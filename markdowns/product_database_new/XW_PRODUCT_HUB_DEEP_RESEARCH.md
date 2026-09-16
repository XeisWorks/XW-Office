# XW Product Hub — Deep Research & Zielarchitektur

**Stand:** 2026-09-16  
**Scope:** XeisWorks/XW-Office, Produktpalette.xlsx, Wix Stores, sevdesk, XW-Flow  
**Ziel:** Eine zentrale, webfähige Produktdatenbank als Single Source of Truth (SSOT), die XW-Office, Wix, sevdesk, Händlerfreigaben und XW-Flow verbindet.

---

## 1. Executive Summary

### Empfehlung in einem Satz

Baue **keine zweite SaaS-Datenbank neben XW-Office**, sondern entwickle den bereits vorhandenen PostgreSQL-/FastAPI-Unterbau von `XeisWorks/XW-Office` zum **XW Product Hub** weiter: PostgreSQL wird die kanonische Produktquelle, eine responsive WebUI/PWA macht sie auf Windows/Android/iOS nutzbar, Wix und sevdesk werden synchronisierte Channels, XW-Flow konsumiert eine stabile API für Inventar und Tasks.

### Warum diese Richtung

- Im Repo ist bereits ein sinnvoller Produkt-Pipeline-Entwurf vorhanden.
- PostgreSQL auf Railway ist bereits Bestandteil der XW-Office-Architektur.
- Alembic-Migrationen für `product`, SKU-Aliase, Bestandsbewegungen und Druckpläne existieren bereits.
- FastAPI ist im Repo bereits als Web-Fundament vorhanden.
- sevdesk-Part- und Wix-Clients existieren bereits.
- Der heutige Engpass ist nicht fehlende Technik, sondern dass Produktdaten noch teilweise als JSON in `SettingKV` liegen und Bestand parallel in mehreren Quellen geführt wird.
- Ein externes PIM wie Pimcore/Akeneo wäre für den jetzigen Umfang und die sehr individuellen Druck-/sevdesk-/Wix-/XW-Flow-Prozesse unnötig schwergewichtig.

### Zielbild

```text
                           ┌─────────────────────────┐
                           │     XW Product Hub      │
                           │ PostgreSQL = Master DB  │
                           └───────────┬─────────────┘
                                       │
             ┌─────────────────────────┼───────────────────────────┐
             │                         │                           │
       ┌─────▼─────┐             ┌─────▼─────┐             ┌──────▼──────┐
       │ WebUI/PWA │             │ XW-Office │             │   XW-Flow   │
       │ iOS/Win/  │             │ Desktop   │             │ Inventar +  │
       │ Android   │             │ Drucken   │             │ Tasks       │
       └───────────┘             └───────────┘             └─────────────┘
             │
    ┌────────┼─────────┐
    │                  │
┌───▼────┐         ┌───▼──────┐
│  Wix   │         │ sevdesk  │
│ Shop   │         │ Artikel  │
└────────┘         └──────────┘

Zusätzlich:
- Objekt-Storage für Webbilder/Exports
- Netzwerk-/Windows-Pfade für produktive Druck-PDFs
- öffentliche, tokenisierte Händleransichten
- CSV/XLSX-Exports
- Audit-/Sync-/Konfliktprotokoll
```

---

## 2. Analyse des heutigen Stands

## 2.1 Excel `Produktpalette.xlsx`

Die Datei ist derzeit **kein normalisierter Produktstamm**, sondern eine Sammlung mehrerer zweckgebundener Ansichten.

### Blätter

| Blatt | Bereich | Beobachtung |
|---|---:|---|
| `XeisWorks` | A1:AN132 | breite Produkt-/Sortimentsmatrix mit vielen SKU-Vorkommen |
| `MusikHeroes` | A1:AF65 | breite Serien-/Variantenmatrix |
| `Amazon` | A1:E17 | separate Identifier-Zuordnung für ART.-NR., ASIN, FNSKU, ISBN |
| `Produktpalette` | A1:G138 | kompakte Produkt-/Preisübersicht |
| `Besetzungen` | A1:A10 | Liste von Besetzungsbezeichnungen |
| `Händler` | A1:Y100 | eigene Händlerdarstellung/Preisübersicht |

### `Produktpalette`

- 111 eindeutige Produkt-SKUs.
- Gruppierungen: BLECH7ER, Edition Böhmisch, MusikHeroes, Blech4er, Tanzlmusi.
- Felder: Artikelnummer, Titel, Beschreibung, SKG, brutto, netto, netto.
- Die Preislogik ist nicht eindeutig normalisiert: einzelne Nettozellen werden per Formel aus Brutto berechnet, andere sind fest eingetragen; zwei unterschiedliche Divisoren (`/1.05`, `/1.1`) kommen vor.
- Viele Bruttofelder sind leer, während andere Preisfelder vorhanden sind.

### `Amazon`

- 10 SKU-Zeilen.
- ISBN für alle 10 vorhanden.
- ASIN/FNSKU nur teilweise vorhanden.
- Identifier liegen damit derzeit **außerhalb** des eigentlichen Produktstamms.

### Mehrfachdarstellungen / Namensdrift

Dieselbe SKU taucht in mehreren Blättern und teilweise mit leicht abweichender Schreibweise auf. Das ist für eine Präsentationsdatei verständlich, aber als Masterdatenhaltung riskant.

### Konsequenz

Die Excel-Datei sollte künftig **Import-/Export-Quelle bzw. Bericht** sein, aber nicht mehr Master. Ihre heutigen Informationen werden in normalisierte Entitäten überführt:

- Produkt
- Variante / SKU
- Identifier (ISBN, ASIN, FNSKU, EAN ...)
- Preise / Preislisten
- Kategorien
- Tags
- Assets
- Channel-Zuordnungen

---

## 2.2 XW-Office: Produkte-Modul

Relevante aktuelle Repo-Pfade:

- `src/xw_office/ui/modules/products/view.py`
- `src/xw_office/services/products/catalog.py`
- `src/xw_office/services/inventory/service.py`
- `src/xw_office/services/sevdesk/part_client.py`
- `src/xw_office/services/wix/client.py`
- `src/xw_office/services/wix/product_details_client.py`
- `src/xw_office/migrations/versions/002_product_pipeline.py`
- `src/xw_office/migrations/versions/003_product_brand_fields.py`
- `docs/product_pipeline_masterplan.md`
- `docs/product_pipeline_phases.yaml`
- `src/xw_office/web/app.py`

### Was bereits gut vorhanden ist

1. **Produkt-Pipeline als Konzept**
   - kanonisches Product-Modell
   - SKU-Aliase
   - Wix-/sevdesk-IDs
   - Print-Dateipfade
   - Mindestbestand / Reprint-Menge
   - Draft/Review/Live-Status

2. **Normalisierte DB-Migrationen**
   - `product`
   - `product_sku_alias`
   - `inventory_movement`
   - `print_plan`
   - `print_plan_item`
   - Brand-Felder

3. **sevdesk-Integration**
   - Part-Liste
   - SKU / Name / Preis
   - Lagerbestand
   - `stockEnabled`
   - Kategorie + Kategorie-ID
   - Steuersatz
   - interne Notiz
   - Bestandslesen/-schreiben

4. **Wix-Integration**
   - Produktliste
   - Detail-Client
   - Versionserkennung V1/V3
   - Wix Revision für optimistische Konflikterkennung
   - Kategorien
   - Preis-/Brand-Felder

5. **FastAPI-Webfundament**
   - Railway-taugliche App ist vorhanden.

### Hauptproblem heute

Trotz der bereits vorhandenen Migrationen wird der operative Produktkatalog weiterhin wesentlich aus dem `SettingKV`-JSON-Key **`inventory.products`** geladen und gespeichert.

Damit ist die Architektur derzeit sinngemäß:

```text
PostgreSQL
  └── SettingKV
       └── inventory.products = riesiges JSON-Array
```

statt:

```text
PostgreSQL
  ├── product
  ├── product_variant
  ├── product_identifier
  ├── product_asset
  ├── product_tag
  ├── product_price
  ├── channel_mapping
  └── ...
```

Das JSON war als Übergang sinnvoll, wird aber für WebUI, Sharing, Varianten, Assets, Konflikte, Versionierung und Multi-Channel-Sync zum Flaschenhals.

---

## 2.3 Kritischer Punkt: Bestand

Der vorhandene Audit im Repo dokumentiert bereits einen zentralen Risikopunkt:

- ein Druck-/Produktpfad liest/schreibt Bestand über sevdesk,
- ein anderer Workflow führt `inventory.stock_levels` separat.

Das ist genau die Art von Doppelwahrheit, die ein Product Hub beseitigen muss.

### Empfohlene Migration

**Übergangsphase:**
- sevdesk bleibt für kurze Zeit Bestandsreferenz.
- Product Hub spiegelt Bestände und protokolliert Abweichungen.
- jeder Bestandsänderungsweg wird inventarisiert.

**Endzustand:**
- Product Hub führt den **kanonischen Lager-Ledger**.
- Wix und sevdesk bekommen ihren Bestand vom Hub.
- Verkäufe/Druck/Korrekturen erzeugen append-only `inventory_movement`-Einträge.
- Externe Abweichungen werden als Konflikt gemeldet, nicht unbemerkt zum Master gemacht.

---

## 3. Single Source of Truth: genau definieren

„Single Source of Truth“ darf nicht bedeuten: alle Systeme dürfen dieselben Felder beliebig überschreiben.

Empfehlung: **Field Ownership Matrix**.

| Datenart | Master | Wix | sevdesk | XW-Office | XW-Flow |
|---|---|---|---|---|---|
| Produktname | Hub | Ziel | Ziel | Client | Lesen |
| SKU | Hub | Ziel | Ziel | Client | Lesen |
| Varianten | Hub | Ziel | ggf. je SKU | Client | Lesen |
| ISBN/EAN/ASIN | Hub | optional Ziel | optional | Client | Lesen |
| Beschreibung | Hub | Ziel | optional Ziel | Client | Lesen |
| Retail-Preis | Hub | Ziel | Ziel | Client | Lesen |
| Händlerpreis | Hub | nicht zwingend | nicht zwingend | Lesen | - |
| interne Tags | Hub | nur gemappt | nicht automatisch | Client | Lesen |
| sevdesk-Kategorie | Hub-Mapping | - | Ziel/Abgleich | Client | - |
| Produktbilder | Hub | Ziel | - | Lesen | optional |
| Druck-PDF-Pfad | Hub | niemals öffentlich | - | produktiver Nutzer | Link/Metadaten |
| Verbesserungen | Hub | - | - | Bearbeiten | Task-Kontext |
| Lagerbestand final | Hub | Projektion | Projektion | Buchungen | Lesen |
| Sync-Zeitstempel | Hub | Quelle/Ziel | Quelle/Ziel | Anzeige | Anzeige |

### Externe manuelle Änderungen

Wenn jemand direkt in Wix oder sevdesk einen Master-Feldwert ändert:

1. Hub erkennt Drift beim Event/Poll.
2. Er erzeugt `sync_conflict`.
3. WebUI zeigt z. B.:
   - Hub: 24,90 €
   - Wix: 25,90 €
   - geändert: 16.09.2026 07:12
4. Benutzer entscheidet:
   - Hub → Wix wiederherstellen
   - Wix-Wert als neuen Hub-Wert übernehmen

Keine stillen „last write wins“-Überschreibungen bei kritischen Feldern.

---

## 4. Empfohlener Tech-Stack

### Backend

- bestehendes **FastAPI** in XW-Office erweitern
- SQLAlchemy 2
- Alembic
- PostgreSQL auf Railway
- modularer Monolith, **keine Microservices** in Phase 1

### WebUI

Empfehlung: **React + TypeScript + Vite als responsive PWA**.

Warum:
- gute mobile Tabellen-/Card-Ansichten
- installierbar auf Android/iOS/Windows
- passt zum Frontend-Muster von XW-Flow
- Data Grid, Filter, Inline-Edit, Bildgalerien, Share-Ansichten einfach umsetzbar

### Assets

Zwei Arten bewusst trennen:

1. **Webfähige Assets**
   - Cover
   - Notenbeispiele
   - Händlerbilder
   - Vorschaudateien
   - S3-kompatibler Object Storage

2. **Produktionsassets**
   - Druck-PDFs
   - Netzwerk-/Windows-Pfad weiterhin möglich
   - zentral gespeichert werden Pfad, Prüfsumme, Dateigröße, letzter Healthcheck

Damit muss ein iPhone keinen Windows-Netzwerkpfad öffnen können, die Desktop-App kann ihn aber weiterhin zum Drucken nutzen.

### Background Jobs

Zu Beginn reicht:
- PostgreSQL-Outbox
- separater Railway Worker oder periodischer Job

Kein Redis/RabbitMQ nötig, solange Last und Jobvolumen niedrig sind.

---

## 5. Datenmodell

## 5.1 `product`

Produkt als gemeinsame fachliche Klammer.

Wichtige Felder:
- UUID
- Name
- Slug
- Kurzbeschreibung
- Langbeschreibung
- Brand
- Produktfamilie
- interner Produkttyp
- Status `draft/review/live/archived`
- aktiv/inaktiv
- Veröffentlichungsdatum
- `created_at`, `updated_at`
- `row_version`

**SKU nicht ausschließlich hier modellieren.** SKU gehört auf `product_variant`.

---

## 5.2 `product_variant`

Jedes Produkt hat mindestens eine Variante.

Beispiele:
- ein einfaches Heft → Default-Variante
- MusikHeroes-Produkt mit unterschiedlichen Ausgaben/Besetzungen → mehrere Varianten, wenn fachlich passend

Felder:
- UUID
- `product_id`
- SKU UNIQUE
- Variantentitel
- `is_default`
- aktiv/inaktiv
- Optionen als normalisierte Werte oder JSONB
- Gewicht
- physisch/digital
- Lagerführung ja/nein

### Migrationsregel

**Nicht automatisch aggressiv gruppieren.**

Initial:
- jede bekannte SKU wird sicher als Produkt + Default-Variante importiert.

Danach:
- verwandte SKUs können kontrolliert in Parent-Produkte gruppiert werden.

Damit werden falsche automatische Zusammenführungen vermieden.

---

## 5.3 `product_identifier`

Keine separaten Excel-Sonderlisten mehr.

Felder:
- `product_id` oder `variant_id`
- `scheme`
- `value`
- `country/market` optional
- `is_primary`

Schemes:
- ISBN13
- ISBN10
- EAN
- UPC
- ASIN
- FNSKU
- BARCODE
- LEGACY_SKU
- VLB_ID
- CUSTOM

Unique Constraint mindestens auf `(scheme, value)`.

---

## 5.4 Kategorien und Tags

### Kategorien
Hierarchische fachliche Klassifikation, z. B.:
- MusikHeroes
- Blech7er
- Blech4er
- Tanzlmusi
- Unterrichtsliteratur

Tabellen:
- `category`
- `product_category`

### Tags
Flexible Querschnittskennzeichen:
- `B2B`
- `POD`
- `Neuauflage`
- `Amazon`
- `VLB`
- `Händler-Export`
- `AudioPlayer`

Tabellen:
- `tag`
- `product_tag`

**B2B ist ein Tag/Publikationsmerkmal, keine sevdesk-Kategorie.**

---

## 5.5 sevdesk-Kategorie

sevdesk bietet für Parts eine echte Kategorie und liefert Kategorie-ID/-Name.

Empfehlung:
- internes Kategoriensystem unabhängig halten
- zusätzlich `channel_category_mapping`

Beispiel:

```text
Interne Kategorie: MusikHeroes Unterrichtsheft
   -> sevdesk Part Category ID 4711 "MusikHeroes"
   -> Wix Category ID abc... "MusikHeroes"
```

Dadurch müssen interne Tags nicht missbräuchlich in sevdesk gepresst werden.

---

## 5.6 Preise

Die Excel-Datei zeigt bereits, warum Preise ein eigenes Modell benötigen.

Tabellen:

### `price_list`
- Retail AT
- Händler/B2B
- optional DE/CH/etc.

### `product_price`
- `variant_id`
- `price_list_id`
- currency
- net amount
- gross amount
- tax rate / tax class
- valid_from
- valid_until
- source

Regel:
- keine semantisch unklaren Spalten wie `netto_1`, `netto_2`
- jede Preisart hat Namen und Gültigkeitskontext

---

## 5.7 Assets

`product_asset`

Felder:
- `product_id` / optional `variant_id`
- Rolle
- Reihenfolge
- Storage-Typ
- URI/Pfad
- MIME-Type
- Prüfsumme
- Dateigröße
- Wix Media-ID
- Quell-URL
- Sichtbarkeit
- Health-Status
- `last_checked_at`

Rollen:
- `COVER`
- `SAMPLE_SCORE`
- `PRINT_PDF`
- `PREVIEW_PDF`
- `AUDIO`
- `DOWNLOAD`
- `OTHER`

### Wix-Initialimport

Wix Catalog V3 definiert das Hauptmedium als das erste Element der Media-Liste. Das passt genau zu deiner bestehenden Konvention.

Importregel:

```text
media[0]  -> COVER
media[1+] -> SAMPLE_SCORE
```

Zusätzlich speichern:
- Wix Media-ID
- Sortierung
- ursprüngliche URL
- optional Mirror im eigenen Object Storage

---

## 5.8 Verbesserungen / Druckfehler

Im UI darf es wie ein einfaches Textfeld wirken, technisch sollte es **nicht nur ein überschreibbares Textfeld** sein.

Tabelle `product_improvement`:
- UUID
- Produkt/Variante
- Titel optional
- Beschreibung
- Quelle (`customer`, `dealer`, `internal`, `proofreading`)
- Quelle-Referenz optional
- Schweregrad (`info/minor/major/critical`)
- Status (`open/planned/resolved/wont_fix`)
- erstellt von
- erstellt am
- aufgelöst am
- `resolved_in_edition_id`

Warum besser als ein Feld:
- alte Hinweise gehen nicht verloren
- mehrere Fehler separat abhakbar
- bei Neuauflage automatisch als Checkliste verwendbar
- nachvollziehbar, wann welcher Fehler behoben wurde

Die Produktseite bekommt trotzdem einen großen Button **„Verbesserung hinzufügen“** und darunter die offenen Punkte.

---

## 5.9 Editionen / Auflagen

Sehr sinnvoll für deine Notenprodukte:

`product_edition`
- edition number / label
- product_id
- status
- published_at
- print asset ID
- notes
- created_at

Bei „Neue Auflage planen“:
- offene `product_improvement` laden
- XW-Flow-Task erzeugen
- Verbesserungen in Task-Details übernehmen
- nach Abschluss Verbesserungen optional mit dieser Edition verknüpfen

---

## 5.10 Lager

### `inventory_location`
Zunächst z. B. nur:
- Hauptlager XeisWorks

Später möglich:
- Büro
- externes Lager
- Messebestand

### `inventory_stock`
- variant_id
- location_id
- on_hand
- reserved
- reorder_point / alarm threshold
- target_stock
- default_reprint_qty
- updated_at

### `inventory_movement`
Append-only Ledger:
- delta
- reason
- source system
- external reference
- idempotency key
- before/after optional
- timestamp

Reasons z. B.:
- sale
- print_run
- manual_adjustment
- recount
- return
- damage
- import_baseline

### Verfügbar

```text
available = on_hand - reserved
```

---

## 5.11 Inventory Alerts

`inventory_alert`
- UUID
- variant_id/location_id
- type (`low_stock`, `out_of_stock`, `sync_drift`)
- threshold
- observed_stock
- status `open/acknowledged/resolved`
- first_triggered_at
- last_triggered_at
- resolved_at
- xw_flow_task_id

### Anti-Spam-Regel

Task nur beim **Schwellwert-Übergang** erzeugen:

```text
vorher > threshold
jetzt   <= threshold
=> EIN Alert + EIN Task
```

Solange Alert offen ist, keine neuen identischen Tasks.

Wenn Bestand wieder über Schwelle steigt:
- Alert resolved
- nächster späterer Threshold-Fall darf neuen Alert erzeugen

---

## 5.12 Channel Mapping / Sync

`channel_mapping`
- entity type (`product`, `variant`, `asset`, `inventory`)
- internal UUID
- channel (`wix`, `sevdesk`, `amazon` ...)
- external ID
- external parent ID
- external revision
- last_pulled_at
- last_pushed_at
- last_external_updated_at
- last_success_at
- sync status
- source payload hash

Zusätzlich:
- `sync_job`
- `sync_item`
- `sync_conflict`
- `sync_cursor`
- `external_payload_archive`

---

## 6. Wix-Synchronisation

## 6.1 Besonderheiten Catalog V3

Für die Implementierung relevant:

- Query Products liefert bis zu 100 Produkte je Abfrage.
- Varianten werden dabei nicht automatisch mitgeliefert.
- Varianten können separat über Read-Only Variants abgefragt werden.
- bis zu 1.000 Varianten pro Variant-Query.
- Produktmedien enthalten ein `main`-Medium; dieses entspricht dem ersten Media-Item.
- Inventory V3 ist variant/location-basiert.
- Updates verwenden eine `revision`, um versehentliches Überschreiben zu verhindern.

### Initialimport

1. Catalog-Version erkennen.
2. Alle Wix-Produkte paginiert lesen.
3. Für jedes Produkt vollständige Details/Medien lesen.
4. Varianten separat lesen oder vollständiges Product Detail verwenden.
5. Inventory Items lesen.
6. Kategorien lesen.
7. Staging-Tabellen füllen.
8. Match-Vorschläge nach:
   - bestehender Wix-ID
   - exakter SKU
   - Alias-SKU
   - anschließend nur manuelle Prüfung bei unsicherem Name-Match
9. Konflikt-/Duplikatbericht anzeigen.
10. Erst nach Freigabe in kanonische Tabellen übernehmen.

### Kein automatisches Fuzzy-Merge bei Produkten

Fuzzy Matching darf **Vorschläge** machen, aber keine Produkte ohne Bestätigung zusammenführen.

---

## 7. sevdesk-Synchronisation

sevdesk Part liefert bereits die benötigten Kerninformationen:
- `partNumber`
- `name`
- `text`
- Kategorie
- Bestand
- `stockEnabled`
- Einheit
- Netto-/Bruttopreise
- Steuer
- interner Kommentar

### Empfohlene Rolle

- sevdesk ist Buchhaltungs-/Artikel-Channel.
- Product Hub besitzt Produktstamm und final den Lager-Ledger.
- Part-ID wird im `channel_mapping` gespeichert.
- sevdesk-Kategorie wird gemappt.
- Tags bleiben intern, außer es gibt bewusst definierte Channel-Mappings.

### Übergang Bestand

Phase 1:
- stock pull from sevdesk
- Abweichungen melden

Phase 2:
- alle XW-Office-Bestandsbewegungen zentral protokollieren

Phase 3:
- Hub wird Stock-Master
- Push an sevdesk + Wix

---

## 8. Händleransicht / Sharing

Dies sollte ein Kernfeature sein, nicht nur ein Exportbutton.

### Saved View

`shared_catalog_view`
- Titel
- Filterdefinition
- Feld-Whitelist
- Preislisten-Auswahl
- Sortierung
- Token-Hash
- optional Passwort
- optional Ablaufdatum
- CSV erlaubt
- XLSX erlaubt
- Bilder erlaubt
- created_at
- last_access_at

### Beispiel

Filter:

```yaml
tags:
  contains: B2B
status: live
active: true
```

Felder:
- Cover
- SKU
- ISBN
- Produktname
- Besetzung
- Händlerpreis
- UVP
- Verfügbarkeit

Explizit **nicht** freigeben:
- Produktionspfade
- interne Verbesserungen
- Einkaufspreise
- Sync-Logs
- API-IDs
- interne Kommentare

### URLs

```text
/share/<opaque-token>
/share/<opaque-token>/export.csv
/share/<opaque-token>/export.xlsx
```

### Verhalten

Standardempfehlung: **Live-Ansicht**.

- Händler öffnet denselben Link später erneut und sieht aktuellen Stand.
- Export enthält `generated_at`.
- Optional kann später eine Snapshot-Funktion ergänzt werden.

### UX-Vorbilder

Baserow und Plytix zeigen sehr gut, was hier sinnvoll ist:
- gefilterte öffentliche Ansicht
- nur freigegebene Felder
- CSV/XLSX
- Assets/Bilder
- stabile Freigabelinks

Diese UX sollte nachgebaut werden, aber auf deinem eigenen kanonischen Datenmodell.

---

## 9. XW-Flow Integration

XW-Flow besitzt bereits:
- FastAPI-Tasks
- `POST /api/v1/tasks`
- `planning_mode`
- externe Entity-Referenzen
- Deep Links
- idempotenten `client_request_id`

Damit kann die Integration sauber und ohne Sonderlogik erfolgen.

### Inventar-Kachel

Product Hub Endpoint:

```http
GET /api/v1/inventory/summary
```

Beispiel:

```json
{
  "physical_products": 84,
  "low_stock": 6,
  "out_of_stock": 1,
  "open_reprint_alerts": 6,
  "sync_errors": 2,
  "updated_at": "2026-09-16T07:30:00+02:00"
}
```

Zusätzlich:

```http
GET /api/v1/inventory/alerts?status=open
```

### Task bei niedrigem Lagerstand

Beispielpayload an XW-Flow:

```json
{
  "title": "Nachdruck: XW-501.01 – Ohrwürmer #1",
  "description": "Lagerbestand hat den Alarmbestand erreicht.",
  "notes": "Bestand: 3\nAlarmbestand: 3\nZielbestand: 8\nOffene Verbesserungen: 2",
  "planning_mode": "pipeline",
  "external_entity_type": "inventory_alert",
  "external_entity_id": "<alert-uuid>",
  "external_deep_link": "https://.../products/<uuid>",
  "client_request_id": "<deterministische-uuid>"
}
```

Der deterministische `client_request_id` verhindert Doppel-Tasks bei Retry.

### Neue Auflage

Button im Product Hub:

**„Neue Auflage in XW-Flow planen“**

Task-Notizen enthalten automatisch:
- alle offenen Verbesserungen
- aktuelle Auflage
- Druck-PDF-Pfad/-Status
- offene Asset-Probleme
- optional ISBN/VLB-Daten

---

## 10. WebUI: empfohlene Ansichten

## 10.1 Dashboard

Kacheln:
- Produkte gesamt
- Wix-ready
- B2B-ready
- niedriger Bestand
- nicht lagernd
- Sync-Konflikte
- fehlende Cover
- offene Verbesserungen
- Produkte mit defektem Druckpfad

## 10.2 Produktliste

Spalten konfigurierbar:
- Bild
- SKU
- Name
- Kategorie
- Tags
- ISBN
- Retail-Preis
- B2B-Preis
- Bestand
- sevdesk
- Wix
- Datenqualität
- Syncstatus
- geändert am

Funktionen:
- Volltextsuche
- Filterchips
- Saved Views
- Bulk-Edit
- CSV/XLSX
- Auswahl → Händleransicht erzeugen

## 10.3 Produktdetail

Tabs:
1. Stammdaten
2. Varianten
3. Preise
4. Identifier
5. Kategorien & Tags
6. Bilder & Dateien
7. Bestand
8. Verbesserungen
9. Wix/sevdesk
10. Historie

## 10.4 Sync Center

Pro Produkt und global:
- Hub
- Wix
- sevdesk
- letztes Pull
- letztes Push
- Status
- Konflikt
- Retry
- Payload-Diff

---

## 11. Datenqualität / Completeness

Ein besonders nützliches Feature aus professionellen PIM-Systemen ist **Channel Readiness**.

Beispielregeln:

### Wix-ready
- SKU vorhanden
- Name vorhanden
- Retail-Preis vorhanden
- Cover vorhanden
- Beschreibung vorhanden
- Wix-Kategorie gemappt

### B2B-ready
- Tag B2B
- B2B-Preis vorhanden
- Cover vorhanden
- Beschreibung vorhanden
- SKU vorhanden
- ISBN, falls relevante Produktfamilie

### Print-ready
- Produktions-PDF vorhanden
- Pfad erreichbar
- Printprofil vorhanden
- Dateicheck erfolgreich

Darstellung:

```text
Wix     100% ✓
B2B      83% !  Händlerpreis fehlt
Print   100% ✓
```

Das ist für deine tägliche Arbeit wertvoller als ein abstrakter „Datenqualitätsscore“ ohne Kontext.

---

## 12. Weitere sinnvolle Features aus PIM-/Inventory-Tools

### Unbedingt empfehlenswert

- Audit-Historie pro Feld
- Soft Delete / Archivieren statt hart löschen
- Bulk Edit
- Saved Views
- Import-Staging mit Diff vor Übernahme
- Channel Readiness
- Asset-Healthcheck
- Konfliktcenter
- eindeutige Identifier-Prüfung
- Produktfamilien + kontrollierte Variantenvererbung
- CSV/XLSX Exporttemplates
- Share-Link mit Feld-Whitelist
- Schwellenwert-Alerts ohne Task-Spam
- Recount/Lagerkorrektur mit Begründung

### Sehr sinnvoll später

- mobiler Barcode-/ISBN-Scanner für Inventur
- QR-/Barcode-Suche direkt in der PWA
- Snapshot eines Händlerkatalogs zu einem bestimmten Datum
- Dealer-spezifische Preislisten
- geplante Veröffentlichung
- Produkt-Versionsvergleich
- Asset-Duplikaterkennung per Hash
- automatische Bilddimension-/Qualitätsprüfung
- VLB-Readiness

---

## 13. Build vs. fertiges Tool

## 13.1 Plytix

Stärken:
- Brand Portals
- stabile Produktdatenblatt-Links
- CSV/XLSX/PDF
- Asset-Downloads

Sehr gutes UX-Vorbild für Händlerfreigaben.

Warum nicht als Master:
- XW-Office-Druckpfade und Printlogik
- sevdesk-Lagerlogik
- XW-Flow Tasks
- eigene Wix-Integration
- bestehender Python/Postgres-Unterbau

würden trotzdem individuelle Middleware benötigen.

## 13.2 Baserow

Stärken:
- schnell verständliche Tabellen-UI
- öffentliche gefilterte Views
- hidden fields bleiben verborgen
- Export aus Shared View

Gutes UX-Vorbild, aber als kanonischer Product Hub zu generisch.

## 13.3 Akeneo

Stärken:
- Familien
- Varianten
- Channel-/Locale-Completeness
- Historie

Davon würde ich insbesondere **Familien, Variantendenken und Channel Readiness** übernehmen.

## 13.4 Pimcore

Stärken:
- PIM + DAM
- Datenqualität
- Workflows
- sehr mächtig

Für XeisWorks derzeit zu groß/komplex, wenn ein erheblicher Teil der spezifischen Logik bereits in XW-Office existiert.

## 13.5 Directus

Kann vorhandene SQL-Daten sehr schnell mit Data Studio, Rollen, Dashboards und Flows bedienbar machen.

Möglicher Einsatz:
- optionaler interner Admin-Accelerator

Nicht empfohlen als primäre Geschäftslogikschicht:
- Sync-Ownership
- Drucklogik
- Inventar-Ledger
- XW-Flow-Verknüpfung

sollten in deiner eigenen Domain-/API-Schicht bleiben.

---

## 14. Empfohlene API

### Products

```text
GET    /api/v1/products
POST   /api/v1/products
GET    /api/v1/products/{id}
PATCH  /api/v1/products/{id}
POST   /api/v1/products/{id}/archive
```

### Variants

```text
POST   /api/v1/products/{id}/variants
PATCH  /api/v1/variants/{id}
```

### Improvements

```text
GET    /api/v1/products/{id}/improvements
POST   /api/v1/products/{id}/improvements
PATCH  /api/v1/improvements/{id}
POST   /api/v1/products/{id}/plan-new-edition
```

### Assets

```text
POST   /api/v1/products/{id}/assets
PATCH  /api/v1/assets/{id}
POST   /api/v1/assets/{id}/healthcheck
```

### Inventory

```text
GET    /api/v1/inventory/summary
GET    /api/v1/inventory/alerts
POST   /api/v1/inventory/movements
POST   /api/v1/inventory/recount
PATCH  /api/v1/variants/{id}/inventory-policy
```

### Sync

```text
POST   /api/v1/sync/wix/import/preview
POST   /api/v1/sync/wix/import/commit
POST   /api/v1/sync/wix/push
POST   /api/v1/sync/sevdesk/pull
POST   /api/v1/sync/sevdesk/push
GET    /api/v1/sync/conflicts
POST   /api/v1/sync/conflicts/{id}/resolve
```

### Sharing

```text
POST   /api/v1/shared-views
GET    /share/{token}
GET    /share/{token}/export.csv
GET    /share/{token}/export.xlsx
POST   /api/v1/shared-views/{id}/revoke
```

---

## 15. Sync-Mechanik

### Outbox Pattern

Jede Masteränderung:

1. DB-Transaktion ändert Produkt.
2. In derselben Transaktion entsteht `outbox_event`.
3. Worker nimmt Event.
4. Push zu Wix/sevdesk.
5. Ergebnis in `sync_item` protokollieren.
6. bei Fehler Retry mit Backoff.
7. nach N Fehlern `sync_error/conflict`.

Vorteil:
- kein verlorener Sync zwischen DB-Commit und API-Aufruf.

### Idempotency

Jeder schreibende externe Vorgang hat eine stabile Idempotency-/Event-ID.

### Reconciliation

Zusätzlich regelmäßiger Abgleich:
- externe IDs vorhanden?
- SKU gleich?
- Preis drifted?
- Bestand drifted?
- Revision neuer als Hub-Snapshot?

Events/Webhooks allein reichen als Sicherheitsnetz nicht.

---

## 16. Auth & Security

### Interne WebUI

Nicht beim heutigen Bootstrap-Bearer-Token stehen bleiben.

Benötigt:
- echte User Session
- mindestens Rollen `admin`, `editor`, `viewer`
- service tokens für XW-Flow/XW-Office

### Public Shares

- zufälliger hochentropischer Token
- in DB nur Token-Hash
- rate limit
- optional Passwort
- optional Ablauf
- explizite Feld-Whitelist
- kein Zugriff auf interne API über Share-Token
- revocable

### Assets

Private Produktions-PDFs nie durch öffentliche Share-URLs zugänglich machen.

---

## 17. Migration aus heutiger Welt

## Phase 0 — Read-only Audit

- heutiges `inventory.products` exportieren
- sevdesk Parts exportieren
- Wix Produkte/Varianten/Medien exportieren
- Excel importieren
- nur Staging-Tabellen
- keinerlei Schreibzugriff auf Wix/sevdesk

Ergebnis:
- Match-Report
- Duplicate-SKU-Report
- Identifier-Konflikte
- Preisabweichungen
- Kategorieabweichungen
- Bestandsabweichungen

## Phase 1 — Canonical Schema

Neue produktive Tabellen ergänzen.

Noch keine externe Masterrolle.

## Phase 2 — Import & Mapping

Priorität beim Match:
1. bereits bekannte externe ID
2. SKU exact
3. Alias exact
4. Identifier exact
5. fuzzy nur als manueller Vorschlag

## Phase 3 — WebUI read-only

Alle Geräte können Daten ansehen.

## Phase 4 — WebUI edit + Audit

Produktpflege zentral.

## Phase 5 — Wix Master-Sync

Hub besitzt definierte Masterfelder.

## Phase 6 — Händlerportal

B2B-Views + CSV/XLSX.

## Phase 7 — Inventory Migration

sevdesk-shadow -> Hub Ledger -> Hub Master.

## Phase 8 — XW-Flow

Inventarkachel + idempotente Alerts + Neuauflagen-Tasks.

## Phase 9 — Legacy JSON entfernen

Erst wenn alle Consumer auf ProductRepository/API umgestellt sind:
- `inventory.products` read-only fallback
- Migration verifizieren
- fallback entfernen

---

## 18. Was ich NICHT machen würde

- Excel als Master behalten
- Airtable/Notion/Baserow zusätzlich als zweites Master-System einführen
- Produkte in Wix als Master lassen
- sevdesk langfristig als Master für Produktstammdaten verwenden
- Lagerbestand parallel in Hub + sevdesk + `SettingKV` führen
- interne Tags direkt 1:1 mit sevdesk-Kategorien gleichsetzen
- Wix-Bilder nur als flüchtige URLs speichern, ohne Media-ID/Provenienz
- alles in eine einzige `product`-Tabelle quetschen
- Produktvarianten als Text im Produktnamen verstecken
- jeden niedrigen Lager-Poll als neuen XW-Flow-Task auslösen
- Produktions-PDFs über Händlerlinks exponieren

---

## 19. Verbindlich bestätigte Architekturentscheidungen

Diese Entscheidungen wurden am **2026-09-16** bestätigt und sind für Codex/Claude **keine offenen Optionen mehr**:

1. **PostgreSQL ist Master für Produktdaten.**
2. **sevdesk ist nur während der Inventory-Migration Stock-Master; final Hub.**
3. **Jede SKU wird initial als Default-Variante modelliert.**
4. **Produktgruppierungen werden nicht automatisch erzwungen.**
5. **B2B = interner Tag + zentrale Preislisten.** Aktuell gilt eine einheitliche B2B-Preisliste; das Datenmodell muss aber bereits zusätzliche händlerbezogene Preislisten unterstützen, ohne dass dafür jetzt eine Händlerpreis-UI gebaut wird.
6. **Wix erstes Medium = Cover, weitere = Notenbeispiele.**
7. **Bilder werden im Hub gespiegelt, Wix IDs/URLs bleiben Provenienz.**
8. **Druck-PDF bleibt als Netzwerk-/Windows-Pfad; WebUI zeigt ausschließlich Pfad-Metadaten und Healthstatus.** In der initialen Architektur gibt es **keinen Download-/Streaming-Endpunkt für produktive Druck-PDFs**.
9. **Händlerlink ist standardmäßig live, read-only, widerrufbar.**
10. **CSV und XLSX werden serverseitig aus exakt derselben View-Definition generiert.**
11. **Sync-Konflikte werden sichtbar, nicht still überschrieben.**
12. **Bestandsalarm erzeugt nur bei Threshold-Crossing einen Task.**
13. **Verbesserungen sind einzelne Datensätze, nicht nur ein überschreibbares Textfeld.**
14. **Neue-Auflage-Task enthält automatisch alle offenen Verbesserungen.**
15. **Legacy `inventory.products` wird erst am Ende entfernt.**
16. **Product Hub wird nach erfolgreicher Shadow-/Reconciliation-Phase endgültig Lager-Master.** Danach sind sevdesk und Wix nur noch Bestandsprojektionen/Channels; direkte externe Abweichungen werden als Drift-Konflikt behandelt.
17. **Variantenmigration erfolgt zweistufig:** zunächst jede bekannte SKU sicher als eigenes Produkt mit Default-Variante; danach werden fachlich zusammengehörige Produkte (insbesondere MusikHeroes) kontrolliert und explizit gruppiert. Keine automatische Fuzzy-Zusammenführung.

---

## 20. Umsetzungsfolgen aus den bestätigten Entscheidungen

### 20.1 Lager-Master ist kein optionaler Endzustand mehr

Der Phasenplan muss bis zum **Inventory Cutover** führen. Der Cutover darf erst erfolgen, wenn die Shadow-Phase nachweislich stabil ist (keine ungeklärten Bestandsdifferenzen, alle produktiven Bestandsbewegungen laufen über den Ledger, Reconciliation erfolgreich). Nach dem Cutover gilt:

- `inventory_stock` + `inventory_movement` im Product Hub sind kanonisch.
- XW-Office bucht ausschließlich über den Hub.
- Wix und sevdesk erhalten Bestand vom Hub.
- direkt extern geänderte Bestände werden nicht still zurückimportiert, sondern als Drift/Sync-Konflikt sichtbar gemacht.
- `inventory.stock_levels` darf danach nicht mehr unabhängig geschrieben werden.

### 20.2 Händlerpreise: heute einheitlich, später erweiterbar

Initial werden mindestens `RETAIL_EUR` und `B2B_EUR` angelegt. Alle Händleransichten verwenden vorerst dieselbe `B2B_EUR`-Preisliste. Das relationale Preislistenmodell und `shared_catalog_view.price_list_id` bleiben bewusst so ausgelegt, dass später ohne Schema-Neubau weitere Preislisten wie `B2B_HAENDLER_X` angelegt und einzelnen Share-Views zugeordnet werden können.

### 20.3 Druck-PDF: nur Pfad + Healthcheck

`PRINT_PDF` bleibt in der ersten produktiven Ausbaustufe ein `NETWORK_PATH`-Asset. Die WebUI darf Pfad, Existenz, Lesbarkeit, Dateigröße, Prüfsumme und letzten Healthcheck anzeigen, aber **keinen Browser-Download und kein Streaming des Produktions-PDFs anbieten**. Händler-/Public-Shares schließen `PRINT_PDF` zwingend aus.

### 20.4 Varianten: sicher importieren, danach kuratieren

Importregel:

1. Jede bekannte SKU wird zunächst verlustfrei als eigenes kanonisches Produkt mit genau einer Default-Variante angelegt.
2. Beziehungen aus Excel/Wix dienen nur als **Grouping Candidates**, nicht als automatischer Merge.
3. Danach folgt ein eigener kuratierter Gruppierungsschritt, in dem fachlich zusammengehörige SKUs – insbesondere MusikHeroes-Instrument-/Besetzungsvarianten – einem gemeinsamen Parent-Produkt zugeordnet werden.
4. SKU, Identifier, Preise, Channel-Mappings, Assets und Historie müssen beim Gruppieren unverändert erhalten bleiben.
5. Gruppierungen sind auditierbar und reversibel bzw. mindestens vor Commit als Preview prüfbar.

---

## 21. Definition of Done

Das Vorhaben ist erst dann wirklich abgeschlossen, wenn:

- jedes Produkt eine kanonische UUID hat,
- jede SKU eindeutig einer Variante zugeordnet ist,
- ISBN/ASIN/FNSKU nicht mehr nur in Sondertabellen leben,
- alle Produktpflege über Hub/API läuft,
- XW-Office Produkte über Repository/API liest,
- Wix und sevdesk nur definierte Channel-Rollen besitzen,
- jede Synchronisierung Zeitstempel/Status/Fehler hat,
- Produktbilder korrekt als Cover/Beispiele klassifiziert sind,
- B2B-Link + CSV/XLSX dieselben Filter/Felder verwenden,
- Lager nur eine kanonische Wahrheit hat,
- niedriger Bestand genau einen offenen Alert/Task erzeugt,
- Verbesserungen revisionssicher gesammelt werden,
- neue Auflagen offene Verbesserungen automatisch übernehmen,
- Audit-Historie Änderungen nachvollziehbar macht,
- Legacy-JSON keine produktive Datenquelle mehr ist.

---

## 22. Quellen / Recherchehinweise für Implementierer

### Wix
- Products V3 Query: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/query-products
- Product Media: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/about-product-media
- Variants V3: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/read-only-variants-v3/query-variants
- Inventory Items V3: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/inventory-items-v3/introduction
- Update Product / revision: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/update-product

### sevdesk
- API reference: https://api.sevdesk.de/

### PIM / Sharing UX research
- Baserow Public Sharing / View Export: https://baserow.io/user-docs/public-sharing
- Plytix Product Data Sheets: https://help.plytix.com/en/creating-and-managing-product-data-sheets
- Plytix Brand Portal downloads: https://help.plytix.com/en/download-from-ecatalog
- Akeneo Families / Completeness: https://help.akeneo.com/en_US/serenity-build-your-catalog/30-serenity-manage-your-families-and-variant-families
- Pimcore Data Quality: https://docs.pimcore.com/platform/Data_Quality_Management/
- Directus Data Studio: https://docs.directus.io/user-guide/overview/data-studio-app

### XW-Office current code references
- `docs/product_pipeline_masterplan.md`
- `docs/product_pipeline_phases.yaml`
- `src/xw_office/services/products/catalog.py`
- `src/xw_office/services/inventory/service.py`
- `src/xw_office/services/sevdesk/part_client.py`
- `src/xw_office/services/wix/client.py`
- `src/xw_office/services/wix/product_details_client.py`
- `src/xw_office/migrations/versions/002_product_pipeline.py`
- `src/xw_office/migrations/versions/003_product_brand_fields.py`
- `src/xw_office/web/app.py`

