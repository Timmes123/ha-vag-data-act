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
2. lists the datasets, downloads the newest one, unpacks the inner JSON and hashes it,
3. re-parses and updates entities **only when the content changed**; otherwise the old
   values stay and `data_age_minutes` grows,
4. resolves every value by its stable portal `key` (never by position or substring),
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
`source_field`, `raw_value`, `status`, `car_captured_at` and `age_minutes`; ambiguous
slots additionally list all `candidates` (key → raw value).

| Entity | Source field | Unit / class | Notes |
|---|---|---|---|
| State of charge | `battery_state_report.soc` | %, battery | Only SoC source; checked against `battery_level_HV.value` and energy content quotient (3 % tolerance), otherwise empty + ambiguity `soc` |
| Range | `value` (key `0ca40e18-…`) | km, distance | Bare field, mapped by key only (see known gaps) |
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
| `dataset` | inner file name; attributes: ZIP name, SHA-256, datasets listed, last error, `data_request` (the portal's data request metadata: interval, requested data clusters) |
| `ambiguous_fields` | count; attributes list every contradicting slot with its candidates |
| `unmapped_points` | count; attributes list every unknown key with field and value |

Values are never hidden behind *unavailable*: stale values stay visible, the age tells.
Service `vag_data_act.refresh_now` polls immediately (optionally one config entry).
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
* `range`: comes from a bare `value` point (key `0ca40e18-…`). evcc documents the same key as
  the MEB range and the fixture value (90 km at 23 %) is plausible, but it is not confirmed
  against the vehicle display yet.
* `climatisation_settings.target_temperature` = 120: unit unknown, exposed raw.
* Keys were verified on a Cupra Tavascan. For other vehicles unknown keys fall back to
  unique field names and are learned per VIN (`.storage/vag_data_act.<VIN>`). A key that
  the table already assigns to *another* slot is never learned: if a vehicle delivers only
  one `settings.target_soc` and it carries the effective-target key, the user target shows
  the same value with `status: shared`.
* **Cupra Born (2026-10-27):** the live dataset holds 72 points instead of 171. It lacks
  the battery/charging reports entirely (`battery_state_report.*`,
  `charging_state_report.current_charge_state`, `energy_contents.*`, `value`/range,
  `outdoor_temperature`, `battery_care_mode.*`), so SoC, range, charging state and energy
  are `unknown`, while odometer, lock state, lights, temperatures, climatisation and the
  charge settings are delivered. Whether the portal data request for that vehicle is
  really *All Data* (compare the `data_request` attribute of the `dataset` sensor between
  the vehicles) or the vehicle simply does not report these clusters is being verified.
* Entity names: `state_of_charge` is the SoC in percent, `charging_state` the enum
  (`CHARGE_STATE_…`).

## Development

```
pip install -r requirements_test.txt
pytest -q && ruff check .
```

Fixtures: `tests/fixtures/raw/` holds 14 real downloads (VIN anonymized). Parser tests
verify every statement in `SPEC.md` against them.
