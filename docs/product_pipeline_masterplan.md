# XW-Office Product Pipeline Masterplan — Final Spec

> Letzte Aktualisierung: 2026-04-03  
> Alle Design-Entscheidungen durch User-Interview bestätigt.

---

## Design-Entscheidungen (aus Interview)

| # | Thema | Entscheidung |
|---|---|---|
| 1 | Schreibstelle | Pipeline = einzige Schreibstelle für alle Menüs |
| 2 | Bestandsquelle | sevDesk = Single Source of Truth (SOT) für Bestand |
| 3 | Stock Write-back | Nach Druck: `PUT /Part/{id}` mit neuem Bestand |
| 4 | Reservierung | Erst beim klick auf START/Drucken — kein Pre-Lock |
| 5 | Digitale Produkte | `stockEnabled: false` in sevDesk → UI zeigt ∞, von Drucklogik ausgeschlossen |
| 6 | POD-Zielbestand | Konfigurierbar pro Produkt (`min_stock_target`, `reprint_batch_qty`) |
| 7 | Print-Reihenfolge | FIFO nach Rechnungsdatum |
| 8 | Order-Referenz | Aus sevDesk-Feldern — keine manuelle Korrektur nötig |
| 9 | Druckdatei | Lokaler Windows-Pfad, pro Produkt in DB gespeichert |
| 10 | Cover/Deckblatt | Bleibt im Layout-Modul (Editor); Pipeline speichert nur den Pfad-Verweis |
| 11 | CRM/Statistik | Lesen aus Pipeline-Queries |
| 12 | Settings-Submenu | Kein eigenes Pipeline-Admin-Submenu |
| 13 | Freigabe | Draft → Review → Live (Sync) |
| 14 | Multi-PC | Lokale Cache-Tabellen erlaubt |

---

## Zielbild
Eine einheitliche, zentrale Produkt-Pipeline, die von allen Menues genutzt wird.

Die Pipeline ist die einzige Quelle fuer:
- Produktstammdaten
- SKU-Normalisierung
- Bestand
- Druckentscheidung
- Druckassets (PDF/Bild/Pfade)
- Wix/sevDesk Synchronisierung
- Fulfillment-Ereignisse

## Architekturprinzipien
- Single Engine: Alle produktbezogenen Entscheidungen laufen ueber einen zentralen Service-Graph.
- Event-Driven: Module publizieren Events, die Pipeline verarbeitet sie idempotent.
- Read/Write Trennung: Query-Views fuer UI, Command-Services fuer Aenderungen.
- Source of Truth: Operative Daten in PostgreSQL, externe Systeme als Integrationen.
- Reproducible Decisions: Jede Druck-/Bestandsentscheidung wird versioniert im Audit-Log abgelegt.

## Kernbausteine

### 1) Product Catalog Core
Verantwortung:
- Canonical Product Entity
- SKU-Mapping (Alias, Legacy-SKU, Wix Variant SKU, sevDesk Artikelnummer)
- Produktstatus (released/unreleased, aktiv/inaktiv)
- Beziehung zu Asset-Pfaden und Renderprofilen

Wichtige Tabellen:
- product
- product_sku_alias
- product_channel_mapping
- product_asset
- product_render_profile

### 2) Inventory Core
Verantwortung:
- Ist-Bestand je Produkt/SKU und Standort
- Reservierungen durch offene Rechnungen
- Verbrauch bei Fulfillment
- Korrekturbuchungen mit Grund

Wichtige Tabellen:
- inventory_stock
- inventory_reservation
- inventory_movement
- inventory_snapshot

### 3) Print Decision Engine
Verantwortung:
- Regel: nur drucken, wenn Bestand < benoetigte Menge
- Regel: Nachdruck-Mindestmenge (z. B. 3 Stk)
- Regelkonflikte aufloesen (manuelle Uebersteuerung moeglich)
- Plan erzeugen: was wann auf welchem Drucker

Wichtige Tabellen:
- print_rule
- print_plan
- print_plan_item
- print_job

### 4) Channel Integrations
Verantwortung:
- Wix: Produkte, Bilder, Order-Line-Items
- sevDesk: Artikel, Rechnungspositionen
- Optionale spaetere Kanaele

Wichtige Tabellen:
- sync_cursor
- sync_job
- sync_error
- external_payload_archive

### 5) Asset Resolver
Verantwortung:
- Lokalen Datei-Pfad fuer Druckdatei aufloesen
- Prioritaet: lokaler Override > Kanal-Asset > Default
- Existenz-/Integritaetspruefung

Wichtige Tabellen:
- asset_path_override
- asset_health

### 6) Unified Product API (intern)
Ein zentraler Einstieg fuer alle Menues.

Beispiel-Commands:
- reserve_for_invoice(invoice_id)
- create_print_plan_for_invoice(invoice_id)
- execute_print_plan(plan_id)
- sync_product(product_id, channels)

Beispiel-Queries:
- get_product_view(product_id)
- get_invoice_piece_blocks(invoice_id)
- get_inventory_gap_for_invoice(invoice_id)

## Zugriff aus Menues

### Rechnungen
- Selektierte Rechnung -> Piece Blocks aus Pipeline
- Druckbuttons fragen Print Decision Engine
- Fulfillment reduziert Bestand via Inventory Core

### Produkte
- Stammdatenpflege direkt im Catalog Core
- Sync-Aktionen triggern Channel Integrations
- Druckplanvorschau nutzt Print Decision Engine

### Layout
- Neue Cover/Deckblatt-Assets landen im Asset Resolver
- Renderprofile pro Produkt aktualisieren

### CRM
- Lesender Zugriff auf Produkt-/Bestellkontext fuer Kundensicht

## Ziel-Datenfluss (vereinfacht)
1. Rechnung wird geladen
2. Pipeline loest Order-Referenz -> Wix Line-Items
3. SKU-Normalisierung gegen Catalog Core
4. Inventory Core berechnet verfuegbar/reserviert/fehlend
5. Print Decision Engine erstellt Vorschlag
6. UI zeigt Stuecke + Druckvorschlag
7. Bei Ausfuehrung: Print Jobs + Inventory Movements + Audit

## Phasenplan (Kurz)
- Phase A: Domain-Schema + zentrale Models
- Phase B: SKU-Mapping + Asset Resolver
- Phase C: Inventory Core + Reservierungen
- Phase D: Print Decision Engine + Regeln
- Phase E: Rechnungen-Integration (Stuecke + Druckvorschlag)
- Phase F: Produkte-UI auf Pipeline umstellen
- Phase G: Voller Channel-Sync + Monitoring

## Akzeptanzkriterien
- Jede produktbezogene UI-Funktion nutzt dieselbe Pipeline-API
- Druckentscheidungen sind im Audit nachvollziehbar
- Bestand veraendert sich konsistent bei Fulfillment
- Wix/sevDesk Konflikte werden sichtbar und bearbeitbar
- Kein Modul implementiert eigene SKU-Logik ausserhalb der Pipeline

## Nicht-Ziele (vorerst)
- Vollautomatischer Social/Marketing-Content
- Komplette Notensatz-Engine
- Fremdsysteme ausser Wix/sevDesk vor Phase G
