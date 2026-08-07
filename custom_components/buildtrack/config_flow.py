import logging
from urllib.parse import urlencode

import voluptuous as vol
from aiohttp import web

from homeassistant import config_entries
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url, NoURLAvailableError

from .const import (
    DOMAIN,
    SCOPE,
    CONF_API_URL,
    CONF_AUTH_URL,
    CONF_AUTH_TYPE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    AUTH_TYPE_AUTH_CODE,
    AUTH_TYPE_CLIENT_CRED,
)

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------
# Authentication and token exchange
# --------------------------------------------------------

CONF_REDIRECT_URI = "redirect_uri"

CONF_GRANT_TYPE = "Grant Type"


def _clean_url(url: str) -> str:
    return url.strip().rstrip("/")


def _token_url(auth_url: str) -> str:
    return f"{_clean_url(auth_url)}/index.php/oauthtokenservice/token"


def _authorize_url(auth_url: str) -> str:
    return f"{_clean_url(auth_url)}/index.php/oauthtokenservice/authorize"


def _build_user_schema(user_input=None):
    user_input = user_input or {}

    return vol.Schema(
        {
            vol.Required(
                CONF_API_URL,
                default=user_input.get(CONF_API_URL, ""),
            ): str,

            vol.Required(
                CONF_AUTH_URL,
                default=user_input.get(CONF_AUTH_URL, ""),
            ): str,

            vol.Required(
                CONF_CLIENT_ID,
                default=user_input.get(CONF_CLIENT_ID, ""),
            ): str,

            vol.Required(
                CONF_CLIENT_SECRET,
                default=user_input.get(CONF_CLIENT_SECRET, ""),
            ): str,

            vol.Required(
                CONF_GRANT_TYPE,
                default=user_input.get(
                    CONF_GRANT_TYPE,
                    AUTH_TYPE_CLIENT_CRED,
                ),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": AUTH_TYPE_CLIENT_CRED,
                            "label": "Client Credentials",
                        },
                        {
                            "value": AUTH_TYPE_AUTH_CODE,
                            "label": "Authorization Code",
                        },
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class BuildTrackOAuthCallbackView(HomeAssistantView):
    requires_auth = False
    url = "/api/buildtrack/oauth/callback"
    name = "api:buildtrack:oauth:callback"

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]

        code = request.query.get("code")
        state = request.query.get("state")
        error = request.query.get("error")

        _LOGGER.debug(
            "BuildTrack callback received: code=%s state=%s error=%s",
            bool(code),
            state,
            error,
        )

        if not state:
            return web.Response(
                text="Missing state",
                status=400,
            )

        await hass.config_entries.flow.async_configure(
            state,
            {
                "code": code,
                "state": state,
                "error": error,
            },
        )

        return web.Response(
            text="<script>window.close()</script>"
            "Authentication completed. "
            "You can close this window.",
            content_type="text/html",
        )


class BuildTrackConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_build_user_schema(),
                errors=errors,
            )

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        self.context[CONF_API_URL] = _clean_url(
            user_input[CONF_API_URL]
        )

        self.context[CONF_AUTH_URL] = _clean_url(
            user_input[CONF_AUTH_URL]
        )

        self.context[CONF_CLIENT_ID] = user_input[
            CONF_CLIENT_ID
        ]

        self.context[CONF_CLIENT_SECRET] = user_input[
            CONF_CLIENT_SECRET
        ]

        self.context[CONF_AUTH_TYPE] = user_input[
            CONF_GRANT_TYPE
        ]

        if (
            user_input[CONF_GRANT_TYPE]
            == AUTH_TYPE_AUTH_CODE
        ):
            return await self._start_auth_code_flow()

        token_data = await self._get_client_credentials_token()

        if not token_data:
            errors["base"] = "token_failed"

            return self.async_show_form(
                step_id="user",
                data_schema=_build_user_schema(
                    user_input
                ),
                errors=errors,
            )

        return await self._create_buildtrack_entry(
            token_data
        )

    async def async_step_reauth(self, entry_data):
        """Start Home Assistant reauthentication."""
        self._reauth_entry = self._get_reauth_entry()

        self.context[CONF_API_URL] = entry_data.get(CONF_API_URL)
        self.context[CONF_AUTH_URL] = entry_data.get(CONF_AUTH_URL)
        self.context[CONF_AUTH_TYPE] = entry_data.get(CONF_AUTH_TYPE)
        self.context[CONF_CLIENT_ID] = entry_data.get(CONF_CLIENT_ID)
        self.context[CONF_CLIENT_SECRET] = entry_data.get(CONF_CLIENT_SECRET)
        self.context[CONF_REDIRECT_URI] = entry_data.get(CONF_REDIRECT_URI)

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Confirm BuildTrack reauthentication."""
        errors = {}
        entry = getattr(self, "_reauth_entry", None) or self._get_reauth_entry()

        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_CLIENT_ID,
                            default=entry.data.get(CONF_CLIENT_ID, ""),
                        ): str,
                        vol.Required(
                            CONF_CLIENT_SECRET,
                            default=entry.data.get(CONF_CLIENT_SECRET, ""),
                        ): str,
                    }
                ),
                errors=errors,
            )

        self.context[CONF_CLIENT_ID] = user_input[CONF_CLIENT_ID]
        self.context[CONF_CLIENT_SECRET] = user_input[CONF_CLIENT_SECRET]

        if self.context.get(CONF_AUTH_TYPE) == AUTH_TYPE_AUTH_CODE:
            return await self._start_auth_code_flow()

        token_data = await self._get_client_credentials_token()

        if not token_data:
            errors["base"] = "token_failed"
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_CLIENT_ID,
                            default=user_input.get(CONF_CLIENT_ID, ""),
                        ): str,
                        vol.Required(
                            CONF_CLIENT_SECRET,
                            default=user_input.get(CONF_CLIENT_SECRET, ""),
                        ): str,
                    }
                ),
                errors=errors,
            )

        return await self._create_buildtrack_entry(token_data)

    async def _start_auth_code_flow(self):
        if not self.hass.data.get(
            f"{DOMAIN}_callback_registered"
        ):
            self.hass.http.register_view(
                BuildTrackOAuthCallbackView
            )

            self.hass.data[
                f"{DOMAIN}_callback_registered"
            ] = True

        try:
            base_url = get_url(
                self.hass,
                prefer_external=False,
            )

        except NoURLAvailableError:
            _LOGGER.exception(
                "Home Assistant URL not found"
            )

            return self.async_abort(
                reason="ha_url_not_found"
            )

        redirect_uri = (
            f"{base_url.rstrip('/')}"
            f"/api/buildtrack/oauth/callback"
        )

        state = self.flow_id

        self.context["oauth_state"] = state

        self.context[
            CONF_REDIRECT_URI
        ] = redirect_uri

        params = {
            "scope": SCOPE,
            "state": state,
            "client_id": self.context[
                CONF_CLIENT_ID
            ],
            "redirect_uri": redirect_uri,
            "response_type": "code",
        }

        auth_url = (
            f"{_authorize_url(self.context[CONF_AUTH_URL])}"
            f"?{urlencode(params)}"
        )

        return self.async_external_step(
            step_id="auth",
            url=auth_url,
        )

    async def async_step_auth(self, user_input=None):
        if not user_input:
            return self.async_abort(
                reason="missing_callback_data"
            )

        returned_state = user_input.get("state")

        code = user_input.get("code")

        error = user_input.get("error")

        expected_state = self.context.get(
            "oauth_state"
        )

        if error:
            return self.async_abort(
                reason="oauth_error"
            )

        if returned_state != expected_state:
            return self.async_abort(
                reason="state_mismatch"
            )

        if not code:
            return self.async_abort(
                reason="missing_code"
            )

        self.context["auth_code"] = code

        return self.async_external_step_done(
            next_step_id="auth_done"
        )

    async def async_step_auth_done(
        self,
        user_input=None,
    ):
        token_data = (
            await self._exchange_code_for_token()
        )

        if not token_data:
            return self.async_abort(
                reason="token_exchange_failed"
            )

        return await self._create_buildtrack_entry(
            token_data
        )

    async def _get_client_credentials_token(self):
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.context.get(
                CONF_CLIENT_ID
            ),
            "client_secret": self.context.get(
                CONF_CLIENT_SECRET
            ),
            "scope": SCOPE,
        }

        return await self._post_token_request(
            payload
        )

    async def _exchange_code_for_token(self):
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.context.get(
                CONF_CLIENT_ID
            ),
            "client_secret": self.context.get(
                CONF_CLIENT_SECRET
            ),
            "code": self.context.get("auth_code"),
            "redirect_uri": self.context.get(
                CONF_REDIRECT_URI
            ),
        }

        return await self._post_token_request(
            payload
        )

    async def _post_token_request(
        self,
        payload,
    ):
        token_url = _token_url(
            self.context[CONF_AUTH_URL]
        )

        headers = {
            "Content-Type":
                "application/x-www-form-urlencoded",
            "Accept":
                "application/json,text/plain,*/*",
        }

        session = async_get_clientsession(
            self.hass
        )

        try:
            async with session.post(
                token_url,
                data=payload,
                headers=headers,
            ) as response:

                if response.status != 200:
                    return None

                data = await response.json(
                    content_type=None
                )

                if not data.get(
                    "access_token"
                ):
                    return None

                return data

        except Exception as err:
            _LOGGER.exception(
                "BuildTrack token request failed: %s",
                err,
            )

            return None

    async def _create_buildtrack_entry(
        self,
        token_data,
    ):
        data = {
            CONF_API_URL:
                self.context.get(CONF_API_URL),

            CONF_AUTH_URL:
                self.context.get(CONF_AUTH_URL),

            CONF_AUTH_TYPE:
                self.context.get(CONF_AUTH_TYPE),

            CONF_CLIENT_ID:
                self.context.get(CONF_CLIENT_ID),

            CONF_CLIENT_SECRET:
                self.context.get(
                    CONF_CLIENT_SECRET
                ),

            "scope": SCOPE,

            "access_token":
                token_data.get(
                    "access_token"
                ),

            "refresh_token":
                token_data.get(
                    "refresh_token"
                ),

            "token_type":
                token_data.get(
                    "token_type"
                ),

            "expires_in":
                token_data.get(
                    "expires_in"
                ),
        }

        if (
            self.context.get(
                CONF_AUTH_TYPE
            )
            == AUTH_TYPE_AUTH_CODE
        ):
            data[
                CONF_REDIRECT_URI
            ] = self.context.get(
                CONF_REDIRECT_URI
            )

        if self.source == config_entries.SOURCE_REAUTH:
            reauth_entry = (
                getattr(self, "_reauth_entry", None)
                or self._get_reauth_entry()
            )

            return self.async_update_reload_and_abort(
                reauth_entry,
                data=data,
            )

        return self.async_create_entry(
            title="BuildTrack",
            data=data,
        )