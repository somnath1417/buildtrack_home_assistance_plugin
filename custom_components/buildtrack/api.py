import asyncio
import logging

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUTH_TYPE_AUTH_CODE,
    AUTH_TYPE_CLIENT_CRED,
    SCOPE,
)

_LOGGER = logging.getLogger(__name__)


def get_token_url(auth_url: str) -> str:
    """Return BuildTrack OAuth token endpoint."""
    return (
        f"{auth_url.strip().rstrip('/')}"
        "/index.php/oauthtokenservice/token"
    )


class BuildTrackAuthError(Exception):
    """Raised when BuildTrack authentication cannot be recovered."""


class BuildTrackConnectionError(Exception):
    """Raised when BuildTrack cannot be reached."""


# --------------------------------------------------------
# Common API call function
# --------------------------------------------------------

class BuildTrackAPI:
    def __init__(
        self,
        hass,
        api_url,
        auth_url,
        auth_type,
        client_id=None,
        client_secret=None,
        access_token=None,
        refresh_token=None,
        entry=None,
    ):
        self._hass = hass
        self._entry = entry
        self._base_url = api_url.strip().rstrip("/")
        self._auth_url = auth_url.strip().rstrip("/")
        self._auth_type = auth_type
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._refresh_lock = asyncio.Lock()

        _LOGGER.debug(
            "BuildTrack API initialized | "
            "base_url=%s | access_token_exists=%s",
            self._base_url,
            bool(self._access_token),
        )

    async def call(
        self,
        endpoint,
        method="GET",
        payload=None,
        params=None,
        headers=None,
        response_key=None,
        success_status=200,
        retry_auth=True,
    ):
        endpoint = (
            endpoint
            if endpoint.startswith("/")
            else f"/{endpoint}"
        )

        url = f"{self._base_url}{endpoint}"

        default_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self._access_token:
            default_headers["Authorization"] = (
                self._access_token
            )

        if headers:
            default_headers.update(headers)

        session = async_get_clientsession(
            self._hass
        )

        try:
            async with session.request(
                method=method,
                url=url,
                json=payload,
                params=params,
                headers=default_headers,
            ) as response:
                text = await response.text()

                _LOGGER.debug(
                    "BuildTrack API call | "
                    "method=%s | endpoint=%s | status=%s",
                    method,
                    endpoint,
                    response.status,
                )

                if response.status in (401, 403):
                    if (
                        retry_auth
                        and await self._refresh_access_token()
                    ):
                        return await self.call(
                            endpoint=endpoint,
                            method=method,
                            payload=payload,
                            params=params,
                            headers=headers,
                            response_key=response_key,
                            success_status=success_status,
                            retry_auth=False,
                        )

                    if self._entry is not None:
                        self._entry.async_start_reauth(
                            self._hass
                        )

                    raise BuildTrackAuthError(
                        "BuildTrack authentication expired"
                    )

                if response.status != success_status:
                    _LOGGER.error(
                        "BuildTrack API error | "
                        "method=%s | endpoint=%s | "
                        "status=%s | body=%s",
                        method,
                        endpoint,
                        response.status,
                        text[:1000],
                    )
                    return None

                try:
                    data = await response.json(
                        content_type=None
                    )

                except Exception:
                    return text

                if response_key:
                    return data.get(response_key)

                return data

        except BuildTrackAuthError:
            raise

        except Exception as err:
            raise BuildTrackConnectionError(
                f"BuildTrack API request failed: {err}"
            ) from err

    async def _refresh_access_token(self):
        async with self._refresh_lock:

            if (
                not self._client_id
                or not self._client_secret
            ):
                return False

            if (
                self._auth_type
                == AUTH_TYPE_AUTH_CODE
            ):
                if not self._refresh_token:
                    return False

                payload = {
                    "grant_type": "refresh_token",
                    "refresh_token":
                        self._refresh_token,
                    "client_id":
                        self._client_id,
                    "client_secret":
                        self._client_secret,
                    "scope": SCOPE,
                }

            elif (
                self._auth_type
                == AUTH_TYPE_CLIENT_CRED
            ):
                payload = {
                    "grant_type":
                        "client_credentials",
                    "client_id":
                        self._client_id,
                    "client_secret":
                        self._client_secret,
                    "scope": SCOPE,
                }

            else:
                return False

            # Common token URL method
            token_url = get_token_url(
                self._auth_url
            )

            session = async_get_clientsession(
                self._hass
            )

            try:
                async with session.post(
                    token_url,
                    data=payload,
                    headers={
                        "Content-Type":
                            "application/x-www-form-urlencoded",
                        "Accept":
                            "application/json,text/plain,*/*",
                    },
                ) as response:

                    if response.status != 200:
                        _LOGGER.warning(
                            "BuildTrack token refresh failed | "
                            "status=%s",
                            response.status,
                        )
                        return False

                    data = await response.json(
                        content_type=None
                    )

                    new_access_token = data.get(
                        "access_token"
                    )

                    if not new_access_token:
                        return False

                    self._access_token = (
                        new_access_token
                    )

                    self._refresh_token = (
                        data.get("refresh_token")
                        or self._refresh_token
                    )

                    if self._entry is not None:
                        updated_data = dict(
                            self._entry.data
                        )

                        updated_data.update(
                            {
                                "access_token":
                                    self._access_token,
                                "refresh_token":
                                    self._refresh_token,
                                "token_type":
                                    data.get(
                                        "token_type"
                                    ),
                                "expires_in":
                                    data.get(
                                        "expires_in"
                                    ),
                            }
                        )

                        self._hass.config_entries.async_update_entry(
                            self._entry,
                            data=updated_data,
                        )

                    _LOGGER.debug(
                        "BuildTrack token refreshed "
                        "successfully | expires_in=%s",
                        data.get("expires_in"),
                    )

                    return True

            except Exception as err:
                _LOGGER.warning(
                    "BuildTrack token refresh failed: %s",
                    err,
                )

                return False