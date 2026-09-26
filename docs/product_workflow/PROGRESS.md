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

Status: erledigt am 2026-09-26. Die freigegebene additive Produktionsmigration und
die native Hub-zu-Druck-Brücke sind implementiert; pro PC ist nur noch die bewusste
Konfiguration und Sichtprüfung erforderlich.

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
- Der bestehende `ProductCatalogService` liest bei aktivem Flag zuerst den
  versionierten Hub-Snapshot (Hub-ID, Variante, private Pfadmetadaten, PrintRule,
  Druckprofil und -plan). Netzwerk-/Vertragsfehler fallen kontrolliert auf den lokalen
  Legacy-Snapshot zurück; titelbezogene Alt-Konfigurationen bleiben erhalten.

Tests:

- `python -m pytest tests/unit/test_apply_legacy_print_migration.py tests/unit/test_product_hub_migration_preview.py tests/unit/test_product_hub_web_api.py tests/unit/test_product_hub_desktop_client.py -q` → 26 bestanden; eine bekannte Starlette/httpx-Deprecation-Warnung.
- Der Migrations-Integrationstest beweist Asset-/Rule-Ergänzung und unveränderte
  `inventory.products`-Daten.
- `git diff --check` → ohne Befund.

Einrichtung pro Desktop-PC:

```text
XW_PRODUCT_HUB_CATALOG_READ_ENABLED=true
XW_PRODUCT_HUB_DESKTOP_API_URL=https://<dein-Content-Web-Service>
XW_PRODUCT_HUB_DESKTOP_API_TOKEN=<bestehender Bootstrap-Token>
```

Produktiv eingerichtet (2026-09-26):

- Das Windows-Benutzerprofil dieses Arbeits-PCs hat die drei Desktop-Variablen gesetzt;
  der API-Token wurde ausschließlich direkt aus Railway bezogen und weder ausgegeben noch
  im Repository hinterlegt.
- `https://products.xeisworks.at/health` sowie ein authentifizierter Hub-API-Aufruf wurden
  mit HTTP 200 verifiziert.
- Weitere Desktop-PCs benötigen dieselbe lokale Konfiguration in ihrem jeweiligen
  Benutzerprofil. Der Web-Service selbst benötigt diese Desktop-Variablen nicht.

Danach PRODUKTE öffnen, einen bekannten Druckauftrag gegen den Hub-Snapshot prüfen und
bei einem Problem nur `XW_PRODUCT_HUB_CATALOG_READ_ENABLED=false` setzen. Dadurch wird
ohne Doppelpflege auf den bisherigen lokalen Katalog zurückgeschaltet.

Offen für T04-Abnahme:

- Manueller Shadow-Vergleich auf jedem weiteren Desktop-PC.
- Native Rechnungs-/Druckaktionen müssen Hub-Snapshot und Hub-ID verwenden, bevor
  der Legacy-Katalog als reine Rückfallquelle gilt.

## T05 – Entwurf, Optionen und Preise modellieren

Status: erledigt am 2026-09-27. Der Hub besitzt jetzt eine additive, dauerhafte
Wizard-Draft-Schicht; sie erstellt weder Produktstammdaten noch Provider-Einträge.

- `product_draft` speichert Schritt, Schema-Version, abgeschlossene Schritte, Eingabedaten
  und `row_version`. Autosave verwendet eine erwartete Version; ein veralteter Stand erhält
  HTTP 409 mit dem aktuellen vollständigen Entwurf.
- `product_draft_option` modelliert Option und erlaubte Werte. `product_draft_variant`
  speichert ausschließlich bewusst ausgewählte Kombinationen samt SKU, Brutto-EUR-Preis,
  Steuer und eigener Versionsnummer. Es wird kein kartesisches Produkt erzeugt.
- Die authentifizierte API kann Entwürfe anlegen, laden und versioniert speichern sowie
  Optionen/Kombinationen hinzufügen. Die SKU-Verfügbarkeit prüft Varianten und Aliase in
  einer DB-Transaktion; ein freier Vorschlag reserviert nichts.
- Migration `018_product_wizard_drafts` ist additiv und hängt an Alembic-Head 017.

Tests:

- `python -m pytest tests/unit/test_product_hub_drafts.py -q` → 2 bestanden.
- `python -m ruff check ...` → ohne Befund.
- `python -m alembic heads` → `018_product_wizard_drafts (head)`.
- Migration von Produktionsrevision 016 auf ein frisches SQLite-Testschema → Revision 017 und
  drei Draft-Tabellen vorhanden; die historische `alembic_version`-Breite wird vor Revision 017
  auf PostgreSQL kompatibel erweitert.

Nächster freigegebener Task: **T06 – Vorlagen und Kopieren**.

## T06 – Vorlagen und Kopieren

Status: erledigt am 2026-09-27. Drei Startvorlagen (Mnozil-Einzeltitel,
MusikHeroes-Heft, Zusatzstimme) stehen über die Draft-API bereit. Ein Produkt kann
als isolierter Entwurf kopiert werden: neue Draft-UUID und editierbare `-COPY`-SKU-
Vorschläge, Texte/Optionen/Variantenpreise übernommen, aber keine Provider-IDs,
Mappings, Bestände, ASINs oder Audit-Historie. Asset-Referenzen werden nur aus einer
expliziten Auswahl übernommen; ein Cover ist stets als neu zu erzeugen markiert.

Test: `python -m pytest tests/unit/test_product_hub_drafts.py -q` → 3 bestanden.

Nächster freigegebener Task: **T07 – Gemeinsame Wizard-Oberfläche**.
