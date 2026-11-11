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
`MS_GRAPH_TENANT_ID`, `MS_GRAPH_CLIENT_ID` und `MS_GRAPH_MAILBOX`; die Werte dürfen
nicht in die Ausgabe übernommen werden. Der Healthcheck muss HTTP 200 liefern.

## 2. Read-only Snapshot und Readiness

Der Datenbankservice stellt für lokale Betriebschecks `DATABASE_PUBLIC_URL` bereit. Die
Snapshot-CLI verwendet diese Variable automatisch, ohne eine DSN als Argument zu loggen:

```powershell
railway run --service Postgres --environment production -- `
  python scripts/product_hub/export_inventory_snapshot.py `
  --out "$env:TEMP\xw-inventory-cutover-$(Get-Date -Format yyyyMMdd-HHmmss).json"

railway run --service Postgres --environment production -- `
  python scripts/product_hub/check_inventory_cutover.py --json
```

Der Readiness-Check darf `eligible=false` liefern. Das ist vor der Inventur erwartbar und
blockiert den Master-Schalter. Ein Snapshot ist ein Anwendungsnachweis und ersetzt kein
provider-natives PostgreSQL-Backup.

## 3. Worker aktivieren

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

```powershell
railway deployment list --service xw-inventory-worker --environment production --json
railway logs --service xw-inventory-worker --environment production --latest --json --lines 100
```

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

## Aktueller Befund (11. November 2026)

- Railway-Zugangsdaten für sevDesk und Graph sind im Product-Hub-Service vorhanden.
- Healthcheck: HTTP 200; aktueller Alembic-Head `037_plc_parcel_evidence`.
- Read-only Snapshot: 0 Ledger-Bewegungen, 0 Inventory-Bestandspositionen,
  588 `sync_conflict`-Zeilen und 263 archivierte Payloads.
- Railway-Worker: Service aktiv; der zuletzt validierte Start war Deployment
  `6978341f-0087-49bb-bb04-a567397f6914`
  erfolgreich; Laufzeitlog zeigt den Start des Containers.
- Provider-natives PostgreSQL-Backup: über Railway CLI versucht, auf dem Hobby-Plan aber
  nicht verfügbar (Railway: „Manual backups and backup schedules are only available for
  Pro workspaces"). Der Anwendungs-Snapshot ist vorhanden, ersetzt dieses Backup nicht.
- Deshalb bleiben Inventur, Konfliktbereinigung, Shadow-Phase, Backup und Rollback echte
  Betriebs-Gates; der Master darf nicht aktiviert werden.
