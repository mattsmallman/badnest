import logging

import requests
import simplejson

from time import sleep

API_URL = "https://home.nest.com"
CAMERA_WEBAPI_BASE = "https://webapi.camera.home.nest.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5) " \
             "AppleWebKit/537.36 (KHTML, like Gecko) " \
             "Chrome/75.0.3770.100 Safari/537.36"
URL_JWT = "https://nestauthproxyservice-pa.googleapis.com/v1/issue_jwt"

# Nest website's (public) API key
NEST_API_KEY = "AIzaSyAdkSIMNc51XGNEAYWasX9UOWkS5P6sZE4"

KNOWN_BUCKET_TYPES = [
    # Thermostats
    "device",
    "shared",
    # Protect
    "topaz",
    # Temperature sensors
    "kryptonite",
    # Cameras
    "quartz"
]

_LOGGER = logging.getLogger(__name__)


class NestAPI():
    def _do_request(self, method_func, url, **kwargs):
        """Execute HTTP request with retries and error handling."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = method_func(url, **kwargs)
                response.raise_for_status()
                try:
                    return response.json()
                except ValueError:
                    return response
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                _LOGGER.debug(f"Request failed, attempt {attempt + 1}/{max_retries}: {str(e)}")
                sleep(2 ** attempt)  # Exponential backoff
                if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 401:
                    _LOGGER.debug("Authentication failed, attempting to login again")
                    self.login()
                    kwargs.get('headers', {}).update({"Authorization": f"Basic {self._access_token}"})

    def __init__(self, user_id, access_token, issue_token, cookie, region):
        """Badnest Google Nest API interface."""
        self.device_data = {}
        self._wheres = {}
        self._user_id = user_id
        self._access_token = access_token
        
        # Configure session with proper connection pooling
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,    # Increase from default 10
            pool_maxsize=20,       # Increase from default 10
            max_retries=3,         # Add retry configuration
            pool_block=False       # Don't block when pool is depleted
        )
        self._session.mount('https://', adapter)
        self._session.headers.update({
            "Referer": "https://home.nest.com/",
            "User-Agent": USER_AGENT,
        })
        
        self._issue_token = issue_token
        self._cookie = cookie
        self._czfe_url = None
        self._camera_url = f'https://nexusapi-{region}1.camera.home.nest.com'
        self.cameras = []
        self.thermostats = []
        self.temperature_sensors = []
        self.hotwatercontrollers = []
        self.switches = []
        self.protects = []
        self.login()
        self._get_devices()
        self.update()

    def __getitem__(self, name):
        """Get attribute."""
        return getattr(self, name)

    def __setitem__(self, name, value):
        """Set attribute."""
        return setattr(self, name, value)

    def __delitem__(self, name):
        """Delete attribute."""
        return delattr(self, name)

    def __contains__(self, name):
        """Has attribute."""
        return hasattr(self, name)

    def login(self):
        if self._issue_token and self._cookie:
            self._login_google(self._issue_token, self._cookie)
        self._login_dropcam()

    def _login_google(self, issue_token, cookie):
        headers = {
            'User-Agent': USER_AGENT,
            'Sec-Fetch-Mode': 'cors',
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://accounts.google.com/o/oauth2/iframe',
            'cookie': cookie
        }
        response = self._do_request(self._session.get, issue_token, headers=headers)
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
        response = self._do_request(self._session.post, URL_JWT, headers=headers, params=params)
        self._user_id = response['claims']['subject']['nestId']['id']
        self._access_token = response['jwt']
        self._session.headers.update({
            "Authorization": f"Basic {self._access_token}",
        })

    def _login_dropcam(self):
        self._do_request(
            self._session.post,
            f"{API_URL}/dropcam/api/login",
            data={"access_token": self._access_token}
        )

    def _get_cameras_updates_pt2(self, sn):
        headers = {
            'User-Agent': USER_AGENT,
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://home.nest.com/',
            'cookie': f"user_token={self._access_token}"
        }
        
        response = self._do_request(
            self._session.get,
            f"{CAMERA_WEBAPI_BASE}/api/cameras.get_with_properties?uuid={sn}",
            headers=headers
        )
        
        try:
            sensor_data = response["items"][0]
            self.device_data[sn]['chime_state'] = \
                sensor_data["properties"]["doorbell.indoor_chime.enabled"]
        except (IndexError, KeyError) as e:
            _LOGGER.error(f"Error parsing camera data: {str(e)}")


    def _get_devices(self):
        response = self._do_request(
            self._session.post,
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
                    self.device_data[sn] = {}
                elif bucket.startswith('kryptonite.'):
                    sn = bucket.replace('kryptonite.', '')
                    self.temperature_sensors.append(sn)
                    self.device_data[sn] = {}
                elif bucket.startswith('device.'):
                    sn = bucket.replace('device.', '')
                    self.thermostats.append(sn)
                    self.temperature_sensors.append(sn)
                    self.hotwatercontrollers.append(sn)
                    self.device_data[sn] = {}
                elif bucket.startswith('quartz.'):
                    sn = bucket.replace('quartz.', '')
                    self.cameras.append(sn)
                    self.switches.append(sn)
                    self.device_data[sn] = {}
        except (KeyError, IndexError) as e:
            _LOGGER.error(f"Error parsing device data: {str(e)}")
            raise

    @classmethod
    def _map_nest_protect_state(cls, value):
        if value == 0:
            return "Ok"
        elif value == 1 or value == 2:
            return "Warning"
        elif value == 3:
            return "Emergency"
        else:
            return "Unknown"

    def update(self):
        try:
            # Get friendly names
            response = self._do_request(
                self._session.post,
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
            response = self._do_request(
                self._session.post,
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
                # Thermostats (thermostat and sensors system)
                if bucket["object_key"].startswith(
                        f"shared.{sn}"):
                    self.device_data[sn]['current_temperature'] = \
                        sensor_data["current_temperature"]
                    self.device_data[sn]['target_temperature'] = \
                        sensor_data["target_temperature"]
                    self.device_data[sn]['hvac_ac_state'] = \
                        sensor_data["hvac_ac_state"]
                    self.device_data[sn]['hvac_heater_state'] = \
                        sensor_data["hvac_heater_state"]
                    self.device_data[sn]['target_temperature_high'] = \
                        sensor_data["target_temperature_high"]
                    self.device_data[sn]['target_temperature_low'] = \
                        sensor_data["target_temperature_low"]
                    self.device_data[sn]['can_heat'] = \
                        sensor_data["can_heat"]
                    self.device_data[sn]['can_cool'] = \
                        sensor_data["can_cool"]
                    self.device_data[sn]['mode'] = \
                        sensor_data["target_temperature_type"]
                    if self.device_data[sn]['hvac_ac_state']:
                        self.device_data[sn]['action'] = "cooling"
                    elif self.device_data[sn]['hvac_heater_state']:
                        self.device_data[sn]['action'] = "heating"
                    else:
                        self.device_data[sn]['action'] = "off"
                # Thermostats, pt 2
                elif bucket["object_key"].startswith(
                        f"device.{sn}"):
                    self.device_data[sn]['name'] = self._wheres[
                        sensor_data['where_id']
                    ]
                    # When acts as a sensor
                    if 'backplate_temperature' in sensor_data:
                        self.device_data[sn]['temperature'] = \
                            sensor_data['backplate_temperature']
                    if 'battery_level' in sensor_data:
                        self.device_data[sn]['battery_level'] = \
                            sensor_data['battery_level']

                    if sensor_data.get('description', None):
                        self.device_data[sn]['name'] += \
                            f' ({sensor_data["description"]})'
                    self.device_data[sn]['name'] += ' Thermostat'
                    self.device_data[sn]['has_fan'] = \
                        sensor_data["has_fan"]
                    self.device_data[sn]['fan'] = \
                        sensor_data["fan_timer_timeout"]
                    self.device_data[sn]['current_humidity'] = \
                        sensor_data["current_humidity"]
                    self.device_data[sn]['target_humidity'] = \
                        sensor_data["target_humidity"]
                    self.device_data[sn]['target_humidity_enabled'] = \
                        sensor_data["target_humidity_enabled"]
                    if sensor_data["eco"]["mode"] == 'manual-eco' or \
                            sensor_data["eco"]["mode"] == 'auto-eco':
                        self.device_data[sn]['eco'] = True
                    else:
                        self.device_data[sn]['eco'] = False

                    # Hot water
                    # - Status
                    self.device_data[sn]['has_hot_water_control'] = \
                        sensor_data["has_hot_water_control"]
                    self.device_data[sn]['hot_water_status'] = \
                        sensor_data["hot_water_active"]
                    self.device_data[sn]['hot_water_actively_heating'] = \
                        sensor_data["hot_water_boiling_state"]
                    self.device_data[sn]['hot_water_away_active'] = \
                        sensor_data["hot_water_away_active"]
                    # - Status/Settings
                    self.device_data[sn]['hot_water_timer_mode'] = \
                        sensor_data["hot_water_mode"]
                    self.device_data[sn]['hot_water_away_setting'] = \
                        sensor_data["hot_water_away_enabled"]
                    self.device_data[sn]['hot_water_boost_setting'] = \
                        sensor_data["hot_water_boost_time_to_end"]

                # Protect
                elif bucket["object_key"].startswith(
                        f"topaz.{sn}"):
                    self.device_data[sn]['name'] = self._wheres[
                        sensor_data['where_id']
                    ]
                    if sensor_data.get('description', None):
                        self.device_data[sn]['name'] += \
                            f' ({sensor_data["description"]})'
                    self.device_data[sn]['name'] += ' Protect'
                    self.device_data[sn]['co_status'] = \
                        self._map_nest_protect_state(sensor_data['co_status'])
                    self.device_data[sn]['smoke_status'] = \
                        self._map_nest_protect_state(sensor_data['smoke_status'])
                    self.device_data[sn]['battery_health_state'] = \
                        self._map_nest_protect_state(sensor_data['battery_health_state'])
                # Temperature sensors
                elif bucket["object_key"].startswith(
                        f"kryptonite.{sn}"):
                    self.device_data[sn]['name'] = self._wheres[
                        sensor_data['where_id']
                    ]
                    if sensor_data.get('description', None):
                        self.device_data[sn]['name'] += \
                            f' ({sensor_data["description"]})'
                    self.device_data[sn]['name'] += ' Temperature'
                    self.device_data[sn]['temperature'] = \
                        sensor_data['current_temperature']
                    self.device_data[sn]['battery_level'] = \
                        sensor_data['battery_level']
                # Cameras
                elif bucket["object_key"].startswith(
                        f"quartz.{sn}"):
                    self.device_data[sn]['name'] = self._wheres[sensor_data['where_id']]
                    self.device_data[sn]['model'] = \
                        sensor_data["model"]
                    self.device_data[sn]['streaming_state'] = \
                        sensor_data["streaming_state"]
                    if 'indoor_chime' in sensor_data["capabilities"]:
                        self.device_data[sn]['indoor_chime'] = True
                        self._get_cameras_updates_pt2(sn)
                    else:
                        self.device_data[sn]['indoor_chime'] = False

        except (simplejson.errors.JSONDecodeError, KeyError, IndexError) as e:
            # Catch any data parsing errors but don't retry since _do_request already handles retries
            _LOGGER.error(f"Error parsing update data: {str(e)}")

    def thermostat_set_temperature(self, device_id, temp, temp_high=None):
        """Set target temperature for thermostat."""
        if device_id not in self.thermostats:
            return

        value = {"target_temperature": temp} if temp_high is None else {
            "target_temperature_low": temp,
            "target_temperature_high": temp_high,
        }
        
        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'shared.{device_id}',
                        "op": "MERGE",
                        "value": value,
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def thermostat_set_target_humidity(self, device_id, humidity):
        """Set target humidity for thermostat."""
        if device_id not in self.thermostats:
            return

        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{device_id}',
                        "op": "MERGE",
                        "value": {"target_humidity": humidity},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def thermostat_set_mode(self, device_id, mode):
        """Set operation mode for thermostat."""
        if device_id not in self.thermostats:
            return

        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'shared.{device_id}',
                        "op": "MERGE",
                        "value": {"target_temperature_type": mode},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def thermostat_set_fan(self, device_id, date):
        """Set fan timer for thermostat."""
        if device_id not in self.thermostats:
            return

        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{device_id}',
                        "op": "MERGE",
                        "value": {"fan_timer_timeout": date},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def thermostat_set_eco_mode(self, device_id, state):
        """Set eco mode for thermostat."""
        if device_id not in self.thermostats:
            return

        mode = 'manual-eco' if state else 'schedule'
        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{device_id}',
                        "op": "MERGE",
                        "value": {"eco": {"mode": mode}},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def hotwater_set_boost(self, device_id, time):
        """Set hot water boost timer."""
        if device_id not in self.hotwatercontrollers:
            return

        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{device_id}',
                        "op": "MERGE",
                        "value": {"hot_water_boost_time_to_end": time},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def hotwater_set_away_mode(self, device_id, away_mode):
        """Set hot water away mode."""
        if device_id not in self.hotwatercontrollers:
            return

        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{device_id}',
                        "op": "MERGE",
                        "value": {"hot_water_away_enabled": away_mode},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )

    def hotwater_set_mode(self, device_id, mode):
        """Set hot water operating mode."""
        if device_id not in self.hotwatercontrollers:
            return

        self._do_request(
            self._session.post,
            f"{self._czfe_url}/v5/put",
            json={
                "objects": [
                    {
                        "object_key": f'device.{device_id}',
                        "op": "MERGE",
                        "value": {"hot_water_mode": mode},
                    }
                ]
            },
            headers={"Authorization": f"Basic {self._access_token}"},
        )


    def _camera_set_properties(self, device_id, property, value):
        """Set camera properties with automatic retries and error handling."""
        if device_id not in self.cameras:
            return

        headers = {
            'User-Agent': USER_AGENT,
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://home.nest.com/',
            'cookie': f"user_token={self._access_token}"
        }
        response = self._do_request(
            self._session.post,
            f"{CAMERA_WEBAPI_BASE}/api/dropcams.set_properties",
            data={property: value, "uuid": device_id},
            headers=headers
        )
        
        return response.get("items", [])

    def camera_turn_off(self, device_id):
        if device_id not in self.cameras:
            return

        return self._camera_set_properties(device_id, "streaming.enabled", "false")

    def camera_turn_on(self, device_id):
        if device_id not in self.cameras:
            return

        return self._camera_set_properties(device_id, "streaming.enabled", "true")

    def camera_get_image(self, device_id, now):
        """Get camera image with automatic retries and error handling."""
        if device_id not in self.cameras:
            return

        headers = {
            'User-Agent': USER_AGENT,
            'X-Requested-With': 'XmlHttpRequest',
            'Referer': 'https://home.nest.com/',
            'cookie': f"user_token={self._access_token}"
        }
        response = self._do_request(
            self._session.get,
            f'{self._camera_url}/get_image?uuid={device_id}&cachebuster={now}',
            headers=headers
        )
        
        return response.content if hasattr(response, 'content') else None

    def camera_turn_chime_off(self, device_id):
        if device_id not in self.switches:
            return

        return self._camera_set_properties(device_id, "doorbell.indoor_chime.enabled", "false")

    def camera_turn_chime_on(self, device_id):
        if device_id not in self.switches:
            return

        return self._camera_set_properties(device_id, "doorbell.indoor_chime.enabled", "true")
