"""Diagnostics support for Bad Nest."""
from typing import Any

from homeassistant.components import diagnostics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_USER_ID
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_USER_ID,
    "access_token",
    "user_id",
    "cookie",
    "issue_token",
    "software_version",
    "mac_address",
    "serial_number",
    "where_id",
}

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    api = hass.data[DOMAIN][entry.entry_id]["api"]

    # Get device data with sensitive information redacted
    device_data = {
        device_id: {
            k: "**redacted**" if k in TO_REDACT else v
            for k, v in data.items()
        }
        for device_id, data in api.device_data.items()
    }

    # Build diagnostics data
    diagnostics_data = {
        "entry": {
            "title": entry.title,
            "data": diagnostics.async_redact_data(entry.data, TO_REDACT),
        },
        "device_data": device_data,
        "device_counts": {
            "thermostats": len(api.thermostats),
            "temperature_sensors": len(api.temperature_sensors),
            "cameras": len(api.cameras),
            "smoke_detectors": len(api.protects),
            "hot_water_controllers": len(api.hotwatercontrollers),
        },
    }

    return diagnostics_data
