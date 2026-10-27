# VAG EU Data Act

[![GitHub release](https://img.shields.io/github/v/release/Timmes123/ha-vag-data-act)](https://github.com/Timmes123/ha-vag-data-act/releases/latest)
[![Pre-release](https://img.shields.io/github/v/release/Timmes123/ha-vag-data-act?include_prereleases&label=pre-release&color=orange)](https://github.com/Timmes123/ha-vag-data-act/releases)
[![Validate](https://github.com/Timmes123/ha-vag-data-act/actions/workflows/validate.yml/badge.svg)](https://github.com/Timmes123/ha-vag-data-act/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Downloads](https://img.shields.io/github/downloads/Timmes123/ha-vag-data-act/total?label=downloads)](https://github.com/Timmes123/ha-vag-data-act/releases)
[![License](https://img.shields.io/github/license/Timmes123/ha-vag-data-act)](https://github.com/Timmes123/ha-vag-data-act/blob/main/LICENSE)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-donate-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/timmes123)
[![PayPal](https://img.shields.io/badge/PayPal-donate-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/paypalme/timmes123)

Vehicle data for Home Assistant from the **VW group EU Data Act portal** – state of
charge, range, odometer, charging state, lock state, temperatures and more for Cupra,
SEAT, Volkswagen, Škoda and Audi EVs – **with a visible health status**. Every value tells
you where it came from and how old it is.

## Why this integration?

The EU Data Act obliges the manufacturer to hand out your vehicle's data. The VW group
does that through a portal that delivers ZIP packages instead of a live API, and those
packages are tricky:

| Portal behaviour | What this integration does |
|---|---|
| A package is a flat list of ~170 untyped strings without any grouping; some field names occur several times with **different values**. | Every value is resolved by its stable portal `key`, never by position or by guessing. Contradicting copies are reported as *ambiguous* instead of picking one. |
| Packages are **partial**: consecutive packages of the same car carry different subsets of reports; the battery report can be missing for hours. | Every unseen package is downloaded and merged by key into a persistent store. A value survives packages that lack it and keeps its own capture time. |
| A new package does not mean new data: the car only reports on events (unlock, lock, charging, climatisation). | Entities update only when a point changed; otherwise the old value stays and `data_age_minutes` grows. Nothing hides behind *unavailable*. |
| The portal rate-limits and sometimes needs a browser confirmation. | Throttled downloads, backoff without re-login, clear `login_status` values and repair issues when you have to act. |

## Features

- **Vehicle values**: SoC, range, odometer, charge target (user and effective), battery care
  threshold, charging state / error / power / rate / remaining time / energy, battery energy,
  charge mode and type, AC current limit, locked, open, outdoor and battery temperature,
  climatisation and window heating, parking lights, vehicle time.
- **Provenance on every entity**: portal key, field, source package, capture time, age and
  the raw string – verifiable down to the ZIP.
- **Health entities**: login status, last download, last vehicle report, data age, dataset,
  ambiguous fields, unmapped points. Repair issues for wrong credentials or a required portal
  confirmation.
- **Several vehicles per account**, one config entry each; one portal session per account,
  kept across polls and restarts.
- **Fully UI configured**: config flow with vehicle selection, reauth, reconfigure, options
  (poll interval). Translations in English and German.
- **Services** `refresh_now` and the diagnostic `scan_datasets`; diagnostics download with
  redaction.

## Installation

### HACS (custom repository)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Timmes123&repository=ha-vag-data-act&category=integration)

1. Click the button above (or HACS → ⋮ → *Custom repositories* → add
   `https://github.com/Timmes123/ha-vag-data-act`, category *Integration*).
2. Download **VAG EU Data Act** and restart Home Assistant.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=vag_data_act)

   (or *Settings → Devices & services → Add integration → VAG EU Data Act*)

4. Enter e-mail, password, brand (default CUPRA) and country/language (default `de`/`de`),
   then pick the vehicle. Repeat for every vehicle.

### Manual

Copy `custom_components/vag_data_act/` into your `config/custom_components/` folder and
restart. HACS is strongly recommended so you get updates.

## Portal preparation (once, in the browser)

1. Open `https://eu-data-act.drivesomethinggreater.com`, log in with your brand account and
   accept terms/consent.
2. Link the vehicle to the account.
3. Create a *continuous data request*: **All Data**, interval **15 minutes**.
4. Wait for the first package (the portal answers "no files" until the car has reported).

### Only one client

Parallel portal sessions with the same account make the portal data unreliable. Run
exactly one client per account: this integration should be the only program that logs in
to the portal with these credentials.

## Options

*Settings → Devices & services → VAG EU Data Act → Configure*

| Option | Default | Meaning |
|---|---|---|
| Poll interval | 15 min | How often the package list is checked (minimum 5). The car itself reports on events, so shorter intervals rarely give newer data. |

## Entities

One device per VIN. Every value carries the attributes `source_key`, `source_field`,
`source_dataset` (inner file of the package it came from), `raw_value`, `status`,
`car_captured_at` (newest report time of that package) and `age_minutes`; ambiguous slots
additionally list all `candidates` (key → raw value).

| Entity | Source field | Unit / class | Notes |
|---|---|---|---|
| State of charge | `battery_state_report.soc` | %, battery | Only SoC source; checked against `battery_level_HV.value` and the energy content quotient (3 % tolerance), otherwise empty + ambiguity `soc` |
| Range | `value` (key `0ca40e18-…`) | km, distance | Bare field, mapped by key only; confirmed against the vehicle display |
| Odometer | `mileage.value` | km, distance, total_increasing | Max of all copies |
| Charge target (effective) | `settings.target_soc` key `b3b04f31-…` | % | min(user, battery care threshold) |
| Charge target (user) | `settings.target_soc` key `e21d4d25-…` | % | `status: shared` when the car delivers only the effective copy |
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
| Climatisation state | `climatisation_state` | enum string | two keys; empty while they contradict, both in `candidates` |
| Climatisation target temperature | `climatisation_settings.target_temperature` | °C | encoded as tenths of a degree above 10 °C (raw 120 = 22.0 °C) |
| Remaining climatisation time | `remaining_climate_time` | s, duration | same as above |
| Window heating | `window_heating_state` | enum string | |
| Parking light left / right | `parking_light_left/right` | binary, light | |
| Vehicle time | `instrument_cluster_time` | timestamp | local vehicle time with offset |
| Last vehicle report | max of all `car_captured_*` | timestamp | |
| Data age | now − last vehicle report | min, duration | |

Diagnostic entities: HV battery level, charging scenario, charge mode selection, auto unlock
AC, climatisation target temperature, profile report time, charging timer start/finish, and
the health sensors below.

## Health

| Entity | Meaning |
|---|---|
| `login_status` | `ok`, `auth_failed` (wrong credentials → reauth + repair issue), `consent_required` (portal needs a browser confirmation → repair issue), `portal_error` (429/5xx/network, retried with backoff up to 2 h, no re-login), `unknown` |
| `last_successful_download` | last time the package list/download succeeded |
| `last_vehicle_report` | newest `car_captured_time` over all stored points (**not** the ZIP time) |
| `data_age_minutes` | minutes since the last vehicle report – the staleness indicator |
| `dataset_changed` | whether the last poll changed any point |
| `dataset` | newest processed package; attributes: ZIP name, SHA-256, packages listed / processed in the last poll / pending (rate limit), point store size, last error, `data_request` (the portal's data request metadata) |
| `ambiguous_fields` | count; attributes list every contradicting slot with its candidates |
| `unmapped_points` | count; attributes list every unknown key with field and value |

Values are never hidden behind *unavailable*: stale values stay visible, the age tells.

## Services

*Developer tools → Actions*, or in an automation via the action picker:

| Service | Purpose |
|---|---|
| `vag_data_act.refresh_now` | Poll the portal immediately (optionally one config entry). |
| `vag_data_act.scan_datasets` | Diagnostic: download every listed package and log per file the inner name, hash, point count, report ids and whether the SoC / charging reports are included. The result is part of the diagnostics download. |

Diagnostics download (*device page → ⋮ → Download diagnostics*) redacts e-mail, password,
VIN, identifier and cookies. Enable debug logging on the integration page to see every
login hop (codes and states redacted) and every download with inner file name and hash.

## How it works

1. Login through the VW identity provider (Auth0 Universal Login); the session cookies are
   kept in `.storage`, so the integration does not log in on every poll.
2. Every poll lists the packages and downloads **every package it has not processed yet**,
   oldest first, 1 s apart. The portal rate-limits after roughly 25 downloads in a row; the
   integration stops at HTTP 429 and continues on the next poll (`packages_pending`).
3. The points of each package are **merged by key** into a persistent store
   (`.storage/vag_data_act.<VIN>`). A newer package overwrites what it contains; everything
   else keeps its value together with its own capture time.
4. The merged store is parsed into entities. Every value is resolved by its stable portal
   key; field names are only a fallback for keys unknown on a vehicle, and only when the
   field name is unique. Details: [docs/slot-mapping.md](docs/slot-mapping.md).
5. A value's `car_captured_at` is the newest report time of *its* package and can be older
   than `last_vehicle_report`. The portal can also deliver a placeholder for a package whose
   own content arrives later; only intermediate history can be lost that way, never the
   newest state.

## Known gaps

- `climatisation_state` / `remaining_climate_time`: two keys with contradicting values
  (actual state vs. last climatisation job). The entity stays empty while they disagree,
  both keys are in `candidates`.
- Keys were verified on Cupra Tavascan and Born. Other vehicles may deliver other keys; the
  parser then falls back to unique field names and learns them per VIN.

## Command line trace

`tools/login_trace.py` runs the login, lists the packages and parses the newest one.
Credentials come from `VAG_EMAIL` / `VAG_PASSWORD` or an interactive prompt – never from
files. Use `-v` for the full redirect chain.

## Feedback

Questions, ideas or bug reports? Open an
[issue](https://github.com/Timmes123/ha-vag-data-act/issues).

## ☕ Support

If this integration is useful to you and you want to support its development:

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/timmes123)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/paypalme/timmes123)

## Development

```
pip install -r requirements_test.txt
pytest -q && ruff check .
```

`tests/fixtures/raw/` holds 14 real downloads (VIN anonymized). The parser tests verify
every statement in `SPEC.md` against them.

## License

MIT – see [LICENSE](LICENSE).
