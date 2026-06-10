# XW-Studio Umbauplan: Produkte Brands gezielt + Bulk bearbeiten

## Zielbild
- Brands im neuen PySide6-Projekt zentral und sicher bearbeiten.
- Gezielte Auswahl moeglich per Suche, Kategorie und Mehrfachauswahl.
- Bulk-Update mit Vorschau (Dry-Run), Ergebnisbericht und nachvollziehbarer Protokollierung.
- Architekturkonform: zentrale Service-Schicht, UI nur als Orchestrator.

## Ist-Stand (verifiziert)
- Produkte-Modul vorhanden mit Tabs Inventar, Wix-Abgleich, Sync-Konflikte.
- Suchfilter vorhanden (SKU/Name/Kategorie lokal, SKU/Name Wix).
- Writeback aktuell nur Wix -> lokal.
- Kein Brand-Feld in Product-Pipeline-Entitaet, kein Brand-Bulk-Workflow.

## Umbauphasen

### Phase 1 - Planung und Schnittstellen (DONE)
- [x] Zielbild und Phasenplan dokumentiert.
- [x] Technische Luecken gegen Legacy identifiziert.
- [x] Integrationsstrategie fuer Brand-Updates festgelegt.

Ergebnis:
- Diese MD-Skizze dient als Abarbeitungsleitfaden und Statusquelle.

### Phase 2 - Datenmodell fuer Brand erweitern (DONE)
- [x] `ProductRow` um Brand-Felder erweitern.
- [x] Wix-Produktmodell um Brand-Felder erweitern (read path).
- [x] Persistenz (`inventory.products`) um Brand-Felder erweitern.
- [x] Migration fuer `product.brand_name` / `product.brand_id` anlegen.

Definition of Done:
- Brand-Daten koennen verlustfrei gelesen/geschrieben werden.
- Bestehende Daten bleiben kompatibel.

### Phase 3 - Zentrale Brand-Service-Schicht (DONE)
- [x] Neuer Service fuer Target-Filter, Dry-Run und Apply.
- [x] Report-Datentypen fuer erfolgreich/uebersprungen/fehlerhaft.
- [x] DI-Registrierung und Nutzung im Produkte-Modul.

Definition of Done:
- UI ruft nur Service-Methoden auf, keine direkte Bulk-Logik im Widget.

### Phase 4 - UI fuer gezielte und Bulk-Bearbeitung (DONE)
- [x] Brand-Spalten in Inventar/Wix/Sync sichtbar.
- [x] Mehrfachauswahl + Brand-Aktion fuer selektierte Produkte.
- [x] Such-/Kategorie-orientierte Zielauswahl nutzen.
- [x] Dry-Run-Vorschau und Ergebnisdialog anzeigen.

Definition of Done:
- Brands koennen im Bulk fuer selektierte Produkte geaendert werden.
- Nutzer sieht vorab und nachher klare Rueckmeldung.

### Phase 5 - Externe Writebacks (Wix/sevDesk) robust anbinden (IN PROGRESS)
- [x] Wix Brand-Writeback ueber Stores/eCommerce Product APIs (nicht Collection).
- [x] V3-Brand-Aufloesung (Name/ID) inkl. optionale Brand-Erzeugung.
- [x] Konfliktbehandlung + Retry + Logging.

Definition of Done:
- Lokal + Kanalupdates laufen nachvollziehbar, mit Teilerfolg-Handling.

### Phase 6 - Tests und Betriebsreife (TODO)
- [x] Unit-Tests fuer Dry-Run/Apply (inkl. Kantenfaelle).
- [x] UI-Smoke fuer Bulk-Flow.
- [x] Dokumentation und Bedienhinweise aktualisieren.

Definition of Done:
- Bulk-Brand-Flow ist regressionssicher und reproduzierbar.

## Abarbeitungsreihenfolge (autonom)
1. Phase 2: Datenmodell + Persistenz
2. Phase 3: Service-Schicht
3. Phase 4: UI-Bulk-Flow
4. Phase 2: DB-Migration fuer zentrale Pipeline
5. Phase 5/6 in Folgeschritten

## Fortschrittslog
- 2026-06-10: Phase 1 abgeschlossen, Umsetzung gestartet (Phase 2/3/4).
- 2026-06-10: Phase 2-4 umgesetzt: Brand-Felder + Migration + zentraler Brand-Service + Bulk-UI (lokal).
- 2026-06-10: Phase 5 gestartet: optionaler Wix-Writeback im Brand-Bulk-Flow implementiert.
- 2026-06-10: Phase 5 erweitert: Wix Brand resolve/create + Retry + detaillierter Ergebnisreport umgesetzt.
- 2026-06-10: Phase 6 gestartet: Unit-Tests und UI-Smoke fuer Brand-Bulk-Flow hinzugefuegt (gruen).
- 2026-06-10: Phase 6 abgeschlossen: Bedienanleitung erstellt (`produkte_brand_bulk_bedienung.md`).
