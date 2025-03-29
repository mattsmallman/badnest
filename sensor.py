"""Support for Nest sensors."""
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass, 
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import (
    ATTR_BATTERY_LEVEL,
    UnitOfTemperature,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS = {
    "temperature": SensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        icon="mdi:thermometer",
        name="Temperature",
    ),
    "co_status": SensorEntityDescription(
        key="co_status",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:molecule-co",
        name="CO Status",
    ),
    "smoke_status": SensorEntityDescription(
        key="smoke_status",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:smoke-detector", 
        name="Smoke Status",
    ),
    "battery_health_state": SensorEntityDescription(
        key="battery_health_state",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:battery",
        name="Battery Health",
    ),
}

PROTECT_SENSOR_TYPES = ["co_status", "smoke_status", "battery_health_state"]

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nest sensors from config entry."""
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    entities = []
    
    # Add temperature sensors
    _LOGGER.info("Adding temperature sensors")
    for sensor in api['temperature_sensors']:
        _LOGGER.info(f"Adding nest temp sensor uuid: {sensor}")
        entities.append(NestTemperatureSensor(
            sensor, 
            api,
            SENSOR_DESCRIPTIONS["temperature"],
            config_entry,
        ))

    # Add protect sensors
    _LOGGER.info("Adding protect sensors")
    for sensor in api['protects']:
        _LOGGER.info(f"Adding nest protect sensor uuid: {sensor}")
        device_name = api.device_data[sensor]['name']
        
        for sensor_type in PROTECT_SENSOR_TYPES:
            entities.append(NestProtectSensor(
                sensor,
                api,
                SENSOR_DESCRIPTIONS[sensor_type],
                device_name,
                config_entry,
            ))

    async_add_entities(entities)

class NestTemperatureSensor(SensorEntity):
    """Implementation of the Nest Temperature Sensor."""

    def __init__(self, device_id: str, api, description: SensorEntityDescription, entry: ConfigEntry):
        """Initialize the sensor."""
        self.entity_description = description
        self.device_id = device_id
        self.device = api
        self._entry = entry
        
        # Set unique ID
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_temperature"
        
        # Set name from device data
        self._attr_name = f"{self.device.device_data[device_id]['name']} Temperature"
        
    @property
    def device_info(self) -> DeviceInfo:
        """Return device specific attributes."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self.device_id}")},
            name=self.device.device_data[self.device_id]['name'],
            manufacturer="Nest",
            model="Temperature Sensor",
            sw_version=self.device.device_data[self.device_id].get('software_version'),
            suggested_area=self.device.device_data[self.device_id].get('where_name'),
            via_device=(DOMAIN, self._entry.entry_id),
        )

    @property 
    def native_value(self):
        """Return the state of the sensor."""
        return self.device.device_data[self.device_id]['temperature']

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            ATTR_BATTERY_LEVEL:
                self.device.device_data[self.device_id]['battery_level']
        }

    async def async_update(self):
        """Get the latest data and updates the states."""
        await self.hass.async_add_executor_job(self.device.update)

class NestProtectSensor(SensorEntity):
    """Representation of a Nest Protect sensor."""

    def __init__(self, device_id: str, api, description: SensorEntityDescription, device_name: str, entry: ConfigEntry):
        """Initialize the sensor."""
        self.entity_description = description
        self.device_id = device_id
        self.device = api
        self._sensor_type = description.key
        self._entry = entry
        
        # Set unique ID
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_{description.key}"
        
        # Set name combining device name and sensor type
        self._attr_name = f"{device_name} {description.name}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device specific attributes."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self.device_id}")},
            name=self.device.device_data[self.device_id]['name'],
            manufacturer="Nest",
            model="Protect",
            sw_version=self.device.device_data[self.device_id].get('software_version'),
            suggested_area=self.device.device_data[self.device_id].get('where_name'),
            via_device=(DOMAIN, self._entry.entry_id),
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.device.device_data[self.device_id][self._sensor_type]

    async def async_update(self):
        """Get the latest data and update the state."""
        await self.hass.async_add_executor_job(self.device.update)
