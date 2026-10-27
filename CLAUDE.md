# HA-VAG-Data-Act

Custom Home Assistant integration `custom_components/vag_data_act/` for the VW group EU Data Act
portal (Cupra Born + Tavascan). Repo: **github.com/Timmes123/ha-vag-data-act**, installed via HACS
custom repository. Sibling projects with the same conventions: `../HA-betterTodo`, `../HA-Bambu-Filaments`.

## Authoritative documents
- `SPEC.md` – the full task/spec from the user (German). Follow it literally; "nothing assumed, verify
  everything against the fixtures and the live portal".
- `tests/fixtures/raw/<zip-name>/<inner>.json` – 14 real portal downloads (VIN anonymized to VSSZZZKRXSA000001,
  2026-10-27). `user_id` is redacted and the VIN replaced, everything else is verbatim. Only 3 distinct inner files exist
  (…180109, …194730, …200113); the other ZIPs are portal re-deliveries of the same content.

## Conventions
- User speaks German → communicate in German. Code, comments, commit messages in English.
- Python 3.14, HA 2026.10, async/aiohttp, DataUpdateCoordinator, full UI config (no YAML-only).
- Deployment only via GitHub releases consumed by HACS (same rule as the sibling projects); never
  copy files into the user's HA directly.
- hassfest rejects `{...}` braces and UTF-8 BOMs in translation files – write files without BOM.
- Never commit real credentials; Portal credentials are provided by the user at runtime only.
- Keep `README.md` up to date (setup, entity list, health explanation, "only one client" note).
- Releases: `gh workflow run release.yml --ref main` (or push a tag `v<version>`); the workflow reads
  the version from `manifest.json`, creates the tag and the GitHub release with `RELEASE_NOTES.md`.
  Every live fix = bump `manifest.json` + `RELEASE_NOTES.md` → PR → merge → release → HACS
  `update_information` + `download` → HA restart.
- CI: `.github/workflows/validate.yml` runs hassfest, hacs/action (topics check ignored, custom
  repo only) and `pytest -q` (parser/API/HA smoke tests). Local: `ruff check . && pytest -q`
  (needs `pytest-homeassistant-custom-component`, Python 3.14).

## Project status (2026-10-27, v0.1.1)

- v0.1.0 installed via HACS, both config entries (Born …0897, Tavascan …7134) created by the
  user in the HA UI (credentials only there, never in chat). Login works for both accounts
  (Auth0 chain → `/services/callbacklogin`), datasets download, `login_status = ok`.
- Tavascan: 171 points, values identical to the fixtures (SoC 23, odometer 10044, range 90,
  2 ambiguities climatisation). Born: only 72 points, **no battery/charging reports** (SoC,
  range, charging state, energy `unknown`); odometer, lock, lights, temperatures, settings OK.
  v0.1.1 logs/exposes the portal data request metadata (`data_request` attribute of the
  `dataset` sensor) to compare both vehicles' portal configuration.
- v0.1.1: `result_state` JWT redacted, foreign-slot keys never learned (`status: shared`),
  German names `Ladestand (SoC)` / `Ladestatus`, HACS topics check enabled.
- Open (README "Known gaps"): Born missing clusters, `climatisation_state` /
  `remaining_climate_time` attribution (Born delivers only the `f95799d0`/`3c19831c` pair →
  likely actual state), `range` vs. car display, `climatisation_settings.target_temperature`
  unit (Tavascan 120, Born 115).
- The README must not mention other integrations or tools the user migrates from; the
  switch-over of the user's other consumers is prepared outside the repository and executed
  only after both vehicles are healthy here.
- Repo topics set (home-assistant, hacs, integration, cupra, eu-data-act).
