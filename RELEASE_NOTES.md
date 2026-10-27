## v0.1.0 – initial release

* Pure-Python parser for the EU Data Act dataset, verified against 14 real portal
  downloads (stable keys, random order, duplicate slots, SoC plausibility check).
* Portal client with the Auth0 Universal Login flow (since 2026-10-26), persistent session
  cookies, serialized logins, consent/terms detection, 429/5xx backoff without re-login.
* Home Assistant integration: config flow (account → vehicle), reauth, reconfigure,
  options (poll interval), sensors/binary sensors with `source_key`/`car_captured_at`/
  `age_minutes`, health entities, diagnostics (redacted), repair issues, `refresh_now`.
* Entities only update when the dataset content changed; stale values stay visible.
