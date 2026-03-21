"""Tesla Supercharger API client - Fetches from Tesla's API."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import ssl
import time
from typing import Any, Literal

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.location import distance

from .const import (
    FEE_TYPE_CHARGING,
    VEHICLE_TYPE_TESLA,
    VEHICLE_TYPE_NON_TESLA,
    STORAGE_KEY_LOCATIONS,
    STORAGE_KEY_DETAILS,
    STORAGE_KEY_PRICING,
    STORAGE_VERSION,
    CACHE_TTL_LOCATIONS,
    CACHE_TTL_DETAILS,
    CACHE_TTL_PRICING,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.tesla.com/api/findus/get-charger-details"
LOCATIONS_URL = "https://www.tesla.com/api/findus/get-locations"
DETAILS_URL = "https://www.tesla.com/api/findus/get-location-details"
DEFAULT_LOCALE = "de-DE"
FetchSource = Literal["api", "cache", "stale_cache"]


@dataclass(slots=True)
class TeslaLocationDataResult:
    """Raw Tesla location payload plus cache metadata."""

    data: dict[str, Any]
    source: FetchSource
    fetched_at: float


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
        
        self._store_locations: Store | None = None
        self._store_details: Store | None = None
        self._store_pricing: Store | None = None
        
        if hass:
            self._store_locations = Store(hass, STORAGE_VERSION, STORAGE_KEY_LOCATIONS)
            self._store_details = Store(hass, STORAGE_VERSION, STORAGE_KEY_DETAILS)
            self._store_pricing = Store(hass, STORAGE_VERSION, STORAGE_KEY_PRICING)

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

    async def _ensure_session(self) -> None:
        """Ensure the aiohttp session is initialized and valid."""
        async with self._session_lock:
            if not self._session:
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
                ssl_context = ssl.create_default_context()
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
                
                cookie_jar = aiohttp.CookieJar()
                connector = aiohttp.TCPConnector(ssl=ssl_context)
                self._session = aiohttp.ClientSession(headers=headers, cookie_jar=cookie_jar, connector=connector)
                
                _LOGGER.debug("Visiting Tesla homepage to establish session")
                try:
                    async with self._session.get("https://www.tesla.com/de_de/", timeout=aiohttp.ClientTimeout(total=30)) as init_response:
                        await init_response.text()
                except Exception as err:
                    _LOGGER.warning("Failed to initialize session from homepage: %s", err)

    async def async_clear_cache(self) -> None:
        """Clear the cached Tesla API data."""
        if self._store_locations:
            await self._store_locations.async_save({})
        if self._store_details:
            await self._store_details.async_save({})
        if self._store_pricing:
            await self._store_pricing.async_save({})
        _LOGGER.info("Tesla Supercharger cache manually cleared.")

    @staticmethod
    def _validate_location_data(location_slug: str, data: Any) -> dict[str, Any]:
        """Validate a Tesla location payload and normalize optional fields."""
        if not isinstance(data, dict):
            raise TeslaSuperchargerApiError(
                f"Invalid data from API for {location_slug}: expected dict, got {type(data)}"
            )

        if "data" not in data:
            raise TeslaSuperchargerApiError(
                f"Invalid data from API for {location_slug}: missing 'data' field. Available keys: {list(data.keys())}"
            )

        if "success" not in data:
            data = dict(data)
            data["success"] = True

        return data

    def _get_cached_location_data(
        self,
        location_slug: str,
        cache_data: dict[str, Any],
        current_time: float,
        *,
        allow_stale: bool,
    ) -> TeslaLocationDataResult | None:
        """Return cached pricing data if available."""
        entry = cache_data.get(location_slug)
        if not isinstance(entry, dict):
            return None

        timestamp = entry.get("timestamp")
        response = entry.get("response")
        if not isinstance(timestamp, (int, float)) or response is None:
            return None

        try:
            payload = self._validate_location_data(location_slug, response)
        except TeslaSuperchargerApiError as err:
            _LOGGER.warning("Ignoring invalid cached pricing data for %s: %s", location_slug, err)
            return None

        age = current_time - float(timestamp)
        if age < CACHE_TTL_PRICING:
            return TeslaLocationDataResult(payload, "cache", float(timestamp))

        if allow_stale:
            return TeslaLocationDataResult(payload, "stale_cache", float(timestamp))

        return None

    def _maybe_use_stale_cached_location_data(
        self,
        location_slug: str,
        cache_data: dict[str, Any],
        current_time: float,
        err: Exception,
        *,
        force_refresh: bool,
    ) -> TeslaLocationDataResult | None:
        """Return stale cached pricing data for automatic refresh failures."""
        if force_refresh:
            return None

        cached_result = self._get_cached_location_data(
            location_slug,
            cache_data,
            current_time,
            allow_stale=True,
        )
        if cached_result and cached_result.source == "stale_cache":
            _LOGGER.warning(
                "Using stale cached pricing data for %s after live fetch failed: %s",
                location_slug,
                err,
            )
            return cached_result

        return None

    async def async_get_closest_superchargers(self, lat: float, lon: float, country: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Fetch closest superchargers by coordinates, utilizing 14-day cache."""
        cache_data = {}
        if self._store_locations:
            cache_data = await self._store_locations.async_load() or {}
            
        current_time = time.time()
        locations = []
        
        # Check cache
        if country in cache_data and "timestamp" in cache_data[country] and "locations" in cache_data[country]:
            if current_time - cache_data[country]["timestamp"] < CACHE_TTL_LOCATIONS:
                _LOGGER.debug("Using cached locations map for %s (%d entries)", country, len(cache_data[country]["locations"]))
                locations = cache_data[country]["locations"]
        
        # Fetch if Cache miss
        if not locations:
            await self._ensure_session()
            url = f"{LOCATIONS_URL}?country={country}&view=map"
            
            try:
                _LOGGER.debug("Fetching locations map from API: %s", url)
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=45)) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                    raw_list = data.get("data", {}).get("data", [])
                    _LOGGER.info("Tesla API returned %d total locations for country=%s", len(raw_list), country)
                    
                    # Extract superchargers: match by type OR presence of supercharger_function block
                    for loc in raw_list:
                        is_suc = "supercharger" in loc.get("location_type", [])
                        has_func = "supercharger_function" in loc
                        has_slug = "location_url_slug" in loc

                        if (is_suc or has_func) and has_slug:
                            locations.append(loc)
                    
                    _LOGGER.info("Filtered to %d supercharger locations for country=%s", len(locations), country)
                    
                    # Save to cache (even if empty, so we don't hammer the API)
                    cache_data[country] = {
                        "timestamp": current_time,
                        "locations": locations
                    }
                    if self._store_locations:
                        await self._store_locations.async_save(cache_data)
            except aiohttp.ClientResponseError as err:
                if err.status == 403:
                    raise TeslaSuperchargerApiAuthError(
                        f"Access forbidden (403) for {country} locations. Tesla may have bot protection active."
                    ) from err
                if err.status == 429:
                    raise TeslaSuperchargerApiRateLimitError(
                        f"Rate limited (429) for {country} locations. Too many requests from this IP."
                    ) from err
                raise TeslaSuperchargerApiConnectionError(
                    f"HTTP error {err.status} fetching {country} locations: {err.message}"
                ) from err
            except aiohttp.ClientError as err:
                raise TeslaSuperchargerApiConnectionError(
                    f"Connection error fetching {country} locations: {err}"
                ) from err
            except Exception as err:
                _LOGGER.error("Failed to fetch superchargers map: %s", err)
                raise TeslaSuperchargerApiError(f"Failed to fetch locations for {country}") from err
                
        # Calculate distances on a separate list of simple dicts/copies to avoid mutating cache
        results = []
        for loc in locations:
            try:
                # Root level latitude/longitude are preferred if they exist
                # Otherwise fallback to supercharger_function values
                loc_lat = loc.get("latitude")
                loc_lon = loc.get("longitude")
                
                if loc_lat is None or loc_lon is None:
                    func = loc.get("supercharger_function", {})
                    loc_lat = func.get("actual_latitude")
                    loc_lon = func.get("actual_longitude")
                
                if loc_lat is None or loc_lon is None:
                    continue
                    
                dist_km = distance(lat, lon, float(loc_lat), float(loc_lon)) / 1000.0
                
                results.append({
                    "location_url_slug": loc["location_url_slug"],
                    "latitude": float(loc_lat),
                    "longitude": float(loc_lon),
                    "distance_km": dist_km
                })
            except (ValueError, TypeError):
                continue
            
        # Sort results by distance and return top X
        results.sort(key=lambda x: x["distance_km"])
        return results[:max_results]

    async def async_get_location_data(
        self,
        location_slug: str,
        locale: str = DEFAULT_LOCALE,
        *,
        force_refresh: bool = False,
    ) -> TeslaLocationDataResult:
        """Get location details for pricing from Tesla API or persistent cache."""
        cache_data = {}
        if self._store_pricing:
            cache_data = await self._store_pricing.async_load() or {}

        current_time = time.time()
        if not force_refresh:
            cached_result = self._get_cached_location_data(
                location_slug,
                cache_data,
                current_time,
                allow_stale=False,
            )
            if cached_result:
                _LOGGER.debug("Using cached pricing data for %s", location_slug)
                return cached_result

        await self._ensure_session()

        url = f"{BASE_URL}?locationSlug={location_slug}&programType=supercharger&locale={locale}&isInHkMoTw=false"

        try:
            _LOGGER.debug("Fetching data from Tesla API: %s", url)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                _LOGGER.debug("Tesla API response status: %s", response.status)
                response.raise_for_status()
                data = await response.json()
                _LOGGER.debug("Tesla API response data keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))

                data = self._validate_location_data(location_slug, data)
                fetched_at = time.time()

                cache_data[location_slug] = {
                    "timestamp": fetched_at,
                    "response": data,
                }
                if self._store_pricing:
                    await self._store_pricing.async_save(cache_data)

                _LOGGER.debug("Successfully fetched location data for %s", location_slug)
                return TeslaLocationDataResult(data, "api", fetched_at)

        except aiohttp.ClientResponseError as err:
            stale_result = self._maybe_use_stale_cached_location_data(
                location_slug,
                cache_data,
                current_time,
                err,
                force_refresh=force_refresh,
            )
            if stale_result:
                return stale_result

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
            stale_result = self._maybe_use_stale_cached_location_data(
                location_slug,
                cache_data,
                current_time,
                err,
                force_refresh=force_refresh,
            )
            if stale_result:
                return stale_result

            raise TeslaSuperchargerApiConnectionError(
                f"Connection error fetching {location_slug}: {err}"
            ) from err
        except Exception as err:
            stale_result = self._maybe_use_stale_cached_location_data(
                location_slug,
                cache_data,
                current_time,
                err,
                force_refresh=force_refresh,
            )
            if stale_result:
                return stale_result

            raise TeslaSuperchargerApiError(
                f"Unexpected error fetching {location_slug}: {err}"
            ) from err

    async def async_get_location_name(self, location_slug: str, locale: str = DEFAULT_LOCALE) -> str:
        """Fetch the display name for a location slug dynamically (with 1 day cache)."""
        cache_data = {}
        if self._store_details:
            cache_data = await self._store_details.async_load() or {}
            
        current_time = time.time()
        
        # Check cache
        if location_slug in cache_data and "timestamp" in cache_data[location_slug] and "name" in cache_data[location_slug]:
            if current_time - cache_data[location_slug]["timestamp"] < CACHE_TTL_DETAILS:
                return cache_data[location_slug]["name"]

        await self._ensure_session()

        # Replace hyphens with underscores in locale to match user example (de_DE vs de-DE)
        api_locale = locale.replace("-", "_")
        url = f"{DETAILS_URL}?locationSlug={location_slug}&functionTypes=party&locale={api_locale}&isInHkMoTw=false"

        name = location_slug.replace("-", " ").replace("supercharger", "").title().strip()
        
        try:
            _LOGGER.debug("Fetching location details for name: %s", url)
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                data = await response.json()
                
                marketing = data.get("data", {}).get("marketing", {})
                if marketing and "display_name" in marketing:
                    name = marketing["display_name"]
                else:
                    functions = data.get("data", {}).get("functions", [])
                    if functions and len(functions) > 0 and "customer_facing_name" in functions[0]:
                        name = functions[0]["customer_facing_name"]
                
        except Exception as err:
            _LOGGER.warning("Could not fetch explicit location name for %s: %s", location_slug, err)
            
        # Save to cache regardless of whether it was perfectly fetched or falling back to slug
        cache_data[location_slug] = {
            "timestamp": current_time,
            "name": name
        }
        if self._store_details:
            await self._store_details.async_save(cache_data)
            
        return name

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
