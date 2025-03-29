import logging
from typing import Any

from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_BATTERY_LEVEL,
    UnitOfTemperature,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PROTECT_SENSOR_TYPES = [
    "co_status",
    "smoke_status",
    "battery_health"  # Changed from battery_health_state to match SENSOR_TYPES
]

SENSOR_TYPES = {
    "temperature": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:thermometer",
        "name": "Temperature",
    },
    "co_status": {
        "device_class": SensorDeviceClass.ENUM,
        "icon": "mdi:molecule-co",
        "name": "CO Status",
    },
    "smoke_status": {
        "device_class": SensorDeviceClass.ENUM,
        "icon": "mdi:smoke-detector",
        "name": "Smoke Status",
    },
    "battery_health": {  # Matches PROTECT_SENSOR_TYPES
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery",
        "name": "Battery Health",
    },
}

async def async_setup_platform(hass,
                               config,
                               async_add_entities,
                               discovery_info=None):
    """Set up the Nest climate device."""
    api = hass.data[DOMAIN]['api']

    temperature_sensors = []
    _LOGGER.info("Adding temperature sensors")
    for sensor in api['temperature_sensors']:
        _LOGGER.info(f"Adding nest temp sensor uuid: {sensor}")
        temperature_sensors.append(NestTemperatureSensor(sensor, api))

    async_add_entities(temperature_sensors)

    protect_sensors = []
    _LOGGER.info("Adding protect sensors")
    for sensor in api['protects']:
        _LOGGER.info(f"Adding nest protect sensor uuid: {sensor}")
        for sensor_type in PROTECT_SENSOR_TYPES:
            protect_sensors.append(NestProtectSensor(sensor, sensor_type, api))

    async_add_entities(protect_sensors)


class NestTemperatureSensor(SensorEntity):
    """Implementation of the Nest Temperature Sensor."""

    def __init__(self, device_id, api):
        """Initialize the sensor."""
        super().__init__()
        self._attr_name = "Nest Temperature Sensor"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self.device_id = device_id
        self.device = api
        self._attr_unique_id = device_id

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

    def __init__(self, device_id, sensor_type, api):
        """Initialize the sensor."""
        self._attr_unique_id = f"{device_id}_{sensor_type}"
        self.device_id = device_id
        self._sensor_type = sensor_type
        self.device = api
        
        self._attr_device_class = SENSOR_TYPES[sensor_type]["device_class"]
        if "state_class" in SENSOR_TYPES[sensor_type]:
            self._attr_state_class = SENSOR_TYPES[sensor_type]["state_class"]
        self._attr_icon = SENSOR_TYPES[sensor_type]["icon"]
        self._attr_name = f"{self.device.device_data[device_id]['name']} {SENSOR_TYPES[sensor_type]['name']}"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": self.device.device_data[self.device_id]['name'],
            "manufacturer": "Nest",
            "model": "Protect",
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.device.device_data[self.device_id][self._sensor_type]

    async def async_update(self):
        """Get the latest data and update the state."""
        await self.hass.async_add_executor_job(self.device.update)
