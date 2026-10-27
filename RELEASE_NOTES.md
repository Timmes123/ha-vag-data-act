## v0.2.0 – merge every package

Breaking finding: portal packages are **partial**. A scan of 30 consecutive Born packages
held 6 … 93 points each with different report sets; the SoC/charging reports were present
in only 11 of 30. Taking only the newest package (v0.1.x) lost those values.

* Every poll now downloads **every package not processed yet** (oldest first) and merges
  its points **by key** into a persistent store (`.storage/vag_data_act.<VIN>`, version 2;
  the v0.1 store is migrated). Newer packages overwrite, missing points keep their value.
* Every value carries `source_dataset` and its own `car_captured_at` / `age_minutes`
  (capture time of the package it came from).
* Downloads are spaced 1 s apart and stop at HTTP 429 (the portal rate-limits after ~25
  downloads); the remaining packages follow on the next poll (`packages_pending`).
* `dataset` sensor: packages listed / processed / pending, point store size.
* `scan_datasets` service throttled as well and stops at 429.
