"""The Tesla Supercharger Pricing integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import TeslaSuperchargerApi, TeslaSuperchargerApiError, TeslaSuperchargerApiAuthError
from .const import CONF_LOCALE, CONF_LOCATION_SLUG, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

type TeslaSucPricingConfigEntry = ConfigEntry[TeslaSuperchargerCoordinator]


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
            update_interval=timedelta(hours=24),  # Refetch data every 24 hours
            config_entry=config_entry,
        )
        self.api = api
        self.location_slug = location_slug
        self._last_pricing_data = None
        self.last_successful_update: datetime | None = None
        self.raw_api_data: dict | None = None

    async def _async_update_data(self):
        """Fetch data from Tesla API."""
        try:
            result = await self.api.async_get_location_data(self.location_slug)
            
            # Store raw API data for congestion sensor
            self.raw_api_data = result
            
            new_data = TeslaSuperchargerApi.extract_pricing_data(result)
            
            # Check if pricing data has actually changed
            if self._last_pricing_data is not None:
                if self._pricing_data_changed(self._last_pricing_data, new_data):
                    _LOGGER.info("Pricing data changed for %s, updating sensors", self.location_slug)
                else:
                    _LOGGER.debug("No pricing changes detected for %s", self.location_slug)
            
            self._last_pricing_data = new_data
            self.last_successful_update = dt_util.now()
            return new_data
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
