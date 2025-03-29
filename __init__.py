"""The Bad Nest integration."""
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_USER_ID,
    CONF_ACCESS_TOKEN,
    CONF_REGION,
)
from .api import NestAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.WATER_HEATER,
    Platform.CAMERA,
    Platform.SWITCH,
    Platform.DIAGNOSTICS,
]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USER_ID): cv.string,
                vol.Required(CONF_ACCESS_TOKEN): cv.string,
                vol.Optional(CONF_REGION, default="us"): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Bad Nest component."""
    hass.data[DOMAIN] = {}

    if DOMAIN not in config:
        return True

    # If user has YAML config, create a config entry from it
    user_input = dict(config[DOMAIN])
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "import"},
            data=user_input,
        )
    )

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bad Nest from a config entry."""
    try:
        api = NestAPI(
            user_id=entry.data[CONF_USER_ID],
            access_token=entry.data[CONF_ACCESS_TOKEN],
            issue_token=None,  # Not using Google auth
            cookie=None,       # Not using Google auth
            region=entry.data[CONF_REGION],
        )
        
        # Initialize API
        await api._create_session()
        await api.login()
        await api._get_devices()
        await api.update()
        
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
        api = hass.data[DOMAIN][entry.entry_id]["api"]
        await api.close()
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok
