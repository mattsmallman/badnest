"""The Bad Nest integration."""
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_USER_ID, CONF_ACCESS_TOKEN, CONF_REGION
from .api import NestAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Bad Nest component."""
    hass.data[DOMAIN] = {}
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bad Nest from a config entry."""
    try:
        api = NestAPI(
            user_id=entry.data[CONF_USER_ID],
            access_token=entry.data[CONF_ACCESS_TOKEN],
            region=entry.data[CONF_REGION],
        )
        
        # Test the connection and update initial data
        await hass.async_add_executor_job(api.update)
        
        hass.data[DOMAIN][entry.entry_id] = {
            "api": api
        }
        
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        return True
        
    except Exception as err:
        _LOGGER.error("Error setting up Bad Nest integration: %s", err)
        return False

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok
