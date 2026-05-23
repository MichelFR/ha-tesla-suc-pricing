"""Binary sensor platform for Tesla Supercharger Pricing integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TeslaSuperchargerCoordinator
from .const import BINARY_SENSOR_STALE_CACHE_IN_USE, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tesla Supercharger Pricing binary sensors."""
    coordinator: TeslaSuperchargerCoordinator = entry.runtime_data

    async_add_entities([TeslaSucStaleCacheInUseBinarySensor(coordinator, entry)])


class TeslaSucStaleCacheInUseBinarySensor(
    CoordinatorEntity[TeslaSuperchargerCoordinator], BinarySensorEntity
):
    """Binary sensor that is on when pricing is being served from stale cache."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:database-clock-outline"

    def __init__(
        self,
        coordinator: TeslaSuperchargerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the stale-cache binary sensor."""
        super().__init__(coordinator)
        self._attr_name = "Stale Cache In Use"
        self._attr_unique_id = f"{entry.entry_id}_{BINARY_SENSOR_STALE_CACHE_IN_USE}"
        self._attr_translation_key = BINARY_SENSOR_STALE_CACHE_IN_USE

        location_name = coordinator.data.get("location_name", "Unknown Location")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Tesla Supercharger - {location_name}",
            "manufacturer": "Tesla",
            "model": "Supercharger",
        }

    @property
    def is_on(self) -> bool:
        """Return True when the coordinator is serving stale cached pricing data."""
        return self.coordinator.is_stale_cache_in_use
