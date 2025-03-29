import logging
import time
import voluptuous as vol

from datetime import datetime
from homeassistant.util.dt import now
from homeassistant.helpers import config_validation as cv
from homeassistant.const import (
    ATTR_ENTITY_ID,
)
from homeassistant.components.water_heater import (
    ATTR_AWAY_MODE,
    ATTR_OPERATION_MODE,
    ATTR_OPERATION_LIST,
)
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)

# Replace old constants with new enum-based features
SUPPORT_OPERATION_MODE = WaterHeaterEntityFeature.OPERATION_MODE
SUPPORT_AWAY_MODE = WaterHeaterEntityFeature.AWAY_MODE
SUPPORT_BOOST_MODE = 8  # Custom feature flag

# Update supported features to use bitwise OR with new enum
SUPPORTED_FEATURES = (
    WaterHeaterEntityFeature.OPERATION_MODE |
    WaterHeaterEntityFeature.AWAY_MODE |
    SUPPORT_BOOST_MODE
)

try:
    from homeassistant.components.water_heater import WaterHeaterEntity
except ImportError:
    from homeassistant.components.water_heater import WaterHeaterDevice as WaterHeaterEntity

from .const import (
    DOMAIN,
)

STATE_SCHEDULE = 'Schedule'
STATE_OFF = 'Off'
STATE_HEATING = 'Heating'
STATE_IDLE = 'Idle'

SERVICE_BOOST_HOT_WATER = 'boost_hot_water'
ATTR_TIME_PERIOD = 'time_period'
ATTR_BOOST_MODE_STATUS = 'boost_mode_status'
ATTR_BOOST_MODE = 'boost_mode'
ATTR_HEATING_ACTIVE = 'heating_active'
ATTR_AWAY_MODE_ACTIVE = 'away_mode_active'

NEST_TO_HASS_MODE = {"schedule": STATE_SCHEDULE, "off": STATE_OFF}
HASS_TO_NEST_MODE = {STATE_SCHEDULE: "schedule", STATE_OFF: "off"}
NEST_TO_HASS_STATE = {True: STATE_HEATING, False: STATE_IDLE}
HASS_TO_NEST_STATE = {STATE_HEATING: True, STATE_IDLE: False}
SUPPORTED_OPERATIONS = [STATE_SCHEDULE, STATE_OFF]

BOOST_HOT_WATER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.comp_entity_ids,
        vol.Optional(ATTR_TIME_PERIOD, default=30): cv.positive_int,
        vol.Required(ATTR_BOOST_MODE): cv.boolean,
    }
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass,
                               config,
                               async_add_entities,
                               discovery_info=None):
    """Set up the Nest water heater device."""
    api = hass.data[DOMAIN]['api']

    waterheaters = []
    _LOGGER.info("Adding waterheaters")
    for waterheater in api['hotwatercontrollers']:
        _LOGGER.info(f"Adding nest waterheater uuid: {waterheater}")
        waterheaters.append(NestWaterHeater(waterheater, api))
    async_add_entities(waterheaters)

    def hot_water_boost(service):
        """Handle the service call."""
        entity_ids = service.data[ATTR_ENTITY_ID]
        minutes = service.data[ATTR_TIME_PERIOD]
        timeToEnd = int(time.mktime(datetime.timetuple(now()))+(minutes*60))
        mode = service.data[ATTR_BOOST_MODE]
        _LOGGER.debug('HW boost mode: {} ending: {}'.format(mode, timeToEnd))

        _waterheaters = [
            x for x in waterheaters if not entity_ids or x.entity_id in entity_ids
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
    
    def __init__(self, device_id, api):
        """Initialize the sensor."""
        super().__init__()
        self._attr_name = "Nest Hot Water Heater"
        self.device_id = device_id
        self.device = api
        self._attr_unique_id = f"{device_id}_hw"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Nest",
            "model": "Hot Water Controller",
            "via_device": (DOMAIN, self.device_id)
        }

    @property
    def name(self):
        """Return the name of the water heater."""
        return "{0} Hot Water".format(
            self.device.device_data[self.device_id]['name'])

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return "mdi:water" if self.current_operation == STATE_SCHEDULE else "mdi:water-off"

    @property
    def state(self):
        """Return the (master) state of the water heater."""
        if self.device.device_data[self.device_id]['hot_water_status']:
            return NEST_TO_HASS_STATE[self.device.device_data[self.device_id]['hot_water_status']]
        return STATE_IDLE

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
        data = {}
        device_data = self.device.device_data[self.device_id]

        # Core state attributes
        if self.supported_features & SUPPORT_OPERATION_MODE:
            data[ATTR_OPERATION_MODE] = self.current_operation

        # Away mode attributes
        if self.supported_features & SUPPORT_AWAY_MODE:
            is_away = self.is_away_mode_on
            data[ATTR_AWAY_MODE] = STATE_HEATING if is_away else STATE_IDLE
            data[ATTR_AWAY_MODE_ACTIVE] = device_data.get('hot_water_away_active', False)

        # Boost mode attributes
        if self.supported_features & SUPPORT_BOOST_MODE:
            boost_time = device_data.get('hot_water_boost_setting', 0)
            data[ATTR_BOOST_MODE_STATUS] = bool(boost_time)
            if boost_time:
                data['boost_time_remaining'] = boost_time - int(time.time())

        # Status attributes
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

async def async_service_away_mode(entity, service):
    """Handle away mode service."""
    if service.data[ATTR_AWAY_MODE]:
        await entity.async_turn_away_mode_on()
    else:
        await entity.async_turn_away_mode_off()
