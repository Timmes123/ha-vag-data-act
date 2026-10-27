"""Slot mapping for the VW group EU Data Act dataset (field name -> key -> meaning).

A dataset is a flat list of ``{"key": <uuid v3>, "dataFieldName": <dotted path>,
"value": <string>}`` points. The ``key`` is stable across downloads (verified on all
14 fixtures: identical key sets, identical key->field mapping), while several field
names occur more than once with *different* keys and sometimes contradictory values.
Slots therefore identify a data point by ``key`` first; the field name is only used
as a fallback when the key is unknown for a vehicle and the field name is unique in
the dataset (see ``parser.parse_dataset``).

Keys below were verified on the Tavascan fixtures (VIN VSSZZZKRXSA000001, 2026-10-27).
Keys are UUID v3 (name based) and evcc hard-codes the very same values for other
MEB vehicles (``battery_state_report.soc`` = 506cb83e-… on ID.3/Enyaq), so they are
expected to be identical for the Born; the per-VIN override store covers deviations.

This module is pure Python and must not import Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    """How the raw string value is converted."""

    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    ENUM = "enum"
    STR = "str"
    DURATION = "duration"  # "6600s" -> 6600 (seconds)
    TIMESTAMP = "timestamp"  # ISO-8601 (Z or offset) or epoch milliseconds


class Policy(str, Enum):
    """How a slot resolves its data point(s)."""

    # Exactly one data point, identified by key. Fallback: field name, if unique.
    KEYED = "keyed"
    # Field occurs several times; the value is the maximum (monotone counters).
    MAX = "max"
    # Field occurs several times; the value is taken only if all copies agree,
    # otherwise the slot is reported as ambiguous and has no value.
    AGREE = "agree"


@dataclass(frozen=True)
class Slot:
    """One normalized output value."""

    name: str
    field: str
    meaning: str
    kind: Kind = Kind.STR
    unit: str | None = None
    key: str | None = None
    policy: Policy = Policy.KEYED
    scale: float | None = None  # multiply the numeric value (0.1 kWh -> kWh)
    note: str = ""


# --- report metadata ------------------------------------------------------------
# These field names describe the ~9 vehicle reports that are mixed into one dataset.
# They occur many times each, are not attributable to a value and are exposed only in
# diagnostics. They are *not* counted as unmapped.
REPORT_TIME_FIELDS: frozenset[str] = frozenset(
    {
        "car_captured_time",
        "car_captured_utc_timestamp",
        "profile_state_report.car_captured_time",
    }
)
REPORT_META_FIELDS: frozenset[str] = frozenset(
    {
        "message_id",
        "report_type",
        "timestamp",
        "transaction_id",
        "trigger",
        "update_reason",
        "state",  # bare "VALID" x3
        "mileage.state",
        "battery_level_HV.state",
    }
)

# --- slots ------------------------------------------------------------------------
SLOTS: tuple[Slot, ...] = (
    # Battery / SoC
    Slot(
        "soc",
        "battery_state_report.soc",
        "State of charge as displayed in the vehicle",
        Kind.INT,
        "%",
        key="506cb83e-f99f-3af3-bbeb-0429b69a78d9",
        note="The only permitted SoC source. Plausibility-checked against "
        "battery_level_hv and the energy content quotient (>3 % deviation -> no value).",
    ),
    Slot(
        "battery_level_hv",
        "battery_level_HV.value",
        "HV battery level (second SoC source, plausibility only)",
        Kind.FLOAT,
        "%",
        key="ac1108b1-b8cc-3db9-a663-03d387e42223",
    ),
    Slot(
        "energy_content_current",
        "energy_contents.current_energy_content.physical_value",
        "Current usable battery energy",
        Kind.FLOAT,
        "kWh",
        key="84e64812-6eaa-3477-b587-0c5b02d8446f",
        scale=0.1,
        note="Delivered in 0.1 kWh (167.5 -> 16.75 kWh).",
    ),
    Slot(
        "energy_content_max",
        "energy_contents.maximal_energy_content.physical_value",
        "Maximum usable battery energy",
        Kind.FLOAT,
        "kWh",
        key="09ed1319-7b17-31c6-ba74-817ce91a4c1d",
        scale=0.1,
        note="Delivered in 0.1 kWh (773.5 -> 77.35 kWh).",
    ),
    Slot(
        "range",
        "value",
        "Cruising range",
        Kind.INT,
        "km",
        key="0ca40e18-0564-3eda-bcc0-7aee9ef44f04",
        note="Bare field name 'value' without context; mapped by key only. evcc "
        "(vehicle/vw/eudataact/types.go, KeyRangeID3) documents this key as the MEB "
        "range. Confirmed live 2026-10-27: Tavascan display 90 km at 23 % = this key.",
    ),
    # Odometer
    Slot(
        "odometer",
        "mileage.value",
        "Odometer",
        Kind.INT,
        "km",
        policy=Policy.MAX,
        note="Two slots (75d65f00-… departure 10031, 30cc36fd-… arrival 10044). "
        "Monotone counter -> maximum of all copies.",
    ),
    # Charge target
    Slot(
        "target_soc_user",
        "settings.target_soc",
        "Charge target set by the user",
        Kind.INT,
        "%",
        key="e21d4d25-98bc-3016-a234-1ad061cc313b",
        note="100 on the fixture while the effective target is 80.",
    ),
    Slot(
        "target_soc_effective",
        "settings.target_soc",
        "Effective charge target (user target capped by battery care mode)",
        Kind.INT,
        "%",
        key="b3b04f31-b10e-38aa-b8ad-c0da7c06caea",
        note="80 on the fixture = min(user 100, bcam threshold 80). The parser "
        "cross-checks this relation and flags an ambiguity if it does not hold.",
    ),
    Slot(
        "bcam_threshold",
        "battery_care_mode.charge_bcam_threshold",
        "Battery care mode charge threshold",
        Kind.INT,
        "%",
        key="9185af4f-0ef9-3e85-a533-340303acb264",
    ),
    # Charging
    Slot(
        "charging_state",
        "charging_state_report.current_charge_state",
        "Charging state",
        Kind.ENUM,
        key="a08cca2b-ed42-37bc-b160-d015ce205d3d",
    ),
    Slot(
        "charging_error_code",
        "charging_state_report.error_code",
        "Charging error code",
        Kind.INT,
        key="d726c45d-3772-39be-80c1-0e82d448aa95",
    ),
    Slot(
        "charging_error_text",
        "error_description",
        "Charging error description",
        Kind.STR,
        key="0a7ecca3-e96a-3745-9bf8-2bac574dfe9d",
        note="Bare field of the RbcErrorReport; error_number (28) matches "
        "charging_state_report.error_code (28).",
    ),
    Slot(
        "charging_error_number",
        "error_number",
        "Charging error number (RbcErrorReport)",
        Kind.INT,
        key="639f00ab-3d10-3918-b318-e2de7484358c",
    ),
    Slot(
        "charging_scenario",
        "charging_state_report.charging_scenario",
        "Charging scenario",
        Kind.ENUM,
        key="a8b48aad-8cd4-3534-b64d-6c8abd600972",
    ),
    Slot(
        "immediate_action_state",
        "charging_state_report.immediate_action_state",
        "Immediate action state",
        Kind.ENUM,
        key="4c4f3038-d18b-3d3c-87fd-335cbfa4b364",
    ),
    Slot(
        "charge_power",
        "battery_state_report.charge_power",
        "Charging power",
        Kind.FLOAT,
        "kW",
        key="c8cb205f-01c6-3c81-bda1-059b99ae6515",
    ),
    Slot(
        "charge_rate",
        "battery_state_report.charge_rate",
        "Charging rate",
        Kind.FLOAT,
        "km/h",
        key="1efb6000-6b54-366a-9233-d320699687cf",
        note="Unit confirmed by battery_state_report.charge_rate_unit = CHARGE_RATE_UNIT_KM_PER_H.",
    ),
    Slot(
        "charge_rate_unit",
        "battery_state_report.charge_rate_unit",
        "Unit of charge_rate",
        Kind.ENUM,
        key="9c83ccaa-5288-38da-9d38-81ef8db469b3",
    ),
    Slot(
        "remaining_charging_time",
        "battery_state_report.remaining_charging_time_complete",
        "Remaining time until the charge target is reached",
        Kind.DURATION,
        "s",
        key="7405c11f-4d20-36d2-8381-18364aa1f444",
        note='"6600s" -> 6600 s. Only meaningful while charging is active.',
    ),
    Slot(
        "charge_energy",
        "battery_state_report.charge_energy",
        "Energy charged",
        Kind.FLOAT,
        "kWh",
        key="e532aed3-190a-3ff0-bfa4-2e05c61c929e",
    ),
    Slot(
        "charge_mode",
        "charging_state_report.charge_mode",
        "Charge mode",
        Kind.ENUM,
        key="45410f9e-b068-3dc7-9afb-238a2ef7454e",
    ),
    Slot(
        "charge_type",
        "charging_state_report.charge_type",
        "Charge type (AC/DC)",
        Kind.ENUM,
        key="a5fa0f82-e717-36ec-a1d7-ed05b47295f8",
    ),
    Slot(
        "max_charge_current_ac",
        "settings.max_charge_current_ac",
        "Maximum AC charge current setting",
        Kind.ENUM,
        policy=Policy.AGREE,
        note="Two identical copies (0387de65-…, 63e08d24-…).",
    ),
    Slot(
        "auto_unlock_ac",
        "settings.auto_unlock_ac",
        "Auto unlock plug after AC charging",
        Kind.ENUM,
        policy=Policy.AGREE,
        note="Two identical copies (02c331b7-…, 2d7b0796-…).",
    ),
    Slot(
        "charge_mode_selection",
        "settings.charge_mode_selection",
        "Selected charge mode",
        Kind.ENUM,
        policy=Policy.AGREE,
        note="Two identical copies (53975124-…, 9905c311-…).",
    ),
    # Access
    Slot(
        "locked",
        "locked",
        "Vehicle locked",
        Kind.BOOL,
        key="bd917b58-82bd-3c34-a006-747ca5aec03d",
    ),
    Slot(
        "open",
        "open",
        "Any door/window/trunk open",
        Kind.BOOL,
        key="c0bb1348-5d0d-3140-9a51-06881db06490",
    ),
    # Temperatures
    Slot(
        "outdoor_temperature",
        "outdoor_temperature",
        "Outdoor temperature",
        Kind.FLOAT,
        "°C",
        key="b6ea5ae8-53ff-386d-8415-1baa0602bbb6",
    ),
    Slot(
        "battery_temperature_min",
        "min_temperature",
        "Battery temperature (minimum)",
        Kind.FLOAT,
        "°C",
        key="374014c4-2fd5-3d73-ac75-7c949e726f00",
    ),
    Slot(
        "battery_temperature_max",
        "max_temperature",
        "Battery temperature (maximum)",
        Kind.FLOAT,
        "°C",
        key="dc4a4716-2205-352f-802f-8d7d59705c5b",
    ),
    # Climatisation
    Slot(
        "climatisation_state",
        "climatisation_state",
        "Climatisation state",
        Kind.ENUM,
        policy=Policy.AGREE,
        note="Two slots with contradicting values (1472bf20-… VENTILATION, f95799d0-… "
        "OFF): presumably actual state vs. last climatisation job. Attribution not "
        "verified -> value only when both agree; both keys exposed as attributes.",
    ),
    Slot(
        "remaining_climate_time",
        "remaining_climate_time",
        "Remaining climatisation time",
        Kind.DURATION,
        "s",
        policy=Policy.AGREE,
        note="Two slots (0f3fab0c-… 1800s, 3c19831c-… 0s), same situation as climatisation_state.",
    ),
    Slot(
        "window_heating_state",
        "window_heating_state",
        "Window heating state",
        Kind.ENUM,
        key="a894455d-2917-33cf-a9bd-d05846a14cfe",
    ),
    Slot(
        "climatisation_target_temperature",
        "climatisation_settings.target_temperature",
        "Climatisation target temperature (raw, unit not verified)",
        Kind.INT,
        policy=Policy.AGREE,
        note="Two identical copies, value 120. Unit unknown (possibly 0.1 °C or an "
        "encoded value); exposed raw without a unit.",
    ),
    # Lights
    Slot(
        "parking_light_left",
        "parking_light_left",
        "Parking light left",
        Kind.BOOL,
        key="c7828009-144b-36e9-af38-2c35e7356c34",
    ),
    Slot(
        "parking_light_right",
        "parking_light_right",
        "Parking light right",
        Kind.BOOL,
        key="0fa69b72-8432-3ef4-a312-cbb2f7861dfc",
    ),
    # Time
    Slot(
        "vehicle_time",
        "instrument_cluster_time",
        "Instrument cluster time (local vehicle time with offset)",
        Kind.TIMESTAMP,
        key="d8d3e58b-b527-39b6-8d71-c3da9c7e2816",
        note="Changes between the fixture generations (17:50:59+01:00 -> 18:45:15+01:00).",
    ),
    Slot(
        "profile_vehicle_time",
        "profile_state_report.instrument_cluster_time",
        "Instrument cluster time of the profile state report",
        Kind.TIMESTAMP,
        key="f295ae23-0485-3ccb-830b-58c644a04f2e",
    ),
    # Charging timer (profile state report)
    Slot(
        "timer_estimated_start",
        "profile_state_report.next_charging_timer_information.estimated_start_time",
        "Next charging timer: estimated start",
        Kind.TIMESTAMP,
        key="9fe68597-df48-30c2-9c84-46c49e955957",
    ),
    Slot(
        "timer_estimated_finish",
        "profile_state_report.next_charging_timer_information.estimated_finish_time",
        "Next charging timer: estimated finish",
        Kind.TIMESTAMP,
        key="e3258c86-d04c-3c17-a00c-ce500ddead21",
    ),
    Slot(
        "timer_target_reachability",
        "profile_state_report.next_charging_timer_information.target_reachability",
        "Next charging timer: target reachability",
        Kind.ENUM,
        key="1b022ff0-eb13-3595-b7a2-e90ce8e500de",
    ),
)

SLOTS_BY_NAME: dict[str, Slot] = {slot.name: slot for slot in SLOTS}

# Fields that appear with several keys in the Tavascan fixture, with the resolution
# applied (documented in docs/slot-mapping.md as well).
MULTI_KEY_FIELDS: dict[str, str] = {
    "settings.target_soc": "keyed: e21d4d25-… user target, b3b04f31-… effective target",
    "mileage.value": "max: monotone counter",
    "climatisation_state": "agree: contradicting, no value until verified",
    "remaining_climate_time": "agree: contradicting, no value until verified",
    "settings.max_charge_current_ac": "agree: identical copies",
    "settings.auto_unlock_ac": "agree: identical copies",
    "settings.charge_mode_selection": "agree: identical copies",
    "climatisation_settings.target_temperature": "agree: identical copies",
    "climatisation_settings.climatisation_without_hv_power": "unmapped (identical copies)",
    "climatisation_settings.climatisation_element_settings.*": "unmapped (identical copies)",
    "additional_consumptions.*": "unmapped (4 identical copies each)",
    "car_captured_time / car_captured_utc_timestamp": "report time: max() = last vehicle report",
    "timestamp / message_id / report_type / transaction_id / trigger / state": "report metadata",
}


@dataclass
class SlotOverrides:
    """Per-VIN learned/overridden slot keys (persisted by the integration)."""

    keys: dict[str, str] = field(default_factory=dict)  # slot name -> key


def all_known_keys() -> frozenset[str]:
    """Return every key hard-coded in the slot table."""
    return frozenset(slot.key for slot in SLOTS if slot.key)


SLOT_BY_KEY: dict[str, str] = {slot.key: slot.name for slot in SLOTS if slot.key}


def owner_of_key(key: str) -> str | None:
    """Name of the slot whose table key this is (None if unknown)."""
    return SLOT_BY_KEY.get(key)


def foreign_key_overrides(overrides: dict[str, str]) -> dict[str, str]:
    """Overrides whose key is hard-coded for a *different* slot (must not be learned)."""
    return {
        name: key
        for name, key in overrides.items()
        if (owner := owner_of_key(key)) is not None and owner != name
    }
