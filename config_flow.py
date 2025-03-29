"""Config flow for Bad Nest integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_USER_ID,
    CONF_ACCESS_TOKEN,
    CONF_REGION,
)
from .api import NestAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USER_ID): str,
        vol.Required(CONF_ACCESS_TOKEN): str,
        vol.Optional(CONF_REGION, default="us"): str,
    }
)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    api = NestAPI(
        user_id=data[CONF_USER_ID],
        access_token=data[CONF_ACCESS_TOKEN],
        region=data[CONF_REGION],
    )

    try:
        # Force an API call to verify credentials
        await hass.async_add_executor_job(api.update)
    except Exception as err:
        raise CannotConnect from err

    # Return validated data
    return {
        CONF_USER_ID: data[CONF_USER_ID],
        CONF_ACCESS_TOKEN: data[CONF_ACCESS_TOKEN],
        CONF_REGION: data[CONF_REGION],
    }

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bad Nest."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                return self.async_create_entry(
                    title=f"Nest ({info[CONF_REGION]})",
                    data=info,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
