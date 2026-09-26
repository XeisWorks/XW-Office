# T02 – Migrationsvorschau

Stand: 2026-09-26. Die Vorschau lief gegen die öffentliche Railway-Verbindung in
einer PostgreSQL-Transaktion mit `SET TRANSACTION READ ONLY`. Sie hat keine
Produkt-, Asset-, Alias- oder Providerdaten verändert.

## Ergebnis

| Prüfaspekt | Ergebnis |
| --- | ---: |
| Legacy-Zeilen in `inventory.products` | 507 |
| Exakt oder über Hub-Alias zugeordnet | 505 |
| Offen, nicht automatisch zuordenbar | 2 |
| Legacy-Pfad vorhanden, Hub-`PRINT_PDF` noch nicht gespiegelt | 170 |
| Ohne Legacy-Druckpfad | 335 |
| Aufgelistete Hub-Aliasbeziehungen | 158 |

Die vollständige zeilenweise Zuordnung einschließlich aller Druckpfade, Titelkonfigurationen
und Aliaslisten liegt lokal als `migration_preview.local.json`. Sie wird nicht eingecheckt,
weil sie interne Dateipfade enthält.

Offene Zuordnungen, bewusst nicht geraten:

- `XW-412.2` – *Auf da Hulzgstett'n*
- `XW-7501` – *Mnoschil*

Titelbezogene Druckkonfigurationen sind als separate manuelle Migrationspunkte im Bericht
markiert. Sie dürfen nicht in die aktuelle, nur variantenbezogene Hub-PrintRule eingeklappt
werden. Insbesondere die 170 Pfade sind erst in T04 additiv als `PRINT_PDF` mit
`NETWORK_PATH` zu spiegeln; die Legacy-Konfiguration bleibt bis zum erfolgreichen
Shadow-Vergleich unverändert.

## Backup, Schreibsperre und Rollback

Vor jeder additiven Migration in T04 wird mit
`scripts/product_hub/export_catalog_snapshot.py` ein lokaler Hub-Snapshot erzeugt und die
jeweilige `inventory.products`-JSON unverändert gesichert. Der Preview-Runner selbst bleibt
read-only. Bis zur bestätigten Umschaltung bleiben `catalog_write_enabled`, Hub-Edit-API und
Sync-Push deaktiviert; keine Migration aktiviert parallele Desktop- und Hub-Produktwrites.

Rollback bedeutet: die neue Desktop-Leseumschaltung per Feature Flag deaktivieren, den
Legacy-Snapshot weiterhin lesbar lassen und neue Hub-Daten nicht automatisch zurück in den
Settings-Katalog schreiben. Bei einem fehlerhaften additiven Import wird aus dem Snapshot
wiederhergestellt, erst nach Prüfung der Zieltabellen und ohne Providerwrites.
