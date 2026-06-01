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

        await self.async_update()

    async def _control_device(self, state, speed=None):
        if speed is None:
            speed = self._attr_fan_mode or ""

        payload = {
            "entityKey": self._entity_key or "",
            "state": state or "",
            "speed": speed or "",
        }

        _LOGGER.warning(
            "BUILTRACK CLIMATE CONTROL API CALL | %s | endpoint=%s | payload=%s",
            self._attr_name,
            f"/controlDevice/{self._entity_id}",
            payload,
        )

        try:
            response = await self._api.call(
                endpoint=f"/controlDevice/{self._entity_id}",
                method="POST",
                payload=payload,
            )

            _LOGGER.warning(
                "BUILTRACK CLIMATE CONTROL API RESPONSE | %s | raw=%s | type=%s",
                self._attr_name,
                response,
                type(response),
            )

            return response

        except Exception as err:
            _LOGGER.exception(
                "BUILTRACK CLIMATE CONTROL API ERROR | %s | payload=%s | error=%s",
                self._attr_name,
                payload,
                err,
            )
            return None

    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get("temperature")

        if temperature is None:
            return

        self._attr_target_temperature = temperature
        self.async_write_ha_state()

        if self._temp_task:
            self._temp_task.cancel()

        self._temp_task = self._hass.async_create_task(
            self._delayed_temperature_call(temperature)
        )

    async def _delayed_temperature_call(self, temperature):
        try:
            await asyncio.sleep(0.5)

            payload = {
                "entityKey": self._entity_key or "",
                "temperature": temperature,
            }

            _LOGGER.warning(
                "BUILTRACK CLIMATE TEMP API CALL | %s | payload=%s",
                self._attr_name,
                payload,
            )

            response = await self._api.call(
                endpoint=f"/setTemperature/{self._entity_id}",
                method="POST",
                payload=payload,
            )

            _LOGGER.warning(
                "BUILTRACK CLIMATE TEMP API RESPONSE | %s | raw=%s | type=%s",
                self._attr_name,
                response,
                type(response),
            )

            await self.async_update()

        except asyncio.CancelledError:
            pass

        except Exception as err:
            _LOGGER.exception(
                "BUILTRACK CLIMATE TEMP API ERROR | %s | error=%s",
                self._attr_name,
                err,
            )

    async def async_set_hvac_mode(self, hvac_mode):
        _LOGGER.warning(
            "BUILTRACK CLIMATE HVAC MODE CHANGE REQUEST | %s | mode=%s",
            self._attr_name,
            hvac_mode,
        )

        if hvac_mode == HVACMode.OFF:
            await self._control_device("off", self._attr_fan_mode)

            self._attr_hvac_mode = HVACMode.OFF
            self._attr_hvac_action = HVACAction.OFF

        else:
            await self._control_device("on", self._attr_fan_mode)

            self._attr_hvac_mode = hvac_mode

            if hvac_mode == HVACMode.HEAT:
                self._attr_hvac_action = HVACAction.HEATING
            else:
                self._attr_hvac_action = HVACAction.COOLING

        self.async_write_ha_state()
        await self.async_update()

    async def async_set_fan_mode(self, fan_mode):
        if fan_mode not in self._attr_fan_modes:
            _LOGGER.warning(
                "BUILTRACK CLIMATE INVALID FAN MODE | %s | fan_mode=%s",
                self._attr_name,
                fan_mode,
            )
            return

        _LOGGER.warning(
            "BUILTRACK CLIMATE FAN MODE CHANGE REQUEST | %s | fan_mode=%s",
            self._attr_name,
            fan_mode,
        )

        self._attr_fan_mode = fan_mode

        if self._attr_hvac_mode != HVACMode.OFF:
            await self._control_device("on", fan_mode)

        self.async_write_ha_state()
        await self.async_update()

    async def async_update(self):
        _LOGGER.warning(
            "BUILTRACK CLIMATE async_update CALLED | %s | id=%s",
            self._attr_name,
            self._entity_id,
        )

        payload = {
            "entityId": self._entity_id,
            "entityKey": self._entity_key,
        }

        _LOGGER.warning(
            "BUILTRACK CLIMATE READ API CALL | %s | payload=%s",
            self._attr_name,
            payload,
        )

        try:
            data = await self._api.call(
                endpoint="/readDeviceData",
                method="POST",
                payload=payload,
            )

            _LOGGER.warning(
                "BUILTRACK CLIMATE READ API RESPONSE | %s | raw=%s | type=%s",
                self._attr_name,
                data,
                type(data),
            )

        except Exception as err:
            _LOGGER.exception(
                "BUILTRACK CLIMATE READ API ERROR | %s | payload=%s | error=%s",
                self._attr_name,
                payload,
                err,
            )
            return

        if not data:
            _LOGGER.warning("BUILTRACK CLIMATE READ EMPTY RESPONSE | %s", self._attr_name)
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

        temperature = (
            data.get("temperature")
            or data.get("targetTemperature")
            or data.get("target_temperature")
            or data.get("temp")
        )

        current_temperature = (
            data.get("currentTemperature")
            or data.get("current_temperature")
            or data.get("roomTemperature")
            or data.get("room_temperature")
        )

        _LOGGER.warning(
            "BUILTRACK CLIMATE PARSED DATA | %s | state=%s | speed=%s | target_temp=%s | current_temp=%s",
            self._attr_name,
            state,
            speed,
            temperature,
            current_temperature,
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

        elif not state and speed is None and temperature is None and current_temperature is None:
            _LOGGER.warning(
                "BUILTRACK CLIMATE UNKNOWN RESPONSE FORMAT | %s | data=%s",
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

                    _LOGGER.warning(
                        "BUILTRACK CLIMATE SPEED UPDATED | %s | speed=%s | fan_mode=%s",
                        self._attr_name,
                        speed_int,
                        self._attr_fan_mode,
                    )

                except Exception as err:
                    _LOGGER.warning(
                        "BUILTRACK CLIMATE SPEED PARSE ERROR | %s | speed=%s | error=%s",
                        self._attr_name,
                        speed,
                        err,
                    )

        if temperature is not None:
            try:
                self._attr_target_temperature = float(temperature)
            except Exception as err:
                _LOGGER.warning(
                    "BUILTRACK CLIMATE TARGET TEMP PARSE ERROR | %s | temp=%s | error=%s",
                    self._attr_name,
                    temperature,
                    err,
                )

        if current_temperature is not None:
            try:
                self._attr_current_temperature = float(current_temperature)
            except Exception as err:
                _LOGGER.warning(
                    "BUILTRACK CLIMATE CURRENT TEMP PARSE ERROR | %s | current_temp=%s | error=%s",
                    self._attr_name,
                    current_temperature,
                    err,
                )

        self.async_write_ha_state()

        _LOGGER.warning(
            "BUILTRACK CLIMATE FINAL HA STATE WRITE | %s | hvac_mode=%s | hvac_action=%s | fan=%s | target_temp=%s | current_temp=%s",
            self._attr_name,
            self._attr_hvac_mode,
            self._attr_hvac_action,
            self._attr_fan_mode,
            self._attr_target_temperature,
            self._attr_current_temperature,
        )
