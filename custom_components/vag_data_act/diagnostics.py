"""Diagnostics with VIN, e-mail, password, cookies and identifiers redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import VagDataActConfigEntry
from .api import redact_url
from .const import CONF_VIN

REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_VIN, "vin", "identifier", "user_id", "cookies"}


def _hide_vin_deep(value: Any, vin: str) -> Any:
    if isinstance(value, str):
        return value.replace(vin, "**VIN**")
    if isinstance(value, dict):
        return {k: _hide_vin_deep(v, vin) for k, v in value.items()}
    if isinstance(value, list):
        return [_hide_vin_deep(v, vin) for v in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VagDataActConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    parsed = data.parsed
    vin = entry.data[CONF_VIN]

    def _hide_vin(text: str | None) -> str | None:
        return text.replace(vin, "**VIN**") if text else text

    payload: dict[str, Any] = {
        "entry": {"data": dict(entry.data), "options": dict(entry.options), "title": entry.title},
        "health": {
            "login_status": data.login_status,
            "last_error": _hide_vin(data.last_error),
            "last_successful_download": data.last_successful_download,
            "last_attempt": data.last_attempt,
            "last_vehicle_report": data.last_vehicle_report,
            "data_age_minutes": data.data_age_minutes(),
            "dataset_name": _hide_vin(data.dataset_name),
            "inner_name": _hide_vin(data.inner_name),
            "dataset_hash": data.dataset_hash,
            "dataset_changed": data.dataset_changed,
            "datasets_listed": data.dataset_count,
            "update_interval_s": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "key_overrides": data.key_overrides,
            "data_request": _hide_vin_deep(data.request_metadata, vin),
            "last_scan": _hide_vin_deep(data.last_scan, vin),
            "packages_processed_last_poll": data.packages_processed,
            "packages_pending": data.packages_pending,
            "processed": [_hide_vin(n) for n in data.processed[-40:]],
            "point_store_size": len(data.points),
        },
        "login_hops": [
            {"method": h.method, "url": redact_url(h.url), "status": h.status}
            for h in coordinator.client.last_login_hops
        ],
    }
    if parsed:
        payload["parsed"] = {
            "point_count": parsed.point_count,
            "values": {name: asdict(sv) for name, sv in parsed.values.items()},
            "ambiguities": [asdict(a) for a in parsed.ambiguities],
            "unmapped": [asdict(p) for p in parsed.unmapped],
            "metadata": parsed.metadata,
            "warnings": parsed.warnings,
        }
    return async_redact_data(payload, REDACT)
