"""Support for Nest Water Heater devices."""
import logging
import time
import voluptuous as vol

from datetime import datetime
from homeassistant.util.dt import now
from homeassistant.helpers import config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
    STATE_OFF,
    STATE_ON,
    ATTR_AWAY_MODE,
    ATTR_OPERATION_MODE,
    ATTR_OPERATION_LIST,
)

from .const import DOMAIN

# Replace old constants with new enum-based features
SUPPORT_OPERATION_MODE = WaterHeaterEntityFeature.OPERATION_MODE
SUPPORT_AWAY_MODE = WaterHeaterEntityFeature.AWAY_MODE
SUPPORT_BOOST_MODE = 8  # Custom feature flag

SUPPORTED_FEATURES = (
    WaterHeaterEntityFeature.OPERATION_MODE |
    WaterHeaterEntityFeature.AWAY_MODE |
    SUPPORT_BOOST_MODE
)

STATE_SCHEDULE = 'Schedule'
SERVICE_BOOST_HOT_WATER = 'boost_hot_water'
ATTR_TIME_PERIOD = 'time_period'
ATTR_BOOST_MODE_STATUS = 'boost_mode_status'
ATTR_BOOST_MODE = 'boost_mode'
ATTR_HEATING_ACTIVE = 'heating_active'
ATTR_AWAY_MODE_ACTIVE = 'away_mode_active'

# Use the HA constants for base states, but our custom modes for operations
NEST_TO_HASS_MODE = {"schedule": STATE_SCHEDULE, "off": STATE_OFF}
HASS_TO_NEST_MODE = {STATE_SCHEDULE: "schedule", STATE_OFF: "off"}
NEST_TO_HASS_STATE = {True: STATE_ON, False: STATE_OFF}
HASS_TO_NEST_STATE = {STATE_ON: True, STATE_OFF: False}
SUPPORTED_OPERATIONS = [STATE_SCHEDULE, STATE_OFF]

BOOST_HOT_WATER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Optional(ATTR_TIME_PERIOD, default=30): cv.positive_int,
        vol.Required(ATTR_BOOST_MODE): cv.boolean,
    }
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nest water heater device from config entry."""
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    entities = []
    _LOGGER.info("Adding water heaters")
    for controller in api['hotwatercontrollers']:
        _LOGGER.info(f"Adding nest water heater uuid: {controller}")
        # Only add if the device supports hot water control
        if api.device_data[controller].get('has_hot_water_control', False):
            entities.append(
                NestWaterHeater(
                    device_id=controller,
                    api=api,
                    entry_id=config_entry.entry_id,
                )
            )

    async_add_entities(entities)

    def hot_water_boost(service):
        """Handle the service call."""
        entity_ids = service.data[ATTR_ENTITY_ID]
        minutes = service.data[ATTR_TIME_PERIOD]
        timeToEnd = int(time.mktime(datetime.timetuple(now()))+(minutes*60))
        mode = service.data[ATTR_BOOST_MODE]
        _LOGGER.debug('HW boost mode: {} ending: {}'.format(mode, timeToEnd))

        _waterheaters = [
            x for x in entities if not entity_ids or x.entity_id in entity_ids
        ]

        for nest_water_heater in _waterheaters:
            if mode:
                nest_water_heater.turn_boost_mode_on(timeToEnd)
            else:
                nest_water_heater.turn_boost_mode_off()

    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOST_HOT_WATER,
        hot_water_boost,
        schema=BOOST_HOT_WATER_SCHEMA,
    )

class NestWaterHeater(WaterHeaterEntity):
    """Representation of a Nest water heater device."""

    _attr_supported_features = SUPPORTED_FEATURES
    
    def __init__(self, device_id: str, api, entry_id: str) -> None:
        """Initialize the water heater."""
        super().__init__()
        self.device_id = device_id
        self.device = api
        self._entry_id = entry_id
        
        # Set unique ID incorporating config entry ID for multi-account support
        self._attr_unique_id = f"{entry_id}_{device_id}_hw"
        
        device_data = self.device.device_data[device_id]
        name = device_data.get('name', '')
        self._attr_name = f"{name} Hot Water"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self.device_id}")},
            "name": self.device.device_data[self.device_id]['name'],
            "manufacturer": "Nest",
            "model": "Thermostat",
            "sw_version": self.device.device_data[self.device_id].get('software_version'),
            "suggested_area": self.device.device_data[self.device_id].get('where_name'),
            "via_device": (DOMAIN, self._entry_id),
        }

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return "mdi:water" if self.current_operation == STATE_SCHEDULE else "mdi:water-off"

    @property
    def state(self):
        """Return the operation mode as the main state."""
        return self.current_operation

    @property
    def capability_attributes(self):
        """Return capability attributes."""
        supported_features = self.supported_features or 0

        data = {}

        if supported_features & SUPPORT_OPERATION_MODE:
            data[ATTR_OPERATION_LIST] = self.operation_list

        return data

    @property
    def state_attributes(self):
        """Return the optional state attributes."""
        data = super().state_attributes or {}
        device_data = self.device.device_data[self.device_id]

        # Core state attributes
        if self.supported_features & SUPPORT_OPERATION_MODE:
            data[ATTR_OPERATION_MODE] = self.current_operation

        # Away mode attributes
        if self.supported_features & SUPPORT_AWAY_MODE:
            is_away = self.is_away_mode_on
            data[ATTR_AWAY_MODE] = STATE_ON if is_away else STATE_OFF
            data[ATTR_AWAY_MODE_ACTIVE] = device_data.get('hot_water_away_active', False)

        # Boost mode attributes
        if self.supported_features & SUPPORT_BOOST_MODE:
            boost_time = device_data.get('hot_water_boost_setting', 0)
            data[ATTR_BOOST_MODE_STATUS] = bool(boost_time)
            if boost_time:
                data['boost_time_remaining'] = boost_time - int(time.time())

        # Status attributes
        data['is_heating'] = device_data.get('hot_water_status', False)
        data[ATTR_HEATING_ACTIVE] = device_data.get('hot_water_actively_heating', False)
        data['next_transition_time'] = device_data.get('hot_water_next_transition_time', None)
        data['boiling_state'] = device_data.get('hot_water_boiling_state', False)
        
        _LOGGER.debug("Device state attributes: {}".format(data))
        return data

    @property
    def current_operation(self):
        """Return current operation ie. eco, electric, performance, ..."""
        return NEST_TO_HASS_MODE[self.device.device_data[self.device_id]['hot_water_timer_mode']]

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return SUPPORTED_OPERATIONS

    @property
    def is_away_mode_on(self):
        """Return true if away mode is on."""
        away = self.device.device_data[self.device_id]['hot_water_away_setting']
        return away

    def set_operation_mode(self, operation_mode):
        """Set new target operation mode."""
        nest_mode = HASS_TO_NEST_MODE.get(operation_mode)
        if nest_mode and self.device.device_data[self.device_id]['has_hot_water_control']:
            self.device.hotwater_set_mode(self.device_id, mode=nest_mode)

    async def async_set_operation_mode(self, operation_mode):
        """Set new target operation mode."""
        await self.hass.async_add_executor_job(self.set_operation_mode, operation_mode)

    def turn_away_mode_on(self):
        """Turn away mode on."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            self.device.hotwater_set_away_mode(self.device_id, away_mode=True)

    async def async_turn_away_mode_on(self):
        """Turn away mode on."""
        await self.hass.async_add_executor_job(self.turn_away_mode_on)

    def turn_away_mode_off(self):
        """Turn away mode off."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            self.device.hotwater_set_away_mode(self.device_id, away_mode=False)

    async def async_turn_away_mode_off(self):
        """Turn away mode off."""
        await self.hass.async_add_executor_job(self.turn_away_mode_off)

    def turn_boost_mode_on(self, timeToEnd):
        """Turn boost mode on."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            self.device.hotwater_set_boost(self.device_id, time=timeToEnd)

    def turn_boost_mode_off(self):
        """Turn boost mode off."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            self.device.hotwater_set_boost(self.device_id, time=0)

    def update(self):
        """Get the latest data from the Hot Water Sensor and updates the states."""
        self.device.update()
