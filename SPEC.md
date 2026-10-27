# Auftrag: Home-Assistant-Custom-Integration „VAG EU Data Act" (Cupra Born + Tavascan)

> Stand 27.10.2026. Dieses Dokument ist die verbindliche Spezifikation. Deutsch in der Kommunikation,
> Code/Kommentare Englisch.

## Ziel

Baue eine eigene HACS-fähige Custom-Integration `custom_components/vag_data_act/`, die Fahrzeugdaten aus dem
VW-Konzern-EU-Data-Act-Portal (`https://eu-data-act.drivesomethinggreater.com`) holt und als HA-Entities
bereitstellt. Zweck: einzige Datenquelle für eine spätere eigene Ladelogik in HA, vollständig verifizierbar, mit
sichtbarem Health-Status. Ersetzt die Integration TommiG1/HA_VAG-EU-Data-Act (v0.6.47) und den
evcc-Fahrzeugzugriff.

Arbeitsweise: nichts annehmen, alles an den mitgelieferten JSON-Dateien und am Live-Portal verifizieren. Bei
Unklarheit Daten anschauen, nicht raten.

## Bereitgestellte Testdaten

14 Portal-ZIPs (Tavascan, VIN anonymisiert zu VSSZZZKRXSA000001, 27.10.2026), entpackt unter
`tests/fixtures/raw/<zip-name>/<innerer-dateiname>.json` (`user_id` ist redigiert, Rest verbatim).
Nutze sie als Testfixtures. Verifizierte Fakten dazu:

* ZIP enthält genau eine JSON: `{"vin": "...", "user_id": "...", "Data": [{"key": "<uuid v3>",
  "dataFieldName": "<dotted.path>", "value": "<string>"}, ...]}`. 171 Punkte, flache Liste, keine Gruppierung,
  keine Unterordner (trotz Portal-Beschreibung „Unterordner je Data Cluster"). Alle Werte sind Strings, auch
  Zahlen, Booleans, Dauern („6600s"), Epoch-ms („1793123118186") und ISO-Zeiten.
* Die Liste ist ein Sammelsurium aus ~9 verschiedenen Fahrzeug-Reports (`message_id`: RpcStateReport_4,
  RbcErrorReport_0, RpcSettingsReport_5, RbcSettingsReportForSettingsJob_0, RpcWindowHeatingStateReport_6,
  RpcStateReportForStartClimaJob_3, RPT_0..3, …), ohne Zuordnung Punkt→Report. Timestamps (`timestamp`,
  `car_captured_time`, `car_captured_utc_timestamp`) liegen lose daneben, nicht am Wert.
* Reihenfolge ist zufällig (zwei Downloads mit identischem Inhalt: nur 5/171 Punkte an gleicher Position).
  Nie auf Reihenfolge bauen.
* `key` ist stabil: über alle Downloads identische UUIDs bei identischem Feldnamen. Slots müssen per `key`
  identifiziert werden, nicht per Feldname.
* Duplikat-Slots mit verschiedenem Key und widersprüchlichen Werten im selben ZIP (geklärte Bedeutung):
  * `settings.target_soc`: Key `e21d4d25-…` = 100 (vom Nutzer gesetzter Wert) und Key `b3b04f31-…` = 80
    (wirksamer Wert, weil `battery_care_mode.charge_bcam_threshold` = 80 aktiv ist). → Zwei getrennte
    Entities: `target_soc_user` und `target_soc_effective` = min(user, bcam_threshold wenn Pflegemodus aktiv).
  * `mileage.value`: Key `75d65f00-…` = 10031 (Abfahrt), Key `30cc36fd-…` = 10044 (Ankunft, aktuell). → bei
    monotonen Zählern Maximum nehmen.
  * `climatisation_state` OFF/VENTILATION und `remaining_climate_time` 0s/1800s: vermutlich Ist-Zustand vs.
    letzter Klimaauftrag; Zuordnung noch offen – beide Keys als Attribute exponieren, Entity-Wert erst nach
    Verifikation festlegen.
  * Rein identische Duplikate (max_charge_current_ac, auto_unlock_ac, climatisation_settings.,
    additional_consumptions.): beliebigen nehmen, Abweichung als Warnung loggen.
* Nackter Feldname `value` = 90 ohne Kontext existiert. Kein Substring-Matching („enthält soc") – nur exakte
  Feldnamen.
* SoC-Dreifachquelle: `battery_state_report.soc` = 23, `battery_level_HV.value` = 23.0,
  `energy_contents.current_energy_content.physical_value` = 167.5 /
  `energy_contents.maximal_energy_content.physical_value` = 773.5 (Einheit 0,1 kWh → 16,75 / 77,35 kWh;
  Quotient 21,7 % = netto vs. SoC-Anzeige). Ist-SoC = `battery_state_report.soc`, plausibilisiert gegen die
  beiden anderen; bei >3 % Abweichung Wert nicht übernehmen und Health auf „ambiguous".
* Fahrzeug meldet Ladefehler: `charging_state_report.current_charge_state` = CHARGE_STATE_CHARGING_ERROR,
  `charging_state_report.error_code` = 28, `error_description` = App_RBC_FailedChargeInfrastructure. Als
  Entities exponieren (Ladezustand, Fehlercode, Fehlertext).
* Portal-Takt ≠ Fahrzeugfrische: Portal erzeugt alle 15 min ein ZIP, aber das Auto sendet ereignisgetrieben
  (Entriegeln/Abfahrt, Verriegeln/Ankunft, Lade-Events, Klima, Settings-Jobs). Verifiziert an einer Fahrt
  17:50–18:44 Uhr lokal: `instrument_cluster_time` 17:50:59 und 18:45:15, Mileage-Slots 10031→10044. Während
  der Fahrt kamen nur Settings-Reports (17:10Z, 17:27Z), keine SoC-/Mileage-Updates.
* ZIP-Zeitstempel ist wertlos: 8 ZIPs von 16:10Z–18:01Z enthielten alle dieselbe JSON `…180109.json` (mit
  Ankunftsdaten von 17:45Z); 5 ZIPs 18:48Z–19:47Z dieselbe `…194730.json`; 20:01Z eine neue `…200113.json`
  mit identischem Inhalt wie 194730, nur anders sortiert. Das Portal überschreibt nicht abgeholte Pakete
  rückwirkend. Konsequenz: Historie nur selbst aufbauen (HA Recorder), neues ZIP ≠ neue Daten → inneren
  Dateinamen bzw. Inhalts-Hash vergleichen und Entities nur bei Änderung aktualisieren.
* Datenalter = max(`car_captured_time`), nicht ZIP-Zeit. Ein Wochen-alter Report (20.10.) liegt mit im Paket →
  max nehmen, nicht irgendeinen.
* `instrument_cluster_time` ist lokale Fahrzeugzeit mit Offset, `car_captured_*` ist UTC (Z).

## Login- und Portal-Flow (Stand 26./27.10.2026)

VW hat am 26.10.2026 den Identity-Provider auf Auth0 Universal Login umgestellt. Referenzimplementierung (Go,
funktionierend): evcc PR #35385 (`vehicle/vw/eudataact/api.go`, `vehicle/vag/vwidentity/`), Issue #35377
enthält die komplette Redirect-Kette aus Browser-DevTools. Zweite Referenz (Python, veraltet beim Login, aber
Dataset-Listing/Download brauchbar): TommiG1/HA_VAG-EU-Data-Act `custom_components/cupra_eu_data_act/`.

Flow laut evcc #35377:

1. GET `https://identity.vwgroup.io/oidc/v1/authorize?client_id=f85e5b69-e3b2-43aa-9c0d-1b7d0e0b576f@apps_vw-dilab_com&redirect_uri=https://eu-data-act.drivesomethinggreater.com/login&response_type=code&scope=openid cars profile&state=de__de__CUPRA&nonce=<random>&prompt=login`
   → 302 auf `/u/login?state=<auth0-state>`
2. GET `/u/login?state=…` → Auth0-ULP-Seite; Formular ohne `id`/`action`, Felder: hidden `state`, `username`,
   `password` (kein `_csrf`/`relayState`/`hmac`/`email` mehr)
3. POST an dieselbe URL `/u/login?state=…` mit `state`, `username`, `password` (ggf. `action=default`)
4. Redirect-Kette folgen: `/authorize/resume` → `/v2/api/flow-state/post-login` → `/continue` →
   `/authorize/resume` → `https://eu-data-act.drivesomethinggreater.com/login?code=…&state=…` →
   `/services/callbacklogin` → `/content/euda/de/de/user.html` → `/de/de/user.html` (200). Login gilt als
   erfolgreich, wenn `/services/callbacklogin` passiert wurde.
5. Mögliche Interstitials: Terms-and-Conditions (`/terms-and-conditions`), Marketing-Consent
   (`/signin-service/v1/consent/marketing/…`) – erkennen und klaren Fehler liefern („Portal öffnen und
   bestätigen"), nicht als falsches Passwort melden.
6. Danach Dataset-Listing und ZIP-Download über die Portal-APIs – Endpunkte aus TommiG1s Code übernehmen und
   live verifizieren (Browser-DevTools-Mitschnitt vom Nutzer anfordern, falls unklar). Fehler-Policy: 429/5xx =
   Portal-Outage, Retry mit Backoff, keine Reauth; 401/403 = Session weg, Reauth.
7. Brand/Country: `state` = `{country}__{language}__{BRAND}` (de__de__CUPRA). Konfigurierbar machen, Default
   de/de/CUPRA. VIN je Config-Entry (zwei Fahrzeuge: Born und Tavascan, gleicher Account).

Nur ein Client darf das Portal nutzen – parallele Sessions (HA + evcc) haben die Daten unzuverlässig gemacht.
Die Integration ist diese eine Quelle; Logins serialisieren, Session-Cookies persistent halten, nicht bei jedem
Poll neu einloggen.

## Anforderungen an die Integration

* HA 2026.10, Python 3.14, async (aiohttp), DataUpdateCoordinator, Config-Flow (E-Mail, Passwort, Country,
  Language, Brand, VIN-Auswahl nach Login), Reauth-Flow, Reconfigure, Diagnostics (mit Redaction von
  VIN/E-Mail/Keys), Translations de/en. Alles UI-konfigurierbar, nichts YAML-only.
* Poll-Intervall Default 15 min, konfigurierbar; zusätzlich Service `refresh_now`.
* Parser als eigenständiges, pure-Python-Modul `parser.py` ohne HA-Abhängigkeit, mit pytest-Tests gegen die 14
  Fixtures. Alle 14 müssen dasselbe normierte Ergebnis liefern (bis auf Datenalter). Parser-Output: normiertes
  Dict + Liste nicht zugeordneter Punkte + Liste erkannter Ambiguitäten.
* Slot-Mapping (Feldname → Key → Bedeutung) in einer Datenstruktur, pro VIN lernbar/überschreibbar und in
  `.storage` persistiert; Unbekannte Keys landen als Attribute im Diagnose-Sensor, nie stillschweigend verworfen.
* Entities (mindestens): SoC (%), Reichweite (km), Kilometerstand (km, monoton), Ladeziel wirksam (%), Ladeziel
  Nutzer (%), BCAM-Schwelle (%), Pflegemodus aktiv, Ladezustand (enum), Ladefehlercode, Ladefehlertext,
  Ladeleistung (kW), Laderate (km/h), Restladezeit (h:mm, nur bei aktivem Laden), geladene Energie (kWh),
  Akku-Energie aktuell/max (kWh), Lademodus, Ladeart, max. AC-Ladestrom, verriegelt, Fahrzeug offen,
  Außentemperatur (°C), Batterie min/max-Temperatur (°C), Klimazustand, Restklimazeit, Scheibenheizung,
  Standlicht, Fahrzeugzeit, letzte Fahrzeugmeldung (timestamp), Datenalter (min).
* Health/Diagnose: `login_status` (ok/auth_failed/consent_required/portal_error), `last_successful_download`,
  `last_vehicle_report` (max car_captured_time), `data_age_minutes`, `dataset_changed` (bool, hat sich der
  Inhalt beim letzten Download geändert), `ambiguous_fields` (Liste), `unmapped_points` (Anzahl). Repairs-Issue
  bei auth_failed/consent_required.
* Keine unavailable-Verstecke: alte Werte bleiben stehen, Datenalter macht Stale sichtbar.
* Jeder Wert mit Attributen `source_key`, `car_captured_at`, `age_minutes`.
* Einheiten/Device-Classes/State-Classes sauber (SensorDeviceClass.BATTERY, DISTANCE total_increasing für km,
  ENERGY, POWER, TEMPERATURE, TIMESTAMP, DURATION). `remaining_charging_time_complete` „6600s" → Sekunden
  parsen, als duration.
* Logging: jede Login-Stufe mit Status, jeder Download mit inneren Dateinamen + Hash, auf DEBUG der komplette
  Redirect-Chain.
* README mit Setup (Portal: kontinuierliche Datenanfrage „All Data", 15 min, Nutzer muss im Portal vorher
  einmal Consent/Fahrzeug verknüpfen), Entity-Liste, Health-Erklärung, Hinweis „nur ein Client".

## Reihenfolge der Arbeit

1. Fixtures (bereits entpackt), Parser bauen, Tests grün auf allen 14 Dateien, Slot-Befunde oben nachprüfen und
   im Code als Kommentar dokumentieren. Alle Duplikat-Feldnamen auflisten und ihre Zuordnung begründen.
2. Login-Client bauen und gegen das Live-Portal testen (Credentials vom Nutzer, Trace-Log vorlegen). Falls
   Dataset-Endpunkte unklar: Nutzer um DevTools-HAR bitten.
3. Integration (Coordinator, Config-Flow, Entities, Diagnostics, Repairs).
4. Installation via HACS Custom Repository oder manuell nach `/config/custom_components/`, Born und Tavascan
   einrichten, Health-Sensoren prüfen.
5. Erst danach: evcc-Fahrzeuge auf `custom` umstellen (SoC/Range/Status aus HA per http-Plugin) und
   TommiG1-Integration entfernen. Nicht vorher, nicht parallel.

## Nicht tun

* Keine Reihenfolge-Annahmen, kein Substring-Matching, kein „erster/letzter Treffer".
* Keinen Wert als SoC übernehmen, der nicht aus `battery_state_report.soc` stammt.
* Kein zweiter Portal-Client parallel.
* Keine Werte raten, wenn Slots widersprüchlich sind – Ambiguität exponieren.
* Keine Entities verstecken.
