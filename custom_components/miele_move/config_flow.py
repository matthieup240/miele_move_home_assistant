"""Config flow for Miele MOVE."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MieleMoveApiClient, MieleMoveApiError, MieleMoveAuthError
from .const import (
    CONF_ACCEPT_LANGUAGE,
    CONF_BASE_URL,
    CONF_DEVICE_TTL_SECONDS,
    CONF_FAST_INTERVAL_SECONDS,
    CONF_MAX_EXECUTION_DETAILS,
    CONF_SLOW_INTERVAL_SECONDS,
    DEFAULT_ACCEPT_LANGUAGE,
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE_TTL_SECONDS,
    DEFAULT_FAST_INTERVAL_SECONDS,
    DEFAULT_MAX_EXECUTION_DETAILS,
    DEFAULT_SLOW_INTERVAL_SECONDS,
    DOMAIN,
    MAX_DEVICE_TTL_SECONDS,
    MAX_FAST_INTERVAL_SECONDS,
    MAX_SLOW_INTERVAL_SECONDS,
    MIN_DEVICE_TTL_SECONDS,
    MIN_FAST_INTERVAL_SECONDS,
    MIN_SLOW_INTERVAL_SECONDS,
)
from .options import migrate_options, validate_intervals


class MieleMoveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Miele MOVE config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            interval_error = validate_intervals(
                user_input[CONF_FAST_INTERVAL_SECONDS],
                user_input[CONF_SLOW_INTERVAL_SECONDS],
            )
            if interval_error:
                errors["base"] = interval_error
            else:
                try:
                    await _validate_input(self.hass, user_input)
                except MieleMoveAuthError:
                    errors["base"] = "invalid_auth"
                except MieleMoveApiError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id("miele_move")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Miele MOVE",
                        data={
                            "api_key": user_input["api_key"],
                            CONF_BASE_URL: user_input[CONF_BASE_URL],
                            CONF_ACCEPT_LANGUAGE: user_input[CONF_ACCEPT_LANGUAGE],
                        },
                        options={
                            CONF_MAX_EXECUTION_DETAILS: user_input[
                                CONF_MAX_EXECUTION_DETAILS
                            ],
                            CONF_FAST_INTERVAL_SECONDS: user_input[
                                CONF_FAST_INTERVAL_SECONDS
                            ],
                            CONF_SLOW_INTERVAL_SECONDS: user_input[
                                CONF_SLOW_INTERVAL_SECONDS
                            ],
                            CONF_DEVICE_TTL_SECONDS: user_input[
                                CONF_DEVICE_TTL_SECONDS
                            ],
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle re-authentication when the API key is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask the user for a fresh API key and update the entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            merged = {**reauth_entry.data, **user_input}
            try:
                await _validate_input(self.hass, merged)
            except MieleMoveAuthError:
                errors["base"] = "invalid_auth"
            except MieleMoveApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required("api_key", default=""): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow."""
        return MieleMoveOptionsFlow()


class MieleMoveOptionsFlow(config_entries.OptionsFlow):
    """Handle Miele MOVE options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            interval_error = validate_intervals(
                user_input[CONF_FAST_INTERVAL_SECONDS],
                user_input[CONF_SLOW_INTERVAL_SECONDS],
            )
            if interval_error:
                errors["base"] = interval_error
            else:
                return self.async_create_entry(title="", data=user_input)

        current = migrate_options(dict(self.config_entry.options))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MAX_EXECUTION_DETAILS,
                        default=current.get(
                            CONF_MAX_EXECUTION_DETAILS,
                            DEFAULT_MAX_EXECUTION_DETAILS,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
                    vol.Optional(
                        CONF_FAST_INTERVAL_SECONDS,
                        default=current.get(
                            CONF_FAST_INTERVAL_SECONDS,
                            DEFAULT_FAST_INTERVAL_SECONDS,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_FAST_INTERVAL_SECONDS,
                            max=MAX_FAST_INTERVAL_SECONDS,
                        ),
                    ),
                    vol.Optional(
                        CONF_SLOW_INTERVAL_SECONDS,
                        default=current.get(
                            CONF_SLOW_INTERVAL_SECONDS,
                            DEFAULT_SLOW_INTERVAL_SECONDS,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SLOW_INTERVAL_SECONDS,
                            max=MAX_SLOW_INTERVAL_SECONDS,
                        ),
                    ),
                    vol.Optional(
                        CONF_DEVICE_TTL_SECONDS,
                        default=current.get(
                            CONF_DEVICE_TTL_SECONDS,
                            DEFAULT_DEVICE_TTL_SECONDS,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_DEVICE_TTL_SECONDS,
                            max=MAX_DEVICE_TTL_SECONDS,
                        ),
                    ),
                }
            ),
            errors=errors,
        )


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate credentials by fetching devices once."""
    client = MieleMoveApiClient(
        session=async_get_clientsession(hass),
        api_key=data["api_key"],
        base_url=data[CONF_BASE_URL],
        accept_language=data[CONF_ACCEPT_LANGUAGE],
    )
    await client.async_get_devices()


def _schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    defaults = user_input or {}
    return vol.Schema(
        {
            vol.Required("api_key", default=defaults.get("api_key", "")): str,
            vol.Optional(
                CONF_BASE_URL,
                default=defaults.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            ): str,
            vol.Optional(
                CONF_ACCEPT_LANGUAGE,
                default=defaults.get(CONF_ACCEPT_LANGUAGE, DEFAULT_ACCEPT_LANGUAGE),
            ): str,
            vol.Optional(
                CONF_MAX_EXECUTION_DETAILS,
                default=defaults.get(
                    CONF_MAX_EXECUTION_DETAILS, DEFAULT_MAX_EXECUTION_DETAILS
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
            vol.Optional(
                CONF_FAST_INTERVAL_SECONDS,
                default=defaults.get(
                    CONF_FAST_INTERVAL_SECONDS, DEFAULT_FAST_INTERVAL_SECONDS
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_FAST_INTERVAL_SECONDS,
                    max=MAX_FAST_INTERVAL_SECONDS,
                ),
            ),
            vol.Optional(
                CONF_SLOW_INTERVAL_SECONDS,
                default=defaults.get(
                    CONF_SLOW_INTERVAL_SECONDS, DEFAULT_SLOW_INTERVAL_SECONDS
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_SLOW_INTERVAL_SECONDS,
                    max=MAX_SLOW_INTERVAL_SECONDS,
                ),
            ),
            vol.Optional(
                CONF_DEVICE_TTL_SECONDS,
                default=defaults.get(
                    CONF_DEVICE_TTL_SECONDS, DEFAULT_DEVICE_TTL_SECONDS
                ),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(
                    min=MIN_DEVICE_TTL_SECONDS,
                    max=MAX_DEVICE_TTL_SECONDS,
                ),
            ),
        }
    )
