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
    try:
        for thermostat in api.thermostats:  # Access thermostats as property
            _LOGGER.info(f"Adding nest thermostat uuid: {thermostat}")
            thermostats.append(NestClimate(thermostat, api))

        if not thermostats:
            _LOGGER.warning("No thermostats found in Nest API response")
            return False

        async_add_entities(thermostats)
        return True
    except Exception as e:
        _LOGGER.error(f"Failed to setup Nest climate platform: {str(e)}")
        return False


class NestClimate(ClimateEntity):
    """Nest climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _unit_of_measurement = UnitOfTemperature.CELSIUS
    
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
        try:
            self.device_id = device_id
            self.device = api
            self._attr_unique_id = device_id
            
            # Verify device data is available
            if self.device_id not in self.device.device_data:
                raise KeyError(f"No device data found for thermostat {device_id}")

            device_data = self.device.device_data[self.device_id]    
            self._attr_name = device_data.get('name', "Nest Thermostat")
            
            # Initialize required properties
            self._attr_current_temperature = None
            self._attr_target_temperature = None
            self._attr_target_temperature_high = None
            self._attr_target_temperature_low = None
            self._attr_current_humidity = None
            
            # Initialize preset mode based on eco state
            self._attr_preset_mode = PRESET_ECO if device_data.get('eco', False) else PRESET_NONE
            
        except Exception as e:
            _LOGGER.error(f"Failed to initialize Nest climate device: {str(e)}")
            raise

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
        try:
            return self.device.device_data[self.device_id]['current_temperature']
        except KeyError:
            _LOGGER.error(f"Missing current_temperature data for {self.device_id}")
            return None

    @property
    def current_humidity(self):
        """Return the current humidity."""
        try:
            return self.device.device_data[self.device_id]['current_humidity']
        except KeyError:
            _LOGGER.error(f"Missing current_humidity data for {self.device_id}")
            return None

    @property
    def target_humidity(self):
        """Return the target humidity."""
        try:
            return self.device.device_data[self.device_id]['target_humidity']
        except KeyError:
            _LOGGER.error(f"Missing target_humidity data for {self.device_id}")
            return None

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
        try:
            device_data = self.device.device_data[self.device_id]
            if device_data.get('mode') != NEST_MODE_HEAT_COOL and not device_data.get('eco', False):
                return device_data.get('target_temperature')
            return None
        except (KeyError, AttributeError) as e:
            _LOGGER.error(f"Error getting target_temperature: {str(e)}")
            return None

    @property
    def target_temperature_high(self):
        """Return the highbound target temperature we try to reach."""
        try:
            device_data = self.device.device_data[self.device_id]
            if device_data.get('mode') == NEST_MODE_HEAT_COOL and not device_data.get('eco', False):
                return device_data.get('target_temperature_high')
            return None
        except (KeyError, AttributeError) as e:
            _LOGGER.error(f"Error getting target_temperature_high: {str(e)}")
            return None

    @property
    def target_temperature_low(self):
        """Return the lowbound target temperature we try to reach."""
        try:
            device_data = self.device.device_data[self.device_id]
            if device_data.get('mode') == NEST_MODE_HEAT_COOL and not device_data.get('eco', False):
                return device_data.get('target_temperature_low')
            return None
        except (KeyError, AttributeError) as e:
            _LOGGER.error(f"Error getting target_temperature_low: {str(e)}")
            return None

    @property
    def hvac_action(self) -> HVACAction:
        """Return current operation ie. heat, cool, idle."""
        try:
            action = self.device.device_data[self.device_id].get('action', 'off')
            return ACTION_NEST_TO_HASS.get(action, HVACAction.IDLE)
        except (KeyError, AttributeError) as e:
            _LOGGER.error(f"Error getting hvac_action: {str(e)}")
            return HVACAction.IDLE

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        try:
            return HVAC_MODE_MAP.get(
                self.device.device_data[self.device_id].get('hvac_mode', 'off'),
                HVACMode.OFF
            )
        except (KeyError, AttributeError) as e:
            _LOGGER.error(f"Error getting hvac_mode: {str(e)}")
            return HVACMode.OFF

    @property
    def fan_mode(self) -> str:
        """Return current fan mode."""
        try:
            return FAN_MODE_MAP.get(
                self.device.device_data[self.device_id].get('fan_mode', 'auto'),
                FAN_AUTO
            )
        except (KeyError, AttributeError) as e:
            _LOGGER.error(f"Error getting fan_mode: {str(e)}")
            return FAN_AUTO

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        try:
            temp = None
            target_temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
            target_temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
            current_mode = self.device.device_data[self.device_id].get('mode')
            
            if current_mode == NEST_MODE_HEAT_COOL:
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
        except Exception as e:
            _LOGGER.error(f"Failed to set temperature: {str(e)}")

    def set_humidity(self, humidity):
        """Set new target humidity."""
        try:
            humidity = int(round(float(humidity) / ROUND_TARGET_HUMIDITY_TO_NEAREST) * ROUND_TARGET_HUMIDITY_TO_NEAREST)
            humidity = max(NEST_HUMIDITY_MIN, min(NEST_HUMIDITY_MAX, humidity))
            self.device.thermostat_set_target_humidity(
                self.device_id,
                humidity,
            )
        except Exception as e:
            _LOGGER.error(f"Failed to set humidity: {str(e)}")

    def set_hvac_mode(self, hvac_mode):
        """Set operation mode."""
        try:
            if hvac_mode in MODE_HASS_TO_NEST:
                self.device.thermostat_set_mode(
                    self.device_id,
                    MODE_HASS_TO_NEST[hvac_mode],
                )
            else:
                _LOGGER.error(f"Invalid HVAC mode: {hvac_mode}")
        except Exception as e:
            _LOGGER.error(f"Failed to set HVAC mode: {str(e)}")

    def set_fan_mode(self, fan_mode: str) -> None:
        """Turn fan on/off."""
        try:
            device_data = self.device.device_data[self.device_id]
            has_fan = device_data.get('has_fan', False)
            
            if has_fan:
                if fan_mode == FAN_ON:
                    self.device.thermostat_set_fan(
                        self.device_id,
                        int(datetime.now().timestamp() + 60 * 30),
                    )
                else:
                    self.device.thermostat_set_fan(
                        self.device_id,
                        0,
                    )
            else:
                _LOGGER.warning(f"Device {self.device_id} does not have a fan")
        except Exception as e:
            _LOGGER.error(f"Failed to set fan mode: {str(e)}")

    def set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        try:
            need_eco = preset_mode == PRESET_ECO
            current_eco = self.device.device_data[self.device_id].get('eco', False)

            if need_eco != current_eco:
                self.device.thermostat_set_eco_mode(
                    self.device_id,
                    need_eco,
                )
        except Exception as e:
            _LOGGER.error(f"Failed to set preset mode: {str(e)}")

    def update(self) -> None:
        """Updates data."""
        try:
            self.device.update()
            
            # Update preset mode based on current eco state
            device_data = self.device.device_data[self.device_id]
            self._attr_preset_mode = PRESET_ECO if device_data.get('eco', False) else PRESET_NONE
        except Exception as e:
            _LOGGER.error(f"Failed to update device data: {str(e)}")
