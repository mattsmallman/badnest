"""Support for Nest water heater devices."""
import logging
from datetime import datetime
from typing import Any

from homeassistant.util.dt import now
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
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
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

# Features
SUPPORT_OPERATION_MODE = WaterHeaterEntityFeature.OPERATION_MODE
SUPPORT_AWAY_MODE = WaterHeaterEntityFeature.AWAY_MODE
SUPPORT_BOOST_MODE = 8  # Custom feature flag

SUPPORTED_FEATURES = (
    WaterHeaterEntityFeature.OPERATION_MODE |
    WaterHeaterEntityFeature.AWAY_MODE |
    SUPPORT_BOOST_MODE
)

# States and modes
STATE_SCHEDULE = 'Schedule'
SERVICE_BOOST_HOT_WATER = 'boost_hot_water'
ATTR_TIME_PERIOD = 'time_period'
ATTR_BOOST_MODE = 'boost_mode'
ATTR_BOOST_MODE_STATUS = 'boost_mode_status'
ATTR_HEATING_ACTIVE = 'heating_active'
ATTR_AWAY_MODE_ACTIVE = 'away_mode_active'

# Mode mappings
NEST_TO_HASS_MODE = {"schedule": STATE_SCHEDULE, "off": STATE_OFF}
HASS_TO_NEST_MODE = {STATE_SCHEDULE: "schedule", STATE_OFF: "off"}
NEST_TO_HASS_STATE = {True: STATE_ON, False: STATE_OFF}
HASS_TO_NEST_STATE = {STATE_ON: True, STATE_OFF: False}
SUPPORTED_OPERATIONS = [STATE_SCHEDULE, STATE_OFF]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nest water heater devices from config entry."""
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    entities = []
    _LOGGER.info("Adding water heaters")
    for controller in api.hotwatercontrollers:
        _LOGGER.info(f"Adding nest water heater uuid: {controller}")
        device_data = api.device_data[controller]
        _LOGGER.debug(f"Device data for {controller}: {device_data}")
        
        has_hw_control = device_data.get('has_hot_water_control', False)
        _LOGGER.debug(f"Has hot water control: {has_hw_control}")
        
        if has_hw_control:
            _LOGGER.info(f"Creating water heater entity for {controller}")
            entities.append(
                NestWaterHeater(
                    device_id=controller,
                    api=api,
                    entry_id=config_entry.entry_id,
                )
            )

    if not entities:
        return

    async_add_entities(entities)

    async def async_hot_water_boost(service: ServiceCall) -> None:
        """Handle the service call."""
        entity_ids = service.data[ATTR_ENTITY_ID]
        minutes = service.data[ATTR_TIME_PERIOD]
        timeToEnd = int(datetime.timestamp(now()) + minutes * 60)
        mode = service.data[ATTR_BOOST_MODE]
        _LOGGER.debug('HW boost mode: %s ending: %s', mode, timeToEnd)

        target_heaters = [
            heater for heater in entities
            if not entity_ids or heater.entity_id in entity_ids
        ]

        for heater in target_heaters:
            if mode:
                await heater.async_turn_boost_mode_on(timeToEnd)
            else:
                await heater.async_turn_boost_mode_off()

    # Register boost service
    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOST_HOT_WATER,
        async_hot_water_boost,
    )

class NestWaterHeater(WaterHeaterEntity):
    """Representation of a Nest water heater device."""

    _attr_has_entity_name = True
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, device_id: str, api, entry_id: str) -> None:
        """Initialize the water heater."""
        self.device_id = device_id
        self.device = api
        self._entry_id = entry_id
        
        # Set unique ID incorporating config entry ID
        self._attr_unique_id = f"{entry_id}_{device_id}_hw"
        
        # Initialize from device data
        device_data = self.device.device_data[device_id]
        _LOGGER.debug(f"Initializing water heater with data: {device_data}")
        
        self._attr_name = f"{device_data.get('name', '')} Hot Water"
        _LOGGER.info(f"Created water heater entity: {self._attr_name}")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Use the same device info as the thermostat to make it a child entity
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self.device_id}")},
            name=self.device.device_data[self.device_id]['name'],
            manufacturer="Nest",
            model="Thermostat",
            sw_version=self.device.device_data[self.device_id].get('software_version'),
            suggested_area=self.device.device_data[self.device_id].get('where_name'),
        )

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        return "mdi:water" if self.current_operation == STATE_SCHEDULE else "mdi:water-off"

    @property
    def operation_list(self) -> list[str]:
        """Return the list of available operation modes."""
        return SUPPORTED_OPERATIONS

    @property
    def current_operation(self) -> str:
        """Return current operation."""
        return NEST_TO_HASS_MODE[
            self.device.device_data[self.device_id]['hot_water_timer_mode']
        ]

    @property
    def is_away_mode_on(self) -> bool:
        """Return true if away mode is on."""
        return self.device.device_data[self.device_id]['hot_water_away_setting']

    @property
    def state_attributes(self) -> dict[str, Any]:
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
                data['boost_time_remaining'] = boost_time - int(datetime.now().timestamp())

        # Status attributes
        data['is_heating'] = device_data.get('hot_water_status', False)
        data[ATTR_HEATING_ACTIVE] = device_data.get('hot_water_actively_heating', False)
        data['next_transition_time'] = device_data.get('hot_water_next_transition_time', None)
        data['boiling_state'] = device_data.get('hot_water_boiling_state', False)
        
        return data

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new target operation mode."""
        nest_mode = HASS_TO_NEST_MODE.get(operation_mode)
        if nest_mode and self.device.device_data[self.device_id]['has_hot_water_control']:
            await self.device.hotwater_set_mode(self.device_id, mode=nest_mode)

    async def async_turn_away_mode_on(self) -> None:
        """Turn away mode on."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            await self.device.hotwater_set_away_mode(self.device_id, away_mode=True)

    async def async_turn_away_mode_off(self) -> None:
        """Turn away mode off."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            await self.device.hotwater_set_away_mode(self.device_id, away_mode=False)

    async def async_turn_boost_mode_on(self, timeToEnd: int) -> None:
        """Turn boost mode on."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            await self.device.hotwater_set_boost(self.device_id, time=timeToEnd)

    async def async_turn_boost_mode_off(self) -> None:
        """Turn boost mode off."""
        if self.device.device_data[self.device_id]['has_hot_water_control']:
            await self.device.hotwater_set_boost(self.device_id, time=0)

    async def async_update(self) -> None:
        """Get the latest data and updates the state."""
        await self.device.update()
