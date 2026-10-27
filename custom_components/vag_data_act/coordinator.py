"""DataUpdateCoordinator: one portal client per account, one coordinator per VIN.

Every poll lists the portal packages and downloads *every package not processed yet*
(oldest first). Packages are partial (see ``parser.py``), so their points are merged by
key into a persistent store; the entities are fed from the merged store. Downloads are
throttled (``DOWNLOAD_DELAY_S``) and stop at HTTP 429, the rest follows on the next poll.
"""

from __future__ import annotations

import asyncio
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
    DatasetInfo,
    NotConfigured,
    PortalClient,
    PortalError,
    PortalOutage,
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
from .parser import (
    ParsedDataset,
    Point,
    load_points,
    merge_points,
    package_capture_time,
    parse_points,
    points_from_json,
    points_to_json,
    stamp_points,
    summarize_points,
)
from .slots import foreign_key_overrides

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 2


class VehicleStore(Store[dict[str, Any]]):
    """Per-VIN store. Version 1 (<= 0.1.2) kept only the newest package as ``last_content``;
    ``async_load_state`` seeds the point store from it, so the data passes through unchanged."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        return old_data


# The portal answers HTTP 429 after ~25 downloads in a row (live scan 2026-10-27).
DOWNLOAD_DELAY_S = 1.0
# Package names remembered as processed (the portal lists 30).
PROCESSED_KEEP = 200


@dataclass
class VehicleData:
    """Coordinator data. Vehicle values persist across failed polls."""

    parsed: ParsedDataset | None = None
    login_status: str = LOGIN_STATUS_UNKNOWN
    last_error: str | None = None
    last_successful_download: datetime | None = None
    last_attempt: datetime | None = None
    dataset_name: str | None = None  # newest processed package (ZIP)
    inner_name: str | None = None  # its inner file name
    dataset_hash: str | None = None  # its SHA-256
    dataset_created_on: datetime | None = None
    dataset_changed: bool = False  # did the last poll change any point
    dataset_count: int = 0  # packages listed by the portal
    packages_processed: int = 0  # packages downloaded in the last poll
    packages_pending: int = 0  # listed packages not processed yet (rate limit)
    identifier: str | None = None
    key_overrides: dict[str, str] = field(default_factory=dict)
    request_metadata: dict[str, Any] = field(default_factory=dict)
    last_scan: list[dict[str, Any]] = field(default_factory=list)
    processed: list[str] = field(default_factory=list)  # ZIP names, oldest first
    points: dict[str, Point] = field(default_factory=dict)  # merged key -> point store

    @property
    def last_vehicle_report(self) -> datetime | None:
        return self.parsed.last_vehicle_report if self.parsed else None

    def data_age_minutes(self) -> int | None:
        return minutes_since(self.last_vehicle_report)


def minutes_since(when: datetime | None) -> int | None:
    if when is None:
        return None
    return max(0, int((dt_util.utcnow() - when).total_seconds() // 60))


class VagDataActCoordinator(DataUpdateCoordinator[VehicleData]):
    """Downloads every unseen package and merges it into the point store."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PortalClient) -> None:
        self.client = client
        self.vin: str = entry.data[CONF_VIN]
        self._store = VehicleStore(hass, STORE_VERSION, f"{DOMAIN}.{self.vin}")
        self._outage_count = 0
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
        data = self.data
        data.key_overrides = dict(stored.get("key_overrides", {}))
        for name, key in foreign_key_overrides(data.key_overrides).items():
            # Learned before 0.1.1: a key that belongs to another slot of the same field
            # (Born: target_soc_user -> effective-target key). Never trust it.
            _LOGGER.info("dropping learned key %s for %s (belongs to another slot)", key, name)
            data.key_overrides.pop(name)
        data.request_metadata = dict(stored.get("request_metadata", {}))
        data.identifier = stored.get("identifier")
        data.dataset_hash = stored.get("dataset_hash")
        data.inner_name = stored.get("inner_name")
        data.dataset_name = stored.get("dataset_name")
        if stored.get("last_successful_download"):
            data.last_successful_download = dt_util.parse_datetime(
                stored["last_successful_download"]
            )
        data.processed = [str(n) for n in stored.get("processed", [])]
        data.points = points_from_json(stored.get("points", []))
        if not data.points and (content := stored.get("last_content")):
            # Store version 1 (<= 0.1.2) kept only the newest package: seed the store with it.
            try:
                _, points = load_points(content)
            except ValueError as err:
                _LOGGER.warning("stored dataset for …%s unreadable: %s", self.vin[-4:], err)
            else:
                merge_points(data.points, stamp_points(points, data.inner_name))
                if data.dataset_name:
                    data.processed = [data.dataset_name]
                _LOGGER.info(
                    "migrated store of …%s: %d points from %s",
                    self.vin[-4:],
                    len(points),
                    data.inner_name,
                )
        if data.points:
            self._reparse()

    async def _async_save_state(self) -> None:
        data = self.data
        await self._store.async_save(
            {
                "key_overrides": data.key_overrides,
                "identifier": data.identifier,
                "request_metadata": data.request_metadata,
                "dataset_hash": data.dataset_hash,
                "inner_name": data.inner_name,
                "dataset_name": data.dataset_name,
                "last_successful_download": data.last_successful_download.isoformat()
                if data.last_successful_download
                else None,
                "processed": data.processed[-PROCESSED_KEEP:],
                "points": points_to_json(data.points),
            }
        )

    # -- parsing ----------------------------------------------------------------------

    def _reparse(self) -> None:
        data = self.data
        parsed = parse_points(self.vin, list(data.points.values()), data.key_overrides)
        for warning in parsed.warnings:
            _LOGGER.warning("…%s: %s", self.vin[-4:], warning)
        if parsed.learned_keys:
            _LOGGER.info("learned slot keys for …%s: %s", self.vin[-4:], parsed.learned_keys)
            data.key_overrides.update(parsed.learned_keys)
        data.parsed = parsed

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

    @staticmethod
    def _pending(datasets: list[DatasetInfo], processed: list[str]) -> list[DatasetInfo]:
        """Unprocessed content packages, oldest first (never by list order)."""
        done = set(processed)
        pending = [
            d for d in datasets if d.has_content and d.created_on is not None and d.name not in done
        ]
        return sorted(pending, key=lambda d: (d.created_on, d.name))  # type: ignore[return-value]

    async def _async_update_data(self) -> VehicleData:
        data = self.data
        data.last_attempt = dt_util.utcnow()
        data.dataset_changed = False
        data.packages_processed = 0
        try:
            if data.identifier is None or not data.request_metadata:
                data.identifier = await self.client.async_get_identifier(self.vin)
                data.request_metadata = dict(self.client.request_metadata.get(self.vin, {}))
            datasets = await self.client.async_list_datasets(self.vin, data.identifier)
            data.dataset_count = len(datasets)
            pending = self._pending(datasets, data.processed)
            if not datasets:
                _LOGGER.info("no content dataset delivered yet for …%s", self.vin[-4:])
            elif not pending:
                _LOGGER.debug(
                    "…%s: all %d listed packages already processed", self.vin[-4:], len(datasets)
                )
            else:
                _LOGGER.info(
                    "…%s: %d of %d packages not processed yet",
                    self.vin[-4:],
                    len(pending),
                    len(datasets),
                )
            changed_total = 0
            rate_limited: str | None = None
            for index, info in enumerate(pending):
                if index:
                    await asyncio.sleep(DOWNLOAD_DELAY_S)
                try:
                    dataset = await self.client.async_download_dataset(
                        self.vin, data.identifier, info.name
                    )
                except PortalOutage as err:
                    if err.status == 429:
                        rate_limited = str(err)
                        break
                    raise
                try:
                    _, points = load_points(dataset.content)
                except ValueError as err:
                    _LOGGER.error("…%s: %s unreadable, skipped: %s", self.vin[-4:], info.name, err)
                    data.processed.append(info.name)
                    continue
                captured = package_capture_time(points)
                changed = merge_points(
                    data.points, stamp_points(points, dataset.inner_name, captured)
                )
                summary = summarize_points(points)
                _LOGGER.info(
                    "downloaded %s (inner %s, sha256 %s, %d points, reports %s, soc %s, "
                    "captured %s): %d points changed",
                    dataset.zip_name,
                    dataset.inner_name,
                    dataset.sha256[:16],
                    summary["points"],
                    summary["message_ids"],
                    summary["has_soc"],
                    captured.isoformat() if captured else "?",
                    changed,
                )
                changed_total += changed
                data.processed.append(info.name)
                data.packages_processed += 1
                data.dataset_name = dataset.zip_name
                data.inner_name = dataset.inner_name
                data.dataset_hash = dataset.sha256
                data.dataset_created_on = info.created_on
            data.processed = data.processed[-PROCESSED_KEEP:]
            data.packages_pending = len(pending) - data.packages_processed
            if data.packages_processed:
                if changed_total:
                    self._reparse()
                    data.dataset_changed = True
                else:
                    _LOGGER.info(
                        "…%s: %d package(s) without changes", self.vin[-4:], data.packages_processed
                    )
                await self._async_save_state()
            if rate_limited:
                _LOGGER.warning(
                    "…%s: rate limited after %d package(s), %d remain for the next poll (%s)",
                    self.vin[-4:],
                    data.packages_processed,
                    data.packages_pending,
                    rate_limited,
                )
                if not data.packages_processed:
                    raise PortalOutage(rate_limited, status=429)
            data.last_successful_download = dt_util.utcnow()
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

    async def async_scan_datasets(self) -> list[dict[str, Any]]:
        """Diagnostic: download *every* listed package (newest first) and summarize it.

        Shows which reports each package carries. Runs over the normal session, throttled;
        results are logged, kept in ``data.last_scan`` and shown in the diagnostics
        download. Entities and the point store are not touched.
        """
        data = self.data
        results: list[dict[str, Any]] = []
        try:
            if data.identifier is None:
                data.identifier = await self.client.async_get_identifier(self.vin)
            datasets = await self.client.async_list_datasets(self.vin, data.identifier)
            ordered = sorted(
                (d for d in datasets if d.created_on is not None),
                key=lambda d: d.created_on,  # type: ignore[arg-type, return-value]
                reverse=True,
            )
            _LOGGER.info("scan …%s: %d datasets listed", self.vin[-4:], len(datasets))
            seen_fields: set[str] = set()
            for index, info in enumerate(ordered):
                entry: dict[str, Any] = {
                    "zip": info.name,
                    "created_on": info.created_on.isoformat() if info.created_on else None,
                    "size": info.size,
                }
                if not info.has_content:
                    entry["summary"] = "no content"
                    results.append(entry)
                    continue
                if index:
                    await asyncio.sleep(DOWNLOAD_DELAY_S)
                try:
                    ds = await self.client.async_download_dataset(
                        self.vin, data.identifier, info.name
                    )
                    _, points = load_points(ds.content)
                except (PortalError, ValueError) as err:
                    entry["error"] = str(err)
                    results.append(entry)
                    _LOGGER.warning("scan …%s: %s failed: %s", self.vin[-4:], info.name, err)
                    if isinstance(err, PortalOutage) and err.status == 429:
                        break
                    continue
                summary = summarize_points(points)
                new_fields = sorted({p.field for p in points} - seen_fields)
                seen_fields.update(p.field for p in points)
                captured = package_capture_time(points)
                entry.update(
                    inner=ds.inner_name,
                    sha256=ds.sha256[:16],
                    captured_at=captured.isoformat() if captured else None,
                    **summary,
                )
                entry["new_fields"] = new_fields
                results.append(entry)
                _LOGGER.info(
                    "scan …%s: %s -> %s sha256=%s points=%d fields=%d soc=%s charging_state=%s "
                    "captured=%s reports=%s new_fields=%s",
                    self.vin[-4:],
                    info.name,
                    ds.inner_name,
                    ds.sha256[:16],
                    summary["points"],
                    summary["fields"],
                    summary["has_soc"],
                    summary["has_charging_state"],
                    captured.isoformat() if captured else "?",
                    summary["message_ids"],
                    new_fields,
                )
            _LOGGER.info(
                "scan …%s finished: %d datasets, %d distinct fields overall, soc in any: %s",
                self.vin[-4:],
                len(results),
                len(seen_fields),
                any(r.get("has_soc") for r in results),
            )
        except (PortalError, ValueError) as err:
            _LOGGER.error("scan …%s aborted: %s", self.vin[-4:], err)
            results.append({"error": str(err)})
        data.last_scan = results
        self.async_update_listeners()
        return results

    async def async_set_base_interval(self, minutes: int) -> None:
        self._base_interval = timedelta(minutes=minutes)
        self._set_interval(outage=False)
