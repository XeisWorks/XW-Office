# XW-Office - To-do nach Wunschliste + Blueprint (Ist-Stand 2026-04-02)

Hinweis (2026-04-03): Verbindliche Source of Truth fuer Daily-Business + Rechnungen ist `docs/phase_master_daily_rechnungen.md`.
Diese Datei bleibt als historischer Verlauf bestehen.

Zweck:
- Diese Datei ist die klare Abarbeitungsliste fuer die naechsten Umsetzungsphasen.
- Basis sind die urspruengliche Wunschliste in `markdowns/umbau auf pyside6 und verbesserungen.txt`
  plus der Blueprint in `docs/copilot_migration_plan.md`.
- Fokus: nur offene Punkte, in kleine commit-faehige Pakete zerlegt.

## 1) Kurzfazit Ist-Stand

Bereits solide umgesetzt:
- PySide6 Grundstruktur mit Sidebar + Modulen
- Rechnungen Kernmodul inkl. Worker-basierter Datenladung
- Layout-Tools (QR, Leerseiten, Deckblatt, ISBN)
- Produkte mit Inventar-Ansicht + Wix-Abgleich Tab
- Kalkulationsmodul mit Royalty-Basislogik + Schnellrechner
- Settings mit DB/Token-Verwaltung und ClickUp Quick-Task
- Druckpfad ohne Acrobat-Flackern via PyMuPDF
- Auto-Update Basis und PostgreSQL/Alembic Grundgeruest

Groesste verbleibende Luecken:
- CRM Merge-Wizard (fachlicher Kern offen)
- Start/Print-Flow mit echter Inventar-Puffer-Logik (+3) end-to-end
- Produkte-Modul: echter bidirektionaler Wix/sevDesk Sync + Konfliktloesung
- FinanzOnline/UVA: echte SOAP/Zeep-Produktivanbindung statt Mock-Flow
- Reisekosten-Bridge (Submodule/Loader)
- Marketing/Notensatz von Ideenspeicher zu produktiven Flows
- CI/Qualitaet verstaerken (Ruff/mypy Gate, Performance-Kriterien)

---

## 2) Phase A - Core-Workflow schliessen (P0/P1)

### A1. START-Flow mit Inventar-Entscheidung finalisieren
Status: DONE (2026-04-02)

Aufgaben:
- Druckentscheidung im Start-Preflight hart umsetzen:
  - Nur drucken, wenn Bestand == 0 oder Bestand < Auftragsmenge
  - Bei Druck immer Puffer +3 addieren
- Start-Modi sauber trennen:
  - Nur Rechnungen
  - Rechnungen + Druck
- Ergebnisreport vor Ausfuehrung und nach Abschluss (was gedruckt, was ausgelassen)

DoD:
- Entscheidungen sind reproduzierbar und testbar.
- Inventar wird nach Workflow korrekt fortgeschrieben.
- Kein UI-Blocking (nur Worker).

Tests:
- Unit: Entscheidungslogik (Grenzfaelle 0, exakt passend, unter Menge)
- Integration: Start-Dialog -> Ausfuehrung -> Inventarupdate

### A2. CRM Merge-Wizard liefern
Status: DONE (2026-04-02, in-memory merge; live writeback folgt)

Aufgaben:
- Service-API fuer Merge-Strategien bauen (Master/Source Feldregeln)
- Wizard/Dialog im CRM:
  - Kandidaten anzeigen
  - Master waehlen
  - Merge bestaetigen
- SevDesk-Writeback robust behandeln (Fehlerdialoge + Logging)

DoD:
- Duplikate koennen Ende-zu-Ende zusammengefuehrt werden.
- Merge ist ohne echte Netzverbindung testbar (Mock ContactClient).

Tests:
- Unit: Merge-Strategie-Regeln
- UI: Smoke fuer Wizard-Ablauf

---

## 3) Phase B - Produkte als Arbeitszentrale (P1)

### B1. Wix/sevDesk Sync produktiv machen
Status: DONE (2026-04-02)

Aufgaben:
- Mapping-Tabelle fuer lokale SKU <-> Wix <-> sevDesk
- Konfliktansicht bei Abweichungen (Preis, Bestand, Sichtbarkeit)
- Sync-Buttons mit klarer Richtung:
  - Lokal -> Wix
  - Wix -> Lokal
  - Lokal -> sevDesk

DoD:
- Synchronisationen laufen nachvollziehbar und transaktionssicher.
- Konflikte werden sichtbar statt stillschweigend ueberschrieben.

Tests:
- Unit: Mapping/Conflict Resolver
- Integration: Mock API Flows fuer Wix/sevDesk

### B2. Druckplaene in Produkte integrieren
Status: DONE (2026-04-02)

Aufgaben:
- Druckplan-Editor im Produkte-Modul bereitstellen
- Verknuepfung mit Start-Preflight Entscheidung
- Cover/Deckblatt-Verknuepfung pro Produkt sichtbar machen

DoD:
- Produkte-Modul deckt Inventar + Sync + Druckplanung in einem Flow ab.

---

## 4) Phase C - Finance/Tax produktiv (P1/P2)

### C1. UVA SOAP live backend (Zeep)
Status: DONE (2026-04-02)

Aufgaben:
- Zeep-Backend in FinanzOnline-Service integrieren
- Strukturierte Payload/Response DTOs absichern
- Taxes-UI Text/Buttons auf produktiven Modus umstellen

DoD:
- Echte UVA-Sendung ist moeglich (konfigurationsabhaengig).
- Fehlertexte sind fuer Fachanwender verstaendlich.

Tests:
- Unit/Integration mit gemocktem zeep client
- Contract-Tests fuer relevante Filing-Varianten

### C2. Clearing/Ausgaben weiter vertiefen
Status: DONE (2026-04-02)

Aufgaben:
- Endpunkte/Importpfade vervollstaendigen
- Listenfilter und Export verbessern

DoD:
- Steuer-Modul ist fuer den Tagesbetrieb nutzbar, nicht nur scaffold.

---

## 5) Phase D - Integrationen und Wachstum (P2)

### D1. Reisekosten Bridge
Status: DONE (2026-04-02, optional loader mit Fallback)

Aufgaben:
- Optionalen Loader fuer Reisekosten-Submodule implementieren
- Fallback-Placeholder beibehalten, falls Submodule fehlt

DoD:
- App startet weiterhin ohne Submodule.
- Bei vorhandenem Submodule wird das Widget eingebettet.

### D2. Marketing von Idee zu Workflow
Status: DONE (2026-04-02, strukturierte Eintraege + Workflow-Felder)

Aufgaben:
- Strukturierte Content-Objekte (Plan, Kanal, Status, Termin)
- Optionaler Connector-Rahmen (zunaechst dry-run) fuer Social Posting
- Newsletter-Export aus CRM Segmenten vorbereiten

DoD:
- Marketing-Modul liefert echte Arbeitsablaeufe statt nur Notizen.

### D3. Notensatz ausbauen
Status: DONE (2026-04-02, strukturierte Projekt-Workflows)

Aufgaben:
- Funktionsroadmap in technische Inkremente aufteilen:
  - Transposition
  - PDF-Digitalisierung (Pilot)
  - Etueden/Melodien-Entwuerfe
- Klar trennen: kurzfristige Tools vs. spaetere KI/Audio Features

DoD:
- Notensatz-Modul hat mindestens einen produktiven End-to-End Use Case.

---

## 6) Phase E - Qualitaet, Betrieb, Zukunftssicherheit (P0 querliegend)

### E1. CI-Qualitaetsgates schaerfen
Status: DONE (2026-04-02, Ruff in CI)

Aufgaben:
- CI um `ruff check src/` erweitern
- Optional: `mypy src/` als Gate oder Warnstufe

DoD:
- PRs laufen reproduzierbar durch gleiche Quality-Gates.

### E2. Performance-/UX-SLOs definieren
Status: DONE (2026-04-02, README erweitert)

Aufgaben:
- Konkrete Zielwerte in README dokumentieren, z.B.:
  - Modulwechsel gefuehlt sofort (<200 ms bis erste Reaktion)
  - Netzladevorgaenge stets mit Worker + sichtbarem Status
- Messpunkte in kritischen Flows einziehen (Start-Flow, Rechnungen laden, CRM Scan)

DoD:
- Performance ist messbar und regressionsfaehig testbar.

### E3. Multi-PC Betriebsleitfaden
Status: DONE (2026-04-02, docs/multi_pc_betriebsleitfaden.md)

Aufgaben:
- Klare Betriebsdoku fuer Railway + lokale venv Instanzen
- Rollout/Update-Strategie fuer mehrere PCs dokumentieren

DoD:
- Neuer PC kann nach Anleitung ohne implizites Wissen produktiv gesetzt werden.

---

## 7) Empfohlene Reihenfolge fuer die naechsten 6 Sprints

1. Sprint 1: A1 (START-Flow Logik + Tests)
2. Sprint 2: A2 (CRM Merge-Wizard)
3. Sprint 3: B1 (Produktiver Wix/sevDesk Sync)
4. Sprint 4: C1 (UVA SOAP live)
5. Sprint 5: D1 + E1 (Reisekosten Bridge + CI Gates)
6. Sprint 6: D2/D3 + E2 (Marketing/Notensatz + Performance SLOs)

Aktueller Fortschritt:
- Abgeschlossen: A1, A2, B1, B2, C1, C2, D1, D2, D3, E1, E2, E3.
- Naechste Hauptpakete: produktiver Live-Writeback fuer CRM-Merge (sevDesk), vertiefte Steuer-Endpunkte und optionale Connectoren fuer Marketing.

Ergaenzung 2026-04-02:
- XW-Copilot Untermenue + Panel fuer Outlook-Add-in Integration umgesetzt.
- Verbesserte Integrationsskizze: docs/xw_copilot_outlook_integration.md
- Dry-Run API-Contract + Simulationsservice + UI-Testtab umgesetzt (Request/Response Validation inkl. Correlation-ID).

---

## 8) Arbeitsmodus pro Ticket (verbindlich)

- Ticketgroesse: 1 fachliche Einheit pro Commit/PR.
- Immer erst Service/API, dann UI.
- Keine blockierenden Netz- oder Dateizugriffe im UI-Thread.
- Nach jedem Ticket:
  - `pytest tests/`
  - bei Qualitaetsphase zusaetzlich `ruff check src/` und ggf. `mypy src/`
- Keine Secrets committen.
