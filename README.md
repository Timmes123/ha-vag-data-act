# VAG EU Data Act – Home Assistant integration

Custom integration `vag_data_act` that pulls vehicle data (Cupra Born / Tavascan and other
VW group EVs) from the EU Data Act portal `https://eu-data-act.drivesomethinggreater.com`
and exposes it as Home Assistant entities **with a visible health status**. Every value is
verifiable: each entity carries the portal `source_key`, the capture time and its age.

[![Validate](https://github.com/Timmes123/ha-vag-data-act/actions/workflows/validate.yml/badge.svg)](https://github.com/Timmes123/ha-vag-data-act/actions/workflows/validate.yml)

## How it works

The portal is not a live API. Once you set up a *continuous data request* in the portal,
it stores a ZIP (one flat JSON with ~170 data points) roughly every 15 minutes. The car
itself only sends data on events (unlock/departure, lock/arrival, charging, climatisation,
settings jobs), so a new ZIP does **not** mean new data. The integration

1. logs in through the VW identity provider (Auth0 Universal Login) and keeps the session
   cookies in `.storage` – it does not log in on every poll,
2. lists the packages and downloads **every package it has not processed yet**, oldest
   first, throttled (the portal rate-limits after ~25 downloads; the rest follows on the
   next poll),
3. merges the points of each package **by key** into a persistent store: packages are
   partial (a live scan showed 6 … 93 points per package, the battery/charging reports in
   only a third of them), so a newer package overwrites what it contains and everything
   else keeps its old value – with its own capture time,
4. re-parses the merged store and updates entities only when a point changed; otherwise
   the old values stay and `data_age_minutes` grows,
5. resolves every value by its stable portal `key` (never by position or substring),
   see [docs/slot-mapping.md](docs/slot-mapping.md).

## Portal preparation (once, in the browser)

1. Open the portal, log in with your brand account (Cupra ID etc.), accept terms/consent.
2. Link the vehicle to the account.
3. Create a continuous data request: *All Data*, interval 15 minutes.
4. Wait for the first dataset (the portal answers "no files" until the car has reported).

## Installation (HACS custom repository)

1. HACS → Integrations → ⋮ → *Custom repositories* → add
   `https://github.com/Timmes123/ha-vag-data-act`, category *Integration*.
2. Install *VAG EU Data Act*, restart Home Assistant.
3. Settings → Devices & services → *Add integration* → *VAG EU Data Act*.
4. Enter e-mail, password, brand (default CUPRA), country/language (default `de`/`de`),
   then pick the vehicle. One config entry per vehicle; the same account may be used for
   several vehicles (they share one portal session).
5. Options: poll interval (default 15 min, minimum 5).

## Only one client!

Parallel portal sessions with the same account make the portal data unreliable. Run
exactly one client per account: this integration should be the only program that logs
in to the portal with these credentials.

## Entities

Vehicle values (device per VIN). Every value carries the attributes `source_key`,
`source_field`, `source_dataset` (inner file of the package it came from), `raw_value`,
`status`, `car_captured_at` (newest report time of that package) and `age_minutes`;
ambiguous slots additionally list all `candidates` (key → raw value).

| Entity | Source field | Unit / class | Notes |
|---|---|---|---|
| State of charge | `battery_state_report.soc` | %, battery | Only SoC source; checked against `battery_level_HV.value` and energy content quotient (3 % tolerance), otherwise empty + ambiguity `soc` |
| Range | `value` (key `0ca40e18-…`) | km, distance | Bare field, mapped by key only; confirmed against the vehicle display |
| Odometer | `mileage.value` | km, distance, total_increasing | Max of all copies |
| Charge target (effective) | `settings.target_soc` key `b3b04f31-…` | % | min(user, battery care threshold) |
| Charge target (user) | `settings.target_soc` key `e21d4d25-…` | % | |
| Battery care threshold | `battery_care_mode.charge_bcam_threshold` | % | |
| Battery care mode active | derived | binary | effective < user **and** effective == threshold |
| Charging state | `charging_state_report.current_charge_state` | enum string | e.g. `CHARGE_STATE_CHARGING_ERROR` |
| Charging error code / text | `charging_state_report.error_code`, `error_description` | | |
| Charging power | `battery_state_report.charge_power` | kW, power | |
| Charging rate | `battery_state_report.charge_rate` | km/h, speed | |
| Remaining charging time | `battery_state_report.remaining_charging_time_complete` | s, duration | only while `CHARGE_STATE_CHARGING` / `…CONSERVATION_CHARGING` |
| Charged energy | `battery_state_report.charge_energy` | kWh | |
| Battery energy / (max) | `energy_contents.*.physical_value` | kWh | delivered in 0.1 kWh, scaled |
| Charge mode / type / max. AC current | `charging_state_report.charge_mode`, `.charge_type`, `settings.max_charge_current_ac` | enum string | |
| Locked | `locked` | binary, lock | |
| Open | `open` | binary, opening | |
| Outdoor temperature | `outdoor_temperature` | °C | |
| Battery temperature (min/max) | `min_temperature`, `max_temperature` | °C | |
| Climatisation state | `climatisation_state` | enum string | two contradicting keys → empty until verified, both in `candidates` |
| Remaining climatisation time | `remaining_climate_time` | s, duration | same as above |
| Window heating | `window_heating_state` | enum string | |
| Parking light left / right | `parking_light_left/right` | binary, light | |
| Vehicle time | `instrument_cluster_time` | timestamp | local vehicle time with offset |
| Last vehicle report | max of all `car_captured_*` | timestamp | |
| Data age | now − last vehicle report | min, duration | |

Diagnostic entities: HV battery level, charging scenario, charge mode selection, auto
unlock AC, climatisation target temperature (raw), profile report time, charging timer
start/finish, and the health sensors below.

## Health

| Entity | Meaning |
|---|---|
| `login_status` | `ok`, `auth_failed` (wrong credentials → reauth + repair issue), `consent_required` (portal needs a browser confirmation → repair issue), `portal_error` (429/5xx/network, retried with backoff up to 2 h, no re-login), `unknown` |
| `last_successful_download` | last time the dataset list/download succeeded |
| `last_vehicle_report` | newest `car_captured_time` in the dataset (**not** the ZIP time) |
| `data_age_minutes` | minutes since the last vehicle report – the staleness indicator |
| `dataset_changed` | whether the last poll delivered new content |
| `dataset` | newest processed package; attributes: ZIP name, SHA-256, packages listed / processed in the last poll / pending (rate limit), point store size, last error, `data_request` (the portal's data request metadata) |
| `ambiguous_fields` | count; attributes list every contradicting slot with its candidates |
| `unmapped_points` | count; attributes list every unknown key with field and value |

Values are never hidden behind *unavailable*: stale values stay visible, the age tells.
Service `vag_data_act.refresh_now` polls immediately (optionally one config entry).
Service `vag_data_act.scan_datasets` is a diagnostic: it downloads every listed dataset
and logs per file the inner name, hash, point count, report ids and whether the SoC /
charging reports are included; the result is part of the diagnostics download.
Diagnostics download redacts e-mail, password, VIN, identifier and cookies.
Logging: set the integration to DEBUG to see every login hop (code/state redacted) and every
download with inner file name and hash.

## Command line trace

`tools/login_trace.py` runs the login, lists the datasets and parses the newest one.
Credentials come from `VAG_EMAIL` / `VAG_PASSWORD` or an interactive prompt – never from
files. Use `-v` for the full redirect chain.

## Known gaps

* `climatisation_state` / `remaining_climate_time`: two keys with contradicting values
  (actual state vs. last climatisation job?). Not verified → entity empty, both keys in
  `candidates`. Once the attribution is confirmed on the live car the key will be fixed.
* `climatisation_settings.target_temperature` = 120: unit unknown, exposed raw.
* Keys were verified on a Cupra Tavascan. For other vehicles unknown keys fall back to
  unique field names and are learned per VIN (`.storage/vag_data_act.<VIN>`). A key that
  the table already assigns to *another* slot is never learned: if a vehicle delivers only
  one `settings.target_soc` and it carries the effective-target key, the user target shows
  the same value with `status: shared`.
* **Packages are partial.** A scan of 30 consecutive Born packages (2026-10-27) found
  6, 16, 67, 72, 74, 88 and 93 points per package with different report sets; the SoC and
  charging reports were present in 11 of 30. The Tavascan showed the same during a trip
  (143–162 points, three packages without SoC). Since v0.2.0 every unseen package is merged
  by key, so values survive packages that lack them. A value's `car_captured_at` is the
  newest report time of *its* package and can be older than `last_vehicle_report`.
* **Rate limit:** the portal answers HTTP 429 after roughly 25 downloads in a row.
  Downloads are spaced 1 s apart and stop at 429; `packages_pending` on the `dataset`
  sensor shows what is left for the next poll.
* **Package names are not final.** The portal can serve a placeholder (a copy of the newest
  content) for a package whose own content arrives later; the 14 fixtures were downloaded
  that way (8 ZIP names, one inner file). Packages are tracked by ZIP name, so such a
  late-filled package is not fetched again – only intermediate history can be lost, never
  the newest state.
* `climatisation_state` / `remaining_climate_time` keys: the Born delivers only the
  `f95799d0-…` / `3c19831c-…` pair (from `RpcStateReport`), which suggests that pair is the
  actual state and `1472bf20-…` / `0f3fab0c-…` belong to the last climatisation job
  (`RpcStateReportForStartClimaJob`). Still to be confirmed by starting a climatisation
  from the app and watching both keys.
* Entity names: `state_of_charge` is the SoC in percent, `charging_state` the enum
  (`CHARGE_STATE_…`).

## Development

```
pip install -r requirements_test.txt
pytest -q && ruff check .
```

Fixtures: `tests/fixtures/raw/` holds 14 real downloads (VIN anonymized). Parser tests
verify every statement in `SPEC.md` against them.
