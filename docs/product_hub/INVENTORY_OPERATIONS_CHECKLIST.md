# Inventur-/Cutover-Betriebscheckliste

Diese Checkliste ist der kontrollierte manuelle Rest des Inventur-/Rechnungsabgang-Umbaus.
Alle Befehle mit `--json` sind read-only, solange der ausdrücklich genannte Master-Schalter
nicht aktiviert wird. Secretwerte niemals ausgeben oder in Dateien/Logs übernehmen.

## 1. Vorprüfung

```powershell
git switch main
git pull --ff-only origin main
railway status
railway variable list --service XW-Product-Hub --json
Invoke-WebRequest -UseBasicParsing https://products.xeisworks.at/health
```

Erwartet werden gesetzte Variablennamen `DATABASE_URL`, `SEVDESK_API_TOKEN`,
`WIX_API_KEY` und `WIX_SITE_ID`,
`MS_GRAPH_TENANT_ID`, `MS_GRAPH_CLIENT_ID` und `MS_GRAPH_MAILBOX`; die Werte dürfen
nicht in die Ausgabe übernommen werden. Der Healthcheck muss HTTP 200 liefern.

## 2. Read-only Snapshot und Readiness

Die beiden ersten Betriebsprüfungen lassen sich gesammelt und ohne Secret-Ausgabe
wiederholen. Das Hilfsskript schreibt Snapshot, DB-Gate und Runtime-Gate in ein lokales
Verzeichnis; der erwartete Exit-Code `2` des DB-Gates vor der Inventur wird als normaler
Blockierungsbefund behandelt:

```powershell
.\scripts\product_hub\invoke_inventory_railway_preflight.ps1
```

Das Skript verändert weder Railway-Variablen noch den Product-Hub-Master-Schalter.
Es liest nur Health-/Service-Status und führt die unten beschriebenen read-only
Anwendungsprüfungen aus.

Der Datenbankservice stellt für lokale Betriebschecks `DATABASE_PUBLIC_URL` bereit. Die
Snapshot-CLI verwendet diese Variable automatisch, ohne eine DSN als Argument zu loggen:

```powershell
railway run --service Postgres --environment production -- `
  python scripts/product_hub/export_inventory_snapshot.py `
  --out "$env:TEMP\xw-inventory-cutover-$(Get-Date -Format yyyyMMdd-HHmmss).json"

railway run --service Postgres --environment production -- `
  python scripts/product_hub/check_inventory_cutover.py --skip-runtime-configuration --json
```

Die Runtime-Gates werden getrennt im Product-Hub-Service geprüft; dadurch wird keine
private Postgres-DNS-Adresse außerhalb des Railway-Netzes verwendet und es werden keine
Secretwerte ausgegeben:

```powershell
railway run --service XW-Product-Hub --environment production -- `
  python scripts/product_hub/check_inventory_cutover.py --runtime-only --json
```

Der Readiness-Check darf `eligible=false` liefern. Das ist vor der Inventur erwartbar und
blockiert den Master-Schalter. Ein Snapshot ist ein Anwendungsnachweis und ersetzt kein
provider-natives PostgreSQL-Backup.

## 3. Worker aktivieren

Die neue Projektionsroutine ist separat prÃ¼fbar und standardmÃ¤ÃŸig read-only:

```powershell
railway run --service XW-Product-Hub --environment production -- `
  python -m xw_office.services.product_hub.inventory_projection_cli --summary
```

`--write` darf erst nach bestandener Inventur, Readiness und ausdrÃ¼cklich
aktiviertem `XW_PRODUCT_HUB_INVENTORY_MASTER_ENABLED=true` verwendet werden. Der
Worker ruft diesen Schreibpfad nur nach einem fehlerfreien sevDesk-Sync auf.

Der separate Railway-Service `xw-inventory-worker` ist im Produktionsprojekt angelegt und
aktiv. Er verwendet Repository/Branch `XeisWorks/XW-Office`/`main` und wurde zuletzt mit
der zuletzt validierte Start war Deployment `6978341f-0087-49bb-bb04-a567397f6914`.
Aktuelles
Startkommando:

```text
python -u -m xw_office.services.product_hub.inventory_worker_cli --interval-seconds 86400
```

Die Variablen `DATABASE_URL`, `SEVDESK_API_TOKEN` sowie die Graph-Grundkonfiguration sind
als Railway-Referenzen auf Postgres bzw. `XW-Product-Hub` gesetzt. Der Worker meldet sich
als aktives Deployment; ein manueller SSH-Zugriff ist in diesem Railway-Konto nicht
freigeschaltet. Für einen einmaligen Lauf kann bei Bedarf ein kontrolliertes
`railway up` mit temporärem `--once`-Startkommando verwendet werden; der Dauerbetrieb
bleibt danach wiederherzustellen:

Zusätzlich ist `XW_INVENTORY_WORKER_ACTIVE=true` als nicht-geheimer Betriebsmarker in
`XW-Product-Hub` und `xw-inventory-worker` gesetzt. Dadurch kann der Readiness-CLI den
bereits nachgewiesenen Worker-Service als `ready` statt pauschal als `manual` ausweisen.

```powershell
railway deployment list --service xw-inventory-worker --environment production --json
railway logs --service xw-inventory-worker --environment production --latest --json --lines 100
```

Die Logs schreiben nach stdout und enthalten `Inventory worker started` sowie pro Zyklus
`Inventory cycle finished forecast=... sync=...`; HTTP-Client-Rauschmeldungen werden
unterdrückt. Damit sind Lauf und Fehlerstatus ohne SSH-Zugriff prüfbar.
Der Fünfjahres-Forecast verwendet paginierte sevDesk-Bulk-Snapshots für Dokumente und
Positionen, sofern der Provider sie anbietet; ältere/alternative Provider fallen sicher
auf Einzelabrufe zurück. Der Inventory-Feed verwendet dieselbe Bulk-Strategie für
Rechnungs-/Gutschriftpositionen; verschachtelte sevDesk-SKUs aus `part.partNumber` werden
normalisiert.

Ein erfolgreicher Lauf muss ohne `needs_review`-/Fehlerstatus enden. Der Worker aktiviert
niemals `inventory_master_enabled`. Der erste Produktionsstart läuft; die bestehende
Readiness-Blockade durch ungeklärte sevDesk-Zuordnungen/Synchronisationskonflikte bleibt
bewusst bestehen.

## 4. Produktionsinventur

1. Provider-natives PostgreSQL-Backup erstellen und Backup-ID/Zeitpunkt notieren.
2. Im Product Hub `/app/inventory/cutover` öffnen.
3. Zählliste einfrieren/exportieren und je aktiver physischer SKU/Variante tatsächlich zählen.
4. Zweite Kontrolle oder Differenzprüfung durchführen.
5. Erst nach Prüfung die Inventur abschließen; keine pauschale `0`- oder `∞`-Übernahme.
6. Den erzeugten Snapshot und die Zählliste gemeinsam revisionssicher ablegen.

## 5. Shadow-Phase und Rollback-Probe

1. `XW_PRODUCT_HUB_INVENTORY_SHADOW_ENABLED=true` setzen und deployen; Master bleibt `false`.
2. Mindestens einen repräsentativen Rechnungs-/Gutschrift-/Druck-/Recount-Zyklus beobachten.
3. `/app/inventory/cutover` prüfen: keine offenen Bestands-/Sync-Konflikte, Projektionen
   reproduzieren den gezählten Bestand.
4. Master testweise auf `false` belassen/zurücksetzen und verifizieren, dass Ledger und
   materialisierter Bestand unverändert bleiben.
5. Erst wenn Backup, Shadow-Nachweis, Projektionen und Rollback dokumentiert sind, darf
   `inventory_master_enabled=true` nach ausdrücklicher Bestätigung gesetzt werden.

## Aktueller Befund (12. November 2026, Railway-Prüfung 00:00 CET)

Nach dem Forecast-Refresh wurde der Read-only-Gate erneut über `DATABASE_PUBLIC_URL`
des Postgres-Service plus Railway-Referenzen des Product-Hub-Service geprüft:
432 Bestandspositionen sind materialisiert, 0 Ledger-Bewegungen vorhanden, 594
blockierende Quellen-/Mappingprobleme, 29 Legacy-/Hub-Abweichungen und 710 offene
Sync-Konflikte. Provider-/Graph-/Wix-Grundkonfiguration und der Worker-Marker sind dabei
`ready`; der Master bleibt wegen Shadow, Inventur und Konflikten blockiert.

- Railway-Zugangsdaten für sevDesk und Graph sind im Product-Hub-Service vorhanden.
- Healthcheck: HTTP 200; aktueller Alembic-Head `037_plc_parcel_evidence`.
- Read-only Snapshot (Railway CLI, 11. November 2026, 23:59 CET): 432
  `inventory_stock`-Zeilen, 0 Ledger-Bewegungen, 432 `inventory_alert`-Zeilen,
  726 `sync_conflict`-Zeilen, 432 Outbox-Ereignisse und 263 archivierte Payloads.
- Der DB-Readiness-Check wurde mit `--skip-runtime-configuration` ausgeführt und
  endet erwartungsgemäß mit Exit-Code 2 (`eligible=false`). Der getrennte
  Product-Hub-Runtime-Check endet mit Exit-Code 0 (`eligible=true`): Provider-
  credentials (sevDesk/Graph/Wix) und Worker-Service sind betriebsbereit.
- Der Implementierungsgate `legacy_mutation_paths` ist im Readiness-Bericht jetzt
  `ready`: Im Master-Modus schreibt `InventoryService` direkt in das Hub-Ledger; der
  Legacy-JSON-Editor wird dabei schreibgeschützt. Das ist kein Ersatz für die noch
  offenen Daten-/Betriebsnachweise.
- Der read-only Projektions-Dry-Run lief über Railway mit `PYTHONPATH=src`: 0
  Schreibungen, 0 Konflikte/Fehler und 432 übersprungene Varianten. Die Überspringungen
  sind auf fehlende eindeutige Wix-Produkt-/Inventarzuordnungen zurückzuführen; es wurde
  keine externe Bestandsmenge verändert.
- Railway-Worker: Service aktiv; der zuletzt geprüfte erfolgreiche Start ist Deployment
  `319ea9cd-0331-45ed-9ee3-55b9a968f1ac` (Commit `e721950`).
- Provider-natives PostgreSQL-Backup: über Railway CLI versucht, auf dem Hobby-Plan aber
  nicht verfügbar (Railway: „Manual backups and backup schedules are only available for
  Pro workspaces"). Der Anwendungs-Snapshot ist vorhanden, ersetzt dieses Backup nicht.
- Worker-Laufzeitprüfung: Forecast mit 432 aktualisierten und 206 übersprungenen
  Varianten erfolgreich; der anschließende Sync endet weiterhin erwartungsgemäß mit
  Exit 1 wegen fehlender Inventurbasis/Unterdeckungen und Gutschriften ohne eindeutige
  Ursprungsrechnung. Der Worker markiert den Product-Hub-Projektionslauf deshalb sicher
  als übersprungen (`master_enabled=false`).
- Deshalb bleiben Inventur, Konfliktbereinigung, Shadow-Phase, Backup und Rollback echte
  Betriebs-Gates; der Master darf nicht aktiviert werden.

## Aktueller Deploy- und Preflight-Stand (12. November 2026, 00:36 CET)

- `origin/main` steht auf Commit `84cf681` (deterministische Idempotenzschlüssel für
  Legacy-START-/REPRINTS-Bewegungen).
- Product Hub Deployment `5dd2017d-6344-4e3a-80ef-cbc9178a170b` und Worker Deployment
  `e396cb2d-ac48-449c-8d0a-209d97283e8e` sind SUCCESS; `/health` ist HTTP 200.
- `invoke_inventory_railway_preflight.ps1` ist der manuelle Betriebszugriff für den
  read-only Check. Erwarteter Zustand vor Inventur: DB-Readiness Exit 2,
  Runtime-Readiness Exit 0.
- Der Preflight-Snapshot bestätigt 432 `inventory_stock`, 0 Ledger-Bewegungen,
  726 Sync-Konflikte (710 offen), 432 Outbox-Ereignisse und 263 archivierte Payloads.
  Keine externen Bestandsdaten wurden verändert.
- Für die Mapping-Bereinigung kann danach read-only der Exact-SKU-Preflight im
  Worker ausgeführt werden:
  `python scripts/product_hub/preview_exact_inventory_mappings.py --summary`.
  Der zuletzt verifizierte Lauf fand 240 eindeutige Kandidaten; wegen unklarer
  Artikelarten (u. a. Versand-/Serviceartikel) werden sie nicht automatisch angewandt.

## Read-only-Folgepruefung (12. November 2026, 00:11 CET)

Das Skript `scripts/product_hub/invoke_inventory_railway_preflight.ps1` wurde fuer
Railway-Aufrufe ohne lokalen Projekt-Link angepasst: Projekt/Environment werden
explizit adressiert, Service-IDs aus dem Railway-Inventar gelesen und der Python-
Interpreter aus der Projekt-venv verwendet. Die PowerShell-Datei wurde geparst und
der vollstaendige read-only Ablauf erfolgreich ausgefuehrt.

- Healthcheck: HTTP 200; Railway-Serviceinventar: Postgres, XW-Product-Hub und
  `xw-inventory-worker` melden SUCCESS. Der Worker-Deploymentstart
  `3b4b3b87-2f31-4a72-8b5d-9094f3e1fdfe` und Product-Hub-Deployment
  `e31e8357-4053-4fef-acc9-2ef63bfe7f1e` sind gesund.
- Der DB-Readiness-Check endet erwartungsgemaess mit Exit 2 (`eligible=false`);
  der getrennte Runtime-Check endet mit Exit 0 (`eligible=true`). sevDesk-, Graph-,
  Wix-Projektionszugangsdaten und Worker-Service sind `ready`; Master und Shadow
  bleiben `false`.
- Snapshot um 00:11 CET: 432 `inventory_stock`, 0 Ledger-Bewegungen,
  0 `inventory_document_booking`, 0 Inventur-Sessions, 432 Alarme,
  726 Sync-Konflikte (710 offen), 432 Outbox-Ereignisse und 263 archivierte
  Payloads. Datenbankchecks bleiben wegen fehlendem Shadow/Ledger, sevDesk-Drift,
  Quellenvertrag und Sync-Queue blockiert; Kanalprojektionen und Betriebsfreigabe
  stehen auf `manual`.
- Damit bleiben Bestands-Master und Shadow weiterhin deaktiviert. Der frische
  Snapshot liegt im lokalen Temp-Ordner; er ersetzt kein provider-natives Backup.
- Separater Railway-Projektions-Dry-Run (`--summary`, read-only): 0 Schreibungen,
  0 Konflikte/Fehler und 432 uebersprungene Varianten wegen nicht eindeutiger
  Wix-Produkt-/Inventarzuordnungen.
- Die automatischen Worker-Neustarts nach Main-Deployments um 00:07, 00:09 und
  00:11 CET meldeten jeweils Forecast `exit=0`, sevDesk-Sync `exit=1`,
  `invoice.processed=0`, `already_applied=0` und uebersprangen Projektionen bei
  `master_enabled=false`. Der Snapshot bestaetigt 0 Ledger-Bewegungen und 0
  Rechnungsbuchungsmarker; Codex hat keinen Worker-Lauf manuell ausgeloest.
- Neuester Product-Hub- und Worker-Deploymentstand (Commit `4aef522`) ist SUCCESS.
  Der Worker-Neustart um 00:12 CET war bei dieser Protokollierung noch aktiv;
  sein Laufabschluss ist daher nicht vorweggenommen.

## Read-only-Folgepruefung (12. November 2026, 00:17 CET)

Nach Abschluss des Worker-Zyklus wurde der Railway-Preflight erneut vollstaendig
read-only ausgefuehrt. Der Snapshot um 00:16:53 CET bestaetigt 432
`inventory_stock`-Zeilen, 0 Ledger-Bewegungen, 0 `inventory_document_booking`-Marker,
0 Inventur-Sessions, 432 Alarme, 726 Sync-Konflikte (710 offen), 432 Outbox-Ereignisse
und 263 archivierte Payloads. Master und Shadow bleiben `false`; Runtime-Readiness ist
`eligible=true`, DB-Readiness erwartungsgemaess `eligible=false`.

Der Worker auf Deployment `0108b761-d361-4187-a581-6b9d540c7d4c` (Commit `4aef522`)
beendete den Forecast mit Exit 0. Der sevDesk-Sync endete mit Exit 1, `processed=0`
und `already_applied=0`, weil offene Altbelege wegen fehlender Bestandsbasis,
unstabiler Positionszuordnung bzw. uneindeutiger SKU-Zuordnung in `needs_review`
bleiben. Die Kanalprojektion wurde bei `master_enabled=false` uebersprungen. Der
Folgesnapshot weist weiterhin keine Bestandsbewegungen oder Rechnungsbuchungen auf;
Codex hat keinen Worker-Lauf manuell ausgeloest.

## Read-only-Folgepruefung nach Mapping-Fix (12. November 2026, 00:49 CET)

Nach Commit `894753b` sind Worker `43c530e1-a0ec-485b-921e-1b2a5ac403c4`
und Product Hub `bb5f3c7f-ddfc-4c00-8ae3-28e067b56633` SUCCESS; Healthcheck HTTP 200.
Der automatische Worker-Lauf meldet Forecast Exit 0, sevDesk-Sync Exit 1,
`processed=0`/`already_applied=0` und uebersprungene Kanalprojektion bei
`master_enabled=false`.

Der Preflight-Snapshot (00:48:56 CET) zaehlt 432 Bestandspositionen, 0 Ledger-
Bewegungen, 0 Rechnungsbuchungsmarker, 0 Inventur-Sessions, 432 Alarme, 726
Sync-Konflikte (710 offen), 432 Outbox-Ereignisse und 263 archivierte Payloads.
Runtime-Readiness ist `eligible=true`; DB-Readiness bleibt `eligible=false`.
`legacy_mutation_paths` ist `ready`; weiterhin blockieren Shadow/Ledger-Nachweis,
594 Quellen-Auditprobleme, 29 Bestandsabweichungen und 710 offene Sync-Konflikte.
Master/Shadow blieben `false`; es wurden keine Buchungs- oder Providerdaten geschrieben.

## Read-only-Folgepruefung nach Exact-SKU-Preflight (12. November 2026, 00:59 CET)

Der aktuelle Stand auf Commit `d9e421b` ist erfolgreich deployt:
Product Hub `2841582d-afab-4663-af81-1a389a8f8b21`, Worker
`41d96250-a187-432f-a781-be4b35797dad`, Healthcheck HTTP 200. Der Preflight endet
mit Runtime-Readiness Exit 0 und DB-Readiness Exit 2. Der Quellen-Audit bleibt bei
594 Mapping-Blockern, 565 fehlenden Quellmengen und 29 Legacy-/Hub-Drifts.
Der Exact-SKU-Preflight fand 240 1:1-Kandidaten, schreibt aber bewusst nichts;
Artikelarten und Zuordnung müssen vor einer Anwendung bestätigt werden.
