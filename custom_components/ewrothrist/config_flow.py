"""Config flow for the EW Rothrist Smart Meter integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import EwrAuthError, EwrClient, EwrConnectionError
from .const import (
    CONF_BACKFILL_DAYS,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate(hass, email: str, password: str) -> list[str]:
    """Try to log in and return the available meter ids."""
    session = async_create_clientsession(hass)
    try:
        client = EwrClient(session, email, password)
        await client.async_login()
        return await client.async_get_meters()
    finally:
        await session.close()


class EwrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI configuration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                meters = await _validate(
                    self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except EwrAuthError:
                errors["base"] = "invalid_auth"
            except EwrConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating EW Rothrist login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"EW Rothrist ({meters[0]})",
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        "meter": meters[0],
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await _validate(
                    self.hass,
                    reauth_entry.data[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
            except EwrAuthError:
                errors["base"] = "invalid_auth"
            except EwrConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EwrOptionsFlow()


class EwrOptionsFlow(OptionsFlow):
    """Polling interval and backfill options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_MINUTES,
                    default=options.get(
                        CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_MINUTES, max=1440)),
                vol.Required(
                    CONF_BACKFILL_DAYS,
                    default=options.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS),
                ): vol.All(vol.Coerce(int), vol.Range(min=3, max=1100)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
