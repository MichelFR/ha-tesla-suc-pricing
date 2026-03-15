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
)
from .const import (
    CONF_LOCALE,
    CONF_LOCATION_SLUG,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOCALE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SCAN_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = TeslaSuperchargerApi(hass)

    try:
        # Test reading the location file
        result = await api.async_get_location_data(data[CONF_LOCATION_SLUG])
        
        pricing_data = TeslaSuperchargerApi.extract_pricing_data(result)
        
        return {
            "title": pricing_data["location_name"],
            "location_slug": data[CONF_LOCATION_SLUG],
        }
    finally:
        # Always close the session after validation
        await api.async_close()


class TeslaSucPricingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tesla Supercharger Pricing."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        # Get available locations from known_locations.json
        api = TeslaSuperchargerApi(self.hass)
        available_locations = await api.async_get_available_locations()
        _LOGGER.info("Found %d location(s): %s", len(available_locations), list(available_locations.keys()))

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Set unique ID based on location slug
                await self.async_set_unique_id(user_input[CONF_LOCATION_SLUG])
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_LOCATION_SLUG: user_input[CONF_LOCATION_SLUG],
                        CONF_NAME: info["title"],
                    },
                )
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

