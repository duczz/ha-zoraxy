"""Config flow for the Zoraxy integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ZoraxyAuthError, ZoraxyClient, ZoraxyError, ZoraxyInfo
from .const import (
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SSL, default=False): bool,
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> ZoraxyInfo:
    """Try to log in and fetch instance information."""
    session = async_create_clientsession(
        hass,
        verify_ssl=data.get(CONF_VERIFY_SSL, True),
        cookie_jar=CookieJar(unsafe=True),
        auto_cleanup=False,
    )
    client = ZoraxyClient(
        session=session,
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        use_ssl=data.get(CONF_SSL, False),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await client.async_login()
        return await client.async_get_info()
    finally:
        # auto_cleanup=False means we own this session's lifetime, but HA's
        # session.close() is monkeypatched to always warn regardless of
        # auto_cleanup (see aiohttp_client.py). detach() is the documented
        # way to release a session created this way without triggering it.
        session.detach()


# domain= is valid for HA's ConfigFlow.__init_subclass__; the ignore below is
# only needed because this lint job runs without the real homeassistant package
# installed, so mypy can't see that __init_subclass__ signature.
class ZoraxyConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle the Zoraxy config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _async_validate(self.hass, user_input)
            except ZoraxyAuthError:
                errors["base"] = "invalid_auth"
            except ZoraxyError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Zoraxy connection")
                errors["base"] = "unknown"
            else:
                if info.node_uuid and info.node_uuid != "Unauthorized":
                    await self.async_set_unique_id(info.node_uuid)
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Zoraxy ({user_input[CONF_HOST]})", data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication after a login failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**reauth_entry.data, **user_input}
            try:
                info = await _async_validate(self.hass, data)
            except ZoraxyAuthError:
                errors["base"] = "invalid_auth"
            except ZoraxyError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Zoraxy connection")
                errors["base"] = "unknown"
            else:
                if (
                    reauth_entry.unique_id
                    and info.node_uuid
                    and info.node_uuid != "Unauthorized"
                    and info.node_uuid != reauth_entry.unique_id
                ):
                    return self.async_abort(reason="wrong_instance")
                return self.async_update_reload_and_abort(reauth_entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=reauth_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"host": reauth_entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry (host, port, SSL, ...)."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            try:
                info = await _async_validate(self.hass, user_input)
            except ZoraxyAuthError:
                errors["base"] = "invalid_auth"
            except ZoraxyError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Zoraxy connection")
                errors["base"] = "unknown"
            else:
                if (
                    reconfigure_entry.unique_id
                    and info.node_uuid
                    and info.node_uuid != "Unauthorized"
                    and info.node_uuid != reconfigure_entry.unique_id
                ):
                    return self.async_abort(reason="wrong_instance")
                return self.async_update_reload_and_abort(
                    reconfigure_entry, data=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or reconfigure_entry.data
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ZoraxyOptionsFlow:
        """Return the options flow handler."""
        return ZoraxyOptionsFlow()


class ZoraxyOptionsFlow(OptionsFlow):
    """Handle Zoraxy options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
        )
