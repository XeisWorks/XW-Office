# Legacy → XW-Studio: Gesamtanalyse der Migration und Übernahmeplan für verbleibende Funktionen

**Datum:** 2026-07-25
**Scope:** Vergleich `C:\Users\XeisWorks\GitHub\sevDesk` (Legacy, Tkinter/CLI) vs. `C:\Users\XeisWorks\GitHub\XW-Studio` (PySide6-Neubau)
**Status:** Analyse/Skizze — **keine Code-Umsetzung**, keine offenen Fragen an den Nutzer. Alle Empfehlungen sind Vorschläge zur Priorisierung durch den Nutzer.

---

## 0. Methodik und Quellenlage

Diese Analyse basiert auf drei parallelen Recherchen:

1. Vollständige Funktionskatalogisierung des Legacy-Repos (`sevdesk_wix_fulfillment/`, `UVA.py`, `Zusammenfassende Meldung.py`, `travel_costs/`, `wix_products/`, `Finanzonline/`, `zahlungsabgleich.py` u.a.)
2. Vollständige Katalogisierung des aktuellen XW-Studio-Stands (`services/`, `ui/modules/`, `core/`, Datenmodell, Tests)
3. Synthese der **bereits existierenden 35 Planungs-Dokumente** in `markdowns/` und `docs/`

Punkt 3 ist wichtig: Es wurde in diesem Projekt bereits sehr diszipliniert dokumentiert, was übernommen wurde, was bewusst *nicht* übernommen wurde, und was noch offen ist — besonders für Rechnungen/Tagesgeschäft, Druck, Produkte, Steuern (UVA/ZM/OSS) und Zahlungsclearing. Dieses Dokument **wiederholt diese Analysen nicht**, sondern:

- fasst deren Kernaussagen kurz zusammen (Abschnitt 2–3), mit Quellenverweis,
- konzentriert sich auf das, was in den bestehenden Docs **noch nicht oder nur am Rande behandelt wurde**: sinnvolle Legacy-Funktionen, die im Neubau fehlen, dünn sind, oder als reine UI-Mockups ohne Fachlogik existieren (Abschnitt 4 — der Hauptteil dieses Dokuments).

Alle Quellen sind in Abschnitt 8 aufgelistet.

---

## 1. Executive Summary

**Kernfrage 1 — Ist die Migration sinnvoll gelaufen?** Ja, im Kern sehr gut, mit klaren Einschränkungen:

- Der geschäftskritische Pfad (Tagesgeschäft/Rechnungen, Druck, Produkte/Inventar, PLC-Versandlabels) ist in XW-Studio **reif, aktiv weiterentwickelt und in Teilen architektonisch besser als das Legacy-System** (echtes relationales Produkt-Datenmodell, DI-Container, BackgroundWorker/-JobManager statt raw Threads, HMAC-gesichertes Copilot-Ingress, Golden-Master-Validierung für Steuerberechnungen).
- Die Migrationsdisziplin ("nie blind kopieren, nur Verhalten studieren, Übernommen/Nicht-übernommen explizit dokumentieren") ist ungewöhnlich hoch und hat sich in der Praxis bewährt.
- **Aber:** mehrere früh als "DONE" deklarierte Bereiche wurden durch spätere, gründlichere Analysen widerlegt (UVA-SOAP "fertig" im April → 1.868 € Berechnungsfehler im Juli gefunden; Brand-Bulk "fertig" im Juni → Concurrency-Bugs im Juli gefunden). Das ist ein wiederkehrendes Muster, kein Einzelfall — siehe Abschnitt 2.2.
- Mehrere Architekturprinzipien, die früh sauber definiert wurden (Single-Write-Location, Pydantic-only, DI-only, Advisory-Lock bei Concurrent-Writes, max. ~800 Zeilen/Datei), werden in den am schnellsten gewachsenen Modulen bereits wieder verletzt.

**Kernfrage 2 — Welche sinnvollen Legacy-Funktionen fehlen noch?** Abschnitt 4 listet 15 konkrete Kandidaten, u.a.:

- **Ausgaben-Check**: im Neubau nur ein 89-Zeilen-Skelett, im Legacy ein ausgereiftes Reconciliation-System mit Fuzzy-Ignore-Regeln und Perioden-Verschiebung.
- **Reisekosten**: im Neubau eine reine Platzhalter-UI, die auf ein nicht vorhandenes Submodul wartet — im Legacy bereits die architektonisch fortschrittlichste Komponente überhaupt (hexagonal, mit Domain/Adapter/Persistence-Trennung).
- **Cover-Erzeugung** und **Audio-Beispiel-Erzeugung**: im Neubau leere Platzhalter-Pakete (`services/graphics`, `services/audio`), im Legacy funktionierende Tools.
- **Druckrechte-Lizenzrechner**: existiert im Neubau an keiner Stelle.
- CRM-Merge-Kaskade, Zahlungsabgleich-Fehlerkatalog, WüdaraMusi-Zweitmandant, u.a. — jeweils mit konkretem Integrationsvorschlag, der **nicht** 1:1-Portierung ist, sondern die Logik in die bestehenden XW-Studio-Muster (Services, DI, Pydantic, BackgroundWorker, SettingKV/Migrations, Dry-Run/Live-Split) einbettet.

---

## 2. Gesamtbeurteilung der Migration

### 2.1 Stärken

| Stärke | Beleg |
|---|---|
| Kern-Fulfillment-Pfad ist reif und aktiv (jüngste 5 Commits alle PLC-bezogen) | Servicekatalog XW-Studio, Migrationen 004/005 vom 23.–25.07.2026 |
| Echtes relationales Datenmodell für Produkte statt Legacy-JSON-Dateien | Migrationen 002/003 (`product`, `sku_alias`, `print_rule`, `print_plan`, `inventory_movement`) |
| Konsequente DI/BackgroundWorker-Architektur in den reifen Modulen | `core/container.py`, `core/worker.py`, `BackgroundJobManager` (Prioritätswarteschlangen, Cancel-Token) |
| Golden-Master-Validierung für Steuerlogik statt "es sieht plausibel aus" | `config/uva_reference_values.json`, `config/oss_reference_values.json`, `tests/expected/UVA *.txt` |
| Explizite "Übernommen/Nicht übernommen"-Sektionen in praktisch jedem Umbau-Dokument | z. B. `uva_ist_berechnung_umbau_2026-06-16.md`, `zahlungsclearing_book_invoice_haertung_2026-07-08.md` |
| Bewusste Architekturentscheidung, wo Legacy-Semantik *exakt* erhalten werden muss (z. B. sevDesk-Buchungsablauf) vs. wo neu gedacht wird | `zahlungsclearing_book_invoice_haertung_2026-07-08.md`: "PySide6-Flow führend für Analyse/Matching, Legacy führend für den konkreten sevDesk-Buchungsaufruf" |
| 94 Testdateien, mypy --strict auf 14 Modulen sauber | `app_performance_gesamtanalyse_2026-07-11.md` |

### 2.2 Schwächen / Risikofelder

**a) Wiederkehrendes Muster: verfrühte "erledigt"-Meldungen, die spätere, gründlichere Analyse widerlegt.**
Die frühen Statusdokumente (`umsetzung_phasen_todo.md`, `umbau_checkliste_prioritaet.md`, beide 2026-04-02) markieren praktisch alles als DONE — inklusive "UVA SOAP live". Die Realität laut `uva_06_2026_testlauf_und_umbau_2026-07-12.md`: die Live-Berechnung wich um **1.868,04 €** von der (nutzerbestätigten) Legacy-Referenz ab, weil zwei Steuerbasen (A022, A006) komplett verloren gingen. Ähnlich beim Brand-Bulk-Feature: im Juni als "alle 6 Phasen DONE" markiert, im Juli-Audit als Quelle realer Concurrency-Bugs (K3) identifiziert. **Empfehlung für die Zukunft:** Checklisten-Status ("☑ done") nur für triviale Features vertrauen; für alles mit Geld-/Rechtsrelevanz grundsätzlich Golden-Master- oder Audit-Validierung verlangen, bevor "done" gilt.

**b) Architektur-Dokumentation und Implementierung laufen auseinander — ausgerechnet an der kritischsten Stelle.**
`CLAUDE.md` (dieses Repo) beschreibt den Druckpfad noch als "PDF-XChange nativ und vektorbasiert … kein automatischer Acrobat- oder Raster-Fallback". Der Audit vom 2026-07-21 (`rechnungen_print_produkte_architektur_audit_2026-07-21.md`, Finding K1) zeigt: der Notendruck läuft inzwischen über einen PDF-XChange-CLI-Subprozess mit einem **stillen, ungeprüften Acrobat-Fallback** (kein `.wait()`, kein Exit-Code-Check) — ohne automatischen Rückfall auf den dokumentierten sicheren QtRaster-Pfad. Das bedeutet: ein Lizenz-/Update-Dialog von Acrobat kann zu **stillem Nichtdrucken führen, das die App als Erfolg loggt.** Das ist der wirtschaftlich sensibelste Pfad der ganzen App (Notendruck = Kerngeschäft) und der einzige, bei dem Dokumentation und Praxis so weit auseinanderlaufen.

**c) Multi-PC-Sync — ein zentrales Architekturversprechen — hat einen nachgewiesenen Bruch.**
Bulk-Schreiboperationen am Produktkatalog umgehen laut Audit (Finding K3) den etablierten `mutate_value_json()`-Advisory-Lock-Mechanismus. Damit können zwei PCs sich gegenseitig überschreiben — genau das, was "Multi-PC sync via PostgreSQL" (laut `CLAUDE.md`) verhindern soll.

**d) Zwei parallele Bestandsführungen.**
`PrintDecisionEngine` (sevDesk-Bestand) und `InventoryService` (lokaler KV-Bestand) können laut Audit (Finding K2) auseinanderlaufen und beeinflussen direkt Über-/Unterdruck-Entscheidungen.

**e) Frühe Architekturprinzipien erodieren mit wachsender Codebasis.**
Beispiele aus dem Audit: `transfers`, `sendungen`, `digital_licenses` verwenden Dataclasses statt der vorgeschriebenen Pydantic-Modelle (X5); `LabelPrinter` wird in zwei Dialogen direkt instanziiert statt über den Container aufgelöst (X4); `rechnungen/view.py` ist mit 4.764 Zeilen ca. 6x über der eigenen ~800-Zeilen-Richtlinie, `products/view.py` mit 1.863 Zeilen ca. 2,3x (X7) — **dasselbe Monolith-Muster, das im Legacy-System explizit als Problem galt** (`UVA.py` 5.456 Zeilen, `ui_wix_products.py` 5.084 Zeilen), tritt im Neubau an anderer Stelle wieder auf.

**f) Steuer-Modul (UVA/ZM/OSS) ist noch nicht "abgabesicher".**
`uva_zm_gesamtanalyse_und_umbauplan_2026-07-12.md` benennt explizit 6 ungelöste P0-Grundsatzprobleme: kein validierter Snapshot-Zustandsautomat, Zahlungsdatum-Auswahl "best effort" statt kanonisches Ledger, textbasierte statt versionierte Steuer-Klassifikation, unvollständiges/hartkodiertes Kennzahlen-Modell (relevant, da sich die U30-Regeln ab Juli 2026 erneut ändern), ZM klassifiziert pro Rechnung statt pro Position, UID-Prüfung nur Format/Checksumme statt VIES-Echtzeitabfrage.

**g) Mehrere Legacy-Module existieren im Neubau nur als Platzhalter oder gar nicht.**
Siehe Abschnitt 4 im Detail: Ausgaben-Check (Skelett), Reisekosten (Platzhalter-UI), WüdaraMusi (Mockup mit `_SAMPLE_PIECES`), Cover-/Audio-Erzeugung (leere Stub-Pakete).

### 2.3 Gesamturteil

Die Migration des Kerngeschäfts ist **fachlich und architektonisch ein Erfolg** — insbesondere im Vergleich zur Legacy-Codequalität (Tkinter-Monolithe, `threading.Thread`, dateibasierte Caches, `float` für Geldbeträge). Sie ist aber **nicht abgeschlossen**: Die größten verbleibenden Risiken liegen nicht in "fehlenden Features" im klassischen Sinn, sondern darin, dass ausgerechnet die drei sensibelsten Pfade — Steuererklärung, Notendruck, Mehr-PC-Schreibzugriff — von der eigenen dokumentierten Architektur abweichen. Diese sind in bestehenden Dokumenten bereits identifiziert (Abschnitt 3) und sollten vor neuen Funktionsübernahmen priorisiert werden. Der vorliegende Übernahmeplan (Abschnitt 4) ergänzt diese Arbeit um die Dimension "welche fachlich wertvolle Legacy-Logik geht verloren, wenn sie nicht bewusst nachgezogen wird."

---

## 3. Bereits bekannte offene Punkte (Kurzrekap, siehe Originalquellen für Details)

Diese Punkte sind in bestehenden Dokumenten bereits vollständig analysiert — hier nur zur Einordnung/Vollständigkeit, **nicht neu hergeleitet**:

| Thema | Kurzstatus | Quelle |
|---|---|---|
| UVA-Berechnungskorrektheit | Nicht abgabesicher, 6 offene P0-Punkte | `uva_zm_gesamtanalyse_und_umbauplan_2026-07-12.md` |
| ZM pro-Position statt pro-Rechnung | Offen (P0) | dito |
| UID-Prüfung nur Format, keine VIES-Live-Prüfung | Offen (P0) | dito |
| Notendruck-Backend weicht von Dokumentation ab, kein Fallback-Netz | Kritisch, offen | `rechnungen_print_produkte_architektur_audit_2026-07-21.md` (K1) |
| Zwei divergierende Bestandssysteme | Kritisch, offen | dito (K2) |
| Bulk-Produktschreibvorgänge umgehen Advisory-Lock | Kritisch, offen | dito (K3) |
| Rechnungsentwurf (Draft-Invoice) — volle Parität unklar | Letzter expliziter Stand: fehlend (April), nur vage spätere Erwähnung | `daily_business_migration_final_report.md`; `rechnungen_daily_business_ui_umbau_2026-06-30.md` |
| Partielle/Positions-Rückerstattungen UI | Plan vom 08.07. wirkt laut Audit vom 21.07. nicht ausgeliefert | `rueckerstattungen_aktionen_legacy_integration_2026-07-08.md` vs. `rechnungen_print_produkte_architektur_audit_2026-07-21.md` |
| CRM-Merge Live-Writeback | Stand April: "in-memory merge; live writeback follows" — keine spätere Bestätigung gefunden | `umsetzung_phasen_todo.md` |
| Provisionsprofile jenseits MusikHeroes | Offen (Phase 4) | `provisionsabrechnung_musikheroes_umbau_2026-07-08.md` |
| ZM/U13 als eigener sichtbarer UI-Bereich | Offen | `zm_u13_steuer_modul_umbau_2026-07-08.md` |

**→ Empfehlung:** Diese Punkte vor oder parallel zu Abschnitt 4 angehen, da sie laufenden Geschäftsbetrieb bzw. Rechtssicherheit betreffen. Abschnitt 4 fokussiert bewusst auf zusätzliche, bisher nicht dokumentierte Funktionslücken.

---

## 4. Sinnvolle Legacy-Funktionen, die noch zu übernehmen sind

Für jede Funktion: Geschäftswert, Fundort im Legacy, aktueller Zustand in XW-Studio, und ein Vorschlag zur **intelligenten Integration** — d. h. wie die Logik in bestehende XW-Studio-Muster (Services + DI, Pydantic-Modelle, BackgroundWorker/-JobManager, SettingKV/Alembic-Migrationen, Dry-Run/Live-Split) eingebettet würde, statt Dateien zu kopieren.

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

**XW-Studio-Zustand:** `services/expenses/service.py` ist laut eigenem Docstring explizit ein "skeleton" (89 Zeilen) — nur DB-Liste, Filter, CSV-Export. Keine Klassifikations-, Ignore- oder Shift-Logik.

**Integrationsvorschlag:**
- `IgnoreRule` und `ShiftEntry` als **echte Tabellen** modellieren (neue Alembic-Migration, analog zum PLC-Audit-Trail-Muster aus Migration 004), nicht als flache JSON-Dateien wie im Legacy — das bringt Multi-PC-Sync automatisch mit, was die Legacy-Variante nie hatte.
- Da der Audit vom 21.07. gezeigt hat, dass KV-Store-Schreibzugriffe ohne konsequenten Advisory-Lock zu Bugs führen (Finding K3): für Ausgaben-Check von Anfang an echte Tabellen statt `SettingKV`-JSON verwenden, nicht das gleiche Risiko ein weiteres Mal einbauen.
- Fuzzy-Match-Schwellwert und Normalisierungs-Regex als getestete, reine Funktionen in `core/text_normalize.py`/`core/fuzzy_match.py` (siehe 4.0) — wiederverwendbar für CRM und Produkte-unreleased.
- Aktionen (`ignore_once`, `ignore_forever`, `shift`, `flag`) als kleines State-Machine-Enum am `ExpenseCheckEntry`-Modell, nicht als lose Strings wie im Legacy.

**Priorität:** P1 — reales, im Alltag genutztes Kontrollinstrument, aktuell komplett unwirksam (nur Anzeige, keine Fachlogik).

---

### 4.2 Reisekosten (Travel Costs) — Domain-Layer übernehmen, Persistence & UI neu

**Geschäftswert:** Reisekostenabrechnung (Kilometergeld, Fahrgemeinschaften, Tourenplanung) für Musiker bei Proben/Auftritten — regelmäßig genutzter Abrechnungsprozess.

**Legacy:** `travel_costs/` ist mit Abstand die architektonisch fortschrittlichste Komponente im gesamten Legacy-Repo — bereits hexagonal aufgebaut (`domain/`, `adapters/`, `persistence/`, `services/`, `ui/`), mit einer klaren 7-Stufen-Pipeline (`raw → clean → ready → reviewed → tour → carpool → final`), konfigurierbaren Prüfregeln (`ReviewService`), austauschbaren Distanz-Providern (Dummy für Tests vs. echte Google-Maps-Distance-Matrix-API) und manuell überschreibbaren Tour-/Fahrgemeinschafts-Zuordnungen mit eigenem Audit-Trail. Bereits als **externe** PySide6-App aus dem Tkinter-Fenster heraus gestartet — d. h. UI-technisch bereits nicht mehr Tkinter. Allerdings selbst noch mitten in einer "Strangler Fig"-Migration: `adapters/legacy_bundle.py` schiebt Aufrufe an ein noch älteres, gebündeltes Tool mit eigener `.venv` weiter.
**XW-Studio-Zustand:** `ui/modules/travel_costs/view.py` versucht dynamisch ein externes `reisekosten`-Submodul zu importieren (`reisekosten.bridge:create_widget` o. ä.), das in diesem Checkout **nicht vorhanden** ist (kein `.gitmodules`-Eintrag) — fällt auf einen deutschsprachigen Platzhaltertext zurück. Laut `copilot_migration_plan.md` als "Phase 4" vertagt.

**Integrationsvorschlag:** Dies ist der einzige Fall im gesamten Vergleich, bei dem **direktere Übernahme statt Neuentwicklung** empfohlen wird — und zwar gezielt nur der `domain/`-Schicht, weil diese bereits framework-agnostisch ist (keine Tkinter-Abhängigkeit, reine Geschäftslogik: Kilometergeld-Berechnung, Touren-/Fahrgemeinschafts-Splitting, Stufen-Pipeline):
- `domain/` möglichst unverändert als eigenes Package unter `services/travel_costs/domain/` übernehmen.
- `persistence/` (aktuell nummerierte JSON-Snapshot-Dateien pro Stufe) durch echte Tabellen ersetzen — das ist der eine echte Schwachpunkt der sonst guten Legacy-Architektur (kein Multi-PC-Sync), und exakt das Problem, das XW-Studios Postgres-Architektur lösen soll.
- `adapters/legacy_bundle.py` (die zweite, ältere Legacy-Schicht) **nicht mitnehmen** — die Strangler-Fig-Migration jetzt zu Ende führen, statt einen zweifach verschachtelten Legacy-Wrapper zu erben.
- `ui/` komplett neu in PySide6 nach denselben Mustern wie Rechnungen/Produkte (DataTable, BackgroundWorker, bestehende Dialog-Patterns) — nicht das externe Fenster-Konzept übernehmen, sondern als reguläres Sidebar-Modul.
- Google-Maps-Distance-Matrix-Integration nach dem gleichen Provider-Pattern wie andere externe HTTP-Clients (`services/http_client.py`) einbinden, `DummyDistanceMatrixClient` für Tests direkt mitnehmen (guter, bereits vorhandener Test-Baustein).

**Priorität:** P1 — größter noch fehlender Funktionsblock mit echtem, regelmäßigem Nutzungsbedarf; mehrwöchiger Aufwand, aber der wiederverwendbare Anteil (Domain-Logik) reduziert ihn erheblich gegenüber einer Neuentwicklung von Null.

---

### 4.3 Cover-Erzeugung (Graphics Service)

**Geschäftswert:** Automatisierte Erzeugung von Produkt-Titelbildern (Komponist/Titel/Arrangeur/Ausgabe-Text-Overlay) für den Notenkatalog.

**Legacy:** `sevdesk_wix_fulfillment/graphics/cover_creator.py` — Text-Overlay auf Hintergrundbild, mehrere Layoutmodi, automatischer Textumbruch.
**XW-Studio-Zustand:** `services/graphics/` ist wörtlich `"""Service placeholder."""` — leer.

**Integrationsvorschlag:** Als `CoverGeneratorService` implementieren, der in die bestehende `services/layout`-PDF-Pipeline eingehängt wird (gleiche Font-/Asset-Auflösung wiederverwenden statt duplizieren), und konzeptionell als **Asset-Resolver-Schritt** in der bereits im `product_pipeline_masterplan.md` definierten Pipeline-Architektur verankert wird (dort explizit als zukünftiger Baustein vorgesehen) — statt als isoliertes Einzeltool wie im Legacy. Auslösung über eine "Cover erzeugen"-Aktion im Produkte-Modul, per BackgroundWorker (Bildgenerierung blockiert sonst die UI).

**Priorität:** P2 — sinnvolle Vervollständigung des Produkt-Workflows, aber kein täglicher Blocker.

---

### 4.4 Audio-Beispiel-Erzeugung (Audio Service)

**Geschäftswert:** Erzeugt standardisierte Hörbeispiele aus Audio-/Videoquellen für Produktlistings.

**Legacy:** `sevdesk_wix_fulfillment/audio_examples/generator.py` — ffmpeg-Pipeline (mp3/wav/mp4/mkv → Hörbeispiel), mit hartkodierter Pfadnormalisierung für einige bekannte Windows-Benutzerprofile (OneDrive-Pfad-Hack).
**XW-Studio-Zustand:** `services/audio/` ist ebenfalls ein leerer Platzhalter.

**Integrationsvorschlag:** `AudioExampleService` als ffmpeg-Subprozess-Wrapper, nach demselben defensiven Subprozess-Muster wie der bereits vorhandene isolierte Outlook-COM-Composer (`outlook_compose.py`: Timeout, nicht-blockierend via BackgroundWorker, strukturierte Fehlerrückgabe). Die hartkodierte Pfad-Normalisierung für bekannte Benutzernamen **nicht** übernehmen — stattdessen das bereits vorhandene `core/shared_paths.py` (Multi-PC-OneDrive-Pfadauflösung) nutzen, das genau dieses Problem bereits sauber löst.

**Priorität:** P2 — wie Cover-Erzeugung, sinnvolle Ergänzung, kein Blocker.

---

### 4.5 Druckrechte-Lizenzrechner

**Geschäftswert:** Berechnet die an einen Rechteinhaber zu zahlende Lizenzgebühr für Notendruck, basierend auf Stimmenanzahl pro Instrument, Nettopreis, Rechte-Prozentsatz, Titel-pro-Kapelle und einer Liste geschützter Titel, mit Mindestgebühren-Untergrenze.

**Legacy:** `sevdesk_wix_fulfillment/ui/kalkulation_app.py`, Abschnitt "Druckrechte" innerhalb "Provision & Kalkulation".
**XW-Studio-Zustand:** `services/calculation/service.py` (allgemeine Provisions-/Tantiemenberechnung) und `services/commission/service.py` (sevDesk-gestützte Provisionsberechnung mit Profilen) decken beide etwas anderes ab — keiner der beiden modelliert den spezifischen Druckrechte-Lizenzgebühren-Fall mit Mindestgebühr und geschützter-Titel-Liste. Diese Funktion scheint im Neubau **an keiner Stelle** zu existieren.

**Integrationsvorschlag:** Als reines, I/O-freies Berechnungsmodul `services/calculation/print_rights.py` mit Pydantic-Request/-Result (`PrintRightsRequest`/`PrintRightsResult`) — vollständig unit-testbar ohne Mocking. UI-seitig kein neues Sidebar-Modul, sondern ein zusätzlicher Bereich/Tab im bestehenden `ui/modules/calculation/view.py`, konsistent mit der übrigen Provisions-/Kalkulationsfunktion. Die Liste geschützter Titel über `SettingKV` persistieren (wie andere Konfigurationsdaten im Neubau), nicht als eigene JSON-Datei wie im Legacy.

**Priorität:** P2 — klar begrenzter Funktionsumfang, aber aktuell schlicht nicht vorhanden; sollte nachgezogen werden, sobald diese Berechnung wieder gebraucht wird.

---

### 4.6 CRM: Match-Kaskade mit Begründung, Merge-Verbotsregeln, Legacy-Nummern-Erhalt

**Geschäftswert:** Zuverlässiges, nachvollziehbares Zusammenführen doppelter sevDesk-Kontakte (entstanden aus Jahren manueller Rechnungserstellung + Wix-Import), ohne versehentlich Rechnungen an falsche/gesperrte Kontakte umzuhängen.

**Legacy:** `sevdesk_wix_fulfillment/crm/crm_engine.py` — mehrstufige Match-Kaskade mit **benannten Konfidenzgründen** (`wixCustomerId-unique` = hohe Konfidenz bei eindeutigem Custom-Field-Match, `highest-customerNumber` = mittlere Konfidenz als Fallback); beim Merge werden problematische Rechnungen (finalisiert/"enshrined", `invoiceDate < deliveryDate`, nicht-numerische Referenz) **vom Verschieben ausgeschlossen und mit Grund protokolliert**, statt den ganzen Merge abzubrechen; konfigurierbare Verlierer-Behandlung (löschen wenn ohne Dokumente möglich, sonst archivieren mit Namenspräfix `[MERGED]`, oder nur ignorieren); Legacy-Kundennummern des Verlierers werden am Gewinner für die Nachvollziehbarkeit hinterlegt.
**XW-Studio-Zustand:** `services/crm/matching.py` — paarweises `rapidfuzz`-Scoring (Namens-Token-Sort + Bonus für E-Mail/Telefon-Match), laut eigenem README "O(n²), für überschaubare Kontaktlisten ok". Laut `umsetzung_phasen_todo.md` (April) war der Merge zu diesem Zeitpunkt "in-memory merge; live writeback follows" — kein späteres Dokument bestätigt, dass das Live-Schreiben nach sevDesk seither umgesetzt wurde.

**Integrationsvorschlag:**
- Die Kaskade nicht als eine monolithische Funktion portieren, sondern als Abfolge benannter `MatchStrategy`-Implementierungen (E-Mail-exakt, WixCustomerId-Lookup, Fuzzy-Fallback aus 4.0), jede mit typisiertem `MatchResult(confidence, reason)` — erhält die im Legacy wertvolle "warum wurde gematcht"-Nachvollziehbarkeit, ohne die Kaskade als Ganzes zu duplizieren.
- Bevor Live-Writeback aktiviert wird: die Legacy-Sperrregeln (enshrined, `invoiceDate < deliveryDate`) als **Preflight-Validierung** implementieren, die dem Nutzer einen Report zur Bestätigung zeigt, bevor irgendetwas geschrieben wird — das ist exakt das bereits in `xw_copilot` etablierte Dry-Run/Live-Split-Muster (4.0), hier wiederverwendet statt neu erfunden.
- Verlierer-Behandlung (löschen/archivieren/ignorieren) als konfigurierbare Policy analog zum Legacy, aber über `SettingKV`/Config statt Merge-Config-Datei.

**Priorität:** P1 — betrifft Datenintegrität in der zentralen Kundenverwaltung; falls Live-Writeback tatsächlich noch fehlt, ist das die dringendere Teil-Lücke.

---

### 4.7 Zahlungsabgleich: Fehlerkatalog, SEPA-Fenster, Mollie-OAuth

**Geschäftswert:** Vollständige, nachvollziehbare Zahlungszuordnung — inkl. der Fälle, die *nicht* automatisch zugeordnet werden können.

**Legacy:** `zahlungsabgleich.py`/`payments.py` — über 30 benannte Skip-/Fehlergründe (`mollie_currency`, `mollie_settlements_oauth_required`, `stripe_refund`, `rechnungsentwurf`, `provider_id_collision`, `booked_tx_ambiguous` u. v. a.) — praktisch eine dokumentierte Sammlung aller in 2+ Jahren Produktivbetrieb aufgetretenen Grenzfälle; SEPA-Überweisungen erhalten ein breiteres Nachschlagefenster (`SEPA_LOOKBACK_DAYS = 45`) als Karten-/PSP-Zahlungen, da sie langsamer verbucht werden; `PAYMENT_EPS = 0.005` als Toleranz für Betragsvergleiche; **Mollie-Payouts benötigen zwingend OAuth** (API-Key allein reicht laut Legacy-Fehlercode nicht).
**XW-Studio-Zustand:** `services/clearing/` — bereits mit `Decimal` statt `float` neu aufgesetzt (laut `zahlungsclearing_umbauphasen_2026-06-12.md`), Gateway-pro-Anbieter-Abstraktion (`MollieClearingGateway`, `StripeClearingGateway`, `SevdeskClearingGateway`, `WixClearingGateway`) — solide Grundlage, aber ob der Legacy-Fehlerkatalog und der Mollie-OAuth-Flow bereits vollständig übernommen wurden, ist unklar.

**Integrationsvorschlag:**
- Den 30+-Fehlerkatalog nicht erst über Monate erneut in der Produktion "wiederentdecken" lassen, sondern direkt als typisiertes `ClearingSkipReason`-Enum (ggf. ein kleineres Enum pro Gateway) aus dem Legacy-Katalog übernehmen, an `ClearingResult` hängen und in der Clearing-UI sichtbar machen — schließt gleichzeitig die im Audit vom 21.07. genannte Lücke (PP-M1: Jobergebnisse geben aktuell kein Feedback).
- SEPA-Lookback-Fenster als konfigurierbare Konstante pro Gateway übernehmen statt hartkodiert.
- Mollie-OAuth-Flow für Payouts explizit in `MollieClearingGateway` einbauen, falls noch nicht vorhanden — ohne ihn können reale Mollie-Settlements strukturell nicht abgeglichen werden, das ist keine Komfortfunktion, sondern eine echte Funktionslücke, falls sie besteht.

**Priorität:** P0/P1 — direkt zahlungsrelevant; genaue Lückenbestimmung (was ist schon da) sollte vor Umsetzung kurz geprüft werden, da `services/clearing/` bereits eine solide Basis hat.

---

### 4.8 B2B-Banküberweisungs-Referenzextraktion

**Geschäftswert:** Ordnet direkte SEPA-Überweisungen (B2B, ohne Wix-Bezug) automatisch sevDesk-Rechnungen zu, indem die 6-stellige Rechnungsnummer (mit Jahres-Präfix) aus dem Verwendungszweck extrahiert wird.

**Legacy:** `b2b-bank-transfer.py` — Regex-Extraktion, Normalisierung auf `RE-NNNNNN`, monatliches Caching.
**XW-Studio-Zustand:** `services/transfers/service.py` (Offene Überweisungen) deckt laut Katalog primär mail-gestützten Abgleich ab — ob der direkte Verwendungszweck-Scan (unabhängig von E-Mails) bereits als Fallback existiert, ist unklar.

**Integrationsvorschlag:** Falls nicht vorhanden: kleine, sichere, reine Funktion `extract_invoice_reference(purpose: str) -> str | None` in `services/transfers/`, als Fallback-Matcher, wenn der primäre (mail-basierte) Weg keine Referenz liefert. Die bereits im Legacy-Repo vorhandenen zwei Jahre gecachter Verwendungszwecke (`sevDesk/json/b2b-bank-transfer-*.json`) eignen sich hervorragend als **Testfixtures**, nicht als Laufzeitdaten.

**Priorität:** P2 — kleiner, risikoarmer Nachtrag, sofern die Lücke tatsächlich besteht.

---

### 4.9 SKU-Regelwerk konsolidieren (Sonderanfertigungen, Besetzungs-Labels, B2B/B2C-Klassifikation)

**Geschäftswert:** Drei kleine, aber geschäftskritische Konventionen: (1) Sonderanfertigungs-SKUs (`XW-600.x`) mit Komponisten-Auswahl + Freitext-Stücktitel aus Wix-Custom-Feld, (2) SKU-Präfix → Besetzungs-Label-Zuordnung für Packzettel, (3) die Konvention "Referenznummer beginnt mit 2 → B2C, beginnt mit 1 → B2B", die quer durch Fulfillment, Rückerstattungen und PLC-Labeling verwendet wird.

**Legacy:** `sevdesk_wix_fulfillment/rules/sku_rules.py` + verstreute Prüfungen in `services/invoice_processor.py` — bereits im Legacy **ad hoc über mehrere Dateien verteilt**, nicht zentralisiert.
**XW-Studio-Zustand:** `services/products/print_decision.py`/`catalog.py` modellieren SKU-/Druckregeln bereits generisch, aber unklar, ob die B2C/B2B-Präfixkonvention und die Sonderanfertigungs-/Besetzungsregeln bereits (und wo) abgebildet sind. Genau die Art von "klein, leicht zu vergessen, aber tragend" Regel, die bei einer Neuentwicklung stillschweigend verloren gehen kann.

**Integrationsvorschlag:** Als explizite, benannte, testbare Regel-Objekte in `services/products/classification_rules.py` bündeln — **einmal** definiert, von allen drei Konsumenten (Fulfillment, Rückerstattung, PLC) referenziert, statt wie im Legacy an drei Stellen einzeln nachgebaut. Das behebt gleichzeitig einen Legacy-eigenen Schwachpunkt (Streuung), nicht nur eine Neubau-Lücke.

**Priorität:** P1 — falls diese Konventionen im Neubau tatsächlich fehlen, ist das ein stiller Korrektheitsrisiko in Fulfillment/PLC/Rückerstattung, nicht nur eine fehlende Komfortfunktion. Sollte kurzfristig verifiziert werden.

---

### 4.10 WüdaraMusi — Zweitmandant statt Parallel-Stack

**Geschäftswert:** Kontaktverwaltung für den zweiten sevDesk-Account ("WüdaraMusi").

**Legacy:** OCR- + KI-gestützte Kontaktextraktion aus gescannten Belegen, Fuzzy-Matching (`rapidfuzz.token_set_ratio`) gegen bestehende Kontakte des zweiten Mandanten, Upsert mit Diff-Anzeige bei Unklarheit.
**XW-Studio-Zustand:** `ui/modules/wuedaramusi/view.py` ist reines UI-Mockup mit `_SAMPLE_PIECES`-Platzhalterdaten, expliziter In-App-Hinweis "Status: Migration aus Altprojekt laufend", keine Backing-Service.

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
**XW-Studio-Zustand:** Die neue Produkt-Pipeline ist grundsätzlich SKU-basiert (`ProductCatalogService`); ob es ein Äquivalent für Titel ohne SKU gibt, ist unklar.

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
**XW-Studio-Zustand:** Laut `finanzonline_uva_fileupload_umbau_2026-06-17.md` **bewusst nicht übernommen** ("DataBox-Download-als-Pflichtschritt" explizit verworfen) — das ist im Unterschied zu allen anderen Punkten in diesem Abschnitt keine Lücke, sondern eine **getroffene Entscheidung**.

**Integrationsvorschlag:** Nicht die Pflichtschritt-Variante zurückholen, aber den reinen **Bestätigungsprotokoll-Abruf** (nicht blockierend, nur für die Ablage) erneut erwägen — der SOAP-Client dafür existiert bereits, der Zusatzaufwand wäre gering, der Compliance-Nutzen (Nachweis der erfolgreichen Einreichung) real.

**Priorität:** P3 — bewusst niedrig, da ursprünglich absichtlich weggelassen; nur als Ergänzung, nicht als Korrektur zu verstehen.

---

### 4.15 Statistik-Modul vertiefen

**Geschäftswert:** Verkaufsanalyse-Dashboard mit Zeitraumvergleich.

**Legacy:** `sevdesk_wix_fulfillment/statistik/` — sauber faktorisiert, reine Funktionen: Umschalten der Analyseachse zwischen Rechnungs- und Zahlungsdatum, vorzeichenbewusste Aggregation (Gutschriften/Retouren gehen automatisch negativ in die Summe ein, über ein `record.sign`-Konzept), deutsche Textnormalisierung für Freitextsuche.
**XW-Studio-Zustand:** `services/statistics/service.py` ist laut Katalog das "am wenigsten komplexe" Finanzmodul, ohne dedizierten Unit-Test.

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

---

## 6. Übergreifende Architektur-Empfehlungen für die Umsetzung von Abschnitt 4

1. **Vor jeder neuen Portierung: kurz verifizieren, was tatsächlich schon existiert.** Mehrere Punkte in Abschnitt 4 (4.7 Zahlungsabgleich-Fehlerkatalog, 4.8 B2B-Referenzextraktion, 4.9 SKU-Regelwerk) sind als "unklar, ob bereits vorhanden" markiert — die vorliegende Analyse basiert auf Servicenamen/Docstrings, nicht auf vollständiger Codeprüfung jeder Methode. Ein kurzer, gezielter Check (z. B. Grep auf die genannten Legacy-Begriffe/Konstanten im Neubau) vor Umsetzungsbeginn spart Doppelarbeit.
2. **Golden-Master-Prinzip auf neue Portierungen ausweiten**, überall dort, wo eine Legacy-Zahl/-Entscheidung als Referenz vorliegt (Druckrechte-Rechner, Zahlungsabgleich-Kategorisierung) — nach dem in Steuer-/OSS-Modulen bereits etablierten Muster, gerade weil Checklisten-"done" sich in diesem Projekt wiederholt als trügerisch erwiesen hat (2.2a).
3. **Dry-Run/Live-Split (aus `xw_copilot`) als Standardmuster für jede Portierung mit Schreibwirkung** (CRM-Merge, Ausgaben-Ignore-Regeln, SKU-Regelwerk-Änderungen an Fulfillment) etablieren, statt für jede Funktion einzeln ein Bestätigungsmuster neu zu entwerfen.
4. **Dateigrößen-Richtlinie technisch durchsetzen, nicht nur dokumentieren** — z. B. ein einfacher CI-Check/Lint-Regel, der bei Überschreiten der ~800-Zeilen-Grenze warnt, da die rein dokumentarische Regel bereits zweimal überschritten wurde (Legacy und `rechnungen/view.py`). Das ist keine Empfehlung aus Abschnitt 4, aber eine Voraussetzung dafür, dass die dort vorgeschlagenen neuen Module nicht denselben Weg gehen.
5. **Gemeinsame `core`-Utilities zuerst bauen (4.0), dann die vier/fünf abhängigen Funktionen (4.1, 4.6, 4.12, teilweise 4.15) darauf aufsetzen** — vermeidet, dieselbe Fuzzy-Match-/Normalisierungslogik erneut viermal einzeln zu portieren.

---

## 7. Vorgeschlagene Priorisierung (Reihenfolge)

**P0 — vor allem Weiteren (bereits in bestehenden Docs identifiziert, hier nur zur Einordnung, siehe Abschnitt 3):**
Steuerkorrektheit (UVA/ZM/OSS), Notendruck-Fallback-Sicherheit (K1), Multi-PC-Schreibsicherheit (K3), Bestandsdivergenz (K2).

**P1 — hoher Geschäftswert, aktuell fehlend oder unwirksam (Kern dieses Dokuments):**
4.1 Ausgaben-Check, 4.2 Reisekosten, 4.6 CRM-Merge-Absicherung, 4.7 Zahlungsabgleich-Fehlerkatalog/Mollie-OAuth (nach Lückenprüfung), 4.9 SKU-Regelwerk-Konsolidierung (nach Lückenprüfung).

**P2 — Vervollständigung, moderater Aufwand:**
4.3 Cover-Erzeugung, 4.4 Audio-Beispiele, 4.5 Druckrechte-Rechner, 4.8 B2B-Referenzextraktion (nach Lückenprüfung), 4.12 Produkte-unreleased, 4.15 Statistik-Vertiefung.

**P3 — sinnvoll, aber klar nachrangig:**
4.10 WüdaraMusi-Mandantenfähigkeit, 4.11 Google-Kalender-Integration, 4.13 Wix-Abkürzungsassistent, 4.14 FinanzOnline-DataBox-Protokollabruf.

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

**Codebasis-Fundstellen (XW-Studio):** `src/xw_studio/services/*`, `src/xw_studio/ui/modules/*`, `src/xw_studio/core/*`, `src/xw_studio/models/*`, `src/xw_studio/repositories/*`, `src/xw_studio/migrations/versions/*`, `tests/unit/*`, `tests/ui/*`.
