"""Tesla Supercharger API client - Fetches from Tesla's API."""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant

from .const import (
    FEE_TYPE_CHARGING,
    VEHICLE_TYPE_TESLA,
    VEHICLE_TYPE_NON_TESLA,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.tesla.com/api/findus/get-charger-details"
DEFAULT_LOCALE = "de-DE"


class TeslaSuperchargerApiError(Exception):
    """Base exception for Tesla API errors."""


class TeslaSuperchargerApiConnectionError(TeslaSuperchargerApiError):
    """Exception for connection errors."""


class TeslaSuperchargerApiAuthError(TeslaSuperchargerApiError):
    """Exception for authentication errors."""


class TeslaSuperchargerApiRateLimitError(TeslaSuperchargerApiError):
    """Exception for rate limits (429)."""


class TeslaSuperchargerApi:
    """API client for Tesla Supercharger pricing data - Fetches from Tesla API."""

    def __init__(self, hass: HomeAssistant | None = None) -> None:
        """Initialize the API client."""
        self._hass = hass
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._ref_count = 0

    def add_reference(self) -> None:
        """Increment reference count for shared session."""
        self._ref_count += 1
        _LOGGER.debug("TeslaSuperchargerApi reference count increased to %d", self._ref_count)

    async def async_close(self) -> None:
        """Close the HTTP session when reference count reaches 0."""
        self._ref_count -= 1
        _LOGGER.debug("TeslaSuperchargerApi reference count decreased to %d", self._ref_count)
        
        if self._ref_count <= 0:
            if self._session:
                await self._session.close()
                self._session = None
                _LOGGER.debug("TeslaSuperchargerApi session closed.")
            self._ref_count = 0

    async def async_get_available_locations(self) -> dict[str, str]:
        """Get list of known location slugs from known_locations.json file."""
        known_locations_file = Path(__file__).parent / "known_locations.json"
        
        if not known_locations_file.exists():
            _LOGGER.warning("Known locations file does not exist: %s", known_locations_file)
            return {}
        
        try:
            # Read the known locations JSON file
            if self._hass:
                # Use async file reading in Home Assistant context
                def _read_json():
                    with open(known_locations_file, encoding="utf-8") as f:
                        return json.load(f)
                
                locations = await self._hass.async_add_executor_job(_read_json)
            else:
                # Sync reading for non-HA context
                with open(known_locations_file, encoding="utf-8") as f:
                    locations = json.load(f)
            
            _LOGGER.debug("Found %d known location slugs", len(locations))
            return locations
            
        except Exception as err:
            _LOGGER.error("Error reading known locations file: %s", err)
            return {}

    async def async_get_location_data(self, location_slug: str, locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
        """Get location details from Tesla API."""
        async with self._session_lock:
            if not self._session:
                # Create session with minimal working headers from curl request
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Priority": "u=1, i",
                    "Referer": "https://www.tesla.com/de_de/findus",
                    "Sec-CH-UA": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"macOS"',
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                }
                # Configure SSL context to use TLS 1.2
                ssl_context = ssl.create_default_context()
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
                
                # Start with accepted cookie consent
                cookie_jar = aiohttp.CookieJar()
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                self._session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar, connector=connector)
                
                # First, visit the Tesla homepage to get session cookies
                _LOGGER.debug("Visiting Tesla homepage to establish session")
                try:
                    async with self._session.get("https://www.tesla.com/de_de/", timeout=aiohttp.ClientTimeout(total=30)) as init_response:
                        _LOGGER.debug("Initial homepage status: %s", init_response.status)
                        # Read response to ensure connection is complete
                        await init_response.text()
                        _LOGGER.debug("Session cookies obtained: %s", [f"{c.key}={c.value}" for c in self._session.cookie_jar])
                except Exception as err:
                    _LOGGER.warning("Failed to initialize session from homepage: %s", err)
        
        # Build URL with query parameters directly
        url = f"{BASE_URL}?locationSlug={location_slug}&programType=supercharger&locale={locale}&isInHkMoTw=false"
        
        try:
            _LOGGER.debug("Fetching data from Tesla API: %s", url)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                _LOGGER.debug("Tesla API response status: %s", response.status)
                response.raise_for_status()
                data = await response.json()
                _LOGGER.debug("Tesla API response data keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))
                
                # Check if data has the expected structure
                if not isinstance(data, dict):
                    raise TeslaSuperchargerApiError(
                        f"Invalid data from API for {location_slug}: expected dict, got {type(data)}"
                    )
                
                if "data" not in data:
                    raise TeslaSuperchargerApiError(
                        f"Invalid data from API for {location_slug}: missing 'data' field. Available keys: {list(data.keys())}"
                    )
                
                # Add success field if missing
                if "success" not in data:
                    data["success"] = True
                
                _LOGGER.debug("Successfully fetched location data for %s", location_slug)
                return data
                
        except aiohttp.ClientResponseError as err:
            if err.status == 403:
                raise TeslaSuperchargerApiAuthError(
                    f"Access forbidden (403) for {location_slug}. Tesla may have bot protection active."
                ) from err
            if err.status == 429:
                raise TeslaSuperchargerApiRateLimitError(
                    f"Rate limited (429) for {location_slug}. Too many requests from this IP."
                ) from err
            raise TeslaSuperchargerApiConnectionError(
                f"HTTP error {err.status} fetching {location_slug}: {err.message}"
            ) from err
        except aiohttp.ClientError as err:
            raise TeslaSuperchargerApiConnectionError(
                f"Connection error fetching {location_slug}: {err}"
            ) from err
        except Exception as err:
            raise TeslaSuperchargerApiError(
                f"Unexpected error fetching {location_slug}: {err}"
            ) from err

    async def async_get_location_name(self, location_slug: str, locale: str = DEFAULT_LOCALE) -> str:
        """Fetch the display name for a location slug dynamically."""
        async with self._session_lock:
            if not self._session:
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                }
                ssl_context = ssl.create_default_context()
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                cookie_jar = aiohttp.CookieJar()
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                self._session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar, connector=connector)

        # Replace hyphens with underscores in locale to match user example (de_DE vs de-DE)
        api_locale = locale.replace("-", "_")
        url = f"https://www.tesla.com/api/findus/get-location-details?locationSlug={location_slug}&functionTypes=party&locale={api_locale}&isInHkMoTw=false"

        try:
            _LOGGER.debug("Fetching location details for name: %s", url)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                data = await response.json()
                
                marketing = data.get("data", {}).get("marketing", {})
                if marketing and "display_name" in marketing:
                    return marketing["display_name"]
                
                functions = data.get("data", {}).get("functions", [])
                if functions and len(functions) > 0 and "customer_facing_name" in functions[0]:
                    return functions[0]["customer_facing_name"]
                
                # Fallback to slug titleized
                return location_slug.replace("-", " ").replace("supercharger", "").title().strip()
                
        except Exception as err:
            _LOGGER.warning("Could not fetch explicit location name for %s: %s", location_slug, err)
            return location_slug.replace("-", " ").replace("supercharger", "").title().strip()

    @staticmethod
    def extract_pricing_data(api_response: dict[str, Any]) -> dict[str, Any]:
        """Extract and organize pricing data from API response."""
        try:
            location_data = api_response.get("data", {}).get("data", {})
            pricebooks = location_data.get("effectivePricebooks", [])
            
            # Organize pricing by vehicle type and member status
            member_prices = []
            public_prices = []
            
            for pricebook in pricebooks:
                if pricebook.get("feeType") != FEE_TYPE_CHARGING:
                    continue
                
                price_info = {
                    "rate": pricebook.get("rateBase"),
                    "currency": pricebook.get("currencyCode"),
                    "unit": pricebook.get("uom"),
                    "start_time": pricebook.get("startTime", ""),
                    "end_time": pricebook.get("endTime", ""),
                    "days": pricebook.get("days", ""),
                    "is_tou": pricebook.get("isTou", False),
                    "vehicle_type": pricebook.get("vehicleMakeType"),
                }
                
                # Categorize by member status and vehicle type
                if pricebook.get("isMemberPricebook"):
                    if pricebook.get("vehicleMakeType") == VEHICLE_TYPE_TESLA:
                        member_prices.append(price_info)
                else:
                    if pricebook.get("vehicleMakeType") == VEHICLE_TYPE_NON_TESLA:
                        public_prices.append(price_info)
            
            return {
                "location_name": location_data.get("name", "Unknown"),
                "location_address": location_data.get("address", {}),
                "member_prices": member_prices,
                "public_prices": public_prices,
            }
            
        except (KeyError, TypeError) as err:
            _LOGGER.error("Error extracting pricing data: %s", err)
            raise TeslaSuperchargerApiError(f"Failed to extract pricing data: {err}") from err
