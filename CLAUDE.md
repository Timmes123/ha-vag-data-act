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

## Project status (2026-10-27)

- v0.1.0 released and installed on the user's HA via HACS (custom repository), HA restarted,
  integration loads, log level DEBUG set for `vag_data_act`. TommiG1 entry "Tavascan"
  (`cupra_eu_data_act`, entry 01KTV0NCKZYSN7HD4PN1STGJDR) disabled, "Born" entry was already disabled.
- The user enters the portal credentials **only in the HA UI** (never in chat). Next: user adds the
  config entries for Born and Tavascan, then verify logs (login hops, dataset download), health
  entities (`login_status`, `data_age_minutes`, `dataset`), SoC/odometer plausibility vs. fixtures.
- Parser findings are documented in `parser.py` (module docstring) and `docs/slot-mapping.md`.
  Mileage is identical across the three fixture contents; only `instrument_cluster_time` differs.
- Open points (README "Known gaps"): `climatisation_state` / `remaining_climate_time` key
  attribution, `range` = bare `value` key `0ca40e18-…` (unverified against the car),
  `climatisation_settings.target_temperature` unit, Born keys (learned per VIN if they differ).
- The cloud session cannot push tags or set repo topics (proxy blocks); a local session with the
  user's own `gh` login can (`gh repo edit --add-topic …`). The HACS topics check is ignored in CI.
- Step 5 of SPEC.md (evcc → custom vehicle via HA, remove TommiG1) is prepared in the README only;
  do not execute it before both vehicles are healthy here.
