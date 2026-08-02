# Legacy → XW-Office: Gesamtanalyse der Migration und Übernahmeplan für verbleibende Funktionen

**Datum:** 2026-07-25
**Scope:** Vergleich `C:\Users\XeisWorks\GitHub\sevDesk` (Legacy, Tkinter/CLI) vs. `C:\Users\XeisWorks\GitHub\XW-Office` (PySide6-Neubau)
**Status:** Verifizierter Übernahmeplan. Nutzerentscheidungen vom 2026-07-25 sind eingearbeitet; die sichtbare Reisekosten-Navigation wurde aus XW-Office entfernt.

**Verbindliche Entscheidungen:**

- **Reisekosten werden nicht in XW-Office integriert.** Die Legacy-Funktion bleibt außerhalb dieses Produkts und ist kein späterer Migrationspunkt.
- **Noten- und qualitätskritischer Produktdruck bleiben bewusst auf PDF-XChange.** Acrobat und automatischer Raster-Fallback gehören nicht zum Zielpfad.
- Bei widersprüchlichen älteren Planungsdokumenten gilt der aktuelle Code-Stand als Ist-Quelle; eine alte Audit-Feststellung wird nicht ungeprüft als noch offen übernommen.

---

## 0. Methodik und Quellenlage

Diese Analyse basiert auf drei Recherchesträngen:

1. Vollständige Funktionskatalogisierung des Legacy-Repos (`sevdesk_wix_fulfillment/`, `UVA.py`, `Zusammenfassende Meldung.py`, `travel_costs/`, `wix_products/`, `Finanzonline/`, `zahlungsabgleich.py` u.a.)
2. Vollständige Katalogisierung des aktuellen XW-Office-Stands (`services/`, `ui/modules/`, `core/`, Datenmodell, Tests)
3. Synthese der **bereits existierenden 35 Planungs-Dokumente** in `markdowns/` und `docs/`

Punkt 3 ist wichtig: Es wurde in diesem Projekt bereits sehr diszipliniert dokumentiert, was übernommen wurde, was bewusst *nicht* übernommen wurde, und was noch offen ist — besonders für Rechnungen/Tagesgeschäft, Druck, Produkte, Steuern (UVA/ZM/OSS) und Zahlungsclearing. Da einzelne Auditbefunde durch spätere Commits bereits behoben wurden, werden Planungsdokumente hier immer gegen den aktuellen Code geprüft. Dieses Dokument:

- fasst deren Kernaussagen kurz zusammen (Abschnitt 2–3), mit Quellenverweis,
- konzentriert sich auf das, was in den bestehenden Docs **noch nicht oder nur am Rande behandelt wurde**: sinnvolle Legacy-Funktionen, die im Neubau fehlen, dünn sind, oder als reine UI-Mockups ohne Fachlogik existieren (Abschnitt 4 — der Hauptteil dieses Dokuments).

Alle Quellen sind in Abschnitt 8 aufgelistet.

---

## 1. Executive Summary

**Kernfrage 1 — Ist die Migration sinnvoll gelaufen?** Ja, im Kern sehr gut, mit klaren Einschränkungen:

- Der geschäftskritische Pfad (Tagesgeschäft/Rechnungen, Druck, Produkte/Inventar, PLC-Versandlabels) ist in XW-Office **reif, aktiv weiterentwickelt und in Teilen architektonisch besser als das Legacy-System** (echtes relationales Produkt-Datenmodell, DI-Container, BackgroundWorker/-JobManager statt raw Threads, HMAC-gesichertes Copilot-Ingress, Golden-Master-Validierung für Steuerberechnungen).
- Die Migrationsdisziplin ("nie blind kopieren, nur Verhalten studieren, Übernommen/Nicht-übernommen explizit dokumentieren") ist ungewöhnlich hoch und hat sich in der Praxis bewährt.
- **Aber:** mehrere früh als "DONE" deklarierte Bereiche wurden durch spätere, gründlichere Analysen widerlegt (UVA-SOAP "fertig" im April → 1.868 € Berechnungsfehler im Juli gefunden; Brand-Bulk "fertig" im Juni → Concurrency-Bugs im Juli gefunden). Das ist ein wiederkehrendes Muster, kein Einzelfall — siehe Abschnitt 2.2.
- Mehrere Architekturprinzipien, die früh sauber definiert wurden (Single-Write-Location, Pydantic-only, DI-only, Advisory-Lock bei Concurrent-Writes, max. ~800 Zeilen/Datei), werden in den am schnellsten gewachsenen Modulen bereits wieder verletzt.

**Kernfrage 2 — Welche sinnvollen Legacy-Funktionen fehlen noch?** Abschnitt 4 bewertet 15 Funktionsbereiche; nach dem bewussten Ausschluss der Reisekosten bleiben 14 mögliche Übernahmekandidaten, u. a.:

- **Ausgaben-Check**: im Neubau nur ein 89-Zeilen-Skelett, im Legacy ein ausgereiftes Reconciliation-System mit Fuzzy-Ignore-Regeln und Perioden-Verschiebung.
- **Cover-Erzeugung** und **Audio-Beispiel-Erzeugung**: im Neubau leere Platzhalter-Pakete (`services/graphics`, `services/audio`), im Legacy funktionierende Tools.
- **Druckrechte-Lizenzrechner**: existiert im Neubau an keiner Stelle.
- CRM-Merge-Absicherung, Zahlungsabgleich-Fehlerkatalog, WüdaraMusi-Zweitmandant u. a. — jeweils mit konkretem Integrationsvorschlag, der **nicht** 1:1-Portierung ist, sondern die Logik in die bestehenden XW-Office-Muster (Services, DI, Pydantic, BackgroundWorker, SettingKV/Migrations, Dry-Run/Live-Split) einbettet.

---

## 2. Gesamtbeurteilung der Migration

### 2.1 Stärken

| Stärke | Beleg |
|---|---|
| Kern-Fulfillment-Pfad ist reif und aktiv | Servicekatalog XW-Office, Migrationen 004/005 vom 23.–25.07.2026 |
| Echtes relationales Datenmodell für Produkte statt Legacy-JSON-Dateien | Migrationen 002/003 (`product`, `sku_alias`, `print_rule`, `print_plan`, `inventory_movement`) |
| Konsequente DI/BackgroundWorker-Architektur in den reifen Modulen | `core/container.py`, `core/worker.py`, `BackgroundJobManager` (Prioritätswarteschlangen, Cancel-Token) |
| Golden-Master-Validierung für Steuerlogik statt "es sieht plausibel aus" | `config/uva_reference_values.json`, `config/oss_reference_values.json`, `tests/expected/UVA *.txt` |
| Explizite "Übernommen/Nicht übernommen"-Sektionen in praktisch jedem Umbau-Dokument | z. B. `uva_ist_berechnung_umbau_2026-06-16.md`, `zahlungsclearing_book_invoice_haertung_2026-07-08.md` |
| Bewusste Architekturentscheidung, wo Legacy-Semantik *exakt* erhalten werden muss (z. B. sevDesk-Buchungsablauf) vs. wo neu gedacht wird | `zahlungsclearing_book_invoice_haertung_2026-07-08.md`: "PySide6-Flow führend für Analyse/Matching, Legacy führend für den konkreten sevDesk-Buchungsaufruf" |
| Umfangreiche automatisierte Tests und typisierte Kernmodule | `tests/`, `app_performance_gesamtanalyse_2026-07-11.md` |

### 2.2 Schwächen / Risikofelder

**a) Wiederkehrendes Muster: verfrühte "erledigt"-Meldungen, die spätere, gründlichere Analyse widerlegt.**
Die frühen Statusdokumente (`umsetzung_phasen_todo.md`, `umbau_checkliste_prioritaet.md`, beide 2026-04-02) markieren praktisch alles als DONE — inklusive "UVA SOAP live". Die Realität laut `uva_06_2026_testlauf_und_umbau_2026-07-12.md`: die Live-Berechnung wich um **1.868,04 €** von der (nutzerbestätigten) Legacy-Referenz ab, weil zwei Steuerbasen (A022, A006) komplett verloren gingen. Ähnlich beim Brand-Bulk-Feature: im Juni als "alle 6 Phasen DONE" markiert, im Juli-Audit als Quelle realer Concurrency-Bugs (K3) identifiziert. **Empfehlung für die Zukunft:** Checklisten-Status ("☑ done") nur für triviale Features vertrauen; für alles mit Geld-/Rechtsrelevanz grundsätzlich Golden-Master- oder Audit-Validierung verlangen, bevor "done" gilt.

**b) Notendruck: Auditbefund behoben, PDF-XChange ist die bewusste Zielentscheidung.**
Der Audit vom 2026-07-21 (`rechnungen_print_produkte_architektur_audit_2026-07-21.md`, Finding K1) beschrieb einen stillen, ungeprüften Acrobat-Fallback. Dieser Befund ist im aktuellen Code **nicht mehr offen**: `services/printing/pdf_backends.py` verwendet für native Profile ausschließlich PDF-XChange, prüft Prozess-Timeout und Exit-Code und verlangt eine neue Jobmeldung des ausgewählten Windows-Spoolers. Ohne Spooler-Bestätigung wird der Auftrag als Fehler behandelt und es erfolgt keine Bestandsbuchung. `CLAUDE.md` dokumentiert inzwischen genau diese Architektur. Die bewusste Produktentscheidung lautet daher nicht „zurück zu QtRaster“, sondern **PDF-XChange als vektorbasierten Notendruckpfad beibehalten**. Der Hardwaretest QA-01 bis QA-04 wurde am 2026-07-29 auf Papier abgenommen: Simplex/Duplex funktionieren, Schärfe und Zentrierung sind absolut ok.

**c) Multi-PC-Bulk-Write: Auditbefund behoben, Restdisziplin weiterhin nötig.**
Finding K3 des Audits beschrieb verlorene Updates bei Feld- und Marken-Bulkänderungen. Der aktuelle Code führt diese Änderungen über `InventoryService.update_product_fields()` und `SettingsRepository.mutate_value_json()` unter PostgreSQL-Advisory-Lock aus. Auch gezielte Bestandswerte und produktspezifische Druckkonfigurationen nutzen atomare Mutationen. Der konkrete K3-Befund ist damit **behoben**; neue Schreibpfade müssen weiterhin denselben atomaren Weg verwenden.

**d) Zwei parallele Bestandsführungen.**
`PrintDecisionEngine` (sevDesk-Bestand) und `InventoryService` (lokaler KV-Bestand) können laut Audit (Finding K2) auseinanderlaufen und beeinflussen direkt Über-/Unterdruck-Entscheidungen.

**e) Frühe Architekturprinzipien erodieren mit wachsender Codebasis.**
Beispiele aus dem Audit: `transfers`, `sendungen`, `digital_licenses` verwenden Dataclasses statt der für externe API-Antworten vorgeschriebenen Pydantic-Modelle (X5); `LabelPrinter` wird in zwei Dialogen direkt instanziiert statt über den Container aufgelöst (X4); `rechnungen/view.py` ist aktuell mit rund 4.900 Zeilen mehr als 6x über der eigenen ~800-Zeilen-Richtlinie, `products/view.py` mit 1.863 Zeilen ca. 2,3x (X7) — **dasselbe Monolith-Muster, das im Legacy-System explizit als Problem galt** (`UVA.py` 5.456 Zeilen, `ui_wix_products.py` 5.084 Zeilen), tritt im Neubau an anderer Stelle wieder auf.

**f) Steuer-Modul (UVA/ZM/OSS) ist noch nicht "abgabesicher".**
`uva_zm_gesamtanalyse_und_umbauplan_2026-07-12.md` benennt explizit 6 ungelöste P0-Grundsatzprobleme: kein validierter Snapshot-Zustandsautomat, Zahlungsdatum-Auswahl "best effort" statt kanonisches Ledger, textbasierte statt versionierte Steuer-Klassifikation, unvollständiges/hartkodiertes Kennzahlen-Modell (relevant, da sich die U30-Regeln ab Juli 2026 erneut ändern), ZM klassifiziert pro Rechnung statt pro Position, UID-Prüfung nur Format/Checksumme statt VIES-Echtzeitabfrage.

**g) Mehrere Legacy-Module existieren im Neubau nur als Platzhalter oder gar nicht.**
Siehe Abschnitt 4 im Detail: Ausgaben-Check (Skelett), WüdaraMusi (Mockup mit `_SAMPLE_PIECES`), Cover-/Audio-Erzeugung (leere Stub-Pakete). Die bisherige Reisekosten-Platzhalter-UI wird bewusst nicht als offene Lücke behandelt und ist aus der sichtbaren Navigation entfernt.

### 2.3 Gesamturteil

Die Migration des Kerngeschäfts ist **fachlich und architektonisch ein Erfolg** — insbesondere im Vergleich zur Legacy-Codequalität (Tkinter-Monolithe, `threading.Thread`, dateibasierte Caches, `float` für Geldbeträge). Sie ist aber **nicht abgeschlossen**. Die größten verifizierten Risiken liegen derzeit bei Steuer-/Abgabesicherheit und der noch nicht konsolidierten Bestandsführung; beim Notendruck und bei Bulk-Produktwrites wurden die im Audit beschriebenen Architekturabweichungen inzwischen behoben. Der vorliegende Übernahmeplan ergänzt diese Arbeit um die Dimension „welche fachlich wertvolle Legacy-Logik geht verloren, wenn sie nicht bewusst nachgezogen wird“ — mit Reisekosten als ausdrücklicher Negativentscheidung.

---

## 3. Bereits bekannte offene Punkte (Kurzrekap, siehe Originalquellen für Details)

Diese Punkte sind in bestehenden Dokumenten bereits vollständig analysiert — hier nur zur Einordnung/Vollständigkeit, **nicht neu hergeleitet**:

| Thema | Kurzstatus | Quelle |
|---|---|---|
| UVA-Berechnungskorrektheit | Nicht abgabesicher, 6 offene P0-Punkte | `uva_zm_gesamtanalyse_und_umbauplan_2026-07-12.md` |
| ZM pro-Position statt pro-Rechnung | Offen (P0) | dito |
| UID-Prüfung nur Format, keine VIES-Live-Prüfung | Offen (P0) | dito |
| Notendruck über PDF-XChange | Bewusster Zielpfad; alter Acrobat-Fallback entfernt, Exit-Code und Spooler werden geprüft; Hardwaretest QA-01 bis QA-04 am 2026-07-29 abgenommen | aktueller `services/printing/pdf_backends.py`; Audit K1 ist überholt |
| Zwei divergierende Bestandssysteme | Kritisch, offen | dito (K2) |
| Bulk-Produktschreibvorgänge | K3 behoben: gezielte Änderungen laufen atomar über `mutate_value_json()` | aktueller `InventoryService.update_product_fields()` |
| Rechnungsentwurf (Draft-Invoice) — volle Parität unklar | Letzter expliziter Stand: fehlend (April), nur vage spätere Erwähnung | `daily_business_migration_final_report.md`; `rechnungen_daily_business_ui_umbau_2026-06-30.md` |
| Partielle/Positions-Rückerstattungen UI | Plan vom 08.07. wirkt laut Audit vom 21.07. nicht ausgeliefert | `rueckerstattungen_aktionen_legacy_integration_2026-07-08.md` vs. `rechnungen_print_produkte_architektur_audit_2026-07-21.md` |
| CRM-Merge Live-Writeback | Vorhanden; es fehlen vor allem Preflight, Sperrregeln, Auditierbarkeit und robuste Verlierer-Policy | aktueller `services/crm/service.py` |
| Provisionsprofile jenseits MusikHeroes | Offen (Phase 4) | `provisionsabrechnung_musikheroes_umbau_2026-07-08.md` |
| ZM/U13 als eigener sichtbarer UI-Bereich | Offen | `zm_u13_steuer_modul_umbau_2026-07-08.md` |

**→ Empfehlung:** Diese Punkte vor oder parallel zu Abschnitt 4 angehen, da sie laufenden Geschäftsbetrieb bzw. Rechtssicherheit betreffen. Abschnitt 4 fokussiert bewusst auf zusätzliche, bisher nicht dokumentierte Funktionslücken.

---

## 4. Bewertete Legacy-Funktionen und Übernahmeentscheidungen

Für jede Funktion: Geschäftswert, Fundort im Legacy, aktueller Zustand in XW-Office, und ein Vorschlag zur **intelligenten Integration** — d. h. wie die Logik in bestehende XW-Office-Muster (Services + DI, Pydantic-Modelle, BackgroundWorker/-JobManager, SettingKV/Alembic-Migrationen, Dry-Run/Live-Split) eingebettet würde, statt Dateien zu kopieren.

### 4.0 Querschnittsempfehlung, die mehrere Punkte unten betrifft

Mehrere der folgenden Funktionen (Statistik, Ausgaben-Check, CRM-Matching, Produkte-unreleased) verwenden im Legacy jeweils **eigene** Fuzzy-Matching- bzw. Textnormalisierungs-Logik (`rapidfuzz`, `difflib.SequenceMatcher`, deutsche Umlaut-Normalisierung), mit unterschiedlichen, unkoordinierten Schwellwerten. Statt das viermal separat zu portieren, empfiehlt sich **ein gemeinsames Utility**:

- `core/text_normalize.py` — deutsche Umlaut-/Sonderzeichen-Normalisierung (ä/ö/ü/ß → ae/oe/ue/ss), Bankbuchungstext-Bereinigung (SEPA-Mandatsreferenzen, IBAN-Fragmente, Datums-/Zeitmuster entfernen)
- `core/fuzzy_match.py` — dünner Wrapper um `rapidfuzz`, mit pro Aufrufer konfigurierbarem Schwellwert, aber einheitlicher Signatur/Typisierung

Das ist kein neues Architekturkonzept, sondern nur die konsequente Anwendung des bereits etablierten "keine Duplikate, gemeinsame Utilities in `core/`"-Prinzips auf vier kommende Portierungen gleichzeitig.

Ebenso wiederverwendbar: das in `xw_copilot` bereits etablierte **Dry-Run/Live-Dispatch-Muster** (`dry_run.py` vs. `live_dispatch.py`) eignet sich hervorragend für jede Legacy-Funktion, die *automatisch* Daten in sevDesk schreibt (CRM-Merge, Ausgaben-Ignore-Regeln mit Auswirkung auf Buchhaltung) — statt für jede ein eigenes Bestätigungsmuster zu erfinden.

---

### 4.1 Ausgaben-Check — von Skelett zu echtem Reconciliation-Modul

**Geschäftswert:** Erkennt Bankbuchungen ohne zugehörigen sevDesk-Beleg (Rechnung/Gutschrift/Ausgabe) pro Monat und Mandant — eine Kontrollfunktion gegen fehlende Buchhaltungsbelege.

**Legacy:** `sevdesk_wix_fulfillment/ausgaben_check/` — ausgereift: `IgnoreManager` mit Fuzzy-Substring-Abgleich (`difflib.SequenceMatcher` Ratio ≥ 0,68) gegen normalisierten Buchungstext, sodass leicht variierende wiederkehrende Buchungen (z. B. unterschiedliche Rechnungsnummer pro Monat) erkannt werden; `ShiftManager` erlaubt das manuelle Verschieben einer Buchung in eine andere Periode bei Audit-Trail; Buchungstext-Normalisierung speziell auf österreichische Bankauszugsformate zugeschnitten (SEPA-Mandatsreferenzen, IBAN-Fragmente, Datums-/Zeitmuster).

**XW-Office-Zustand:** `services/expenses/service.py` ist laut eigenem Docstring explizit ein "skeleton" (89 Zeilen) — nur DB-Liste, Filter, CSV-Export. Keine Klassifikations-, Ignore- oder Shift-Logik.

**Integrationsvorschlag:**
- `IgnoreRule` und `ShiftEntry` als **echte Tabellen** modellieren (neue Alembic-Migration, analog zum PLC-Audit-Trail-Muster aus Migration 004), nicht als flache JSON-Dateien wie im Legacy — das bringt Multi-PC-Sync automatisch mit, was die Legacy-Variante nie hatte.
- Da der inzwischen behobene Auditbefund K3 gezeigt hat, wie leicht komplette KV-Listen bei konkurrierenden Schreibzugriffen verloren gehen: für Ausgaben-Check von Anfang an echte Tabellen statt `SettingKV`-JSON verwenden, nicht erneut eine gemeinsam überschriebene Gesamtliste einführen.
- Fuzzy-Match-Schwellwert und Normalisierungs-Regex als getestete, reine Funktionen in `core/text_normalize.py`/`core/fuzzy_match.py` (siehe 4.0) — wiederverwendbar für CRM und Produkte-unreleased.
- Aktionen (`ignore_once`, `ignore_forever`, `shift`, `flag`) als kleines State-Machine-Enum am `ExpenseCheckEntry`-Modell, nicht als lose Strings wie im Legacy.

**Priorität:** P1 — reales, im Alltag genutztes Kontrollinstrument, aktuell komplett unwirksam (nur Anzeige, keine Fachlogik).

---

### 4.2 Reisekosten (Travel Costs) — bewusst ausgeschlossen

**Entscheidung:** Reisekosten werden **nicht** in XW-Office integriert. Die Qualität oder Wiederverwendbarkeit des Legacy-Moduls ändert diese Produktentscheidung nicht.

**Konsequenzen für XW-Office:**

- kein Sidebar-Eintrag und keine Dashboard-Karte,
- keine Lazy-Page-Registrierung in `MainWindow`,
- kein Git-Submodul, kein Bridge-Import und keine Datenmigration,
- keine Reisekosten-Tabellen, Secrets oder Google-Distance-Matrix-Abhängigkeiten,
- keine Aufnahme in Priorisierung, Aufwandsschätzung oder Definition of Done dieses Plans.

Der vorhandene Legacy-Code in `C:\Users\XeisWorks\GitHub\sevDesk\travel_costs\` bleibt eine separate historische bzw. eigenständige Anwendung. Im XW-Office-Quellbaum noch vorhandene, nicht registrierte Bridge-Dateien sind kein zugesagtes Feature und können in einer späteren, rein technischen Bereinigung entfernt werden.

**Priorität:** **OUT OF SCOPE / NICHT ÜBERNEHMEN.**

---

### 4.3 Cover-Erzeugung (Graphics Service)

**Geschäftswert:** Automatisierte Erzeugung von Produkt-Titelbildern (Komponist/Titel/Arrangeur/Ausgabe-Text-Overlay) für den Notenkatalog.

**Legacy:** `sevdesk_wix_fulfillment/graphics/cover_creator.py` — Text-Overlay auf Hintergrundbild, mehrere Layoutmodi, automatischer Textumbruch.
**XW-Office-Zustand:** `services/graphics/` ist wörtlich `"""Service placeholder."""` — leer.

**Integrationsvorschlag:** Als `CoverGeneratorService` implementieren, der in die bestehende `services/layout`-PDF-Pipeline eingehängt wird (gleiche Font-/Asset-Auflösung wiederverwenden statt duplizieren), und konzeptionell als **Asset-Resolver-Schritt** in der bereits im `product_pipeline_masterplan.md` definierten Pipeline-Architektur verankert wird (dort explizit als zukünftiger Baustein vorgesehen) — statt als isoliertes Einzeltool wie im Legacy. Auslösung über eine "Cover erzeugen"-Aktion im Produkte-Modul, per BackgroundWorker (Bildgenerierung blockiert sonst die UI).

**Priorität:** P2 — sinnvolle Vervollständigung des Produkt-Workflows, aber kein täglicher Blocker.

---

### 4.4 Audio-Beispiel-Erzeugung (Audio Service)

**Geschäftswert:** Erzeugt standardisierte Hörbeispiele aus Audio-/Videoquellen für Produktlistings.

**Legacy:** `sevdesk_wix_fulfillment/audio_examples/generator.py` — ffmpeg-Pipeline (mp3/wav/mp4/mkv → Hörbeispiel), mit hartkodierter Pfadnormalisierung für einige bekannte Windows-Benutzerprofile (OneDrive-Pfad-Hack).
**XW-Office-Zustand:** `services/audio/` ist ebenfalls ein leerer Platzhalter.

**Integrationsvorschlag:** `AudioExampleService` als ffmpeg-Subprozess-Wrapper, nach demselben defensiven Subprozess-Muster wie der bereits vorhandene isolierte Outlook-COM-Composer (`outlook_compose.py`: Timeout, nicht-blockierend via BackgroundWorker, strukturierte Fehlerrückgabe). Die hartkodierte Pfad-Normalisierung für bekannte Benutzernamen **nicht** übernehmen — stattdessen das bereits vorhandene `core/shared_paths.py` (Multi-PC-OneDrive-Pfadauflösung) nutzen, das genau dieses Problem bereits sauber löst.

**Priorität:** P2 — wie Cover-Erzeugung, sinnvolle Ergänzung, kein Blocker.

---

### 4.5 Druckrechte-Lizenzrechner

**Geschäftswert:** Berechnet die an einen Rechteinhaber zu zahlende Lizenzgebühr für Notendruck, basierend auf Stimmenanzahl pro Instrument, Nettopreis, Rechte-Prozentsatz, Titel-pro-Kapelle und einer Liste geschützter Titel, mit Mindestgebühren-Untergrenze.

**Legacy:** `sevdesk_wix_fulfillment/ui/kalkulation_app.py`, Abschnitt "Druckrechte" innerhalb "Provision & Kalkulation".
**XW-Office-Zustand:** `services/calculation/service.py` (allgemeine Provisions-/Tantiemenberechnung) und `services/commission/service.py` (sevDesk-gestützte Provisionsberechnung mit Profilen) decken beide etwas anderes ab — keiner der beiden modelliert den spezifischen Druckrechte-Lizenzgebühren-Fall mit Mindestgebühr und geschützter-Titel-Liste. Diese Funktion scheint im Neubau **an keiner Stelle** zu existieren.

**Integrationsvorschlag:** Als reines, I/O-freies Berechnungsmodul `services/calculation/print_rights.py` mit Pydantic-Request/-Result (`PrintRightsRequest`/`PrintRightsResult`) — vollständig unit-testbar ohne Mocking. UI-seitig kein neues Sidebar-Modul, sondern ein zusätzlicher Bereich/Tab im bestehenden `ui/modules/calculation/view.py`, konsistent mit der übrigen Provisions-/Kalkulationsfunktion. Die Liste geschützter Titel über `SettingKV` persistieren (wie andere Konfigurationsdaten im Neubau), nicht als eigene JSON-Datei wie im Legacy.

**Priorität:** P2 — klar begrenzter Funktionsumfang, aber aktuell schlicht nicht vorhanden; sollte nachgezogen werden, sobald diese Berechnung wieder gebraucht wird.

---

### 4.6 CRM: Match-Kaskade mit Begründung, Merge-Verbotsregeln, Legacy-Nummern-Erhalt

**Geschäftswert:** Zuverlässiges, nachvollziehbares Zusammenführen doppelter sevDesk-Kontakte (entstanden aus Jahren manueller Rechnungserstellung + Wix-Import), ohne versehentlich Rechnungen an falsche/gesperrte Kontakte umzuhängen.

**Legacy:** `sevdesk_wix_fulfillment/crm/crm_engine.py` — mehrstufige Match-Kaskade mit **benannten Konfidenzgründen** (`wixCustomerId-unique` = hohe Konfidenz bei eindeutigem Custom-Field-Match, `highest-customerNumber` = mittlere Konfidenz als Fallback); beim Merge werden problematische Rechnungen (finalisiert/"enshrined", `invoiceDate < deliveryDate`, nicht-numerische Referenz) **vom Verschieben ausgeschlossen und mit Grund protokolliert**, statt den ganzen Merge abzubrechen; konfigurierbare Verlierer-Behandlung (löschen wenn ohne Dokumente möglich, sonst archivieren mit Namenspräfix `[MERGED]`, oder nur ignorieren); Legacy-Kundennummern des Verlierers werden am Gewinner für die Nachvollziehbarkeit hinterlegt.
**XW-Office-Zustand:** `services/crm/matching.py` verwendet paarweises `rapidfuzz`-Scoring (Namens-Token-Sort + Bonus für E-Mail/Telefon-Match). Anders als im ersten Entwurf angenommen ist der Live-Writeback inzwischen vorhanden: `CrmService.merge_contacts()` delegiert bei konfiguriertem `ContactClient` an sevDesk. Noch nicht sichtbar sind jedoch die Legacy-Preflight-Sperrregeln, eine begründete Match-Kaskade, ein vollständiger Merge-Report und eine konfigurierbare Verlierer-Policy.

**Integrationsvorschlag:**
- Die Kaskade nicht als eine monolithische Funktion portieren, sondern als Abfolge benannter `MatchStrategy`-Implementierungen (E-Mail-exakt, WixCustomerId-Lookup, Fuzzy-Fallback aus 4.0), jede mit typisiertem `MatchResult(confidence, reason)` — erhält die im Legacy wertvolle "warum wurde gematcht"-Nachvollziehbarkeit, ohne die Kaskade als Ganzes zu duplizieren.
- Vor dem bereits aktiven Live-Writeback: die Legacy-Sperrregeln (enshrined, `invoiceDate < deliveryDate`) als **Preflight-Validierung** implementieren, die dem Nutzer einen Report zur Bestätigung zeigt, bevor irgendetwas geschrieben wird — das ist exakt das bereits in `xw_copilot` etablierte Dry-Run/Live-Split-Muster (4.0), hier wiederverwendet statt neu erfunden.
- Verlierer-Behandlung (löschen/archivieren/ignorieren) als konfigurierbare Policy analog zum Legacy, aber über `SettingKV`/Config statt Merge-Config-Datei.

**Priorität:** P1 — betrifft Datenintegrität in der zentralen Kundenverwaltung; die Absicherung des bereits vorhandenen Live-Writebacks ist dringender als zusätzliche Match-Komfortfunktionen.

---

### 4.7 Zahlungsabgleich: Fehlerkatalog, SEPA-Fenster, Mollie-OAuth

**Geschäftswert:** Vollständige, nachvollziehbare Zahlungszuordnung — inkl. der Fälle, die *nicht* automatisch zugeordnet werden können.

**Legacy:** `zahlungsabgleich.py`/`payments.py` — über 30 benannte Skip-/Fehlergründe (`mollie_currency`, `mollie_settlements_oauth_required`, `stripe_refund`, `rechnungsentwurf`, `provider_id_collision`, `booked_tx_ambiguous` u. v. a.) — praktisch eine dokumentierte Sammlung aller in 2+ Jahren Produktivbetrieb aufgetretenen Grenzfälle; SEPA-Überweisungen erhalten ein breiteres Nachschlagefenster (`SEPA_LOOKBACK_DAYS = 45`) als Karten-/PSP-Zahlungen, da sie langsamer verbucht werden; `PAYMENT_EPS = 0.005` als Toleranz für Betragsvergleiche; **Mollie-Payouts benötigen zwingend OAuth** (API-Key allein reicht laut Legacy-Fehlercode nicht).
**XW-Office-Zustand:** `services/clearing/` ist bereits mit `Decimal`, Gateway-pro-Anbieter-Abstraktion und typisiertem `MatchStatus` neu aufgesetzt. Kandidaten enthalten sichtbare Freitext-Begründungen; Refund- und Payout-Fälle werden grundsätzlich unterschieden. Nicht vorhanden sind ein vollständiger typisierter Legacy-Fehlerkatalog und ein Mollie-OAuth-Flow. Der aktuelle Mollie-Gateway versucht Settlements mit dem vorhandenen Client und degradiert Fehler auf eine leere Settlement-Liste; dadurch kann ein Authentifizierungsproblem fachlich zu wenig sichtbar bleiben.

**Integrationsvorschlag:**
- Den 30+-Fehlerkatalog nicht erst über Monate erneut in der Produktion "wiederentdecken" lassen, sondern direkt als typisiertes `ClearingSkipReason`-Enum (ggf. ein kleineres Enum pro Gateway) aus dem Legacy-Katalog übernehmen, an `ClearingResult` hängen und in der Clearing-UI sichtbar machen — schließt gleichzeitig die im Audit vom 21.07. genannte Lücke (PP-M1: Jobergebnisse geben aktuell kein Feedback).
- SEPA-Lookback-Fenster als konfigurierbare Konstante pro Gateway übernehmen statt hartkodiert.
- Mollie-OAuth-Flow für Payouts explizit in `MollieClearingGateway` einbauen und fehlende Berechtigung als eigenen sichtbaren Fehlergrund melden — ohne ihn können reale Mollie-Settlements strukturell nicht zuverlässig abgeglichen werden.

**Priorität:** P1 — direkt zahlungsrelevant, aber kein Neubau des Clearing-Moduls: vorhandene Status-/Reason-Struktur erweitern, Mollie-Authentifizierung härten und mit Legacy-Grenzfällen testen.

---

### 4.8 B2B-Banküberweisungs-Referenzextraktion

**Geschäftswert:** Ordnet direkte SEPA-Überweisungen (B2B, ohne Wix-Bezug) automatisch sevDesk-Rechnungen zu, indem die 6-stellige Rechnungsnummer (mit Jahres-Präfix) aus dem Verwendungszweck extrahiert wird.

**Legacy:** `b2b-bank-transfer.py` — Regex-Extraktion, Normalisierung auf `RE-NNNNNN`, monatliches Caching.
**XW-Office-Zustand:** Der direkte SEPA-Scan existiert bereits im Clearing, ist aber auf **5-stellige Wix-Ordernummern** ausgelegt (`_ORDER_NUMBER` in `services/clearing/service.py`). Die Legacy-B2B-Logik sucht dagegen 6-stellige Rechnungsnummern, prüft zulässige Jahrespräfixe, normalisiert auf `RE-NNNNNN` und unterstützt mehrere Rechnungen in einer Überweisung. Diese fachlich andere Variante fehlt.

**Integrationsvorschlag:** Eine sichere, reine Funktion `extract_b2b_invoice_numbers(purpose: str, year_prefixes: set[str]) -> tuple[str, ...]` im Clearing-Kontext ergänzen. Sie darf nicht mit dem bestehenden Wix-Ordernummern-Parser vermischt werden. Mehrfachzuordnungen müssen nur dann automatisch freigegeben werden, wenn die Summe der offenen Rechnungen exakt zum Überweisungsbetrag passt. Die bereits im Legacy-Repo vorhandenen zwei Jahre gecachter Verwendungszwecke (`sevDesk/json/b2b-bank-transfer-*.json`) eignen sich als anonymisierte **Testfixtures**, nicht als Laufzeitdaten.

**Priorität:** P1 — die Lücke ist verifiziert und zahlungsrelevant; der reine Parser ist klein, die sichere Mehrfachzuordnung braucht jedoch eigene Tests.

---

### 4.9 SKU-Regelwerk konsolidieren (Sonderanfertigungen, Besetzungs-Labels, B2B/B2C-Klassifikation)

**Geschäftswert:** Drei kleine, aber geschäftskritische Konventionen: (1) Sonderanfertigungs-SKUs (`XW-600.x`) mit Komponisten-Auswahl + Freitext-Stücktitel aus Wix-Custom-Feld, (2) SKU-Präfix → Besetzungs-Label-Zuordnung für Packzettel, (3) die Konvention "Referenznummer beginnt mit 2 → B2C, beginnt mit 1 → B2B", die quer durch Fulfillment, Rückerstattungen und PLC-Labeling verwendet wird.

**Legacy:** `sevdesk_wix_fulfillment/rules/sku_rules.py` + verstreute Prüfungen in `services/invoice_processor.py` — bereits im Legacy **ad hoc über mehrere Dateien verteilt**, nicht zentralisiert.
**XW-Office-Zustand:** Teilweise vorhanden: `XW-600.0` gehört zu den konfigurierbaren Sonder-SKUs; Wix-Optionen liefern Besetzungsdaten, und der Rechnungsbereich zeigt sie an. Eine zentrale `B2B`/`B2C`-Klassifikation anhand des Referenzpräfixes wurde im Neubau nicht gefunden. Die vorhandenen Regeln sind außerdem über Wix-, Rechnungs- und Produktcode verteilt.

**Integrationsvorschlag:** Als explizite, benannte, testbare Regel-Objekte in `services/products/classification_rules.py` bündeln — **einmal** definiert, von allen drei Konsumenten (Fulfillment, Rückerstattung, PLC) referenziert, statt wie im Legacy an drei Stellen einzeln nachgebaut. Das behebt gleichzeitig einen Legacy-eigenen Schwachpunkt (Streuung), nicht nur eine Neubau-Lücke.

**Priorität:** P1 — gezielt die fehlende B2B/B2C-Klassifikation und die Zentralisierung angehen; vorhandene Sonder-SKU- und Besetzungslogik nicht doppelt implementieren.

---

### 4.10 WüdaraMusi — Zweitmandant statt Parallel-Stack

**Geschäftswert:** Kontaktverwaltung für den zweiten sevDesk-Account ("WüdaraMusi").

**Legacy:** OCR- + KI-gestützte Kontaktextraktion aus gescannten Belegen, Fuzzy-Matching (`rapidfuzz.token_set_ratio`) gegen bestehende Kontakte des zweiten Mandanten, Upsert mit Diff-Anzeige bei Unklarheit.
**XW-Office-Zustand:** `ui/modules/wuedaramusi/view.py` ist reines UI-Mockup mit `_SAMPLE_PIECES`-Platzhalterdaten, expliziter In-App-Hinweis "Status: Migration aus Altprojekt laufend", keine Backing-Service.

**Integrationsvorschlag:** Keinen zweiten, parallelen CRM-Stack für WüdaraMusi bauen. Stattdessen den ohnehin für 4.6 überarbeiteten `services/crm/` **mandantenfähig** machen (ein `SevdeskAccount`-Konzept, das die bereits vorhandene Pro-Integration-Konfiguration im Container aufgreift) — WüdaraMusi wird dann einfach ein zweiter konfigurierter Account, der dieselben `MatchStrategy`-Klassen nutzt. Das macht aus "ein ganzes separates Legacy-Modul portieren" die deutlich kleinere Aufgabe "Multi-Tenancy zu einem Modul hinzufügen, das ohnehin überarbeitet wird."

**Priorität:** P3 — abhängig davon, wie aktiv WüdaraMusi aktuell noch genutzt wird; strategisch sinnvoll, aber kein Blocker.

---

### 4.11 ClickUp-Aufgaben & Google-Kalender aus Copilot

**Geschäftswert:** Automatische Aufgaben-/Termin-Erstellung direkt aus E-Mail-Kontext heraus.

**Legacy:** `copilot/clickup.py` (vorhanden im Neubau, minimal getestet) + `copilot/google_calendar.py` (im Neubau **nicht gefunden**).
**Integrationsvorschlag:** Falls dieser Workflow noch im Alltag genutzt wird: `services/calendar/` nach demselben OAuth-Muster, das für MS Graph bereits bewährt ist (`services/mailing/graph_client.py`, MSAL Device-Flow) — Googles Device-Flow ist strukturell sehr ähnlich, es handelt sich also eher um "bewährtes Muster auf zweiten Anbieter anwenden" als um neue Architektur.

**Priorität:** P3 — abhängig von tatsächlicher Nutzungshäufigkeit im Alltag.

---

### 4.12 Produkte-unreleased — Freitext-Matching für Vorab-Titel

**Geschäftswert:** Ordnet Freitext-Bestellzeilen (z. B. Auftragswerke, die vor Katalogisierung verkauft werden) einer kleinen, handgepflegten Liste noch nicht veröffentlichter Stücke inkl. Komponist/Eigentümer zu.

**Legacy:** `products_unreleased/matcher.py` — `rapidfuzz`, Auto-Match-Schwelle 85, bis zu 5 Kandidaten bei Unklarheit.
**XW-Office-Zustand:** Eine partielle Kennzeichnung existiert: Wix-Positionen mit Präfix `XW-600`/`XW-010` werden als `is_unreleased` markiert und im Druckworkflow besonders behandelt. Es fehlt aber das Legacy-Äquivalent für eine handgepflegte Titelliste ohne verlässliche SKU sowie die fuzzy Kandidatenauswahl mit manueller Bestätigung.

**Integrationsvorschlag:** "Unreleased" als Lifecycle-Status (`status: released | unreleased | preview`) am bereits existierenden `Product`-Modell (Migration 002 hat bereits eine echte Produkttabelle) statt einer separaten parallelen JSON-Liste + eigenem Matcher. Freitext-Matching nutzt die gleiche gemeinsame Fuzzy-Match-Utility aus 4.0 — nicht eine dritte, separat parametrisierte `rapidfuzz`-Aufrufstelle.

**Priorität:** P2.

---

### 4.13 Wix→sevDesk Teilenamen-Abkürzungsassistent

**Geschäftswert:** Automatische Ableitung kurzer sevDesk-Teilenamen/SKUs aus langen Wix-Produkttiteln beim Anlegen neuer Katalogteile, inkl. domänenspezifischer Kategorien-Rangfolge (Musikkapelle, Sinfonisches Blasorchester, Mnozil Brass, "da Blechhauf'n" etc.).

**Legacy:** `wix_products/ui_wix_products.py` — hartkodiertes Abkürzungswörterbuch + Kategorien-Ranking.
**Integrationsvorschlag:** Niedrige Priorität — eine Komfortfunktion für die Content-Erstellung, keine Kernlogik. Falls gewünscht: Abkürzungstabelle als statische Konfigurationsdatei (`config/part_name_abbreviations.yaml`, analog zu `config/commission_profiles.yaml`) statt hartkodiertem Dict, aufgerufen aus einer manuellen "Teil aus Wix-Produkt anlegen"-Aktion — bewusst nicht automatisch, da eine Namensableitung menschlich bestätigt werden sollte.

**Priorität:** P3.

---

### 4.14 FinanzOnline DataBox-Protokoll-/Belegabruf

**Geschäftswert:** Abruf der Einreichungsprotokolle/PDF-Bestätigungen aus der FinanzOnline-DataBox nach einer UVA-Einreichung, für die Compliance-Ablage.

**Legacy:** vorhanden.
**XW-Office-Zustand:** Laut `finanzonline_uva_fileupload_umbau_2026-06-17.md` **bewusst nicht übernommen** ("DataBox-Download-als-Pflichtschritt" explizit verworfen) — das ist im Unterschied zu allen anderen Punkten in diesem Abschnitt keine Lücke, sondern eine **getroffene Entscheidung**.

**Integrationsvorschlag:** Nicht die Pflichtschritt-Variante zurückholen, aber den reinen **Bestätigungsprotokoll-Abruf** (nicht blockierend, nur für die Ablage) erneut erwägen — der SOAP-Client dafür existiert bereits, der Zusatzaufwand wäre gering, der Compliance-Nutzen (Nachweis der erfolgreichen Einreichung) real.

**Priorität:** P3 — bewusst niedrig, da ursprünglich absichtlich weggelassen; nur als Ergänzung, nicht als Korrektur zu verstehen.

---

### 4.15 Statistik-Modul vertiefen

**Geschäftswert:** Verkaufsanalyse-Dashboard mit Zeitraumvergleich.

**Legacy:** `sevdesk_wix_fulfillment/statistik/` — sauber faktorisiert, reine Funktionen: Umschalten der Analyseachse zwischen Rechnungs- und Zahlungsdatum, vorzeichenbewusste Aggregation (Gutschriften/Retouren gehen automatisch negativ in die Summe ein, über ein `record.sign`-Konzept), deutsche Textnormalisierung für Freitextsuche.
**XW-Office-Zustand:** `services/statistics/service.py` ist laut Katalog das "am wenigsten komplexe" Finanzmodul, ohne dedizierten Unit-Test.

**Integrationsvorschlag:** Datum-Modus (Rechnungsdatum/Zahlungsdatum) als Enum-Parameter der Service-Methode statt globaler Konfiguration; Vorzeichen-Logik nicht als Kopie von `record.sign`, sondern als berechnete Property auf einem pydantic `StatisticsRecord`, abgeleitet aus dem sevDesk-Dokumenttyp; deutsche Textnormalisierung aus der gemeinsamen Utility (4.0); Export über die bereits vorhandene `services/layout`-PDF-Fassade statt eines eigenen Exporters.

**Priorität:** P2 — geringes Risiko, guter Nutzen, kleiner Umsetzungsaufwand (Legacy-Code ist bereits sauber genug, um als direkte Vorlage für die *Struktur* zu dienen, auch wenn er nicht kopiert wird).

---

## 5. Was explizit NICHT übernommen werden soll (Anti-Patterns)

Diese Muster sind im Legacy-System klar erkennbar problematisch und sollten bei keiner der obigen Portierungen wiederholt werden — die meisten wurden im Neubau bereits bewusst vermieden, werden hier der Vollständigkeit halber und als Erinnerung für Punkt 4 festgehalten:

- **Tkinter-UI-Struktur und -Zustandshaltung** — keine 1:1-Fensterlogik übernehmen.
- **`threading.Thread` direkt** — immer `BackgroundWorker`/`BackgroundJobManager`.
- **`float` für Geldbeträge** — immer `Decimal` (im Clearing-Modul bereits korrekt umgesetzt, als Vorbild für alle Punkte in Abschnitt 4 mit Geldbezug, insbesondere 4.5 und 4.7).
- **Dateibasierte JSON-Zustände für alles, was Multi-PC-Sync braucht** (Ignore-Listen, Snapshot-Stufen, Merge-Konfiguration) — echte Tabellen oder `SettingKV`, nie lokale Dateien.
- **Monolithische Einzeldateien** (`UVA.py` 5.456 Zeilen, `ui_wix_products.py` 5.084 Zeilen, `invoice_processor.py` 3.168 Zeilen) — hier besonders zu betonen, weil der Neubau selbst bereits in diese Falle zurückgefallen ist (`rechnungen/view.py`, 4.764 Zeilen, siehe 2.2e). Bei jeder Portierung aus Abschnitt 4 von Anfang an in fokussierte Module aufteilen, nicht erst nachträglich.
- **Einzelne globale Boolean-Flag-Datei** (`config_flags.py`, eine Zeile) — die vorhandene YAML-/`.env`-/DB-Konfigurationsstruktur konsequent weiterverwenden, keine Parallelstruktur für neue Flags schaffen.
- **Ad-hoc-Diagnose-Skripte im Repo-Root** (`dump_open_invoices.py`, `debug_invoice_chain.py`, `wix_fulfillment_debug.py` etc.) — als Entwicklerwerkzeuge okay, aber nicht mit Architektur verwechseln; falls vergleichbare Diagnosewerkzeuge im Neubau gebraucht werden, gehören sie nach `scripts/`, nicht in die Service-Schicht.
- **Verstreute, unbenannte Ad-hoc-Regeln** (SKU-Präfix-Konventionen quer über mehrere Dateien, siehe 4.9) — auch wenn dies ein Legacy-Muster ist: es sollte bei der Portierung *behoben*, nicht mitübernommen werden.
- **Reisekosten als XW-Office-Modul** — weder Domain-Code noch UI, Bridge, Submodul oder Persistence übernehmen; siehe verbindliche Entscheidung 4.2.
- **Acrobat als automatischer Notendruck-Fallback** — PDF-XChange bleibt der bewusst gewählte Vektorpfad. Ein Fehler muss sichtbar abbrechen und darf keine Bestandsbuchung auslösen; ein Qualitätswechsel auf Raster darf nicht still erfolgen.

---

## 6. Übergreifende Architektur-Empfehlungen für die Umsetzung von Abschnitt 4

1. **Vor jeder neuen Portierung den konkreten Teilumfang erneut am Code abgrenzen.** Die Nachprüfung dieses Plans hat bereits mehrere Teilimplementierungen gefunden (CRM-Live-Writeback, Clearing-Reason-Strings, Unreleased-Kennzeichnung, Sonder-SKU-/Besetzungslogik). Umgesetzt werden nur die jeweils ausdrücklich als fehlend beschriebenen Teile, nicht der ganze Legacy-Block.
2. **Golden-Master-Prinzip auf neue Portierungen ausweiten**, überall dort, wo eine Legacy-Zahl/-Entscheidung als Referenz vorliegt (Druckrechte-Rechner, Zahlungsabgleich-Kategorisierung) — nach dem in Steuer-/OSS-Modulen bereits etablierten Muster, gerade weil Checklisten-"done" sich in diesem Projekt wiederholt als trügerisch erwiesen hat (2.2a).
3. **Dry-Run/Live-Split (aus `xw_copilot`) als Standardmuster für jede Portierung mit Schreibwirkung** (CRM-Merge, Ausgaben-Ignore-Regeln, SKU-Regelwerk-Änderungen an Fulfillment) etablieren, statt für jede Funktion einzeln ein Bestätigungsmuster neu zu entwerfen.
4. **Dateigrößen-Richtlinie technisch durchsetzen, nicht nur dokumentieren** — z. B. ein einfacher CI-Check/Lint-Regel, der bei Überschreiten der ~800-Zeilen-Grenze warnt, da die rein dokumentarische Regel bereits zweimal überschritten wurde (Legacy und `rechnungen/view.py`). Das ist keine Empfehlung aus Abschnitt 4, aber eine Voraussetzung dafür, dass die dort vorgeschlagenen neuen Module nicht denselben Weg gehen.
5. **Gemeinsame `core`-Utilities zuerst bauen (4.0), dann die vier/fünf abhängigen Funktionen (4.1, 4.6, 4.12, teilweise 4.15) darauf aufsetzen** — vermeidet, dieselbe Fuzzy-Match-/Normalisierungslogik erneut viermal einzeln zu portieren.

---

## 7. Vorgeschlagene Priorisierung (Reihenfolge)

**P0 — vor allem Weiteren (bereits in bestehenden Docs identifiziert, hier nur zur Einordnung, siehe Abschnitt 3):**
Steuerkorrektheit (UVA/ZM/OSS) und Konsolidierung der zwei Bestandsquellen (K2). PDF-XChange-/Spooler-Regressionstests bleiben eine Betriebsanforderung, sind aber keine offene Legacy-Portierung. K1 und K3 sind im aktuellen Code behoben.

**P1 — hoher Geschäftswert, aktuell fehlend oder unwirksam (Kern dieses Dokuments):**
4.1 Ausgaben-Check, 4.6 CRM-Merge-Absicherung, 4.7 Zahlungsabgleich-Fehlerkatalog/Mollie-OAuth, 4.8 B2B-Rechnungsreferenzen, 4.9 gezielte SKU-/B2B-B2C-Regelkonsolidierung.

**P2 — Vervollständigung, moderater Aufwand:**
4.3 Cover-Erzeugung, 4.4 Audio-Beispiele, 4.5 Druckrechte-Rechner, 4.12 Produkte-unreleased-Freitextmatching, 4.15 Statistik-Vertiefung.

**P3 — sinnvoll, aber klar nachrangig:**
4.10 WüdaraMusi-Mandantenfähigkeit, 4.11 Google-Kalender-Integration, 4.13 Wix-Abkürzungsassistent, 4.14 FinanzOnline-DataBox-Protokollabruf.

**Nicht einplanen:**
4.2 Reisekosten.

---

## 8. Quellenverzeichnis

**Bestehende Analyse-Dokumente (chronologisch), referenziert in Abschnitt 2–3:**

- `docs/copilot_migration_plan.md` (2026-04-03)
- `docs/sevdesk_daily_business_analysis.md`, `docs/sevdesk_daily_business_quick_reference.md` (2026-04)
- `docs/daily_business_parity_analysis.md`, `docs/daily_business_parity_test_results.md`, `docs/daily_business_migration_final_report.md`, `docs/recommendations_and_quick_wins.md` (2026-04-04)
- `docs/umbau_checkliste_prioritaet.md`, `docs/umsetzung_phasen_todo.md` (2026-04-02)
- `docs/product_pipeline_masterplan.md` (2026-04-03)
- `markdowns/copilot_remaining_phases.md` (2026-04-03)
- `markdowns/start_button_rechnungen_analyse_2026-05-22.md`, `markdowns/sevdesk_sendviaemail_mailstrategie_2026-05-22.md` (2026-05-22)
- `markdowns/zahlungsclearing_umbauphasen_2026-06-12.md` (2026-06-12)
- `markdowns/produkte_brand_bulk_umbauplan.md`, `markdowns/produkte_brand_bulk_bedienung.md` (2026-06-10/12)
- `markdowns/uva_ist_berechnung_umbau_2026-06-16.md` (2026-06-16)
- `markdowns/finanzonline_uva_fileupload_umbau_2026-06-17.md`, `markdowns/zm_u13_integration_2026-06-17.md` (2026-06-17)
- `markdowns/wix_cache_umbau_2026-06-19.md` (2026-06-19)
- `markdowns/post_label_center_webservice_bauplan_2026-06-24.md` (2026-06-24)
- `markdowns/rechnungen_daily_business_ui_umbau_2026-06-30.md` (2026-06-30)
- `markdowns/rechnungen_performance_umbau_2026-07-01.md` (2026-07-01)
- `markdowns/a5_verdoppeln_auf_a4_migration_2026-07-06.md`, `markdowns/rechnungen_overview_refactor_2026-07-06.md` (2026-07-06)
- `markdowns/klick_performance_analyse_2026-07-08.md`, `markdowns/rueckerstattungen_aktionen_legacy_integration_2026-07-08.md`, `markdowns/provisionsabrechnung_musikheroes_umbau_2026-07-08.md`, `markdowns/zahlungsclearing_book_invoice_haertung_2026-07-08.md`, `markdowns/zm_u13_steuer_modul_umbau_2026-07-08.md`, `markdowns/eu_oss_integration_recherche_2026-07-08.md` (2026-07-08)
- `markdowns/offene_ueberweisungen_pyside6_umbauskizze_2026-07-10.md` (2026-07-10)
- `markdowns/app_performance_gesamtanalyse_2026-07-11.md`, `markdowns/drucksystem_plc_noten_produkte_verbesserungsplan_2026-07-11.md`, `markdowns/sonderanfertigungen_digitale_lizenzen_wix_umbauskizze_2026-07-11.md` (2026-07-11)
- `markdowns/uva_zm_gesamtanalyse_und_umbauplan_2026-07-12.md`, `markdowns/uva_06_2026_testlauf_und_umbau_2026-07-12.md`, `markdowns/eu_oss_gesamtanalyse_und_umbauplan_2026-07-12.md` (2026-07-12)
- `markdowns/drucksystem_offene_hardware_backend_punkte_2026-07-13.md` (2026-07-13, aktualisiert 07-16/18)
- `markdowns/produktdruckplaene_rechnungen_umbauskizze_2026-07-18.md` (2026-07-18)
- `markdowns/rechnungen_print_produkte_architektur_audit_2026-07-21.md` (2026-07-21, jüngstes und für Abschnitt 2 wichtigstes Dokument)

**Nicht direkt migrationsrelevant, nur zur Vollständigkeit geprüft:** `markdowns/XeisWorks_Content_Studio_*.md` (neues, separates Content-Studio-Projekt, keine Legacy-Portierung), `markdowns/widerrufsbutton-online-notenversand-at.md` (reine Rechtsrecherche zum Wix-Storefront, kein Code-Bezug).

**Codebasis-Fundstellen (Legacy):** `sevdesk_wix_fulfillment/` (gesamtes Paket inkl. `ui/`, `services/`, `crm/`, `ausgaben_check/`, `copilot/`, `statistik/`, `rules/`, `graphics/`, `audio_examples/`, `notes_layout/`, `printing/`, `inventory/`), `UVA.py`, `Zusammenfassende Meldung.py`, `matching.py`, `payments.py`, `zahlungsabgleich.py`, `b2b-bank-transfer.py`, `travel_costs/`, `wix_products/`, `products_unreleased/`, `Finanzonline/`.

**Codebasis-Fundstellen (XW-Office):** `src/xw_office/services/*`, `src/xw_office/ui/modules/*`, `src/xw_office/core/*`, `src/xw_office/models/*`, `src/xw_office/repositories/*`, `src/xw_office/migrations/versions/*`, `tests/unit/*`, `tests/ui/*`.
