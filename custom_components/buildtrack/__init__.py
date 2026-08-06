import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_AUTH_URL,
    CONF_AUTH_TYPE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
)
from .api import BuildTrackAPI, BuildTrackAuthError, BuildTrackConnectionError

# --------------------------------------------------------
# Initial method
# --------------------------------------------------------

PLATFORMS = ["button", "light", "scene", "climate"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.debug("BuildTrack async_setup loaded")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("BuildTrack async_setup_entry started")

    hass.data.setdefault(DOMAIN, {})

    api_url = entry.data.get(CONF_API_URL)
    auth_url = entry.data.get(CONF_AUTH_URL)
    auth_type = entry.data.get(CONF_AUTH_TYPE)

    client_id = entry.data.get(CONF_CLIENT_ID)
    client_secret = entry.data.get(CONF_CLIENT_SECRET)

    redirect_uri = entry.data.get("redirect_uri")

    access_token = entry.data.get("access_token")
    refresh_token = entry.data.get("refresh_token")
    token_type = entry.data.get("token_type")
    expires_in = entry.data.get("expires_in")
    scope = entry.data.get("scope")

    if not api_url or not auth_url:
        raise ConfigEntryNotReady(
            "BuildTrack API or authentication URL is missing"
        )

    if not client_id or not client_secret or not access_token:
        raise ConfigEntryAuthFailed(
            "BuildTrack authentication details are missing"
        )

    api = BuildTrackAPI(
        hass=hass,
        entry=entry,
        api_url=api_url,
        auth_url=auth_url,
        auth_type=auth_type,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=refresh_token,
    )

    try:
        devices = await api.call(
            endpoint="/getDevices",
            method="GET",
            response_key="devices",
        )
    except BuildTrackAuthError as err:
        raise ConfigEntryAuthFailed(
            "BuildTrack authentication failed"
        ) from err
    except BuildTrackConnectionError as err:
        raise ConfigEntryNotReady(
            "Unable to connect to BuildTrack"
        ) from err

    if devices is None:
        raise ConfigEntryNotReady(
            "BuildTrack device fetch failed"
        )

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "devices": devices,
        "api_url": api_url,
        "auth_url": auth_url,
        "auth_type": auth_type,
        "client_id": client_id,
        "client_secret": client_secret,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_type,
        "expires_in": expires_in,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug(
        "BuildTrack entry setup completed | entry_id=%s | devices=%s",
        entry.entry_id,
        len(devices),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    _LOGGER.debug("BuildTrack entry unloaded: %s", entry.entry_id)

    return unload_ok
