"""Support for Nest thermostats."""
from __future__ import annotations

from typing import Any
import logging
from datetime import datetime

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
    PRESET_ECO,
    PRESET_NONE,
)
from homeassistant.components.climate.const import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_ON,
    FAN_AUTO,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

# Nest mode constants
NEST_MODE_HEAT_COOL = "range"
NEST_MODE_ECO = "eco"
NEST_MODE_HEAT = "heat"
NEST_MODE_COOL = "cool"
NEST_MODE_OFF = "off"
NEST_MODE_HEAT_COOL_ALT = "heat-cool"

# Mode mappings
MODE_HASS_TO_NEST = {
    HVACMode.HEAT_COOL: NEST_MODE_HEAT_COOL,
    HVACMode.COOL: NEST_MODE_COOL,
    HVACMode.HEAT: NEST_MODE_HEAT,
    HVACMode.OFF: NEST_MODE_OFF,
}

MODE_NEST_TO_HASS = {
    NEST_MODE_HEAT_COOL: HVACMode.HEAT_COOL,
    NEST_MODE_COOL: HVACMode.COOL,
    NEST_MODE_HEAT: HVACMode.HEAT,
    NEST_MODE_OFF: HVACMode.OFF,
    NEST_MODE_ECO: HVACMode.OFF,  # Map eco to OFF since we handle eco separately
    NEST_MODE_HEAT_COOL_ALT: HVACMode.HEAT_COOL,
}

FAN_MODE_MAP = {
    "on": FAN_ON,
    "auto": FAN_AUTO,
}

ACTION_NEST_TO_HASS = {
    "off": HVACAction.IDLE,
    "heating": HVACAction.HEATING,
    "cooling": HVACAction.COOLING,
}

PRESET_MODES = [PRESET_NONE, PRESET_ECO]

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nest climate devices from config entry."""
    api = hass.data[DOMAIN][config_entry.entry_id]["api"]

    entities = []
    _LOGGER.info("Adding thermostats")
    
    for thermostat in api.thermostats:
        _LOGGER.info(f"Adding nest thermostat uuid: {thermostat}")
        entities.append(
            NestClimate(
                device_id=thermostat,
                api=api,
                entry_id=config_entry.entry_id,
            )
        )

    async_add_entities(entities)

class NestClimate(ClimateEntity):
    """Representation of a Nest climate device."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.TARGET_TEMPERATURE_RANGE |
        ClimateEntityFeature.PRESET_MODE |
        ClimateEntityFeature.FAN_MODE
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]
    _attr_preset_modes = PRESET_MODES
    _attr_fan_modes = [FAN_ON, FAN_AUTO]

    def __init__(self, device_id: str, api, entry_id: str) -> None:
        """Initialize the thermostat."""
        self.device_id = device_id
        self.device = api
        self._entry_id = entry_id
        
        # Set unique ID incorporating config entry ID
        self._attr_unique_id = f"{entry_id}_{device_id}_climate"
        
        # Initialize state data
        self._async_update_attrs()

    def _async_update_attrs(self) -> None:
        """Update state attributes from device data."""
        try:
            device_data = self.device.device_data[self.device_id]
            
            # Basic attributes
            self._attr_name = device_data.get('name', "Nest Thermostat")
            self._attr_current_temperature = device_data.get('current_temperature')
            self._attr_target_temperature = device_data.get('target_temperature')
            self._attr_target_temperature_high = device_data.get('target_temperature_high')
            self._attr_target_temperature_low = device_data.get('target_temperature_low')
            self._attr_current_humidity = device_data.get('current_humidity')
            
            # HVAC modes based on capabilities
            modes = [HVACMode.OFF]
            if device_data.get('can_heat', False):
                modes.append(HVACMode.HEAT)
            if device_data.get('can_cool', False):
                modes.append(HVACMode.COOL)
            if device_data.get('can_heat', False) and device_data.get('can_cool', False):
                modes.append(HVACMode.HEAT_COOL)
            self._attr_hvac_modes = modes
            
            # Fan modes if supported
            if device_data.get('has_fan', False):
                self._attr_fan_modes = [FAN_ON, FAN_AUTO]
            else:
                self._attr_fan_modes = []
                
            # Preset mode
            self._attr_preset_mode = PRESET_ECO if device_data.get('eco', False) else PRESET_NONE
            
        except Exception as e:
            _LOGGER.error(f"Failed to update thermostat attributes: {str(e)}")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        data = self.device.device_data[self.device_id]
        
        # Collect MAC addresses for connections
        connections = set()
        if mac := data.get("mac_address"):
            connections.add(("mac", mac))
            
        # Build model info
        model = data.get('model_version', "Thermostat")
        if backplate := data.get('backplate_model'):
            model = f"{model} with {backplate}"
            
        # Combine software versions
        sw_version = data.get('current_version')
        if heat_link_version := data.get('heat_link_sw_version'):
            sw_version = f"{sw_version} (Heat Link: {heat_link_version})" if sw_version else heat_link_version
            
        # Get hardware serials
        serials = []
        if main_serial := self.device_id:
            serials.append(main_serial)
        if backplate_serial := data.get('backplate_serial_number'):
            serials.append(f"Backplate: {backplate_serial}")
        if heat_link_serial := data.get('heat_link_serial_number'):
            serials.append(f"Heat Link: {heat_link_serial}")
        serial_number = ", ".join(serials)
            
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self.device_id}")},
            name=data.get('name', "Nest Thermostat"),
            manufacturer="Nest",
            model=model,
            sw_version=sw_version,
            hw_version=data.get('backplate_bsl_version'),
            suggested_area=data.get('where_name'),
            configuration_url="https://home.nest.com",
            connections=connections,
            serial_number=serial_number,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific state attributes."""
        data = self.device.device_data[self.device_id]
        return {
            "hvac_system": {
                "heater_source": data.get('heater_source'),
                "heater_delivery": data.get('heater_delivery'),
                "has_heat_pump": data.get('has_heat_pump'),
                "has_fossil_fuel": data.get('has_fossil_fuel'),
                "has_dehumidifier": data.get('has_dehumidifier'),
                "has_humidifier": data.get('has_humidifier'),
                "has_fan": data.get('has_fan'),
                "equipment_type": data.get('equipment_type'),
                "wiring": data.get('hvac_wires'),
            },
            "safety": {
                "lower_safety_temp_enabled": data.get('lower_safety_temp_enabled'),
                "lower_safety_temp": data.get('lower_safety_temp'),
                "upper_safety_temp_enabled": data.get('upper_safety_temp_enabled'),
                "upper_safety_temp": data.get('upper_safety_temp'),
                "safety_state": data.get('safety_state'),
                "hvac_safety_shutoff_active": data.get('hvac_safety_shutoff_active'),
            },
            "learning": {
                "learning_mode": data.get('learning_mode'),
                "learning_state": data.get('learning_state'),
                "time_to_target": data.get('time_to_target'),
                "time_to_target_training": data.get('time_to_target_training'),
                "learning_days_completed_heat": data.get('learning_days_completed_heat'),
                "learning_days_completed_cool": data.get('learning_days_completed_cool'),
            },
            "eco": {
                "enabled": data.get('eco', False),
                "leaf_away_high": data.get('leaf_away_high'),
                "leaf_away_low": data.get('leaf_away_low'),
                "leaf_threshold_cool": data.get('leaf_threshold_cool'),
                "leaf_threshold_heat": data.get('leaf_threshold_heat'),
            },
            "network": {
                "local_ip": data.get('local_ip'),
                "rssi": data.get('rssi'),
            },
            "locale": data.get('device_locale'),
            "temperature_scale": data.get('temperature_scale'),
            "sunlight_correction": {
                "enabled": data.get('sunlight_correction_enabled'),
                "active": data.get('sunlight_correction_active'),
                "ready": data.get('sunlight_correction_ready'),
            },
            "preconditioning": {
                "enabled": data.get('preconditioning_enabled'),
                "active": data.get('preconditioning_active'),
                "ready": data.get('preconditioning_ready'),
            }
        }

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode."""
        mode = self.device.device_data[self.device_id].get('mode', NEST_MODE_OFF)
        return MODE_NEST_TO_HASS.get(mode, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running hvac operation."""
        action = self.device.device_data[self.device_id].get('action', 'off')
        return ACTION_NEST_TO_HASS.get(action, HVACAction.IDLE)

    @property
    def fan_mode(self) -> str:
        """Return the fan setting."""
        device_data = self.device.device_data[self.device_id]
        if device_data.get('has_fan', False):
            return FAN_ON if device_data.get('fan', 0) > 0 else FAN_AUTO
        return None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode == PRESET_ECO:
            await self.device.thermostat_set_eco_mode(self.device_id, True)
        else:
            await self.device.thermostat_set_eco_mode(self.device_id, False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        target_temp = kwargs.get(ATTR_TEMPERATURE)

        if temp_high is not None and temp_low is not None:
            await self.device.thermostat_set_temperature(
                self.device_id,
                temp_low,
                temp_high,
            )
        elif target_temp is not None:
            await self.device.thermostat_set_temperature(
                self.device_id,
                target_temp,
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode == FAN_ON:
            # Turn on for 30 minutes
            await self.device.thermostat_set_fan(
                self.device_id,
                int(datetime.now().timestamp() + 60 * 30),
            )
        else:
            # Turn off
            await self.device.thermostat_set_fan(self.device_id, 0)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode in MODE_HASS_TO_NEST:
            await self.device.thermostat_set_mode(
                self.device_id,
                MODE_HASS_TO_NEST[hvac_mode],
            )

    async def async_update(self) -> None:
        """Update all Node data."""
        await self.device.update()
        self._async_update_attrs()
