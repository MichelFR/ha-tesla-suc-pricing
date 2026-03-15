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
    DEFAULT_LOCALE,
    DEFAULT_LOCATIONS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SCAN_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = TeslaSuperchargerApi(hass)

    try:
        # Test reading the location file to ensure slug is valid/accessible
        result = await api.async_get_location_data(data[CONF_LOCATION_SLUG])
        
        location_slug = data[CONF_LOCATION_SLUG]
        
        # Get the real display name dynamically
        title = await api.async_get_location_name(location_slug)

        return {
            "title": title,
            "location_slug": location_slug,
        }
    finally:
        # Always close the session after validation
        await api.async_close()


class TeslaSucPricingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tesla Supercharger Pricing."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._custom_slug: str | None = None
        self._custom_name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        # Load default locations from constants
        api = TeslaSuperchargerApi(self.hass)
        
        # Initialize dictionary to store dynamically fetched names
        if not hasattr(self, "_available_locations"):
            self._available_locations = {}
            for slug in DEFAULT_LOCATIONS:
                try:
                    name = await api.async_get_location_name(slug)
                    self._available_locations[slug] = name
                except Exception as e:
                    _LOGGER.warning("Could not fetch name for %s: %s", slug, e)
                    self._available_locations[slug] = slug
                    
        available_locations = self._available_locations
        _LOGGER.info("Loaded %d location(s): %s", len(available_locations), list(available_locations.keys()))

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Set unique ID based on location slug
                location_slug = user_input[CONF_LOCATION_SLUG]
                await self.async_set_unique_id(location_slug)
                self._abort_if_unique_id_configured()
                
                # If they manually typed it, present confirmation step
                if location_slug not in available_locations:
                    self._custom_slug = location_slug
                    self._custom_name = info["title"]
                    return await self.async_step_confirm()
                
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_LOCATION_SLUG: location_slug,
                        CONF_NAME: info["title"],
                    },
                )
            except TeslaSuperchargerApiRateLimitError:
                errors["base"] = "rate_limit"
            except TeslaSuperchargerApiConnectionError:
                errors["base"] = "cannot_connect"
            except TeslaSuperchargerApiError:
                errors["base"] = "invalid_location"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # Build select options and create selector
        options = [
            selector.SelectOptionDict(value=slug, label=name)
            for slug, name in available_locations.items()
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_LOCATION_SLUG): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the custom location."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._custom_name,
                data={
                    CONF_LOCATION_SLUG: self._custom_slug,
                    CONF_NAME: self._custom_name,
                },
            )

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._custom_name},
        )


