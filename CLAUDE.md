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
