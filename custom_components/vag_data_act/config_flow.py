"""Config flow: account -> vehicle selection; reauth; reconfigure; options."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import AuthFailed, ConsentRequired, PortalClient, PortalError, PortalOutage, Vehicle
from .const import (
    BRANDS,
    CONF_BRAND,
    CONF_COUNTRY,
    CONF_LANGUAGE,
    CONF_NICKNAME,
    CONF_SCAN_INTERVAL,
    CONF_VIN,
    DEFAULT_BRAND,
    DEFAULT_COUNTRY,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


def _account_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=d.get(CONF_EMAIL, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL)
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_BRAND, default=d.get(CONF_BRAND, DEFAULT_BRAND)): SelectSelector(
                SelectSelectorConfig(options=list(BRANDS), mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_COUNTRY, default=d.get(CONF_COUNTRY, DEFAULT_COUNTRY)): str,
            vol.Required(CONF_LANGUAGE, default=d.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)): str,
        }
    )


async def _try_login(data: Mapping[str, Any]) -> tuple[str | None, list[Vehicle]]:
    """Login with a throw-away session. Returns (error_key, vehicles)."""
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
        client = PortalClient(
            session,
            data[CONF_EMAIL],
            data[CONF_PASSWORD],
            brand=data[CONF_BRAND],
            country=data[CONF_COUNTRY],
            language=data[CONF_LANGUAGE],
        )
        try:
            await client.async_login()
            return None, await client.async_list_vehicles()
        except AuthFailed:
            return "invalid_auth", []
        except ConsentRequired:
            return "consent_required", []
        except PortalOutage:
            return "cannot_connect", []
        except PortalError as err:
            _LOGGER.error("portal error during config flow: %s", err)
            return "unknown", []


class VagDataActConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI flows."""

    VERSION = 1

    def __init__(self) -> None:
        self._account: dict[str, Any] = {}
        self._vehicles: list[Vehicle] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_COUNTRY] = user_input[CONF_COUNTRY].strip().lower()
            user_input[CONF_LANGUAGE] = user_input[CONF_LANGUAGE].strip().lower()
            error, vehicles = await _try_login(user_input)
            if error:
                errors["base"] = error
            elif not vehicles:
                errors["base"] = "no_vehicles"
            else:
                self._account = dict(user_input)
                self._vehicles = vehicles
                return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="user", data_schema=_account_schema(user_input), errors=errors
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            vin = user_input[CONF_VIN]
            vehicle = next(v for v in self._vehicles if v.vin == vin)
            await self.async_set_unique_id(vin)
            self._abort_if_unique_id_configured()
            title = vehicle.nickname or vehicle.model or f"Vehicle …{vin[-4:]}"
            return self.async_create_entry(
                title=title,
                data={
                    **self._account,
                    CONF_VIN: vin,
                    CONF_NICKNAME: vehicle.nickname or vehicle.model,
                },
                options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_MINUTES},
            )
        options = [
            {"value": v.vin, "label": f"{v.nickname or v.model or 'Vehicle'} ({v.vin})"}
            for v in self._vehicles
        ]
        return self.async_show_form(
            step_id="vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VIN): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            error, vehicles = await _try_login(merged)
            if error:
                errors["base"] = error
            elif entry.data[CONF_VIN] not in {v.vin for v in vehicles}:
                errors["base"] = "wrong_account"
            else:
                return self.async_update_reload_and_abort(entry, data=merged)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_COUNTRY] = user_input[CONF_COUNTRY].strip().lower()
            user_input[CONF_LANGUAGE] = user_input[CONF_LANGUAGE].strip().lower()
            error, vehicles = await _try_login(user_input)
            if error:
                errors["base"] = error
            elif entry.data[CONF_VIN] not in {v.vin for v in vehicles}:
                errors["base"] = "wrong_account"
            else:
                return self.async_update_reload_and_abort(entry, data={**entry.data, **user_input})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_account_schema(user_input or entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VagDataActOptionsFlow()


class VagDataActOptionsFlow(OptionsFlow):
    """Poll interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=720,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
