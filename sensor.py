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
    "heat_status": SensorEntityDescription(
        key="heat_status",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:fire",
        name="Heat Status",
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

PROTECT_SENSOR_TYPES = ["co_status", "smoke_status", "battery_health_state", "heat_status"]

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
    for sensor in api.temperature_sensors:
        _LOGGER.info(f"Adding nest temp sensor uuid: {sensor}")
        entities.append(NestTemperatureSensor(
            sensor, 
            api,
            SENSOR_DESCRIPTIONS["temperature"],
            config_entry,
        ))

    # Add protect sensors
    _LOGGER.info("Adding protect sensors")
    for sensor in api.protects:
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
        await self.device.update()

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

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        data = self.device.device_data[self.device_id]
        return {
            ATTR_BATTERY_LEVEL: data.get('battery_level'),
            "device_model": data.get('model'),
            "creation_time": data.get('creation_time'),
            "last_test_start": data.get('latest_manual_test_start_utc_secs'),
            "last_test_end": data.get('latest_manual_test_end_utc_secs'),
            "last_audio_test_start": data.get('last_audio_self_test_start_utc_secs'),
            "last_audio_test_end": data.get('last_audio_self_test_end_utc_secs'),
            "auto_away": data.get('auto_away'),
            "night_light": {
                "enabled": data.get('night_light_enable'),
                "brightness": data.get('night_light_brightness'),
                "continuous": data.get('night_light_continuous')
            },
            "steam_detection_enable": data.get('steam_detection_enable'),
            "born_on_date": data.get('device_born_on_date_utc_secs'),
            "replace_by_date": data.get('replace_by_date_utc_secs'),
            "kl_software_version": data.get('kl_software_version'),
            "device_info": {
                "color": data.get('device_external_color'),
                "locale": data.get('device_locale'),
                "installed_locale": data.get('installed_locale')
            },
            "component_tests": {
                "smoke": data.get('component_smoke_test_passed'),
                "co": data.get('component_co_test_passed'),
                "heat": data.get('component_heat_test_passed'),
                "humidity": data.get('component_hum_test_passed'),
                "temperature": data.get('component_temp_test_passed'),
                "pir": data.get('component_pir_test_passed'),
                "audio": data.get('component_speaker_test_passed'),
                "wifi": data.get('component_wifi_test_passed')
            },
            "network": {
                "wifi": {
                    "ip": data.get('wifi_ip_address'),
                    "mac": data.get('wifi_mac_address'),
                    "regulatory_domain": data.get('wifi_regulatory_domain')
                },
                "thread": {
                    "ip": data.get('thread_ip_address'),
                    "mac": data.get('thread_mac_address')
                }
            }
        }

    async def async_update(self):
        """Get the latest data and update the state."""
        await self.device.update()
