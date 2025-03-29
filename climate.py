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
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

# Nest mode constants
NEST_MODE_HEAT_COOL = "range"
NEST_MODE_ECO = "eco"
NEST_MODE_HEAT = "heat"
NEST_MODE_COOL = "cool"
NEST_MODE_OFF = "off"

# Alternative mode format sometimes used by Nest
NEST_MODE_HEAT_COOL_ALT = "heat-cool"

# Map Home Assistant modes to Nest modes
MODE_HASS_TO_NEST = {
    HVACMode.HEAT_COOL: NEST_MODE_HEAT_COOL,
    HVACMode.COOL: NEST_MODE_COOL,
    HVACMode.HEAT: NEST_MODE_HEAT,
    HVACMode.OFF: NEST_MODE_OFF,
}

# Map Nest modes to Home Assistant modes
MODE_NEST_TO_HASS = {
    NEST_MODE_HEAT_COOL: HVACMode.HEAT_COOL,
    NEST_MODE_COOL: HVACMode.COOL,
    NEST_MODE_HEAT: HVACMode.HEAT,
    NEST_MODE_OFF: HVACMode.OFF,
    NEST_MODE_ECO: HVACMode.OFF,  # Map eco to OFF since we handle eco separately
    NEST_MODE_HEAT_COOL_ALT: HVACMode.HEAT_COOL,  # Alternative format
}

# Fan mode mapping
FAN_MODE_MAP = {
    "on": FAN_ON,
    "auto": FAN_AUTO,
}

# Map Nest actions to Home Assistant HVAC actions
ACTION_NEST_TO_HASS = {
    "off": HVACAction.IDLE,
    "heating": HVACAction.HEATING,
    "cooling": HVACAction.COOLING,
}

ROUND_TARGET_HUMIDITY_TO_NEAREST = 5
NEST_HUMIDITY_MIN = 10
NEST_HUMIDITY_MAX = 60

# Update PRESET_MODES to use string constants
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
    try:
        for thermostat in api.thermostats:
            _LOGGER.info(f"Adding nest thermostat uuid: {thermostat}")
            entities.append(NestClimate(
                device_id=thermostat,
                api=api,
                entry=config_entry,
            ))

        if not entities:
            _LOGGER.warning("No thermostats found in Nest API response")
            return

        async_add_entities(entities)
    except Exception as e:
        _LOGGER.error(f"Failed to setup Nest climate platform: {str(e)}")

class NestClimate(ClimateEntity):
    """Nest climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _unit_of_measurement = UnitOfTemperature.CELSIUS
    
    _attr_preset_modes = PRESET_MODES

def __init__(self, device_id: str, api, entry: ConfigEntry) -> None:
    """Initialize the thermostat."""
    super().__init__()
    try:
        self.device_id = device_id
        self.device = api
        self._entry = entry
        
        # Set unique ID incorporating config entry ID for multi-account support
        self._attr_unique_id = f"{entry.entry_id}_{device_id}_climate"

        device_data = self.device.device_data[device_id]
        if not device_data:
            raise KeyError(f"No device data found for thermostat {device_id}")
            
        # Set up device info with config entry linkage
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{device_id}")},
            name=device_data.get('name', "Nest Thermostat"),
            manufacturer="Nest",
            model="Thermostat",
            sw_version=device_data.get('software_version'),
            suggested_area=device_data.get('where_name'),
            via_device=(DOMAIN, entry.entry_id),
        )

        # Set supported features based on device capabilities
        supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE |
            ClimateEntityFeature.PRESET_MODE
        )

        # Add fan support only if device has a fan
        if device_data.get('has_fan', False):
            supported_features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = [FAN_ON, FAN_AUTO]
        
        self._attr_supported_features = supported_features
        
        # Set name combining device name and type
        self._attr_name = f"{device_data.get('name')} Thermostat"
        
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
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes."""
        try:
            modes = [HVACMode.OFF]  # Always include OFF
            device_data = self.device.device_data[self.device_id]
            
            if device_data.get('can_heat', False):
                modes.append(HVACMode.HEAT)
                
            if device_data.get('can_cool', False):
                modes.append(HVACMode.COOL)
                
            if device_data.get('can_heat', False) and device_data.get('can_cool', False):
                modes.append(HVACMode.HEAT_COOL)
            
            _LOGGER.debug(f"Device {self.device_id} available modes: {modes}")
            return modes
        except Exception as e:
            _LOGGER.error(f"Error getting hvac_modes: {str(e)}")
            return [HVACMode.OFF]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        try:
            device_data = self.device.device_data[self.device_id]
            mode = device_data.get('mode', 'off')
            
            _LOGGER.debug(
                f"Determining HVAC mode - "
                f"Raw mode: {mode}, "
                f"Current data: {device_data}"
            )
            
            can_heat = device_data.get('can_heat', False)
            can_cool = device_data.get('can_cool', False)
            
            _LOGGER.debug(
                f"Device {self.device_id} capabilities - "
                f"Mode: {mode}, Can Heat: {can_heat}, Can Cool: {can_cool}"
            )

            # If the device can't heat or cool, force OFF mode
            if not can_heat and not can_cool:
                _LOGGER.debug(f"Device {self.device_id} has no heating/cooling capability")
                return HVACMode.OFF

            # Try to map the mode
            mapped_mode = MODE_NEST_TO_HASS.get(mode, HVACMode.OFF)
            _LOGGER.debug(f"Initial mode mapping: {mode} -> {mapped_mode}")
            
            # Validate the mapped mode against capabilities
            if mapped_mode == HVACMode.HEAT and not can_heat:
                _LOGGER.debug(f"Device {self.device_id} cannot heat, forcing OFF mode")
                return HVACMode.OFF
            elif mapped_mode == HVACMode.COOL and not can_cool:
                _LOGGER.debug(f"Device {self.device_id} cannot cool, forcing OFF mode")
                return HVACMode.OFF
            elif mapped_mode == HVACMode.HEAT_COOL and not (can_heat and can_cool):
                _LOGGER.debug(f"Device {self.device_id} cannot heat and cool, forcing OFF mode")
                return HVACMode.OFF
                
            _LOGGER.debug(
                f"Device {self.device_id} final mode: {mapped_mode} "
                f"(can_heat: {can_heat}, can_cool: {can_cool})"
            )
            return mapped_mode
                
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
            # Check if the requested mode is supported by the device
            if hvac_mode not in self.hvac_modes:
                _LOGGER.error(f"HVAC mode {hvac_mode} not supported by device {self.device_id}")
                return

            if hvac_mode in MODE_HASS_TO_NEST:
                nest_mode = MODE_HASS_TO_NEST[hvac_mode]
                _LOGGER.debug(
                    f"Setting {self.device_id} to mode: {hvac_mode} "
                    f"(Nest mode: {nest_mode})"
                )
                
                # Force an update before setting the mode to ensure we have latest state
                self.device.update()
                
                self.device.thermostat_set_mode(
                    self.device_id,
                    nest_mode,
                )
                
                # Force another update to get the new state
                self.device.update()
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
            
            device_data = self.device.device_data[self.device_id]
            
            # Log the raw state from Nest for debugging
            _LOGGER.debug(
                f"Device {self.device_id} update - "
                f"Mode: {device_data.get('mode')}, "
                f"Action: {device_data.get('action')}, "
                f"Current temp: {device_data.get('current_temperature')}, "
                f"Target temp: {device_data.get('target_temperature')}, "
                f"Can heat: {device_data.get('can_heat')}, "
                f"Can cool: {device_data.get('can_cool')}, "
                f"Eco: {device_data.get('eco', False)}"
            )
            
            # Update preset mode based on current eco state
            self._attr_preset_mode = PRESET_ECO if device_data.get('eco', False) else PRESET_NONE
        except Exception as e:
            _LOGGER.error(f"Failed to update device data: {str(e)}")
