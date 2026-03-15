"""Config flow for Tesla Supercharger Pricing integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .api import (
    TeslaSuperchargerApi,
    TeslaSuperchargerApiConnectionError,
    TeslaSuperchargerApiError,
    TeslaSuperchargerApiRateLimitError,
)
from .const import (
    CONF_LOCALE,
    CONF_LOCATION_SLUG,
    CONF_SCAN_INTERVAL,
    CONF_RADIUS_AMOUNT,
    CONF_COUNTRY,
    DEFAULT_LOCALE,
    DEFAULT_COUNTRY,
    DEFAULT_RADIUS_AMOUNT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SCAN_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


class TeslaSucPricingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tesla Supercharger Pricing."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._custom_slug: str | None = None
        self._custom_name: str | None = None
        self._locations = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - Gathering Coordinates."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.lat = user_input[CONF_LATITUDE]
            self.lon = user_input[CONF_LONGITUDE]
            self.country = user_input[CONF_COUNTRY]
            self.amount = user_input[CONF_RADIUS_AMOUNT]
            return await self.async_step_select()

        # Defaults based on HA config
        default_lat = self.hass.config.latitude
        default_lon = self.hass.config.longitude

        data_schema = vol.Schema(
            {
                vol.Required(CONF_LATITUDE, default=default_lat): vol.Coerce(float),
                vol.Required(CONF_LONGITUDE, default=default_lon): vol.Coerce(float),
                vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): str,
                vol.Required(CONF_RADIUS_AMOUNT, default=DEFAULT_RADIUS_AMOUNT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=10)
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the selection step."""
        errors: dict[str, str] = {}
        api = TeslaSuperchargerApi(self.hass)

        if user_input is not None:
            try:
                location_slug = user_input[CONF_LOCATION_SLUG]
                
                # Verify we have the selected slug
                selected_loc = next((loc for loc in self._locations if loc["slug"] == location_slug), None)
                title = selected_loc["name"] if selected_loc else user_input.get(CONF_LOCATION_SLUG)

                await self.async_set_unique_id(location_slug)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_LOCATION_SLUG: location_slug,
                        CONF_NAME: title,
                    },
                )
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception in select step")
                errors["base"] = "unknown"
            finally:
                await api.async_close()
        
        # Load closest superchargers
        if not self._locations:
            try:
                # 1. Fetch Closest
                closest = await api.async_get_closest_superchargers(
                    self.lat, self.lon, self.country, self.amount
                )
                
                # 2. Fetch Marketing Names dynamically
                locations = []
                for loc in closest:
                    slug = loc.get("location_url_slug")
                    if not slug:
                        continue
                    name = await api.async_get_location_name(slug)
                    
                    dist_km = round(loc.get("distance_km", 0), 1)
                    locations.append({
                        "slug": slug,
                        "name": f"{name} ({dist_km} km)",
                        "distance_km": dist_km
                    })
                    
                self._locations = locations
                
            except TeslaSuperchargerApiError:
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.error("Failed to fetch superchargers: %s", e)
                errors["base"] = "unknown"
            finally:
                await api.async_close()

        if not self._locations and not errors:
            errors["base"] = "no_locations"

        # Build dropdown options
        options = [
            selector.SelectOptionDict(value=loc["slug"], label=loc["name"])
            for loc in self._locations
        ]

        # Add fallback empty schema if errors/no locations found
        if not options:
            return self.async_show_form(
                step_id="select",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_LOCATION_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        custom_value=False,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select",
            data_schema=data_schema,
            errors=errors,
        )


