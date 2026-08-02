# XW-Office Umbau Checkliste (Prioritaet + autonome Abarbeitung)

Hinweis (2026-04-03): Diese Datei ist historisch.
Verbindlicher Status und Phasenstand liegen in `docs/phase_master_daily_rechnungen.md`.

Zielbild (erste Ausbaustufe):
- App startet stabil auf jedem PC.
- PostgreSQL und Alembic sind sauber eingebunden.
- Druckerstatus ist verlaesslich und Druckfunktionen sind robust.
- In Modul Rechnungen sind die ersten offenen Rechnungen sichtbar.
- Daily-Business-Untermenue ist modern integriert (nicht als verstreute Alt-Widgets).
- START ALL wird durch einen klaren START-Flow ersetzt (Play-Logik), mit parallelem Einzel-Druck.

Legende:
- Prioritaet: P0 = kritisch fuer Go-Live, P1 = wichtig direkt danach, P2 = mittelfristig.
- Status: TODO | IN PROGRESS | BLOCKED | DONE.
- DoD = Definition of Done (objektive Abnahme).

## P0 - Fundament fuer lauffaehige Kern-App

### P0.1 Runtime-Basis aufraeumen und reproduzierbar machen
- Status: TODO
- Warum: Ohne reproduzierbare Umgebung entstehen auf jedem PC andere Fehler.
- Aufgaben:
  - Python-Version fixieren und in README + pyproject dokumentieren.
  - Startpfad `python -m xw_office` als einzige Startmethode festlegen.
  - Fehlerlogging und Startdiagnose beim App-Boot verifizieren.
- DoD:
  - Frisches Setup auf 1 Referenz-PC funktioniert ohne Handarbeit.
  - App startet bis Home-View ohne Exception.

### P0.2 PostgreSQL + Alembic produktionsreif schalten
- Status: DONE (Settings-DB-Status-Anzeige)
- Warum: Multi-PC-Sync ist Kernanforderung.
- Aufgaben:
  - `DATABASE_URL` und `FERNET_MASTER_KEY` Pflichtpruefung mit klaren Fehlermeldungen.
  - Migrationsfluss `alembic upgrade head` in Start-Checkliste integrieren.
  - DB-Verbindungsstatus im Settings-Modul sichtbar machen.
- DoD:
  - DB-Verbindung wird beim Start validiert.
  - Alembic-Head ist aktuell.
  - API-Secret-Repository kann lesen/schreiben (Smoke-Test).

### P0.3 Drucker-Subsystem robust machen (ohne Acrobat-Flackern)
- Status: IN PROGRESS
- Warum: Druck ist geschaeftskritisch und muss jederzeit nutzbar sein.
- Aufgaben:
  - Druckerampel mit echter Sperrlogik fuer alle Druck-Entry-Points vereinheitlichen.
  - Rechnung/Noten-DPI und Seitenbereichsdruck in End-to-End-Flow testen.
  - Fehlerdialoge und Fallback bei nicht verfuegbaren Druckern vereinheitlichen.
- DoD:
  - Kein Acrobat-Popup notwendig.
  - Druck auf gueltigem Drucker erfolgreich.
  - Bei roter Ampel sind Druckaktionen deaktiviert.

### P0.4 Rechnungen-Modul als erstes produktives Kernmodul fertigstellen
- Status: DONE
- Aufgaben:
  - [x] Default-Ansicht auf offene Rechnungen (Status 200) gesetzt.
  - [x] InvoiceSummary um buyer_note + address_country_code erweitert.
  - [x] Tabelle zeigt Spalten: Land + Notiz (✎-Symbol) als Hinweisspalten.
  - [x] Detailpanel modernisiert: QGroupBox-Sektionen (Rechnung / Kunde / Käufernotiz).
  - [x] Schnell-Druck: Rechnung + Label + Noten als separate Buttons.

## P0 Daily-Business Integration (neues Rechnungen-Design)

### P0.5 Altes Daily-Business-Untermenue in moderne Struktur ueberfuehren
- Status: DONE (TagesgeschaeftView mit Tabs)
- Warum: Alte Funktionstiefe darf nicht verloren gehen.
- Aufgaben:
  - In Rechnungen eine obere Action-Bar mit Segmenten einfuehren:
    - Invoices
    - Mollie Authorized
    - Gutscheine
    - Download-Links
    - Refunds
  - Jede Sektion mit Badge/Pending-Zaehler ausstatten.
  - Badge-Logik zentral ueber AppSignals + Sidebar spiegeln.
- DoD:
  - Alle Daily-Business-Unterpunkte sind in Rechnungen erreichbar.
  - Pending-Zaehler aktualisieren sich ohne manuellen Refresh.

### P0.6 START ALL ersetzen durch klaren START-Flow
- Status: DONE (START-Button + Pre-Flight-Dialog)
- Warum: Bedienlogik soll klarer und zukunftsfaehig sein.
- Aufgaben:
  - Button-Set neu definieren:
    - START (Play-Symbol) fuer Workflow-Ausfuehrung
    - PRINT ALL fuer Sammeldruck
    - CHECK PRODUCTS optional als Vorpruefung
  - START-Dialog zeigt vor Ausfuehrung:
    - Was ist auf Lager?
    - Was wird auto-nachgedruckt?
    - Welche Jobs werden nur fakturiert?
  - Modi im START-Dialog:
    - Nur Rechnungen abarbeiten
    - Rechnungen + Druck
- DoD:
  - Kein START ALL mehr im UI.
  - START-Dialog trifft nachvollziehbare Entscheidungen.
  - PRINT ALL bleibt separat nutzbar.

### P0.7 Inventar + Druckplan-Entscheidung in START integrieren
- Status: TODO
- Warum: Verhindert unnoetige Druckjobs und baut gezielt Bestand auf.
- Aufgaben:
  - Regel implementieren:
    - Nur drucken wenn Bestand 0 oder unter Auftragsmenge.
    - Bei Druck automatisch Puffer +3 erzeugen.
  - Vor Ausfuehrung klare Auflistung: vorhanden vs. nachzudrucken.
- DoD:
  - START-Workflow erzeugt konsistente Druckentscheidungen.
  - Inventar wird nach Abschluss korrekt aktualisiert.

## P1 - Direkte Erweiterung nach stabiler Basis

### P1.1 CRM von Demo auf produktive Daten heben
- Status: TODO
- Aufgaben:
  - Echte sevDesk-Contacts laden.
  - Duplicate Scan + Merge-Wizard mit nachvollziehbarer Entscheidung.
- DoD:
  - Doppelte Kunden koennen sichtbar zusammengefuehrt werden.

### P1.2 Produkte-Modul vom Placeholder zum Arbeitsmodul
- Status: TODO
- Aufgaben:
  - Wix/sevDesk Sync, Mapping, Konfliktansicht.
  - Druckplaene + Cover/Deckblatt-Bezug in Produkte verankern.
- DoD:
  - Produkte-Modul deckt Inventar + Sync + Druckplanung ab.

### P1.3 Settings als echte Zentrale
- Status: IN PROGRESS
- Aufgaben:
  - Druckerzuordnung, API-Token-Verwaltung, DB-Status, Sync-Optionen.
  - Sichere Speicherung ueber verschluesselte Secrets.
- DoD:
  - Alle zentralen Laufzeitparameter sind in Settings pflegbar.

## P2 - Ausbau und Skalierung

### P2.1 Statistik/Kalkulation produktiv
- Status: TODO

### P2.2 Marketing/Notensatz von Ideenspeicher zu echten Flows
- Status: TODO

### P2.3 Reisekosten sauber als Submodule-Bridge integrieren
- Status: TODO

## Technische Querschnitts-DoD (fuer jede abgeschlossene Task)
- Kein blockierender Netzwerkcall im UI-Thread.
- Fehlertexte fuer User klar und deutsch.
- Tests fuer Kernlogik vorhanden (mind. Unit + 1 Integration/Smoke je kritischem Pfad).
- Logging statt print.
- Keine nackten except-Bloecke.

## Abarbeitungsreihenfolge (autonom)
1. P0.1
2. P0.2
3. P0.3
4. P0.4
5. P0.5
6. P0.6
7. P0.7
8. P1.1
9. P1.2
10. P1.3

## Fortschrittslog (laufend)
- 2026-04-02: Checkliste erstellt und Prioritaeten finalisiert.
- 2026-04-02: Rechnungen auf Default-Filter Offen umgestellt.
- 2026-04-02: status_message Signal an globale Statusleiste angebunden.
- 2026-04-02: Startup-DB-Konnektivitaetscheck (Ping) eingebaut; App startet bei Fehlern weiter mit Warnhinweis.
- 2026-04-02: Einzel-Druck im Rechnungen-Modul erweitert: Rechnung + Label + Noten.
- 2026-04-02: InvoiceSummary um buyer_note (✎-Symbol) + address_country_code erweitert.
- 2026-04-02: Detailpanel auf QGroupBox-Sektionen modernisiert (Rechnung / Kunde / Käufernotiz).
- 2026-04-02: Settings-Modul neu: DB-Ping-Button, Secrets-Status, Druckerkonfiguration.
- 2026-04-02: TagesgeschaeftView erstellt: 5 Tabs (Rechnungen, Mollie, Gutscheine, Downloads, Refunds).
- 2026-04-02: START-Button (▶ START) mit Pre-Flight-Dialog (Modus: Nur Rechnungen / Rechnungen + Druck).
- 2026-04-02: START-Preflight-Engine umgesetzt (Bestand vs Bedarf, Fehlmenge, Druck inkl. Puffer +3).
- 2026-04-02: Daily-Business Badges erweitert (Rechnungen + Mollie/Gutscheine/Downloads/Refunds via DB-JSON).
- 2026-04-02: Sidebar-Badge-Update ueber AppSignals.badge_updated verdrahtet.
- 2026-04-02: SecretService eingefuehrt (DB-verschluesselt mit Fernet, .env-Fallback).
- 2026-04-02: Settings um sichere Token-Speicherung (SEVDESK/WIX) in DB erweitert.
- 2026-04-02: Print-Dialog runtime-gehaertet (Druckerverfuegbarkeit + konfigurierter Drucker geprueft).
- 2026-04-02: DailyBusinessService eingefuehrt; Mollie/Gutscheine/Downloads/Refunds Tabs nun mit Queue-Views statt Placeholdern.
- 2026-04-02: Settings-Queue-Felder fuer alle vier Daily-Business-Queues ergaenzt (DB-JSON editierbar).
- 2026-04-02: SecretService um weitere Schluessel erweitert (Mollie/Stripe/OpenAI/ClickUp/MS/FON/Maps) inkl. ENV-Fallback.
- 2026-04-02: Druckampel-Regel korrigiert (ohne konfigurierte Namen + ohne lokale Drucker nun rot statt gruen).
- 2026-04-02: Neue Unit-Tests fuer Druckampel + SecretService hinzugefuegt (8 Tests gruen).

## Sofort-Fokus (naechster Arbeitsblock)
- Block A: P0.2 + P0.3 abschliessen (DB + Druck robust).
- Block B: P0.4 umsetzen (offene Rechnungen + Hinweis-Spalten + Einzel-Druckaktionen).
- Block C: P0.5/P0.6 starten (Daily-Business-Integration + START-Flow mit Play-Logik).