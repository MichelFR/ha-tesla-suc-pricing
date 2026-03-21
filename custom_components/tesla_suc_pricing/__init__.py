"""The Tesla Supercharger Pricing integration."""
from __future__ import annotations

import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TeslaLocationDataResult,
    TeslaSuperchargerApi,
    TeslaSuperchargerApiError,
    TeslaSuperchargerApiRateLimitError,
)
from .const import CACHE_TTL_PRICING, CONF_LOCATION_SLUG, DOMAIN

_LOGGER = logging.getLogger(__name__)
PRICING_UPDATE_INTERVAL = timedelta(seconds=CACHE_TTL_PRICING)
RATE_LIMIT_BACKOFF_INITIAL = timedelta(minutes=15)
RATE_LIMIT_BACKOFF_MAX = timedelta(hours=6)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TeslaSucPricingConfigEntry = ConfigEntry[TeslaSuperchargerCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Tesla Supercharger Pricing integration."""
    hass.data.setdefault(DOMAIN, {})

    async def handle_refresh_cache(call):
        """Handle the service call to clear the API cache."""
        api_instance = hass.data[DOMAIN].get("api")
        if api_instance:
            await api_instance.async_clear_cache()
            _LOGGER.info("Tesla Supercharger cache cleared via service call.")
        else:
            # No running instance - create a temporary API just to clear the store
            temp_api = TeslaSuperchargerApi(hass)
            await temp_api.async_clear_cache()
            _LOGGER.info("Tesla Supercharger cache cleared (no active instance).")

    hass.services.async_register(DOMAIN, "refresh_cache", handle_refresh_cache)
    return True

class TeslaSuperchargerCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Tesla Supercharger pricing data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TeslaSuperchargerApi,
        location_slug: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=PRICING_UPDATE_INTERVAL,
            config_entry=config_entry,
        )
        self.api = api
        self.location_slug = location_slug
        self._last_pricing_data = None
        self.last_successful_update: datetime | None = None
        self.raw_api_data: dict | None = None
        self._rate_limit_backoff_attempts = 0

    def _set_update_interval_for_result(self, result: TeslaLocationDataResult) -> None:
        """Schedule the next refresh relative to the original Tesla fetch time."""
        self._rate_limit_backoff_attempts = 0

        if result.source == "cache":
            remaining_seconds = max(1.0, CACHE_TTL_PRICING - max(0.0, time.time() - result.fetched_at))
            self.update_interval = timedelta(seconds=remaining_seconds)
            return

        self.update_interval = PRICING_UPDATE_INTERVAL

    def _apply_rate_limit_backoff(self, err: TeslaSuperchargerApiRateLimitError) -> None:
        """Increase retry delay after Tesla rate limiting."""
        self._rate_limit_backoff_attempts += 1
        backoff_seconds = min(
            RATE_LIMIT_BACKOFF_MAX.total_seconds(),
            RATE_LIMIT_BACKOFF_INITIAL.total_seconds() * (2 ** (self._rate_limit_backoff_attempts - 1)),
        )
        self.update_interval = timedelta(seconds=backoff_seconds)
        _LOGGER.warning(
            "Rate limited for %s; retrying in %s (attempt %d): %s",
            self.location_slug,
            self.update_interval,
            self._rate_limit_backoff_attempts,
            err,
        )

    def _apply_location_result(self, result: TeslaLocationDataResult) -> dict[str, Any]:
        """Apply the API/cache result to coordinator state."""
        self._set_update_interval_for_result(result)
        self.raw_api_data = result.data

        new_data = TeslaSuperchargerApi.extract_pricing_data(result.data)

        if self._last_pricing_data is not None:
            if self._pricing_data_changed(self._last_pricing_data, new_data):
                _LOGGER.info("Pricing data changed for %s, updating sensors", self.location_slug)
            else:
                _LOGGER.debug("No pricing changes detected for %s", self.location_slug)

        self._last_pricing_data = new_data
        self.last_successful_update = datetime.fromtimestamp(result.fetched_at, tz=timezone.utc)
        return new_data

    async def _async_fetch_pricing_data(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch and apply Tesla pricing data."""
        result = await self.api.async_get_location_data(
            self.location_slug,
            force_refresh=force_refresh,
        )
        return self._apply_location_result(result)

    async def _async_update_data(self):
        """Fetch data from Tesla API."""
        try:
            return await self._async_fetch_pricing_data()
        except TeslaSuperchargerApiRateLimitError as err:
            self._apply_rate_limit_backoff(err)
            raise UpdateFailed(f"Error reading location data: {err}") from err
        except TeslaSuperchargerApiError as err:
            raise UpdateFailed(f"Error reading location data: {err}") from err

    async def async_manual_refresh(self) -> None:
        """Force a live Tesla API refresh and reset the 24-hour cache window."""
        try:
            async with self._debounced_refresh.async_lock():
                new_data = await self._async_fetch_pricing_data(force_refresh=True)
                self.async_set_updated_data(new_data)
        except TeslaSuperchargerApiRateLimitError as err:
            self._apply_rate_limit_backoff(err)
            raise UpdateFailed(f"Error reading location data: {err}") from err
        except TeslaSuperchargerApiError as err:
            raise UpdateFailed(f"Error reading location data: {err}") from err

    def _pricing_data_changed(self, old_data: dict, new_data: dict) -> bool:
        """Check if pricing data has changed."""
        # Compare member prices
        old_member = old_data.get("member_prices", [])
        new_member = new_data.get("member_prices", [])
        
        if self._prices_different(old_member, new_member):
            return True
        
        # Compare public prices
        old_public = old_data.get("public_prices", [])
        new_public = new_data.get("public_prices", [])
        
        if self._prices_different(old_public, new_public):
            return True
        
        return False

    @staticmethod
    def _prices_different(old_prices: list, new_prices: list) -> bool:
        """Compare two price lists for differences."""
        if len(old_prices) != len(new_prices):
            return True
        
        # Compare each price entry
        for old_price, new_price in zip(old_prices, new_prices):
            if old_price.get("rate") != new_price.get("rate"):
                return True
            if old_price.get("start_time") != new_price.get("start_time"):
                return True
            if old_price.get("end_time") != new_price.get("end_time"):
                return True
        
        return False


async def async_setup_entry(hass: HomeAssistant, entry: TeslaSucPricingConfigEntry) -> bool:
    """Set up Tesla Supercharger Pricing from a config entry."""
    # Ensure domain data exists
    hass.data.setdefault(DOMAIN, {})
    
    # Create or get shared API instance
    if "api" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["api"] = TeslaSuperchargerApi(hass)
        
    api = hass.data[DOMAIN]["api"]
    api.add_reference()
    
    # Coordinator refetches pricing data from Tesla API every 24 hours
    # Sensors update themselves based on time-of-use schedules
    coordinator = TeslaSuperchargerCoordinator(
        hass,
        api,
        entry.data[CONF_LOCATION_SLUG],
        entry,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TeslaSucPricingConfigEntry) -> bool:
    """Unload a config entry."""
    # Close API session
    coordinator = entry.runtime_data
    await coordinator.api.async_close()
    
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
