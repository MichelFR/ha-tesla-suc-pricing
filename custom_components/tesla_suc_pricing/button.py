"""Button platform for Tesla Supercharger Pricing integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TeslaSuperchargerCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tesla Supercharger Pricing button entities."""
    coordinator: TeslaSuperchargerCoordinator = entry.runtime_data
    
    async_add_entities([TeslaSucRefreshButton(coordinator, entry)])


class TeslaSucRefreshButton(CoordinatorEntity[TeslaSuperchargerCoordinator], ButtonEntity):
    """Button to manually refresh pricing data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TeslaSuperchargerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._attr_name = "Refresh"
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_icon = "mdi:refresh"
        self._attr_translation_key = "refresh"
        
        location_name = coordinator.data.get("location_name", "Unknown Location")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Tesla Supercharger - {location_name}",
            "manufacturer": "Tesla",
            "model": "Supercharger",
        }

    async def async_press(self) -> None:
        """Handle the button press to refresh data."""
        _LOGGER.info("Manual refresh requested for %s", self.coordinator.location_slug)
        await self.coordinator.async_request_refresh()
