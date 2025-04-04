"""Async API client for Nest."""
import logging
import asyncio
import aiohttp
import simplejson
from typing import Dict, Any, Optional

API_URL = "https://home.nest.com"
CAMERA_WEBAPI_BASE = "https://webapi.camera.home.nest.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) " \
             "AppleWebKit/537.36 (KHTML, like Gecko) " \
             "Chrome/75.0.3770.100 Safari/537.36"
URL_JWT = "https://nestauthproxyservice-pa.googleapis.com/v1/issue_jwt"

# Nest website's (public) API key
NEST_API_KEY = "AIzaSyAdkSIMNc51XGNEAYWasX9UOWkS5P6sZE4"

KNOWN_BUCKET_TYPES = [
    "device",     # Thermostats
    "shared",     # Thermostats
    "topaz",      # Protect
    "kryptonite", # Temperature sensors
    "quartz"      # Cameras
]

_LOGGER = logging.getLogger(__name__)

class NestAPI:
    """Async implementation of Nest API."""

    def __init__(self, user_id, access_token, issue_token, cookie, region):
        """Initialize the API."""
        self.device_data: Dict[str, Any] = {}
        self._wheres: Dict[str, str] = {}
        self._user_id = user_id
        self._access_token = access_token
        self._issue_token = issue_token
        self._cookie = cookie
        self._czfe_url: Optional[str] = None
        self._camera_url = f'https://nexusapi-{region}1.camera.home.nest.com'
        
        self.cameras = []
        self.thermostats = []
        self.temperature_sensors = []
        self.hotwatercontrollers = []
        self.switches = []
        self.protects = []

        # Session will be created during login
        self._session: Optional[aiohttp.ClientSession] = None
        self._headers = {
            "Referer": "https://home.nest.com/",
            "User-Agent": USER_AGENT,
        }

    async def _create_session(self) -> None:
        """Create aiohttp session with proper settings."""
        if self._session is None:
            conn = aiohttp.TCPConnector(
                limit=20,  # Maximum number of concurrent connections
                ttl_dns_cache=300,  # DNS cache TTL
            )
            self._session = aiohttp.ClientSession(
                connector=conn,
                headers=self._headers,
            )

    async def _do_request(self, method: str, url: str, **kwargs) -> Any:
        """Execute HTTP request with retries and error handling."""
        await self._create_session()
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                async with self._session.request(method, url, **kwargs) as response:
                    response.raise_for_status()
                    try:
                        return await response.json()
                    except (ValueError, aiohttp.ContentTypeError):
                        return response
                        
            except aiohttp.ClientError as e:
                if attempt == max_retries - 1:
                    raise
                _LOGGER.debug(f"Request failed, attempt {attempt + 1}/{max_retries}: {str(e)}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
                if isinstance(e, aiohttp.ClientResponseError) and e.status == 401:
                    _LOGGER.debug("Authentication failed, attempting to login again")
                    await self.login()
                    if 'headers' in kwargs:
                        kwargs['headers'].update({"Authorization": f"Basic {self._access_token}"})

    async def login(self) -> None:
        """Log in to the Nest API."""
        if self._issue_token and self._cookie:
            await self._login_google(self._issue_token, self._cookie)
        await self._login_dropcam()

    async def _login_google(self, issue_token: str, cookie: str) -> None:
        """Login using Google authentication."""
        headers = {
            'User-Agent': USER_AGENT,
            'Sec-Fetch-Mode': 'cors',
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://accounts.google.com/o/oauth2/iframe',
            'cookie': cookie
        }
        
        response = await self._do_request('GET', issue_token, headers=headers)
        access_token = response['access_token']

        headers = {
            'User-Agent': USER_AGENT,
            'Authorization': 'Bearer ' + access_token,
            'x-goog-api-key': NEST_API_KEY,
            'Referer': 'https://home.nest.com'
        }
        params = {
            "embed_google_oauth_access_token": True,
            "expire_after": '3600s',
            "google_oauth_access_token": access_token,
            "policy_id": 'authproxy-oauth-policy'
        }
        
        response = await self._do_request('POST', URL_JWT, headers=headers, params=params)
        self._user_id = response['claims']['subject']['nestId']['id']
        self._access_token = response['jwt']
        self._headers.update({
            "Authorization": f"Basic {self._access_token}",
        })

    async def _login_dropcam(self) -> None:
        """Login to Dropcam API."""
        await self._do_request(
            'POST',
            f"{API_URL}/dropcam/api/login",
            data={"access_token": self._access_token}
        )

    async def _get_cameras_updates_pt2(self, sn: str) -> None:
        """Get additional camera properties."""
        headers = {
            'User-Agent': USER_AGENT,
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://home.nest.com/',
            'cookie': f"user_token={self._access_token}"
        }
        
        response = await self._do_request(
            'GET',
            f"{CAMERA_WEBAPI_BASE}/api/cameras.get_with_properties?uuid={sn}",
            headers=headers
        )
        
        try:
            sensor_data = response["items"][0]
            self.device_data[sn]['chime_state'] = \
                sensor_data["properties"]["doorbell.indoor_chime.enabled"]
        except (IndexError, KeyError) as e:
            _LOGGER.error(f"Error parsing camera data: {str(e)}")

    async def _get_devices(self) -> None:
        """Get list of devices."""
        response = await self._do_request(
            'POST',
            f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
            json={
                "known_bucket_types": ["buckets"],
                "known_bucket_versions": [],
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

        try:
            self._czfe_url = response["service_urls"]["urls"]["czfe_url"]

            buckets = response['updated_buckets'][0]['value']['buckets']
            for bucket in buckets:
                if bucket.startswith('topaz.'):
                    sn = bucket.replace('topaz.', '')
                    self.protects.append(sn)
                    # Initialize static device data
                    bucket_data = response.get('objects', {}).get(bucket, {})
                    self.device_data[sn] = {
                        'model': bucket_data.get('model'),
                        'device_info': {
                            'color': bucket_data.get('device_external_color'),
                            'locale': bucket_data.get('device_locale'),
                            'installed_locale': bucket_data.get('installed_locale')
                        },
                        'born_on_date': bucket_data.get('device_born_on_date_utc_secs'),
                        'replace_by_date': bucket_data.get('replace_by_date_utc_secs'),
                        'kl_software_version': bucket_data.get('kl_software_version'),
                        'network': {
                            'wifi': {
                                'mac': bucket_data.get('wifi_mac_address'),
                                'regulatory_domain': bucket_data.get('wifi_regulatory_domain')
                            },
                            'thread': {
                                'mac': bucket_data.get('thread_mac_address')
                            }
                        }
                    }
                elif bucket.startswith('kryptonite.'):
                    sn = bucket.replace('kryptonite.', '')
                    self.temperature_sensors.append(sn)
                    self.device_data[sn] = {}
                elif bucket.startswith('device.'):
                    sn = bucket.replace('device.', '')
                    _LOGGER.debug(f"Processing device bucket for {sn}")
                    self.thermostats.append(sn)
                    self.temperature_sensors.append(sn)
                    self.hotwatercontrollers.append(sn)  # Add all thermostats as potential hot water controllers
                    self.device_data[sn] = {}
                    _LOGGER.debug(f"Added {sn} to hot water controllers")
                elif bucket.startswith('quartz.'):
                    sn = bucket.replace('quartz.', '')
                    self.cameras.append(sn)
                    self.switches.append(sn)
                    self.device_data[sn] = {}
        except (KeyError, IndexError) as e:
            _LOGGER.error(f"Error parsing device data: {str(e)}")
            raise

    @staticmethod
    def _map_nest_protect_state(value: int) -> str:
        """Map Nest Protect state values to strings."""
        if value == 0:
            return "Ok"
        elif value == 1 or value == 2:
            return "Warning"
        elif value == 3:
            return "Emergency"
        else:
            return "Unknown"

    async def update(self) -> None:
        """Update data from Nest API."""
        try:
            _LOGGER.debug("Starting device update")
            
            # Store previous state for comparison
            previous_states = {
                device_id: dict(data) for device_id, data in self.device_data.items()
            }
            
            # Get friendly names
            _LOGGER.debug("Fetching friendly names")
            response = await self._do_request(
                'POST',
                f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
                json={
                    "known_bucket_types": ["where"],
                    "known_bucket_versions": [],
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )

            for bucket in response["updated_buckets"]:
                sensor_data = bucket["value"]
                sn = bucket["object_key"].split('.')[1]
                if bucket["object_key"].startswith(f"where.{sn}"):
                    wheres = sensor_data['wheres']
                    for where in wheres:
                        self._wheres[where['where_id']] = where['name']

            # Get device data
            _LOGGER.debug("Fetching device data")
            response = await self._do_request(
                'POST',
                f"{API_URL}/api/0.1/user/{self._user_id}/app_launch",
                json={
                    "known_bucket_types": KNOWN_BUCKET_TYPES,
                    "known_bucket_versions": [],
                },
                headers={"Authorization": f"Basic {self._access_token}"},
            )

            for bucket in response["updated_buckets"]:
                sensor_data = bucket["value"]
                sn = bucket["object_key"].split('.')[1]
                
                # Process each device type
                if bucket["object_key"].startswith(f"shared.{sn}"):
                    await self._process_thermostat_shared(sn, sensor_data, previous_states)
                elif bucket["object_key"].startswith(f"device.{sn}"):
                    await self._process_thermostat_device(sn, sensor_data)
                elif bucket["object_key"].startswith(f"topaz.{sn}"):
                    await self._process_protect(sn, sensor_data)
                elif bucket["object_key"].startswith(f"kryptonite.{sn}"):
                    await self._process_temperature_sensor(sn, sensor_data)
                elif bucket["object_key"].startswith(f"quartz.{sn}"):
                    await self._process_camera(sn, sensor_data)

        except (simplejson.errors.JSONDecodeError, KeyError, IndexError) as e:
            _LOGGER.error(f"Error parsing update data: {str(e)}")
        except Exception as e:
            _LOGGER.error(f"Unexpected error during update: {str(e)}", exc_info=True)

    async def _process_thermostat_shared(self, sn: str, sensor_data: Dict, previous_states: Dict) -> None:
        """Process shared thermostat data."""
        _LOGGER.debug(f"Processing shared data for thermostat {sn}")
        
        self.device_data[sn]['current_temperature'] = sensor_data["current_temperature"]
        self.device_data[sn]['target_temperature'] = sensor_data["target_temperature"]
        self.device_data[sn]['hvac_ac_state'] = sensor_data["hvac_ac_state"]
        self.device_data[sn]['hvac_heater_state'] = sensor_data["hvac_heater_state"]
        self.device_data[sn]['target_temperature_high'] = sensor_data["target_temperature_high"]
        self.device_data[sn]['target_temperature_low'] = sensor_data["target_temperature_low"]
        self.device_data[sn]['can_heat'] = sensor_data["can_heat"]
        self.device_data[sn]['can_cool'] = sensor_data["can_cool"]
        self.device_data[sn]['mode'] = sensor_data["target_temperature_type"]
        
        if self.device_data[sn]['hvac_ac_state']:
            self.device_data[sn]['action'] = "cooling"
        elif self.device_data[sn]['hvac_heater_state']:
            self.device_data[sn]['action'] = "heating"
        else:
            self.device_data[sn]['action'] = "off"

    async def _process_thermostat_device(self, sn: str, sensor_data: Dict) -> None:
        """Process thermostat device data."""
        _LOGGER.debug(f"Processing device data for thermostat {sn}")
        
        self.device_data[sn]['name'] = self._wheres[sensor_data['where_id']]
        
        if sensor_data.get('description', None):
            self.device_data[sn]['name'] += f' ({sensor_data["description"]})'
        self.device_data[sn]['name'] += ' Thermostat'
        
        # Basic thermostat data
        self.device_data[sn]['has_fan'] = sensor_data["has_fan"]
        self.device_data[sn]['fan'] = sensor_data["fan_timer_timeout"]
        self.device_data[sn]['current_humidity'] = sensor_data["current_humidity"]
        self.device_data[sn]['target_humidity'] = sensor_data["target_humidity"]
        self.device_data[sn]['target_humidity_enabled'] = sensor_data["target_humidity_enabled"]
        
        # Temperature sensor data
        if 'backplate_temperature' in sensor_data:
            self.device_data[sn]['temperature'] = sensor_data['backplate_temperature']
        if 'battery_level' in sensor_data:
            self.device_data[sn]['battery_level'] = sensor_data['battery_level']
            
        # Eco mode
        if sensor_data["eco"]["mode"] in ['manual-eco', 'auto-eco']:
            self.device_data[sn]['eco'] = True
        else:
            self.device_data[sn]['eco'] = False

        # Hot water data
        _LOGGER.debug(f"Processing hot water data for {sn}")
        has_hw = sensor_data.get("has_hot_water_control", False)
        _LOGGER.debug(f"Device {sn} has_hot_water_control: {has_hw}")
        
        if has_hw:
            self.device_data[sn]['has_hot_water_control'] = True
            self.device_data[sn]['hot_water_status'] = sensor_data.get("hot_water_active", False)
            self.device_data[sn]['hot_water_actively_heating'] = sensor_data.get("hot_water_boiling_state", False)
            self.device_data[sn]['hot_water_away_active'] = sensor_data.get("hot_water_away_active", False)
            self.device_data[sn]['hot_water_timer_mode'] = sensor_data.get("hot_water_mode", "off")
            self.device_data[sn]['hot_water_away_setting'] = sensor_data.get("hot_water_away_enabled", False)
            self.device_data[sn]['hot_water_boost_setting'] = sensor_data.get("hot_water_boost_time_to_end", 0)
            _LOGGER.debug(f"Hot water data for {sn}: {self.device_data[sn]}")
        else:
            self.device_data[sn]['has_hot_water_control'] = False

    async def _process_protect(self, sn: str, sensor_data: Dict) -> None:
        """Process Nest Protect data."""
        _LOGGER.debug(f"Processing protect data for {sn}")
        
        # Update device name
        self.device_data[sn]['name'] = self._wheres[sensor_data['where_id']]
        if sensor_data.get('description', None):
            self.device_data[sn]['name'] += f' ({sensor_data["description"]})'
        self.device_data[sn]['name'] += ' Protect'
        
        # Update dynamic status values
        self.device_data[sn].update({
            'co_status': self._map_nest_protect_state(sensor_data['co_status']),
            'smoke_status': self._map_nest_protect_state(sensor_data['smoke_status']),
            'battery_health_state': self._map_nest_protect_state(sensor_data['battery_health_state']),
            'battery_level': sensor_data.get('battery_level'),
            
            # Dynamic features state
            'steam_detection_enable': sensor_data.get('steam_detection_enable'),
            'night_light': {
                'enabled': sensor_data.get('night_light_enable'),
                'brightness': sensor_data.get('night_light_brightness'),
                'continuous': sensor_data.get('night_light_continuous')
            },
            'auto_away': sensor_data.get('auto_away'),
            
            # Latest test results
            'component_tests': {
                'smoke': sensor_data.get('component_smoke_test_passed'),
                'co': sensor_data.get('component_co_test_passed'),
                'humidity': sensor_data.get('component_hum_test_passed'),
                'temperature': sensor_data.get('component_temp_test_passed'),
                'pir': sensor_data.get('component_pir_test_passed'),
                'audio': sensor_data.get('component_speaker_test_passed'),
                'wifi': sensor_data.get('component_wifi_test_passed')
            },
            
            # Dynamic network info
            'network': {
                'wifi': {'ip': sensor_data.get('wifi_ip_address')},
                'thread': {'ip': sensor_data.get('thread_ip_address')}
            },
            
            # Latest test timestamps
            'last_test_start': sensor_data.get('latest_manual_test_start_utc_secs'),
            'last_test_end': sensor_data.get('latest_manual_test_end_utc_secs'),
            'last_audio_test_start': sensor_data.get('last_audio_self_test_start_utc_secs'),
            'last_audio_test_end': sensor_data.get('last_audio_self_test_end_utc_secs'),
        })

    async def _process_temperature_sensor(self, sn: str, sensor_data: Dict) -> None:
        """Process temperature sensor data."""
        _LOGGER.debug(f"Processing temperature sensor data for {sn}")
        
        self.device_data[sn]['name'] = self._wheres[sensor_data['where_id']]
        if sensor_data.get('description', None):
            self.device_data[sn]['name'] += f' ({sensor_data["description"]})'
        self.device_data[sn]['name'] += ' Temperature'
        
        self.device_data[sn]['temperature'] = sensor_data['current_temperature']
        self.device_data[sn]['battery_level'] = sensor_data['battery_level']

    async def _process_camera(self, sn: str, sensor_data: Dict) -> None:
        """Process camera data."""
        _LOGGER.debug(f"Processing camera data for {sn}")
        
        self.device_data[sn]['name'] = self._wheres[sensor_data['where_id']]
        self.device_data[sn]['model'] = sensor_data["model"]
        self.device_data[sn]['streaming_state'] = sensor_data["streaming_state"]
        
        if 'indoor_chime' in sensor_data["capabilities"]:
            self.device_data[sn]['indoor_chime'] = True
            await self._get_cameras_updates_pt2(sn)
        else:
            self.device_data[sn]['indoor_chime'] = False

    async def thermostat_set_temperature(self, device_id: str, target_temp: float, target_temp_high: float = None) -> None:
        """Set target temperature or range for thermostat."""
        if device_id not in self.thermostats:
            return

        try:
            if target_temp_high is not None:
                value = {
                    "target_temperature_low": target_temp,
                    "target_temperature_high": target_temp_high,
                    "target_temperature_type": "range"
                }
            else:
                value = {
                    "target_temperature": target_temp,
                    "target_temperature_type": self.device_data[device_id]['mode']
                }

            data = {
                "objects": [{
                    "object_key": f"shared.{device_id}",
                    "op": "MERGE",
                    "value": value
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set temperature: {str(e)}")
            await self.login()
            await self.thermostat_set_temperature(device_id, target_temp, target_temp_high)

    async def thermostat_set_mode(self, device_id: str, mode: str) -> None:
        """Set operation mode for thermostat."""
        if device_id not in self.thermostats:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"shared.{device_id}",
                    "op": "MERGE",
                    "value": {"target_temperature_type": mode}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set mode: {str(e)}")
            await self.login()
            await self.thermostat_set_mode(device_id, mode)

    async def thermostat_set_fan(self, device_id: str, end_timestamp: int) -> None:
        """Set fan timer for thermostat."""
        if device_id not in self.thermostats:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"device.{device_id}",
                    "op": "MERGE",
                    "value": {"fan_timer_timeout": end_timestamp}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set fan: {str(e)}")
            await self.login()
            await self.thermostat_set_fan(device_id, end_timestamp)

    async def thermostat_set_eco_mode(self, device_id: str, eco_enable: bool) -> None:
        """Set eco mode for thermostat."""
        if device_id not in self.thermostats:
            return

        try:
            mode = "manual-eco" if eco_enable else "schedule"
            data = {
                "objects": [{
                    "object_key": f"device.{device_id}",
                    "op": "MERGE",
                    "value": {"eco": {"mode": mode}}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set eco mode: {str(e)}")
            await self.login()
            await self.thermostat_set_eco_mode(device_id, eco_enable)

    async def hotwater_set_mode(self, device_id: str, mode: str) -> None:
        """Set hot water operation mode."""
        if device_id not in self.hotwatercontrollers:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"device.{device_id}",
                    "op": "MERGE",
                    "value": {"hot_water_mode": mode}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set hot water mode: {str(e)}")
            await self.login()
            await self.hotwater_set_mode(device_id, mode)

    async def hotwater_set_away_mode(self, device_id: str, away_mode: bool) -> None:
        """Set hot water away mode."""
        if device_id not in self.hotwatercontrollers:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"device.{device_id}",
                    "op": "MERGE",
                    "value": {"hot_water_away_enabled": away_mode}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set hot water away mode: {str(e)}")
            await self.login()
            await self.hotwater_set_away_mode(device_id, away_mode)

    async def hotwater_set_boost(self, device_id: str, time: int) -> None:
        """Set hot water boost mode with end timestamp."""
        if device_id not in self.hotwatercontrollers:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"device.{device_id}",
                    "op": "MERGE",
                    "value": {"hot_water_boost_time_to_end": time}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to set hot water boost: {str(e)}")
            await self.login()
            await self.hotwater_set_boost(device_id, time)

    async def camera_turn_off(self, device_id: str) -> None:
        """Turn off camera streaming."""
        if device_id not in self.cameras:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"quartz.{device_id}",
                    "op": "MERGE",
                    "value": {"streaming.enabled": False}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to turn off camera: {str(e)}")
            await self.login()
            await self.camera_turn_off(device_id)

    async def camera_turn_on(self, device_id: str) -> None:
        """Turn on camera streaming."""
        if device_id not in self.cameras:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"quartz.{device_id}",
                    "op": "MERGE",
                    "value": {"streaming.enabled": True}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to turn on camera: {str(e)}")
            await self.login()
            await self.camera_turn_on(device_id)

    async def camera_get_image(self, device_id: str, now: int) -> bytes | None:
        """Return a still image response from the camera."""
        if device_id not in self.cameras:
            return None

        try:
            headers = {
                'User-Agent': USER_AGENT,
                'X-Requested-With': 'XmlHttpRequest',
                'Referer': 'https://home.nest.com/',
                'cookie': f"user_token={self._access_token}"
            }
            
            response = await self._do_request(
                'GET',
                f"{self._camera_url}/get_image?uuid={device_id}&cachebuster={now}",
                headers=headers
            )
            
            return response.content
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to get camera image: {str(e)}")
            await self.login()
            return await self.camera_get_image(device_id, now)

    async def camera_turn_chime_off(self, device_id: str) -> None:
        """Turn off camera indoor chime."""
        if device_id not in self.switches:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"quartz.{device_id}",
                    "op": "MERGE",
                    "value": {"doorbell.indoor_chime.enabled": False}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to turn off camera chime: {str(e)}")
            await self.login()
            await self.camera_turn_chime_off(device_id)

    async def camera_turn_chime_on(self, device_id: str) -> None:
        """Turn on camera indoor chime."""
        if device_id not in self.switches:
            return

        try:
            data = {
                "objects": [{
                    "object_key": f"quartz.{device_id}",
                    "op": "MERGE",
                    "value": {"doorbell.indoor_chime.enabled": True}
                }]
            }
            
            await self._do_request(
                'POST',
                f"{self._czfe_url}/v5/put",
                headers={"Authorization": f"Basic {self._access_token}"},
                json=data
            )
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Failed to turn on camera chime: {str(e)}")
            await self.login()
            await self.camera_turn_chime_on(device_id)

    async def close(self) -> None:
        """Close the session."""
        if self._session:
            await self._session.close()
            self._session = None
