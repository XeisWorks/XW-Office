# Unified Product Workflow – Fortschritt

## T01 – Iststand und Verbraucher erfassen

Status: erledigt am 2026-09-26.

Änderungen:

- Belegte Bestandsaufnahme in `CURRENT_STATE.md` angelegt.
- Den Taskstatus in `markdowns/unifying product flow/TASK_QUEUE.yaml` auf `done` gesetzt.
- Keine Produkt-, Datenbank- oder Provider-Schreibaktion ausgeführt.

Tests:

- `python -m alembic heads` → `017_wix_reconciliation_disposition (head)`
- `python -m pytest tests/unit/test_product_hub_onboarding.py tests/unit/test_product_hub_outbox_worker.py tests/unit/test_product_hub_web_api.py -q` → 27 bestanden; eine bekannte Starlette/httpx-Deprecation-Warnung.
- `git diff --check` → ohne Befund.

Offene externe Einrichtung:

- Serverseitiger Microsoft-Graph-/OneDrive-Zugriff samt sicherer Tokenablage.
- Ausgewählte OneDrive- und Cover-Hintergrundordner sowie die privaten Book-Antiqua-/Deneane-Fonts.
- Reale Wix-/sevDesk-Leseprüfung, Editor-Link-Strategie und ein persistenter Railway-Worker.
- Amazon-SP-API-Rollen und Produktidentifikatoren erst für P07.

Commit: `9d37dff` (`docs: record unified product workflow baseline`).

Nächster freigegebener Task: **T02 – Migration als Vorschau planen**.

## T02 – Migration als Vorschau planen

Status: erledigt am 2026-09-26. Der echte Bericht wurde über die öffentliche Railway-
Verbindung in einer PostgreSQL-Read-only-Transaktion erzeugt; Details stehen in
`MIGRATION_PREVIEW.md`.

Änderungen:

- `services/product_hub/migration_preview.py` gleicht ausschließlich normalisierte,
  exakte SKUs und Hub-Aliase ab. Doppelte Legacy-SKUs bleiben mehrdeutig.
- `scripts/product_hub/preview_legacy_product_migration.py` liest
  `setting_kv.inventory.products`, Varianten, Aliase und `PRINT_PDF`-Assets und schreibt
  einen lokalen JSON-Bericht. Für PostgreSQL setzt es die Transaktion auf read-only.
- Titelbezogene Druckkonfigurationen werden gezählt und als manueller Migrationspunkt
  ausgewiesen, da die aktuelle Hub-Regel nur variantenbezogen ist.

Ausführung mit einer bewusst bereitgestellten, bevorzugt schreibgeschützten DB-Verbindung:

```powershell
python scripts/product_hub/preview_legacy_product_migration.py `
  --database-url $env:DATABASE_URL `
  --out docs/product_workflow/migration_preview.local.json
```

`migration_preview.local.json` enthält lokale Druckpfade und wird deshalb nicht als
allgemeiner Repository-Artefakt eingecheckt. Der echte Bericht umfasst 507 Zeilen,
505 eindeutige Zuordnungen und zwei bewusst offene Zuordnungen.

Tests:

- `python -m pytest tests/unit/test_product_hub_migration_preview.py tests/unit/test_product_hub_repository.py tests/unit/test_inventory_service_import.py -q` → 40 bestanden.
- Der CLI-Test erstellt eine temporäre SQLite-Datenbank, erzeugt den Bericht und beweist,
  dass `inventory.products` unverändert bleibt.
- `git diff --check` → ohne Befund.

Commit: `8129bee` (`docs: record product migration preview`).

Nächster freigegebener Task: **T03 – Hub-API für Desktop-Verbraucher ergänzen**.

## T03 – Hub-API für Desktop-Verbraucher ergänzen

Status: erledigt am 2026-09-26.

Änderungen:

- `GET /api/v1/desktop/products/{id}/snapshot` liefert einen expliziten,
  authentifizierten `v1`-Lesevertrag: Produkt, Varianten, Preise, PrintRules samt
  `print_plan` und Asset-Metadaten. Produktions-PDFs werden weiterhin nicht gestreamt.
- `ProductHubDesktopClient` besitzt ausschließlich diese Leseoperation, prüft die
  Vertragsversion und verwendet den Bearer-Token. `XW_PRODUCT_HUB_DESKTOP_API_URL` und
  `XW_PRODUCT_HUB_DESKTOP_API_TOKEN` sind als Desktop-Konfiguration dokumentiert.
- Die vorhandene PrintRule-Ausgabe enthält nun auch den bestehenden `print_plan`.
  Die PySide-Ansicht bleibt bis T04 auf dem Legacy-Pfad; es gab keine UI-Umschaltung und
  keinen Desktop-Providerwrite.

Tests:

- `python -m pytest tests/unit/test_product_hub_web_api.py tests/unit/test_product_hub_desktop_client.py -q` → 21 bestanden; eine bekannte Starlette/httpx-Deprecation-Warnung.
- Der Integrationstest leitet den Desktop-Client auf die echte FastAPI-Snapshotroute und
  belegt identische Produkt-UUID sowie Bruttopreis `27.9000`.
- `git diff --check` → ohne Befund.

Commit: `33674bd` (`feat: add desktop product hub read contract`).

Nächster freigegebener Task: **T04 – Migration und Desktop-Umschaltung**.

## T04 – Migration und Desktop-Umschaltung

Status: in Arbeit. Die freigegebene additive Produktionsmigration ist ausgeführt;
die native Druckbrücke über Hub-IDs ist noch nicht implementiert.

Produktionsmigration (2026-09-26):

- Vorheriger Hub-Snapshot lokal unter `.tmp/product_workflow/hub_before_t04.json`
  gesichert (3.25 MB, nicht eingecheckt).
- 170 fehlende `PRINT_PDF`-Metadaten als private `NETWORK_PATH`-Assets und 70 neue
  PrintRules aus eindeutig zugeordneten Legacy-Zeilen ergänzt.
- Wiederholte Vorschau danach: 0 weitere Asset-/Rule-Änderungen, 70 bestehende
  Regeln geschützt; `XW-412.2` und `XW-7501` weiter offen.
- `inventory.products` sowie externe Provider blieben unverändert.

Änderungen:

- `apply_legacy_print_migration.py` verlangt ausdrücklich `--apply --yes`, führt nur
  additive Hub-Writes aus und bewahrt vorhandene Regeln sowie Legacy-Settings.
- Bei aktivem `product_hub.catalog_read_enabled` und konfigurierter
  `XW_PRODUCT_HUB_DESKTOP_API_URL` startet PRODUKTE den gemeinsamen Product Hub im
  Systembrowser, ohne Token in URLs zu übergeben. Ohne diese bewusste Einrichtung
  bleibt die bewährte Desktop-Ansicht aktiv.

Tests:

- `python -m pytest tests/unit/test_apply_legacy_print_migration.py tests/unit/test_product_hub_migration_preview.py tests/unit/test_product_hub_web_api.py tests/unit/test_product_hub_desktop_client.py -q` → 26 bestanden; eine bekannte Starlette/httpx-Deprecation-Warnung.
- Der Migrations-Integrationstest beweist Asset-/Rule-Ergänzung und unveränderte
  `inventory.products`-Daten.
- `git diff --check` → ohne Befund.

Offen für T04-Abnahme:

- Konfiguration und manueller Shadow-Vergleich auf jedem Desktop-PC.
- Native Rechnungs-/Druckaktionen müssen Hub-Snapshot und Hub-ID verwenden, bevor
  der Legacy-Katalog als reine Rückfallquelle gilt.
