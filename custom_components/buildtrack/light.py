import asyncio
import logging

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


def get_location(device):
    location = device.get("location")

    if location and str(location).strip():
        return str(location).strip()

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
    """Set up BuildTrack Climate platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data["devices"]
    api = data["api"]

    climates = []

    for device in devices:
        if "THERMOSTAT" in device.get("type", []):
            climates.append(BuildTrackClimate(hass, api, device))

    async_add_entities(climates)


class BuildTrackClimate(ClimateEntity):
    """BuildTrack Thermostat Entity."""

    should_poll = False

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
        self._attr_current_temperature = 24
        self._attr_target_temperature = 26
        self._attr_min_temp = 18
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

    async def async_added_to_hass(self):
        location = get_location(self._device)

        if location:
            await assign_device_to_area(
                self._hass,
                self._entity_id,
                location,
            )

    async def async_set_temperature(self, **kwargs):
        )

    async def _delayed_temperature_call(self, temperature):
        """Delay API call to avoid rapid requests."""
        try:
            await asyncio.sleep(0.5)

            response = await self._api.call(
                endpoint=f"/setTemperature/{self._entity_id}",
                method="POST",
                payload={
                    "entityId": self._entity_id,
                    "entityKey": self._entity_key,
                    "temperature": temperature,
                },
            )

            _LOGGER.warning("Temperature RAW API RESPONSE: %s", response)

        except asyncio.CancelledError:
            pass

        except Exception as err:
            _LOGGER.exception(
                "ERROR: Exception while setting temperature | Entity: %s | Error: %s",
                self.entity_id,
                err,
            )

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode."""

        if hvac_mode not in self._attr_hvac_modes:
            return

        command_map = {
            HVACMode.COOL: "COOL",
            HVACMode.HEAT: "HEAT",
            HVACMode.OFF: "OFF",
        }

        command = command_map.get(hvac_mode)

        response = await self._api.call(
            endpoint=f"/controlDevice/{self._entity_id}",
            method="POST",
            payload={
                "entityId": self._entity_id,
                "entityKey": self._entity_key,
                "state": command,
            },
        )

        _LOGGER.warning("HVAC RAW RESPONSE: %s", response)

        if response:
            self._attr_hvac_mode = hvac_mode

            if hvac_mode == HVACMode.COOL:
                self._attr_hvac_action = HVACAction.COOLING
            elif hvac_mode == HVACMode.HEAT:
                self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.OFF

            self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode):
            self.async_write_ha_state()

    async def async_update(self):
        _LOGGER.warning(
            "BUILTRACK THERMOSTAT async_update CALLED | %s | id=%s",
            self._attr_name,
            self._entity_id,
        )

        payload = {
            "entityId": self._entity_id,
            "entityKey": self._entity_key,
        }

        _LOGGER.warning(
            "BUILTRACK THERMOSTAT READ API CALL | %s | payload=%s",
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
                "BUILTRACK THERMOSTAT READ API ERROR | %s | error=%s",
                self._attr_name,
                err,
            )
            return

        _LOGGER.warning(
            "BUILTRACK THERMOSTAT READ API RESPONSE | %s | raw=%s | type=%s",
            self._attr_name,
            data,
            type(data),
        )

        if not data:
            _LOGGER.warning(
                "BUILTRACK THERMOSTAT READ EMPTY RESPONSE | %s",
                self._attr_name,
            )
            return

        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data")

        if not isinstance(data, dict):
            _LOGGER.warning(
                "BUILTRACK THERMOSTAT INVALID RESPONSE FORMAT | %s | data=%s",
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
            "BUILTRACK THERMOSTAT PARSED DATA | %s | state=%s | speed=%s | target_temp=%s | current_temp=%s",
            self._attr_name,
            state,
            speed,
            target_temp,
            current_temp,
        )

        if state in ["on", "1", "true", "yes", "open"]:
            if self._attr_hvac_mode == HVACMode.OFF:
                self._attr_hvac_mode = HVACMode.COOL

            if self._attr_hvac_mode == HVACMode.HEAT:
                self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.COOLING

        elif state in ["off", "0", "false", "no", "close", "closed"]:
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.OFF

        elif not state and speed is None and target_temp is None and current_temp is None:
            _LOGGER.warning(
                "BUILTRACK THERMOSTAT UNKNOWN RESPONSE FORMAT | %s | data=%s",
                self._attr_name,
                data,
            )
            return

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
                        "BUILTRACK THERMOSTAT SPEED PARSE ERROR | %s | speed=%s | error=%s",
                        self._attr_name,
                        speed,
                        err,
                    )

        if target_temp is not None:
            try:
                self._attr_target_temperature = float(target_temp)
            except Exception as err:
                _LOGGER.warning(
                    "BUILTRACK THERMOSTAT TARGET TEMP PARSE ERROR | %s | temp=%s | error=%s",
                    self._attr_name,
                    target_temp,
                    err,
                )

        if current_temp is not None:
            try:
                self._attr_current_temperature = float(current_temp)
            except Exception as err:
                _LOGGER.warning(
                    "BUILTRACK THERMOSTAT CURRENT TEMP PARSE ERROR | %s | temp=%s | error=%s",
                    self._attr_name,
                    current_temp,
                    err,
                )

        self.async_write_ha_state()

        _LOGGER.warning(
            "BUILTRACK THERMOSTAT FINAL HA STATE WRITE | %s | hvac_mode=%s | hvac_action=%s | fan=%s | target_temp=%s | current_temp=%s",
            self._attr_name,
            self._attr_hvac_mode,
            self._attr_hvac_action,
            self._attr_fan_mode,
            self._attr_target_temperature,
            self._attr_current_temperature,
        )
