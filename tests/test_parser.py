"""Parser tests against the 14 real portal fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.vag_data_act.parser import parse_dataset, parse_timestamp
from custom_components.vag_data_act.slots import SLOTS, all_known_keys

RAW = Path(__file__).parent / "fixtures" / "raw"
FIXTURES = sorted(RAW.glob("*/*.json"))
F180109 = RAW / "20261027180109_VSSZZZKRXSA000001" / "VSSZZZKRXSA000001_20261027180109.json"
F194730 = RAW / "20261027194730_VSSZZZKRXSA000001" / "VSSZZZKRXSA000001_20261027194730.json"
F200113 = RAW / "20261027200113_VSSZZZKRXSA000001" / "VSSZZZKRXSA000001_20261027200113.json"

EXPECTED_UNMAPPED_FIELDS = {
    "additional_consumptions.interior_climatization_consumption": 4,
    "additional_consumptions.residual_consumption": 4,
    "charge_mode_selection_options.home_storage_charging": 1,
    "charge_mode_selection_options.immediate_charging": 1,
    "charge_mode_selection_options.immediate_discharging": 1,
    "charge_mode_selection_options.only_own_current": 1,
    "charge_mode_selection_options.preferred_charging_times": 1,
    "charge_mode_selection_options.timer_charging": 1,
    "charge_mode_selection_options.timer_charging_climatization": 1,
    "climatisation_settings.climatisation_element_settings.is_climatisation_at_unlock": 2,
    "climatisation_settings.climatisation_element_settings.is_mirror_heating_enabled": 2,
    "climatisation_settings.climatisation_element_settings.zone_front_left_enabled": 2,
    "climatisation_settings.climatisation_element_settings.zone_front_right_enabled": 2,
    "climatisation_settings.climatisation_element_settings.zone_rear_left_enabled": 2,
    "climatisation_settings.climatisation_element_settings.zone_rear_right_enabled": 2,
    "climatisation_settings.climatisation_without_hv_power": 2,
    "energy_contents.current_energy_content.value_type": 1,
    "energy_contents.maximal_energy_content.value_type": 1,
    "error_code": 1,
    "setup_real_speed_ratios.speed_ratio_x1_y1.value_type": 1,
    "setup_real_speed_ratios.speed_ratio_x2_y2.physical_value_x": 1,
    "setup_real_speed_ratios.speed_ratio_x2_y2.physical_value_y": 1,
    "setup_real_speed_ratios.speed_ratio_x2_y2.value_type": 1,
    "setup_real_speed_ratios.speed_ratio_x3_y3.physical_value_x": 1,
    "setup_real_speed_ratios.speed_ratio_x3_y3.physical_value_y": 1,
    "setup_real_speed_ratios.speed_ratio_x3_y3.value_type": 1,
    "setup_real_speed_ratios.speed_ratio_x4_y4.physical_value_x": 1,
    "setup_real_speed_ratios.speed_ratio_x4_y4.physical_value_y": 1,
    "setup_real_speed_ratios.speed_ratio_x4_y4.value_type": 1,
}


def _raw(path: Path) -> dict:
    return json.loads(path.read_bytes())


def test_fixture_inventory():
    """14 ZIPs, 3 distinct contents, 171 points each, VIN anonymized."""
    assert len(FIXTURES) == 14
    hashes = {}
    for f in FIXTURES:
        hashes.setdefault(hashlib.md5(f.read_bytes()).hexdigest(), []).append(f.name)
    assert len(hashes) == 3
    assert sorted(len(v) for v in hashes.values()) == [1, 5, 8]
    for f in FIXTURES:
        d = _raw(f)
        assert set(d) == {"vin", "user_id", "Data"}
        assert d["vin"] == "VSSZZZKRXSA000001"
        assert len(d["Data"]) == 171
        assert all(isinstance(p["value"], str) for p in d["Data"])


def test_keys_stable_and_order_random():
    key_sets = set()
    key_to_field: dict[str, set[str]] = {}
    for f in FIXTURES:
        pts = _raw(f)["Data"]
        key_sets.add(frozenset(p["key"] for p in pts))
        for p in pts:
            key_to_field.setdefault(p["key"], set()).add(p["dataFieldName"])
    assert len(key_sets) == 1, "all downloads carry the same key set"
    assert all(len(v) == 1 for v in key_to_field.values()), "key -> field is stable"
    a, b, c = (_raw(f)["Data"] for f in (F180109, F194730, F200113))
    assert sum(x["key"] == y["key"] for x, y in zip(a, b, strict=True)) == 5
    assert sum(x["key"] == y["key"] for x, y in zip(b, c, strict=True)) == 5
    # keys verified only on the live Born (not part of the Tavascan fixtures)
    live_only = {
        "b9e3fd5e-4346-3e94-8c67-d4a0f5d61d5a",
        "2725401e-75cf-3c11-96a1-e926c9871fd3",
    }
    assert all_known_keys() - live_only <= key_sets.pop()


def test_duplicate_slots_and_soc_sources():
    pts = _raw(F180109)["Data"]
    by_field: dict[str, dict[str, str]] = {}
    for p in pts:
        by_field.setdefault(p["dataFieldName"], {})[p["key"]] = p["value"]
    assert by_field["settings.target_soc"] == {
        "e21d4d25-98bc-3016-a234-1ad061cc313b": "100",
        "b3b04f31-b10e-38aa-b8ad-c0da7c06caea": "80",
    }
    assert by_field["mileage.value"] == {
        "75d65f00-5fa8-334a-826d-e73e91fe5c8d": "10031",
        "30cc36fd-71ca-3c09-9296-e94ebd47bd2b": "10044",
    }
    assert set(by_field["climatisation_state"].values()) == {
        "CLIMATISATION_STATE_OFF",
        "CLIMATISATION_STATE_VENTILATION",
    }
    assert set(by_field["remaining_climate_time"].values()) == {"0s", "1800s"}
    assert by_field["battery_state_report.soc"] == {"506cb83e-f99f-3af3-bbeb-0429b69a78d9": "23"}
    assert by_field["battery_level_HV.value"] == {"ac1108b1-b8cc-3db9-a663-03d387e42223": "23.0"}
    assert list(by_field["energy_contents.current_energy_content.physical_value"].values()) == [
        "167.5"
    ]
    assert list(by_field["energy_contents.maximal_energy_content.physical_value"].values()) == [
        "773.5"
    ]
    assert by_field["value"] == {"0ca40e18-0564-3eda-bcc0-7aee9ef44f04": "90"}
    # max(car_captured_time) must skip the week-old report
    times = [parse_timestamp(v) for v in by_field["car_captured_time"].values()]
    assert min(times) == datetime(2026, 10, 20, 5, 8, 42, tzinfo=UTC)
    assert max(times) == datetime(2026, 10, 27, 17, 46, 51, tzinfo=UTC)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.parent.name)
def test_every_fixture_normalizes(path: Path):
    parsed = parse_dataset(path.read_bytes())
    assert parsed.vin == "VSSZZZKRXSA000001"
    assert parsed.point_count == 171
    assert parsed.get("soc") == 23
    assert parsed.get("battery_level_hv") == 23.0
    assert parsed.get("energy_content_current") == 16.75
    assert parsed.get("energy_content_max") == 77.35
    assert parsed.get("range") == 90
    assert parsed.get("odometer") == 10044
    assert parsed.values["odometer"].key == "30cc36fd-71ca-3c09-9296-e94ebd47bd2b"
    assert parsed.get("target_soc_user") == 100
    assert parsed.get("target_soc_effective") == 80
    assert parsed.get("bcam_threshold") == 80
    assert parsed.get("charging_state") == "CHARGE_STATE_CHARGING_ERROR"
    assert parsed.get("charging_error_code") == 28
    assert parsed.get("charging_error_text") == "App_RBC_FailedChargeInfrastructure"
    assert parsed.get("remaining_charging_time") == 6600
    assert parsed.get("charge_rate") == 53.0
    assert parsed.get("locked") is True
    assert parsed.get("open") is True
    assert parsed.get("outdoor_temperature") == 8.5
    assert parsed.get("climatisation_state") is None
    assert parsed.get("remaining_climate_time") is None
    assert parsed.get("max_charge_current_ac") == "MAX_CHARGE_CURRENT_AC_MAXIMUM"
    assert sorted(a.name for a in parsed.ambiguities) == [
        "climatisation_state",
        "remaining_climate_time",
    ]
    assert parsed.values["climatisation_state"].candidates == {
        "1472bf20-0861-32a1-977b-ac3a49002854": "CLIMATISATION_STATE_VENTILATION",
        "f95799d0-bb95-3a0b-bce3-f3593e94afb6": "CLIMATISATION_STATE_OFF",
    }
    assert parsed.last_vehicle_report == datetime(2026, 10, 27, 17, 46, 51, tzinfo=UTC)
    counts: dict[str, int] = {}
    for p in parsed.unmapped:
        counts[p.field] = counts.get(p.field, 0) + 1
    assert counts == EXPECTED_UNMAPPED_FIELDS
    assert sorted(parsed.metadata) == sorted(
        [
            "battery_level_HV.state",
            "car_captured_time",
            "car_captured_utc_timestamp",
            "message_id",
            "mileage.state",
            "profile_state_report.car_captured_time",
            "report_type",
            "state",
            "timestamp",
            "transaction_id",
            "trigger",
            "update_reason",
        ]
    )
    assert parsed.learned_keys == {}


def test_three_contents_differ_only_in_vehicle_time():
    a, b, c = (parse_dataset(f.read_bytes()).normalized() for f in (F180109, F194730, F200113))
    assert b == c, "…200113 is …194730 re-sorted"
    diff = {
        k: (a["values"][k], b["values"][k]) for k in a["values"] if a["values"][k] != b["values"][k]
    }
    assert diff == {
        "vehicle_time": (
            parse_timestamp("2026-10-27T17:50:59.000+01:00"),
            parse_timestamp("2026-10-27T18:45:15.000+01:00"),
        )
    }
    assert a["last_vehicle_report"] == b["last_vehicle_report"]
    assert a["ambiguous"] == b["ambiguous"] and a["unmapped"] == b["unmapped"]


def test_same_content_identical_normalized_result():
    groups: dict[str, set] = {}
    for f in FIXTURES:
        n = parse_dataset(f.read_bytes()).normalized()
        groups.setdefault(f.name, set()).add(json.dumps(n, default=str, sort_keys=True))
    assert all(len(v) == 1 for v in groups.values())


def test_soc_plausibility_and_target_cross_check():
    d = _raw(F180109)
    for p in d["Data"]:
        if p["key"] == "506cb83e-f99f-3af3-bbeb-0429b69a78d9":
            p["value"] = "40"
        if p["key"] == "b3b04f31-b10e-38aa-b8ad-c0da7c06caea":
            p["value"] = "90"
    parsed = parse_dataset(d)
    assert parsed.get("soc") is None
    assert parsed.values["soc"].status == "implausible"
    names = sorted(a.name for a in parsed.ambiguities)
    assert names == ["climatisation_state", "remaining_climate_time", "soc", "target_soc_effective"]


def test_unknown_key_falls_back_to_unique_field_and_learns():
    d = _raw(F180109)
    for p in d["Data"]:
        if p["key"] == "506cb83e-f99f-3af3-bbeb-0429b69a78d9":
            p["key"] = "00000000-0000-3000-8000-000000000000"
    parsed = parse_dataset(d)
    assert parsed.get("soc") == 23
    assert parsed.learned_keys == {"soc": "00000000-0000-3000-8000-000000000000"}
    # the override path resolves it directly
    parsed2 = parse_dataset(d, key_overrides={"soc": "00000000-0000-3000-8000-000000000000"})
    assert parsed2.learned_keys == {} and parsed2.get("soc") == 23


def test_slot_table_consistency():
    names = [s.name for s in SLOTS]
    assert len(names) == len(set(names))
    keys = [s.key for s in SLOTS if s.key]
    assert len(keys) == len(set(keys))


def test_single_copy_with_foreign_key_is_shared_not_learned():
    """Born: only one ``settings.target_soc`` and it carries the effective-target key."""
    d = _raw(F180109)
    d["Data"] = [p for p in d["Data"] if p["key"] != "e21d4d25-98bc-3016-a234-1ad061cc313b"]
    parsed = parse_dataset(d)
    user, eff = parsed.values["target_soc_user"], parsed.values["target_soc_effective"]
    assert eff.value == 80 and eff.status == "ok"
    assert user.value == 80 and user.status == "shared"
    assert user.key == "b3b04f31-b10e-38aa-b8ad-c0da7c06caea"
    assert parsed.learned_keys == {}, (
        "the effective-target key must not be learned for the user slot"
    )
    # an override learned by 0.1.0 is ignored as well
    parsed2 = parse_dataset(
        d, key_overrides={"target_soc_user": "b3b04f31-b10e-38aa-b8ad-c0da7c06caea"}
    )
    assert parsed2.values["target_soc_user"].status == "shared"
    assert parsed2.learned_keys == {}


def test_foreign_key_overrides_helper():
    from custom_components.vag_data_act.slots import foreign_key_overrides

    overrides = {
        "target_soc_user": "b3b04f31-b10e-38aa-b8ad-c0da7c06caea",  # effective-target key
        "soc": "00000000-0000-3000-8000-000000000000",  # unknown key: fine
        "range": "0ca40e18-0564-3eda-bcc0-7aee9ef44f04",  # its own key: fine
    }
    assert foreign_key_overrides(overrides) == {
        "target_soc_user": "b3b04f31-b10e-38aa-b8ad-c0da7c06caea"
    }


def test_summarize_points_fixture():
    from custom_components.vag_data_act.parser import load_points, summarize_points

    _, points = load_points(F180109.read_bytes())
    s = summarize_points(points)
    assert s["points"] == 171 and s["has_soc"] and s["has_charging_state"]
    assert "RpcStateReport_4" in s["message_ids"]
    assert s["field_groups"]["battery_state_report"] == 6
    assert s["field_groups"]["<bare>"] > 10


def test_merge_points_keeps_values_missing_from_newer_package():
    from datetime import timedelta

    from custom_components.vag_data_act.parser import (
        load_points,
        merge_points,
        package_capture_time,
        parse_points,
        points_from_json,
        points_to_json,
        stamp_points,
    )

    _, full = load_points(F180109.read_bytes())
    t_full = package_capture_time(full)
    assert t_full == datetime(2026, 10, 27, 17, 46, 51, tzinfo=UTC)
    # a later, partial package: no battery/charging/energy reports, odometer advanced
    later = [
        p
        for p in full
        if not p.field.startswith(
            ("battery_state_report.", "charging_state_report.", "energy_contents.")
        )
        and p.field not in ("value", "battery_level_HV.value")
    ]
    later = [p if p.field != "mileage.value" else type(p)(p.key, p.field, "10100") for p in later]
    t_later = t_full + timedelta(hours=2)

    store: dict = {}
    assert merge_points(store, stamp_points(full, "a.json", t_full)) == 171
    changed = merge_points(store, stamp_points(later, "b.json", t_later))
    assert changed == 2  # both mileage keys
    assert len(store) == 171, "points absent from the newer package are kept"

    parsed = parse_points("VIN", list(store.values()))
    soc, odo = parsed.values["soc"], parsed.values["odometer"]
    assert soc.value == 23 and soc.source == "a.json" and soc.captured_at == t_full
    assert odo.value == 10100 and odo.source == "b.json" and odo.captured_at == t_later
    assert parsed.last_vehicle_report == t_full, "report times come from the stored points"

    # JSON round trip of the store
    restored = points_from_json(points_to_json(store))
    assert restored == store

    # the single-dataset path stamps every value with the package time
    single = parse_dataset(F180109.read_bytes(), source="x.json")
    assert single.values["soc"].captured_at == t_full
    assert single.values["soc"].source == "x.json"


def test_climatisation_target_temperature_is_degrees():
    parsed = parse_dataset(F180109.read_bytes())
    sv = parsed.values["climatisation_target_temperature"]
    assert sv.raw == "120" and sv.value == 22.0 and sv.unit == "°C"


def test_soc_not_flagged_by_reference_from_other_package():
    """Live Born case: SoC 51 % from one package, HV level 90 % from a later one."""
    from datetime import timedelta

    from custom_components.vag_data_act.parser import (
        load_points,
        merge_points,
        package_capture_time,
        parse_points,
        stamp_points,
    )

    _, full = load_points(F180109.read_bytes())
    t0 = package_capture_time(full)
    store: dict = {}
    merge_points(store, stamp_points(full, "a.json", t0))
    hv_key = "ac1108b1-b8cc-3db9-a663-03d387e42223"
    later = [type(p)(p.key, p.field, "90.0") for p in full if p.key == hv_key]
    merge_points(store, stamp_points(later, "b.json", t0 + timedelta(hours=3)))
    parsed = parse_points("VIN", list(store.values()))
    assert parsed.get("soc") == 23
    assert parsed.values["soc"].status == "ok"
    assert "soc" not in [a.name for a in parsed.ambiguities]
