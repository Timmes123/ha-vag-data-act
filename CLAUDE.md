# HA-VAG-Data-Act

Custom Home Assistant integration `custom_components/vag_data_act/` for the VW group EU Data Act
portal (Cupra Born + Tavascan). Repo: **github.com/Timmes123/ha-vag-data-act** (public, MIT),
installed via HACS custom repository. Sibling projects with the same conventions: `../HA-betterTodo`,
`../HA-Bambu-Filaments` – when in doubt, look there first.

## Authoritative documents
- `SPEC.md` – the user's task/spec (German). "Nothing assumed, verify everything against the
  fixtures and the live portal."
- `docs/slot-mapping.md` – key/field findings incl. the live package observations.
- `tests/fixtures/raw/<zip-name>/<inner>.json` – 14 real portal downloads (VIN anonymized to
  VSSZZZKRXSA000001, 2026-10-27, `user_id` redacted). Only 3 distinct inner files exist; the portal
  served placeholders for the other ZIP names at the time.

## Hard rule: deployment only via HACS releases
Never write integration files into the user's HA (no `ha_write_file`, no copying). Every change,
debug iterations included: commit → GitHub release → HACS update (over MCP) → HA restart → verify
via logs/entities over MCP. Portal credentials exist only in the HA UI, never in chat or files.

## GitHub workflow (same as the sibling projects)
- **Commit directly on `main`.** No feature branches, no own pull requests (PRs only from external
  contributors, merged with a merge commit).
- **One commit per release**, named like the tag: `vX.Y.Z: <what changed>`; it contains code,
  `manifest.json` bump and README changes together. Other commits with an area prefix
  (`README: …`, `CI: …`, `CLAUDE.md: …`, `Parser: …`). Commit body: only the Co-Authored-By line.
- **Release with the gh CLI**, never a workflow:
  `gh release create vX.Y.Z --prerelease --title "vX.Y.Z – <topic>" --notes "<notes>"`.
  Every release is a **pre-release**; stable only by promoting a proven build on the user's call
  (`gh release edit vX.Y.Z --prerelease=false --latest`) with rollup notes since the last stable.
  The HACS pre-release switch for this repository must be ON on the user's HA.
- **Docs-only changes get no release** (README, docs/, images, metadata): commit + push.
- **Versioning:** major = huge milestone, minor = new features, patch = fixes/refinements.
- **Batch changes** while a discussion is ongoing: one release per topic, not per tweak.
- CI: `.github/workflows/validate.yml` (hassfest, HACS action, pytest) on push/PR/weekly/manual.
  Local: `ruff check . && ruff format --check . && pytest -q` (Python 3.14,
  `pytest-homeassistant-custom-component`; the HA smoke test only runs in CI on Windows).

## Conventions
- User speaks German → communicate in German. Code, comments, commit messages, docs in English.
- HA 2026.10, Python 3.14, async/aiohttp, DataUpdateCoordinator, full UI config (no YAML-only).
- hassfest rejects `{...}` braces and UTF-8 BOMs in translation files – write files without BOM.
- README: structure like the siblings (badges, pitch, features, installation with my-HA badges,
  entities/health/services with the UI path first, how it works, FAQ, feedback, support, license).
  **Never name other integrations or tools** in public repo files, no migration notes, no internal
  project history – that stays in chat/memory.
- Keep `docs/slot-mapping.md` up to date with every verified key finding.

## Project status (2026-10-28, v0.2.2 pre-release)
- Both vehicles (two portal accounts) log in (Auth0 chain → `/services/callbacklogin`), sessions
  are reused across polls and restarts (cookies in `.storage`).
- **Packages are partial** (live scans of 30+30 packages via service `scan_datasets`): Born 6…93
  points, SoC in 11/30; Tavascan 143…171, SoC missing in 3 during a trip. Both portal data
  requests are identical (All Data, 15 min). Portal rate-limits (HTTP 429) after ~25 downloads.
  v0.2.0 therefore downloads every unseen package (1 s apart, stop at 429) and merges points by
  key into a persistent store with per-value provenance. v0.2.1 (store migration fix) is live:
  both entries loaded, 30 packages each backfilled without 429, Born shows SoC 51 % / 135 km /
  CHARGE_STATE_CHARGING_ERROR from the 19:47Z package. All releases are pre-releases; no stable
  has been promoted yet.
- Verified live: range key `0ca40e18` = display (90 km at 23 %); climate target temperature =
  10 °C + raw/10 (120 → 22.0 °C Tavascan, 115 → 21.5 °C Born), shipped in v0.2.2. SoC and HV
  level always arrive in the same package (see docs/slot-mapping.md).
- Open: `climatisation_state`/`remaining_climate_time` key attribution (Born delivers only the
  `f95799d0`/`3c19831c` pair → likely actual state).
- 2026-10-28: the previous Data Act integration was removed from the user's HA (config entries
  and HACS repository); entity ids lost their `_2` suffix; the energy dashboard and the monthly
  utility meters point at this integration's entities. The user's charging manager still has to
  be switched to these entities by the user in its own UI (needs its admin password).
