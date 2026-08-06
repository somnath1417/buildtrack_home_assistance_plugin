import logging

from homeassistant.components.scene import Scene

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities,
    discovery_info=None,
):
    """Set up BuildTrack scenes."""

    data = hass.data[DOMAIN][entry.entry_id]

    devices = data["devices"]
    api = data["api"]

    scenes = []

    for device in devices:
        if "SCENE" in device.get("type", []):
            scenes.append(
                BuildTrackScene(
                    hass,
                    api,
                    device,
                )
            )

    async_add_entities(scenes)


class BuildTrackScene(Scene):
    """BuildTrack Scene Entity."""

    def __init__(
        self,
        hass,
        api,
        device,
    ):
        self._hass = hass
        self._api = api
        self._device = device

        self._entity_id = device.get("entityId")
        self._entity_key = device.get("entityKey")

        self._attr_name = device.get("entityName")
        self._attr_unique_id = self._entity_id

    async def async_activate(self, **kwargs):
        """Activate BuildTrack scene."""

        _LOGGER.debug(
            "Activating BuildTrack Scene | name=%s | entityId=%s",
            self._attr_name,
            self._entity_id,
        )

        response = await self._api.call(
            endpoint=f"/activateScene/{self._entity_id}",
            method="POST",
            payload=None,
        )

        _LOGGER.debug(
            "BuildTrack Scene Response | name=%s | response=%s",
            self._attr_name,
            response,
        )

        if response is None:
            _LOGGER.error(
                "Failed to activate BuildTrack Scene | name=%s | entityId=%s",
                self._attr_name,
                self._entity_id,
            )