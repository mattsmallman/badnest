"""Diagnostics support for Bad Nest."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_USER_ID

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_USER_ID,
    "name",
    "where_name",
    "app_url",
    "structure_id",
    "serial_number",
    "mac_address",
    "wifi_mac_address",
    "online_id",
}

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    api = hass.data[DOMAIN][entry.entry_id]["api"]

    device_data = {}

    # Collect data for all device types
    if hasattr(api, 'device_data'):
        device_data = api.device_data

    diagnostics_data = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "state": entry.state,
        },
        "device_data": device_data,
    }

    # Redact sensitive data
    return async_redact_data(diagnostics_data, TO_REDACT)
