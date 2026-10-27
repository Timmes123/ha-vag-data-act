## v0.1.2 – dataset scan diagnostic

* New service `vag_data_act.scan_datasets`: downloads every listed dataset of a vehicle over
  the normal session and logs per file the inner name, hash, point count, report ids and
  whether the SoC / charging reports are included (also in the diagnostics download). Used
  to check whether older packages of a vehicle carry data points the newest one lacks.
* `range` (key `0ca40e18-…`) confirmed against the vehicle display (90 km at 23 %).
