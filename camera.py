"""Support for Nest cameras."""
import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
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
    """Set up a Nest camera."""
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    cameras = []
    _LOGGER.info("Adding cameras")
    for camera in api.cameras:
        _LOGGER.info(f"Adding nest camera uuid: {camera}")
        cameras.append(NestCamera(
            camera,
            api,
            config_entry.entry_id,
        ))

    async_add_entities(cameras)

class NestCamera(Camera):
    """Representation of a Nest camera."""

    _attr_supported_features = CameraEntityFeature.ON_OFF

    def __init__(self, device_id: str, api, entry_id: str) -> None:
        """Initialize a Nest camera."""
        super().__init__()
        self.device_id = device_id
        self.device = api
        self._entry_id = entry_id
        
        # Set unique ID incorporating config entry ID
        self._attr_unique_id = f"{entry_id}_{device_id}_camera"
        
        # Initialize from device data
        device_data = self.device.device_data[device_id]
        self._attr_name = device_data.get('name', "Nest Camera")
        self._attr_is_on = device_data.get('streaming_state', False)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device specific attributes."""
        device_data = self.device.device_data[self.device_id]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self.device_id}")},
            name=device_data.get('name', "Nest Camera"),
            manufacturer="Nest",
            model=device_data.get('model', "Camera"),
            sw_version=device_data.get('software_version'),
            suggested_area=device_data.get('where_name'),
        )

    @property
    def is_on(self) -> bool:
        """Return true if on."""
        return self._attr_is_on

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image response from the camera."""
        if not self.is_on:
            return None

        return await self.device.camera_get_image(
            self.device_id,
            int(datetime.now().timestamp()),
        )

    async def async_turn_off(self) -> None:
        """Turn off camera."""
        await self.device.camera_turn_off(self.device_id)
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on camera."""
        await self.device.camera_turn_on(self.device_id)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the status of the camera."""
        await self.device.update()
        self._attr_is_on = self.device.device_data[self.device_id].get('streaming_state', False)
