# Slot mapping (Tavascan fixtures, 2026-10-27)

Data points are identified by their `key` (UUID v3, stable across all 14 downloads).
Field names that occur with **more than one key** in the same dataset and how the
parser (`custom_components/vag_data_act/parser.py`, table in `slots.py`) resolves them:

| Field name | Keys (short) | Values | Resolution | Reason |
|---|---|---|---|---|
| `settings.target_soc` | `e21d4d25-…`, `b3b04f31-…` | 100 / 80 | keyed: `e21d…` = `target_soc_user`, `b3b0…` = `target_soc_effective` | `battery_care_mode.charge_bcam_threshold` = 80 is active, so the effective target is min(user, threshold) = 80 = `b3b0…`. The parser re-checks this relation on every dataset and flags `target_soc_effective` as ambiguous if it breaks. |
| `mileage.value` | `75d65f00-…`, `30cc36fd-…` | 10031 / 10044 | max → `odometer` | Monotone counter; 10031 is the departure value, 10044 the arrival value of the verified trip 17:50–18:44 local. Both copies are identical in all three fixture contents. |
| `climatisation_state` | `1472bf20-…`, `f95799d0-…` | VENTILATION / OFF | agree → no value, both keys as attributes | Presumably actual state vs. last climatisation job; attribution not verified. Reported as ambiguity until verified live. |
| `remaining_climate_time` | `0f3fab0c-…`, `3c19831c-…` | 1800s / 0s | agree → no value, both keys as attributes | Same pair as `climatisation_state`. |
| `settings.max_charge_current_ac` | `0387de65-…`, `63e08d24-…` | identical | agree → value, warning on deviation | Pure duplicates (settings report + settings job report). |
| `settings.auto_unlock_ac` | `02c331b7-…`, `2d7b0796-…` | identical | agree | Pure duplicates. |
| `settings.charge_mode_selection` | `53975124-…`, `9905c311-…` | identical | agree | Pure duplicates. |
| `climatisation_settings.target_temperature` | `559fd5ec-…`, `6d4e5b62-…` | 120 / 120 | agree, raw (unit unknown) | Pure duplicates. |
| `climatisation_settings.climatisation_without_hv_power` | 2 keys | identical | unmapped | Diagnostics only. |
| `climatisation_settings.climatisation_element_settings.*` | 2 keys each | identical | unmapped | Diagnostics only. |
| `additional_consumptions.*` | 4 keys each | identical | unmapped | Diagnostics only. |
| `car_captured_time` (13), `car_captured_utc_timestamp` (14), `profile_state_report.car_captured_time` (1) | many | times | `last_vehicle_report` = max over all | Points are not attributable to a report; a week-old report (2026-10-20) is part of every dataset, so only the maximum is meaningful. |
| `timestamp` (17), `message_id` (9), `report_type` (14), `transaction_id` (3), `trigger` (2), `state` (3), `mileage.state` (2) | many | – | report metadata | Exposed in diagnostics, never counted as unmapped. |

## Single-key slots worth a note

| Slot | Field | Key | Note |
|---|---|---|---|
| `soc` | `battery_state_report.soc` | `506cb83e-…` | The only SoC source. Checked against `battery_level_HV.value` (23.0) and `energy_contents` 167.5/773.5 = 21.66 % (0.1 kWh units). Deviation > 3 % → no value, ambiguity `soc`. |
| `range` | `value` | `0ca40e18-…` | Bare field name without context. Mapped by key only; evcc (`vehicle/vw/eudataact/types.go`, `KeyRangeID3`) documents the same key as the MEB range. Confirmed live (2026-10-27): the Tavascan display showed 90 km at 23 %. |
| `charging_error_text` | `error_description` | `0a7ecca3-…` | From `RbcErrorReport_0`; `error_number` 28 equals `charging_state_report.error_code` 28. The bare `error_code` = `#0` is a different field and stays unmapped. |
| `vehicle_time` | `instrument_cluster_time` | `d8d3e58b-…` | Local vehicle time with offset. The only value that differs between the fixture generations (17:50:59+01:00 → 18:45:15+01:00). |

## Fallback for unknown keys (other vehicles)

If a slot's key is not present in a dataset (e.g. the Born), the parser uses the field
name **only if it occurs exactly once**; the found key is then learned per VIN and
persisted by the integration. Field names with several different values are reported
as ambiguous, never guessed. No substring matching anywhere.

Exception: if the single copy carries a key that the table assigns to *another* slot of
the same field, nothing is learned. The value is reused with `status: shared`. Live
example (Born, 2026-10-27): only one `settings.target_soc` = 90 with the effective-target
key `b3b04f31-…`; `target_soc_user` shows 90 / `shared`, `target_soc_effective` 90 / `ok`.

## Cupra Born dataset (live, 2026-10-27)

72 points, reports `RPT_0`, `RPT_1`, `RbcErrorReport_7`, `RpcSettingsReport_2`,
`RpcStateReport_0`, `RpcWindowHeatingStateReport_1`. Present with the *same keys* as the
Tavascan: `mileage.value` (both keys), `locked`, `open`, `parking_light_*`,
`min/max_temperature`, `window_heating_state`, `instrument_cluster_time`,
`profile_state_report.instrument_cluster_time`, `charging_state_report.error_code`,
`error_description`, `error_number`, `settings.max_charge_current_ac` (one copy),
`settings.auto_unlock_ac` (one copy), `settings.charge_mode_selection` (one copy),
`climatisation_settings.target_temperature` (one copy, 115),
`climatisation_state` (only `f95799d0-…` = OFF) and `remaining_climate_time` (only
`3c19831c-…` = 0s). Missing: every `battery_state_report.*`, `battery_level_HV.*`,
`energy_contents.*`, `charging_state_report.*` except `error_code`, `value` (range),
`outdoor_temperature`, `battery_care_mode.*`, the timer information and the second
`settings.target_soc` key. The Born's `climatisation_state`/`remaining_climate_time` keys
are the `f95799d0-…`/`3c19831c-…` pair, which supports the reading that this pair is the
*actual state* (`RpcStateReport`) and `1472bf20-…`/`0f3fab0c-…` belong to
`RpcStateReportForStartClimaJob` (last climatisation job) – still to be confirmed live.
