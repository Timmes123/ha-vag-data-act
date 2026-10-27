"""Pure-Python parser for EU Data Act dataset JSON documents (no Home Assistant imports).

Findings verified on the 14 Tavascan fixtures in ``tests/fixtures/raw`` (see
``tests/test_parser.py`` for the executable form of every statement):

* Every inner JSON is ``{"vin", "user_id", "Data": [171 points]}``; all values are
  strings (numbers, booleans, durations "6600s", epoch ms "1793123118186", ISO times).
* The 14 ZIPs contain only 3 distinct inner files (MD5): 8x ``…180109.json``,
  5x ``…194730.json``, 1x ``…200113.json``. ``…200113`` is byte-for-byte different
  from ``…194730`` but has identical key->value content (only the order differs).
  ``…180109`` vs ``…194730`` differ in exactly three points: ``instrument_cluster_time``
  (17:50:59+01:00 -> 18:45:15+01:00), one ``car_captured_time`` (16:51:00.748Z ->
  17:45:15.300Z) and one ``message_id`` (RPT_0 -> RPT_3). The mileage slots
  (10031 / 10044) are *identical* in all three files: the 10031 -> 10044 step from
  SPEC.md is the difference between the two ``mileage.value`` keys inside one file,
  not a difference between files.
* Order is random: consecutive distinct contents share only 5 of 171 positions.
* Keys are stable: all 14 files have the same 171-key set and every key maps to the
  same field name everywhere. Slots are resolved by key, never by position.
* Duplicate field names with different keys: ``settings.target_soc`` (100 user / 80
  effective), ``mileage.value`` (10031 / 10044), ``climatisation_state`` (VENTILATION /
  OFF), ``remaining_climate_time`` (1800s / 0s) plus identical copies of several
  settings fields. Resolution per field is documented in ``slots.py`` and
  ``docs/slot-mapping.md``.
* SoC triple source: ``battery_state_report.soc`` = 23, ``battery_level_HV.value`` =
  23.0, energy contents 167.5 / 773.5 (0.1 kWh) = 21.66 %. Only the first is used as
  SoC; the other two only serve the plausibility check (3 % tolerance).
* ``max(car_captured_time)`` over all ``car_captured_*`` fields = 2026-10-27T17:46:51Z
  in all three contents; a week-old report (2026-10-20) is part of every dataset, so
  ``max`` is mandatory. ZIP timestamps (16:10Z … 18:01Z all carrying the same
  ``…180109`` file) say nothing about data freshness.
* The data points carry no link to their report, therefore ``car_captured_at`` of a
  value is the dataset-wide maximum, not a per-point time.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .slots import (
    REPORT_META_FIELDS,
    REPORT_TIME_FIELDS,
    SLOTS,
    Kind,
    Policy,
    Slot,
    owner_of_key,
)

_LOGGER = logging.getLogger(__name__)

SOC_TOLERANCE_PERCENT = 3.0


class ParseError(ValueError):
    """The document is not a dataset JSON."""


@dataclass(frozen=True)
class Point:
    """One raw data point."""

    key: str
    field: str
    value: str


@dataclass
class SlotValue:
    """Resolved value of one slot."""

    name: str
    value: Any  # converted value, None if missing/ambiguous/implausible
    raw: str | None
    key: str | None
    field: str
    unit: str | None
    candidates: dict[str, str] = field(default_factory=dict)  # key -> raw (multi-slot)
    status: str = "ok"  # ok | shared | missing | ambiguous | implausible | invalid


@dataclass
class Ambiguity:
    """A slot whose copies contradict each other or fail a cross-check."""

    name: str
    field: str
    candidates: dict[str, str]
    reason: str


@dataclass
class ParsedDataset:
    """Normalized parser output."""

    vin: str
    point_count: int
    values: dict[str, SlotValue]
    last_vehicle_report: datetime | None
    report_times: list[datetime]
    metadata: dict[str, list[str]]
    unmapped: list[Point]
    ambiguities: list[Ambiguity]
    warnings: list[str]
    learned_keys: dict[str, str]  # slot name -> key learned via unique field name

    def get(self, name: str) -> Any:
        """Return the converted value of a slot (None if absent)."""
        sv = self.values.get(name)
        return sv.value if sv else None

    def normalized(self) -> dict[str, Any]:
        """Comparable view: slot values + ambiguities + unmapped keys (no timestamps of 'now')."""
        return {
            "values": {name: sv.value for name, sv in self.values.items()},
            "ambiguous": sorted(a.name for a in self.ambiguities),
            "unmapped": sorted(p.key for p in self.unmapped),
            "last_vehicle_report": self.last_vehicle_report,
        }


# --- value conversion ----------------------------------------------------------------


def parse_timestamp(raw: str) -> datetime | None:
    """Parse ISO-8601 (Z or offset) or epoch milliseconds into an aware datetime."""
    text = raw.strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=UTC)
        except OverflowError, OSError, ValueError:
            return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def parse_duration(raw: str) -> int | None:
    """Parse "6600s" (or a bare number) into seconds."""
    text = raw.strip().lower()
    text = text.removesuffix("s")
    try:
        return int(float(text))
    except ValueError:
        return None


def convert(slot: Slot, raw: str) -> Any:
    """Convert a raw string according to the slot kind. Returns None if invalid."""
    text = raw.strip()
    try:
        if slot.kind is Kind.INT:
            value: Any = int(float(text))
        elif slot.kind is Kind.FLOAT:
            value = float(text)
        elif slot.kind is Kind.BOOL:
            lowered = text.lower()
            if lowered not in ("true", "false"):
                return None
            return lowered == "true"
        elif slot.kind is Kind.DURATION:
            return parse_duration(text)
        elif slot.kind is Kind.TIMESTAMP:
            return parse_timestamp(text)
        else:
            return text
    except ValueError:
        return None
    if slot.scale is not None:
        value = round(value * slot.scale, 3)
    return value


# --- document handling ---------------------------------------------------------------


def load_points(document: bytes | str | dict[str, Any]) -> tuple[str, list[Point]]:
    """Validate a dataset document and return (vin, points)."""
    if isinstance(document, (bytes, str)):
        try:
            data = json.loads(document)
        except ValueError as err:
            raise ParseError(f"dataset is not valid JSON: {err}") from err
    else:
        data = document
    if not isinstance(data, dict) or not isinstance(data.get("Data"), list):
        raise ParseError("dataset JSON lacks the 'Data' list")
    points: list[Point] = []
    for idx, item in enumerate(data["Data"]):
        if not isinstance(item, dict):
            raise ParseError(f"data point {idx} is not an object")
        key = item.get("key")
        name = item.get("dataFieldName")
        value = item.get("value")
        if not isinstance(key, str) or not isinstance(name, str):
            raise ParseError(f"data point {idx} lacks key/dataFieldName")
        points.append(Point(key=key, field=name, value="" if value is None else str(value)))
    vin = data.get("vin")
    return (vin if isinstance(vin, str) else ""), points


def _resolve_keyed(
    slot: Slot,
    by_key: dict[str, Point],
    by_field: dict[str, list[Point]],
    key_override: str | None,
    learned: dict[str, str],
    ambiguities: list[Ambiguity],
) -> SlotValue:
    key = key_override or slot.key
    if key_override and (owner := owner_of_key(key_override)) not in (None, slot.name):
        # A learned key that belongs to another slot is never trusted (see below).
        _LOGGER.debug("slot %s: ignoring override %s owned by %s", slot.name, key_override, owner)
        key = slot.key
    point = by_key.get(key) if key else None
    if point is not None:
        if point.field != slot.field:
            # The key exists but carries a different field name: never trust it.
            ambiguities.append(
                Ambiguity(
                    slot.name,
                    slot.field,
                    {point.key: point.value},
                    f"key {point.key} carries field {point.field!r}, expected {slot.field!r}",
                )
            )
            return SlotValue(slot.name, None, None, None, slot.field, slot.unit, status="ambiguous")
        return _finish(slot, point.key, point.value)

    # Key unknown for this vehicle: fall back to the field name if it is unambiguous.
    candidates = by_field.get(slot.field, [])
    if not candidates:
        return SlotValue(slot.name, None, None, None, slot.field, slot.unit, status="missing")
    distinct = {p.value for p in candidates}
    if len(candidates) == 1:
        single = candidates[0]
        owner = owner_of_key(single.key)
        if owner is not None and owner != slot.name:
            # The only copy of this field is the key of another slot (Born: a single
            # ``settings.target_soc`` carrying the effective-target key). The value is
            # shared with that slot, but the key is *not* learned for this one.
            sv = _finish(slot, single.key, single.value)
            if sv.status == "ok":
                sv.status = "shared"
            return sv
        learned[slot.name] = single.key
        return _finish(slot, single.key, single.value)
    if len(distinct) == 1:
        # identical copies: any of them is fine, but do not learn a key
        return _finish(
            slot,
            None,
            candidates[0].value,
            candidates={p.key: p.value for p in candidates},
        )
    ambiguities.append(
        Ambiguity(
            slot.name,
            slot.field,
            {p.key: p.value for p in candidates},
            "key not known for this vehicle and field name occurs with different values",
        )
    )
    return SlotValue(
        slot.name,
        None,
        None,
        None,
        slot.field,
        slot.unit,
        candidates={p.key: p.value for p in candidates},
        status="ambiguous",
    )


def _resolve_multi(
    slot: Slot,
    by_field: dict[str, list[Point]],
    ambiguities: list[Ambiguity],
    warnings: list[str],
) -> SlotValue:
    candidates = by_field.get(slot.field, [])
    cand_map = {p.key: p.value for p in candidates}
    if not candidates:
        return SlotValue(slot.name, None, None, None, slot.field, slot.unit, status="missing")
    if slot.policy is Policy.MAX:
        best: Point | None = None
        best_value: Any = None
        for p in candidates:
            v = convert(slot, p.value)
            if v is None:
                continue
            if best_value is None or v > best_value:
                best, best_value = p, v
        if best is None:
            return SlotValue(
                slot.name, None, None, None, slot.field, slot.unit, cand_map, status="invalid"
            )
        return _finish(slot, best.key, best.value, candidates=cand_map)
    # Policy.AGREE
    distinct = {p.value for p in candidates}
    if len(distinct) == 1:
        return _finish(slot, None, candidates[0].value, candidates=cand_map)
    warnings.append(f"{slot.field}: copies disagree {cand_map}")
    ambiguities.append(Ambiguity(slot.name, slot.field, cand_map, "copies disagree"))
    return SlotValue(
        slot.name, None, None, None, slot.field, slot.unit, cand_map, status="ambiguous"
    )


def _finish(
    slot: Slot, key: str | None, raw: str, candidates: dict[str, str] | None = None
) -> SlotValue:
    value = convert(slot, raw)
    return SlotValue(
        slot.name,
        value,
        raw,
        key,
        slot.field,
        slot.unit,
        candidates=candidates or {},
        status="ok" if value is not None else "invalid",
    )


def _cross_checks(values: dict[str, SlotValue], ambiguities: list[Ambiguity]) -> None:
    """Plausibility rules from SPEC.md that span several slots."""
    soc = values["soc"]
    if soc.value is not None:
        refs: dict[str, float] = {}
        hv = values["battery_level_hv"].value
        if hv is not None:
            refs["battery_level_hv"] = float(hv)
        cur, mx = values["energy_content_current"].value, values["energy_content_max"].value
        if cur is not None and mx:
            refs["energy_quotient"] = round(100.0 * cur / mx, 2)
        bad = {k: v for k, v in refs.items() if abs(v - soc.value) > SOC_TOLERANCE_PERCENT}
        if bad:
            ambiguities.append(
                Ambiguity(
                    "soc",
                    soc.field,
                    {soc.key or "": soc.raw or "", **{k: str(v) for k, v in bad.items()}},
                    f"soc {soc.value} deviates >{SOC_TOLERANCE_PERCENT:g} % from {bad}",
                )
            )
            soc.value = None
            soc.status = "implausible"

    user, eff, bcam = (
        values["target_soc_user"].value,
        values["target_soc_effective"].value,
        values["bcam_threshold"].value,
    )
    if user is not None and eff is not None and bcam is not None and eff != min(user, bcam):
        ambiguities.append(
            Ambiguity(
                "target_soc_effective",
                "settings.target_soc",
                {"user": str(user), "effective": str(eff), "bcam_threshold": str(bcam)},
                "effective target is not min(user, bcam_threshold)",
            )
        )


def parse_points(
    vin: str,
    points: list[Point],
    key_overrides: dict[str, str] | None = None,
) -> ParsedDataset:
    """Resolve all slots from the raw points."""
    overrides = key_overrides or {}
    by_key: dict[str, Point] = {}
    by_field: dict[str, list[Point]] = defaultdict(list)
    warnings: list[str] = []
    for p in points:
        if p.key in by_key:
            warnings.append(f"duplicate key {p.key} ({p.field})")
        by_key[p.key] = p
        by_field[p.field].append(p)

    ambiguities: list[Ambiguity] = []
    learned: dict[str, str] = {}
    values: dict[str, SlotValue] = {}
    consumed: set[str] = set()

    for slot in SLOTS:
        if slot.policy is Policy.KEYED:
            sv = _resolve_keyed(
                slot, by_key, by_field, overrides.get(slot.name), learned, ambiguities
            )
        else:
            sv = _resolve_multi(slot, by_field, ambiguities, warnings)
        values[slot.name] = sv
        if sv.key:
            consumed.add(sv.key)
        consumed.update(sv.candidates)
        if sv.status == "missing" and slot.key:
            _LOGGER.debug("slot %s: key %s not present in dataset", slot.name, slot.key)

    _cross_checks(values, ambiguities)

    report_times: list[datetime] = []
    metadata: dict[str, list[str]] = defaultdict(list)
    unmapped: list[Point] = []
    for p in points:
        if p.field in REPORT_TIME_FIELDS:
            consumed.add(p.key)
            metadata[p.field].append(p.value)
            ts = parse_timestamp(p.value)
            if ts is not None:
                report_times.append(ts)
            else:
                warnings.append(f"unparseable report time {p.value!r} ({p.key})")
        elif p.field in REPORT_META_FIELDS:
            consumed.add(p.key)
            metadata[p.field].append(p.value)
        elif p.key not in consumed:
            unmapped.append(p)

    unmapped.sort(key=lambda p: (p.field, p.key))
    return ParsedDataset(
        vin=vin,
        point_count=len(points),
        values=values,
        last_vehicle_report=max(report_times) if report_times else None,
        report_times=sorted(report_times),
        metadata={k: sorted(v) for k, v in metadata.items()},
        unmapped=unmapped,
        ambiguities=ambiguities,
        warnings=warnings,
        learned_keys=learned,
    )


def parse_dataset(
    document: bytes | str | dict[str, Any],
    key_overrides: dict[str, str] | None = None,
) -> ParsedDataset:
    """Parse a dataset JSON document (bytes, text or already-decoded dict)."""
    vin, points = load_points(document)
    return parse_points(vin, points, key_overrides)
