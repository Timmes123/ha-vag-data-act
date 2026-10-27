## v0.1.1 – live fixes after the first installation

* Security: `result_state` (a JWT with the identity subject) and other token-like query
  parameters are redacted in debug logs and diagnostics.
* The portal's data request metadata (`metadata/partial` minus the identifier) is logged
  once, persisted and exposed as attribute `data_request` of the `dataset` sensor – needed
  to compare vehicles that deliver fewer data points (Cupra Born: 72 points, no battery/
  charging reports).
* Parser: a key that the slot table assigns to another slot is never learned for a
  different slot. A vehicle with a single `settings.target_soc` (effective-target key) now
  shows the user target with `status: shared`; a key learned by v0.1.0 is dropped.
* German entity names: `Ladestand (SoC)` and `Ladestatus` instead of `Ladezustand` /
  `Ladezustand (Status)`.
* CI: HACS topics check enabled (repository topics set).
