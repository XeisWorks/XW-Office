# XW Product Hub — Bauplan für Codex 5.6 Luna

**Stand:** 2026-09-16  
**Primärrepo:** `XeisWorks/XW-Office`  
**Sekundärrepo:** `XeisWorks/XW-Flow`  
**Baseline geprüft:** XW-Office `09e3b64c8377c938868f2b939c36bb38d2852cb5`, XW-Flow `86fd0f83fd2a15a23b7e97f430780b0d91ed2504`  
**Architekturstatus:** Entscheidungen bestätigt  

## 0. Zweck dieses Dokuments

Dieses Dokument ist der operative Bauplan für Codex 5.6 Luna. Es übersetzt die bereits freigegebenen Architekturdateien

- `XW_PRODUCT_HUB_DEEP_RESEARCH.md`
- `XW_PRODUCT_HUB_IMPLEMENTATION.yaml`
- `XW_PRODUCT_HUB_DATA_MODEL.yaml`

in eine bewusst kleinteilige Folge von Pull-Request-/Arbeits-Paketen.

Luna soll **niemals den gesamten Product Hub in einem Durchlauf bauen**. Pro Arbeitslauf wird genau **ein PR-Paket** umgesetzt, getestet und dokumentiert. Erst wenn dessen Definition of Done erfüllt ist, wird das nächste Paket begonnen.

---

# 1. Nicht verhandelbare Architekturentscheidungen

Diese Entscheidungen gelten als bestätigt und dürfen von Codex nicht erneut zur Diskussion gestellt oder stillschweigend verändert werden.

1. **PostgreSQL/Product Hub ist der endgültige Master für Produktdaten und Lagerbestand.**
2. **sevdesk und Wix sind Channels**, nicht Masterdatenbanken.
3. In der Übergangsphase darf sevdesk als Bestandsvergleich/Shadow dienen; der Endzustand ist Product-Hub-Master.
4. **Händlerpreise:** zunächst eine gemeinsame Preisliste `B2B_EUR`; das Schema muss spätere händlerspezifische Preislisten ohne strukturelle Migration ermöglichen.
5. **Produktive Druck-PDFs:** nur Netzwerk-/Windows-Pfad plus Healthcheck; kein Browser-Download, kein Public Share, kein Upload in Object Storage in Phase 1.
6. **Variantenmigration:** zuerst verlustfrei 1:1: jede bekannte SKU wird als eigenes Produkt mit Default-Variante übernommen. Erst danach kontrollierte Gruppierung. Keine automatische Fuzzy-Zusammenführung.
7. Bestehende XW-Office-Druck-/Rechnungslogik darf nicht durch einen Big-Bang-Umbau destabilisiert werden.
8. Kein neues externes PIM als zweite Wahrheit.
9. Kein Microservice-Split, Redis oder RabbitMQ ohne nachgewiesenen Bedarf.
10. WebUI = responsive PWA; Desktop bleibt lokaler Print-Agent/Windows-Client.

---

# 2. Bestehenden Code respektieren

## 2.1 Bereits vorhandene Bausteine

Codex muss bestehende Implementierungen zuerst wiederverwenden:

- `src/xw_office/services/products/catalog.py`
- `src/xw_office/services/inventory/service.py`
- `src/xw_office/services/products/print_decision.py`
- `src/xw_office/services/sevdesk/part_client.py`
- `src/xw_office/services/wix/client.py`
- `src/xw_office/services/wix/product_details_client.py`
- `src/xw_office/ui/modules/products/view.py`
- `src/xw_office/bootstrap.py`
- `src/xw_office/core/database.py`
- `src/xw_office/web/app.py`
- Alembic-Migrationen `001` bis aktuell `008`

## 2.2 Bekannte Übergangsschulden

Heute existieren insbesondere:

- `SettingKV["inventory.products"]`
- `SettingKV["inventory.stock_levels"]`
- normalisierte `product`-/`inventory_movement`-Tabellen aus Migration 002, die operativ noch nicht vollständig genutzt werden
- ältere Dokumentation mit der überholten Aussage `sevDesk = SOT für Bestand`
- `ProductCatalogService`, der konzeptionell kanonisch ist, aber noch Settings-/In-Memory-basiert arbeitet
- `InventoryService`, der noch JSON-Bestände liest

Diese Übergangspfade werden schrittweise verdrängt, nicht sofort gelöscht.

---

# 3. Luna-Arbeitsregeln

Vor jedem PR muss Codex:

1. `git status --short` prüfen.
2. aktuellen `main`-Stand lesen und relevante Dateien erneut öffnen.
3. dieses Dokument plus Datenmodell-/Implementierungs-YAML lesen.
4. bestehende Tests zum betroffenen Bereich identifizieren.
5. nur den Scope des aktuellen PR bearbeiten.
6. vor Migrationen die aktuelle Alembic-Head-Revision feststellen; niemals hart `009` annehmen, falls inzwischen weitere Migrationen existieren.

Während jedes PR:

- keine fremden Nebenbaustellen refactoren;
- keine bereits angewendeten Migrationen 002/003 umschreiben;
- additive Migrationen bevorzugen;
- externe Wix-/sevdesk-Schreiboperationen standardmäßig deaktiviert lassen, bis der jeweilige PR dies ausdrücklich erlaubt;
- Geldwerte nur `Decimal`/`Numeric`, niemals `float`;
- UUIDs intern, externe IDs nur Mapping;
- Zeitzonenfähige Timestamps;
- Core-Relationen nicht als JSON verstecken;
- idempotente Imports/Commands vorsehen;
- kritische Updates mit optimistic locking/version fields schützen;
- jede neue Business-Logik mit Tests absichern.

Nach jedem PR muss Codex mindestens ausführen:

```bash
python -m pytest
python -m ruff check src tests
python -m mypy src/xw_office
```

Falls die Gesamtsuite bereits bekannte Altfehler enthält, muss Codex:

- die betroffenen gezielten Tests erfolgreich ausführen,
- Altfehler klar von neu eingeführten Fehlern unterscheiden,
- keine bestehenden Fehler verschleiern.

---

# 4. Feature-Flags für sichere Migration

Früh einführen und bis PR16 behalten:

- `product_hub.catalog_read_enabled`
- `product_hub.catalog_write_enabled`
- `product_hub.sync_push_enabled`
- `product_hub.inventory_shadow_enabled`
- `product_hub.inventory_master_enabled`
- `product_hub.shared_catalog_enabled`

Bevorzugt als zentral typisierte Settings/Config mit sicheren Defaults. Produktionsdefault bis zum jeweiligen Cutover:

- Reads: schrittweise aktivierbar
- Writes: aus
- Sync Push: aus
- Inventory Shadow: aus/gezielt aktivierbar
- Inventory Master: **aus bis PR15**

Kein Feature-Flag darf Sicherheitsprüfungen umgehen.

---

# 5. Ziel-Paketstruktur

Empfohlene neue/erweiterte Bereiche:

```text
src/xw_office/
  models/
    product_hub.py
  repositories/
    product_hub.py
    product_hub_import.py
    inventory_v2.py
    sync.py
  services/
    product_hub/
      __init__.py
      catalog_service.py
      import_service.py
      matching.py
      readiness.py
      asset_health.py
      editions.py
      shared_catalog.py
    sync/
      outbox.py
      wix_product_sync.py
      sevdesk_product_sync.py
      reconcile.py
    inventory_v2/
      service.py
      alerts.py
      xw_flow_client.py
  web/
    routers/
      products.py
      imports.py
      sync.py
      inventory.py
      shared_catalog.py
    schemas/
      products.py
      imports.py
      sync.py
      inventory.py
  migrations/versions/
    <next>_product_hub_*.py

web/product-hub/               # nur falls Frontend getrennt vom Python-Paket geführt wird
  package.json
  src/
```

Codex darf die Dateiaufteilung an bestehende Repo-Konventionen anpassen. Die fachlichen Grenzen müssen jedoch erhalten bleiben.

---

# 6. PR-Reihenfolge

## PR00 — Dokumentation und Guardrails angleichen

### Ziel
Das Repo darf keine widersprüchlichen Architekturvorgaben mehr enthalten.

### Ändern

- `docs/product_pipeline_masterplan.md`
- `docs/product_pipeline_phases.yaml`
- neue Repo-Kopie der drei freigegebenen Spezifikationen unter z. B. `docs/product_hub/`
- optional `docs/product_hub/CODEX_BUILD_PLAN.md` = dieses Dokument

### Muss geändert werden

- alte Aussage `sevDesk = Single Source of Truth für Bestand` als historische Entscheidung kennzeichnen/ersetzen;
- Endzustand: Product Hub Master;
- Produktion-PDF = Network Path + Healthcheck;
- gemeinsame B2B-Preisliste jetzt, spezifische später möglich;
- sichere 1:1-Variantenmigration vor Gruppierung;
- Cutover-Phasen sichtbar machen.

### Nicht tun

- keine Runtime-Änderung;
- keine DB-Migration.

### Definition of Done

- keine zentrale Doku widerspricht den bestätigten Entscheidungen;
- Links zwischen Masterplan, Data Model, Implementation Plan und diesem Bauplan vorhanden.

---

## PR01 — Kanonisches SQLAlchemy-Datenmodell + Repository-Layer

### Ziel
Die bereits vorhandenen Tabellen werden zu einer echten ORM-/Repository-Schicht ausgebaut. Noch keine produktiven Channel-Writes.

### Migration
Neue additive Alembic-Migration ab aktuellem Head.

### Bestehende `product`-Tabelle
Nicht löschen. Additiv erweitern um benötigte Parent-Felder wie:

- slug
- short_description
- description
- product_type
- active
- release_date
- attributes JSONB
- row_version
- archived_at
- ggf. family_id nach Anlage von `product_family`

Das bestehende `product.sku` bleibt **vorübergehend als Legacy-Kompatibilitätsfeld** bestehen und spiegelt in der Bridge die Default-Variante. Es wird erst PR16 entfernt oder entkoppelt.

### Neue Kernobjekte
Mindestens:

- `product_family`
- `product_variant`
- Erweiterung/Bridge `product_sku_alias` -> Variante
- `product_identifier`
- `category`
- `product_category`
- `tag`
- `product_tag`
- `price_list`
- `product_price`
- `product_asset`
- `print_rule`
- `product_edition`
- `product_improvement`
- `channel_mapping`
- `channel_category_mapping`
- `audit_log`

### Initiale Seeds

- Preislisten `RETAIL_EUR`, `B2B_EUR`
- zentrale Tags nur wenn konfliktfrei; ansonsten separater Seed-Service

### Backfill
Für bereits vorhandene `product`-Zeilen:

1. genau eine Default-Variante erzeugen;
2. SKU aus `product.sku` übernehmen;
3. bestehende Wix-/sevdesk-ID in `channel_mapping` spiegeln, ohne Legacy-Spalten zu löschen;
4. `print_file_path` als `product_asset(role=PRINT_PDF, storage_kind=NETWORK_PATH)` spiegeln;
5. Print-Minimum/-Batch in `print_rule` spiegeln.

Backfill muss idempotent oder migrationssicher sein.

### Repository
Neue Repository-APIs, z. B.:

- `get_product(product_id)`
- `get_product_by_sku(sku)`
- `list_products(filters)`
- `create_product(...)`
- `update_product(..., expected_row_version)`
- `resolve_sku(raw_sku)`
- `list_variants(product_id)`
- `list_identifiers(product_id|variant_id)`
- `list_assets(product_id)`

### Tests

- SKU uniqueness/normalization
- one-default-variant constraint
- identifier uniqueness
- optimistic locking
- backfill legacy product -> default variant
- no money float
- migration upgrade on empty DB and representative pre-existing DB

### DoD
ORM + Repository können alle Kernobjekte lesen/schreiben, ohne `inventory.products` zu benötigen.

---

## PR02 — Staging-/Import-Infrastruktur

### Ziel
Externe Daten zunächst sicher einlesen, ohne Masterdaten zu verändern.

### Tabellen

- `import_batch`
- `staging_product`
- `staging_variant`
- `staging_identifier`
- `staging_asset`
- `staging_inventory`
- optional `staging_category`
- `import_match_candidate`

### Anforderungen

Jede Staging-Zeile speichert:

- source (`wix`, `sevdesk`, `excel`)
- external_id/source_key
- raw payload/hash
- normalized business fields
- imported_at
- batch_id
- match status

### Statusmodell

- `unmatched`
- `exact_match`
- `alias_match`
- `identifier_match`
- `suggested_match`
- `conflict`
- `approved`
- `rejected`
- `committed`

### Regel
**Staging darf nie automatisch Masterdaten überschreiben.**

### Tests

- mehrfacher Import desselben Payloads ohne Dubletten
- Batch-Wiederholbarkeit
- Payload Hash
- Rollback bei Fehler

---

## PR03 — Wix Read Importer

### Ziel
Wix vollständig als Read-Quelle in Staging einlesen.

### Wiederverwenden

- `WixProductsClient`
- `WixProductDetailsClient`

### Ergänzen

V3-kompatibel:

1. Products paginieren;
2. vollständige Details;
3. Varianten separat laden;
4. Inventory separat laden;
5. Kategorien laden;
6. Media-Reihenfolge bewahren.

### Media-Regel

- erstes Wix-Medium -> `COVER`
- weitere Medien -> `SAMPLE_SCORE`
- Wix media id/url/order als Provenance speichern

### Wichtig
Query Products allein reicht nicht für Varianten. Varianten werden explizit separat importiert.

### Keine Writes
Dieser PR darf Wix **nicht** verändern.

### Tests
Fixtures für:

- Produkt ohne Varianten
- Produkt mit mehreren Varianten
- Produkt ohne Media
- 1 Cover + mehrere Samples
- revision vorhanden
- Paging >100
- Inventory variant-basiert

---

## PR04 — sevdesk Read Importer

### Ziel
sevdesk Parts/Kategorien/Bestand nach Staging importieren.

### Wiederverwenden
`PartClient`.

### Mappen

- `partNumber` -> SKU
- Part id -> channel external id
- Name
- Preiswerte
- Steuersatz
- stock / stockEnabled
- Kategorie ID/name
- internal comment nur intern/provenance, nicht ungeprüft als öffentliche Beschreibung

### Kategorien
Interne Kategorien bleiben separat. Eine sevdesk-Kategorie wird über `channel_category_mapping` zugeordnet.

### Keine Writes
Noch kein sevdesk Update.

### Tests

- physical/digital (`stockEnabled`)
- category mapping
- empty SKU fallback nur in Staging, nicht automatisch als finale SKU
- stock parsing

---

## PR05 — Excel Import + Matching Engine

### Ziel
`Produktpalette.xlsx` strukturiert importieren und mit Wix/sevdesk/Stamm abgleichen.

### Matching-Reihenfolge

1. existierende `channel_mapping.external_id`
2. exakte normalisierte SKU
3. SKU alias
4. eindeutiger Identifier (ISBN/EAN/ASIN/...)
5. Fuzzy Name nur als **Vorschlag**, niemals Auto-Merge

### Excel-spezifisch

- Produktpalette-Blatt als Produkt-/Preisquelle
- Amazon-Blatt als Identifier-Quelle
- Händler-Blatt nur kontrolliert als Händler-/Preisreferenz
- doppelte `netto`-Spalten nicht blind übernehmen; als Importwarnung markieren, wenn Semantik nicht eindeutig

### Variantenregel
Alle bekannten SKUs zunächst 1:1 als eigene Produkte/Default-Varianten behandeln.

### Output
Import-Review-Bericht mit:

- exact matches
- suggested matches
- duplicates
- identifier conflicts
- title drift
- price ambiguity
- missing fields

---

## PR06 — Import Commit Service + kontrollierte Produktgruppierung

### Ziel
Freigegebene Staging-Daten atomar in den Hub übernehmen.

### Commands

- approve_match
- reject_match
- create_from_staging
- commit_import_batch
- group_products_into_parent
- move_variant_to_product

### Sicherheitsregeln

- Commit transaktional;
- wiederholter Commit idempotent;
- keine Fuzzy-Vorschläge automatisch übernehmen;
- bei Identifier-/SKU-Konflikt abbrechen;
- Audit-Log schreiben.

### Gruppierung
Erst **nach** verlustfreiem 1:1-Import.

MusikHeroes und andere logisch zusammengehörige SKUs dürfen anschließend manuell/regelbasiert kuratiert gruppiert werden. Jede Gruppierung muss Preview + Diff anzeigen und reversibel/auditierbar sein.

---

## PR07 — Product Hub Read API

### Ziel
Stabile read-only API für Desktop und zukünftige WebUI.

### Router
Empfohlen:

- `GET /api/v1/products`
- `GET /api/v1/products/{id}`
- `GET /api/v1/products/by-sku/{sku}`
- `GET /api/v1/products/{id}/variants`
- `GET /api/v1/products/{id}/assets`
- `GET /api/v1/products/{id}/improvements`
- `GET /api/v1/products/{id}/channels`
- `GET /api/v1/products/{id}/audit`
- `GET /api/v1/catalog/readiness-summary`

### Filter

- search
- status
- active
- family
- category
- tag
- channel state
- readiness
- low-stock später

### API-Regeln

- Pydantic Response Models
- Pagination
- keine ORM-Objekte ungefiltert serialisieren
- keine privaten Network Paths in Händler-/Public-Schemas
- `row_version` für editierbare interne Responses mitsenden

### Auth
Bootstrap-Token ist nur Übergang. Internen API-Auth-Layer so kapseln, dass später User Sessions/Rollen ergänzt werden können.

---

## PR08 — Read-only WebUI/PWA

### Ziel
Produktdaten auf Windows, Android und iOS lesbar machen, ohne bereits Masterdaten im Browser zu ändern.

### Stack

- React
- TypeScript
- Vite
- PWA

### Ansichten

1. Dashboard
2. Produktliste
3. Produktdetail
4. Sync-Status readonly
5. Asset-/Print-Health readonly

### Produktliste
Spalten:

- Cover
- SKU
- Name
- Kategorie
- Tags
- ISBN
- Retail Preis
- B2B Preis
- Bestand (zunächst Shadow/Anzeige)
- Wix Status
- sevdesk Status
- Readiness
- geändert am

### PWA
- responsive
- installierbar
- keine Offline-Masterwrites in erster Version

### Nicht tun
Keine Web-Downloads produktiver PRINT_PDFs.

---

## PR09 — Edit API + WebUI Editing + Verbesserungen/Auflagen

### Ziel
Product Hub wird echte Produktpflegeoberfläche.

### Editierbar

- Stammdaten
- Beschreibungen
- Preise
- Kategorien
- Tags
- Identifier
- Assets-Metadaten
- Print-Regeln
- Verbesserungen

### Optimistic Locking
PATCH/PUT erfordert erwartete `row_version`; Konflikt -> HTTP 409 mit aktuellem Serverstand.

### Verbesserungen
UI darf einfach wirken: `+ Verbesserung hinzufügen`, intern aber separate Records.

Felder:

- description
- source
- source_reference
- severity
- status
- resolved_in_edition_id

### Neue Auflage
Service für:

- neue `product_edition`
- offene Verbesserungen zuordnen
- optional später XW-Flow Task triggern

---

## PR10 — Transactional Outbox + Sync-Grundgerüst

### Ziel
Robuste Channel-Writes vorbereiten, ohne Business-Transaktion und HTTP-Aufruf zu koppeln.

### Tabellen

- `outbox_event`
- `sync_job`
- `sync_item`
- `sync_conflict`
- `sync_cursor`
- `external_payload_archive`

### Outbox-Regel
Business-Änderung + Outbox Event in **derselben DB-Transaktion**.

Worker verarbeitet danach extern.

### Eventtypen Beispiele

- product.created
- product.updated
- price.changed
- asset.changed
- inventory.changed
- edition.created

### Retry

- bounded exponential backoff
- attempt count
- last_error
- next_attempt_at
- dead/error state sichtbar

---

## PR11 — Wix Push + Reconcile + Konfliktmanagement

### Ziel
Wix wird kontrolliert synchronisierter Channel.

### Ownership
Hub ist Master für definierte Felder.

### Push
Nur wenn `product_hub.sync_push_enabled=true`.

### Wix optimistic concurrency
Bei V3 Revision immer aktuelle Revision verwenden.

### Drift/Reconcile
Wenn Wix manuell verändert wurde:

- nicht silent überschreiben;
- `sync_conflict` erzeugen;
- UI zeigt Hub vs Wix;
- Aktionen: `keep_hub_and_push`, `accept_external`, `ignore_once` nur wo sinnvoll.

### Media
Hub-Metadaten respektieren:

- COVER zuerst
- Samples danach

### Tests
409/revision conflict, retry, idempotency, disabled push.

---

## PR12 — Händlerfreigabe + CSV/XLSX Export

### Ziel
Live gefilterte B2B-Produktansicht per Link.

### Tabelle
`shared_catalog_view` plus `export_log`.

### Sicherheit

- opaque high-entropy token
- nur Token-Hash in DB
- revoke
- optional expiry/password später
- serverseitige Field Whitelist
- rate limiting

### Standardfilter

- tag B2B
- product.status=live
- active=true

### Standardfelder

- Cover
- SKU
- ISBN
- Name
- Besetzung/Description
- UVP
- B2B-Preis aus `B2B_EUR`
- Verfügbarkeit

### Niemals öffentlich

- `NETWORK_PATH`
- PRINT_PDF
- Verbesserungen
- interne Kommentare
- Einkaufskosten
- API IDs
- raw payloads
- Sync-Debugdaten

### Routen

- `/share/{token}`
- `/share/{token}/export.csv`
- `/share/{token}/export.xlsx`

HTML/CSV/XLSX verwenden **dieselbe serverseitige Query**, damit keine Unterschiede entstehen.

---

## PR13 — Inventory V2 Shadow Mode

### Ziel
Hub-Lagerledger aufbauen, noch ohne finalen Master-Cutover.

### Tabellen

- `inventory_location`
- `inventory_stock`
- erweiterte `inventory_movement`
- `inventory_alert`

### Ledger
Jede Änderung append-only:

- delta
- reason
- source
- external_ref
- idempotency_key
- on_hand_after
- actor
- timestamp

### Shadow Mode

- sevdesk-Bestand regelmäßig lesen;
- Hub-Bestand berechnen;
- Drift erfassen;
- noch keine automatische externe Korrektur.

### Alle XW-Office-Bestandswege inventarisieren
Insbesondere:

- START/Druck
- REPRINTS
- Rechnungs-Fulfillment
- manuelle Korrektur
- Retouren
- Recount
- `PrintDecisionEngine` direkte PartClient-Nutzung

### Bridge
Bestehende `InventoryService`-Aufrufer dürfen zunächst weiterlaufen, sollen aber hinter einer gemeinsamen Inventory-Port-Schnittstelle liegen.

---

## PR14 — Lagerwarnungen + XW-Flow Integration

### Ziel
Schwellwertüberschreitung erzeugt genau eine XW-Flow Pipeline-Aufgabe.

### Trigger
Nur bei Crossing:

```text
before > threshold AND after <= threshold
```

### Dedupe
Solange ein Alert offen ist, keine neue Aufgabe.

Wenn Bestand wieder > threshold:

- Alert resolved.

Bei späterem erneutem Crossing:

- neuer Alert erlaubt.

### XW-Flow Task

- title: `Nachdruck: <SKU> – <Produktname>`
- description: Lagerwarnung
- notes: Bestand, Schwelle, Zielbestand, offene Verbesserungen
- `planning_mode=PIPELINE`
- `external_entity_type=inventory_alert`
- `external_entity_id=<alert uuid>`
- `external_deep_link=<Product Hub Product URL>`
- `client_request_id=UUID5(<namespace>, <alert uuid>)`

### Product Hub Endpoint für XW-Flow Tile

`GET /api/v1/inventory/summary`

Response mindestens:

- physical_products
- low_stock
- out_of_stock
- open_reprint_alerts
- sync_errors
- updated_at

### Neue Auflage
Button/Command kann ebenfalls PIPELINE-Task erzeugen, mit offenen Verbesserungen im Text.

---

## PR15 — Inventory Cutover: Product Hub wird Master

### Ziel
Bestätigte Architekturentscheidung produktiv aktivieren.

### Vorbedingungen — alle müssen erfüllt sein

1. alle bekannten Bestandsänderungspfade laufen durch Inventory V2;
2. Shadow Mode über repräsentativen Zeitraum ohne ungeklärte Drift;
3. sevdesk-/Hub-Bestände reconciled;
4. Backups vorhanden;
5. Rollback-Schalter getestet;
6. keine kritischen Sync-Fehler offen;
7. Inventory-Movement-Idempotency getestet;
8. Druckpfad verwendet Hub-Bestand;
9. Wix-/sevdesk-Projektionen getestet.

### Aktivierung
`product_hub.inventory_master_enabled=true`

### Danach

- Hub Ledger/Stock ist kanonisch;
- sevdesk stock = Projektion;
- Wix inventory = Projektion;
- externe manuelle Abweichung -> Drift/Conflict, nicht Master-Overwrite.

### Rollback
Feature Flag zurück auf false darf kurzfristig Leseverhalten zurückschalten, aber bereits erfasste Ledger-Movements niemals löschen.

---

## PR16 — Legacy JSON entfernen

### Ziel
Erst jetzt technische Altlasten beseitigen.

### Entfernen/migrieren

- Runtime Reads/Writes von `inventory.products`
- Runtime Reads/Writes von `inventory.stock_levels`
- doppelte Produkt-SKU-/Bestandslogik
- Legacy-Felder nur wenn wirklich keine Consumer mehr existieren

### Daten
Vor Entfernung finalen Snapshot archivieren.

### `product.sku`
Nur dann physisch entfernen, wenn:

- jeder Consumer Varianten-SKU nutzt;
- alle Abfragen migriert sind;
- Tests beweisen, dass Multi-Variant-Produkte funktionieren.

Ansonsten als deprecated compatibility mirror belassen und Folge-PR planen.

### DoD Gesamtprojekt

- Product Hub = einzige fachliche Masterquelle;
- XW-Office Desktop nutzt zentrale Repositories/Services;
- WebUI/PWA funktioniert;
- Wix/sevdesk sind synchronisierte Channels;
- Händlerlink/Exports funktionieren;
- Print-Pfade haben Healthcheck, sind nicht öffentlich;
- Inventory-Ledger ist kanonisch;
- XW-Flow erhält deduplizierte Lager-/Auflagen-Tasks;
- kein produktiver Pfad benötigt die beiden alten Inventory-JSON-Blobs.

---

# 7. Channel Readiness

Frühestens ab PR07 berechnen, ab PR08 anzeigen.

## Wix-ready

- SKU
- Name
- Retail-Preis
- Cover
- Beschreibung
- Wix-Kategorie-Mapping

## B2B-ready

- B2B Tag
- SKU
- Name
- B2B Preis
- Cover
- Beschreibung
- ISBN falls für Produktfamilie erforderlich

## Print-ready

- PRINT_PDF Asset vom Typ NETWORK_PATH
- Health = `ok`
- Print Rule vorhanden
- Profil/Plan verfügbar

## sevdesk-ready

- SKU
- Name
- Kategorie-Mapping
- Steuersatz
- Einheit

Readiness soll Prozent + konkrete Missing Reasons liefern.

---

# 8. Print-Asset-Healthcheck

Da PRINT_PDFs nicht über das Web ausgeliefert werden, braucht es einen lokalen/desktopnahen Healthcheck.

Prüfungen:

- Pfad nicht leer
- Pfad auf aktuellem Windows/Netzwerk-Host erreichbar
- Datei vorhanden
- lesbar
- `.pdf`
- optional Größe/mtime/checksum

Status:

- unknown
- ok
- missing
- unreadable
- checksum_mismatch
- stale

Wichtig: Ein Railway-Webworker kann lokale Windows-/SMB-Pfade evtl. nicht erreichen. Deshalb Healthcheck-Ausführung als Capability behandeln:

- Desktop Agent kann lokal prüfen und Ergebnis/checked_at an Hub melden;
- Webserver zeigt letzten bekannten Health-Status;
- niemals aus `missing` schließen, wenn der prüfende Host den Share grundsätzlich nicht mounten kann.

---

# 9. API-/Security-Leitplanken

## Intern

Rollen später mindestens:

- admin
- editor
- viewer
- service

## Service Tokens
Getrennte Credentials für:

- XW-Office Desktop
- Worker
- XW-Flow

## Public Share
Public Endpoints dürfen niemals dasselbe Response-Schema wie interne Product-Endpoints ungefiltert wiederverwenden.

## Audit
Mindestens protokollieren:

- wer
- wann
- Entity/ID
- Operation
- vorher/nachher oder Diff
- source/client

---

# 10. Codex-Startprompt für jeden neuen PR

Diesen Prompt mit der gewünschten PR-Nummer verwenden:

```text
Arbeite im Repo XeisWorks/XW-Office.

Lies zuerst vollständig:
1. docs/product_hub/XW_PRODUCT_HUB_DEEP_RESEARCH.md
2. docs/product_hub/XW_PRODUCT_HUB_IMPLEMENTATION.yaml
3. docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml
4. docs/product_hub/XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md

Setze ausschließlich PRXX aus dem Bauplan um.

Regeln:
- Prüfe vor Änderungen den aktuellen main-Stand und git status.
- Lies die bestehenden Implementierungen, bevor du neue Services/Modelle anlegst.
- Keine Big-Bang-Refactors und keine Arbeit aus späteren PRs vorziehen.
- Bestehende Migrationen niemals rückwirkend umschreiben; neue additive Alembic-Migration ab aktuellem Head.
- Wix/sevdesk Writes bleiben deaktiviert, sofern PRXX sie nicht ausdrücklich einschaltet.
- Bestehende Druck-/Rechnungsfunktionen müssen kompatibel bleiben.
- Schreibe/aktualisiere Tests für jede neue Business-Regel.
- Führe gezielte Tests sowie pytest, ruff und mypy aus.
- Wenn bestehende Altfehler die Gesamtsuite blockieren, dokumentiere sie klar und beweise, dass deine geänderten Bereiche grün sind.
- Keine Fuzzy-Matches automatisch committen.
- Product Hub ist der endgültige Inventory Master; sevdesk ist nach Cutover nur Projektion.
- PRINT_PDF bleibt NETWORK_PATH + Healthcheck und darf nicht im Browser ausgeliefert werden.

Am Ende antworte mit:
1. Kurzfassung der Änderungen
2. Liste aller geänderten/neu angelegten Dateien
3. DB-Migrationswirkung
4. ausgeführte Tests + Ergebnis
5. offene Risiken/TODOs, ausschließlich innerhalb PRXX
6. klare Aussage, ob die Definition of Done von PRXX erfüllt ist

Wenn die Definition of Done nicht vollständig erfüllt werden kann, stoppe beim sicheren Teil und erkläre präzise, was fehlt. Beginne nicht mit PRXX+1.
```

---

# 11. Spezieller Startprompt für PR01

```text
Setze PR01 „Kanonisches SQLAlchemy-Datenmodell + Repository-Layer“ aus dem XW Product Hub Bauplan um.

Bevor du codest:
- ermittle die aktuelle Alembic-Head-Revision;
- prüfe, welche Tabellen/Spalten aus 002/003 real existieren;
- prüfe src/xw_office/models/__init__.py, core/database.py und Repository-Konventionen;
- suche alle Consumer von product.sku, product_sku_alias, inventory.products und inventory.stock_levels;
- ändere diese Consumer in PR01 noch nicht großflächig; dokumentiere sie für spätere PRs.

Migration muss additiv und rückwärtskompatibel sein.
Die bestehende product-Tabelle bleibt bestehen.
Für jede bestehende product-Zeile wird eine Default-Variante vorbereitet/backfilled.
Legacy product.sku, wix_product_id, sevdesk_part_id, print_file_path, min_stock_target und reprint_batch_qty bleiben vorerst kompatibel und werden in die neuen Strukturen gespiegelt.

Schreibe keine Wix-/sevdesk-Daten.
Ändere noch keine Produkt-WebUI.
Ändere noch keine Inventory-Masterlogik.
```

---

# 12. Review-Checkliste nach jedem PR

- [ ] Scope nur aktueller PR
- [ ] keine unbeabsichtigten externen Writes
- [ ] Migration upgrade getestet
- [ ] downgrade zumindest strukturell geprüft, sofern sicher sinnvoll
- [ ] neue Constraints getestet
- [ ] idempotency getestet, wo relevant
- [ ] Audit/Conflict-Verhalten getestet, wo relevant
- [ ] Ruff sauber für geänderte Dateien
- [ ] Mypy sauber für geänderte Dateien
- [ ] Pytest relevante Suite grün
- [ ] Dokumentation aktualisiert
- [ ] keine Secrets/Payloads/Network Paths in Public API
- [ ] kein produktiver PRINT_PDF Download eingeführt
- [ ] keine Fuzzy-Auto-Merges
- [ ] keine doppelte neue SSOT geschaffen

---

# 13. Empfohlene Branch-/Commit-Namen

- `feat/product-hub-pr00-docs`
- `feat/product-hub-pr01-schema`
- `feat/product-hub-pr02-staging`
- `feat/product-hub-pr03-wix-import`
- `feat/product-hub-pr04-sevdesk-import`
- `feat/product-hub-pr05-excel-matching`
- `feat/product-hub-pr06-import-commit`
- `feat/product-hub-pr07-read-api`
- `feat/product-hub-pr08-web-readonly`
- `feat/product-hub-pr09-editing`
- `feat/product-hub-pr10-outbox`
- `feat/product-hub-pr11-wix-sync`
- `feat/product-hub-pr12-b2b-share`
- `feat/product-hub-pr13-inventory-shadow`
- `feat/product-hub-pr14-xw-flow-alerts`
- `feat/product-hub-pr15-inventory-cutover`
- `refactor/product-hub-pr16-remove-legacy-json`

---

# 14. Reihenfolge, die nicht übersprungen werden soll

```text
PR00
 ↓
PR01
 ↓
PR02
 ├─ PR03 Wix Import
 ├─ PR04 sevdesk Import
 └─ PR05 Excel/Matching
          ↓
        PR06
          ↓
        PR07
          ↓
        PR08
          ↓
        PR09
          ↓
        PR10
          ↓
        PR11
          ↓
        PR12
          ↓
        PR13
          ↓
        PR14
          ↓
        PR15
          ↓
        PR16
```

PR03–PR05 können technisch teilweise parallel entwickelt werden, aber für Luna ist **sequenziell** vorzuziehen, damit der Kontext klein und die Fehlerursache eindeutig bleibt.

---

# 15. Wichtigster Grundsatz für Codex Luna

**Bestehende Businesslogik zuerst verstehen, dann kapseln, dann migrieren, erst zuletzt löschen.**

Der Product Hub ist kein zweites Produktmodul neben dem alten. Er ist die schrittweise Normalisierung und Zentralisierung der bereits vorhandenen XW-Office-Produktpipeline.
