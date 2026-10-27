"""The VAG EU Data Act integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import PortalClient, cookies_from_list, cookies_to_list
from .const import (
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
    SERVICE_REFRESH_NOW,
)
from .coordinator import VagDataActCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
COOKIE_STORE_VERSION = 1

type VagDataActConfigEntry = ConfigEntry[VagDataActCoordinator]

SERVICE_SCHEMA = vol.Schema({vol.Optional("config_entry_id"): cv.string})


def account_key(data: dict[str, Any]) -> str:
    return f"{data.get(CONF_BRAND, DEFAULT_BRAND)}:{data[CONF_EMAIL].lower()}"


class SharedClient:
    """One portal client per account, shared by all VINs of that account."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        self.key = account_key(data)
        self.session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
        self.client = PortalClient(
            self.session,
            data[CONF_EMAIL],
            data[CONF_PASSWORD],
            brand=data.get(CONF_BRAND, DEFAULT_BRAND),
            country=data.get(CONF_COUNTRY, DEFAULT_COUNTRY),
            language=data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
        )
        self.refs = 0
        self._store = Store[dict[str, Any]](
            hass, COOKIE_STORE_VERSION, f"{DOMAIN}.cookies.{_safe(self.key)}"
        )
        self.client.on_session_changed = self.async_save_cookies

    async def async_load_cookies(self) -> None:
        stored = await self._store.async_load() or {}
        count = cookies_from_list(self.session.cookie_jar, stored.get("cookies", []))
        if count:
            self.client.logged_in = True
            _LOGGER.debug("restored %d portal cookies for %s", count, self.key)

    async def async_save_cookies(self) -> None:
        await self._store.async_save({"cookies": cookies_to_list(self.session.cookie_jar)})

    async def async_close(self) -> None:
        await self.session.close()


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)


async def async_get_shared_client(hass: HomeAssistant, data: dict[str, Any]) -> SharedClient:
    clients: dict[str, SharedClient] = hass.data.setdefault(DOMAIN, {}).setdefault("clients", {})
    key = account_key(data)
    shared = clients.get(key)
    if shared is None:
        shared = SharedClient(hass, data)
        await shared.async_load_cookies()
        clients[key] = shared
    shared.refs += 1
    return shared


async def async_release_shared_client(hass: HomeAssistant, shared: SharedClient) -> None:
    shared.refs -= 1
    if shared.refs <= 0:
        hass.data.get(DOMAIN, {}).get("clients", {}).pop(shared.key, None)
        await shared.async_close()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the refresh_now service."""

    async def _refresh_now(call: ServiceCall) -> None:
        entries = hass.config_entries.async_entries(DOMAIN)
        if entry_id := call.data.get("config_entry_id"):
            entries = [e for e in entries if e.entry_id == entry_id]
            if not entries:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="unknown_entry"
                )
        for entry in entries:
            if entry.state.recoverable and hasattr(entry, "runtime_data"):
                await entry.runtime_data.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_NOW, _refresh_now, schema=SERVICE_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VagDataActConfigEntry) -> bool:
    shared = await async_get_shared_client(hass, dict(entry.data))
    coordinator = VagDataActCoordinator(hass, entry, shared.client)
    await coordinator.async_load_state()
    entry.runtime_data = coordinator
    hass.data[DOMAIN].setdefault("shared", {})[entry.entry_id] = shared

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_VIN])},
        manufacturer=entry.data.get(CONF_BRAND, DEFAULT_BRAND).capitalize(),
        model=entry.data.get(CONF_NICKNAME) or "EU Data Act vehicle",
        name=entry.title,
        serial_number=entry.data[CONF_VIN],
    )

    # First poll must never block or fail setup: the health entities show the state.
    await coordinator.async_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: VagDataActConfigEntry) -> None:
    await entry.runtime_data.async_set_base_interval(
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
    )


async def async_unload_entry(hass: HomeAssistant, entry: VagDataActConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    shared = hass.data.get(DOMAIN, {}).get("shared", {}).pop(entry.entry_id, None)
    if shared is not None:
        await async_release_shared_client(hass, shared)
    return ok
