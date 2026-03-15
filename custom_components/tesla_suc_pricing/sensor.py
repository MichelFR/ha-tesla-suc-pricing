"""Sensor platform for Tesla Supercharger Pricing."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import TeslaSuperchargerCoordinator
from .const import DOMAIN, SENSOR_MEMBER_PRICE, SENSOR_PUBLIC_PRICE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tesla Supercharger Pricing sensors from a config entry."""
    coordinator: TeslaSuperchargerCoordinator = entry.runtime_data

    entities = [
        TeslaSucPricingSensor(coordinator, entry, SENSOR_MEMBER_PRICE),
        TeslaSucPricingSensor(coordinator, entry, SENSOR_PUBLIC_PRICE),
        TeslaSucLastUpdateSensor(coordinator, entry),
        TeslaSucCongestionSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class TeslaSucPricingSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tesla Supercharger pricing sensor."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None  # Monetary sensors should not have state_class

    def __init__(
        self,
        coordinator: TeslaSuperchargerCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._unsub_update = None
        
        # Set sensor name based on type
        if sensor_type == SENSOR_MEMBER_PRICE:
            self._attr_name = "Member Price"
            self._attr_translation_key = "member_price"
        else:
            self._attr_name = "Public Charging Price"
            self._attr_translation_key = "public_price"
        
        # Device info
        location_name = coordinator.data.get("location_name", "Unknown Location")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Tesla Supercharger - {location_name}",
            manufacturer="Tesla",
            model="Supercharger",
            configuration_url=f"https://www.tesla.com/findus/location/supercharger/{coordinator.location_slug}",
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._schedule_next_update()

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        if self._unsub_update:
            self._unsub_update()
        await super().async_will_remove_from_hass()

    def _schedule_next_update(self) -> None:
        """Schedule the next update at the next price change time."""
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

        next_update = self._get_next_price_change_time()
        if next_update:
            _LOGGER.debug(
                "Scheduling next price update for %s at %s",
                self._sensor_type,
                next_update,
            )
            self._unsub_update = async_track_point_in_time(
                self.hass, self._handle_scheduled_update, next_update
            )

    @callback
    def _handle_scheduled_update(self, now: datetime) -> None:
        """Handle scheduled update when price period changes."""
        _LOGGER.info(
            "Time-based price period changed for %s, updating sensor",
            self._sensor_type,
        )
        self.async_write_ha_state()
        self._schedule_next_update()

    def _get_next_price_change_time(self) -> datetime | None:
        """Get the next time when the price will change based on time-of-use schedule."""
        if not self.coordinator.data:
            return None

        prices = (
            self.coordinator.data.get("member_prices", [])
            if self._sensor_type == SENSOR_MEMBER_PRICE
            else self.coordinator.data.get("public_prices", [])
        )

        # Get current time in local timezone
        now = dt_util.now()
        current_time = now.time()
        current_weekday = now.weekday()  # Monday = 0, Sunday = 6
        
        # Convert to Tesla's day format (Sunday = 0, Saturday = 6)
        current_day = (current_weekday + 1) % 7

        next_change_times = []

        for price in prices:
            if not price.get("is_tou"):
                continue

            start_time = price.get("start_time")
            end_time = price.get("end_time")
            days_str = price.get("days", "")

            if not start_time or not days_str:
                continue

            # Parse days
            applicable_days = [int(d) for d in days_str.split(",") if d.strip()]
            
            # Check if this price applies today
            if current_day in applicable_days:
                # Parse start time
                try:
                    hour, minute = map(int, start_time.split(":"))
                    start_dt_time = time(hour, minute)
                    
                    # If the start time is in the future today, that's our next change
                    if current_time < start_dt_time:
                        next_change = now.replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                        next_change_times.append(next_change)
                except (ValueError, AttributeError):
                    continue

            # Check for start times tomorrow and in the next 7 days
            for days_ahead in range(1, 8):
                future_date = now + timedelta(days=days_ahead)
                future_weekday = future_date.weekday()
                future_day = (future_weekday + 1) % 7

                if future_day in applicable_days:
                    try:
                        hour, minute = map(int, start_time.split(":"))
                        next_change = future_date.replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                        next_change_times.append(next_change)
                        break  # Only need the first occurrence
                    except (ValueError, AttributeError):
                        continue

        # Return the earliest next change time
        if next_change_times:
            return min(next_change_times)

        return None

    def _get_current_price(self) -> float | None:
        """Get the current applicable price based on time-of-use schedule."""
        if not self.coordinator.data:
            return None

        prices = (
            self.coordinator.data.get("member_prices", [])
            if self._sensor_type == SENSOR_MEMBER_PRICE
            else self.coordinator.data.get("public_prices", [])
        )

        # Get current time in local timezone
        now = dt_util.now()
        current_time = now.time()
        current_weekday = now.weekday()  # Monday = 0, Sunday = 6
        
        # Convert to Tesla's day format (Sunday = 0, Saturday = 6)
        current_day = (current_weekday + 1) % 7

        # Find applicable time-of-use price
        for price in prices:
            if not price.get("is_tou"):
                continue

            start_time = price.get("start_time")
            end_time = price.get("end_time")
            days_str = price.get("days", "")

            if not start_time or not end_time or not days_str:
                continue

            # Parse days
            applicable_days = [int(d) for d in days_str.split(",") if d.strip()]
            
            if current_day not in applicable_days:
                continue

            # Parse times
            try:
                start_hour, start_minute = map(int, start_time.split(":"))
                end_hour, end_minute = map(int, end_time.split(":"))
                
                start_dt_time = time(start_hour, start_minute)
                end_dt_time = time(end_hour, end_minute)

                # Handle time ranges that cross midnight
                if start_dt_time <= end_dt_time:
                    # Normal range (e.g., 08:00 to 23:00)
                    if start_dt_time <= current_time < end_dt_time:
                        return price.get("rate")
                else:
                    # Crosses midnight (e.g., 23:00 to 04:00)
                    if current_time >= start_dt_time or current_time < end_dt_time:
                        return price.get("rate")
            except (ValueError, AttributeError):
                continue

        # Fall back to base rate (non-TOU price)
        for price in prices:
            if not price.get("is_tou"):
                return price.get("rate")

        # If no base rate, return the first available price
        if prices:
            return prices[0].get("rate")

        return None

    @property
    def native_value(self) -> float | None:
        """Return the current price based on time-of-use schedule."""
        return self._get_current_price()

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        if not self.coordinator.data:
            return None

        prices = (
            self.coordinator.data.get("member_prices", [])
            if self._sensor_type == SENSOR_MEMBER_PRICE
            else self.coordinator.data.get("public_prices", [])
        )

        if prices:
            currency = prices[0].get("currency", "EUR")
            unit = prices[0].get("unit", "kwh")
            return f"{currency}/{unit}"
        
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        prices = (
            self.coordinator.data.get("member_prices", [])
            if self._sensor_type == SENSOR_MEMBER_PRICE
            else self.coordinator.data.get("public_prices", [])
        )

        attributes = {
            "location": self.coordinator.data.get("location_name"),
            "address": self._format_address(self.coordinator.data.get("location_address", {})),
            "last_update": self.coordinator.last_successful_update.isoformat() if self.coordinator.last_successful_update else None,
        }

        # Add current time info
        now = dt_util.now()
        attributes["current_time"] = now.strftime("%H:%M")
        
        # Add next price change time
        next_change = self._get_next_price_change_time()
        if next_change:
            attributes["next_price_change"] = next_change.strftime("%Y-%m-%d %H:%M:%S")
            
            # Find what the next price will be
            next_price = self._get_price_at_time(next_change + timedelta(seconds=1))
            if next_price:
                attributes["next_price_rate"] = next_price

        # Add time-based pricing details
        time_ranges = []
        for price in prices:
            if price.get("is_tou"):
                time_range = {
                    "rate": price.get("rate"),
                    "start_time": price.get("start_time"),
                    "end_time": price.get("end_time"),
                    "days": self._format_days(price.get("days", "")),
                }
                time_ranges.append(time_range)
        
        if time_ranges:
            attributes["time_based_pricing"] = time_ranges
        
        # Add base rate if it exists
        for price in prices:
            if not price.get("is_tou"):
                attributes["base_rate"] = price.get("rate")
                break

        return attributes

    def _get_price_at_time(self, target_time: datetime) -> float | None:
        """Get the price that will be active at a specific time."""
        if not self.coordinator.data:
            return None

        prices = (
            self.coordinator.data.get("member_prices", [])
            if self._sensor_type == SENSOR_MEMBER_PRICE
            else self.coordinator.data.get("public_prices", [])
        )

        target_time_only = target_time.time()
        target_weekday = target_time.weekday()
        target_day = (target_weekday + 1) % 7

        # Find applicable time-of-use price
        for price in prices:
            if not price.get("is_tou"):
                continue

            start_time = price.get("start_time")
            end_time = price.get("end_time")
            days_str = price.get("days", "")

            if not start_time or not end_time or not days_str:
                continue

            # Parse days
            applicable_days = [int(d) for d in days_str.split(",") if d.strip()]
            
            if target_day not in applicable_days:
                continue

            # Parse times
            try:
                start_hour, start_minute = map(int, start_time.split(":"))
                end_hour, end_minute = map(int, end_time.split(":"))
                
                start_dt_time = time(start_hour, start_minute)
                end_dt_time = time(end_hour, end_minute)

                if start_dt_time <= end_dt_time:
                    if start_dt_time <= target_time_only < end_dt_time:
                        return price.get("rate")
                else:
                    if target_time_only >= start_dt_time or target_time_only < end_dt_time:
                        return price.get("rate")
            except (ValueError, AttributeError):
                continue

        # Fall back to base rate
        for price in prices:
            if not price.get("is_tou"):
                return price.get("rate")

        return None

    @staticmethod
    def _format_address(address: dict[str, Any]) -> str:
        """Format address dictionary into a string."""
        if not address:
            return "Unknown"
        
        parts = []
        if street := address.get("street"):
            parts.append(street)
            if street_number := address.get("streetNumber"):
                parts[-1] = f"{street} {street_number}"
        
        if city := address.get("city"):
            postal_code = address.get("postalCode", "")
            parts.append(f"{postal_code} {city}".strip())
        
        if country := address.get("country"):
            parts.append(country)
        
        return ", ".join(parts)

    @staticmethod
    def _format_days(days_str: str) -> str:
        """Format days string into human-readable format."""
        if not days_str:
            return "All days"
        
        day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        day_indices = [int(d) for d in days_str.split(",") if d.strip()]
        
        if len(day_indices) == 7:
            return "All days"
        
        return ", ".join(day_names[i] for i in day_indices if i < len(day_names))


class TeslaSucLastUpdateSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing when the pricing data was last updated."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: TeslaSuperchargerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the last update sensor."""
        super().__init__(coordinator)
        
        self._attr_name = "Last Update"
        self._attr_unique_id = f"{entry.entry_id}_last_update"
        self._attr_translation_key = "last_update"
        
        # Device info
        location_name = coordinator.data.get("location_name", "Unknown Location")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Tesla Supercharger - {location_name}",
            manufacturer="Tesla",
            model="Supercharger",
            configuration_url=f"https://www.tesla.com/findus/location/supercharger/{coordinator.location_slug}",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the last update timestamp."""
        return self.coordinator.last_successful_update


class TeslaSucCongestionSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing current congestion level at the Supercharger."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:car-multiple"
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: TeslaSuperchargerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the congestion sensor."""
        super().__init__(coordinator)
        
        self._attr_name = "Congestion"
        self._attr_unique_id = f"{entry.entry_id}_congestion"
        self._attr_translation_key = "congestion"
        self._unsub_update = None
        
        # Device info
        location_name = coordinator.data.get("location_name", "Unknown Location")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Tesla Supercharger - {location_name}",
            manufacturer="Tesla",
            model="Supercharger",
            configuration_url=f"https://www.tesla.com/findus/location/supercharger/{coordinator.location_slug}",
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._schedule_next_update()

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        if self._unsub_update:
            self._unsub_update()
        await super().async_will_remove_from_hass()

    def _schedule_next_update(self) -> None:
        """Schedule the next update at the top of the next hour."""
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

        # Update at the top of every hour
        now = dt_util.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        
        _LOGGER.debug(
            "Scheduling congestion update for %s at %s",
            self.coordinator.location_slug,
            next_hour,
        )
        
        self._unsub_update = async_track_point_in_time(
            self.hass, self._handle_scheduled_update, next_hour
        )

    @callback
    def _handle_scheduled_update(self, _now: datetime) -> None:
        """Handle scheduled update."""
        self.async_write_ha_state()
        self._schedule_next_update()

    @property
    def native_value(self) -> float | None:
        """Return the current congestion percentage."""
        if not self.coordinator.data:
            return None

        try:
            # Get the raw API data
            # The coordinator.data is already extracted, we need the raw data
            # We'll need to store it or recalculate from coordinator
            availability_profile = self._get_availability_profile()
            
            if not availability_profile:
                return None

            now = dt_util.now()
            day_name = now.strftime("%A").lower()
            hour = now.hour

            # Get congestion values for current day
            day_data = availability_profile.get(day_name, {})
            congestion_values = day_data.get("congestionValue", [])
            
            if hour < len(congestion_values):
                # Convert to percentage (values are 0-1)
                return round(congestion_values[hour] * 100, 0)
            
            return None
            
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Error calculating congestion: %s", err)
            return None

    def _get_availability_profile(self) -> dict | None:
        """Extract availability profile from coordinator raw API data."""
        if not self.coordinator.raw_api_data:
            return None
        
        try:
            location_data = self.coordinator.raw_api_data.get("data", {}).get("data", {})
            availability = location_data.get("availabilityProfile", {})
            return availability.get("availabilityProfile", {})
        except (KeyError, TypeError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return {}

        try:
            availability_profile = self._get_availability_profile()
            if not availability_profile:
                return {}

            now = dt_util.now()
            day_name = now.strftime("%A").lower()
            
            # Get congestion for next few hours
            day_data = availability_profile.get(day_name, {})
            congestion_values = day_data.get("congestionValue", [])
            
            next_hours = []
            for i in range(1, 4):  # Next 3 hours
                hour = (now.hour + i) % 24
                if hour < len(congestion_values):
                    next_hours.append(round(congestion_values[hour] * 100, 0))
            
            return {
                "next_3_hours": next_hours,
            }
        except (KeyError, TypeError, ValueError):
            return {}
