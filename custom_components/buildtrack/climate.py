import asyncio
import logging
from datetime import timedelta

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    HVACAction,
    ClimateEntityFeature,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Refresh BuildTrack climate state from the API every 10 seconds.
SCAN_INTERVAL = timedelta(seconds=10)


def get_location(device):
    location = device.get("location")

    if location and str(location).strip():
        return str(location).strip()

    return None


def normalize_temperature_to_celsius(value):
    try:
        temp = float(value)

        # If API returns Fahrenheit like 70, 75, 80 convert to Celsius.
        # Normal AC Celsius values are usually below 45.
        if temp > 45:
            temp = (temp - 32) * 5 / 9

        return round(temp, 1)

    except Exception:
        return None


async def ensure_area(hass, location):
    area_registry = ar.async_get(hass)
    area = area_registry.async_get_area_by_name(location)

    if area is None:
        area = area_registry.async_create(location)

    return area


async def assign_device_to_area(hass, device_identifier, location):
    if not location:
        return

    area = await ensure_area(hass, location)
    device_registry = dr.async_get(hass)

    device = device_registry.async_get_device(
        identifiers={(DOMAIN, device_identifier)}
    )

    if device and device.area_id != area.id:
        device_registry.async_update_device(
            device.id,
            area_id=area.id,
        )

        _LOGGER.warning(
            "BuildTrack climate device assigned to area %s",
            location,
        )


async def async_setup_entry(hass, entry, async_add_entities, discovery_info=None):
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data["devices"]
    api = data["api"]

    climates = []

    _LOGGER.warning(
        "BUILTRACK CLIMATE SETUP START | total_devices=%s",
        len(devices),
    )

    for device in devices:
        device_types = device.get("type", [])

        _LOGGER.warning(
            "BUILTRACK CLIMATE DEVICE CHECK | name=%s | id=%s | key=%s | type=%s",
            device.get("entityName"),
            device.get("entityId"),
            device.get("entityKey"),
            device_types,
        )

        if (
            "THERMOSTAT" in device_types
            or "AC" in device_types
            or "AIR CONDITIONER" in device_types
        ):
            climates.append(BuildTrackClimate(hass, api, device))

            _LOGGER.warning(
                "BUILTRACK CLIMATE ADDED | %s",
                device.get("entityName"),
            )

    _LOGGER.warning(
        "BUILTRACK CLIMATE SETUP COMPLETE | total_added=%s",
        len(climates),
    )

    # Read the latest BuildTrack state before the entities first appear in HA.
    async_add_entities(climates, update_before_add=True)


class BuildTrackClimate(ClimateEntity):
    # Allow Home Assistant to call async_update periodically so changes made
    # from the BuildTrack application are reflected in Home Assistant.
    should_poll = True

    def __init__(self, hass, api, device):
        self._hass = hass
        self._api = api
        self._device = device

        self._entity_id = device.get("entityId")
        self._entity_key = device.get("entityKey")

        self._attr_name = device.get("entityName")
        self._attr_unique_id = self._entity_id

        self._temp_task = None

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_current_temperature = None
        self._attr_target_temperature = 24
        self._attr_min_temp = 16
        self._attr_max_temp = 32
        self._attr_target_temperature_step = 1

        self._attr_hvac_modes = [
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.OFF,
        ]

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = HVACAction.OFF

        self._attr_fan_modes = ["low", "medium", "high"]
        self._attr_fan_mode = "low"

        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
        )

        _LOGGER.warning(
            "BUILTRACK CLIMATE INIT | name=%s | id=%s | key=%s",
            self._attr_name,
            self._entity_id,
            self._entity_key,
        )

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entity_id)},
            "name": self._attr_name,
            "manufacturer": self._device.get("manufacturer", "BuildTrack"),
            "model": ", ".join(self._device.get("type", [])),
        }

    @property
    def suggested_area(self):
        return get_location(self._device)

    @property
    def temperature_unit(self):
        """Return the native temperature unit used by this device/API."""
        return UnitOfTemperature.CELSIUS

    async def async_added_to_hass(self):
        _LOGGER.warning(
            "BUILTRACK CLIMATE ADDED TO HASS | %s",
            self._attr_name,
        )

        location = get_location(self._device)

        if location:
            await assign_device_to_area(
                self._hass,
                self._entity_id,
                location,
            )

    async def _control_device(self, state, speed=None):
        if speed is None:
            speed = self._attr_fan_mode or ""

        payload = {
            "entityId": self._entity_id,
            "entityKey": self._entity_key,
            "state": state,
            "speed": speed,
        }

        _LOGGER.warning(
            "BUILTRACK CLIMATE CONTROL API CALL | name=%s | payload=%s",
            self._attr_name,
            payload,
        )

        try:
            response = await self._api.call(
                endpoint=f"/controlDevice/{self._entity_id}",
                method="POST",
                payload=payload,
            )

            _LOGGER.warning(
                "BUILTRACK CLIMATE CONTROL API RESPONSE | name=%s | response=%s",
                self._attr_name,
                response,
            )

            return response

        except Exception as err:
            _LOGGER.exception(
                "BUILTRACK CLIMATE CONTROL API ERROR | name=%s | payload=%s | error=%s",
                self._attr_name,
                payload,
                err,
            )
            return None

    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get("temperature")

        if temperature is None:
            return

        # Home Assistant may send the value using the UI/user temperature unit.
        # Normalize it before storing it and before calling the BuildTrack API.
        temperature_c = normalize_temperature_to_celsius(temperature)

        if temperature_c is None:
            _LOGGER.warning(
                "BUILTRACK CLIMATE INVALID TEMPERATURE | name=%s | value=%s",
                self._attr_name,
                temperature,
            )
            return

        # Keep the requested value inside the AC-supported Celsius range.
        temperature_c = max(self._attr_min_temp, min(self._attr_max_temp, temperature_c))

        self._attr_target_temperature = temperature_c
        self.async_write_ha_state()

        if self._temp_task:
            self._temp_task.cancel()

        self._temp_task = self._hass.async_create_task(
            self._delayed_temperature_call(temperature_c)
        )

    async def _delayed_temperature_call(self, temperature_c):
        try:
            await asyncio.sleep(0.5)

            payload = {
                "entityId": self._entity_id,
                "entityKey": self._entity_key,
                "temperature": temperature_c,
            }

            response = await self._api.call(
                endpoint=f"/setTemperature/{self._entity_id}",
                method="POST",
                payload=payload,
            )

            _LOGGER.warning(
                "BUILTRACK CLIMATE TEMPERATURE API RESPONSE | name=%s | payload=%s | response=%s",
                self._attr_name,
                payload,
                response,
            )

        except asyncio.CancelledError:
            pass

        except Exception as err:
            _LOGGER.exception(
                "BUILTRACK CLIMATE TEMPERATURE API ERROR | name=%s | error=%s",
                self._attr_name,
                err,
            )

    async def async_set_hvac_mode(self, hvac_mode):
        _LOGGER.warning(
            "BUILTRACK CLIMATE HVAC MODE CHANGE REQUEST | name=%s | mode=%s",
            self._attr_name,
            hvac_mode,
        )

        if hvac_mode == HVACMode.OFF:
            await self._control_device("off")
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.OFF
        else:
            await self._control_device("on")
            self._attr_hvac_mode = hvac_mode

            if hvac_mode == HVACMode.HEAT:
                self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.COOLING

        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        if fan_mode not in self._attr_fan_modes:
            return

        self._attr_fan_mode = fan_mode

        if self._attr_hvac_mode != HVACMode.OFF:
            await self._control_device("on", fan_mode)

        self.async_write_ha_state()

    async def async_update(self):
        _LOGGER.warning(
            "BUILTRACK CLIMATE READ async_update_device CALLED | name=%s | id=%s",
            self._attr_name,
            self._entity_id,
        )

        payload = {
            "entityId": self._entity_id,
            "entityKey": self._entity_key,
        }

        _LOGGER.warning(
            "BUILTRACK CLIMATE READ API CALL | name=%s | payload=%s",
            self._attr_name,
            payload,
        )

        try:
            data = await self._api.call(
                endpoint="/readDeviceData",
                method="POST",
                payload=payload,
            )

        except Exception as err:
            _LOGGER.exception(
                "BUILTRACK CLIMATE READ API ERROR | name=%s | error=%s",
                self._attr_name,
                err,
            )
            return

        _LOGGER.warning(
            "BUILTRACK CLIMATE READ API RESPONSE | name=%s | raw=%s | type=%s",
            self._attr_name,
            data,
            type(data),
        )

        if not data:
            _LOGGER.warning(
                "BUILTRACK CLIMATE READ EMPTY RESPONSE | name=%s",
                self._attr_name,
            )
            return

        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data")

        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            data = data[0]

        if not isinstance(data, dict):
            _LOGGER.warning(
                "BUILTRACK CLIMATE INVALID RESPONSE FORMAT | name=%s | data=%s",
                self._attr_name,
                data,
            )
            return

        state = str(
            data.get("state")
            or data.get("status")
            or data.get("power")
            or data.get("switch")
            or data.get("value")
            or data.get("acStatus")
            or data.get("ac_status")
            or data.get("acState")
            or data.get("ac_state")
            or ""
        ).strip().lower()

        speed = (
            data.get("speed")
            or data.get("fanSpeed")
            or data.get("fan_speed")
            or data.get("level")
        )

        target_temp = (
            data.get("temperature")
            or data.get("targetTemperature")
            or data.get("target_temperature")
            or data.get("setTemperature")
            or data.get("set_temperature")
            or data.get("temp")
        )

        current_temp = (
            data.get("currentTemperature")
            or data.get("current_temperature")
            or data.get("roomTemperature")
            or data.get("room_temperature")
        )

        _LOGGER.warning(
            "BUILTRACK CLIMATE PARSED DATA BEFORE CONVERT | name=%s | state=%s | speed=%s | target_temp=%s | current_temp=%s",
            self._attr_name,
            state,
            speed,
            target_temp,
            current_temp,
        )

        if state in ["on", "1", "true", "yes", "open", "cool", "cooling"]:
            if self._attr_hvac_mode == HVACMode.OFF:
                self._attr_hvac_mode = HVACMode.COOL

            self._attr_hvac_action = HVACAction.COOLING

        elif state in ["heat", "heating"]:
            self._attr_hvac_mode = HVACMode.HEAT
            self._attr_hvac_action = HVACAction.HEATING

        elif state in ["off", "0", "false", "no", "close", "closed"]:
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.OFF

        else:
            _LOGGER.warning(
                "BUILTRACK CLIMATE UNKNOWN STATE FORMAT | name=%s | state=%s | data=%s",
                self._attr_name,
                state,
                data,
            )

        if speed is not None:
            speed_str = str(speed).strip().lower()

            if speed_str in ["low", "medium", "high"]:
                self._attr_fan_mode = speed_str
            else:
                try:
                    speed_int = int(float(speed))

                    if speed_int <= 33:
                        self._attr_fan_mode = "low"
                    elif speed_int <= 66:
                        self._attr_fan_mode = "medium"
                    else:
                        self._attr_fan_mode = "high"

                except Exception as err:
                    _LOGGER.warning(
                        "BUILTRACK CLIMATE SPEED PARSE ERROR | name=%s | speed=%s | error=%s",
                        self._attr_name,
                        speed,
                        err,
                    )

        if target_temp is not None:
            converted_target_temp = normalize_temperature_to_celsius(target_temp)

            if converted_target_temp is not None:
                # readDeviceData returns the selected AC temperature in the
                # `temperature` field. Update the target temperature shown on
                # the climate card. Because the API does not return a separate
                # room/current temperature, expose the same value there too.
                self._attr_target_temperature = converted_target_temp
                self._attr_current_temperature = converted_target_temp

                _LOGGER.warning(
                    "BUILTRACK CLIMATE TEMPERATURE UPDATED | "
                    "name=%s | target_temp_c=%s | current_temp_c=%s",
                    self._attr_name,
                    self._attr_target_temperature,
                    self._attr_current_temperature,
                )

        if current_temp is not None:
            converted_current_temp = normalize_temperature_to_celsius(current_temp)

            if converted_current_temp is not None:
                # When the API later provides a real room temperature, it
                # overrides the fallback value assigned above.
                self._attr_current_temperature = converted_current_temp

        self.async_write_ha_state()

        _LOGGER.warning(
            "BUILTRACK CLIMATE FINAL HA STATE WRITE | name=%s | hvac_mode=%s | hvac_action=%s | fan=%s | target_temp_c=%s | current_temp_c=%s",
            self._attr_name,
            self._attr_hvac_mode,
            self._attr_hvac_action,
            self._attr_fan_mode,
            self._attr_target_temperature,
            self._attr_current_temperature,
        )
