"""Support for Nest switches."""
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nest switches from config entry."""
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    switches = []
    _LOGGER.info("Adding switches")
    for switch in api.switches:
        _LOGGER.info(f"Adding nest switch uuid: {switch}")
        if api.device_data[switch].get('indoor_chime', False):
            switches.append(NestChimeSwitch(
                switch,
                api,
                config_entry.entry_id,
            ))

    async_add_entities(switches)

class NestChimeSwitch(SwitchEntity):
    """Implementation of Nest camera indoor chime switch."""

    def __init__(self, device_id: str, api, entry_id: str) -> None:
        """Initialize the switch."""
        self.device_id = device_id
        self.device = api
        self._entry_id = entry_id
        
        # Set unique ID incorporating config entry ID
        self._attr_unique_id = f"{entry_id}_{device_id}_chime"
        
        # Initialize from device data
        device_data = self.device.device_data[device_id]
        self._attr_name = f"{device_data.get('name', '')} Indoor Chime"
        self._attr_is_on = device_data.get('chime_state', False)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Use the same device identifier as the camera
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self.device_id}")},
        )

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        return "mdi:bell" if self.is_on else "mdi:bell-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on indoor chime."""
        await self.device.camera_turn_chime_on(self.device_id)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off indoor chime."""
        await self.device.camera_turn_chime_off(self.device_id)
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the status of the indoor chime."""
        await self.device.update()
        self._attr_is_on = self.device.device_data[self.device_id].get('chime_state', False)
