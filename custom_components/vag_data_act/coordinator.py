"""DataUpdateCoordinator: one portal client per account, one coordinator per VIN."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    AuthFailed,
    ConsentRequired,
    NotConfigured,
    PortalClient,
    PortalError,
    PortalOutage,
    newest_dataset,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_VIN,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    ISSUE_AUTH_FAILED,
    ISSUE_CONSENT_REQUIRED,
    LOGIN_STATUS_AUTH_FAILED,
    LOGIN_STATUS_CONSENT_REQUIRED,
    LOGIN_STATUS_OK,
    LOGIN_STATUS_PORTAL_ERROR,
    LOGIN_STATUS_UNKNOWN,
    MAX_OUTAGE_BACKOFF_MINUTES,
)
from .parser import ParsedDataset, parse_dataset

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1


@dataclass
class VehicleData:
    """Coordinator data. Vehicle values persist across failed polls."""

    parsed: ParsedDataset | None = None
    login_status: str = LOGIN_STATUS_UNKNOWN
    last_error: str | None = None
    last_successful_download: datetime | None = None
    last_attempt: datetime | None = None
    dataset_name: str | None = None
    inner_name: str | None = None
    dataset_hash: str | None = None
    dataset_created_on: datetime | None = None
    dataset_changed: bool = False
    dataset_count: int = 0
    identifier: str | None = None
    key_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def last_vehicle_report(self) -> datetime | None:
        return self.parsed.last_vehicle_report if self.parsed else None

    def data_age_minutes(self) -> int | None:
        if self.last_vehicle_report is None:
            return None
        return max(0, int((dt_util.utcnow() - self.last_vehicle_report).total_seconds() // 60))


class VagDataActCoordinator(DataUpdateCoordinator[VehicleData]):
    """Polls the newest dataset and only re-parses when the content changed."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PortalClient) -> None:
        self.client = client
        self.vin: str = entry.data[CONF_VIN]
        self._store = Store[dict[str, Any]](hass, STORE_VERSION, f"{DOMAIN}.{self.vin}")
        self._outage_count = 0
        self._last_content: bytes | None = None
        self._base_interval = timedelta(
            minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.vin[-4:]}",
            update_interval=self._base_interval,
        )
        self.data = VehicleData()

    # -- persistence ------------------------------------------------------------------

    async def async_load_state(self) -> None:
        stored = await self._store.async_load() or {}
        self.data.key_overrides = dict(stored.get("key_overrides", {}))
        self.data.identifier = stored.get("identifier")
        self.data.dataset_hash = stored.get("dataset_hash")
        self.data.inner_name = stored.get("inner_name")
        self.data.dataset_name = stored.get("dataset_name")
        if stored.get("last_successful_download"):
            self.data.last_successful_download = dt_util.parse_datetime(
                stored["last_successful_download"]
            )
        content = stored.get("last_content")
        if content:
            self._last_content = content.encode("utf-8")
            try:
                self.data.parsed = parse_dataset(content, self.data.key_overrides)
            except ValueError as err:
                _LOGGER.warning("stored dataset for %s unreadable: %s", self.vin[-4:], err)

    async def _async_save_state(self) -> None:
        content = self._last_content
        await self._store.async_save(
            {
                "key_overrides": self.data.key_overrides,
                "identifier": self.data.identifier,
                "dataset_hash": self.data.dataset_hash,
                "inner_name": self.data.inner_name,
                "dataset_name": self.data.dataset_name,
                "last_successful_download": self.data.last_successful_download.isoformat()
                if self.data.last_successful_download
                else None,
                "last_content": content.decode("utf-8", "replace") if content else None,
            }
        )

    # -- polling ----------------------------------------------------------------------

    def _set_interval(self, outage: bool) -> None:
        if outage:
            self._outage_count += 1
            minutes = min(
                self._base_interval.total_seconds() / 60 * (2**self._outage_count),
                MAX_OUTAGE_BACKOFF_MINUTES,
            )
            self.update_interval = timedelta(minutes=minutes)
            _LOGGER.warning("portal outage, next attempt in %d min", minutes)
        else:
            self._outage_count = 0
            self.update_interval = self._base_interval

    async def _async_update_data(self) -> VehicleData:
        data = self.data
        data.last_attempt = dt_util.utcnow()
        data.dataset_changed = False
        try:
            if data.identifier is None:
                data.identifier = await self.client.async_get_identifier(self.vin)
            datasets = await self.client.async_list_datasets(self.vin, data.identifier)
            data.dataset_count = len(datasets)
            newest = newest_dataset(datasets)
            if newest is None:
                _LOGGER.info("no content dataset delivered yet for …%s", self.vin[-4:])
            elif newest.name != data.dataset_name or data.dataset_hash is None:
                dataset = await self.client.async_download_dataset(
                    self.vin, data.identifier, newest.name
                )
                changed = dataset.sha256 != data.dataset_hash
                _LOGGER.info(
                    "downloaded %s (inner %s, sha256 %s, %s)",
                    dataset.zip_name,
                    dataset.inner_name,
                    dataset.sha256[:16],
                    "content changed" if changed else "content unchanged",
                )
                data.dataset_name = dataset.zip_name
                data.dataset_created_on = newest.created_on
                if changed:
                    parsed = parse_dataset(dataset.content, data.key_overrides)
                    for warning in parsed.warnings:
                        _LOGGER.warning("…%s: %s", self.vin[-4:], warning)
                    if parsed.learned_keys:
                        _LOGGER.info(
                            "learned slot keys for …%s: %s", self.vin[-4:], parsed.learned_keys
                        )
                        data.key_overrides.update(parsed.learned_keys)
                    data.parsed = parsed
                    data.inner_name = dataset.inner_name
                    data.dataset_hash = dataset.sha256
                    data.dataset_changed = True
                    self._last_content = dataset.content
                data.last_successful_download = dt_util.utcnow()
                await self._async_save_state()
            else:
                data.last_successful_download = dt_util.utcnow()
                _LOGGER.debug("newest dataset %s already processed", newest.name)
            self._set_login_status(LOGIN_STATUS_OK, None)
            self._set_interval(outage=False)
        except AuthFailed as err:
            self._set_login_status(LOGIN_STATUS_AUTH_FAILED, str(err))
            self._set_interval(outage=False)
            self.config_entry.async_start_reauth(self.hass)
        except ConsentRequired as err:
            self._set_login_status(LOGIN_STATUS_CONSENT_REQUIRED, str(err))
            self._set_interval(outage=False)
        except PortalOutage as err:
            self._set_login_status(LOGIN_STATUS_PORTAL_ERROR, str(err))
            self._set_interval(outage=True)
        except (NotConfigured, PortalError, ValueError) as err:
            data.identifier = None if isinstance(err, NotConfigured) else data.identifier
            self._set_login_status(LOGIN_STATUS_PORTAL_ERROR, str(err))
            self._set_interval(outage=False)
            _LOGGER.error("update for …%s failed: %s", self.vin[-4:], err)
        return data

    def _set_login_status(self, status: str, error: str | None) -> None:
        data = self.data
        if status != data.login_status or error != data.last_error:
            _LOGGER.log(
                logging.INFO if status == LOGIN_STATUS_OK else logging.WARNING,
                "login status for …%s: %s%s",
                self.vin[-4:],
                status,
                f" ({error})" if error else "",
            )
        data.login_status = status
        data.last_error = error
        for issue, wanted in (
            (ISSUE_AUTH_FAILED, status == LOGIN_STATUS_AUTH_FAILED),
            (ISSUE_CONSENT_REQUIRED, status == LOGIN_STATUS_CONSENT_REQUIRED),
        ):
            issue_id = f"{issue}_{self.config_entry.entry_id}"
            if wanted:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=issue == ISSUE_CONSENT_REQUIRED,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key=issue,
                    translation_placeholders={
                        "title": self.config_entry.title,
                        "error": error or "",
                    },
                    data={"entry_id": self.config_entry.entry_id},
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def async_set_base_interval(self, minutes: int) -> None:
        self._base_interval = timedelta(minutes=minutes)
        self._set_interval(outage=False)
