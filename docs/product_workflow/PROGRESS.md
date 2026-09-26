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

Status: in Arbeit – der schreibgeschützte Preview-Runner ist implementiert und getestet;
der echte Bericht kann ohne eine explizit bereitgestellte Datenbankverbindung nicht
erzeugt werden.

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
allgemeiner Repository-Artefakt eingecheckt. Erst dieser echte Bericht erfüllt die
Abnahme von T02; derzeit ist `DATABASE_URL` im Prozess nicht gesetzt.

Tests:

- `python -m pytest tests/unit/test_product_hub_migration_preview.py tests/unit/test_product_hub_repository.py tests/unit/test_inventory_service_import.py -q` → 40 bestanden.
- Der CLI-Test erstellt eine temporäre SQLite-Datenbank, erzeugt den Bericht und beweist,
  dass `inventory.products` unverändert bleibt.
- `git diff --check` → ohne Befund.
