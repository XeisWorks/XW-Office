# CW00 – Current State and Reuse Map

Stand: 2026-09-17

## Bestehende Bausteine

- `sync_conflict` bleibt die technische, feldbezogene Drift-Meldung der Wix- und
  Inventory-Reconcile-Pfade. Sie wird nicht ersetzt oder migriert.
- `conflict_case` und seine Kindtabellen bilden darüber die fachliche, dauerhafte
  Wizard-Schicht mit Queue-Status, Entscheidungen, Snapshots und Aktionen.
- `channel_mapping` liefert stabile externe IDs und Revisions-/Hash-Metadaten.
- `outbox_event` und `OutboxWorker` bleiben der einzige Weg für externe Writes.
- `WixPushService.resolve_conflict` wird vom Worker, nicht von der UI, ausgeführt und
  übernimmt den vorhandenen Wix-Readback-/Baseline-Refresh.
- `audit_log` protokolliert interne Hub-Änderungen mit der Case-ID als Correlation-ID.
- Inventory-Drift erzeugt bereits `sync_conflict` und fließt damit ohne parallele
  Konfliktarchitektur in den Wizard ein.

## Bewusste Grenzen

- Der Wix-Quellscan liest ausschließlich bereits gemappte Produkte read-only ein,
  archiviert geänderte Payloads und führt `name`, `description` und `visible` in die
  technische Konfliktliste über. sevdesk/Amazon bleiben bei ihren jeweiligen Importern.
- Wix-Produktbilder sind Canonical-Asset-Metadaten: erstes Bild `COVER`, weitere
  `GALLERY_IMAGE`, jeweils als Wix-URL ohne Download. Entfernte Bilder werden als
  `stale` markiert statt gelöscht.

- Der erste Scanner materialisiert vorhandene, offene `sync_conflict`-Signale. Direkte
  Vollimporte von Wix/sevdesk/Amazon gehören weiterhin den jeweiligen Importern.
- Sichere interne Writes sind zunächst auf direkte Product-Felder begrenzt. Preis,
  Bestand und Identifier bleiben gesperrt, bis ihre spezialisierten Services in einen
  feldgenauen Planner eingebunden sind.
- Wix ist der einzige vorhandene verifizierbare externe Write-Pfad. sevdesk und Amazon
  werden als nicht unterstützt ausgewiesen, statt Erfolg zu simulieren.

## Migration und Deduplizierung

Migration `016` hängt additiv an Head `015`. Ein fachlicher Schlüssel kann mehrfach in
der Historie vorkommen; `(dedupe_key, occurrence)` ist eindeutig. Nur Status `OPEN`,
`IN_PROGRESS`, `WAITING` und `PARTIALLY_RESOLVED` werden als aktive Dublette behandelt.
Ein absichtlich erlaubter Unterschied wird bei späteren Scans unterdrückt.
