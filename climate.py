"""Demo platform that offers a fake climate device."""
from datetime import datetime
from typing import Any
import logging

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
    FAN_ON,  # Changed from FAN_MODE_ON
    FAN_AUTO,  # Changed from FAN_MODE_AUTO
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.components.sensor import SensorDeviceClass

from .const import DOMAIN

HVAC_MODE_MAP = {
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "heat-cool": HVACMode.HEAT_COOL,
    "eco": HVACMode.AUTO,
    "off": HVACMode.OFF,
}

# Update fan mode mapping to use new constants
FAN_MODE_MAP = {
    "on": FAN_ON,
    "auto": FAN_AUTO,
}

NEST_MODE_HEAT_COOL = "range"
NEST_MODE_ECO = "eco"
NEST_MODE_HEAT = "heat"
NEST_MODE_COOL = "cool"
NEST_MODE_OFF = "off"

MODE_HASS_TO_NEST = {
    HVACMode.HEAT_COOL: NEST_MODE_HEAT_COOL,
    HVACMode.HEAT: NEST_MODE_HEAT,
    HVACMode.COOL: NEST_MODE_COOL,
    HVACMode.OFF: NEST_MODE_OFF,
}

# Update ACTION_NEST_TO_HASS mapping to use HVACAction enum only
ACTION_NEST_TO_HASS = {
    "off": HVACAction.IDLE,
    "heating": HVACAction.HEATING,
    "cooling": HVACAction.COOLING,
}

MODE_NEST_TO_HASS = {v: k for k, v in MODE_HASS_TO_NEST.items()}

ROUND_TARGET_HUMIDITY_TO_NEAREST = 5
NEST_HUMIDITY_MIN = 10
NEST_HUMIDITY_MAX = 60

# Update PRESET_MODES to use string constants
PRESET_MODES = [PRESET_NONE, PRESET_ECO]

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass,
                               config,
                               async_add_entities,
                               discovery_info=None):
    """Set up the Nest climate device."""
    api = hass.data[DOMAIN]['api']

    thermostats = []
    _LOGGER.info("Adding thermostats")
    for thermostat in api['thermostats']:
        _LOGGER.info(f"Adding nest thermostat uuid: {thermostat}")
        thermostats.append(NestClimate(thermostat, api))

    async_add_entities(thermostats)


class NestClimate(ClimateEntity):
    """Nest climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.TARGET_TEMPERATURE_RANGE |
        ClimateEntityFeature.FAN_MODE |
        ClimateEntityFeature.PRESET_MODE
    )

    _attr_hvac_modes = [
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.HEAT_COOL,
        HVACMode.OFF,
    ]
    
    _attr_preset_modes = PRESET_MODES
    _attr_fan_modes = [FAN_ON, FAN_AUTO]  # Updated fan modes

    def __init__(self, device_id, api):
        """Initialize the thermostat."""
        super().__init__()
        self._attr_name = "Nest Thermostat"
        self.device_id = device_id
        self.device = api
        self._attr_unique_id = device_id

    @property
    def unique_id(self):
        """Return an unique ID."""
        return self.device_id

    @property
    def name(self):
        """Return an friendly name."""
        return self.device.device_data[self.device_id]['name']

    @property
    def should_poll(self):
        """Return the polling state."""
        return True

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.device.device_data[self.device_id]['current_temperature']

    @property
    def current_humidity(self):
        """Return the current humidity."""
        return self.device.device_data[self.device_id]['current_humidity']

    @property
    def target_humidity(self):
        """Return the target humidity."""
        return self.device.device_data[self.device_id]['target_humidity']

    @property
    def min_humidity(self):
        """Return the min target humidity."""
        return NEST_HUMIDITY_MIN

    @property
    def max_humidity(self):
        """Return the max target humidity."""
        return NEST_HUMIDITY_MAX

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self.device.device_data[self.device_id]['mode'] \
                != NEST_MODE_HEAT_COOL \
                and not self.device.device_data[self.device_id]['eco']:
            return \
                self.device.device_data[self.device_id]['target_temperature']
        return None

    @property
    def target_temperature_high(self):
        """Return the highbound target temperature we try to reach."""
        if self.device.device_data[self.device_id]['mode'] \
                == NEST_MODE_HEAT_COOL \
                and not self.device.device_data[self.device_id]['eco']:
            return \
                self.device. \
                device_data[self.device_id]['target_temperature_high']
        return None

    @property
    def target_temperature_low(self):
        """Return the lowbound target temperature we try to reach."""
        if self.device.device_data[self.device_id]['mode'] \
                == NEST_MODE_HEAT_COOL \
                and not self.device.device_data[self.device_id]['eco']:
            return \
                self.device. \
                device_data[self.device_id]['target_temperature_low']
        return None

    @property
    def hvac_action(self) -> HVACAction:
        """Return current operation ie. heat, cool, idle."""
        return ACTION_NEST_TO_HASS[
            self.device.device_data[self.device_id]['action']
        ]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        return HVAC_MODE_MAP.get(
            self.device.device_data[self.device_id]['hvac_mode'],
            HVACMode.OFF
        )

    @property
    def fan_mode(self) -> str:
        """Return current fan mode."""
        return FAN_MODE_MAP.get(
            self.device.device_data[self.device_id]['fan_mode'],
            FAN_AUTO  # Updated default
        )

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        temp = None
        target_temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        target_temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        if self.device.device_data[self.device_id]['mode'] == \
                NEST_MODE_HEAT_COOL:
            if target_temp_low is not None and target_temp_high is not None:
                self.device.thermostat_set_temperature(
                    self.device_id,
                    target_temp_low,
                    target_temp_high,
                )
        else:
            temp = kwargs.get(ATTR_TEMPERATURE)
            if temp is not None:
                self.device.thermostat_set_temperature(
                    self.device_id,
                    temp,
                )

    def set_humidity(self, humidity):
        """Set new target humidity."""
        humidity = int(round(float(humidity) / ROUND_TARGET_HUMIDITY_TO_NEAREST) * ROUND_TARGET_HUMIDITY_TO_NEAREST)
        if humidity < NEST_HUMIDITY_MIN:
            humidity = NEST_HUMIDITY_MIN
        if humidity > NEST_HUMIDITY_MAX:
            humidity = NEST_HUMIDITY_MAX
        self.device.thermostat_set_target_humidity(
            self.device_id,
            humidity,
        )

    def set_hvac_mode(self, hvac_mode):
        """Set operation mode."""
        self.device.thermostat_set_mode(
            self.device_id,
            MODE_HASS_TO_NEST[hvac_mode],
        )

    def set_fan_mode(self, fan_mode: str) -> None:
        """Turn fan on/off."""
        if self.device.device_data[self.device_id]['has_fan']:
            if fan_mode == FAN_ON:  # Updated comparison
                self.device.thermostat_set_fan(
                    self.device_id,
                    int(datetime.now().timestamp() + 60 * 30),
                )
            else:
                self.device.thermostat_set_fan(
                    self.device_id,
                    0,
                )

    def set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        need_eco = preset_mode == PRESET_ECO

        if need_eco != self.device.device_data[self.device_id]['eco']:
            self.device.thermostat_set_eco_mode(
                self.device_id,
                need_eco,
            )

    def update(self) -> None:
        """Updates data."""
        self.device.update()
