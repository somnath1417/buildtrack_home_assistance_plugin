import logging

from datetime import datetime

from homeassistant.components.light import (
    LightEntity,
    ColorMode,
)
from homeassistant.helpers.restore_state import RestoreEntity
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
            "BuildTrack light device assigned to area %s",
            location,
        )


async def async_setup_entry(
    hass,
    entry,
    async_add_entities,
    discovery_info=None,
):
    data = hass.data[DOMAIN][entry.entry_id]

    devices = data["devices"]
    api = data["api"]

    lights = []

    _LOGGER.warning("BuildTrack Devices : %s", devices)

    for device in devices:
        device_types = device.get("type", [])

        _LOGGER.warning(
            "BuildTrack light check: %s | %s",
            device.get("entityName"),
            device_types,
        )

        if "LIGHT DIMMER" in device_types:
            lights.append(BuildTrackDimmer(hass, api, device))

        elif "LIGHT" in device_types:
            lights.append(BuildTrackLight(hass, api, device))

    _LOGGER.warning("BuildTrack total lights added: %s", len(lights))

    async_add_entities(lights)


class BuildTrackLight(LightEntity):

    should_poll = False

    def __init__(self, hass, api, device):
        self._hass = hass
        self._api = api
        self._device = device

        self._entity_id = device.get("entityId")
        self._entity_key = device.get("entityKey")

        self._attr_name = device.get("entityName")
        self._attr_unique_id = self._entity_id

        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.ONOFF

        self._is_on = False
        self._last_local_change = None

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

    @property
    def is_on(self):
        return self._is_on

    @property
    def available(self):
        return True

    async def async_turn_on(self, **kwargs):
        self._set_local_state("on", True)

    async def async_turn_off(self, **kwargs):
        self._set_local_state("off", False)

    def _set_local_state(self, state: str, is_on: bool):
        old_state = self._is_on

        self._is_on = is_on
        self._last_local_change = datetime.now()
        self.async_write_ha_state()

        self._hass.async_create_task(
            self._send_power_to_api(state, old_state)
        )

    async def _send_power_to_api(self, state: str, old_state: bool):
        response = await self._api.call(
            endpoint=f"/controlDevice/{self._entity_id}",
            method="POST",
            payload={
                "entityId": self._entity_id,
                "entityKey": self._entity_key,
                "state": state,
            },
        )

        if response is None:
            self._is_on = old_state
            self.async_write_ha_state()

    async def async_update(self):
        data = await self._api.call(
            endpoint="/readDeviceData",
            method="POST",
            payload={
                "entityId": self._entity_id,
                "entityKey": self._entity_key,
            },
        )

        _LOGGER.warning(
            "Realtime Light Data | %s | %s",
            self._attr_name,
            data,
        )

        if not data:
            return

        state = str(data.get("state", "")).lower()

        if state in ["on", "1", "true"]:
            self._is_on = True

        elif state in ["off", "0", "false"]:
            self._is_on = False

        self.async_write_ha_state()


class BuildTrackDimmer(LightEntity, RestoreEntity):

    should_poll = False

    def __init__(self, hass, api, device):
        self._hass = hass
        self._api = api
        self._device = device

        self._entity_id = device.get("entityId")
        self._entity_key = device.get("entityKey")

        self._attr_name = device.get("entityName")
        self._attr_unique_id = self._entity_id

        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS

        self._is_on = False
        self._brightness = 255
        self._last_local_change = None

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
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        if last_state:
            self._is_on = last_state.state == "on"

            brightness = last_state.attributes.get("brightness")

            if brightness is not None:
                self._brightness = brightness

            if self._brightness is None:
                self._brightness = 255

        location = get_location(self._device)

        if location:
            await assign_device_to_area(
                self._hass,
                self._entity_id,
                location,
            )

    @property
    def is_on(self):
        return self._is_on

    @property
    def brightness(self):
        return self._brightness

    @property
    def available(self):
        return True

    async def async_turn_on(self, **kwargs):
        brightness = kwargs.get("brightness")

        if brightness is not None:
            self._brightness = brightness

        if self._brightness is None or self._brightness <= 0:
            self._brightness = 255

        brightness_percent = int((self._brightness / 255) * 100)

        self._is_on = True
        self._last_local_change = datetime.now()
        self.async_write_ha_state()

        self._hass.async_create_task(
            self._api.call(
                endpoint=f"/controlDevice/{self._entity_id}",
                method="POST",
                payload={
                    "entityId": self._entity_id,
                    "entityKey": self._entity_key,
                    "state": "on",
                    "speed": brightness_percent,
                },
            )
        )

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        self._brightness = 0
        self._last_local_change = datetime.now()
        self.async_write_ha_state()

        self._hass.async_create_task(
            self._api.call(
                endpoint=f"/controlDevice/{self._entity_id}",
                method="POST",
                payload={
                    "entityId": self._entity_id,
                    "entityKey": self._entity_key,
                    "state": "off",
                    "speed": 0,
                },
            )
        )

    async def async_update(self):
        data = await self._api.call(
            endpoint="/readDeviceData",
            method="POST",
            payload={
                "entityId": self._entity_id,
                "entityKey": self._entity_key,
            },
        )

        _LOGGER.warning(
            "DIMMER REALTIME RAW DATA | %s | %s",
            self._attr_name,
            data,
        )

        if not data:
            return

        if "state" not in data and "speed" not in data:
            _LOGGER.warning(
                "DIMMER SKIP UPDATE | No state/speed found | %s | %s",
                self._attr_name,
                data,
            )
            return

        state = str(data.get("state", "")).lower()
        speed = data.get("speed")

        if speed is not None:
            try:
                speed_int = int(float(speed))
                speed_int = max(0, min(speed_int, 100))

                self._brightness = int((speed_int / 100) * 255)

                if speed_int > 0:
                    self._is_on = True
                else:
                    self._is_on = False

            except Exception as err:
                _LOGGER.warning(
                    "DIMMER SPEED PARSE ERROR | %s | %s",
                    self._attr_name,
                    err,
                )

        if state in ["on", "1", "true"]:
            self._is_on = True

        elif state in ["off", "0", "false"]:
            self._is_on = False
            self._brightness = 0

        if self._brightness is None:
            self._brightness = 255 if self._is_on else 0

        _LOGGER.warning(
            "FINAL DIMMER STATE | %s | is_on=%s | brightness=%s",
            self._attr_name,
            self._is_on,
            self._brightness,
        )

        self.async_write_ha_state()
