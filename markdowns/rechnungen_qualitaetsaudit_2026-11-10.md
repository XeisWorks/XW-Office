# RECHNUNGEN – Qualitätsaudit und Umsetzungsplan

Erstellt: **10.11.2026**; fortgeschrieben bis **12.11.2026**, Europe/Vienna.
Repository: `XeisWorks/XW-Office`.
Geprüfte Ausgangsbasis: `main`, `eb162c5d8c40db8052d31bc8bb009e27aa6cd351`.
Vor Beginn sauberer Arbeitsbaum und erfolgreicher `git pull --ff-only origin main`.

## 1. Executive Summary

Der Rechnungsbereich besitzt bereits umfangreichen Regressionsschutz, asynchrone
Listen-/Detailpfade, START-Wiederaufnahme, Druckwarteschlange und einen
quellenneutralen sevDesk-Kontext. Die wichtigsten Risiken liegen an den Übergängen
zwischen diesen Bausteinen: Fallidentität bei asynchronen Antworten, dauerhaftes
Beanspruchen externer Schreibaktionen, unvollständige Positionsdaten sowie
Transaktionsgrenzen zwischen Lagerbewegung, Buchungsmarke und Legacy-Bestand.

**27 Code-/Testbefunde: 19 ERLEDIGT, 7 OFFEN, 1 BLOCKIERT. Keine bestaetigte P0-Stoerung.**
Zwei zusaetzliche Betriebsabnahmen sind BLOCKIERT durch benoetigte Testbelege,
Hardware und eine isolierte PostgreSQL-Betriebsumgebung; sie sind nicht als
zusaetzliche Softwarefehler gezaehlt. OFFEN bedeutet eine konkrete, abgrenzbare
Aufgabe, nicht eine Behauptung ueber bereits eingetretene Schaeden.

Direkt behoben wurden falsche Nullmengen, unzulässige Bestandsmengen, doppelte
Lageralarm-Mails während eines laufenden Versands, vertauschter Kundenkontext bei
digitaler Lieferung, verlorene Worker-Referenzen, blockierender Lageralarm-Zähler,
veraltete Druckanhänge und zwei überholte Regressionserwartungen. Fortlaufende
Ergänzungen typisieren weitere Rechnungs-/Inventargrenzen, sichern den geteilten
Legacy-/Hub-START-Retry mit einem Teilfehler-Fake ab und verhindern, dass ein
fehlgeschlagener Settings-Write einen Unreleased-Alias nur lokal als gespeichert
erscheinen lässt.

**Keine Freigabe zum Bestands-Master-Cutover aus diesem Audit ableiten.**
Die offenen P1-Pakete betreffen Datenintegrität. Produktive Rechnungen, E-Mails,
Drucker, Bestände und Infrastruktur wurden nicht gezielt verändert. Alle neuen
Regressionstests verwenden Fakes bzw. lokale SQLite-Datenbanken.

### Belegstufen und Grenzen

- **Testbeleg:** mit Regressionstest oder lokalem reproduzierbarem Experiment nachgewiesen.
- **Codebeleg:** Aufrufpfad und Fehlerbedingung im aktuellen Quelltext nachvollzogen;
  ein tatsächlicher Produktionsvorfall wird damit nicht behauptet.
- **Prüfauftrag:** Hardware-, Mehr-PC-, DPI- oder Produktionsverhalten noch nicht nachgewiesen.
- Das vollständige statische Inventar in Anhang A erfasst alle 25 Python-Dateien
  des Untermenüs, ihre Methoden sowie deklarierte Aktionen, Dialogaufrufe, Signale,
  Timer und Worker. Dynamisch erzeugte Buttons sind als Schleifen-/Factory-Stellen
  enthalten. Diese Erfassung ersetzt keinen manuellen Klicktest jeder Instanz.
- Ein durchgehender produktiver End-to-End-Test aller Integrationen wurde bewusst
  nicht durchgeführt. Erfolgreiche Mocktests sind keine Freigabe echter Belege.

## 2. Verbindliche Quellen und jüngste Änderungen

Gelesen bzw. gegen die betroffenen aktuellen Pfade abgeglichen:

- `AGENTS.md`, `CLAUDE.md`, `pyproject.toml`, `tests/conftest.py`.
- `markdowns/rechnungen_manuelle_sevdesk_entwuerfe_5_6_luna_umbauspezifikation_2026-11-06.md`.
- `markdowns/rechnungen_inventur_bestand_5_6_luna_umbauspezifikation_2026-11-08.md`
  und zugehörige YAML-Arbeitsliste; Product-Hub-Fortschrittsdokument.
- `docs/rechnungen_umbauphasen_autonom.md`, `docs/phase_master_daily_rechnungen.md`,
  `docs/REFUND_FLOW_AUDIT_2026-11-05.md` und Rechnungen-Performanceplan vom 01.07.
- Vorhandene Rechnungs-, START-, Inventur-, Refund-, Druck-, PLC-, Kundenbetreuungs-,
  Such- und Rapid-Switch-Tests; die Gesamtsuite wurde zusätzlich ausgeführt.

Historische „erledigt“-Angaben wurden nicht als Nachweis übernommen. Beispiel:
Die Inventur-Spezifikation behauptet Schutz paralleler Alarm-Mails. Der tatsächliche
Code gab die Sperre jedoch vor dem Graph-Aufruf frei und ließ `pending` erneut zu
(F03). Umgekehrt setzt der **neuere Commit `f1e759c`** den offenen Produktdruck
bewusst unabhängig vom Bestand. Diese neuere implementierte Entscheidung wird
erhalten, auch wenn ältere Texte einen lagerbereinigten Druckknopf beschreiben.
`eb162c5`/`f8ea319` ergänzen Paketinhalt und echte Post-Ereignisse; F08 aktualisiert
deren veraltete Testverträge, ohne die neuen Funktionen zurückzubauen.

Das geschützte Content-Studio-Originalarchiv bleibt unverändert.

## 3. Funktionsinventar und Datenflüsse

Die folgenden Pfade wurden im aktuellen Code verfolgt. Die exakten Einstiegsstellen
und Signalverdrahtungen stehen vollständig in Anhang A.

| Oberfläche / Einstieg | Ausführung und Ergebnis | Wichtige Grenzen / Status |
| --- | --- | --- |
| Tagesgeschäft-Aktionsleiste | Aktualisieren, Entwurf, Custom-/PLC-Label, Statistik, Sonderauftrag, START/STOP und Alarmbuttons delegieren in Rechnungen/Services | Lazy eingebettete Rechnungsansicht; Parent übernimmt mehrere Badge-Refreshes |
| Rechnungsliste | Erst Entwürfe, anschließend aktuelle Nichtentwürfe, weitere Seiten; Tabellenmodell mit Proxy-Sortierung | Keine API-Abfrage pro gezeichneter Tabellenzelle; Nachladen weiter nötig |
| Suche | 220-ms-Debounce, lokaler Index/Service-Suche, Reset und Wiederherstellen der geladenen Liste | Sequenzschutz und Suchbanner vorhanden |
| Zeilenauswahl / Detail | Sofort Summary-Felder, dann verzögerte Cache-/API-Hydration; Kunden-, Versand-, Notiz- und Produktbereich | Wix- und sevDesk-Pfade getrennt; F05 schützt manuelle Worker-Lebensdauer |
| Tabellenaktion / Kontext | PLC/Post, Zoll, Nachlieferung; Statuschips lösen kontrollierte Retry-Schritte aus | Anwendbarkeit wird teilweise über Flags geprüft; serviceweite Claim-Lücke F12 |
| Detailmenüs | Rechnung, Adresslabel, PLC, archivierte Packlisten, Noten; Ansehen von PDF/PLC/Zoll/Packlisten/Paketinhalt; sevDesk/Wix/Kundenmail | Ausgewählte Rechnung und Archive müssen zusammenpassen |
| Wix-Rechnungsentwurf | Eingabe → Preview → Produktklärung → Draft-Service → sevDesk-Entwurf → optional Browser | Kein automatischer neuer Erstattungsprozess; Preview-/Dialogabbruch erhalten |
| Manueller sevDesk-Entwurf | Rechnung + InvoicePos → normalisierter Kontext → Adresse/Kunde/Produkte, PLC ohne Wix | Fünfstellige sevDesk-Referenz bleibt gemäß Nutzerentscheidung Wix-Kandidat; fehlende Positionsdaten F14 offen |
| START | Vorprüfung/B2B/Käufernotizen → Produktklärung → optional Notendruck → Freigabe/Rechnung/Label → Zahlung/Wix/Mail → Journal/Ergebnis | Selektierter und gesamter Scope; STOP kooperativ zwischen Schritten, keine Rücknahme bereits erfolgter Writes |
| START-Recovery | Persistierte Fulfillment-Flags → fehlende Schritte nachholen, Papier vor nachgelagerten Aktionen | Vorhandenen Print-first-Fix `346c7aa` erhalten; Mehr-PC-Claims F12 |
| Produktdruck einzeln/gesamt | Konfiguration/PDF-Seiten prüfen → PrintQueue/PDF-XChange → bestätigten Erfolg buchen | Kein Raster-/Acrobat-Fallback; offener Druck bleibt gemäß `f1e759c` editierbar und bestandsunabhängig |
| Druckhistorie / Reprints | Persistierte START-Snapshots und gezielter Wiederholungsdruck | Historische Anzeige erzeugt allein keine Lagerbewegung; neue Druckproduktion benötigt eigene Identität |
| PLC / Zoll / Packlisten | Kontext, Produkt, Gewicht, Mehrpaket-Aufteilung, Zollartikel → Shipment-Service/Importdatei → Archiv/Packliste/Ergebnis | Mehrpaket-Nicht-EU wird ausdrücklich blockiert; vorhandene Archive und zusätzliche Sendungen gesondert |
| Paketinhalt & Tracking | Persistierte Paketpositionen, bestaetigter Trackingcode, Original-XML-Import, Annahme/Zustellung anzeigen | Post-Ereignisse nicht aus blossem Labeldruck ableiten; PLC-Trackingimport und Paketcode-Zuordnung laufen im Worker (F17) |
| Offene Sendungen | Mail-/Fallliste → Detail/Adresse/Positionen → Label/Lieferschein/erledigt | Sequenzzähler für Details, asynchrone Aktionen, manuelle Felder; Close-Waits F18 |
| OPEN PRINTS | Graph/Flow-Liste -> Anhaenge -> lokalen Download oeffnen -> erledigt | F07 verhindert Uebernahme alter Anhangslisten; Laden, Download und Erledigen laufen asynchron, F17 |
| Offene Ueberweisungen | Maildetail -> Zahlungsformular -> QR/PDF -> verschieben/Outlook erledigt | Bedeutet keine Bankueberweisung; Rechnungsauswahl und PDF-Download asynchron, F17 |
| Digitale Lieferung | Bezahlte Lizenzfälle → fehlende PDF zuordnen → personalisieren → Sichtkontrolle → Outlook-Entwurf → manuellen Versand bestätigen → Wix-Abschluss | F04 bindet Dateien/Entwurf an denselben Fall; keine automatische Mailfreigabe |
| Lageralarme | Badge → Liste/Ist/Schwelle/Forecast → Fixwert/Automatik → manuelle Task-Mail | F03 dauerhafte Claim-/Unklar-Semantik; F06 asynchroner Badge; Lageralarm-Detail und -Aktionen im Worker; weitere I/O-Pfade F17 |
| Nachlieferungen / Betreuung | Review/Manager/Tab → Rollen/Mengen/Adresse/Snooze/sofort/erledigt/storniert → optional Zusatzrechnung | Klare Fallzustände, Originalbeleg und nicht verrechnete Nachlieferung erhalten; Mehrschritttransaktionen prüfen |
| Käufernotizen | Jede Notiz lesen, Lieferschein vormerken, digital bestätigen oder Datensatz überspringen → START fortsetzen | Unvollständige Bestätigung sperrt Fortsetzen; Cancel beendet Vorprüfung |
| Stornos & Gutschriften | Flow-Statusliste → finales Gutschrift-PDF / bestätigte Kundenmail | Erstellung erfolgt laut UI ausschließlich in Wix; kein neuer Storno-Button hinzuerfunden; F12/F17 |
| Sonderauftrag | Wix-Produkte/Freitextmodus → validierter Payment Link → Zwischenablage | Digital-Handling pro Produkt, kein physisches Fulfillment im Lizenzpfad |
| PLC-Statistik / Zahlungs-QR | Worker lädt Perioden bzw. lokale QR-Datei/Ordner öffnen | Statistik: Woche/Monat/Jahr/Gesamt; kein Erfolgsnachweis für Zustellung |

Historische, nicht mehr aktiv verdrahtete Einstiege: `RefundDialog` beschreibt noch den alten kombinierten Refund; die aktuelle View ?ffnet stattdessen den Wix-Hinweis bzw. `RefundsDialog`. Der Nachdruck-Handler und `ReprintPreviewDialog` sind vorhanden, aber in der aktuellen Tagesgesch?ft-Aktionsleiste nicht als eigener Button verbunden. Diese Stellen sind im statischen Inventar enthalten; sie wurden nicht als produktiv erreichbare neue Aktion freigeschaltet.

### Service- und Persistenzgrenzen

- `services/invoice_processing/{service,context,buyer_notes}.py`: Orchestrierung,
  Fähigkeiten, Positionen, Adressfallback, PDF-/Header-Caches, Fulfillment-Journal.
- `services/sevdesk/{invoice_client,part_client,refund_client,payment_booking}.py`,
  `services/http_client.py`: API-Parsing, Freigabe, PDF, Part-Bestand, Gutschriften,
  Zahlungen, Rate-Limit und Timeout. HTTP-GET-Retries sind von Writes zu unterscheiden.
- `services/wix/client.py`, Wix-Cache und Draft-Service: exakte Auflösung,
  Single-flight/Cache, Positionen, Adresse, Zahlung, Fulfillment, Lizenz- und Sonderaufträge.
- `services/printing/*`, `services/products/{catalog,print_decision}.py`,
  `services/inventory/service.py`: Druckplan, Warteschlange, Spoolerbestätigung,
  Legacy-Lager und Shadow-Spiegelung. Mehrere Schreibpfade bestehen weiter.
- `services/product_hub/{invoice_inventory,inventory,inventory_count,inventory_alert_tasks,
  sevdesk_invoice_inventory,sevdesk_credit_note_inventory,inventory_forecast_refresh}.py`
  und Worker/Repositories: Buchungsmarken, Ledger, Inventur, Forecast, Gegenbelege,
  Konflikte, Task-Mail. SQLite-Tests beweisen keine PostgreSQL-Sperrsemantik.
- `services/{sendungen,transfers,drucke,digital_licenses,customer_aftercare,mailing,plc,
  daily_business}` und deren Repositories: abhängige Arbeitslisten, Versand,
  Nachlieferungen, Outlook/Graph, Archive und Statusanzeigen.
- `SettingKvRepository.mutate_value_json()` serialisiert das gemeinsame JSON pro
  Schlüssel unter PostgreSQL. Das verhindert kein Überschreiben veralteter
  **Felder desselben Rechnungsflagsatzes** und ist kein Claim externer Aktionen.

## 4. Befundliste

Prioritäten: **P0 kritisch**, **P1 hoch**, **P2 mittel**, **P3 niedrig**.
Fundstellen sind Repository-Pfade; Methodennamen bleiben auch nach Zeilenverschiebung eindeutig.

| ID | Priorität | Status | Fundstelle / Ursache / reproduzierbare Auswirkung | Beleg |
| --- | --- | --- | --- | --- |
| F01 | P1 | ERLEDIGT | `invoice_processing/context.py::normalize_invoice_positions`: `quantity or qty` machte numerische 0 zu Default 1 bzw. alternativer Menge. Nullposition konnte physisch verarbeitet werden. Nun nur bei fehlendem/leeren Feld fallback. | Parametrisierte Tests mit int/float/Decimal/Text-Null und alternativer Menge |
| F02 | P1 | ERLEDIGT | `product_hub/invoice_inventory.py::_resolve_invoice_lines`: Bruchmenge wurde über `quantity_int` abgeschnitten; Part ohne SKU still übersprungen. Vorprüfung/Anwendung lehnen Bruchmengen und positive ungelöste Part-Zeilen nun ab. Nullposition bleibt ohne Buchung. | 0,5/1,5/2,9; Part ohne SKU; kein Booking bei Ablehnung |
| F03 | P1 | ERLEDIGT | `product_hub/inventory_alert_tasks.py::create_and_send`: nach Commit konnte zweiter Aufruf `pending` wieder beanspruchen. Jetzt aktive Claims immer gesperrt; `sent/unknown/failed` nur mit explizitem Resend. Transportfehler bleiben `unknown`; UI erklärt laufenden/unklaren Versand. | Reentranter Aufruf während Mail-Fake, Timeout nach Annahme, expliziter Resend |
| F04 | P1 | ERLEDIGT | `digital_licenses_dialog.py::_on_files_prepared/_on_draft_created`: Callback las die aktuelle Auswahl statt des ursprünglichen Falls; Dateien A konnten Entwurf B zugeordnet werden. Beide Stufen erfassen jetzt den Fall; Auswahl/Refresh/Aktionen sind gesperrt; alter Worker-Finish löscht neuen Worker nicht. | Echter Qt-Worker-Test mit zwei Fällen und verzögerten Fake-Stufen |
| F05 | P2 | ERLEDIGT | `view.py::_load_sevdesk_context`: alter Finish setzte `_stuecke_worker=None`, während der neue Worker lief. Nun Identitätsprüfung, vollständige Liste laufender Kontextworker für Shutdown und Sequenzschutz auch bei Fehlern. | Überlappende manuelle Loads; alter Finish erhält neue Referenz; beide im Shutdown |
| F06 | P2 | ERLEDIGT | `view.py::_refresh_inventory_alert_count`: DB-Abfrage im Konstruktor und Timer/UI-Thread, Fehler als 0 versteckt. Nun Worker, Coalescing, Laden beim Anzeigen, Timer-Stopp bei Hide/Shutdown und sichtbarer `?`-Fehlerstatus. | Eventloop-Heartbeat bei blockiertem Fake, ein Request für wiederholten Aufruf |
| F07 | P1 | ERLEDIGT | `offene_drucke_dialog.py::_select`: Auswahl B während Load A wurde verworfen; A-Anhänge erschienen bei B. Sequenzschutz und anschließender Load der letzten Auswahl; Downloads erfassen weiterhin ihren Fall. Datei zusätzlich lesbar formatiert. | A→B→C während verzögertem A: nur A/C gelesen, ausschließlich C angezeigt |
| F08 | P2 | ERLEDIGT | `test_database.py`, `test_rechnungen_view_smoke.py`: erwarteten weder neue PLC-Tabellen noch Menü „Paketinhalt & Tracking“. Tests aktualisiert; Produktion unverändert. | Zuvor fehlgeschlagene Erwartungen laufen jetzt grün |
| F09 | P1 | ERLEDIGT | `InvoiceProcessingService.load_invoice_work_context/_run_finalize_step/build_inventory_requirements`: Positionsfehler werden als unvollst?ndiger Kontext mit Ladezustand/Fehlertext behandelt und nicht gecacht. Freigabe und Produktdruck brechen vor dem externen Schreibaufruf ab; Retry l?dt erneut. | Regressionen: Timeout bleibt uncached, Freigabe sendet nicht, Druck gibt klare Exception, Retry l?dt erfolgreich |
| F10 | P1 | ERLEDIGT | `InvoiceInventoryBookingService.apply_line`: Booking, append-only Ledgerbewegung, materialisierter Bestand und Alarmstatus laufen in einer Session/Transaktion. Jede Mengen?nderung verwendet eine fortlaufende Transition-ID statt wiederverwendeter Zielmenge. | SQLite-Regression 10?2?3?2 ergibt 8; Replay bleibt idempotent; Transaktionscode sperrt vorhandene und erstmalige Booking-Zeile |
| F11 | P1 | ERLEDIGT | `apply_credit_line`: sperrt die Ursprungsposition und berechnet bestehende R?ckgaben in derselben Transaktion wie die neue Gegenbuchung. Konkurrierende Credits serialisieren auf der Ursprungs-Booking-Zeile. | SQLite Cap-/Replay-Tests; isolierter PostgreSQL-Barrierentest laesst konkurrierend nur eine von zwei zu grossen Rueckgaben zu; injizierter Buchungsfehler rollt Ledger, Booking und Bestand zurueck |
| F12 | P1 | OFFEN | Rechnungs-Mail, sevDesk-Freigabe, Wix-Fulfillment, Gutschrift-Mail und physischer Produktdruck nutzen dauerhafte Claims. Druck-Claims gelten pro Part-ID (Fallback SKU) in Rechnungs-Einzel-/Sammeldruck, offene Produkte und Produktbereich; `running`/`unknown` blockieren Instanzen, absichtlicher Nachdruck nach Erfolg erhaelt neue ID. `PrintDecisionEngine` serialisiert Part-GET/SET je Part im Prozess und ueber transaktionale PostgreSQL-Advisory-Locks; opt-in PostgreSQL-Tests bestaetigen verlustfreie Updates aus zwei unabhaengigen Engine-Instanzen und gemeinsame Claims ueber getrennte Stores. Die lokale manuelle `unknown`-Reconciliation ist mit einem auditierbaren Werkzeug erledigt; Bediener-Readback sowie externer Mehr-PC-/Prozessabbruchnachweis bleiben offen. Eine ledgerbasierte Part-Bestandsprojektion statt GET+SET bleibt als Architekturmassnahme offen. | Unit-Regression fuer Claim-Neulauf, Parallel-Engine und Unknown-Sperre; UI-/Legacy-Drucktests; opt-in PostgreSQL-Barrierentests fuer Erstbuchung, Credit-Cap, Part-Stock-Serialisierung, Claim-Serialisierung und Rollback |
| F13 | P1 | ERLEDIGT | Nutzerentscheidung vom 11.11.2026: Bestehende Zuordnung aus `sevdesk_reference`/`order_reference` bleibt verbindlich, auch für START-Zahlungsbuchung, Wix-Fulfillment und Nachlieferungskontext. Der Partner erzeugt die Referenz als Wix-Ordernummer oder `PO | Wix-Ordernummer`; XW-Office extrahiert fünfstellige Nummern. Die Detailansicht fällt bei leerem Wix-Treffer oder Fehler auf sevDesk-Positionen zurück; der WIX-ORDER-Button bleibt auf bestätigten WorkContext begrenzt. Automatische Schreibpfade behalten ihre persistenten Idempotenz-Claims. | Bestehende Tests schützen Fremdreferenz ohne Wix-Treffer in der Detailansicht, bestätigten WIX-ORDER-Button, erfolgreiche START-Zahlungsbuchung und Wix-Fulfillment. Die bewusste Beibehaltung der Referenzregel ist Nutzerentscheidung; keine neue Herkunftsmarkierung oder Kontakt-Heuristik |
| F14 | P1 | ERLEDIGT | `load_invoice_piece_blocks` gibt nur explizit druckbare ganzzahlige Produktpositionen aus. Die SevDesk-Detailansicht zeigt jede normalisierte Position mit Art, Menge, SKU/Quelle, Druckbarkeit, Beschreibung, IDs, Gewicht, Einheitspreis netto/brutto, Positionssteuer, Steuersatz, Rabatt, Positionssummen und Klaerhinweisen. Optionale Zahlenfelder bleiben bei fehlenden/ungueltigen API-Werten leer; sie aendern keine Druck- oder Lagerentscheidung. | Regression: Bruchmenge wird nicht als ganze Druckmenge behandelt; Normalisierung prueft optionale Geld-/Steuerfelder und UI-Test prueft deren Darstellung |
| F15 | P1 | ERLEDIGT | Decimal-Mengen, finale Statuswerte, stabile Positions-IDs und Needs-Review wurden strikt validiert. Der Invoice-Poll speichert einen atomaren Erfolgswasserstand mit 30-Tage-Overlap; bei Fehlern/Needs-Review bleibt er stehen. sevDesk-Seitenlimit wirft `TaxPageLimitError`, bevor Ergebnisse als vollstaendig gelten. | Feed-Validierungs-, Checkpoint- und `load_tax_resource`-Paginationstests |
| F16 | P1 | OFFEN | Invoice-Level-Journale und idempotente Replay-Behandlung fuer Legacy-/Hub-Buchungen bleiben im Code erhalten. Seit Nutzerentscheidung vom 11.11.2026 sind START-Bestands-Preflight, beide Buchungen und bestandsbezogene Resume-Retries standardmaessig durch `inventory.start_stock_booking_enabled: false` deaktiviert; Rechnungs-, Druck-, Zahlungs-, Wix- und Mailablauf laufen davon unabhaengig. Bei spaeterer Aktivierung gelten die bestehenden Journale/Claims. Getrennte Legacy-/Hub-Journale sowie isolierter Mehr-PC-/Prozessabbruch- und Betriebsnachweis bleiben offen. | SQLite-Regression fuer beide Schalterzustaende, per-Rechnung-Verbrauch, Replay, fehlgeschlagene Buchung ohne Teilupdate, Resume, Teilfehler und Rollback; externer Mehrsystemnachweis Gate G2 |
| F17 | P2 | OFFEN | Alarmdetail-Laden, Schwellenwertspeichern und Task-Mail laufen asynchron. Refund-Liste, Mailvorbereitung/-versand und PDF-Abruf, OPEN-PRINTS-Anhaenge/Erledigen, Ueberweisungs-PDF, PLC-Trackingimport/Paketcode-Zuordnung sowie Listen-, Positions- und Statusaktionen im eingebetteten Nachbetreuungs-Tab nutzen Worker. Due-/Wix-/Inbox-Pruefungen und Nachbetreuungs-Badgezaehler laufen bereits im koaleszierten BackgroundWorker von `TagesgeschaeftView._refresh_badges`. Dialoge fuer Sendungen, digitale Lieferung und Ueberweisungen geben nach dem Schliessen nur noch ihren lokalen Zaehlersnapshot zurueck; auch die Nachbetreuungs-Badges werden anschliessend asynchron aktualisiert. Die manuelle B2B-Kreditpruefung und bestaetigte Plan-/Limit-Schreibaktionen laufen jetzt in lifecycle-verfolgten Workern. Lizenz-PDF-Pfadschreiben laufen im Worker; Produktdruckkonfiguration/SKU-Flags der Rechnungsauswahl und Katalog-/Bestandsanreicherung der offenen Printproduktliste werden sequenzgesichert off-thread vorbereitet. Der erstmalige Datei-/Settings-Read des Unreleased-Katalogs wird vor der Teileaufloesung in einem Worker vorgewaermt. BuyerNote-Review erzeugt Outlook-Entwuerfe asynchron; OpenAI-Vorschlag, PDF-Erzeugung, Druck und Lieferschein-Mailentwurf im Lieferschein-Dialog laufen ebenfalls in Workern. Das Oeffnen und Zaehlen von Produktdruck-PDFs geschieht nun erst im Druck-Worker; PDF-Fehler vor dem Spool werden als sichere Fehlversuche abgeschlossen, Fehler nach moeglichem Druck bleiben unknown. Die synchrone Windows-Druckererkennung vor Produktdruck wurde entfernt; der Druckstatus kommt aus dem zentralen Snapshot und wird im MainWindow alle 60 Sekunden in einem Worker aktualisiert. Die BuyerNote-Aktionen stehen in einer kompakten Reihe; Outlook-Antwortentwuerfe erhalten die konfigurierte Signatur zwischen Antworttext und zitierter Kaeufernotiz. Bei manuellen Alias-/Produktentscheidungen wird der lokale Override-Cache erst nach erfolgreichem Settings-Commit aktualisiert; Fehlerregressionen belegen, dass fehlgeschlagene Writes keinen nicht gespeicherten Titel publizieren. START wartet nach einer manuellen Unreleased-Entscheidung jetzt ereignisgesteuert auf den Settings-Commit; Produktdialoge und START-Verarbeitung beginnen erst danach, und ein Schreibfehler stoppt START. Auch die manuellen Alias- und Produktentscheidungen aus Rechnungsauswahl sowie PRINT-PRODUKTE-`+` persistieren jetzt ueber den lifecycle-verfolgten Worker; UI-Update und Druckkonfiguration folgen erst nach Commit. Der START-Pfad waermt den Katalog bei kaltem Cache ebenfalls im Worker vor. Die sevDesk-Secret-Pruefung und die Lazy-Aufloesung des Rechnungsservice fuer Listenladen/Nachladen laufen nun im Lade-Worker; Cache-Invalidierung und Suchindex-Sync werden ebenfalls dort ausgefuehrt. | Eventloop-Heartbeats mit blockierten Fakes fuer Refunds, OPEN-PRINTS, Ueberweisungs-PDF, B2B-Lese-/Schreibaktionen, PLC-Trackingaktionen, Nachbetreuungs-Statuswrite, offene Printprodukt-Anreicherung und Unreleased-Katalog-Read; async START-Fortsetzung erst nach Commit, Worker-Write blockiert keinen Qt-Heartbeat; Katalog-Warmup wird bei kaltem Cache off-thread ausgefuehrt |
| F18 | P2 | ERLEDIGT | Worker-Dialoge verwerfen spaete UI-Ergebnisse und bleiben beim Schliessen reaktionsfaehig. Tagesgeschaeft deferiert Close ereignisgesteuert; BuyerNote-/Lieferschein-Dialoge bleiben waehrend aktiver Worker sicher. CustomerAftercareTab prueft den Qt-Owner vor jedem spaeten Widgetzugriff. Rechnungsansicht-Shutdown verwirft Resultate/Fehler, laesst nur Worker-Cleanup zu und startet keine Folgeauftraege; Draft-Erstellung, PDF-Oeffnung und Dialogfeedback werden nach Shutdown unterdrueckt. Es gibt keine direkten `.wait()`-Aufrufe in `ui/modules/rechnungen`. | Blockierte Fake-Worker pruefen Aftercare-, Tagesgeschaeft-, BuyerNote- und Rechnungsansicht-Close sowie spaete Resultate und Follow-ups; Rechnungsansicht-Smoke 104 Tests, Vollsuite 2.287 bestanden, 5 uebersprungen; Ruff/Mypy gruen |
| F19 | P2 | OFFEN | Invoice-PDFs verwenden jetzt einen 64-MiB-LRU und pruefen die erwartete Rechnungsnummer auch bei Cache-Hits; ein abweichendes PDF wird verworfen und neu geladen. Erfolgreiche Freigaben invalidieren PDF-, Detail-, WorkContext- und Rechnungslisten-Batch-Caches zentral, auch wenn ein vorheriger Claim bereits Erfolg meldet oder ein Fehler-Readback die Freigabe bestaetigt; ein neuer Wix-Entwurf invalidiert den Listenbatch vor dem UI-Reload. Ein einzelner monotoner Generationstoken verhindert auch nach explizitem Refresh, dass zuvor gestartete Detail-, WorkContext- oder PDF-Ladevorgaenge veraltete Werte wieder cachen; Cache-Zugriffe sind mit der Invalidierung synchronisiert, der Tokenzustand bleibt konstant gross. Header-/WorkContext-Caches haben eine 30-Sekunden-TTL; gemeinsame Inhaltsrevisionen und vollstaendige Produktaufloesung bleiben offen. Hub-Varianten und Bestandszeilen offener Printprodukte werden im gemeinsamen Vorbereitungslauf gebuendelt; SKU-/Alias-Aufloesung ist von N Einzelabfragen auf hoechstens fuenf Repository-SELECTs pro Batch reduziert, danach folgen eine Standort- und eine Bestandsabfrage. Katalogaufloesung und sevDesk-Cache-Fallback bleiben je SKU. | Regression: Header-/WorkContext-TTL erzwingt erneuten Fetch; Warm-Cache bleibt innerhalb der Frist; PDF-Nummernpruefung, Byte-Limit, Cache-Invalidierung nach finaler Freigabe, Entwurfserstellung und explizitem Refresh; blockierter Detail-Fetch wird waehrend des Fetch invalidiert und darf danach nicht in den Cache schreiben; direkte, alias- und Default-Variant-Aufloesung im Batch sowie UI-Aufruf mit genau einer Varianten-/Bestandsabfrage |
| F20 | P2 | OFFEN | pytest laedt keine lokale dotenv-Konfiguration; sensible Umgebungsvariablen werden entfernt und externe Socket-Verbindungen blockiert (Loopback bleibt erlaubt). `InvoiceProcessingService`, `tagesgeschaeft_view.py`, `redelivery_dialog.py`, `customer_aftercare_tab.py`, `buyer_note_review_dialog.py`, `buyer_note_delivery_dialog.py`, `print_decision.py`, `OffeneDruckeService`, `ProductsView`, `DigitalLicenseService`, `SpecialOrderService`, `products/catalog.py`, `services/product_hub/inventory.py`, `services/product_hub/inventory_count.py`, `services/product_hub/inventory_forecast_refresh.py`, `web/routers/inventory_count.py`, `services/product_hub/inventory_alert_tasks.py`, `services/product_hub/inventory_external_mirror.py`, `services/product_hub/conflicts/service.py`, `services/inventory/service.py`, `sevdesk/invoice_client.py`, `sevdesk/part_client.py`, `draft_invoice/service.py`, `plc/polling.py`, `plc/customs_document.py`, `plc/models.py`, `plc/service.py`, `plc/packing_list.py`, `plc/webservice.py`, `printing/pdf_renderer.py`, `sendungen/delivery_note.py`, `invoice_processing/context.py`, `services/customer_aftercare/redelivery.py`, `services/customer_aftercare/inbox_service.py`, `migrations/versions/026_customer_aftercare_redelivery.py`, `migrations/versions/027_customer_aftercare_snooze_context.py` und `ui/main_window.py` sind jeweils gezielt mit `--follow-imports=silent` mypy-fehlerfrei. Die MainWindow-Grenzen validieren Startup-Worker-Payloads und Theme-Anwendungsziel explizit; Performance-Snapshots und Shutdown-Hooks sind konkret typisiert/geprueft. `InventoryExternalMirrorService` grenzt JSON-Bestandswerte vor der Umwandlung auf die weiterhin akzeptierten Zahl-/Textformen ein; Legacy-Bestandsspiegel, START-Journal und Printplan-Payloads werden ebenfalls explizit eingegrenzt. Letzte Vollsuite: **2.290 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung (192,36 s)**. Aktuelle lokale MyPy-Baseline: **315 Fehler in 57 Dateien**; globales Ruff ist gruen. Hosted-Windows-Run `42987122286` auf `04171c5`: Ruff erfolgreich, **2.134 bestanden, 5 uebersprungen, 1 Warnung (615,78 s)**; weicher MyPy-Schritt **403 Fehler in 74 Dateien**. Hosted-Windows-Run `43044613867` auf `4fed6ee`: Ruff erfolgreich, **2.187 bestanden, 5 uebersprungen, 1 Warnung (550,94 s)**; weicher MyPy-Schritt **359 Fehler in 63 Dateien**. Die betroffenen Rechnungsdateien `view.py` und `tagesgeschaeft_view.py` sind in diesem Lauf fehlerfrei; die verbleibenden globalen MyPy-Fehler liegen in anderen Dateien. Die 24 Befunde des bisher installierten Ruff 0.15.9 wurden bereinigt. Ruff 0.17.4 pinnt die etablierte Regelbasis E4/E7/E9/F. Globale Typbereinigung und Controller-Extraktion bleiben offen. | Gesamtsuite lokal ohne Credentials/externe Verbindungen; CI verwendet reproduzierbare Ruff-Version und Regelbasis; globale Mypy-Baseline bleibt offen |
| F21 | P1 | ERLEDIGT | `view.py::_DraftInvoiceDialog`: nach erfolgreicher Vorschau konnte die Ordernummer ge?ndert und weiterhin bestaetigt werden. Jede Eingabe?nderung invalidiert nun die Vorschaufreigabe. | Qt-Test: Vorschau A ? Eingabe B bleibt gesperrt, erst Vorschau B erlaubt Best?tigen |
| F22 | P2 | ERLEDIGT | `InvoiceProcessingService.resolve_invoice_list_hints`: ein temporaerer Wix-Resolve-Fehler wurde als dauerhafter leerer Cacheeintrag abgelegt, sodass Notiz-/Pruefhinweise bis zum Neustart fehlten. Fehlerantworten werden nicht mehr gecacht und koennen beim naechsten Prefetch erneut geladen werden. | Fake mit Timeout beim ersten und erfolgreichem zweiten Resolve; zweiter Aufruf zeigt Wix-Notiz |
| F23 | P1 | BLOCKIERT | `SpecialOrderService` beansprucht den SHA-256-Fingerprint des Auftrags vor dem POST dauerhaft ueber `InvoiceOperationClaimStore`/SettingKV. Die Claim-ID wird als stabiler `clientRequestKey` mitgesendet; parallele Versuche und Neustarts sehen `running`/`unknown` und senden keinen zweiten POST. Jeder Fehler nach Claim-Erwerb bleibt vorsichtshalber `unknown` und wird sichtbar gesperrt; nach bestaetigtem Erfolg erlaubt eine neue bewusste Aktion eine frische Claim-ID. Das Wix-Backend prueft jetzt vor dem Create einen exakten Request-Key-Treffer und exponiert eine authentifizierte Readback-Aktion fuer unbekannte Ausgangszustaende; XW-Office nutzt diese ohne lokale Wix-API-Zugangsdaten. Mehrdeutige, unvollstaendige, fehlerhafte oder leere Antworten loesen keinen zweiten POST aus. Wix garantiert mit der Notiz weiterhin keine atomare serverseitige Deduplizierung. Die Website-Aenderung ist mit `check:all` getestet und als Commit `0f883d4` in den verbundenen `XeisWorks/XW-Website_v2`-Main-Branch gepusht. Wix-Commit `0f883d4` ist mit UI-Version `18585` erfolgreich auf `https://www.xeisworks.at/` veroeffentlicht. Ein Live-Wix-REST-Search-Probe mit eindeutigem Dummy-Key antwortete HTTP 200 und null Treffern; der echte Match-Fall blieb ohne Payment-Link-Erstellung. Ein invalid-secret-Probe auf der veroeffentlichten XW-HTTP-Funktion erhielt 403 vor Ausfuehrung des Readbacks. | XW-Office-Regressionsfaelle und volle Suite **2.297 bestanden, 5 uebersprungen, 1 bestehende Warnung**; GitHub-CI `43179094040` erfolgreich; Website `check:all` mit **155 Unit-Tests** gruen. Exakte Treffer reconciliieren unknown ohne zweiten Create, alle anderen Ergebnisse halten Claim unknown; offen bleibt ein Live-Test mit exakt passendem bestehenden Request-Key; die lokale XW-Endpunkt-URL und Shared-Secret-Konfiguration fehlen |
| F24 | P1 | ERLEDIGT | START behandelte den Product-Hub-Bestand trotz ausgeschaltetem Master-Flag als Preflight-Gate; zudem konnte ein einfacher START-Klick die Bestandspruefung umgehen. Der vom Nutzer gewuenschte `inventory.start_stock_booking_enabled`-Schalter ist standardmaessig `false` und deaktiviert START-Bestandspruefung, Legacy-/Hub-Buchung und bestandsbezogene Resume-Arbeit gemeinsam; Rechnung, Druck, Zahlung, Wix und Mail bleiben aktiv. Aktivierung benoetigt nach Bauabschluss einen bewussten Konfigurationswechsel und weiterhin ein separates Product-Hub-Masterflag fuer Hub-Buchungen. | Tests fuer beide Schalterzustaende, Replay, Resume und Teilfehler; Nutzerlog vom 11.11.2026 bestaetigt sieben Rechnungen ohne Bestandsbuchung erfolgreich verarbeitet; kein Codex-Produktiv-START ausgefuehrt |

## F20-Fortschreibung - optionale JSON-Felder bei Nachlieferungen

Die Nachlieferungsnormalisierung behandelte sevDesk-/Wix-JSON-Objekte mit
`null`-Werten an optionalen Objektfeldern nicht durchgehend sicher. Eine kleine
Normalisierungshilfe liefert fuer solche Felder ein leeres Objekt; numerische
Preis-/Steuerwerte sind explizit als `Decimal | None` typisiert. Der Regressionstest
deckt `part`, `contact`, `shippingAddress` und `taxRate` mit `null` sowie eine
gueltige Lieferadresse als Text ab. Die gezielte Datei ist mit strict MyPy ohne
Fehler; die Redelivery-Unit-Suite besteht mit **8 Tests**. Die globale lokale
MyPy-Baseline sank von 356 auf **337 Fehler in 60 Dateien**. Nach diesen Aenderungen
besteht die Vollsuite mit **2.288 Tests, 5 optionalen PostgreSQL-Ueberspringungen
und 1 bestehenden Starlette/httpx-Deprecation-Warnung (152,08 s)**; globales
Ruff ist gruen. F20 bleibt offen fuer weitere Typbereinigung und die geplante
Controller-Extraktion.
| F25 | P2 | OFFEN | Die Phasenmetriken und Hintergrundaufbereitung bleiben bestehen. Ein weiterer Desktop-Lauf am 12.11.2026 zeigt jedoch beim Abschluss der Non-Draft-Seitenladen erneut Eventloop-Luecken von 389 ms (50 Zeilen), 481 ms und 339 ms (je 10 Zeilen). Zeitgleich liefen sevDesk-Summary-Observer/Suchindex-Upserts; `Invoice batch metric` weist 4.310 ms fuer 50 Zeilen und 1.158/1.130 ms fuer die 10er-Seiten aus. Fuer diese Seiten fehlt ein `Rechnungen apply metric` ab 100 ms, daher belegen die Daten keine langsame Tabellenanwendung und auch keine eindeutige Ursache. Die bisherige Erledigt-Einstufung war zu weitgehend; GIL-Konkurrenz, Callback-Nacharbeit und Observer-Last muessen noch isoliert werden. | 50-Zeilen-Qt-Regression unter 250 ms; Phasenmetriken; Ursache der neuen 339–481-ms-Luecken isolieren und erneuten Desktop-Lauf unter 250 ms nachweisen |
| F26 | P2 | ERLEDIGT | Beim automatischen PLC-Labelversand wurde bei einem physischen Paket ein Packlisten-PDF erzeugt und auf `Paketmarke A5` gedruckt, obwohl der manuelle Packlisten-Button bereits mindestens zwei Pakete verlangt. Ursache war die alleinige Pruefung auf vorhandene Packlisten-Kontexte in `plc_label_dialog.py`; ein Kontext wird auch fuer ein Paket benoetigt, damit dessen Inhalt vor dem PLC-Aufruf im lokalen Collo-/Paketjournal gespeichert wird. Der automatische PDF-/Druckpfad prueft jetzt `len(shipment.parcels) >= 2`; die Inhalts-Snapshots bleiben fuer ein Paket erhalten und in den PLC-Infos sichtbar. | Fake-Regressionen: ein Paket mit zwei PLC-Codes erzeugt weder PDF noch Druckauftrag, behaelt aber seine Produktinhalte im Collo-Journal; zwei Pakete erzeugen weiterhin ein gemeinsames Packlisten-PDF und einen Druckauftrag. 46 PLC-/UI-Tests bestanden; Ruff und gezieltes MyPy gruen |
| F27 | P2 | OFFEN | Der Desktop-Loglauf vom 11.11.2026 verzeichnete waehrend Produkt-/Labeldruck-Dispatch Eventloop-Luecken von 334 bis 487 ms; zeitliche Korrelation belegt noch keine Ursache. Die Produktdruckvorbereitung protokolliert jetzt ihre Laufzeit. Zwei Fake-Qt-Heartbeat-Regressionen halten die maximale Luecke bei einem 400-ms-Fake-Dispatch unter 250 ms und bestaetigen die Ausfuehrung auf einem Hintergrundthread. Im Desktop-Lauf vom 12.11. lagen die Eventloop-Luecken direkt vor zwei Produktdruckauftraegen bei 159 ms oder darunter; spaetere 747/274/364/476-ms-Luecken traten im START-Rechnungs-/Labeldruck auf und brauchen eine getrennte Ursachenanalyse. | Fake-Druck mit Qt-Heartbeat unter 250 ms; Phasenmessung der Produktdruckvorbereitung; G1: freigegebener Testdruck mit Job-ID ohne Produktivbelege |

## 5. Performance-Audit

### Messmethode und Zahlen

Lokale Windows-Umgebung, Python **3.14.10**, PySide6 **6.11.0**, Qt `offscreen`.
Synthetische `InvoiceSummary.as_table_row()`-Zeilen, neun sichtbare Tabellenspalten,
`DataTable` mit Proxy, fünf Wiederholungen und Median; Sortierung abwechselnd
auf-/absteigend nach `sevDesk`, Filter `Kunde 99` in Kundenspalte, jeweils mit
`rowCount()` ausgewertet. Reine POD-Planung über 100 wiederkehrende SKUs einmal
gemessen. Gemessen nach den Fixes; **kein Vorher/Nachher-Geschwindigkeitsgewinn
für Tabellen behauptet**, weil deren Algorithmus unverändert ist.

| Zeilen | Tabelle setzen inkl. bestehendem Proxy | Umsortieren | Filtern | POD-Planung |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 1,30 ms | 1,13 ms | 0,42 ms | 0,42 ms |
| 1.000 | 34,90 ms | 22,80 ms | 4,08 ms | 3,35 ms |
| 10.000 | 389,02 ms | 317,79 ms | 38,97 ms | 34,80 ms |

Grenzen: kein echtes Paint/Scroll-Profil, keine Netzwerk-/Druckerzeiten,
keine PostgreSQL-Latenz, keine Messung des gesamten Hauptfensters oder des
Speichermaximums. Parallele Testprozesse machen die Werte zu Orientierungswerten.
Bei 10.000 geladenen Zeilen ist bereits die Sortierung ein sichtbarer UI-Block;
Pagination beibehalten und solche Mengen nicht ungefragt komplett materialisieren.

Der F06-Test misst eine Eigenschaft statt einer fragilen Millisekundengrenze:
Während der Fake-DB-Aufruf blockiert, läuft ein GUI-Timer-Heartbeat weiter;
wiederholtes Aktualisieren startet keinen zweiten Aufruf. Vorher lag genau dieser
Service-Aufruf im GUI-Thread. Die Datenbank wird dadurch nicht schneller,
die Oberfläche bleibt während ihrer Antwort bedienbar.

### Bestehende sinnvolle Optimierungen

- Gestuftes Laden, Suche mit Debounce, Source-/Proxy-Zeilenabbildung.
- Gemeinsamer Wix-Kontext statt separater Meta-/Positionsrequests, TTL-/persistenter
  Cache und Single-flight im Wix-Client; Selektion hat Vorrang vor Warmup.
- Priorisierte BackgroundJobManager-Queues, sequenzgebundene Ergebnisse,
  inkrementelle Hint-Patches, Phasenmetriken für Auswahl/START/Wix.
- START bündelt Kontext und nutzt begrenzte Parallelität für Nacharbeiten;
  Druckerfolg und nachgelagerte Kundenaktionen bleiben getrennt nachvollziehbar.

### Verbleibende Engpässe und Messaufträge

- F17: jeden synchronen I/O-Slot einzeln auf Worker umstellen, DTO vor Start im
  GUI-Thread erfassen; keine Qt-Widgets im Job lesen. UI-Heartbeat mit langsamen
  Fakes als Abnahmekriterium, nicht nur `worker.start()` als Quelltexttest.
- `_piece_block_from_open_product` kann pro Produkt den Hub lesen; für große
  Übersichten Bestände/Katalogkonfiguration einmal pro Batch auflösen. SQL-Queries
  zählen; Ziel höchstens konstante Batch-Abfragen statt eine je Zeile.
- Fulfillment-JSON wird mehrfach vollständig gelesen/dekodiert; pro Batch einen
  unveränderlichen Snapshot verwenden, Writes weiter atomar. Keine bloße lokale
  Kopie als Mehr-PC-Lösung ausgeben.
- PDF-Retryfolge wartet bereits 0,5+1+2+4 Sekunden zusätzlich zu Requests;
  in Hintergrundjobs akzeptabel, für Cancel gezielt unterbrechbare Warte-/Retry-
  Grenzen und begrenzten Cache vorsehen (F19). Kein blindes Write-Retry hinzufügen.

## 6. Konsistenz und UX

Umgesetzt: Nullmengen bleiben Null; unklare Task-Mail-Zustände werden verständlich
erklärt; Lageralarmfehler verschwinden nicht als scheinbare Entwarnung; digitale
Lieferung sperrt Auswahl und Aktionsbuttons während ihrer Verarbeitung; OPEN
PRINTS zeigt zum gewählten Fall gehörende Anhänge. Bestehende Entwurfsfarbe,
sichtbare Käufernotizen und Druck-/Archivaktionen bleiben erhalten.

Weitere konkrete Verbesserungen innerhalb F13/F14/F17/F18:

- Capability-Modell tatsächlich an Button-Verfügbarkeit binden; „nicht anwendbar“,
  „lädt“, „Daten fehlen“ und „fehlgeschlagen“ unterscheiden.
- Im Lageralarmdialog Aktionen bei leerer Liste deaktivieren, aktuelle Auswahl
  nach Schwellenänderung erhalten und Status `pending/sent/unknown/failed`
  dauerhaft zeigen; expliziten, bestätigten Wiederholungsversand nach Prüfung anbieten.
- „Mail wurde gesendet“ von „war bereits gesendet“ unterscheiden; Mehrfachklick
  darf keinen neuen Versand behaupten. Auch bei externen Statusfehlern nachvollziehbar bleiben.
- `Selected`, `OPEN PRINTS`, unterschiedliche Umlaut-/ASCII-Schreibweisen und
  einzelne bereits im Quelltext beschädigte Platzhalter vereinheitlichen.
  Keine pauschale Encoding-Konvertierung des großen Views ohne Sichtkontrolle.
- `ERLEDIGT`: Mengen im Nachlieferungsdialog sind begrenzte `QSpinBox`-Editoren;
  Originalpositionen koennen nicht ueberliefert werden, manuelle Zeilen sind auf
  1..999 begrenzt. Ungueltige Werte werden nicht still zu 1 umgedeutet.
- Lange feste Buttonreihen und Mindestgrößen (digitale Lieferung 1020×650,
  breite Nachlieferungs-/PLC-Dialoge) bei 1366×768, 100/125/150/200 % prüfen.
  Erst nach bestätigtem Clipping Wrap/Scroll/Größenregeln ändern.
- Tastaturpfade Tab/Enter/Escape, Doppelklick, Dialog-X, Abbrechen während Load,
  Vorschau ablehnen und Retry nach Fehler systematisch in Gate G1 abnehmen.

## 7. Architektur-Audit und konkrete offene Arbeitspakete

UI, Services und Repositories sind grundsätzlich vorhanden und über DI angebunden.
Die Grenzverletzungen liegen vor allem in großen UI-Orchestratoren und in
mehrstufigen Writes über mehrere Services. `view.py` hat rund 7.900 Zeilen,
`tagesgeschaeft_view.py` 1.757, PLC-Dialog 2.409; das überschreitet die
CLAUDE-Richtgröße von etwa 800 deutlich. Eine sofortige Gesamtextraktion wäre
risikoreich. Erst Schnittstellen/Regressionen sichern, dann kleine Controller für
Kontextladen, Dokumentaktionen, Druckübersicht und Journal auslagern.

AP01 ist umgesetzt: F09, F13 und F14 sind erledigt. SevDesk-Positionspreise, Einheit, Steuer-, Rabatt- und Accounting-Summen werden verlustfrei in den WorkContext uebernommen und in der Detailansicht dargestellt, ohne Druck-/Lagerregeln zu veraendern.
AP02-Implementierung F10/F11 ist lokal umgesetzt. Isolierte PostgreSQL-Barrierentests
belegen Erstbuchung, Credit-Cap und Rollback; Gate G2 bleibt fuer weitere AP03-Claims,
den physischen Part-Stock-Pfad und Betriebsabnahme offen. Die uebrigen Pakete sind offen.

### AP01 - Vollstaendiger, fehlersicherer Rechnungskontext (F09/F13/F14 ERLEDIGT; P1)

Kontext um explizite Header-/Positions-Ladezustände und Warnungen erweitern.
Positionsfehler niemals als vollständigen leeren Kontext cachen. Ein bestätigter
fehlender Wix-Treffer fällt auf sevDesk zurück; bloßer Kandidat schaltet keine
Wix-Schreibaktion frei. Unbekannte/bruchzahlige Originalpositionen sichtbar halten,
Druck und Bestandsbuchung jedoch sperren, bis eindeutig geklärt.

**Akzeptanz:** Timeout bei InvoicePos führt zu null Freigabe-/Druck-/Lagerwrites;
Retry lädt Positionen erneut. Manuelle fünfstellige Referenz ohne Wix-Treffer nutzt
für die Detailanzeige sevDesk; die dokumentierte Referenz bleibt zugleich gemäß
Nutzerentscheidung der bestehende Kandidat für automatische Wix-Folgeaktionen. 0,
0,5, 1,5, Part ohne SKU, Versand, Rabatt, Freitext und reine Digitalware werden mit
begründeten Fähigkeiten angezeigt. Wix-Bestandspfade bleiben kompatibel.

**Umgesetzt (F09):** Ladezustand und Positionsfehler sind Teil des Kontexts; ein
Fehlerzustand wird nicht gecacht. Freigabe und Produktdruck brechen vor Writes ab.
Timeout, Retry, Header-only-Nachladen und Freigabesperre sind regressionsgetestet.

### AP02 - Atomare Dokumentbuchung und Gegenbeleggrenzen (F10/F11 umgesetzt; PostgreSQL-Gate G2 offen; P1)

Ledgerbewegung, Booking-Ziel, Bestandszeile und Alarmbewertung unter einer
gemeinsamen Session/Transaktion verarbeiten. Pro Ursprungsposition sperren,
auch beim ersten Booking; eine monoton identifizierte Revision/Transition statt
wiederverwendetem reinem Zielmengen-Schlüssel einsetzen. Keine historische
Bewegung überschreiben; bestehende Keys bei Einführung kompatibel behandeln.

**Akzeptanz:** 10→Zielverkauf 2→3→2 ergibt 8; Wiederholung jeder Transition bleibt
idempotent. Prozessabbruch zwischen Bewegung und Booking heilt ohne Doppelbewegung.
Zwei PCs buchen dieselbe Position gleichzeitig einmal; zwei Gegenbelege können
zusammen nie die Ursprungsmenge überschreiten. Echte PostgreSQL-Tests mit Barrieren
für beide Interleavings, Rollback und leere Erstzeile ergänzen. Negative Bestände
bleiben gesperrt und erzeugen einen dauerhaften Klärfall.

**Umgesetzt (F10/F11):** Booking, Ledgerbewegung, Bestand und Alarmstatus teilen
eine Session. Erstbuchungen werden per Unique-Insert angelegt und dann gesperrt.
Credit-Pruefung sperrt die Ursprungsposition bis Gegenbewegung und Booking committet
sind. SQLite-Regressionsfaelle bestehen. Fuenf opt-in PostgreSQL-Tests mit zwei unabhaengigen
Session-/Claim-Store-Clients pruefen Erstbuchung, Credit-Cap, Claim-Serialisierung und
Rollback in einem zufaelligen Schema einer isolierten Testdatenbank. Produktionsdatenbanken
werden nicht verwendet. Mehr-PC-Prozessabbruch/Recovery und Betriebsabnahme bleiben Gate G2.

### AP03 - Dauerhafte Claims externer Aktionen (teilweise umgesetzt; F12 teilweise offen; P1)

Gemeinsamen Status pro Rechnung und Aktion mit `pending/running/succeeded/unknown/failed`
und eindeutiger Operation-ID einführen. START, manuelle Aktion und Retry verwenden
denselben Dienst. Lease-Recovery nur mit Zustandsabgleich, niemals durch erneutes
blindes Senden. Unklare sevDesk-Mailantwort ohne verlässlichen Readback darf keinen
automatischen Graph-Zweitversand auslösen. Part-Bestandsprojektion vom Ledger ableiten,
nicht mit konkurrierendem `get+set` erhöhen.

Direkter Produktdruck blockiert parallele UI-Auftraege derselben Part-ID/SKU. Ein persistenter SettingKV-Claim serialisiert den physischen Lauf ueber Engine-Instanzen und laesst einen bewussten neuen Druck nach `succeeded` zu. Unklare Ergebnisse bleiben `unknown` und muessen manuell abgeglichen werden. Das GET/SET-Paar zum sevDesk-Part-Bestand ist pro Part innerhalb des Prozesses serialisiert und wird mit gesetzter Datenbankverbindung zusaetzlich unter einen transaktionalen PostgreSQL-Advisory-Lock gestellt. PostgreSQL-Integrationstest mit zwei Engine-Instanzen bestaetigt den Advisory-Lock fuer den Part-GET/SET-Pfad; eine ledgerbasierte Part-Bestandsprojektion ist weiterhin offen.

**Akzeptanz:** zwei Widgetinstanzen/zwei Prozesse, START+manuelle Mail und Retry
gleichzeitig erzeugen höchstens eine Mail/Freigabe/Fulfillment-Aktion. Timeout nach
Serverannahme bleibt sichtbar unklar. Druckwiederholung ist ein bewusst neuer Lauf;
ein alter Lauf bucht bei Recovery keinen zweiten Zugang. Bestehende sevDesk-first-
Strategie und die PDF-/Graph-Fallbacktests fachlich abgestimmt weiterführen.

**Umgesetzt:** `invoice_mail`, `invoice_finalize` und nach Line-Item-Fingerprint
eindeutige Wix-Fulfillments teilen `InvoiceOperationClaimStore`. Status `running`,
`succeeded`, `unknown` und `failed` werden ueber SettingKV persistiert; PostgreSQL-
Advisory-Locks serialisieren gleichzeitige Clients. Unklare Resultate sperren Retry.
Gutschrift-Mails verwenden jetzt ebenfalls einen dauerhaften Claim je Gutschrift; ein unklarer Graph-Ausgang sperrt automatische Wiederholung. Direkter Produktdruck hat einen UI-lokalen In-Flight-Guard sowie einen persistenten Claim gegen gleiche SKU/Part-ID in parallelen Instanzen. `PrintDecisionEngine` serialisiert die Part-Stock-GET/SET-Paarung per gemeinsamem Engine-Lock und bei vorhandener Datenbank per transaktionalem PostgreSQL-Advisory-Lock. Ein neuer absichtlicher Drucklauf erhält nach Erfolg eine neue ID; `unknown` sperrt bis zum manuellen Abgleich. Der neu gepruefte manuelle Wix-Fulfillment-Pfad fuer Digital-Lizenzen ist ebenfalls geclaimt. Sonderauftrag-Payment-Links verwenden nun einen dauerhaften payloadgebundenen Claim und eine stabile Request-ID; unklare Ausgaenge blockieren Wiederholung auch zwischen Serviceinstanzen. Wix-REST-Notizen und der nicht verifizierte XW-Endpunktvertrag garantieren keine serverseitige Deduplizierung oder Readback. Manuelle Claim-Reconciliation und die ledgerbasierte Bestandsprojektion bleiben offen.

### AP04 – Externe Belege strikt normalisieren (F15; P1)

Gemeinsame Decimal-basierte Mengen-/Identitätsvalidierung für Invoice-/Credit-Feed
verwenden. Nur explizit finale, unterstützte Statuswerte buchen. Ungültige Zahlen,
Bruchmengen, fehlende IDs und unklare Gegenbelege in `needs_review`, nicht als
Menge 0 oder erfundene Positionsidentität behandeln. Provider-Pagination und
persistente Wasserstände samt Überlappung erhalten.

**Akzeptanz:** 0/0,5/1,5/NaN/Infinity/fehlender Status/fehlende Positions-ID,
digitale und stornierte Belege erzeugen nur fachlich zulässige Bewegungen;
Neustart verarbeitet Fehlerfälle erneut und überspringt keine späteren Belege.

**Umgesetzt:** Mengen werden als Decimal erhalten; nur sevDesk-Status `200` (open),
`750` (partially paid) und `1000` (paid) werden als final akzeptiert. Unbekannte
Statuswerte, Bruch-/Ungueltigmengen und fehlende Positions-IDs werden nicht gebucht.
Der atomare SettingKV-Wasserstand wird nur nach vollstaendigem Poll ohne Needs-Review
fortgeschrieben; jeder Lauf liest mit 30 Tagen Ueberlappung. Das sevDesk-Seitenlimit
bricht mit `TaxPageLimitError` ab. Statusdefinition gemaess [sevDesk API-Dokumentation](https://api.sevdesk.de/).

### AP05 - Legacy-/Hub-Bestand und START-Teilfehler (F16; teilweise umgesetzt; P1)

Den pauschalen Batchverbrauch durch dokumentweise idempotente Legacy-Buchungen
ersetzen. Vor `sendBy` Bestand pruefen; die offene Druckliste bleibt davon unabhaengig.
Vor dem externen Write den Recovery-Status persistieren. Legacy-Snapshot,
Produktzeilen und Verbrauchsjournal atomar speichern; Hub-Buchungen bleiben ueber
ihre Dokument-/Positionsidentitaet idempotent und werden bei Resume erneut versucht.

**Teilweise umgesetzt:** Legacy-Verbrauch wird nur fuer erfolgreich finalisierte
Dokumente gebucht und ueber `invoice_id:SKU` gegen Wiederholung geschuetzt.
`SettingKvRepository.mutate_values_json` speichert Journal, Stock-Snapshot und
Produktzeilen gemeinsam; Start-Resume wiederholt die idempotente Buchung.
Unterdeckung sperrt die externe Freigabe. Preflight-Mengen werden nach Rechnung
gruppiert, unvollstaendige Positionen und Bruchmengen blockieren die Planung.

**Noch offen:** Abnahme eines 2+1-Teilfehler-/STOP-Szenarios mit echten sevDesk- und
Hub-Testbelegen sowie Poller-Recovery in einer isolierten Umgebung. Die Legacy-
und Hub-Journale sind getrennt und koennen nur ueber den Recovery-Lauf konvergieren.
Die bewusst bestandsunabhaengige offene Produktdruckliste aus `f1e759c` bleibt
erhalten.

### AP06 – UI-I/O und gemeinsame Dialogaktionen (F17, F18; teilweise umgesetzt; P2)

**Teilweise umgesetzt (F17/F18):** Lageralarm-Laden, Schwellenwertspeichern und Task-Mail laufen im Worker; Refund-Liste, Gutschrift-Mail, Refund-PDF, OPEN-PRINTS-Anhaenge und Erledigen-Aktion ebenfalls. Das eingebettete Nachbetreuungs-Tab lädt Liste/Positionen sequenzsicher im Worker und führt Snooze, Sofortversand, Bearbeiten, Erledigen und Stornieren außerhalb des GUI-Threads aus. Sendungen-, Ueberweisungs-, Nachbetreuungs- und OPEN-PRINTS-Dialoge warten beim Schliessen nicht im GUI-Thread und verwerfen spaete UI-Ergebnisse. Die Nachbetreuungs-Worker pruefen vor Ergebnis-, Fehler- und Abschlusscallbacks, ob ihr Qt-Owner noch lebt; Ergebnisse nach Owner-Zerstoerung werden ignoriert. Auch Zusatzrechnungsdialog und Tagesgeschaeft-Close blockieren nicht mehr; Dialog-Rueckgabewerte fuer Sendungen, digitale Lieferung und Ueberweisungen nutzen den geladenen Zaehlersnapshot statt synchroner Serviceabfragen; der Nachbetreuungs-Badge wird nach Dialogschluss erneut im koaleszierten Worker berechnet. Die manuelle B2B-Kreditpruefung sowie ausdruecklich bestaetigte Plan- und Limit-Schreibaktionen laufen in serialisierten Workern, die bei Close beruecksichtigt werden. Rechnungslisten-Toggle und Refresh lesen/schreiben START-Haltepunkt-Settings jetzt im Worker und aktualisieren die Tabelle nach Commit; BuyerNote-Review setzt START ebenfalls erst nach durablem Commit fort. Das Oeffnen/Parsen von Produktdruck-PDFs wurde aus dem GUI-Thread in den Druck-Worker verschoben; die bisher ungenutzte synchrone Druck-Wrapperfunktion wurde entfernt. Auch die Windows-Druckererkennung vor dem Druck nutzt nun den zentralen Status-Snapshot ohne UI-seitige Systemabfrage; der Status wird lifecycle-sicher jede Minute asynchron aktualisiert. Weitere UI-I/O-Pfade und spaete Callback-Policies bleiben offen.

Der Sonderauftrag-Dialog verhindert jetzt Schliessen/Escape waehrend des externen
Payment-Link-Writes, damit Ergebnis oder unklarer Ausgang sichtbar bleiben. Der
Produktlade-Callback ignoriert Ergebnisse nach Dialogschluss; Workerabschluss
raeumt nur den zugehoerigen Worker auf. Regressionstest mit blockiertem Fake-Write:
Close bleibt bis zum Abschluss verhindert, danach wird das Ergebnis angezeigt.
Vollsuite auf Windows CI Run 43068708273: 2.195 bestanden, 5 uebersprungen,
1 PyMuPDF-FutureWarning in 605,44 s; Ruff erfolgreich. Der globale MyPy-Gate
bleibt mit 359 Fehlern in 63 Dateien rot (keiner in den geaenderten Dateien).

**Weitere F18-Fixes (ERLEDIGT):** Schreibaktionen halten ihre Dialoge bis zum
abgearbeiteten Ergebnis offen: digitale Lieferung (PDF-Pfad, Lizenzentwurf,
Outlook-Aktion und Wix-Abschluss), Gutschrift-Mailversand, Lageralarm-Schwellenwert
und Task-Mail, OPEN-PRINTS-Abschluss, PLC-Trackingimport und Paketcode-Zuordnung,
Nachbetreuungs-Manageraktionen, Sendungsdruck/Erledigen sowie Ueberweisungs-QR,
Zurueckstellen und Erledigen. Reine Leseaktionen duerfen weiterhin geschlossen
werden; verspaetete Leseantworten werden verworfen. Worker-Finish-Callbacks raeumen
nur ihre eigene Worker-Referenz auf. Regressionen versuchen Accept, Reject und
Fensterschliessen waehrend blockierter Fake-Writes und pruefen, dass Dialog und
Ergebnis bis zum sicheren Abschluss erhalten bleiben.

Gezielte Windows-venv-Pruefung: **60 Tests bestanden**; Ruff fuer alle geaenderten
Dateien erfolgreich; strict MyPy fuer betroffene Rechnungsdialoge fehlerfrei und
Paketpruefung `ui/modules/rechnungen`: **0 Fehler in 27 Quelldateien**. Windows-CI
Run `43088839022` auf `febf9f3`: Ruff erfolgreich, **2.200 bestanden, 5
uebersprungen, 1 PyMuPDF-FutureWarning in 618,80 s**. Globales MyPy bleibt bei
**359 Fehlern in 63 Dateien**; die betroffenen Rechnungsdateien sind gezielt
fehlerfrei. AP06 bleibt teilweise offen, da weitere UI-I/O-Pfade noch zu pruefen sind.

Verbleibende UI-I/O-Slots auf vorhandenen
`UiAsyncAction`/BackgroundWorker umstellen. Snapshot/Identität vor Workerstart;
Callbacks auf aktuelle Auswahl prüfen oder bewusst ursprünglichen Fall bearbeiten.
Schreibaktionen gemeinsam sperren, Datenbank-/Netzfehler im Dialog lassen.
Für Schließen/Escape bei Writes eine einheitliche Policy: im Hintergrund mit
dauerhaftem Ergebnis fortsetzen oder Schließen bis zum sicheren Punkt verhindern.
Keine mehrsekündigen `wait()`-Schleifen im GUI-Thread.

**Akzeptanz:** 2-s-Fake-Netzwerk blockiert keinen Heartbeat; Abbruch/Retry und
Zeilenwechsel zeigen keine fremden Daten; Doppelklick startet einen Auftrag;
Dialogschließen führt weder zu QThread-Abbruch noch unbemerktem neuen Write.
Erfolg erst nach nachgewiesenem externen bzw. Spooler-Ergebnis anzeigen.

### AP07 – Cacheverträge und Batchauflösung (F19; teilweise umgesetzt; P2)

**Teilweise umgesetzt:** Hub-Varianten offener Printprodukte werden jetzt mit `resolve_variants_by_skus` in einer gebuendelten Repository-Aufloesung geladen, einschliesslich exakter SKU, Alias und Default-Variant-Fallback. Danach folgen eine Standortabfrage und eine Bestandsabfrage fuer N Varianten statt 2N Einzelabfragen. Repository-Regression begrenzt die direkten/alias/default SELECTs auf hoechstens fuenf fuer den gemischten Batch; eine UI-Regression bestaetigt genau einen Varianten- und einen Bestandsbatch. Die Aufloesung der Produkt-/Druckkonfiguration im lokalen Katalog und der sevDesk-Cache-Fallback bleiben je SKU. Invoice-PDF-Cache ist ein 64-MiB-LRU; Cache-Hits werden
erneut gegen die erwartete Rechnungsnummer geprueft. Header-/WorkContext-Caches
sind auf je 256 Eintraege begrenzt und laufen nach 30 Sekunden ab; fehlende gemeinsame Inhaltsrevisionen werden dadurch zeitlich begrenzt.
Produkt-/Bestandsdaten werden noch nicht durchgaengig vor dem Rendern gebuendelt.

Revision, Vollständigkeit und gegebenenfalls TTL für Header/Positionen/PDF festlegen;
Freigabe, Entwurfsänderung und Löschung invalidieren alle abhängigen Einträge.
PDF-LRU mit Byte-Limit; Erwartungsnummer auch bei Cache-Hit prüfen.
Produkt-/Bestandsdaten vor Rendering gebündelt auflösen.

**Akzeptanz:** Entwurfsvorschau→Freigabe liefert final nummeriertes PDF;
Rechnung auf zweitem PC geändert→Reload zeigt neue Positionen/Adresse;
1.000 PDF-Ansichten halten definiertes RAM-Limit ein; GUI-Rendern löst keine
Netzwerkanfrage aus. Warm-Cache spart Requests nachweisbar per Fake-Zähler.

### AP08 – Reproduzierbare Qualitätsgates und kleine Controller (F20; teilweise umgesetzt; P2)

**Teilweise umgesetzt:** `tests/conftest.py` deaktiviert dotenv-Laden, entfernt
relevante Credential-/Datenbank-Variablen und sperrt externe Socket-Verbindungen.
Lokale Loopback-Testserver bleiben erlaubt. `services/invoice_processing/service.py`
und `ui/modules/rechnungen/tagesgeschaeft_view.py` sind jetzt einzeln mit
`--follow-imports=silent` mypy-fehlerfrei. Bei der zweiten Datei wurden 19
Typfehler an optionalen/ungeprüften Worker-Payloads behoben; fehlerhafte Badge-Zähler
werden als null behandelt, und unerwartete Popup-/Listenpayloads werden verworfen.
Der aktuelle Paketlauf ueber `src/xw_office` findet 484 MyPy-Fehler in 88 Dateien
(vor den letzten Dateibereinigungen 680/104); der isolierte Rechnungs-UI-Lauf findet
0 Fehler in 0 Dateien (urspruenglich 150 in 11 Dateien). `redelivery_dialog.py`,
`customer_aftercare_tab.py` und `print_decision.py` sind ebenfalls einzeln fehlerfrei.
`ProductsView` ist jetzt ebenfalls einzeln mypy-fehlerfrei; sechs Delegate-Overrides,
Worker-Payloads, Filterzustand, Bestandskorrektur-Argumente und ein Event-Filter
wurden praezise typisiert. Weitere betroffene Module und Controller-Extraktion sind
weiterhin offen.

Testprozess von lokalen `.env`-/Credentials isolieren und echte externe
Verbindungen standardmäßig sperren; lokale Testclient-Verbindungen zulassen.
Striktes mypy zuerst je bearbeitetem Controller/DTO bereinigen, Baseline nicht
mit pauschalem `ignore_errors` verstecken. Anschließend große Klassen entlang
stabiler Ports aufteilen, jeweils mit bestehendem UI-/START-Testpaket.

**Akzeptanz:** identische Tests auf sauberem PC ohne Secrets; keine externen
Netzwerkaufrufe; mypy-Fehlerzahl pro Paket sinkt; Ruff bleibt grün;
Refactoring ändert keine sichtbaren Geschäftsregeln oder Datenverträge.

## 8. Erledigte Verbesserungen und Qualitätssicherung

Geänderte Produktionsdateien:

- `services/invoice_processing/context.py`: Menge 0 korrekt erhalten (F01), expliziter
  Positionsladezustand (F09).
- `services/invoice_processing/service.py` und `services/sevdesk/invoice_client.py`:
  fehlende/fehlerhafte InvoicePos-Antworten nicht cachen; Freigabe und Produktdruck
  bei unvollst?ndigem Kontext vor externem Write sperren (F09).
- `services/product_hub/invoice_inventory.py` und `services/product_hub/inventory.py`:
  atomare Dokumentbewegungen, monoton eindeutige Transitionen und gesperrte Credit-Caps
  (F10/F11).
- `services/product_hub/invoice_inventory.py`: Mengen-/Zuordnungsvalidierung (F02).
- `services/product_hub/inventory_alert_tasks.py` und Alarmdialog:
  aktiver Claim, unklarer Versand und verständliche Rückmeldung (F03).
- `ui/modules/rechnungen/digital_licenses_dialog.py`: fester Kundenkontext,
  Aktionssperren und Worker-Identität (F04).
- `services/invoice_processing/service.py` und `ui/modules/rechnungen/refunds_dialog.py`: dauerhafter Claim fuer Gutschrift-Mails; unklarer Versand sperrt Retry.
- `services/invoice_processing/service.py`: optionale API-Payloads werden vor verschachteltem Zugriff typisiert/nachgewiesen; mypy fuer die Datei von 44 Fehlern auf 0 reduziert, ohne Geschaeftsregeln zu aendern.
- `services/invoice_processing/service.py`: Header- und WorkContext-Caches erhalten eine 30-Sekunden-TTL mit gebundener Timestamp-Invalidierung (F19).
- `ui/modules/rechnungen/view.py`: manuelle Worker und asynchroner Alarmzähler (F05/F06).
- `ui/modules/rechnungen/view.py`: alle normalisierten SevDesk-Positionsdetails bleiben sichtbar, auch wenn eine Position nicht druckbar ist; Text kann markiert/kopiert werden (F14).
- `ui/modules/rechnungen/plc_label_dialog.py` und `view.py`: Mehrpaket-PDF-Erstellung, PLC-Ergebnisarchivierung und Druckwarteschlangen-Write, archivierter Packlistennachdruck sowie bestaetigter PLC-Dokumentnachdruck bei Duplikatantworten laufen off-thread. Der PLC-Finalizer behaelt die bisherige Reihenfolge fuer Archive, Queue, Druckmarke, Teilerfuellung und Packlistenjournal; Doppelklicks und Close waehrend eines Write werden verhindert (F17/F18).
- `ui/modules/rechnungen/view.py`: verhindert gleichzeitig gestartete Einzelproduktdrucke fuer dieselbe SKU/Part-ID, erlaubt bewusste Wiederholung nach Abschluss (F12).
- `ui/modules/rechnungen/offene_drucke_dialog.py`: sequenzsichere Anhänge (F07).

- `ui/modules/rechnungen/offene_ueberweisungen_dialog.py`: Rechnungsauswahl aus dem asynchron geladenen Fallkontext; PDF-Download und temporaere Dateiablage im Worker (F17).

- `ui/modules/rechnungen/customer_aftercare_manager_dialog.py`: schliesst ohne Worker-Wartezeit; invalidiert Detail-/Aktionscallbacks und behaelt typisierte Bestaetigungsdaten (F18).
- `ui/modules/rechnungen/customer_aftercare_invoice_dialog.py`: blockierte Kontakt-Reads halten Close nicht mehr auf und spaete Ergebnisse werden verworfen; laufende Rechnungserstellung bleibt bis zum Ergebnis offen.
- `ui/modules/rechnungen/customer_aftercare_tab.py`: Listen-/Positionsreads, Fallbearbeitung, Snooze und Statuswrites laufen sequenzsicher im Worker (F17/F18).
- `ui/modules/rechnungen/tagesgeschaeft_view.py`: Shutdown wartet asynchron auf die Worker statt bis zu fuenf Sekunden im GUI-Thread zu blockieren; Timer schliesst nach Worker-Ende.
- `ui/modules/rechnungen/tagesgeschaeft_view.py`: nach dem Sendungsdialog wird der Nachbetreuungs-Badge aus dem letzten Snapshot angezeigt und der Datenbank-Refresh im Worker gestartet (F17).
- `ui/modules/products/view.py`: Delegate-Signaturen, Worker-Payloads, Filterzustand, Bestandskorrektur und Event-Filter mypy-fehlerfrei typisiert (F20).

- `ui/modules/rechnungen/plc_evidence_dialog.py`: PLC-Nachweis laden, Original-Tracking-XML importieren und Paketcode zuordnen laufen asynchron; spaete Ergebnisse werden nach Dialogschluss verworfen (F17/F18).

Gezielte Tests ergänzt in `test_invoice_work_context.py`,
`test_invoice_inventory_booking.py`, `test_inventory_alert_tasks.py`,
`test_rechnungen_view_smoke.py`, `test_digital_licenses_dialog.py` und neu
`test_offene_drucke_dialog.py`. `test_database.py` und Toolbar-Smoke an tatsächlich
vorhandene PLC-Funktion angepasst (F08).

### Tatsächliche Prüfergebnisse

Letzter Gesamtlauf vor Wix-Snapshot-Typisierung: **2.125 bestanden, 1 Warnung, 0 fehlgeschlagen in 155,36 s**. Die einzelne Warnung ist die bestehende Starlette-Deprecation zu `httpx` in `fastapi.testclient`; sie blockiert den Lauf nicht.
- Aktueller lokaler Gesamtlauf auf `177fe52` einschliesslich aller aktuellen Main-Aenderungen: **2.178 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (204,03 s)**.
- Hosted-Windows-Run `43025023976` auf `7e75d62` brach bei 12 % mit Heap-Fehler `0xc0000374` beim Erzeugen der naechsten Rechnungsansicht ab, direkt nach `test_rechnungen_cached_wix_summary_allows_product_fallback_when_items_missing`. Dieser Test wartet auf die sichtbare Adresse, nicht auf das Ende aller Hintergrund-Worker; das ist eine plausible, noch nicht durch den Hosted-Rerun bestaetigte Ursache. Er wartet jetzt vor dem Abbau auf `RechnungenView.shutdown_complete()`; Rechnungs-UI-Smoke danach lokal **89 bestanden**, Ruff gruen. Hosted-Rerun auf aktuellem Main ist noch ausstehend.
- Nutzerentscheidung zu F13 bestaetigt am 11.11.2026: Bestehendes Verhalten der verbindlichen Zuordnung ueber `sevdesk_reference`/`order_reference` beibehalten. Keine zusaetzliche Herkunftsmarkierung oder Kontakt-Heuristik einfuehren.
- AP08/AP04 sevDesk-Historienadapter: Beleg- und Positionsfelder sind als `dict[str, Any]` typisiert; `_deduplicate` nimmt ein typisiertes Iterable entgegen, und optionale Statuswerte werden vor der Zahlkonvertierung behandelt. Striktes MyPy und Ruff fuer `sevdesk_history_audit.py` gruen; Historien-/Forecasttests **4 bestanden**. Repository-weite MyPy-Baseline sinkt von **367/62** auf **357 Fehler in 61 Dateien**.
- AP07/AP08 Wix-Snapshot: Persistierte ChannelMappings sind als `ChannelMapping` typisiert; optionale Varianten-/SKU-Listen werden als Sequenzen validiert, bevor sie iteriert werden. Striktes MyPy und Ruff fuer `wix_snapshot.py` gruen; Snapshottests **10 bestanden**, inklusive einer Regression mit fehlerhaftem SKU-Listenfeld. Repository-weite MyPy-Baseline sinkt weiter auf **352 Fehler in 60 Dateien**.
- Produktionspruefung Railway, 11.11.2026: Deployment `79e59fc4-8d1b-4484-89eb-49ac1b77f8e2` auf `c4a522f` scheitert zunaechst mit `ModuleNotFoundError: No module named 'lxml'` ueber `repositories.plc_shipment` → `services.post_tracking`. Nach Aufnahme von `lxml>=5.0,<7` zeigt der Start `stdnum.eu` aus `finanzonline.zm_service` als weiteren fehlenden Import; auch die bestehende Projektvorgabe `python-stdnum>=1.20` wird in `requirements-web.txt` aufgenommen. Der kombinierte Stand `43a4a5f` ist mit Railway-Deployment `6e386f0e-6c7d-43e3-866d-ea7f4d82ff3c` **SUCCESS**; Uvicorn meldet Startup abgeschlossen und `GET /health` liefert HTTP 200. Lokaler Import beider Pakete/Web-App sowie 23 fokussierte Web-API-Tests sind gruen. Ein lokaler Docker-Build war wegen TLS-Zertifikatsfehler beim PyPI-Zugriff im Build-Container nicht verifizierbar; Railway hat den Produktions-Docker-Build erfolgreich ausgefuehrt.
- AP08 DigitalLicenseService-Typisierung: Die erweiterte Claim-/Readback-Behandlung fuer manuelle Wix-Freigaben sowie zwei bestaetigte Typkorrekturen machen `digital_licenses/service.py` im strikten MyPy-Lauf fehlerfrei (zuvor 2 Dateifehler). Repo-Baseline sinkt von 506/91 auf **504/90**; 12 Service- und 5 Dialogtests sowie Gesamtsuite **2.114 bestanden, 1 Warnung**.

Die folgenden historischen Teillaeufe dokumentieren den Entwicklungsverlauf:
- Erster Gesamtlauf: **1.979 bestanden, 4 fehlgeschlagen**, 138,53 s.
  Zwei stale PLC-Erwartungen durch F08 behoben. Zwei Wix-Media-Tests übernahmen
  Umgebungscredentials; ein unerwarteter externer Leseaufruf erhielt HTTP 403.
  Kein erfolgreicher produktiver Write wurde beobachtet. Keine Credentials in
  dieses Dokument oder Commits übernehmen. Folgeprüfungen extern netzwerkgesperrt.
- Fokussierter Lauf nach F01–F06/F08: **105 bestanden**.
- Erweiterter Lauf inklusive digitaler Lieferregression: **104 bestanden**
  (anderer Dateiumfang); OPEN-PRINTS-/digitale UI-Tests danach **3 bestanden**.
- Ein temporärer Offline-Runner sperrte zunächst versehentlich auch lokale
  Asyncio-Sockets; diese Fehlversuche sind **kein Produktfehler**. Der korrigierte
  Runner erlaubt Loopback und leert die vier geerbten Wix-Credential-Variablen
  je Test. MockTransports/ASGI/SQLite funktionieren weiter; Kontrolllauf **8 grün**.
- Ruff über alle geänderten Python-Dateien plus neue UI-Testdatei: **grün**.
  Die vorherigen 58 Ruff-Meldungen im angefassten OPEN-PRINTS-Dialog wurden durch
  dessen lokale Formatierung entfernt; keine Repository-weite Formatierung.
- Striktes mypy für die sieben zunächst bearbeiteten Produktionsdateien,
  `--follow-imports=silent`: Ausgangsstand **113 Fehler in 6 Dateien**;
  abschließenden Vergleich unten festhalten. Das ist kein grünes Typprüfungs-Gate.
  Die Baseline stammt aus einem temporären `git archive HEAD src`, nicht aus
  einem anderen Checkout oder alten Audittext.
- AP03-Claims und externe Aktionstests: **90 bestanden** aus InvoiceService-,
  Claim-Store- und Wix-Client-Tests (1,63 s); Ruff: **gruen**; mypy strict fuer
  `operation_claims.py`: **gruen**.
- Gutschrift-Mailclaim: **2 neue Fake-Transporttests** belegen einmaligen Erfolg und Sperre nach unklarem Timeout; Refund-Dialog/Claim-Tests zusammen **6 bestanden**. Ruff gruen. Mypy im gesamten `invoice_processing/service.py` zeigt die bekannte bestehende Baseline von 44 Fehlern; die bearbeiteten neuen Methoden erzeugten keine neue Meldung.
- OPEN-PRINTS-Aktion: **3 Qt-Tests bestanden** (schnelle Zeilenauswahl, blockierendes Markieren ohne UI-Blockade/Mehrfachklick, Schliessen waehrend Worker ohne spaeten UI-Write); Ruff und mypy fuer den Dialog gruen.
- Ueberweisungs-PDF: **7 UI-Tests bestanden**; blockierter Fake-Download laesst Eventloop-Heartbeat laufen, Schaltflaeche bleibt bis zum Abschluss gesperrt; Ruff und mypy fuer den Dialog gruen.
- Nachbetreuungsmanager: **8 UI-Tests bestanden**, einschliesslich Close bei blockiertem Worker ohne Aufruf von `wait()`; Ruff und mypy fuer den Dialog gruen.
- PLC-Paketnachweis: **2 Qt-Tests bestanden**; blockierte Codezuordnung und XML-Import halten den Eventloop frei; Ruff und mypy gruen.
- AP04-Feed-Normalisierung: **51 Tests bestanden** ueber Invoice-/Credit-Feeds,
  Status-/Decimal-Helfer und Bestandsbuchung (2,43 s); Ruff: **gruen**.
- Regression fuer F10: Ziel 2->3->2 bei Anfangsbestand 10 ergibt Endbestand 8;
  jede Transition hat eine eigene ID, Replay erzeugt keine zweite Bewegung.
- Aktueller gezielter Lauf: 74 bestanden aus InvoiceService-, InvoiceBooking- und
  InvoiceClient-Tests (1,77 s). Ruff auf acht geaenderten Python-Dateien: gruen.
  Mypy fuer invoice_inventory.py: gruen. PostgreSQL-Barrieren sind lokal nicht nachgewiesen.
- InvoiceProcessingService-Typbereinigung: fokussierter Lauf **148 bestanden**
  ueber Verarbeitung, Work-Context, Claims, Inventory-Start, Wix-Orders/Cache und
  InvoiceClient; Ruff fuer `service.py` gruen, mypy fuer `service.py` **0 Fehler**
  (vorher 44). Andere Module und die Paket-Baseline bleiben offen.
- F14 Positionsdarstellung: Rechnungsansicht **82 bestanden**, inklusive Test aller
  normalisierten Details fuer nichtdruckbare SevDesk-Positionen; Ruff fuer View und
  Testdatei gruen. Gesamtsuite danach **2.076 bestanden**.
- F18 Close-Lebenszyklus: **14 fokussierte Tests bestanden** fuer Aftercare-Dialog und
  Tagesgeschaeft-Close; Ruff gruen. Mypy fuer den Zusatzrechnungsdialog gruen;
  `tagesgeschaeft_view.py` enthaelt 19 bestehende Typfehler ausserhalb der Close-Aenderung.
  Badge-Regression: **8 Tests bestanden**, einschliesslich des asynchronen
  Nachbetreuungs-Refreshs nach dem Sendungsdialog. Gesamtsuite danach **2.080 bestanden**.
- AP07 Cache-TTL: zwei neue InvoiceService-Regressionen belegen Warm-Cache innerhalb der Frist und erneuten Header-/Positionsabruf nach Ablauf; Ruff und mypy fuer `service.py` gruen. Gesamtsuite danach **2.083 bestanden**.
- AP08 Worker-Payload-Typen: `tagesgeschaeft_view.py` mypy von 19 Fehlern auf 0 bereinigt; ungültige Badge-Zähler und asynchrone Listen-/Popup-Payloads werden defensiv geprüft. Ruff fuer Produktions- und Testdatei gruen; Badge-/Aftercare-UI **9 bestanden**; Gesamtsuite danach **2.084 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung**.
- AP08 Aftercare-Tabellen und Callbacks: fehlende optionale Zellen werden ueber einen zentralen Default-Reader behandelt; Callback-Typen spiegeln die tatsaechlich ignorierten Rueckgabewerte wider. `redelivery_dialog.py` und `customer_aftercare_tab.py` mypy/Ruff fehlerfrei; Qt-Regression fuer fehlende Tabellenzellen; Manager-Dialog **9 bestanden**; Rechnungs-UI-MyPy sinkt von 150 auf 140 Fehler in 9 statt 11 Dateien. Repository-weite Messung sank von 680/104 auf 666/101; Gesamtsuite danach **2.085 bestanden, 1 Warnung**.
- AP08 `ProductsView`-Typen: 20 lokale MyPy-Fehler auf 0 reduziert; keine pauschalen `ignore_errors`, Override-Signaturen entsprechen Qt, Produkt-/Wix-Worker-Payloads werden zur Laufzeit typvalidiert und Korrekturparameter sind explizit. Produkte-UI und Inventurkorrektur **26 bestanden**, Ruff gruen. Repository-MyPy sinkt weiter von 666 Fehlern/101 Dateien auf **646/100**. Gesamtsuite nach Aenderung: **2.092 bestanden, 1 bestehende Warnung, 0 fehlgeschlagen (146,44 s)**.
- AP06 Aftercare-Tab: DB-Listen-/Positionsreads und Fallwrites blockieren nicht mehr den UI-Thread; spaete Positionsantworten nach schneller Zeilenauswahl werden verworfen. Aftercare-Qt-Tests **11 bestanden**, einschliesslich blockiertem Statuswrite mit Eventloop-Heartbeat und A→B-Auswahl; Tab mypy/Ruff fehlerfrei. Gesamtsuite nach der Aenderung: **2.094 bestanden, 1 bestehende Warnung, 0 fehlgeschlagen (147,20 s)**.
- AP06 F17 Zaehlerrueckgaben: Sendungen-, Digital- und Ueberweisungsdialoge greifen nach dem Schliessen nicht mehr synchron auf Services zu; ungueltige Worker-Payloads fuehren zu asynchronem Reload. Nachbetreuungs-Badges werden nach dem Dialog im koaleszierten Worker aktualisiert. 32 gezielte UI-Tests bestanden; Ruff gruen; MyPy fuer drei Dialoge und TagesgeschaeftView fehlerfrei. Rechnungs-UI-Baseline jetzt 130/7, Repository-MyPy 636/98. Gesamtsuite nach allen Aenderungen: **2.100 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (151,08 s)**.
- AP06 F17 B2B-Kreditpruefung und Schreibaktionen: Rechnungs-/Planpruefung sowie ausdruecklich bestaetigte Plan- und Limit-Speicherungen laufen in lifecycle-verfolgten Workern. Blockierte Lese- und Schreib-Fakes bestaetigen Eventloop-Reaktion, Aktionssperre und Shutdown-Verfolgung. 11 gezielte Tagesgeschaeft-Qt-Tests bestanden; Ruff und MyPy fuer die Datei gruen; Repository-MyPy 636/98. Gesamtsuite danach: **2.101 bestanden, 1 Warnung (155,24 s)**.
- AP07 Cacheinvalidierung: Erfolgreiche sevDesk-Freigaben invalidieren PDF-, Detail-, WorkContext- und Listenbatch-Caches zentral; bereits erfolgreiche Claims und finale Readbacks nach Timeout tun dasselbe. Entwurfloeschung nutzt denselben Helper; Wix-Entwurfserstellung invalidiert den Rechnungslistenbatch vor dem UI-Reload. Ein Generationszaehler verhindert, dass ein vor der Invalidierung gestarteter Listenabruf danach veraltete Daten wieder in den Cache schreibt. 56 InvoiceProcessingService-Tests bestanden; Ruff und MyPy fuer service.py gruen. Gesamtsuite: **2.106 bestanden, 1 Warnung (152,63 s)**.
- F22 Wix-Retry: `361ef08` (`Retry invoice hints after Wix read failures`) verhindert, dass ein tempor?rer Resolve-Fehler einen leeren dauerhaften Cacheeintrag hinterl?sst. 57 InvoiceProcessingService-Tests bestanden; Ruff und gezieltes MyPy gruen. Gesamtsuite: **2.107 bestanden, 1 Warnung (168,26 s)**.
- AP08 Typbereinigung: `00e604a` (`Type invoice review and reprint dialogs`) macht `buyer_note_review_dialog.py` beim Dialogparent und `reprint_dialog.py` beim konkreten `ReprintPreflight`-Vertrag typkorrekt. Die beiden Dateien sind mypy-fehlerfrei; Rechnungs-UI 127/5, Repository 633/96. 42 gezielte START-/Drucktests bestanden; Ruff gruen.
- AP08 nullable UI-Pfade: `4644f19` (`Guard optional invoice dialog data`) prueft in `special_order_dialog.py` das optionale Layout vor `invalidate()`; `customer_aftercare_review_dialog.py` behandelt fehlende Mengen-Zellen mit Default 1; `plc_label_dialog.py` normalisiert fehlende Wix-Metadaten und prueft Layout-Items vor Zugriff. 26 gezielte PLC-/Aftercare-Tests bestanden; betroffene Dateien und Ruff gruen. Baseline 120/3 und 626/94; Gesamtsuite 2.107 bestanden (152,68 s).
- AP08 Druckdialog: `9be0a7f` (`Type invoice product print dialog`) typisiert `_PrintPlanModel` und `_PrintProfileDelegate` mit den Qt-Index-/Modelltypen, `print_pdf_by_plan` erh?lt typisierte Argumente; `fitz` ist als untypierte Drittbibliothek pr?zise markiert. `print_dialog.py` mypy-fehlerfrei; 11 Druckplan-/Produktdrucktests, Ruff und Gesamtsuite 2.107 bestanden (152,68 s). UI-Baseline 0/0; Repository 506/91.
- AP07 manueller Refresh: `8f6b953` (`Invalidate invoice snapshots on explicit refresh`) leert vor dem sichtbaren Neuladen den Rechnungslistenbatch und die Detail-/PDF-/WorkContext-Snapshots der ausgew?hlten Rechnung. 141 gezielte Unit-/Qt-Tests, MyPy und Ruff gruen; Gesamtsuite **2.108 bestanden, 1 Warnung (191,99 s)**.
- AP07 In-flight-Invalidierung: Detail-, WorkContext- und PDF-Cachezugriffe sind durch Generationstoken und einen reentrant lock gegen parallelen Refresh abgesichert. Ein blockierter sevDesk-Detailabruf, der waehrenddessen invalidiert wird, schreibt nach Abschluss keinen veralteten Snapshot in den Cache; der naechste Aufruf laedt erneut. InvoiceProcessingService **59 Tests bestanden**, Ruff/MyPy gruen; Gesamtsuite **2.109 bestanden, 1 bestehende Warnung (161,70 s)**.
- AP06 F17 Digital-Lizenz-Druckpfad: `DigitalLicensesDialog._pick_missing_pdf` persistierte den neuen Produktdruckpfad synchron im Katalog und optional im Product Hub. Der Schreibvorgang laeuft nun im bereits lifecycle-verfolgten Dialogworker; Zeilenliste und weitere Aktionen bleiben bis zum Ergebnis gesperrt, und erst danach wird der erfasste Lizenzpositionsdatensatz aktualisiert. Blockierter Fake bestaetigt freien Qt-Eventloop und unveraenderte Zeile bis zum Schreibabschluss. 5 Dialogtests, Ruff/MyPy gruen; Gesamtsuite **2.110 bestanden, 1 bestehende Warnung (152,12 s)**.
- AP06 F17 Produktdaten fuer Druckbereich: `RechnungenView._on_stuecke_loaded` loest Produkt-/Druckkonfiguration und SKU-Druckflags sequenzgesichert off-thread auf; auch die offene Printproduktliste laedt Katalog-/Bestandsdaten im Worker und verwirft veraltete Antworten nach Wechsel der Rechnungsansicht. Unreleased-Titelklaerung bleibt interaktiv im UI. 85 Rechnungsansichtstests bestanden, einschliesslich blockiertem Resolver mit Qt-Heartbeat und stale A->B-Antwort; Rechnungs-UI-MyPy, Ruff und `git diff --check` gruen. Gesamtsuite ohne opt-in PostgreSQL: **2.121 bestanden, 5 uebersprungen, 1 bestehende Warnung (150,17 s)**.
- Abschliessende Gesamtsuite nach den aktuellen Code- und Regressionstest-Commits: **2.115 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (147,39 s)**. Die Warnung stammt aus `fastapi.testclient`/Starlette.
- AP08 Sonderauftrags-Service: `SpecialOrderService` ist mit präzisen Payload-/WixProduct-Typen mypy-fehlerfrei. Eine ungültige Nicht-JSON-Endpoint-Antwort lieferte zuvor durch `data.get(...)` einen `AttributeError`; sie ergibt jetzt eine verständliche `RuntimeError`. Vier gezielte Response-Regressionen bestanden; `ok` wird strikt als JSON-Boolean `true` validiert und die Zeichenkette `"false"` abgelehnt; Ruff/MyPy grün. Repository-Baseline sinkt von 504/90 auf **494/89**.
- Abschliessender Gesamtlauf nach dem Sonderauftrags-Service-Fix: **2.124 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (157,19 s)**.
- F23: dauerhafter payloadgebundener SettingKV-Claim fuer Sonderauftrag-Payment-Links; Timeout-/Mehrinstanz-Regressionen bestehen. Wix/XW-Endpoint-Deduplizierung und manuelle Reconciliation bleiben Restpunkte.
- Ruff-CI-Blocker korrigiert: 24 aktuelle Source-Befunde in `OffeneDruckeService` und Product-Hub entfernt; `ruff check src/` besteht nun global.
- Vollsuite nach F23 und Ruff-Korrektur: **2.126 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Warnung (156,71 s)**.
- Ruff-CI-Abweichung geklaert: Hosted CI installierte 0.17.4, dessen implizite Regelwahl gegenueber 0.15.9 erweitert wurde. `pyproject.toml` pinnt 0.17.4 und setzt E4/E7/E9/F explizit, womit die bisherige Gate-Basis reproduzierbar bleibt. `OffeneDruckeService` nun ebenfalls gezielt mypy-fehlerfrei; Repository-Baseline 481/87. Fokussierte Drucktests: **5 bestanden**.
- Windows-Hosted-Pytest deckte eine spaete `Path`-Importzeile in `test_product_hub_migration_preview.py` auf; Importreihenfolge korrigiert, vier Regressionstests und Ruff lokal bestanden. Der lokale Python-3.14-Runner hatte den Fehler wegen verzogerter Testannotation nicht reproduziert.
- Windows-Hosted-Pytest erreichte nach der Importkorrektur **2.123 bestanden, 5 uebersprungen** und fand drei Qt-Pruefprobleme: Busy-State-Abschluss wurde vor dem GUI-Callback abgefragt; Tabellenhoehenverhaeltnis 4x war bei 386/111 px zu streng. Tests warten nun auf Thread-Ende plus Button-Reaktivierung und pruefen die fachlich ausreichende 3x-Hoehe. Betroffene UI-Tests: **29 bestanden**, Ruff gruen; neuer Hosted-Lauf ausstehend.
- Windows-Hosted-Pytest nach Qt-Korrekturen: **2.123 bestanden, 5 uebersprungen**. Drei weitere CI-spezifische Regressionen behoben: Mollie-Cache vereinigt Detailanreicherungen bei Zeitstempel-Gleichstand, erzwungener Expense-Refresh behandelt gleiche `datetime.now()`-Aufloesung nicht mehr als bereits erfolgte spaetere Synchronisierung. Fuenf gezielte Mollie-/Expense-Regressionen bestanden; Ruff gruen.
- Expense-Sync-Rennen: Die Force-Erkennung nutzt nun eine persistierte Generation statt Zeitstempel-Gleichheit. Ein wartender manueller Sync erkennt damit einen zwischenzeitlich abgeschlossenen Scan eines anderen PCs; der zusaetzliche Generation-Read erfolgt nur fuer erzwungene Syncs. Die bestehende Gleichheitsregression und die PostgreSQL-Lockregression bleiben erhalten. Fokussierte Expense-Tests: 34 bestanden; globales Ruff und `git diff --check` bestanden.
- F17 Wix-Order-Link: `resolve_order_dashboard_url` konnte nach bis zu drei erfolglosen Versuchen mit Pausen den GUI-Thread blockieren. Die Aufloesung laeuft nun im lifecycle-verfolgten Worker; Mehrfachklicks werden zusammengefasst. Ein blockierter Fake bestaetigt den Qt-Heartbeat, einen einzigen Request und korrektes URL-Oeffnen; beide gezielten Qt-Tests und Ruff bestanden.
- F17 toter sevDesk-Prefill-Pfad: `_prefill_detail_from_invoice` war im gesamten Repository unreferenziert und rief synchron `get_invoice_detail_context()` auf. Der Helper ist entfernt; der aktive Detailpfad bleibt beim Cache-Prefill plus sequenzgesicherter Worker-Hydration. Rechnungsansicht-MyPy, globales Ruff und `git diff --check` bestanden.
- AP06 F17 Unreleased-Katalog: Der erstmalige Datei-/Settings-Read wurde aus `_on_stuecke_loaded` in einen lifecycle-verfolgten Worker verschoben; erst nach erfolgreichem Vorwaermen startet die sequenzgesicherte Teileaufloesung. Ein blockierter Loader-Fake bestaetigt den Qt-Heartbeat und den anschliessenden Renderpfad; 87 Rechnungsansichtstests, Rechnungsansicht-MyPy und globales Ruff bestanden. Die aktuelle Gesamtsuite: **2.131 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (171,64 s)**. Manuelle Katalogschreibvorgaenge nach Nutzerbestaetigung bleiben als synchroner Restpunkt dokumentiert.
- Hosted Windows CI fuer `66ae954` (Run `42893153938`): Ruff erfolgreich; **2.131 bestanden, 5 uebersprungen, 1 bestehende fitz-Warnung (561,41 s)**. Der weiche MyPy-Schritt meldet die bestehende Baseline von **483 Fehlern in 88 Dateien**; der Rechnungs-View ist lokal gezielt fehlerfrei typisiert.
- AP08 ProductCatalogService: 16 MyPy-Fehler in der direkt genutzten Katalogabhaengigkeit behoben; JSON-/Hub-Werte werden vor Zugriff und Iteration eingegrenzt. `catalog.py` ist jetzt mit `--follow-imports=silent` fehlerfrei; der lokale Paketlauf sinkt von 479/86 auf **463 Fehler in 85 Dateien**. Katalog-/Hub-Fallback-/Druckentscheidungstests: 15 bestanden; Gesamtsuite: **2.131 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (152,86 s)**.
- Hosted Windows CI fuer `fdef1db` (Run `42898060086`): Ruff erfolgreich; **2.131 bestanden, 5 uebersprungen, 1 bestehende fitz-Warnung (775,05 s)**. Der weiche MyPy-Schritt bestaetigt **467 Fehler in 87 Dateien**, 16 weniger und eine Datei weniger als vor dem Katalog-Fix.
- AP08 sevDesk-Rechnungsclient: Falsche Tabellen-Metadaten-Typen, unscharfe Retry-/Timeout-kwargs, optionale Positionsnummernkonvertierung und PDF-Rekursionstypen bereinigt. `invoice_client.py` und `InvoiceProcessingService` sind zusammen gezielt MyPy-fehlerfrei; 79 Client-/Processing-Tests bestanden. Lokale globale MyPy-Baseline sinkt weiter auf **453 Fehler in 84 Dateien**. Gesamtsuite: **2.131 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (150,90 s)**.
- Hosted Windows CI fuer `a66e19b` (Run `42901651749`): Ruff erfolgreich; **2.131 bestanden, 5 uebersprungen, 1 bestehende fitz-Warnung (706,97 s)**. Der weiche MyPy-Schritt bestaetigt **457 Fehler in 86 Dateien**, zehn weniger und eine Datei weniger als vor dem Rechnungsclient-Fix.
- AP08 sevDesk-PartClient: Optionaler Steuersatz und optionale Kategorie-/Einheitspayloads sind defensiv eingegrenzt; `part_client.py` ist gezielt MyPy-fehlerfrei. Neun PartClient-Regressionen bestanden; lokale globale MyPy-Baseline sinkt auf **450 Fehler in 83 Dateien**.
- AP08 PLC-Polling-Typisierung: Parcel-, Artikel- und Metadaten-Payloads sind nun als `dict[str, Any]` deklariert; gezieltes MyPy ist fehlerfrei, Ruff bestanden und PLC-Webservice-/Label-Dialogtests: **39 bestanden**. Die lokale globale MyPy-Baseline sinkt auf **447 Fehler in 82 Dateien**.
- AP08 PLC-Zolldokument-Typisierung: PyMuPDFs untypisierte Byte-/Bool-Rueckgaben sind an der PDF-Bytes- und Seitengroessen-Grenze explizit normalisiert; `customs_document.py` ist gezielt MyPy-fehlerfrei. Zoll-PDF-/Archivtests: **16 bestanden**, Ruff bestanden; lokale globale MyPy-Baseline jetzt **444 Fehler in 81 Dateien**.
- AP08 PLC-Referenztypisierung: Die Uebersetzung typografischer Minuszeichen in PLC-sichere Bindestriche verwendet nun eine vollstaendig typisierte Mapping-Tabelle. `plc/models.py` ist gezielt MyPy-fehlerfrei; PLC-Modell-/Webservice-/Zolldokument-/Archivtests: **35 bestanden**, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **443 Fehler in 80 Dateien**.
- AP08 PLC-Shipment-Service: Das persistierte Parcel-Snapshot-DTO ist am Repository-Aufruf explizit als `tuple[dict[str, object], ...]` typisiert. `plc/service.py` ist gezielt MyPy-fehlerfrei; PLC-Webservice-/Archiv-/Evidence-Dialogtests: **33 bestanden**, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **442 Fehler in 79 Dateien**.
- AP08 PLC-Packlisten-PDF: Die PyMuPDF-Seite wird als dynamische Fremdbibliotheksgrenze mit `Any` behandelt; dadurch entfallen unzutreffende `object`-Attributfehler und `packing_list.py` ist gezielt MyPy-fehlerfrei. Packlisten-/Labeldialogtests: **22 bestanden**, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **426 Fehler in 78 Dateien**.
- AP01 DraftInvoiceService-Typisierung: Wix-Buyer-, Billing-, sevDesk-Part- und Unity-Payloads werden nach wiederholter Fremddatenpruefung zentral als sichere Dictionary-Payloads eingegrenzt. `draft_invoice/service.py` ist gezielt MyPy-fehlerfrei; DraftInvoice-/SpecialOrder-/Preflight-Tests: **15 bestanden**, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **416 Fehler in 77 Dateien**.
- AP06 PLC-Webservice-Typisierung: Zeep-/Requests-Aufrufe sind als dynamische Fremdbibliotheksgrenze markiert; der SOAP-Service wird am Protocol-Eingang gecastet. `plc/webservice.py` ist gezielt MyPy-fehlerfrei; PLC-Webservice-Tests: **19 bestanden**, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **411 Fehler in 76 Dateien**.
- AP06 PDF-Renderer-Typisierung: Farb-/Schwarzverstaerkungsmodi werden nun ohne redundante Casts und mit einer zentralen Auto-Modus-Aufloesung verengt; der konkrete PyMuPDF-Import wird als untypisierte Bibliotheksgrenze markiert. `pdf_renderer.py` ist gezielt MyPy-fehlerfrei; Renderer-Tests: **22 bestanden**, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **405 Fehler in 75 Dateien**.
- AP06 Lieferschein-PDF: Der lazy geladene PyMuPDF-Import ist als optionale untypisierte Bibliotheksgrenze deklariert. `sendungen/delivery_note.py` ist gezielt MyPy-fehlerfrei; der Lieferschein-PDF-Regressionstest bestanden, Ruff bestanden. Lokale globale MyPy-Baseline jetzt **404 Fehler in 74 Dateien**.
- Vollsuite nach PLC-/DraftInvoice-Typisierung und SQLite-Teststabilisierung: **2.131 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (149,46 s)**. Globales Ruff und `git diff --check` gruen.
- Hosted Windows CI fuer `f0acc44` (Run `42904386317`): Ruff erfolgreich; **2.131 bestanden, 5 uebersprungen, 1 Warnung (748,17 s)**. Der weiche MyPy-Schritt meldet **455 Fehler in 85 Dateien** nach PartClient-Typisierung.
- AP08 MainWindow-Typisierung: Startup-Worker-Rueckgaben, QApplication-Themegrenze und Shutdown-Hooks werden zur Laufzeitform passend eingegrenzt; Performance-Snapshots verwenden `EventLoopGap`. Gezieltes MyPy, Ruff und MainWindow-/Shutdown-Tests: **5 bestanden**; globale lokale MyPy-Baseline jetzt **400 Fehler in 73 Dateien**. Hosted Windows CI fuer den vorherigen Commit `caa3cc2` (Run `42908814236`): Ruff erfolgreich, **2.131 bestanden, 5 uebersprungen, 1 Warnung (522,21 s)**; weiches MyPy **411/77**.
- AP08 Product-Hub-Inventargrenze: `InventoryService.resolve_variant_by_sku` deklariert den bereits bestehenden `ResolvedSku | None`-Vertrag explizit. Gezieltes MyPy und Ruff bestanden; Inventarservice-, Quellen-Audit- und Alarmtasktests: **23 bestanden**. Globale lokale MyPy-Baseline sinkt auf **399 Fehler in 72 Dateien**.
- AP08/F16 Legacy-Bestandsspiegel: Der Settings-JSON-Wert wird vor `int()` auf die bisher akzeptierten JSON-Zahl-/Texttypen eingegrenzt; Service- und Sessiongrenzen sind typisiert. Gezieltes MyPy/Ruff und drei Mirror-Regressionen bestanden; globale lokale MyPy-Baseline sinkt auf **396 Fehler in 71 Dateien**.
- AP05/F16 getrennte START-Buchungen: Fake-Test bildet erfolgreichen Hub-Commit mit anschließendem Legacy-Ausfall ab. Resume wiederholt den idempotenten Hub-Aufruf, bucht Legacy genau einmal nach und löscht erst danach die Warnung. Der komplette InvoiceProcessingService-Testblock besteht mit **61 Tests**; kein Produktivbestand wurde angesprochen.
- AP06/F17 Unreleased-START: START-Klaerungen persistieren Alias-/Produktentscheidungen jetzt in einem lifecycle-verfolgten Worker. Produktdialoge und die START-Vorpruefung setzen erst nach dem Commit fort; bei Writefehler oder Abbruch startet keine Produkt-/Rechnungsverarbeitung. Regressionen decken den Qt-Heartbeat waehrend blockiertem Write, Callback-Reihenfolge und START-Fortsetzung erst nach Commit ab. Lokale Ruff- und Diff-Pruefungen bestanden; lokale Qt/MyPy-Ausfuehrung ist mangels PySide6/MyPy nicht verfuegbar. Hosted-Windows-Lauf `43035742212` bestand Ruff und meldete 2.187 bestandene Tests/5 uebersprungene Tests, endete aber mit einem Teardown-Fehler im Test-Dummy (fehlende Shutdown-Methoden); der Shutdown-Pfad wurde danach geh?rtet, sodass auch ein leichtgewichtiger Rechnungs-View-Stub ohne Shutdown-Hooks sicher behandelt wird (Commit `66a015f`). Rechnungsauswahl, START und PRINT-PRODUKTE-`+` verwenden nun den gleichen lifecycle-verfolgten Settings-Worker; weitere F17-I/O- und Callback-Restpunkte bleiben offen. Hosted-Windows-Run `43044613867`: **2.187 bestanden, 5 uebersprungen, 1 Warnung**; Ruff gruen, beide Rechnungsdateien MyPy-fehlerfrei.
- AP01/F13 Folgepfad-Audit und Nutzerentscheidung (11.11.2026): Zahlungsbuchung, START-Fulfillment und Nachlieferungskontext verwenden weiter `summary.order_reference`; der Nutzer hat ausdrücklich entschieden, dieses bestehende Verhalten beizubehalten. Claims schützen weiterhin vor Doppelwrites.
- F13 Schnittstellenvertrag geprueft: `wix-sevdesk-api/src/services/sevdesk.Invoice.js#getWixInvoiceReference` schreibt entweder nur die Wix-Ordernummer oder `PO | Wix-Ordernummer`; der XW-Office-Parser extrahiert eine fuenfstellige Nummer aus allgemeinen Referenzfeldern. Im Bare-Number-Format gibt es kein Herkunftsmerkmal; dies ist als bewusst akzeptierte Produktregel dokumentiert, nicht als technisch bewiesene Cross-System-Identitaet.
- AP01/F14 Positionsdaten: WorkContext uebernimmt Einheit, Netto-/Brutto-Einzelpreis, Einzelsteuer, Steuersatz, Rabatt und rabattierte Netto-/Steuer-/Bruttosummen. Die Detailansicht zeigt nur vorhandene Werte; ungültige optionale Zahlen bleiben leer. Die bisherige PLC-Preissemantik und Druck-/Lagerentscheidungen bleiben unverändert. Kontext-Unit-Tests: **12 bestanden**; Ruff und `git diff --check` bestanden. Der lokale UI-Test ist mangels PySide6 nicht sammelbar und wird im gehosteten Windows-Lauf nachgeprüft.
- Vollsuite nach split START-Buchung und Unreleased-Cachefehlerregressionen: **2.134 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (204,36 s)**. Globales Ruff und `git diff --check` gruen; Testumgebung ohne Produktivzugriffe.
- AP08 Inventur-API-Typisierung: `InventoryCountService` nimmt jetzt eine typisierte SQLAlchemy-Session-Factory an; der API-Router serialisiert ein explizites `InventoryCountView`. Gezielt MyPy/Ruff und beide Inventurservice-Regressionen bestanden; lokale Repository-Baseline **395 Fehler in 69 Dateien**.
- AP08 Product-Hub-Wiedervorlagen: Die durable Wix-Reconciliation-Abfrage materialisiert das Repository-Ergebnis explizit als `list`, passend zum Servicevertrag. Gezielt MyPy/Ruff und Konfliktwizard-/Advisor-Tests: **28 bestanden, 1 bestehende Deprecation-Warnung**; globale lokale Baseline **394 Fehler in 68 Dateien**.
- AP08/F17 Lageralarm-Mail-Typisierung: Session-Factory und `MailDeliveryService` sind an der Servicegrenze explizit typisiert. Gezieltes MyPy/Ruff sowie Alarmtask- und Dialogregressionen: **7 bestanden**; globale lokale Baseline **393 Fehler in 67 Dateien**.
- F13 bestehende Referenzregel: Nutzer hat am 11.11.2026 bestätigt, dass die aktuelle Zuordnung über sevDesk-`order_reference` erhalten bleibt. InvoiceProcessing- und UI-Regressionsblock bestätigt Zahlungsbuchung, Fulfillment, Fallback auf sevDesk-Details ohne Wix-Treffer und die WIX-ORDER-Sichtbarkeit: **178 Rechnungs-/Inventartests bestanden**.
- AP08 Legacy-Inventar-Typgrenze: JSON-Werte für START-Journal, Bestandssnapshot, Produktzeilen und Printplan werden vor Konvertierung/Zugriff eingegrenzt; Shadow-Mirror-Aufrufe verwenden explizit typisierte Schlüsselwortargumente. `services/inventory/service.py` ist gezielt MyPy- und Ruff-fehlerfrei; START-/Inventar-/InvoiceProcessing-Tests: **84 bestanden**.
- AP06/F18 BuyerNote-Dialoglebenszyklus: Close, Escape und Fensterschließen werden während Outlook-/Lieferschein-Worker nicht zugelassen; nach Worker-Ende wird normal geschlossen. Zwei blockierte Fake-Worker-Qt-Regressionen bestehen; BuyerNote-/Lieferschein-UI-Tests: **8 bestanden**. Beide Dialogdateien sind gezielt MyPy- und Ruff-fehlerfrei.
- Aktuelle Vollsuite am 11.11.2026: **2.143 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung (203,73 s)**; `ruff check src/` erfolgreich; globale lokale MyPy-Baseline **383 Fehler in 65 Dateien**. Hosted CI fuer `4ed97ed` (Run `42990359119`) und `b5eb5e4` (Run `42990467071`) erfolgreich.
- BuyerNote-/Outlook-Nacharbeit auf Nutzercommits `d6775c6`/`ab285b1`: Aktionsbuttons in kompakter Reihe mit Tooltips; Antwortentwurf fuegt die Outlook-Signatur zwischen eigenem Antworttext und zitierter Kaeufernotiz ein. Betroffene UI-/Outlook-Regressionen: **17 bestanden**; gezieltes Ruff erfolgreich; globale MyPy-Baseline unveraendert bei **383 Fehlern in 65 Dateien**.
- Hosted Windows CI fuer aktuellen Stand `6f00440` (Run `42994701377`): Ruff und Vollsuite erfolgreich; **2.147 bestanden, 5 uebersprungen, 1 Warnung (776,44 s)**; weicher MyPy-Gate **390 Fehler in 68 Dateien**.
- AP07/F19 gebuendelte Hub-Bestandsanzeige: `InventoryRepository.list_stock_by_variants` und `InventoryV2Service.variant_on_hand_many` laden den Standort einmal und alle Bestandszeilen gesammelt; die Rechnungsansicht bereitet Printprodukt-Bloecke weiter im sequenzgesicherten Worker vor und erhaelt den sevDesk-Cache-Fallback. Query-Zaehlerregression: 2 SQL-Abfragen fuer zwei SKUs statt 4 einzeln; Service-/View-Regressionen **104 bestanden**, gezieltes MyPy/Ruff fehlerfrei. Vollsuite: **2.148 bestanden, 5 uebersprungen, 1 bestehende Warnung (188,60 s)**; lokale globale MyPy-Baseline **383 Fehler in 65 Dateien**.
- AP06/F18 Aftercare-Callback-Lebenszyklus: versp?tete Positions-/Aktions-/Druckergebnisse pruefen den Qt-Owner, bevor sie Widgets oder Dialoge aktualisieren. Regression zerstoert den Aftercare-Tab mit blockiertem Positions-Worker; danach trifft das Ergebnis keine Qt-Widgets. Aftercare-Dialogsuite **13 bestanden**; die beiden Stale-/Destroyed-Owner-Regressionen bestanden in fuenf Wiederholungen. Gezieltes Ruff/MyPy fehlerfrei; Vollsuite des gemeinsamen Arbeitsbaums **2.157 bestanden, 5 uebersprungen, 1 bestehende Warnung (204,78 s)**.
- AP06/F17 BuyerNote-START-Haltepunkt: Das Speichern laeuft jetzt im BackgroundWorker; Skip/Erledigt, Fallwechsel und Close sind bis zum Commit gesperrt, danach setzt der Dialog START fort. Ein blockierter Fake bestaetigt Heartbeat und Reihenfolge; BuyerNote-Dialogsuite **9 bestanden**, gezieltes MyPy/Ruff fehlerfrei, Vollsuite **2.157 bestanden, 5 uebersprungen, 1 bestehende Warnung (201,36 s)**. Der Tabellen-Toggle bleibt als AP06-Rest noch synchron.
- AP06/F17 Rechnungslisten-START-Haltepunkt: Toggle und Tabellen-Refresh laufen in einem lifecycle-verwalteten Worker; Konflikte mit einem anderen PC bleiben durch Versionspruefung sichtbar. Ein blockierter Fake bestaetigt Eventloop-Heartbeat und Statusaktualisierung. Ein gezielter Qt-Test, MyPy und Ruff bestanden; gemeinsame Vollsuite **2.158 bestanden, 5 uebersprungen, 1 bestehende Warnung (200,50 s)**.
- START-Zurueckstellungen: Persistente Holds pro Rechnung sperren Voll-START, Selektion und Recovery, zeigen Grund/Notiz/Wiedervorlage und lassen bewusste Freigabe zu. Der Hosted-Windows-Lauf deckte auf, dass zwei schnelle Aenderungen denselben Zeitstempel erhalten konnten; der Vergleichstoken wird jetzt innerhalb der atomaren Setting-Mutation monoton erhoeht. Deterministischer Regressionstest erzwingt identische Zeitstempel und prueft, dass eine veraltete Freigabe von einem anderen PC abgewiesen wird. Lokal: **7 Hold-Tests bestanden**, gezieltes MyPy und Ruff fehlerfrei; Vollsuite **2.157 bestanden, 5 uebersprungen, 1 bestehende Warnung (197,61 s)**; Windows Hosted-CI nach diesem Fix noch ausstehend.
- Hosted Windows CI fuer `04171c5` (Run `42987122286`): Ruff erfolgreich; **2.134 bestanden, 5 uebersprungen, 1 Warnung (615,78 s)**; der weiche MyPy-Schritt meldet **403 Fehler in 74 Dateien**. Dieser Stand enthaelt die START-Teilfehler- und Katalog-Write-Regressions.
- Vollsuite nach PLC-Polling: Ein bestehender SQLite-Outbox-Test hing gelegentlich davon ab, ob die DB-Standardzeit beim Insert die zuvor im Test gelesene Uhrzeit ueberschritt. Der Ready-Zeitpunkt ist im Test nun explizit gesetzt. Der erste Gesamtlauf reproduzierte den Flake (2.130 bestanden, 1 fehlgeschlagen); gezielter Testlauf danach: **9 bestanden**; wiederholte Gesamtsuite: **2.131 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (152,07 s)**.
- Vollsuite nach Generation- und Wix-Worker-Korrekturen: **2.129 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (158,33 s)**. Nach der Force-Read-Optimierung liefen erneut alle 34 Expense-Tests; globales Ruff, Rechnungsansicht-MyPy und `git diff --check` bestanden. Windows-Hosted-Lauf 42880435956 nach beiden Aenderungen: Ruff erfolgreich, **2.129 bestanden, 5 uebersprungen, 1 fitz-Warnung (515,13 s)**. Hosted-MyPy bleibt ein weicher Gate und meldet 485/89; die Rechnungsansicht selbst ist lokal gezielt fehlerfrei.
- Expense-Review-Typisierung: `list_position_rules` lieferte ein `SimpleNamespace` als `ExpensePositionRule` und hatte ein unnoetiges Return-Ignore. Ein tenant-normalisiertes `ExpensePositionRuleView` bildet den tatsaechlichen Vertrag ab. Tenant-Key-Regression plus Expense-Service-/Review-Tests: **62 bestanden**; gezieltes MyPy fuer `expenses/service.py` und Ruff fuer `src/` gruen. Voll-Mypy lokal jetzt **479 Fehler in 86 Dateien** (vorher 481/87).
- Hosted-CI nach Expense-Review-Typisierung (`0423121`): Lauf 42883508244 erfolgreich; Ruff gruen, **2.130 bestanden, 5 uebersprungen, 1 fitz-Warnung (688,37 s)**. Weicher Hosted-MyPy-Gate: **483 Fehler in 88 Dateien**, zwei weniger als vor dem DTO.
- AP02/AP03 PostgreSQL-Gate: Fuenf opt-in Integrationsregressionen liefen auf einem kurzlebigen lokalen PostgreSQL-16-Container mit zufaelligem Schema und ohne Produktivdaten. Erstbuchung, Credit-Cap, Part-Stock-GET/SET und Claim-Serialisierung unter unabhaengigen Datenbankclients sowie Rollback nach injiziertem DB-Fehler bestanden. Der Container wurde danach gestoppt. Gesamtsuite mit gesetztem `XW_TEST_POSTGRES_URL`: **2.125 bestanden, 1 bestehende Warnung, 0 fehlgeschlagen (155,36 s)**.
- Abschlusslauf nach strikter Payment-Link-Antwortvalidierung: **2.125 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (155,36 s)**.
- AP06 Sendungen-Dialog: Zwei unreferenzierte Helfer fuer direktes Speichern bzw. PDF-Erzeugen im GUI-Thread und ihr nie genutzter PDF-Cache wurden entfernt; alle produktiven Aufrufe fuer diese Aktionen laufen bereits ueber Worker. Inventarzeile der Dialogmethoden aktualisiert. 11 Sendungen-Dialogtests, Ruff und MyPy gruen. Ein erster Testlauf traf ein Timingfenster im Statusassert; Einzeltest und kompletter Dialoglauf bestanden danach.
- AP06 F17 Lageralarme: Nach erfolgreichem Schwellenwertspeichern oder Automatikwechsel wurde der Refresh aus dem Ergebnis-Signal angefordert, solange derselbe Worker noch lief; der Dialog verwarf ihn daher und zeigte weiter den alten Wert. Ausstehender Refresh wird nach Worker-Ende gestartet und beim Schliessen verworfen. Regression bestaetigt Worker-Heartbeat, zweiten Detailabruf und aktualisierten Schwellenwert; fokussierter Dialogtest, MyPy/Ruff und Gesamtsuite (**2.121 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Warnung, 148,67 s**) gruen.
- AP05 F16 START-Resume: Ein zuvor fehlgeschlagener Product-Hub-/Legacy-Bestandswrite wurde nur in `last_warning` gespeichert und nicht als Resume-Arbeit erkannt, falls Rechnung, Label, Mail und Zahlung bereits abgeschlossen waren. Solche spezifischen Bestandswarnungen waehlen nun den physischen Resume-Pfad aus; nur bei konfigurierter passender Integration wird wiederholt und Erfolg entfernt die Bestandswarnung. Fake-InvoiceInventory-Test deckt Fehler, erneuten Versuch, keine doppelten Papier-/Mailaktionen und Warnungsbereinigung ab. InvoiceProcessingService **60 Tests**, gezieltes MyPy/Ruff und Gesamtsuite (**2.122 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Warnung, 145,11 s**) gruen.
- AP01 F13 Detailaktionen: `WIX ORDER` wurde vor dem Abschluss der Kontextpruefung allein anhand der gespeicherten Referenz eingeblendet. Der Button bleibt nun verborgen, bis `InvoiceWorkContext` einen bestaetigten Wix-Order-Kontext liefert. Manuelle fuenfstellige Referenz ohne Kontext und SevDesk-Fallback: 2 Regressionen bestanden; Rechnungsansicht-MyPy und Ruff gruen. Weitere rohe Referenzpfade bleiben zu pruefen.
- AP08 Hosted-CI-Pruefung: Die fruehere Ruff-Abweichung ist durch die festgelegte Ruff-Version und Regelbasis behoben; der Hosted-Lauf besteht Ruff. Der Lauf 42876458401 erreichte 2.127 bestandene Tests und 5 uebersprungene Tests, scheiterte aber noch an genau einem Expense-Sync-Rennen bei gleicher Windows-Zeitaufloesung.
- AP06 Nachlieferungsdialog: Freie Mengen-Textfelder mit stillem Fallback auf 1 durch begrenzte `QSpinBox`-Editoren ersetzt. Originalpositionen bleiben auf die Ausgangsmenge gedeckelt; manuelle Zeilen erlauben 1..999. 12 Nachbetreuungs-/Nachlieferungs-Qt-Tests, gezieltes MyPy/Ruff sowie Rechnungs-UI-/InvoiceProcessing-Ruff bestanden. Gesamtsuite: **2.124 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 bestehende Starlette-Warnung (151,09 s)**.
- AP07 Snapshot-Generationszustand: Die In-flight-Invalidierung nutzt einen einzelnen monotonen Service-Token statt einer pro Rechnungs-ID wachsenden Map; so bleibt ihr Verwaltungs-Speicher konstant. 59 InvoiceProcessingService-Tests, Ruff/MyPy gruen; Gesamtsuite **2.110 bestanden, 1 bestehende Warnung (151,01 s)**.
- AP03 manuelle Digital-Lizenz-Freigabe: `DigitalLicenseService.mark_done` prueft Wix-Status und legt Fulfillment nun innerhalb eines dauerhaften `digital_license_fulfillment`-Claims an. Ein Timeout nach serverseitiger Annahme wird per Readback als Erfolg erkannt; bei unklarem Readback wird `unknown` gespeichert und der zweite Client blockiert. 4 neue Service-Regressionen pruefen Doppelaufruf ueber Serviceinstanzen, Timeout-Readback, Unknown-Sperre und gleichzeitigen Write; 12 Service-/5 UI-Tests, Ruff/MyPy gruen; Gesamtsuite **2.114 bestanden, 1 bestehende Warnung (150,35 s)**.
- AP03 Payment-Link-Pruefung: `SpecialOrderService.create_payment_link` erzeugt pro POST einen neuen Request-Key; nach Annahme mit verlorener Antwort kann ein UI-Retry einen zweiten zahlbaren Link anlegen. Als neues offenes P1 F23 mit konkreten Timeout-/Dedupe-Akzeptanzkriterien dokumentiert; automatische Deduplizierung bleibt abhaengig vom Vertrag des konfigurierten externen Endpunkts und der Entscheidung, wie ein bewusst neuer Link gegen einen Retry abgegrenzt wird.
- AP08 Rechnungsansicht/PLC: `3c5c6aa` (`Type invoice view and PLC dialogs`) macht `view.py`, `plc_label_dialog.py` und `plc_evidence_dialog.py` gezielt mypy-fehlerfrei. Qt-Modell-/Delegate-Signaturen, gespeicherte Payloads, sortierte Zeilenindizes, asynchrone Wix-Ergebnisse und Dialoglebenszyklen sind pr?zise typisiert. Das Rechnungs-UI-Paket hat **0 MyPy-Fehler**; repositoryweit sind es **506 Fehler in 91 Dateien**. 141 gezielte UI-/PLC-Tests und Gesamtsuite **2.107 bestanden, 1 bestehende Warnung (152,57 s)**; Ruff gr?n.
- F12 Part-Stock-Konkurrenz im Prozess: `PrintDecisionEngine` sperrt pro sevDesk-Part die Bestandsabfrage und -erhoehung; gleichzeitige Worker verlieren keine Erhoehung. `print_decision.py` mypy/Ruff fehlerfrei; fokussierte Drucktests **13 bestanden**; Gesamtsuite **2.086 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung**.
- F12 Cross-Instance-Part-Lock: `SettingKvRepository.advisory_lock` haelt den PostgreSQL-Transaktionslock waehrend der begrenzten Part-GET/SET-Sequenz; Bootstrap injiziert das gemeinsame Repository in `PrintDecisionEngine`. Thread-Test mit zwei Engines und gemeinsamem Lock-Port belegt Serialisierung; Repository-, Claim- und Drucktests **21 bestanden**, einschliesslich SQLite-Kontext-/Schluesselvalidierung; Ruff und mypy fuer Repository, Bootstrap und Druckservice gruen. Kein echter PostgreSQL-Parallelitaetslauf (G2).
- F12 Einzelproduktdruck: Rechnungsansicht **83 Tests bestanden**; paralleler Druck
  verschiedener SKUs bleibt erlaubt, zweiter aktiver Auftrag derselben SKU wird
  verworfen, und die Sperre faellt nach Abschluss weg. Gesamtsuite danach **2.081 bestanden**.

- F12 persistenter Druck-Claim: Vor jedem physischen Produktdruck wird jetzt ein
  Claim pro sevDesk-Part-ID (Fallback: normalisierte SKU) atomar in `SettingKV`
  erworben. Das gilt fuer Rechnungs-Einzel-/Sammeldruck, offene Produkte und den
  Produktbereich. Andere Instanzen werden bei `running`/`unknown` blockiert;
  ein bewusster erneuter Druck nach `succeeded` erhaelt eine neue Lauf-ID. Claim-,
  Legacy-Druck- und Rechnungs-UI-Tests **94 bestanden**; Ruff fuer alle geaenderten
  Python-Dateien gruen; finale Suite **2.091 bestanden, 1 bestehende
  Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (150,21 s)**. Ein Drucker-
  oder sevDesk-Fehler nach moeglichem physischen Druck bleibt `unknown` und sperrt
  automatische Wiederholung; eine Bedienoberflaeche fuer manuellen Abgleich ist
  weiterhin OFFEN. Echtes PostgreSQL-/Mehr-PC-Verhalten bleibt bis G2 BLOCKIERT.
  Mypy fuer die drei betroffenen Services/Views meldet weiterhin **20 bestehende
  Fehler ausschliesslich in `ProductsView`** (u. a. alte Callback-Signaturen und
  Bestandskorrektur); `operation_claims.py` und `print_decision.py` sind fehlerfrei.
  eine provisorische Schlüsseländerung kaschiert.

Reproduktion der regulären Prüfungen aus dem Repository:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest tests/unit tests/ui tests/integration -q
.\.venv\Scripts\python.exe -m ruff check <geaenderte-Python-Dateien>
.\.venv\Scripts\python.exe -m mypy --follow-imports=silent <betroffene-Produktionsdateien>
```

Vor einer Wiederholung der Gesamtsuite die Isolation gemäß AP08 sicherstellen;
einfaches Löschen von Shell-Variablen reicht bei späterem `.env`-Nachladen nicht.
Lokale Laufprotokolle bleiben außerhalb des Repositories im TEMP-Verzeichnis.

### Verwendeter isolierter Test-Runner

Der folgende Inhalt wurde als tempor?re Python-Datei ausgefuehrt, mit den drei
Testverzeichnissen als Argumenten. Er benoetigt keine zus?tzliche Dependency.
Loopback-Verbindungen bleiben fuer Starlette/Asyncio erlaubt. Der Runner ersetzt
keinen produktiven Schutz oder eine dauerhafte Testinfrastruktur (AP08).

```python
import os
import socket
import sys
import pytest

sys.path[:0] = [os.path.abspath("src"), os.path.abspath(".")]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex

def local_address(sock, address):
    return sock.family == getattr(socket, "AF_UNIX", -1) or (
        isinstance(address, tuple)
        and address[0] in ("127.0.0.1", "::1", "localhost")
    )

def connect(sock, address):
    if local_address(sock, address):
        return original_connect(sock, address)
    raise RuntimeError("Audit blocks external network connections")

def connect_ex(sock, address):
    if local_address(sock, address):
        return original_connect_ex(sock, address)
    raise RuntimeError("Audit blocks external network connections")

socket.socket.connect = connect
socket.socket.connect_ex = connect_ex

class Isolation:
    @pytest.fixture(autouse=True)
    def clear_inherited_wix_credentials(self, monkeypatch):
        for key in ("WIX_API_KEY_DATA", "WIX_API_KEY", "WIX_SITE_ID", "WIX_ACCOUNT_ID"):
            monkeypatch.delenv(key, raising=False)

raise SystemExit(pytest.main(sys.argv[1:], plugins=[Isolation()]))
```

## 9. Verbindlicher Regressionsschutz

- `tests/integration/test_rechnungen_rapid_switch.py`: letzte Auswahl gewinnt,
  alte Wix-Antworten dürfen neue Auswahl nicht überschreiben.
- Rechnungen-Smokes/Suchtests: sofortige Summary-Anzeige vor Hydration,
  START-Deferral, gestuftes Nachladen, aktuelle Sortierung, Reset der Suche.
- `test_invoice_work_context.py` und InvoiceProcessing-Tests: manueller sevDesk-
  Entwurf ohne Wix, Rechnungsadresse als Fallback, eindeutige Herkunft.
- `test_inventory_start_workflow.py`, `test_inventory_policy.py`,
  `test_invoice_inventory_booking.py`, externe Feed-/Gegenbeleg-/Inventurtests:
  Entwurf bucht nicht, Freigabe einmal, richtige Gegenbelegmengen, keine negative
  Bestandsfiktion, Stichtag und Konfliktpersistenz.
- `test_rechnungen_product_print.py` und Toolbar-Smokes: unabhängige Mengen-
  Stepper, einzelne bzw. gesamte Produktdruckaktion, titelgebundene XW-010-
  Konfiguration, manueller Mehrdruck, gespeicherte Historie. **Die neue
  bestandsunabhängige offene Druckmenge nicht aus alten Plänen zurückbauen.**
- Drucktests einschließlich `test_no_external_pdf_printing.py`: nativer
  vektorbasierter Produktdruck, kein automatischer Acrobat-/Raster-Fallback,
  bestätigter Spoolererfolg vor Bestandszugang.
- PLC-Tests: mehrere Sendungen und Packlisten, Duplikaterkennung, Gebühren-/
  Zollregeln, Paketinhalt, Tracking-XML und echte Annahme-/Zustellereignisse erhalten.
- Käufernotiz-/Betreuungs-/Nachlieferungstests: vollständige Bestätigung,
  Skip/Snooze, richtige Rollen und Mengen, keine automatische Doppelverrechnung.
- Neue F03/F04/F05/F06/F07-Tests müssen bei Änderungen an Worker-/Dialogmustern
  gemeinsam mitlaufen; ein reiner `isRunning()`-Check ersetzt ihre Datenbindung nicht.

- AP08 Invoice-Kontext: `address_lines_from_invoice` behandelt optionale Kontakt-/Adressobjekte defensiv und normalisiert optionale PLZ-/Ort-Werte. Zehn bestehende MyPy-Fehler in `invoice_processing/context.py` sind beseitigt; Regression fuer fehlende/fehlerhafte verschachtelte Adressen besteht. Repository-Baseline sinkt von 494/89 auf **484/88**.
- Abschliessender Gesamtlauf nach Sonderauftrags-Service, PostgreSQL-Race-Tests und Invoice-Kontext: **2.124 bestanden, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (157,19 s)**.

## 10. Abschlussbewertung und Betriebsabnahmen

Die sicheren Fixes verbessern konkrete Fehlersituationen, die Reaktionsfähigkeit
des Alarmzählers und die Konkurrenzsicherheit beim Produktdruck. Der persistente
Claim fuer physische Produktdrucke ist umgesetzt; weitere externe Claims,
atomare Buchungs-/Gegenbelegtransaktionen und konsistenter Legacy-/Hub-Verbrauch
bleiben offen.

| Gate | Priorität | Status | Benötigter Nachweis / anfängerfreundlicher Ablauf |
| --- | --- | --- | --- |
| G1 – Windows/Hardware/Integration | P2 | BLOCKIERT | In einer freigegebenen Testumgebung einen Wix-Testauftrag und einen manuell angelegten sevDesk-Testentwurf mit eindeutiger Testadresse bereitstellen. Testdrucker wählen, zuerst PDF/Label/PLC im Testmodus prüfen, anschließend die erlaubten START-Schritte einzeln abnehmen. Versand ausschließlich an eigene Testadresse. Auch Escape/Schließen/Retry und 100–200 % Windows-Skalierung prüfen; Ergebnis und Beleg-/Job-IDs ohne Secrets protokollieren. |
| G2 - Mehr-PC/PostgreSQL/Cutover | P1 | BLOCKIERT | Lokal wurde ein kurzlebiger PostgreSQL-16-Testcontainer ohne Produktivdaten verwendet. Fuenf opt-in Integrationstests bestehen: zwei Clients konkurrieren um die erstmalige Rechnungsbuchung, um zwei Gutschriften mit gemeinsamer Ursprungsposition und um denselben dauerhaften Claim; zwei PrintDecisionEngine-Instanzen serialisieren den Part-Stock-GET/SET-Pfad ueber Advisory-Locks; ein injizierter DB-Fehler belegt Rollback von Ledger, Booking und Bestand. Das Gate bleibt offen fuer AP03-Prozessabbruch/Recovery in zwei echten App-Instanzen sowie Inventur-, Backup-, Shadow- und Cutover-/Rollback-Abnahme. Produktionsdatenbank und Master-Flags blieben unberuehrt. |

### Abschlussnachweis

Frueherer Auditstand: `dafebdd` (`Fix invoice quantity validation and asynchronous action races`) und der zugehoerige Dokumentationscommit wurden bereits nach `origin/main` gepusht.

Fortschreibung F12: `f95d4e8` (`Add persistent claims for product printing`) wurde nach den Tests erfolgreich zu `origin/main` gepusht. Suite: **2.091 bestanden**, Ruff: **gruen**. Mypy-Baseline fuer die drei betroffenen Services/Views: **20 bestehende Fehler in `ProductsView`**, keine in den neuen Claim-/Druckservice-Methoden. G1/G2 bleiben wie oben BLOCKIERT; `unknown`-Claim-Abgleich durch Bedienpersonal bleibt OFFEN.

Fortschreibung AP08: `0038419` (`Type-check ProductsView worker payloads`) wurde nach 26 fokussierten und 2.092 Gesamttests erfolgreich zu `origin/main` gepusht. `ProductsView`-Mypy ist 0; die Repository-Baseline liegt bei 646 Fehlern in 100 Dateien.

Fortschreibung AP06: `9a7b329` (`Move aftercare tab database work off UI thread`) wurde nach 11 fokussierten und 2.094 Gesamttests erfolgreich zu `origin/main` gepusht. Aftercare-Liste, Positionen und Statusaktionen laufen im Worker; Auswahlwechsel verwerfen veraltete Positionsantworten.

Fortschreibung AP06: 296ac8e (Avoid synchronous invoice dialog count reads) wurde nach 32 gezielten UI-Tests und 2.099 Gesamttests zu origin/main gepusht. Sendungen-, Digital- und Ueberweisungsdialoge liefern lokale Zaehlersnapshots; Nachbetreuungs-Badges aktualisieren sich asynchron.

Fortschreibung AP06: 8197e64 (Move B2B credit alert reads off UI thread) wurde nach 10 gezielten Tagesgeschaeft-Tests und 2.100 Gesamttests zu origin/main gepusht. Die manuelle B2B-Pruefung laedt Rechnungen und Planstatus im Worker; bestaetigte Datenbank-Schreibaktionen bleiben als offener Teil von AP06 dokumentiert.

Fortschreibung AP06: cf45a12 (Move confirmed B2B credit writes off UI thread) wurde nach 11 gezielten Tagesgeschaeft-Qt-Tests und 2.101 Gesamttests zu origin/main gepusht. Zahlungsplaene und Kundenlimits werden erst nach bewusster Bestaetigung gespeichert und blockieren den GUI-Thread nicht; Fehler bleiben sichtbar.

Fortschreibung AP07: `5d16413` (`Invalidate invoice snapshots after finalization`) implementiert Cache-Invalidierung nach finaler Rechnungsfreigabe und Entwurfserstellung; ein Generationstoken verwirft Batchantworten, die vor einer Mutation begonnen haben. 56 fokussierte Tests, Ruff und gezieltes MyPy gruen; Gesamtsuite 2.106 bestanden. Push erfolgt nach ff-only Synchronisierung.

Fortschreibung AP07: Batched Hub-SKU-/Alias-Aufloesung fuer offene Printprodukte in `ProductHubRepository`, `InventoryV2Service` und Rechnungsansicht ergänzt. 34 gezielte Repository-/UI-Tests sowie 88 Rechnungsansicht-Smoke-Tests bestanden; gezieltes Ruff und striktes MyPy fuer die drei Produktionsdateien gruen. Hosted CI fuer `8486f23` (Ruff, volle Pytest-Suite, MyPy) erfolgreich; Railway-Deployment `10b49488-6383-4cf2-b11b-d7892d077b1f` ebenfalls **SUCCESS**.

Fortschreibung AP07: Produkt-Hub-Snapshots werden fuer die offenen Printprodukte nun ueber `POST /api/v1/desktop/products/snapshots/batch` gebuendelt geladen und im `ProductCatalogService` ausschliesslich fuer den aktuellen Vorbereitungslauf vorgewaermt; unbekannte SKUs werden in diesem Lauf ebenfalls gecacht. Der Client dedupliziert normalisierte SKUs und teilt Requests in maximal 100 Eintraege. Der einzelne Snapshot-Endpunkt nutzt denselben Mapper. 29 fokussierte API-/Client-/Katalog-/UI-Regressionen und alle 89 Rechnungsansicht-Smoke-Tests bestanden; Ruff und striktes MyPy fuer sechs betroffene Produktionsdateien gruen. Der bestehende sevDesk-/Legacy-Fallback bleibt erhalten. CI fuer den neuen Stand ist noch ausstehend. Der vorherige CI-Lauf fuer `9e950d7` schlug nur in einem Print-Center-TTL-Test fehl, weil dieser eine absolute monotone Zeit statt eines abgelaufenen Zeitpunkts setzte; der Test verwendet nun `time.monotonic() - 301` und ist im fokussierten Lauf gruen.

AP06/AP08 CI-Isolation: Der Hosted-Lauf fuer `64223ba` brach im Windows-Pytestprozess mit Heap-Corruption ab, waehrend `test_rechnungen_applies_persistent_wix_cache_before_background_load` noch den Katalog-Worker ausfuehrte. Der Test wartete bisher auf den Tabellen-Render, nicht auf das Ende dieses Workers. Er wartet jetzt zusaetzlich auf den Worker-Abschluss; der betroffene Test bestand lokal fuenfmal, die gesamte Rechnungsansicht-Smoke-Suite mit 89 Tests ebenfalls. Das ist eine plausible Isolationsursache, kein Nachweis eines Produktionscrashs. Vollstaendiger Hosted-Lauf mit dieser Testanpassung steht noch aus.

Regression nach AP07/CI-Isolation auf `76a9ada`: Vollstaendige lokale Suite **2.172 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung (206,30 s)**; die Smoke-Suite Rechnungen **89 bestanden**, der Worker-Lifecycle-Test **5/5 Wiederholungen bestanden**. Der Product-Hub-Deploymentstand `76a9ada` ist auf Railway **SUCCESS** und `/health` antwortet HTTP 200. Hosted CI `43016634244` wurde nach neueren Main-Commits abgebrochen; der aktuelle Voll-Workflow fuer `7305213` (`43018537354`) wird beobachtet.

AP05/AP08 Nachpruefung der auf `ff7ac62` ergaenzten externen Bestandsunterdeckung: `SevdeskInvoiceInventoryPoller` verwirft keine `Decimal`-Mengen am Mirror-Callback mehr, sondern uebergibt den validierten ganzzahligen Wert; JSON-/Part-Payloads sind praezise typisiert und vor Zugriff eingegrenzt. Sechs strikte MyPy-Fehler in `sevdesk_invoice_inventory.py` beseitigt; die drei betroffenen Service-/API-Dateien bestehen striktes MyPy, Ruff und **33 Inventur-/Bestandsregressionen**. Der aktuelle Hosted-CI-Lauf fuer `7305213` umfasst diese Aenderung und laeuft noch.

AP08 Inventur-Sync-Typisierung: Der Shortage-Callback in `inventory_sync_cli.py` ist jetzt mit `InvoiceInventoryLine`/`Exception` typisiert. Striktes MyPy besteht fuer fuenf betroffene Product-Hub-/Rechnungsdateien; Ruff und **40 Inventur-/Bestandsregressionen** bestehen ebenfalls. Die bestehenden Geschaeftsregeln bleiben unveraendert.

AP04/AP08 Gutschrift-Feed: `sevdesk_credit_note_inventory.py` typisiert Provider-Payloads als JSON-Mappings und grenzt optionale Referenz-/Part-Objekte defensiv ein. Die bereits als ganzzahlig validierte Decimal-Menge wird fuer Booking und Mirror einmal in `int` normalisiert. Sieben strikte MyPy-Fehler beseitigt; acht Inventurdateien bestehen jetzt striktes MyPy, Ruff und **48 Inventur-/Invoice-/Credit-Feed-Regressionen** bestehen. Die separate nicht-strikte globale MyPy-Baseline liegt aktuell bei **367 Fehlern in 62 Dateien**; diese sieben dateilokalen Strict-Fehler waren darin nicht enthalten.

AP07-Fortschreibung auf `305d929`: Offene Produktpositionen zeigen jetzt den aus frueheren offenen Auftraegen bereits verplanten Bestand separat vom tatsaechlich verfuegbaren Lager. Die sequenzielle SKU-Planung weist verbleibende Mengen korrekt dem spaeteren Auftrag zu; der neue Regressionstest und zusammen **40 Inventur-/Druckplan-Tests** bestehen lokal.

AP06/AP08 Windows-Regression auf ba77a44 (Hosted Run 43026932649): Der Prozess endete mit einer Windows-Access-Violation waehrend warm_catalog() im Test test_rechnungen_applies_persistent_wix_cache_before_background_load; der Stack zeigte den erstmaligen Unreleased-Katalog-Read. Der Test prueft den persistenten Wix-Cache, nicht diesen unabhaengigen Katalog-Warmup. Er waermt den Katalog jetzt in der Testvorbereitung vor und wartet nach den Assertions auf den Abschluss des View-Shutdowns. Damit ist die Testisolation verbessert; ein Produktionsfehler oder dessen Ursache ist nicht belegt. Nach der Anpassung bestanden lokal der fokussierte Test und die vollstaendige Rechnungs-Smoke-Suite (89 Tests); die volle lokale Suite ergab **2.182 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung, 0 fehlgeschlagen (200,16 s)**. Ruff und git diff --check bestanden. Der Hosted-Run 43026066254 fuer c16925b bestaetigte die Worker-Abschlusswartezeit: Ruff erfolgreich, **2.182 bestanden, 5 uebersprungen, 1 bestehende fitz-Warnung (1.044,66 s)**.

Nach Fast-Forward auf 5bb2136 bestanden ausserdem die vollstaendige Rechnungs-UI-Smoke-Datei und der neue Inventurzaehldialog zusammen mit **90 Tests** (16,13 s); Ruff und Diff-Pruefung blieben gruen.

AP06/AP08 Katalog-Cache-Race: Der Windows-Run 43029061301 brach bei 12 Prozent erneut mit Access Violation ab, diesmal waehrend test_late_invoice_product_configuration_is_discarded_after_selection_change und parallel laufendem warm_catalog(). Commit 259016d fuehrt einen reentrant lock fuer Cache-Initialisierung und Invalidierung ein und ergaenzt einen Parallel-Warmup-Test. Die Rechnungs-Regression test_unreleased_catalog_disk_and_settings_read_runs_off_ui_thread deckte auf, dass auch der reine unreleased_products_loaded-Statusgetter nicht auf den Lock warten darf: dessen Ladepfad haelt den Lock waehrend Disk-/Settings-I/O und wuerde sonst den GUI-Thread blockieren. Der Getter liest jetzt die atomare Cache-Referenz ohne Lock; die Initialisierung selbst bleibt serialisiert. Katalog- plus Rechnungs-Smokes: **95 bestanden**; Ruff, striktes MyPy fuer catalog.py und git diff --check bestanden. Hosted Run 43030648930 fuer 259016d scheiterte am bestehenden Responsiveness-Test, weil der gelockte Statusgetter den UI-Thread waehrend des blockierten Reads anhielt. Der lockfreie Getter aus f6fbeff beseitigte den Blocker; Hosted Run 43031308110 ist vollstaendig erfolgreich: Ruff, **2.186 bestanden, 5 uebersprungen, 1 bestehende fitz-Warnung (726,75 s)**. Der weiche MyPy-Gate meldet weiterhin 359 Fehler in 63 Dateien.

Der finale Suite-Nachweis dieses Fortschreibungsschritts steht oben. Weitere Commit-/Push-Nachweise werden nach ihrer Integration ergänzt. Das folgende statische Inventar
wurde aus dem vorherigen Quellstand erzeugt und dient als Navigationshilfe; nach
spaeteren Codeaenderungen koennen einzelne Zeilennummern abweichen.

<!-- STATIC_INVENTORY -->

## Anhang A – Vollständiges statisches UI-Inventar

Automatisch aus dem finalen AST erfasst und für die oben beschriebenen Flows herangezogen. Fundstellen beziehen sich auf den Audit-Commit. Zeilen sind Navigationshilfen. Zählwerte sind **Deklarationsstellen**, keine Anzahl zur Laufzeit sichtbarer Instanzen. Signalverbindungen schließen Worker-, Tabellen-, Menü- und Timer-Signale ein. Qt-Standardbuttons, dynamische Schleifen und Delegate-Klickzonen sind über ihre Factory bzw. Eventmethoden erfasst.

| Datei | Zeilen | Methoden/Funktionen | Signalverbindungen | Worker-/Jobstellen | Timerstellen |
| --- | ---: | ---: | ---: | ---: | ---: |
| `__init__.py` | 1 | 0 | 0 | 0 | 0 |
| `buyer_note_review_dialog.py` | 220 | 9 | 7 | 0 | 0 |
| `customer_aftercare_invoice_dialog.py` | 239 | 21 | 12 | 3 | 1 |
| `customer_aftercare_manager_dialog.py` | 443 | 32 | 24 | 5 | 1 |
| `customer_aftercare_review_dialog.py` | 292 | 10 | 4 | 0 | 0 |
| `customer_aftercare_tab.py` | 550 | 22 | 14 | 2 | 0 |
| `digital_licenses_dialog.py` | 324 | 18 | 15 | 3 | 2 |
| `inventory_alerts_dialog.py` | 155 | 7 | 5 | 0 | 0 |
| `offene_drucke_dialog.py` | 233 | 14 | 15 | 3 | 1 |
| `offene_sendungen_dialog.py` | 955 | 66 | 22 | 3 | 4 |
| `offene_ueberweisungen_dialog.py` | 546 | 36 | 18 | 3 | 2 |
| `open_invoice_overview.py` | 818 | 29 | 0 | 1 | 0 |
| `payment_qr_dialog.py` | 81 | 4 | 4 | 0 | 0 |
| `plc_evidence_dialog.py` | 194 | 5 | 3 | 0 | 0 |
| `plc_label_dialog.py` | 2409 | 79 | 34 | 2 | 2 |
| `plc_statistics_dialog.py` | 162 | 8 | 5 | 1 | 0 |
| `print_dialog.py` | 729 | 43 | 12 | 0 | 0 |
| `product_preflight_dialog.py` | 206 | 9 | 2 | 0 | 0 |
| `redelivery_dialog.py` | 272 | 9 | 5 | 0 | 0 |
| `refund_dialog.py` | 70 | 2 | 2 | 0 | 0 |
| `refunds_dialog.py` | 157 | 6 | 4 | 0 | 0 |
| `reprint_dialog.py` | 121 | 2 | 2 | 0 | 0 |
| `special_order_dialog.py` | 371 | 22 | 13 | 2 | 1 |
| `tagesgeschaeft_view.py` | 1757 | 82 | 55 | 11 | 2 |
| `view.py` | 7903 | 395 | 136 | 30 | 13 |

### A – __init__.py

Quelle: `src/xw_office/ui/modules/rechnungen/__init__.py`.

Keine direkten UI-/Signal-/Timer-/Worker-Einstiege in dieser Datei.

### A – buyer_note_review_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/buyer_note_review_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.services.invoice_processing.buyer_notes`.

**BuyerNoteReviewDialog** (Z. 31): `__init__`:34; `_build_ui`:56; `_item_label`:125; `_case`:129; `_save_editor_values`:134; `_show_case`:147; `_choose`:180; `_accept_if_complete`:203; `selections`:215.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 66 | UI / Aktion | `QListWidget()` |
| 68 | Signal → Handler | `self._case_list.currentRowChanged.connect(self._show_case)` |
| 78 | UI / Aktion | `QPlainTextEdit()` |
| 85 | UI / Aktion | `QPlainTextEdit()` |
| 94 | UI / Aktion | `QPlainTextEdit()` |
| 100 | UI / Aktion | `QPushButton('Gelesen – ohne Lieferschein')` |
| 101 | Signal → Handler | `self._ack.clicked.connect(lambda: self._choose(BUYER_NOTE_ACK))` |
| 103 | UI / Aktion | `QPushButton('Lieferschein vormerken')` |
| 104 | Signal → Handler | `self._delivery.clicked.connect(lambda: self._choose(BUYER_NOTE_DELIVERY_NOTE))` |
| 106 | UI / Aktion | `QPushButton('Digital bestätigt')` |
| 107 | Signal → Handler | `self._digital.clicked.connect(lambda: self._choose(BUYER_NOTE_DIGITAL_ACK))` |
| 109 | UI / Aktion | `QPushButton('Diesen Datensatz überspringen')` |
| 110 | Signal → Handler | `self._skip.clicked.connect(lambda: self._choose(BUYER_NOTE_SKIP))` |
| 116 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)` |
| 119 | UI / Aktion | `buttons.addButton('START fortsetzen', QDialogButtonBox.ButtonRole.AcceptRole)` |
| 120 | Signal → Handler | `buttons.accepted.connect(self._accept_if_complete)` |
| 121 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 186 | Popup / Modal | `QMessageBox.warning(self, 'Lieferadresse fehlt', 'Für den Lieferschein muss eine Lieferadresse vorhanden sein.')` |
| 207 | Popup / Modal | `QMessageBox.warning(self, 'Prüfung unvollständig', f'Bitte noch {len(missing)} Käufernotiz(en) bestätigen oder überspringen.')` |

### A – customer_aftercare_invoice_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/customer_aftercare_invoice_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.services.crm.types`, `xw_office.services.customer_aftercare.invoice_service`, `xw_office.services.customer_aftercare.pricing_policy`, `xw_office.services.customer_aftercare.service`, `xw_office.services.sevdesk.contact_client`.

**CustomerAftercareInvoiceDialog** (Z. 50): `__init__`:53; `closeEvent`:76; `accept`:80; `reject`:84; `_wait_for_workers`:88; `_build_ui`:93; `_load_contacts`:138; `_populate_contacts`:161; `_selected_contact_id`:173; `_on_create_clicked`:176; `_on_skip_clicked`:213; `_set_buttons_enabled`:236.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 74 | Timer | `QTimer.singleShot(0, self._load_contacts)` |
| 107 | UI / Aktion | `QPlainTextEdit('\n'.join(lines))` |
| 112 | UI / Aktion | `QComboBox()` |
| 116 | UI / Aktion | `QLineEdit('AT')` |
| 126 | UI / Aktion | `QDialogButtonBox()` |
| 127 | UI / Aktion | `QPushButton('Zusatzrechnung erstellen')` |
| 128 | UI / Aktion | `QPushButton('Ohne Rechnung erledigen')` |
| 129 | UI / Aktion | `QPushButton('Später')` |
| 130 | UI / Aktion | `buttons.addButton(self._btn_create, QDialogButtonBox.ButtonRole.AcceptRole)` |
| 131 | UI / Aktion | `buttons.addButton(self._btn_skip, QDialogButtonBox.ButtonRole.ActionRole)` |
| 132 | UI / Aktion | `buttons.addButton(self._btn_later, QDialogButtonBox.ButtonRole.RejectRole)` |
| 133 | Signal → Handler | `self._btn_create.clicked.connect(self._on_create_clicked)` |
| 134 | Signal → Handler | `self._btn_skip.clicked.connect(self._on_skip_clicked)` |
| 135 | Signal → Handler | `self._btn_later.clicked.connect(self.reject)` |
| 154 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 155 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 156 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 157 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_contacts_worker', None))` |
| 179 | Popup / Modal | `QMessageBox.warning(self, 'Zusatzrechnung', 'Bitte einen sevDesk-Kontakt auswählen.')` |
| 183 | Popup / Modal | `QMessageBox.warning(self, 'Zusatzrechnung', 'Bitte ein gültiges 2-stelliges Länderkürzel angeben.')` |
| 206 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 207 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 208 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 209 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_action_worker', None))` |
| 229 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 230 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 231 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 232 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_action_worker', None))` |

### A – customer_aftercare_manager_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/customer_aftercare_manager_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.repositories.customer_aftercare`, `xw_office.services.customer_aftercare`, `xw_office.services.customer_aftercare.service`, `xw_office.services.sendungen.service`, `xw_office.ui.modules.rechnungen.customer_aftercare_invoice_dialog`, `xw_office.ui.modules.rechnungen.customer_aftercare_review_dialog`, `xw_office.ui.modules.rechnungen.offene_sendungen_dialog`, `xw_office.ui.modules.rechnungen.redelivery_dialog`.

**CustomerAftercareManagerDialog** (Z. 56): `__init__`:59; `closeEvent`:83; `accept`:87; `reject`:92; `_bump_seq`:97; `_wait_for_workers`:101; `open_count`:106; `_build_ui`:109; `_current_filter`:199; `_load_cases`:202; `_populate_list`:232; `_on_case_selected`:249; `_load_items`:268; `_open_review_dialog`:289; `_open_invoice_dialog`:302; `_prepare_nachsendung`:311; `_apply_outcome`:397; `_mark_resolved`:416; `_mark_cancelled`:422; `_run_action`:428.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 81 | Timer | `QTimer.singleShot(0, self._load_cases)` |
| 118 | UI / Aktion | `QComboBox()` |
| 121 | Signal → Handler | `self._filter_combo.currentIndexChanged.connect(lambda _index: self._load_cases())` |
| 125 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 126 | Signal → Handler | `self._btn_refresh.clicked.connect(self._load_cases)` |
| 134 | UI / Aktion | `QListWidget()` |
| 135 | Signal → Handler | `self._list.currentRowChanged.connect(self._on_case_selected)` |
| 157 | UI / Aktion | `QPlainTextEdit()` |
| 164 | UI / Aktion | `QPlainTextEdit()` |
| 171 | UI / Aktion | `QPushButton('Prüfen / Bestätigen…')` |
| 172 | Signal → Handler | `self._btn_review.clicked.connect(self._open_review_dialog)` |
| 174 | UI / Aktion | `QPushButton('Zusatzrechnung…')` |
| 175 | Signal → Handler | `self._btn_invoice.clicked.connect(self._open_invoice_dialog)` |
| 177 | UI / Aktion | `QPushButton('Nachsendung vorbereiten…')` |
| 178 | Signal → Handler | `self._btn_nachsendung.clicked.connect(self._prepare_nachsendung)` |
| 180 | UI / Aktion | `QPushButton('Als erledigt markieren')` |
| 181 | Signal → Handler | `self._btn_resolve.clicked.connect(self._mark_resolved)` |
| 183 | UI / Aktion | `QPushButton('Stornieren')` |
| 184 | Signal → Handler | `self._btn_cancel.clicked.connect(self._mark_cancelled)` |
| 194 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 195 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 196 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 225 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 226 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 227 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 228 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_load_worker', None))` |
| 283 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 284 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 285 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_detail_worker', None))` |
| 296 | Popup / Modal | `dialog.exec()` |
| 307 | Popup / Modal | `dialog.exec()` |
| 344 | Popup / Modal | `dlg.exec()` |
| 346 | Hintergrundarbeit | `BackgroundWorker(legacy_job)` |
| 347 | Signal → Handler | `worker.signals.result.connect(legacy_result)` |
| 348 | Signal → Handler | `worker.signals.error.connect(lambda exc: self._status.setText(f'Nachsendung konnte nicht vorbereitet werden: {exc}'))` |
| 349 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_action_worker', None))` |
| 366 | Popup / Modal | `dialog.exec()` |
| 390 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 391 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 392 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 393 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_action_worker', None))` |
| 438 | Hintergrundarbeit | `BackgroundWorker(fn)` |
| 439 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 440 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 441 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_action_worker', None))` |

### A – customer_aftercare_review_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/customer_aftercare_review_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.config`, `xw_office.repositories.customer_aftercare`, `xw_office.services.customer_aftercare.service`.

**ReviewDialogOutcome** (Z. 66): Datenmodell / Konstanten.
**CustomerAftercareReviewDialog** (Z. 74): `__init__`:77; `outcome`:94; `_build_ui`:97; `_format_items`:196; `_error_party_label`:205; `_refresh_trigger_preview`:213; `_current_outcome`:231; `_on_apply`:274; `_on_defer`:286; `_on_ignore`:290.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 107 | UI / Aktion | `QComboBox()` |
| 115 | Signal → Handler | `self._type_combo.currentIndexChanged.connect(self._refresh_trigger_preview)` |
| 122 | UI / Aktion | `QCheckBox('Kulanz anwenden')` |
| 136 | UI / Aktion | `QPlainTextEdit()` |
| 144 | UI / Aktion | `QTableWidget(0, 4)` |
| 145 | UI / Aktion | `self._items_table.setHorizontalHeaderLabels(['', 'Position', 'SKU / Komponente', 'Menge'])` |
| 174 | UI / Aktion | `QPlainTextEdit()` |
| 181 | UI / Aktion | `QDialogButtonBox()` |
| 182 | UI / Aktion | `QPushButton('Übernehmen')` |
| 183 | UI / Aktion | `QPushButton('Bearbeiten')` |
| 184 | UI / Aktion | `QPushButton('Ignorieren')` |
| 185 | UI / Aktion | `button_row.addButton(self._btn_apply, QDialogButtonBox.ButtonRole.AcceptRole)` |
| 186 | UI / Aktion | `button_row.addButton(self._btn_edit, QDialogButtonBox.ButtonRole.ActionRole)` |
| 187 | UI / Aktion | `button_row.addButton(self._btn_ignore, QDialogButtonBox.ButtonRole.DestructiveRole)` |
| 188 | Signal → Handler | `self._btn_apply.clicked.connect(self._on_apply)` |
| 189 | Signal → Handler | `self._btn_edit.clicked.connect(self._on_defer)` |
| 190 | Signal → Handler | `self._btn_ignore.clicked.connect(self._on_ignore)` |
| 277 | Popup / Modal | `QMessageBox.warning(self, 'Nachlieferposition fehlt', 'Bitte mindestens eine Rechnungsposition oder Stimme auswählen.')` |

### A – customer_aftercare_tab.py

Quelle: `src/xw_office/ui/modules/rechnungen/customer_aftercare_tab.py`.

Direkte interne Abhängigkeiten: `xw_office.core.worker`, `xw_office.repositories.customer_aftercare`, `xw_office.services.customer_aftercare.service`, `xw_office.services.printing.label_printer`, `xw_office.services.printing.print_queue`, `xw_office.services.sendungen.service`, `xw_office.services.sevdesk.invoice_client`, `xw_office.ui.modules.rechnungen.redelivery_dialog`.

**CustomerAftercareTab** (Z. 51): `__init__`:54; `_build_ui`:65; `refresh`:142; `_current`:168; `_select`:172; `_update_dispatch_actions`:229; `_dispatch_print_request`:270; `_run_dispatch_action`:323; `_show_delivery_note`:357; `_print_delivery_note`:372; `_print_label`:399; `_edit`:426; `_snooze`:459; `_show_invoice`:501; `_immediate`:534; `_resolve`:540; `_cancel`:546.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 70 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 71 | Signal → Handler | `refresh.clicked.connect(self.refresh)` |
| 76 | UI / Aktion | `QListWidget()` |
| 77 | Signal → Handler | `self._list.currentRowChanged.connect(self._select)` |
| 87 | UI / Aktion | `QPlainTextEdit()` |
| 92 | UI / Aktion | `QPlainTextEdit()` |
| 106 | UI / Aktion | `QPushButton(label)` |
| 107 | Signal → Handler | `button.clicked.connect(callback)` |
| 113 | UI / Aktion | `QPushButton('Lieferschein zeigen')` |
| 117 | Signal → Handler | `self._btn_delivery_show.clicked.connect(self._show_delivery_note)` |
| 119 | UI / Aktion | `QPushButton('Lieferschein drucken')` |
| 123 | Signal → Handler | `self._btn_delivery_print.clicked.connect(self._print_delivery_note)` |
| 125 | UI / Aktion | `QPushButton('Label drucken')` |
| 127 | Signal → Handler | `self._btn_label_print.clicked.connect(self._print_label)` |
| 130 | UI / Aktion | `QPushButton('Erledigt')` |
| 131 | Signal → Handler | `self._btn_resolve.clicked.connect(self._resolve)` |
| 133 | UI / Aktion | `QPushButton('Stornieren')` |
| 134 | Signal → Handler | `self._btn_cancel.clicked.connect(self._cancel)` |
| 282 | Popup / Modal | `QMessageBox.information(self, 'Nachlieferung drucken', 'Bitte die Nachlieferung zuerst aktivieren (Sofort versenden oder Fälligkeit).')` |
| 298 | Popup / Modal | `QMessageBox.information(self, 'Nachlieferung drucken', 'Keine zustellfähige Lieferadresse vorhanden.')` |
| 315 | Popup / Modal | `QMessageBox.information(self, 'Nachlieferung drucken', 'Bitte in „Bearbeiten…“ mindestens eine nachzuliefernde Position auswählen.')` |
| 340 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 341 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 342 | Signal → Handler | `worker.signals.error.connect(lambda exc: QMessageBox.warning(self, 'Nachlieferung drucken', f'Druck konnte nicht vorbereitet werden:\n\n{exc}'))` |
| 343 | Popup / Modal | `QMessageBox.warning(self, 'Nachlieferung drucken', f'Druck konnte nicht vorbereitet werden:\n\n{exc}')` |
| 353 | Signal → Handler | `worker.signals.finished.connect(finished)` |
| 394 | Popup / Modal | `QMessageBox.information(self, 'Lieferschein', 'Lieferschein erfolgreich an Rechnungen gesendet.')` |
| 421 | Popup / Modal | `QMessageBox.information(self, 'Label', 'Label erfolgreich an Drucker gesendet.')` |
| 441 | Popup / Modal | `dialog.exec()` |
| 468 | Popup / Modal | `QInputDialog.getItem(self, 'Nachlieferung snoozen', 'Snooze:', labels, 0, False)` |
| 482 | Popup / Modal | `QInputDialog.getText(self, 'Snooze bis', 'Datum/Uhrzeit (TT.MM.JJJJ HH:MM):', text=default)` |
| 493 | Popup / Modal | `QMessageBox.warning(self, 'Snooze', 'Bitte Datum als TT.MM.JJJJ HH:MM eingeben.')` |
| 495 | Popup / Modal | `QInputDialog.getText(self, 'Snooze-Grund', 'Grund (optional):')` |
| 504 | Popup / Modal | `QMessageBox.information(self, 'Originalrechnung', 'Keine sevDesk-Rechnung verknüpft.')` |
| 523 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 524 | Signal → Handler | `worker.signals.result.connect(done)` |
| 525 | Signal → Handler | `worker.signals.error.connect(lambda exc: QMessageBox.warning(self, 'Originalrechnung', f'Rechnung konnte nicht geladen werden:\n\n{exc}'))` |
| 526 | Popup / Modal | `QMessageBox.warning(self, 'Originalrechnung', f'Rechnung konnte nicht geladen werden:\n\n{exc}')` |
| 530 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_invoice_worker', None))` |

### A – digital_licenses_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/digital_licenses_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.services.digital_licenses`.

**DigitalLicensesDialog** (Z. 30): `__init__`:33; `_build_ui`:47; `open_count`:98; `_load_cases`:103; `_on_cases_loaded`:113; `_selected_case`:127; `_show_selected_case`:133; `_pick_missing_pdf`:161; `_prepare_selected`:180; `_on_files_prepared`:206; `_start_draft_job`:234; `_on_draft_worker_finished`:250; `_on_draft_created`:259; `_mark_selected_done`:268; `_on_mark_done_finished`:294; `_run_action`:304; `_on_error`:322.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 45 | Timer | `QTimer.singleShot(0, self._load_cases)` |
| 55 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 56 | Signal → Handler | `self._btn_refresh.clicked.connect(self._load_cases)` |
| 63 | UI / Aktion | `QListWidget()` |
| 64 | Signal → Handler | `self._list.currentRowChanged.connect(self._show_selected_case)` |
| 73 | UI / Aktion | `QPlainTextEdit()` |
| 78 | UI / Aktion | `QPushButton('Fehlende Druck-PDF zuordnen')` |
| 79 | Signal → Handler | `self._btn_pick_missing.clicked.connect(self._pick_missing_pdf)` |
| 81 | UI / Aktion | `QPushButton('PDFs erstellen und pruefen')` |
| 82 | Signal → Handler | `self._btn_prepare.clicked.connect(self._prepare_selected)` |
| 85 | UI / Aktion | `QPushButton('E-Mail wurde gesendet – abschliessen')` |
| 86 | Signal → Handler | `self._btn_done.clicked.connect(self._mark_selected_done)` |
| 94 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 95 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 107 | Hintergrundarbeit | `BackgroundWorker(self._service.list_open_cases)` |
| 108 | Signal → Handler | `self._load_worker.signals.result.connect(self._on_cases_loaded)` |
| 109 | Signal → Handler | `self._load_worker.signals.error.connect(self._on_error)` |
| 110 | Signal → Handler | `self._load_worker.signals.finished.connect(lambda: setattr(self, '_load_worker', None))` |
| 167 | Popup / Modal | `QMessageBox.information(self, 'Druck-PDF', 'Alle Produkte haben bereits einen gueltigen Druckpfad.')` |
| 169 | Popup / Modal | `QFileDialog.getOpenFileName(self, 'Druck-PDF zuordnen', '', 'PDF (*.pdf)')` |
| 173 | Popup / Modal | `QMessageBox.warning(self, 'Druck-PDF', 'Die Datei wurde nicht gefunden.')` |
| 196 | Popup / Modal | `QMessageBox.warning(self, 'Externe Bestellung', 'Bitte zuerst alle fehlenden Druck-PDFs zuordnen.')` |
| 219 | Popup / Modal | `QMessageBox.question(self, 'PDF-Kontrolle', 'Die personalisierten PDFs wurden geoeffnet. Sind Name, Seiten und Vollstaendigkeit korrekt?', QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)` |
| 243 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 244 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 245 | Signal → Handler | `worker.signals.error.connect(self._on_error)` |
| 246 | Signal → Handler | `worker.signals.finished.connect(lambda: self._on_draft_worker_finished(worker))` |
| 262 | Popup / Modal | `QMessageBox.information(self, 'Outlook-Entwurf', 'Der Entwurf wurde gespeichert und geoeffnet. Sende ihn in Outlook und bestaetige danach hier den Versand.')` |
| 275 | Popup / Modal | `QMessageBox.warning(self, 'Externe Bestellung', 'Bitte zuerst die PDFs kontrollieren und den Outlook-Entwurf speichern.')` |
| 281 | Popup / Modal | `QMessageBox.question(self, 'Externe Bestellung', 'Hast du die E-Mail mit Rechnung und allen Noten-PDFs gesendet?\n\nDanach wird Wix-Fulfillment abgeschlossen.')` |
| 300 | Timer | `QTimer.singleShot(0, self.accept)` |
| 315 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 317 | Signal → Handler | `self._action_worker.signals.result.connect(result_handler)` |
| 318 | Signal → Handler | `self._action_worker.signals.error.connect(self._on_error)` |
| 319 | Signal → Handler | `self._action_worker.signals.finished.connect(lambda: setattr(self, '_action_worker', None))` |
| 324 | Popup / Modal | `QMessageBox.warning(self, 'Externe Bestellung', str(exc))` |

### A – inventory_alerts_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/inventory_alerts_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.services.mailing.service`, `xw_office.services.product_hub.inventory`, `xw_office.services.product_hub.inventory_alert_tasks`.

**InventoryAlertsDialog** (Z. 23): `__init__`:24; `refresh`:69; `_select`:86; `_current`:97; `_save_threshold`:101; `_use_automatic`:116; `_create_task`:132.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 34 | UI / Aktion | `QListWidget()` |
| 35 | Signal → Handler | `self._list.currentRowChanged.connect(self._select)` |
| 41 | UI / Aktion | `QSpinBox()` |
| 53 | UI / Aktion | `QPushButton('Alarmbestand speichern')` |
| 54 | Signal → Handler | `self._save.clicked.connect(self._save_threshold)` |
| 55 | UI / Aktion | `QPushButton('Automatik verwenden')` |
| 56 | Signal → Handler | `self._auto.clicked.connect(self._use_automatic)` |
| 57 | UI / Aktion | `QPushButton('Task erzeugen')` |
| 58 | Signal → Handler | `self._task.clicked.connect(self._create_task)` |
| 59 | UI / Aktion | `QPushButton('Schließen')` |
| 60 | Signal → Handler | `close.clicked.connect(self.accept)` |
| 114 | Popup / Modal | `QMessageBox.warning(self, 'Alarmbestand', str(exc))` |
| 130 | Popup / Modal | `QMessageBox.warning(self, 'Alarmbestand', str(exc))` |
| 139 | Popup / Modal | `QMessageBox.information(self, 'Task erzeugen', 'Task-Mail wurde an todo@xeisworks.at gesendet.')` |
| 141 | Popup / Modal | `QMessageBox.information(self, 'Task erzeugen', 'Die Task-Mail wird bereits versendet.')` |
| 143 | Popup / Modal | `QMessageBox.warning(self, 'Task erzeugen', 'Der Versandstatus ist unklar. Bitte zuerst den Mailversand prüfen. Es wird keine weitere Mail automatisch versendet.')` |
| 150 | Popup / Modal | `QMessageBox.warning(self, 'Task erzeugen', result.error or 'Task-Mail konnte nicht gesendet werden.')` |
| 152 | Popup / Modal | `QMessageBox.warning(self, 'Task erzeugen', str(exc))` |

### A – offene_drucke_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/offene_drucke_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.services.drucke.service`.

**OffeneDruckeDialog** (Z. 28): `__init__`:29; `_load`:82; `_loaded`:97; `_load_error`:113; `_clear_detail`:119; `_current_case`:126; `_select`:130; `_on_attachment_finished`:159; `_attachments_loaded`:170; `_open_attachment`:183; `_open_local_file`:208; `_mark_done`:221; `open_count`:228; `_format_size`:232.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 42 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 43 | Signal → Handler | `self._refresh.clicked.connect(lambda: self._load(True))` |
| 48 | UI / Aktion | `QListWidget()` |
| 49 | Signal → Handler | `self._list.currentRowChanged.connect(self._select)` |
| 53 | UI / Aktion | `QTextEdit()` |
| 57 | UI / Aktion | `QListWidget()` |
| 58 | Signal → Handler | `self._attachment_list.itemDoubleClicked.connect(lambda _item: self._open_attachment())` |
| 61 | UI / Aktion | `QPushButton('Anhang öffnen')` |
| 62 | Signal → Handler | `self._open_attachment_button.clicked.connect(self._open_attachment)` |
| 70 | UI / Aktion | `QPushButton('Als erledigt markieren')` |
| 71 | Signal → Handler | `self._done.clicked.connect(self._mark_done)` |
| 73 | UI / Aktion | `QPushButton('Schließen')` |
| 74 | Signal → Handler | `close.clicked.connect(self.accept)` |
| 80 | Timer | `QTimer.singleShot(0, lambda: self._load(True))` |
| 87 | Hintergrundarbeit | `BackgroundWorker(lambda: self._service.refresh_from_graph() if refresh else self._service.load_open_cases())` |
| 92 | Signal → Handler | `self._worker.signals.result.connect(self._loaded)` |
| 93 | Signal → Handler | `self._worker.signals.error.connect(self._load_error)` |
| 94 | Signal → Handler | `self._worker.signals.finished.connect(lambda: self._refresh.setEnabled(True))` |
| 115 | Popup / Modal | `QMessageBox.warning(self, 'OPEN PRINTS', f'Druckaufträge konnten nicht geladen werden:\n\n{exc}')` |
| 144 | Hintergrundarbeit | `BackgroundWorker(lambda: self._service.list_attachments(case.id))` |
| 146 | Signal → Handler | `worker.signals.result.connect(lambda result: self._attachments_loaded(result) if seq == self._attachment_seq else None)` |
| 149 | Signal → Handler | `worker.signals.error.connect(lambda exc: self._status.setText(f'Anhänge konnten nicht geladen werden: {exc}') if seq == self._attachment_seq else None)` |
| 156 | Signal → Handler | `worker.signals.finished.connect(lambda: self._on_attachment_finished(worker, seq))` |
| 195 | Hintergrundarbeit | `BackgroundWorker(lambda: self._service.download_attachment_to_cache(case.id, attachment.id, attachment.name))` |
| 201 | Signal → Handler | `worker.signals.result.connect(self._open_local_file)` |
| 202 | Signal → Handler | `worker.signals.error.connect(lambda exc: QMessageBox.warning(self, 'Anhang öffnen', str(exc)))` |
| 203 | Popup / Modal | `QMessageBox.warning(self, 'Anhang öffnen', str(exc))` |
| 205 | Signal → Handler | `worker.signals.finished.connect(lambda: self._on_attachment_finished(worker, seq))` |
| 215 | Popup / Modal | `QMessageBox.warning(self, 'Anhang öffnen', 'Die Datei konnte nicht mit dem Windows-Standardprogramm geöffnet werden.')` |

### A – offene_sendungen_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/offene_sendungen_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.services.printing.label_printer`, `xw_office.services.printing.print_queue`, `xw_office.services.sendungen.service`, `xw_office.ui.modules.rechnungen.customer_aftercare_tab`.

**_SendungProductsModel** (Z. 47): `__init__`:50; `rowCount`:54; `columnCount`:57; `data`:60; `setData`:74; `flags`:107; `headerData`:117; `set_products`:122; `add_product`:127; `remove_row`:133; `products`:140.
**_ContentSizedPlainTextEdit** (Z. 144): `__init__`:145; `resizeEvent`:156; `_schedule_resize`:160; `_resize_to_contents`:164.
**OffeneSendungenDialog** (Z. 170): `__init__`:173; `closeEvent`:197; `accept`:201; `reject`:207; `_wait_for_workers`:213; `_build_ui`:219; `open_count`:388; `_load_cases`:391; `_on_cases_loaded`:441; `_schedule_silent_refresh_after_detail`:488; `_case_list_text`:495; `_on_cases_load_error`:513; `_current_case`:519; `_on_case_selected`:525; `_extract_selected`:539; `_invalidate_detail_load`:561; `_on_detail_worker_finished`:568; `_on_detail_loaded`:576; `_set_case_metadata`:629; `_on_detail_error`:652; `_set_detail_loading`:662; `_clear_detail`:670; `_compact_thread_text`:681; `_set_actions_enabled`:686; `_set_products`:698; `_add_product_row`:703; `_remove_selected_product_row`:706; `_address_lines`:710; `_products_from_table`:713; `_manual_bool`:717; `_validated_products`:724; `_cell_text`:764; `_print_label`:769; `_on_label_printed`:802; `_show_delivery_note`:805; `_on_delivery_note_ready`:827; `_print_delivery_note`:830; `_on_delivery_note_printed`:857; `_delivery_note_request`:862; `_mark_done`:879; `_on_mark_done_finished`:905; `_start_action`:917; `_finish_action`:949.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 150 | Timer | `QTimer(self)` |
| 151 | Timer | `self._resize_timer.setSingleShot(True)` |
| 152 | Signal → Handler | `self._resize_timer.timeout.connect(self._resize_to_contents)` |
| 153 | Signal → Handler | `self.textChanged.connect(self._schedule_resize)` |
| 154 | Signal → Handler | `self.document().documentLayout().documentSizeChanged.connect(self._schedule_resize)` |
| 188 | Timer | `QTimer(self)` |
| 189 | Timer | `self._silent_refresh_timer.setSingleShot(True)` |
| 190 | Signal → Handler | `self._silent_refresh_timer.timeout.connect(lambda: self._load_cases(refresh=True, preserve=True, silent=True))` |
| 195 | Timer | `QTimer.singleShot(0, lambda: self._load_cases(refresh=False))` |
| 225 | UI / Aktion | `QTabWidget()` |
| 231 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 232 | Signal → Handler | `self._btn_refresh.clicked.connect(lambda: self._load_cases(refresh=True, preserve=True))` |
| 236 | UI / Aktion | `QPushButton('OpenAI neu extrahieren')` |
| 237 | Signal → Handler | `self._btn_extract.clicked.connect(lambda: self._extract_selected(force=True))` |
| 245 | UI / Aktion | `QListWidget()` |
| 246 | Signal → Handler | `self._list.currentRowChanged.connect(self._on_case_selected)` |
| 296 | UI / Aktion | `QTableView()` |
| 305 | UI / Aktion | `QPushButton('+ Produkt')` |
| 306 | Signal → Handler | `self._btn_add_product.clicked.connect(lambda: self._add_product_row(SendungProductLine()))` |
| 310 | UI / Aktion | `QPushButton('− Produkt')` |
| 311 | Signal → Handler | `self._btn_remove_product.clicked.connect(self._remove_selected_product_row)` |
| 317 | UI / Aktion | `QPlainTextEdit()` |
| 324 | UI / Aktion | `QPushButton('Lieferschein zeigen')` |
| 325 | Signal → Handler | `self._btn_delivery_show.clicked.connect(self._show_delivery_note)` |
| 327 | UI / Aktion | `QPushButton('Lieferschein drucken')` |
| 328 | Signal → Handler | `self._btn_delivery_print.clicked.connect(self._print_delivery_note)` |
| 339 | UI / Aktion | `QPlainTextEdit()` |
| 344 | UI / Aktion | `QPushButton('Label drucken')` |
| 345 | Signal → Handler | `self._btn_label.clicked.connect(self._print_label)` |
| 357 | UI / Aktion | `QPushButton('✓')` |
| 367 | Signal → Handler | `self._btn_done.clicked.connect(self._mark_done)` |
| 376 | UI / Aktion | `tabs.addTab(sendungen_tab, 'OFFENE SENDUNGEN')` |
| 385 | UI / Aktion | `tabs.addTab(aftercare_tab, 'NACHLIEFERUNGEN')` |
| 431 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 432 | Signal → Handler | `self._load_worker.signals.result.connect(lambda result, token=seq, keep=preserve, cid=selected_id: self._on_cases_loaded(token, result, preserve=keep, selected_id=cid))` |
| 437 | Signal → Handler | `self._load_worker.signals.error.connect(self._on_cases_load_error)` |
| 438 | Signal → Handler | `self._load_worker.signals.finished.connect(lambda: setattr(self, '_load_worker', None))` |
| 517 | Popup / Modal | `QMessageBox.warning(self, 'OFFENE SENDUNGEN', f'Laden fehlgeschlagen:\n\n{exc}')` |
| 553 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 556 | Signal → Handler | `worker.signals.result.connect(lambda result, token=seq: self._on_detail_loaded(token, result))` |
| 557 | Signal → Handler | `worker.signals.error.connect(lambda exc, token=seq: self._on_detail_error(token, exc))` |
| 558 | Signal → Handler | `worker.signals.finished.connect(lambda w=worker: self._on_detail_worker_finished(w))` |
| 660 | Popup / Modal | `QMessageBox.warning(self, 'OFFENE SENDUNGEN', f'Details konnten nicht geladen werden:\n\n{exc}')` |
| 735 | Popup / Modal | `QMessageBox.information(self, 'Lieferpreis fehlt', f'Bitte in Produktzeile {row} einen Lieferpreis eingeben (Standard: € 5,90).')` |
| 767 | Popup / Modal | `QMessageBox.information(self, 'Label', 'Keine Adresszeilen vorhanden.')` |
| 795 | Popup / Modal | `QMessageBox.information(self, 'Label', 'Label erfolgreich an Drucker gesendet.')` |
| 863 | Popup / Modal | `QMessageBox.information(self, 'Lieferschein', 'Lieferschein erfolgreich an Rechnungen gesendet.')` |
| 916 | Timer | `QTimer.singleShot(0, self.accept)` |
| 933 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 935 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 936 | Signal → Handler | `worker.signals.error.connect(lambda exc: QMessageBox.warning(self, 'Aktion fehlgeschlagen', str(exc)))` |
| 937 | Popup / Modal | `QMessageBox.warning(self, 'Aktion fehlgeschlagen', str(exc))` |
| 939 | Signal → Handler | `worker.signals.finished.connect(lambda current=worker, target=button, text=idle_text: self._finish_action(current, target, text))` |

### A – offene_ueberweisungen_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/offene_ueberweisungen_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.services.transfers.models`, `xw_office.services.transfers.payment_qr`, `xw_office.services.transfers.service`, `xw_office.ui.modules.rechnungen.payment_qr_dialog`.

**OffeneUeberweisungenDialog** (Z. 37): `__init__`:40; `closeEvent`:55; `accept`:59; `reject`:65; `_wait_for_workers`:71; `_build_ui`:77; `open_count`:181; `_load_cases`:184; `_on_cases_loaded`:206; `_on_cases_load_error`:227; `_clear_detail`:233; `_set_payment_loading`:247; `_set_payment_actions_enabled`:261; `_current_case`:266; `_on_case_selected`:272; `_on_detail_worker_finished`:309; `_on_case_detail_loaded`:317; `_on_case_detail_error`:330; `_fill_payment_form`:340; `_collect_payment_form`:355; `_summarize_selected`:392; `_show_invoice`:408; `_generate_qr`:431; `_on_qr_generated`:444; `_defer`:452; `_mark_done`:471; `_start_action`:506; `_detail_status_for_action`:530; `_on_action_error`:533; `_finish_action`:537.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 53 | Timer | `QTimer.singleShot(0, lambda: self._load_cases(refresh=True))` |
| 87 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 88 | Signal → Handler | `self._btn_refresh.clicked.connect(lambda: self._load_cases(refresh=True))` |
| 96 | UI / Aktion | `QListWidget()` |
| 97 | Signal → Handler | `self._list.currentRowChanged.connect(self._on_case_selected)` |
| 108 | UI / Aktion | `QPlainTextEdit()` |
| 114 | UI / Aktion | `QPlainTextEdit()` |
| 121 | UI / Aktion | `QLineEdit()` |
| 122 | UI / Aktion | `QLineEdit()` |
| 123 | UI / Aktion | `QLineEdit()` |
| 124 | UI / Aktion | `QLineEdit()` |
| 125 | UI / Aktion | `QLineEdit('EUR')` |
| 127 | UI / Aktion | `QLineEdit()` |
| 128 | UI / Aktion | `QLineEdit()` |
| 129 | UI / Aktion | `QLineEdit()` |
| 130 | UI / Aktion | `QLineEdit()` |
| 147 | UI / Aktion | `QPushButton('Mit OpenAI zusammenfassen')` |
| 148 | Signal → Handler | `self._btn_summary.clicked.connect(self._summarize_selected)` |
| 154 | UI / Aktion | `QPushButton('Rechnung zeigen')` |
| 155 | Signal → Handler | `self._btn_show_invoice.clicked.connect(self._show_invoice)` |
| 158 | UI / Aktion | `QPushButton('QR-Code generieren')` |
| 159 | Signal → Handler | `self._btn_generate_qr.clicked.connect(self._generate_qr)` |
| 162 | UI / Aktion | `QPushButton('Spaeter - Alarm bleibt')` |
| 163 | Signal → Handler | `self._btn_defer.clicked.connect(self._defer)` |
| 166 | UI / Aktion | `QPushButton('Ueberweisung durchgefuehrt')` |
| 167 | Signal → Handler | `self._btn_done.clicked.connect(self._mark_done)` |
| 176 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 177 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 178 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 200 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 201 | Signal → Handler | `self._load_worker.signals.result.connect(lambda result, token=seq: self._on_cases_loaded(token, result))` |
| 202 | Signal → Handler | `self._load_worker.signals.error.connect(self._on_cases_load_error)` |
| 203 | Signal → Handler | `self._load_worker.signals.finished.connect(lambda: setattr(self, '_load_worker', None))` |
| 231 | Popup / Modal | `QMessageBox.warning(self, 'OFFENE UEBERWEISUNGEN', f'Laden fehlgeschlagen:\n\n{exc}')` |
| 301 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 304 | Signal → Handler | `worker.signals.result.connect(lambda result, token=seq: self._on_case_detail_loaded(token, result))` |
| 305 | Signal → Handler | `worker.signals.error.connect(lambda exc, token=seq: self._on_case_detail_error(token, exc))` |
| 306 | Signal → Handler | `worker.signals.finished.connect(lambda w=worker: self._on_detail_worker_finished(w))` |
| 338 | Popup / Modal | `QMessageBox.warning(self, 'OFFENE UEBERWEISUNGEN', f'Zahlungsdaten konnten nicht geladen werden:\n\n{exc}')` |
| 414 | Popup / Modal | `QMessageBox.information(self, 'Rechnung', 'Keine PDF-Rechnung in dieser Mail gefunden.')` |
| 419 | Popup / Modal | `QInputDialog.getItem(self, 'PDF auswaehlen', 'Anhang:', labels, 0, False)` |
| 429 | Popup / Modal | `QMessageBox.warning(self, 'Rechnung', 'PDF konnte nicht geoeffnet werden.')` |
| 450 | Popup / Modal | `PaymentQrDialog(qr_path, payment, self).exec()` |
| 468 | Timer | `QTimer.singleShot(0, self.accept)` |
| 475 | Popup / Modal | `QMessageBox.question(self, 'Ueberweisung durchgefuehrt', 'Diese Ueberweisung als durchgefuehrt markieren?\nDie Mail wird in Outlook als erledigt markiert.\nDer Alarm verschwindet danach fuer diesen Fall.')` |
| 519 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 521 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 522 | Signal → Handler | `worker.signals.error.connect(self._on_action_error)` |
| 523 | Signal → Handler | `worker.signals.finished.connect(lambda current=worker, target=button, text=idle_text: self._finish_action(current, target, text))` |
| 535 | Popup / Modal | `QMessageBox.warning(self, title, str(exc))` |

### A – open_invoice_overview.py

Quelle: `src/xw_office/ui/modules/rechnungen/open_invoice_overview.py`.

Direkte interne Abhängigkeiten: `xw_office.services.invoice_processing.service`, `xw_office.services.products.catalog`, `xw_office.services.sevdesk.invoice_client`, `xw_office.services.wix.client`.

**PrintProductAggregate** (Z. 19): Datenmodell / Konstanten.
Funktion `plan_open_print_products`: Z. 35.
**UnreleasedAssignment** (Z. 85): Datenmodell / Konstanten.
**BuyerNote** (Z. 94): Datenmodell / Konstanten.
**OpenInvoiceOverview** (Z. 105): `suffix`:124.
Funktion `open_invoice_overview_key`: Z. 128.
Funktion `overview_from_visible_summaries`: Z. 140.
Funktion `unknown_open_invoice_summaries`: Z. 224.
Funktion `resolve_open_invoice_overview`: Z. 246.
Funktion `_resolve_one_summary`: Z. 346.
Funktion `_resolve_hint_context`: Z. 433.
Funktion `_cached_hint_context`: Z. 449.
Funktion `note_has_plc_label_hint`: Z. 473.
Funktion `_separate_piece_titles`: Z. 489.
**_ProductAccumulator** (Z. 505): `__init__`:506; `add_items`:514; `to_list`:536.
**_UnreleasedAccumulator** (Z. 558): `__init__`:559; `add_items`:562; `to_list`:600.
**_BuyerNoteAccumulator** (Z. 611): `__init__`:612; `add`:615; `to_list`:639.
Funktion `_cached_reference_digital_only`: Z. 650.
Funktion `_cached_order_buyer_note`: Z. 662.
Funktion `_cached_order_customer_name`: Z. 673.
Funktion `_cached_order_line_items`: Z. 687.
Funktion `_cached_order_shipping_name`: Z. 699.
Funktion `_order_shipping_name`: Z. 713.
Funktion `_order_line_items`: Z. 735.
Funktion `overview_payload_from_object`: Z. 754.
Funktion `_int_value`: Z. 814.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 271 | Hintergrundarbeit | `ThreadPoolExecutor(max_workers=min(4, len(summaries)))` |

### A – payment_qr_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/payment_qr_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.services.transfers.models`.

**PaymentQrDialog** (Z. 21): `__init__`:24; `_build_ui`:30; `_open_png`:74; `_open_folder`:78.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 59 | UI / Aktion | `QPushButton('PNG oeffnen')` |
| 60 | Signal → Handler | `btn_open.clicked.connect(self._open_png)` |
| 63 | UI / Aktion | `QPushButton('Ordner oeffnen')` |
| 64 | Signal → Handler | `btn_folder.clicked.connect(self._open_folder)` |
| 69 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 70 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 71 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 76 | Popup / Modal | `QMessageBox.warning(self, 'QR', 'PNG konnte nicht geoeffnet werden.')` |
| 81 | Popup / Modal | `QMessageBox.warning(self, 'QR', 'Ordner konnte nicht geoeffnet werden.')` |

### A – plc_evidence_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/plc_evidence_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.repositories.plc_shipment`.

**PlcEvidenceDialog** (Z. 18): `__init__`:19; `_render`:58; `_parcel_html`:94; `_import_tracking`:162; `_confirm_code`:181.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 40 | UI / Aktion | `QComboBox(self)` |
| 42 | UI / Aktion | `QLineEdit(self)` |
| 44 | UI / Aktion | `QPushButton('Code zuordnen', self)` |
| 45 | Signal → Handler | `self._confirm.clicked.connect(self._confirm_code)` |
| 50 | UI / Aktion | `QPushButton('Post-Tracking-XML importieren', self)` |
| 51 | Signal → Handler | `import_button.clicked.connect(self._import_tracking)` |
| 53 | UI / Aktion | `QPushButton('Schließen', self)` |
| 54 | Signal → Handler | `close.clicked.connect(self.accept)` |
| 163 | Popup / Modal | `QFileDialog.getOpenFileName(self, 'Originale Post-Trackingdatei auswählen', '', 'Post-Tracking XML (*.xml)')` |
| 174 | Popup / Modal | `QMessageBox.warning(self, 'Post-Tracking', f'Import fehlgeschlagen: {exc}')` |
| 177 | Popup / Modal | `QMessageBox.information(self, 'Post-Tracking', f'{count} neue Post-Ereignisse für diese Rechnung importiert.')` |
| 189 | Popup / Modal | `QMessageBox.warning(self, 'PLC-Code', 'Der Code gehört nicht zu dieser Sendung oder ist bereits einem anderen Paket zugeordnet.')` |

### A – plc_label_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/plc_label_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.repositories.settings_kv`, `xw_office.services.invoice_processing.context`, `xw_office.services.invoice_processing.service`, `xw_office.services.plc.customs_document`, `xw_office.services.plc.label_archive`, `xw_office.services.plc.models`, `xw_office.services.plc.packing_list`, `xw_office.services.plc.partial_fulfillment`, `xw_office.services.plc.polling`, `xw_office.services.plc.pricing`, `xw_office.services.plc.service`, `xw_office.services.plc.webservice`, `xw_office.services.printing.print_jobs`, `xw_office.services.printing.print_queue`, `xw_office.services.secrets.service`, `xw_office.services.sevdesk.invoice_client`, `xw_office.services.shipping.countries`, `xw_office.services.wix.client`.

Funktion `queue_archived_plc_label`: Z. 94.
Funktion `queue_archived_plc_customs`: Z. 134.
Funktion `queue_packing_lists`: Z. 169.
**_PlcDialogContext** (Z. 205): Datenmodell / Konstanten.
**_PlcSendResult** (Z. 215): Datenmodell / Konstanten.
**PlcLabelPrintDialog** (Z. 222): `__init__`:225; `_build_ui`:312; `_load_context`:548; `_on_context_loaded`:645; `_on_context_error`:687; `_on_product_selected`:693; `_on_address_edit`:698; `_on_weight_edit`:705; `_packing_item_key`:711; `_partial_fulfillment_order_key`:721; `_open_quantities_for_items`:724; `_open_quantity_for_item`:737; `_on_package_count_changed`:742; `_set_multi_parcel_tools_visible`:746; `_snapshot_parcel_state`:755; `_split_package_quantity`:772; `_format_package_quantity`:779; `_resize_parcel_state`:782; `_set_package_count`:806; `_add_parcel`:817; `_clear_package`:829; `_delete_parcel`:836; `_package_action_widget`:865; `_ordered_open_widget`:876; `_refresh_parcel_header_delete_buttons`:898; `_layout_parcel_header_buttons`:916; `_add_parcel_widget`:927; `_rebuild_parcel_controls`:939; `_clear_parcel_weight_inputs`:1040; `_update_parcel_summaries`:1048; `_on_parcel_weight_edit`:1068; `_auto_distribute_by_weight`:1086; `_on_order_number_edit`:1224; `_on_country_completed`:1227; `_current_mode`:1230; `_build_reference`:1234; `_current_address_lines`:1253; `_parse_address`:1269; `_country_group`:1276; `_current_country`:1284; `_current_country_group`:1287; `_update_price`:1295; `_sync_product_options`:1330; `_update_customs_visibility`:1343; `_find_product`:1359; `_customs_cell`:1367; `_append_customs_row`:1370; `_populate_customs_table`:1397; `_add_empty_customs_row`:1419; `_remove_selected_customs_row`:1424; `_customs_text`:1430; `_set_customs_details_visible`:1434; `_customs_rows_complete`:1444; `_gross_weight_kg`:1460; `_update_customs_summary`:1467; `_build_customs_articles`:1525; `_is_b2b_packing_order`:1548; `_allocation_warning_rows`:1551; `_confirm_allocation_warnings`:1563; `_capture_pending_fulfillment`:1637; `_record_pending_fulfillment`:1663; `_build_parcels_and_packing_lists`:1677; `_print_packing_lists`:1830; `_send_to_plc`:1862; `_start_send`:1972; `_on_send_result`:2004; `_show_success_overlay`:2138; `_on_send_error`:2192; `_handle_duplicate_archived_label`:2218; `_next_additional_shipment`:2332; `_append_reference_suffix`:2352; `_queue_webservice_label`:2361; `_queue_customs_document`:2364; `_load_products`:2368.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 310 | Timer | `QTimer.singleShot(0, self._load_context)` |
| 339 | UI / Aktion | `QComboBox()` |
| 344 | UI / Aktion | `QComboBox()` |
| 345 | Signal → Handler | `self._product_combo.currentTextChanged.connect(self._on_product_selected)` |
| 348 | UI / Aktion | `QLineEdit()` |
| 350 | Signal → Handler | `self._weight_edit.textChanged.connect(self._on_weight_edit)` |
| 354 | UI / Aktion | `QSpinBox()` |
| 358 | Signal → Handler | `self._package_count.valueChanged.connect(self._on_package_count_changed)` |
| 360 | UI / Aktion | `QPushButton(f'Nach Gewicht verteilen (max. {_PACKING_TARGET_NET_WEIGHT_KG:.1f} kg Warengewicht)')` |
| 366 | Signal → Handler | `self._auto_distribute_btn.clicked.connect(self._auto_distribute_by_weight)` |
| 369 | UI / Aktion | `QLineEdit()` |
| 371 | Signal → Handler | `self._primary_order_number.textChanged.connect(self._on_order_number_edit)` |
| 375 | UI / Aktion | `QLineEdit()` |
| 377 | Signal → Handler | `self._secondary_order_number.textChanged.connect(self._on_order_number_edit)` |
| 380 | UI / Aktion | `QPlainTextEdit()` |
| 385 | UI / Aktion | `QLineEdit()` |
| 387 | Signal → Handler | `self._company_edit.textChanged.connect(self._on_address_edit)` |
| 390 | UI / Aktion | `QLineEdit()` |
| 392 | Signal → Handler | `self._name_edit.textChanged.connect(self._on_address_edit)` |
| 395 | UI / Aktion | `QLineEdit()` |
| 397 | Signal → Handler | `self._street_edit.textChanged.connect(self._on_address_edit)` |
| 400 | UI / Aktion | `QLineEdit()` |
| 402 | Signal → Handler | `self._postal_city_edit.textChanged.connect(self._on_address_edit)` |
| 405 | UI / Aktion | `QComboBox()` |
| 416 | Signal → Handler | `country_completer.activated[str].connect(self._on_country_completed)` |
| 418 | Signal → Handler | `self._country_combo.editTextChanged.connect(self._on_address_edit)` |
| 421 | UI / Aktion | `QPlainTextEdit()` |
| 426 | Signal → Handler | `self._address_edit.textChanged.connect(self._on_address_edit)` |
| 429 | UI / Aktion | `QLineEdit()` |
| 457 | UI / Aktion | `QTableWidget(0, 0, self._parcel_group)` |
| 462 | Signal → Handler | `self._packing_table.itemChanged.connect(self._update_parcel_summaries)` |
| 464 | Signal → Handler | `packing_header.sectionResized.connect(lambda *_args: self._layout_parcel_header_buttons())` |
| 465 | Signal → Handler | `packing_header.geometriesChanged.connect(self._layout_parcel_header_buttons)` |
| 497 | UI / Aktion | `QPushButton('Artikeldetails anzeigen')` |
| 499 | Signal → Handler | `self._customs_details_btn.toggled.connect(self._set_customs_details_visible)` |
| 506 | UI / Aktion | `QTableWidget(0, 8, self._customs_details)` |
| 507 | UI / Aktion | `self._customs_table.setHorizontalHeaderLabels(['Artikel (Englisch)', 'SKU', 'Anzahl', 'Netto kg/Stk', 'Wert/Stk', 'Währung', 'Ursprung', 'Zolltarif-Nr.'])` |
| 517 | Signal → Handler | `self._customs_table.itemChanged.connect(self._update_customs_summary)` |
| 521 | UI / Aktion | `QPushButton('Artikel hinzufügen')` |
| 522 | UI / Aktion | `QPushButton('Ausgewählten Artikel entfernen')` |
| 523 | Signal → Handler | `add_customs.clicked.connect(self._add_empty_customs_row)` |
| 524 | Signal → Handler | `remove_customs.clicked.connect(self._remove_selected_customs_row)` |
| 536 | UI / Aktion | `QPushButton('Senden an PLC')` |
| 537 | UI / Aktion | `QPushButton('Packliste drucken')` |
| 538 | UI / Aktion | `QPushButton('Abbrechen')` |
| 542 | Signal → Handler | `self._packing_print_btn.clicked.connect(self._print_packing_lists)` |
| 543 | Signal → Handler | `self._send_btn.clicked.connect(self._send_to_plc)` |
| 544 | Signal → Handler | `cancel_button.clicked.connect(self.reject)` |
| 640 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 641 | Signal → Handler | `self._load_worker.signals.result.connect(self._on_context_loaded)` |
| 642 | Signal → Handler | `self._load_worker.signals.error.connect(self._on_context_error)` |
| 820 | Popup / Modal | `QMessageBox.warning(self, 'Paketaufteilung', f'Es sind höchstens {self._package_count.maximum()} Pakete möglich.')` |
| 849 | Popup / Modal | `QMessageBox.warning(self, 'Paket löschen', 'Bitte zuerst alle Mengen als ganze Zahl oder im Format 10+1 eintragen.')` |
| 869 | UI / Aktion | `QPushButton('Liste leeren', widget)` |
| 872 | Signal → Handler | `clear_button.clicked.connect(lambda _checked=False, index=package_index: self._clear_package(index))` |
| 905 | UI / Aktion | `QToolButton(header.viewport())` |
| 911 | Signal → Handler | `button.clicked.connect(lambda _checked=False, index=package_index: self._delete_parcel(index))` |
| 931 | UI / Aktion | `QPushButton('+', widget)` |
| 934 | Signal → Handler | `add_button.clicked.connect(lambda _checked=False: self._add_parcel())` |
| 965 | UI / Aktion | `self._packing_table.setHorizontalHeaderLabels(['Produkt', 'Bestellt / offen', *[f'Paket {number}' for number in range(1, package_count + 1)], '+'])` |
| 1022 | UI / Aktion | `QLineEdit()` |
| 1035 | Signal → Handler | `edit.textChanged.connect(self._on_parcel_weight_edit)` |
| 1095 | Popup / Modal | `QMessageBox.warning(self, 'Paketaufteilung', 'Keine physischen Produkte zum Verteilen gefunden.')` |
| 1118 | Popup / Modal | `QMessageBox.information(self, 'Paketaufteilung', 'Für diese Bestellung sind keine offenen Produkte mehr vorhanden.')` |
| 1125 | Popup / Modal | `QMessageBox.warning(self, 'Gewicht fehlt', 'Die automatische Verteilung benötigt ein Wix-Gewicht für jedes physische Produkt.\n\nOhne Gewicht: ' + ', '.join(missing_weights))` |
| 1141 | Popup / Modal | `QMessageBox.warning(self, 'Produkt zu schwer für ein Paket', f'Dieses Produkt würde allein die sichere Grenze von {_PACKING_TARGET_NET_WEIGHT_KG:.1f} kg Warengewicht überschreiten:\n\n' + '\n'.join(too_heavy) + '\n\nSie wird nicht automatisch geteilt, weil gleiche Produkte zusammenbleib…` |
| 1173 | Popup / Modal | `QMessageBox.warning(self, 'Zu viele Pakete', f'Die sichere Verteilung benötigt {len(bins)} Pakete; erlaubt sind höchstens {self._package_count.maximum()}.')` |
| 1597 | UI / Aktion | `QTableWidget(len(rows), 3, dialog)` |
| 1599 | UI / Aktion | `table.setHorizontalHeaderLabels(['Produkt', 'Verteilt', 'Offen'])` |
| 1625 | UI / Aktion | `QPushButton('✕ Zurück und prüfen', dialog)` |
| 1627 | Signal → Handler | `cancel.clicked.connect(dialog.reject)` |
| 1628 | UI / Aktion | `QPushButton(f'✓ {action} trotzdem', dialog)` |
| 1631 | Signal → Handler | `proceed.clicked.connect(dialog.accept)` |
| 1635 | Popup / Modal | `dialog.exec()` |
| 1833 | Popup / Modal | `QMessageBox.information(self, 'Packliste', 'Eine Packliste kann erstellt werden, sobald mindestens zwei Pakete angelegt sind.')` |
| 1856 | Popup / Modal | `QMessageBox.warning(self, 'Packliste', f'Packliste konnte nicht gedruckt werden: {exc}')` |
| 1875 | Popup / Modal | `QMessageBox.warning(self, 'PLC', 'Bitte folgende Empfängerdaten eingeben: ' + ', '.join(missing_fields))` |
| 1884 | Popup / Modal | `QMessageBox.warning(self, 'PLC', 'Bitte Lieferadresse eingeben.')` |
| 1889 | Popup / Modal | `QMessageBox.warning(self, 'PLC', 'Adresse ist unvollständig.')` |
| 1903 | Popup / Modal | `QMessageBox.information(self, 'Zollerklärung', 'Für dieses Zielland wird keine Zollerklärung benötigt.')` |
| 1910 | Popup / Modal | `QMessageBox.warning(self, 'PLC', 'Versandprodukt ist nicht konfiguriert.')` |
| 1915 | Popup / Modal | `QMessageBox.warning(self, 'PLC', 'Mehrpaket-Sendungen außerhalb der EU benötigen eine paketweise Zollartikelaufteilung und sind noch nicht verfügbar.')` |
| 1928 | Popup / Modal | `QMessageBox.warning(self, 'PLC', str(exc))` |
| 1941 | Popup / Modal | `QMessageBox.warning(self, 'PLC', str(exc))` |
| 1944 | Popup / Modal | `QMessageBox.warning(self, 'PLC', 'Für dieses Zielland wird mindestens ein Zollartikel benötigt.')` |
| 1961 | Popup / Modal | `QMessageBox.warning(self, 'PLC', str(exc))` |
| 1998 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1999 | Signal → Handler | `self._send_worker.signals.result.connect(lambda result: self._on_send_result(shipment, result))` |
| 2000 | Signal → Handler | `self._send_worker.signals.error.connect(lambda exc: self._on_send_error(shipment, exc))` |
| 2001 | Signal → Handler | `self._send_worker.signals.finished.connect(lambda: self._send_btn.setEnabled(True))` |
| 2094 | Popup / Modal | `QMessageBox.warning(self, 'Zollerklärung erstellt' if self._customs_only else 'PLC-Label erstellt', f'{failure_message}{archive_note}\n\nDetails: {exc}')` |
| 2190 | Timer | `QTimer.singleShot(_SUCCESS_OVERLAY_MS, self.accept)` |
| 2201 | Popup / Modal | `QMessageBox.warning(self, 'Zollerklärung bereits erstellt' if self._customs_only else 'PLC-Label bereits erstellt', 'PLC sperrt eine zweite Erstellung dieser Zollerklärung. Ein lokales Archiv-PDF wurde noch nicht gefunden, daher kann XW-Office keinen sicheren Nachdruck ausführen.' if se…` |
| 2216 | Popup / Modal | `QMessageBox.critical(self, 'PLC Fehler', str(exc))` |
| 2254 | UI / Aktion | `box.addButton(reprint_label, QMessageBox.ButtonRole.AcceptRole)` |
| 2256 | UI / Aktion | `box.addButton('Label-PDF öffnen', QMessageBox.ButtonRole.ActionRole)` |
| 2263 | UI / Aktion | `box.addButton('Zoll-Original öffnen', QMessageBox.ButtonRole.ActionRole)` |
| 2265 | UI / Aktion | `box.addButton('Zoll-A5 öffnen', QMessageBox.ButtonRole.ActionRole)` |
| 2266 | UI / Aktion | `box.addButton('Neue Zollerklärung erstellen' if self._customs_only else 'Neues Label erstellen', QMessageBox.ButtonRole.ActionRole)` |
| 2270 | UI / Aktion | `box.addButton('Abbrechen', QMessageBox.ButtonRole.RejectRole)` |
| 2272 | Popup / Modal | `box.exec()` |
| 2294 | Popup / Modal | `QMessageBox.warning(self, 'PLC-Nachdruck', f'Nachdruck konnte nicht eingereiht werden:\n\n{exc}')` |

### A – plc_statistics_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/plc_statistics_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.worker`, `xw_office.services.plc.statistics`.

**_StatisticsPage** (Z. 23): `__init__`:24; `apply`:64.
**PlcStatisticsDialog** (Z. 99): `__init__`:100; `_build_ui`:110; `_reload`:137; `_on_loaded`:148; `_on_error`:157; `_on_finished`:160.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 47 | UI / Aktion | `QTableWidget(0, 4)` |
| 48 | UI / Aktion | `self._table.setHorizontalHeaderLabels(['Land', 'Sendungen', 'Gewicht', 'Preis'])` |
| 117 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 118 | Signal → Handler | `self._refresh.clicked.connect(self._reload)` |
| 126 | UI / Aktion | `QTabWidget()` |
| 130 | UI / Aktion | `self._tabs.addTab(page, label)` |
| 133 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 134 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 142 | Hintergrundarbeit | `BackgroundWorker(self._service.load)` |
| 143 | Signal → Handler | `self._worker.signals.result.connect(self._on_loaded)` |
| 144 | Signal → Handler | `self._worker.signals.error.connect(self._on_error)` |
| 145 | Signal → Handler | `self._worker.signals.finished.connect(self._on_finished)` |

### A – print_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/print_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.printer_detect`, `xw_office.core.signals`, `xw_office.core.types`, `xw_office.services.inventory`, `xw_office.services.printing.pdf_renderer`, `xw_office.services.printing.planned_pdf_printer`, `xw_office.services.printing.print_jobs`, `xw_office.services.printing.print_queue`, `xw_office.services.products.catalog`, `xw_office.services.products.print_decision`.

Funktion `_format_page_ranges`: Z. 57.
**_PrintPlanModel** (Z. 73): `__init__`:76; `rowCount`:81; `columnCount`:84; `data`:87; `setData`:100; `flags`:112; `headerData`:120; `add_row`:125; `remove_row`:131; `plan`:138; `_printer_for_profile`:141.
**_PrintProfileDelegate** (Z. 148): `__init__`:149; `createEditor`:153; `setEditorData`:160; `setModelData`:171.
**ProductPrintConfigDialog** (Z. 176): `__init__`:177; `values`:265; `accept`:271; `_browse_pdf`:294; `_open_pdf`:299; `_open_pdf_folder`:306; `_load_initial_plan_rows`:314; `_add_plan_row`:326; `_remove_selected_plan_row`:329; `_parse_plan`:332; `_pdf_path`:342; `_refresh_pdf_status`:345; `_refresh_plan_summary`:374; `_plan_coverage_note`:390; `_refresh_title_override_note`:420; `_profile_printer`:444; `_backend_label`:451.
Funktion `_check_printer_runtime`: Z. 458.
Funktion `_print_with_dialog`: Z. 482.
Funktion `run_invoice_pdf_print`: Z. 538.
Funktion `run_label_pdf_print`: Z. 548.
Funktion `run_plc_label_pdf_print`: Z. 558.
Funktion `run_music_pdf_print`: Z. 574.
Funktion `_configure_missing_piece_print`: Z. 584.
Funktion `prepare_piece_pdf_print`: Z. 636.
Funktion `run_piece_pdf_print`: Z. 705.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 154 | UI / Aktion | `QComboBox(parent)` |
| 166 | Signal → Handler | `editor.currentIndexChanged.connect(lambda _selected, combo=editor: self.commitData.emit(combo))` |
| 195 | UI / Aktion | `QLineEdit(str(piece.print_file_path or ''))` |
| 196 | Signal → Handler | `self._path_edit.textChanged.connect(self._refresh_pdf_status)` |
| 199 | UI / Aktion | `QPushButton('PDF waehlen')` |
| 200 | Signal → Handler | `browse_btn.clicked.connect(self._browse_pdf)` |
| 202 | UI / Aktion | `QPushButton('PDF oeffnen')` |
| 203 | Signal → Handler | `open_pdf_btn.clicked.connect(self._open_pdf)` |
| 205 | UI / Aktion | `QPushButton('Ordner')` |
| 206 | Signal → Handler | `open_folder_btn.clicked.connect(self._open_pdf_folder)` |
| 226 | UI / Aktion | `QTableView(self)` |
| 229 | Signal → Handler | `self._plan_model.dataChanged.connect(lambda *_args: self._refresh_plan_summary())` |
| 230 | Signal → Handler | `self._plan_model.rowsInserted.connect(lambda *_args: self._refresh_plan_summary())` |
| 231 | Signal → Handler | `self._plan_model.rowsRemoved.connect(lambda *_args: self._refresh_plan_summary())` |
| 237 | UI / Aktion | `QPushButton('Zeile hinzufuegen')` |
| 238 | Signal → Handler | `add_row_btn.clicked.connect(lambda: self._add_plan_row('Alle Seiten', ''))` |
| 240 | UI / Aktion | `QPushButton('Zeile entfernen')` |
| 241 | Signal → Handler | `remove_row_btn.clicked.connect(self._remove_selected_plan_row)` |
| 258 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Save &#124; QDialogButtonBox.StandardButton.Cancel)` |
| 259 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 260 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 275 | Popup / Modal | `QMessageBox.warning(self, 'Druck konfigurieren', str(exc))` |
| 278 | Popup / Modal | `QMessageBox.warning(self, 'Druck konfigurieren', 'Bitte einen PDF-Druckpfad waehlen.')` |
| 281 | Popup / Modal | `QMessageBox.warning(self, 'Druck konfigurieren', 'Bitte Drucker oder Druckplan angeben.')` |
| 285 | Popup / Modal | `QMessageBox.warning(self, 'Druck konfigurieren', 'Die gewaehlte PDF-Datei existiert nicht.')` |
| 290 | Popup / Modal | `QMessageBox.warning(self, 'Druck konfigurieren', 'Die PDF-Datei konnte nicht geoeffnet werden.')` |
| 295 | Popup / Modal | `QFileDialog.getOpenFileName(self, 'Produkt-PDF waehlen', self._path_edit.text(), 'PDF (*.pdf)')` |
| 463 | Popup / Modal | `QMessageBox.warning(parent, 'Druck nicht verfuegbar', 'Kein konfigurierter Drucker ist verfuegbar (Ampel rot).')` |
| 473 | Popup / Modal | `QMessageBox.warning(parent, 'Falscher Drucker', 'Der gewaehlt Drucker ist nicht in den konfigurierten Druckern enthalten.')` |
| 492 | Popup / Modal | `QFileDialog.getOpenFileName(parent, title, '', 'PDF (*.pdf);;Alle Dateien (*.*)')` |
| 506 | Popup / Modal | `dialog.exec()` |
| 521 | Popup / Modal | `QMessageBox.warning(parent, 'Druck', 'Kein Drucker ausgewaehlt.')` |
| 590 | Popup / Modal | `dialog.exec()` |
| 658 | Popup / Modal | `QMessageBox.warning(parent, 'Produktdruck', f'Kein PDF-Pfad für SKU {piece.sku} konfiguriert.')` |
| 670 | Popup / Modal | `QMessageBox.critical(parent, 'Produktdruck fehlgeschlagen', f'Die Produkt-PDF konnte nicht geoeffnet werden:\n\n{exc}')` |
| 724 | Popup / Modal | `QMessageBox.critical(parent, 'Produktdruck fehlgeschlagen', f'Die Produkt-PDF konnte nicht ueber den hinterlegten Druckplan gedruckt werden:\n\n{exc}')` |

### A – product_preflight_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/product_preflight_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.services.draft_invoice.service`.

**ProductPreflightDialog** (Z. 22): `__init__`:25; `_build`:44; `show_dialog`:144; `_collect_draft`:148; `_create`:173; `_skip`:180; `_fmt_num`:185; `_fmt_currency`:191; `_parse_optional_float`:197.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 76 | UI / Aktion | `QPlainTextEdit()` |
| 81 | UI / Aktion | `QPlainTextEdit()` |
| 98 | UI / Aktion | `QLineEdit(draft.name)` |
| 99 | UI / Aktion | `QLineEdit(draft.sku)` |
| 100 | UI / Aktion | `QLineEdit(self._fmt_currency(draft.price_gross))` |
| 101 | UI / Aktion | `QLineEdit(self._fmt_num(draft.tax_rate if draft.tax_rate is not None else 10.0))` |
| 102 | UI / Aktion | `QComboBox()` |
| 111 | UI / Aktion | `QPlainTextEdit()` |
| 113 | UI / Aktion | `QPlainTextEdit()` |
| 136 | UI / Aktion | `QPushButton('Überspringen')` |
| 137 | Signal → Handler | `btn_skip.clicked.connect(self._skip)` |
| 138 | UI / Aktion | `QPushButton('Produkt anlegen')` |
| 139 | Signal → Handler | `btn_create.clicked.connect(self._create)` |
| 145 | Popup / Modal | `self.exec()` |
| 152 | Popup / Modal | `QMessageBox.warning(self, 'Produkt', 'Name und SKU dürfen nicht leer sein.')` |
| 158 | Popup / Modal | `QMessageBox.warning(self, 'Produkt', str(exc))` |

### A – redelivery_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/redelivery_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.repositories.customer_aftercare`.

**RedeliveryDialogOutcome** (Z. 31): Datenmodell / Konstanten.
**RedeliveryDialog** (Z. 39): `__init__`:42; `outcome`:60; `_build_ui`:63; `_preview`:142; `_remove_selected_items`:163; `_decode_address`:172; `_add_item_row`:181; `_add_manual_item`:199; `_save`:221.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 73 | UI / Aktion | `QPlainTextEdit()` |
| 90 | UI / Aktion | `QComboBox()` |
| 98 | UI / Aktion | `QPlainTextEdit()` |
| 104 | UI / Aktion | `QPlainTextEdit()` |
| 111 | UI / Aktion | `QTableWidget(0, 5)` |
| 112 | UI / Aktion | `self._table.setHorizontalHeaderLabels(['', 'Produkt / Stimme', 'SKU / Komponente', 'Menge', 'Quelle'])` |
| 121 | UI / Aktion | `QPushButton('Manuelle Position hinzufügen')` |
| 122 | Signal → Handler | `add_button.clicked.connect(self._add_manual_item)` |
| 125 | UI / Aktion | `QPushButton('Ausgewählte Position entfernen')` |
| 126 | Signal → Handler | `remove_button.clicked.connect(self._remove_selected_items)` |
| 129 | UI / Aktion | `QPushButton('Lieferschein-Vorschau')` |
| 130 | Signal → Handler | `preview_button.clicked.connect(self._preview)` |
| 133 | UI / Aktion | `QDialogButtonBox()` |
| 134 | UI / Aktion | `QPushButton('Nachlieferung speichern')` |
| 135 | UI / Aktion | `QPushButton('Abbrechen')` |
| 136 | UI / Aktion | `buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)` |
| 137 | UI / Aktion | `buttons.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)` |
| 138 | Signal → Handler | `save.clicked.connect(self._save)` |
| 139 | Signal → Handler | `cancel.clicked.connect(self.reject)` |
| 154 | Popup / Modal | `QMessageBox.information(self, 'Lieferschein-Vorschau', f'NACHLIEFERUNG\n\n{address}\n\n' + ('\n'.join(products) if products else '(keine Position ausgewählt)') + f'\n\n{note}')` |
| 200 | Popup / Modal | `QInputDialog.getText(self, 'Manuelle Position', 'Produktbezeichnung:')` |
| 203 | Popup / Modal | `QInputDialog.getText(self, 'Manuelle Position', 'SKU (optional):')` |
| 206 | Popup / Modal | `QInputDialog.getInt(self, 'Manuelle Position', 'Menge:', 1, 1, 999)` |

### A – refund_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/refund_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.services.sevdesk.invoice_client`.

**RefundDialog** (Z. 17): `__init__`:20; `send_customer_mail`:69.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 50 | UI / Aktion | `QCheckBox('Kundenmail über Wix senden')` |
| 55 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel &#124; QDialogButtonBox.StandardButton.Ok)` |
| 64 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 65 | Signal → Handler | `buttons.rejected.connect(self.reject)` |

### A – refunds_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/refunds_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.services.flow_api`, `xw_office.services.invoice_processing.service`, `xw_office.services.mailing.service`, `xw_office.services.sevdesk.invoice_client`, `xw_office.services.sevdesk.refund_client`, `xw_office.services.wix.client`.

**RefundsDialog** (Z. 33): `__init__`:34; `_load`:54; `_credit_note_id`:87; `_open_pdf`:93; `_send_mail`:108.
Funktion `_find_email`: Z. 149.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 42 | UI / Aktion | `QTableWidget(0, 8, self)` |
| 43 | UI / Aktion | `self._table.setHorizontalHeaderLabels(['Refund', 'Order', 'Betrag', 'Wix', 'Aktion', 'Status', 'sevDesk', 'Aktionen'])` |
| 48 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 49 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 50 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 58 | Popup / Modal | `QMessageBox.warning(self, 'Refunds', f'Refund-Liste konnte nicht geladen werden:\n\n{exc}')` |
| 76 | UI / Aktion | `QPushButton('PDF')` |
| 77 | Signal → Handler | `pdf.clicked.connect(lambda _checked=False, index=row_index: self._open_pdf(index))` |
| 78 | UI / Aktion | `QPushButton('Mail')` |
| 79 | Signal → Handler | `mail.clicked.connect(lambda _checked=False, index=row_index: self._send_mail(index))` |
| 106 | Popup / Modal | `QMessageBox.warning(self, 'Gutschrift-PDF', str(exc))` |
| 128 | Popup / Modal | `QInputDialog.getText(self, 'Gutschrift senden', 'E-Mail-Adresse:')` |
| 133 | Popup / Modal | `QMessageBox.question(self, 'Gutschrift senden', f'Gutschrift {number} an {email.strip()} senden?')` |
| 144 | Popup / Modal | `QMessageBox.information(self, 'Gutschrift gesendet', f'Die Gutschrift wurde an {email.strip()} gesendet.')` |
| 146 | Popup / Modal | `QMessageBox.warning(self, 'Gutschrift senden', str(exc))` |

### A – reprint_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/reprint_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.ui.widgets.data_table`.

**ReprintPreviewDialog** (Z. 20): `__init__`:28; `_build_ui`:36.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 116 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Ok &#124; QDialogButtonBox.StandardButton.Cancel)` |
| 119 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 120 | Signal → Handler | `buttons.rejected.connect(self.reject)` |

### A – special_order_dialog.py

Quelle: `src/xw_office/ui/modules/rechnungen/special_order_dialog.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.worker`, `xw_office.services.special_orders`.

**SpecialOrderDialog** (Z. 35): `__init__`:38; `_build_ui`:48; `_load_products`:116; `_on_products_loaded`:126; `_filter_products`:131; `_update_mode`:148; `_add_selected_product`:159; `_remove_product`:168; `_refresh_selected_products`:179; `_sync_price_from_selection`:204; `_create_link`:212; `_build_items`:252; `_find_handling_product`:308; `_is_selected_product`:314; `_same_product`:323; `_payment_link_title`:332; `_payment_link_description`:341; `_product_price`:349; `_on_link_created`:355; `_on_link_error`:362; `_https_url`:367.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 46 | Timer | `QTimer.singleShot(0, self._load_products)` |
| 54 | UI / Aktion | `QComboBox()` |
| 58 | Signal → Handler | `self._mode.currentIndexChanged.connect(self._update_mode)` |
| 61 | UI / Aktion | `QLineEdit()` |
| 63 | UI / Aktion | `QTextEdit()` |
| 72 | UI / Aktion | `QSpinBox()` |
| 86 | UI / Aktion | `QLineEdit()` |
| 88 | Signal → Handler | `self._product_filter.textChanged.connect(self._filter_products)` |
| 90 | UI / Aktion | `QListWidget()` |
| 93 | Signal → Handler | `self._product_list.itemClicked.connect(self._add_selected_product)` |
| 98 | UI / Aktion | `QListWidget()` |
| 106 | UI / Aktion | `QPushButton('Payment Link erstellen + kopieren')` |
| 107 | Signal → Handler | `self._create_btn.clicked.connect(self._create_link)` |
| 111 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 112 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 120 | Hintergrundarbeit | `BackgroundWorker(self._service.list_wix_products)` |
| 121 | Signal → Handler | `self._worker.signals.result.connect(self._on_products_loaded)` |
| 122 | Signal → Handler | `self._worker.signals.error.connect(lambda exc: self._status.setText(str(exc)))` |
| 123 | Signal → Handler | `self._worker.signals.finished.connect(lambda: setattr(self, '_worker', None))` |
| 195 | UI / Aktion | `QPushButton('✕')` |
| 198 | Signal → Handler | `remove_btn.clicked.connect(lambda _checked=False, product=product: self._remove_product(product))` |
| 217 | Popup / Modal | `QMessageBox.warning(self, 'Sonderauftrag', 'Titel ist Pflicht.')` |
| 222 | Popup / Modal | `QMessageBox.warning(self, 'Sonderauftrag', str(exc))` |
| 245 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 246 | Signal → Handler | `self._worker.signals.result.connect(self._on_link_created)` |
| 247 | Signal → Handler | `self._worker.signals.error.connect(self._on_link_error)` |
| 248 | Signal → Handler | `self._worker.signals.finished.connect(lambda: self._create_btn.setEnabled(True))` |
| 249 | Signal → Handler | `self._worker.signals.finished.connect(lambda: setattr(self, '_worker', None))` |
| 360 | Popup / Modal | `QMessageBox.information(self, 'Sonderauftrag', f'Payment Link erstellt und in die Zwischenablage kopiert:\n{url}')` |
| 364 | Popup / Modal | `QMessageBox.warning(self, 'Sonderauftrag', str(exc))` |

### A – tagesgeschaeft_view.py

Quelle: `src/xw_office/ui/modules/rechnungen/tagesgeschaeft_view.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.signals`, `xw_office.core.types`, `xw_office.core.worker`, `xw_office.services.b2b_credit`, `xw_office.services.background_jobs.service`, `xw_office.services.customer_aftercare.service`, `xw_office.services.daily_business.service`, `xw_office.services.digital_licenses`, `xw_office.services.draft_invoice.service`, `xw_office.services.drucke.service`, `xw_office.services.inventory.service`, `xw_office.services.invoice_processing.buyer_notes`, `xw_office.services.invoice_processing.service`, `xw_office.services.sendungen.service`, `xw_office.services.sevdesk.invoice_client`, `xw_office.services.transfers.service`, `xw_office.ui.modules.rechnungen.buyer_note_review_dialog`, `xw_office.ui.modules.rechnungen.customer_aftercare_review_dialog`, `xw_office.ui.modules.rechnungen.product_preflight_dialog`, `xw_office.ui.modules.rechnungen.reprint_dialog`, `xw_office.ui.modules.rechnungen.view`, `xw_office.ui.widgets.data_table`, `xw_office.ui.widgets.search_bar`.

**_QueueTabView** (Z. 80): `__init__`:83; `_build_ui`:92; `hideEvent`:124; `closeEvent`:127; `reload`:130; `_on_load_result`:145; `_on_load_error`:154; `_on_search`:158; `_queue_search_suggestions`:161; `_on_selection_changed`:172.
**QueuePopupDialog** (Z. 186): `__init__`:189.
**_StartDialog** (Z. 211): `__init__`:214; `full_mode`:278; `selected_mode`:282; `_format_preflight`:285.
**TagesgeschaeftView** (Z. 316): `__init__`:319; `showEvent`:363; `hideEvent`:368; `closeEvent`:372; `has_active_flow`:384; `prepare_shutdown`:397; `request_shutdown`:401; `shutdown_complete`:411; `_shutdown_workers`:416; `_wait_for_workers`:433; `_build_ui`:443; `_materialize_rechnungen_view`:626; `_set_invoice_ui_ready`:637; `_reload_invoice_view`:649; `_create_invoice_draft`:653; `_open_custom_label`:657; `_open_manual_plc_label`:661; `_open_plc_statistics`:665; `_open_statistics`:669; `_open_special_order`:673; `_build_alert_button`:677; `_refresh_badges`:690; `_create_badge_refresh_worker`:699; `_on_badges_result`:786; `_on_badges_error`:843; `_update_alert_button`:847; `_on_sendungen_alert_clicked`:854; `_on_drucke_alert_clicked`:868; `_on_digital_licenses_alert_clicked`:875; `_on_transfer_alert_clicked`:886; `_on_mollie_alert_clicked`:893; `_on_b2b_credit_alert_clicked`:903; `_on_lieferkorrektur_review_alert_clicked`:927; `_on_lieferkorrektur_due_alert_clicked`:930; `_open_lieferkorrekturen_dialog`:933; `_maybe_show_next_lieferkorrektur_review_popup`:950; `_show_lieferkorrektur_review_popup`:993; `_apply_lieferkorrektur_review_outcome`:1001; `_on_start_clicked`:1041; `_on_start_preflight_ready`:1137; `_start_missing_product_check`:1199; `_show_b2b_credit_holds`:1244; `_on_start_product_preflight_ready`:1327; `_run_product_preflight_dialogs`:1491; `_on_start_executed`:1501; `_offer_digital_license_delivery`:1599; `_on_digital_license_candidates_ready`:1615; `_on_start_preflight_error`:1640; `_set_start_running`:1650; `_on_start_stop_clicked`:1660; `_on_reprints_clicked`:1678; `_on_reprint_preflight_ready`:1696; `_on_reprint_executed`:1720; `_on_reprint_error`:1750.

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 103 | Signal → Handler | `self._search.search_changed.connect(self._on_search)` |
| 108 | UI / Aktion | `QPushButton('Aktualisieren')` |
| 109 | Signal → Handler | `self._btn_refresh.clicked.connect(lambda: self.reload())` |
| 122 | Signal → Handler | `sel.selectionChanged.connect(self._on_selection_changed)` |
| 139 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 140 | Signal → Handler | `self._worker.signals.result.connect(self._on_load_result)` |
| 141 | Signal → Handler | `self._worker.signals.error.connect(self._on_load_error)` |
| 142 | Signal → Handler | `self._worker.signals.finished.connect(lambda: self._btn_refresh.setEnabled(True))` |
| 204 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)` |
| 205 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 206 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 239 | UI / Aktion | `QPushButton('📄 Nur Rechnungen')` |
| 242 | UI / Aktion | `QPushButton('📄 + 🖨 Rechnungen + Druck (Noten & Labels vorbereiten)')` |
| 259 | UI / Aktion | `QPlainTextEdit()` |
| 267 | Signal → Handler | `self._mode_invoices.toggled.connect(lambda c: self._mode_full.setChecked(not c) if c else None)` |
| 268 | Signal → Handler | `self._mode_full.toggled.connect(lambda c: self._mode_invoices.setChecked(not c) if c else None)` |
| 270 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Ok &#124; QDialogButtonBox.StandardButton.Cancel)` |
| 273 | Signal → Handler | `buttons.accepted.connect(self.accept)` |
| 274 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 358 | Timer | `QTimer(self)` |
| 359 | Timer | `self._badge_timer.setInterval(60000)` |
| 360 | Signal → Handler | `self._badge_timer.timeout.connect(self._refresh_badges)` |
| 454 | UI / Aktion | `QToolButton()` |
| 467 | Signal → Handler | `self._btn_refresh.clicked.connect(self._reload_invoice_view)` |
| 470 | UI / Aktion | `QPushButton('Entwurf')` |
| 473 | Signal → Handler | `self._btn_draft.clicked.connect(self._create_invoice_draft)` |
| 476 | UI / Aktion | `QToolButton()` |
| 491 | UI / Aktion | `QMenu(self._btn_label_menu)` |
| 492 | Signal → Handler | `label_menu.addAction('Custom-Label …').triggered.connect(self._open_custom_label)` |
| 492 | UI / Aktion | `label_menu.addAction('Custom-Label …')` |
| 493 | Signal → Handler | `label_menu.addAction('PLC-Label …').triggered.connect(self._open_manual_plc_label)` |
| 493 | UI / Aktion | `label_menu.addAction('PLC-Label …')` |
| 497 | UI / Aktion | `QToolButton()` |
| 511 | Signal → Handler | `self._btn_statistics.clicked.connect(self._open_statistics)` |
| 514 | UI / Aktion | `QPushButton('Sonderauftrag')` |
| 517 | Signal → Handler | `self._btn_special_order.clicked.connect(self._open_special_order)` |
| 520 | UI / Aktion | `QToolButton()` |
| 537 | Signal → Handler | `self._btn_start.clicked.connect(lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, include_product_print=False))` |
| 541 | UI / Aktion | `QMenu(self._btn_start)` |
| 542 | Signal → Handler | `start_menu.addAction('Selected').triggered.connect(lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, selected_only=True, include_product_print=False))` |
| 542 | UI / Aktion | `start_menu.addAction('Selected')` |
| 545 | Signal → Handler | `start_menu.addAction('+ Noten').triggered.connect(lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, selected_only=False, include_product_print=True))` |
| 545 | UI / Aktion | `start_menu.addAction('+ Noten')` |
| 548 | Signal → Handler | `start_menu.addAction('+ Noten Selected').triggered.connect(lambda: self._on_start_clicked(StartMode.INVOICES_AND_PRINT, selected_only=True, include_product_print=True))` |
| 548 | UI / Aktion | `start_menu.addAction('+ Noten Selected')` |
| 553 | UI / Aktion | `QPushButton('STOP')` |
| 567 | Signal → Handler | `self._btn_stop.clicked.connect(self._on_start_stop_clicked)` |
| 572 | Signal → Handler | `self._btn_sendungen_alert.clicked.connect(self._on_sendungen_alert_clicked)` |
| 577 | Signal → Handler | `self._btn_drucke_alert.clicked.connect(self._on_drucke_alert_clicked)` |
| 582 | Signal → Handler | `self._btn_digital_licenses_alert.clicked.connect(self._on_digital_licenses_alert_clicked)` |
| 587 | Signal → Handler | `self._btn_transfer_alert.clicked.connect(self._on_transfer_alert_clicked)` |
| 592 | Signal → Handler | `self._btn_mollie_alert.clicked.connect(self._on_mollie_alert_clicked)` |
| 597 | Signal → Handler | `self._btn_lieferkorrektur_review_alert.clicked.connect(self._on_lieferkorrektur_review_alert_clicked)` |
| 604 | Signal → Handler | `self._btn_lieferkorrektur_due_alert.clicked.connect(self._on_lieferkorrektur_due_alert_clicked)` |
| 609 | Signal → Handler | `self._btn_b2b_credit_alert.clicked.connect(self._on_b2b_credit_alert_clicked)` |
| 624 | Timer | `QTimer.singleShot(0, self._materialize_rechnungen_view)` |
| 678 | UI / Aktion | `QPushButton(label)` |
| 691 | Hintergrundarbeit | `self._background_jobs.submit(queue=_BADGE_JOB_QUEUE, priority=10, coalesce_key='tagesgeschaeft-badges', start_fn=self._create_badge_refresh_worker, can_start=lambda: self._badge_worker is None or not self._badge_worker.isRunning())` |
| 780 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 781 | Signal → Handler | `self._badge_worker.signals.result.connect(self._on_badges_result)` |
| 782 | Signal → Handler | `self._badge_worker.signals.error.connect(self._on_badges_error)` |
| 783 | Signal → Handler | `self._badge_worker.signals.finished.connect(lambda: setattr(self, '_badge_worker', None))` |
| 915 | Popup / Modal | `QMessageBox.information(self, 'B2B-Zahlungsplan', 'Mindestens eine Rate ist fällig. Bitte in sevDesk die nächste Teilrechnung prüfen/erstellen und nach Zahlung den Zahlungseingang kontrollieren.')` |
| 922 | Popup / Modal | `QMessageBox.information(self, 'B2B-Zahlungen', 'Aktuell keine B2B-Kreditfreigabe offen.')` |
| 924 | Popup / Modal | `QMessageBox.warning(self, 'B2B-Zahlungen', f'Prüfung fehlgeschlagen:\n{exc}')` |
| 987 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 988 | Signal → Handler | `worker.signals.result.connect(on_result)` |
| 989 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_lieferkorrektur_popup_fetch_worker', None))` |
| 998 | Popup / Modal | `dialog.exec()` |
| 1034 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1035 | Signal → Handler | `worker.signals.result.connect(on_done)` |
| 1036 | Signal → Handler | `worker.signals.error.connect(on_error)` |
| 1037 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_lieferkorrektur_popup_apply_worker', None))` |
| 1065 | Popup / Modal | `QMessageBox.information(self, 'START SELECTED', 'Bitte zuerst eine oder mehrere Rechnungen markieren.')` |
| 1132 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1133 | Signal → Handler | `self._start_worker.signals.result.connect(self._on_start_preflight_ready)` |
| 1134 | Signal → Handler | `self._start_worker.signals.error.connect(self._on_start_preflight_error)` |
| 1160 | Popup / Modal | `review.exec()` |
| 1178 | Popup / Modal | `dlg.exec()` |
| 1238 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1239 | Signal → Handler | `self._start_product_worker.signals.result.connect(self._on_start_product_preflight_ready)` |
| 1240 | Signal → Handler | `self._start_product_worker.signals.error.connect(self._on_start_preflight_error)` |
| 1241 | Signal → Handler | `self._start_product_worker.signals.finished.connect(lambda: setattr(self, '_start_product_worker', None))` |
| 1273 | UI / Aktion | `dialog.addButton('30/35/35-Plan speichern', QMessageBox.ButtonRole.ActionRole)` |
| 1274 | UI / Aktion | `dialog.addButton('Kundenlimit bearbeiten', QMessageBox.ButtonRole.ActionRole)` |
| 1275 | UI / Aktion | `dialog.addButton(QMessageBox.StandardButton.Close)` |
| 1276 | Popup / Modal | `dialog.exec()` |
| 1286 | Popup / Modal | `QMessageBox.information(self, 'Zahlungsplan gespeichert', f'{saved} Zahlungsplan/Pläne wurden gespeichert.\nDie eigentlichen sevDesk-Anzahlungs-/Teilrechnungen bitte zunächst manuell erstellen. Fällige Schritte erscheinen danach als B2B-Alarm.')` |
| 1294 | Popup / Modal | `QMessageBox.critical(self, 'Zahlungsplan', f'Plan konnte nicht gespeichert werden:\n{exc}')` |
| 1302 | Popup / Modal | `QMessageBox.warning(self, 'Kundenlimit', 'Für diesen Datensatz ist kein Kundenname verfügbar.')` |
| 1305 | Popup / Modal | `QInputDialog.getDouble(self, 'Kundenlimit', f'Neues Netto-Limit für {customer} (EUR):', current, 0.0, 100000000.0, 2)` |
| 1319 | Popup / Modal | `QMessageBox.critical(self, 'Kundenlimit', f'Limit konnte nicht gespeichert werden:\n{exc}')` |
| 1321 | Popup / Modal | `QMessageBox.information(self, 'Kundenlimit gespeichert', 'Das Limit wurde gespeichert. Bitte START erneut anklicken; die Freigabe wird dann neu geprüft.')` |
| 1357 | Popup / Modal | `QMessageBox.warning(self, 'START', 'START-Preflight ist nicht mehr verfuegbar.')` |
| 1485 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1486 | Signal → Handler | `self._start_exec_worker.signals.result.connect(self._on_start_executed)` |
| 1487 | Signal → Handler | `self._start_exec_worker.signals.error.connect(self._on_start_preflight_error)` |
| 1488 | Signal → Handler | `self._start_exec_worker.signals.finished.connect(lambda: self._set_start_running(False))` |
| 1569 | Popup / Modal | `QMessageBox.information(self, 'START abgeschlossen', '\n'.join(lines))` |
| 1608 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1609 | Signal → Handler | `worker.signals.result.connect(self._on_digital_license_candidates_ready)` |
| 1610 | Signal → Handler | `worker.signals.error.connect(lambda exc: logger.warning('Digital-license reconcile failed: %s', exc))` |
| 1611 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_digital_license_offer_worker', None))` |
| 1620 | Popup / Modal | `QMessageBox.question(self, 'Digitale Lieferung', f"{count} digitale Bestellung{('en' if count != 1 else '')} wurde vorbereitet. Digitale Lieferung jetzt ausfuehren?", QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)` |
| 1644 | Popup / Modal | `QMessageBox.warning(self, 'Fehler', f'Pre-Flight konnte nicht erstellt werden:\n\n{exc}')` |
| 1691 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1692 | Signal → Handler | `self._reprint_worker.signals.result.connect(self._on_reprint_preflight_ready)` |
| 1693 | Signal → Handler | `self._reprint_worker.signals.error.connect(self._on_reprint_error)` |
| 1702 | Popup / Modal | `dlg.exec()` |
| 1715 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 1716 | Signal → Handler | `self._reprint_exec_worker.signals.result.connect(self._on_reprint_executed)` |
| 1717 | Signal → Handler | `self._reprint_exec_worker.signals.error.connect(self._on_reprint_error)` |
| 1732 | Popup / Modal | `QMessageBox.information(self, 'Nachdrucke abgeschlossen', f"Positionen geprüft: {result.decisions_count}\nDruckjobs: {len(result.printed_skus)}\nSKU: {(', '.join(result.printed_skus) if result.printed_skus else 'keine')}\nBestand aktualisiert: {result.stock_updated}" + ('\n\nHinweise:\n…` |
| 1753 | Popup / Modal | `QMessageBox.warning(self, 'Fehler', f'Nachdrucke-Workflow konnte nicht ausgefuehrt werden:\n\n{exc}')` |

### A – view.py

Quelle: `src/xw_office/ui/modules/rechnungen/view.py`.

Direkte interne Abhängigkeiten: `xw_office.core.container`, `xw_office.core.performance_metrics`, `xw_office.core.signals`, `xw_office.core.types`, `xw_office.core.worker`, `xw_office.repositories.customer_aftercare`, `xw_office.repositories.plc_shipment`, `xw_office.services.background_jobs.service`, `xw_office.services.customer_aftercare.redelivery`, `xw_office.services.customer_aftercare.service`, `xw_office.services.daily_business.service`, `xw_office.services.digital_licenses`, `xw_office.services.draft_invoice.service`, `xw_office.services.drucke.service`, `xw_office.services.inventory`, `xw_office.services.invoice_processing.context`, `xw_office.services.invoice_processing.service`, `xw_office.services.mailing.outlook_compose`, `xw_office.services.plc.label_archive`, `xw_office.services.plc.statistics`, `xw_office.services.printer_status.service`, `xw_office.services.printing.label_printer`, `xw_office.services.printing.planned_pdf_printer`, `xw_office.services.printing.print_queue`, `xw_office.services.product_hub.inventory`, `xw_office.services.products.catalog`, `xw_office.services.products.print_decision`, `xw_office.services.secrets.service`, `xw_office.services.sendungen.service`, `xw_office.services.sevdesk.invoice_client`, `xw_office.services.sevdesk.part_client`, `xw_office.services.wix.client`, `xw_office.ui.dialogs.unreleased_title_dialog`, `xw_office.ui.modules.rechnungen.customer_aftercare_manager_dialog`, `xw_office.ui.modules.rechnungen.digital_licenses_dialog`, `xw_office.ui.modules.rechnungen.inventory_alerts_dialog`, `xw_office.ui.modules.rechnungen.offene_drucke_dialog`, `xw_office.ui.modules.rechnungen.offene_sendungen_dialog`, `xw_office.ui.modules.rechnungen.offene_ueberweisungen_dialog`, `xw_office.ui.modules.rechnungen.open_invoice_overview`, `xw_office.ui.modules.rechnungen.plc_evidence_dialog`, `xw_office.ui.modules.rechnungen.plc_label_dialog`, `xw_office.ui.modules.rechnungen.plc_statistics_dialog`, `xw_office.ui.modules.rechnungen.print_dialog`, `xw_office.ui.modules.rechnungen.product_preflight_dialog`, `xw_office.ui.modules.rechnungen.redelivery_dialog`, `xw_office.ui.modules.rechnungen.refunds_dialog`, `xw_office.ui.modules.rechnungen.special_order_dialog`, `xw_office.ui.modules.rechnungen.tagesgeschaeft_view`, `xw_office.ui.widgets.busy_spinner`, `xw_office.ui.widgets.data_table`, `xw_office.ui.widgets.progress_overlay`, `xw_office.ui.widgets.search_bar`, `xw_office.ui.widgets.toolbar`.

**_PrintRunSnapshot** (Z. 161): Datenmodell / Konstanten.
**_RunOutputPrintRequest** (Z. 175): Datenmodell / Konstanten.
**_HintsIconDelegate** (Z. 220): `__init__`:231; `_icon_for_key`:237; `_tinted_icon_for_key`:249; `paint`:275; `sizeHint`:327.
**_InvoiceStatusDelegate** (Z. 334): `paint`:339; `sizeHint`:372.
**_SevdeskDraftActionDelegate** (Z. 379): `_button_geometry`:383; `hit_remove_action`:390; `paint`:394; `sizeHint`:421.
**_ActionsDelegate** (Z. 428): `__init__`:441; `_rendered_icon_for_key`:445; `_layout`:488; `action_at_x`:500; `visible_action_at_x`:508; `_visible_layout`:515; `paint`:526; `sizeHint`:547.
**_FulfillmentDelegate** (Z. 554): `__init__`:566; `_icon`:571; `_layout`:580; `chip_at_x`:592; `paint`:600; `sizeHint`:647.
**_DraftInvoiceDialog** (Z. 654): `__init__`:657; `_invalidate_preview`:705; `wix_order_number`:711; `open_in_sevdesk`:715; `preview_ok`:719; `on_preview_requested`:722; `set_preview_result`:725; `set_preview_loading`:737; `_accept_if_valid`:746.
**_CustomLabelDialog** (Z. 759): `__init__`:760; `_on_print_clicked`:790; `_on_print_result`:819; `_on_print_error`:822; `_on_print_finished`:826.
**_PieceListModel** (Z. 831): `__init__`:844; `set_pieces`:848; `rowCount`:853; `data`:856; `rows`:885; `set_print_enabled`:899; `adjust_quantity`:906; `quantity_for_block`:914; `toggle_selected`:920; `show_print_confirmation`:930.
**_PieceDelegate** (Z. 960): `__init__`:966; `paint`:972; `sizeHint`:1102; `editorEvent`:1107; `_button_rects`:1158; `_checkbox_rect`:1169.
**RechnungenView** (Z. 1263): `__init__`:1266; `_build_ui`:1436; `showEvent`:2088; `hideEvent`:2116; `mousePressEvent`:2123; `_should_clear_selection_for_global_pos`:2133; `_global_pos_inside_widget`:2141; `closeEvent`:2145; `prepare_shutdown`:2149; `request_shutdown`:2153; `shutdown_complete`:2176; `_shutdown_workers`:2179; `set_badge_refresh_managed_externally`:2214; `set_top_actions_managed_externally`:2221; `set_start_workflow_running`:2225; `reload_first_page`:2288; `create_draft_from_wix_order`:2291; `open_custom_label_dialog`:2294; `open_manual_plc_label_dialog`:2297; `open_plc_statistics_dialog`:2300; `open_special_order_dialog`:2303; `open_sendungen_dialog`:2306; `open_drucke_dialog`:2313; `open_digital_licenses_dialog`:2320; `open_ueberweisungen_dialog`:2327; `open_lieferkorrekturen_dialog`:2332; `open_queue_dialog`:2336; `show_start_summary`:2348; `_stop_mollie_worker`:2357; `resizeEvent`:2364; `_start_search_index_sync`:2369; `_reset_search`:2392; `_on_search`:2396; `_on_printer_status`:2422; `_initialize_printer_status`:2429; `_reload_first_page`:2433; `_load_more`:2457; `_start_load`:2465; `_blank_hint_patch`:2536; `_prepare_rows_for_hint_prefetch`:2544; `_current_sevdesk_token`:2556; `_has_sevdesk_token`:2560; `_on_load_result`:2563; `_apply_load_result_data`:2608; `_sort_rows_by_actuality`:2684; `_summary_actuality_key`:2710; `_schedule_open_overview_refresh`:2722; `_schedule_post_load_prefetch`:2733; `_submit_side_job`:2753; `_update_load_more_button`:2769; `_apply_table_column_layout`:2796; `_refresh_mollie_alert_count`:2815; `_create_mollie_badge_worker`:2824; `_on_mollie_badge_result`:2846; `update_mollie_alert_count`:2862; `update_sendungen_alert_count`:2870; `update_drucke_alert_count`:2878; `update_digital_licenses_alert_count`:2886; `_on_mollie_alert_clicked`:2896; `_on_sendungen_alert_clicked`:2900; `_on_drucke_alert_clicked`:2903; `_on_digital_licenses_alert_clicked`:2908; `_refresh_inventory_alert_count`:2913; `_on_inventory_alert_count`:2930; `_on_inventory_alert_error`:2941; `_on_inventory_alert_finished`:2947; `_on_inventory_alert_clicked`:2950; `_on_special_order_clicked`:2959; `_selected_summary`:2963; `selected_summaries`:2969; `_require_selected_invoice`:2977; `_invoice_search_suggestions`:2988; `_rebuild_search_index`:3019; `_on_load_error`:3037; `_on_load_finished`:3054; `_restore_loaded_invoice_list`:3066; `_on_search_result`:3079; `_on_search_error`:3119; `_on_search_finished`:3128; `_refresh_open_invoice_overview`:3131; `_start_open_invoice_overview`:3201; `_can_run_open_overview_job`:3244; `_create_open_overview_worker`:3251; `_on_open_overview_result`:3295; `_merge_open_overview_batches`:3316; `_on_open_overview_error`:3379; `_on_open_overview_finished`:3389; `_plan_open_print_overview`:3399; `_apply_open_invoice_overview`:3434; `_open_product_preparation_key`:3462; `_ensure_open_product_preparation`:3471; `_on_open_product_preparation_result`:3507; `_on_open_product_preparation_error`:3521; `_on_open_product_preparation_finished`:3534; `mark_print_products_last_run`:3541; `_print_tab_label`:3575; `_print_tab_tooltip`:3582; `_rebuild_print_product_tabs`:3592; `_on_print_products_tab_changed`:3615; `_render_active_print_tab`:3629; `_merge_session_print_products`:3673; `_merge_session_unreleased`:3690; `_merge_session_buyer_notes`:3701; `_unreleased_session_key`:3713; `_print_product_session_key`:3721; `_print_product_display_overview`:3729; `_buyer_note_session_key`:3751; `_snapshot_payload`:3758; `_persist_print_run_history`:3797; `_persist_last_start_overview`:3810; `_restore_last_start_overview`:3843; `_restore_legacy_start_overview`:3944; `_clear_unreleased_rows`:4017; `_set_unreleased_message`:4024; `_build_unreleased_row`:4031; `_render_unreleased_assignments`:4074; `_clear_buyer_note_rows`:4122; `_set_buyer_notes_message`:4129; `_build_buyer_note_row`:4135; `_render_buyer_notes`:4163; `_clear_open_print_product_rows`:4188; `_set_open_products_message`:4195; `_render_open_print_products`:4202; `_displayed_print_products`:4242; `_open_product_check_key`:4249; `_selected_displayed_print_products`:4257; `_on_open_product_check_changed`:4267; `_open_product_quantity`:4271; `_open_product_with_quantity`:4278; `_on_open_product_quantity_changed`:4296; `_set_open_products_feedback`:4316; `_update_print_all_products_button`:4320; `_active_run_output_ids`:4328; `_update_print_run_output_buttons`:4336; `_on_print_run_invoices_clicked`:4352; `_on_print_run_labels_clicked`:4355; `_start_run_output_print`:4358; `_start_next_run_output_print`:4391; `_on_print_run_output_result`:4413; `_on_print_run_output_error`:4434; `_on_print_run_output_finished`:4441; `_print_all_products_key`:4447; `_on_print_all_open_products_clicked`:4458; `_on_print_all_open_products_result`:4595; `_build_open_print_product_row`:4599; `_open_product_description`:4751; `_plain_open_print_product_line`:4787; `_open_print_product_ready`:4802; `_resolve_open_print_product_ready`:4805; `_piece_block_from_open_product`:4819; `_basic_piece_block_from_open_product`:4824; `_resolve_piece_block_from_open_product`:4838; `_on_open_product_manage_clicked`:4876; `_on_open_product_print_clicked`:4902; `_show_toolbutton_print_confirmation`:4929; `_format_open_print_products`:4959; `_warm_wix_context_for_summaries`:4996; `_start_next_wix_warm_batch`:5028; `_launch_next_wix_warm_batch`:5039; `_can_run_wix_warm_job`:5068; `_run_wix_warm_batch`:5077; `_on_wix_warm_result`:5131; `_on_wix_warm_error`:5165; `_on_wix_warm_finished`:5168; `_restart_hint_prefetch`:5176; `_prioritize_summaries_for_background_prefetch`:5199; `_prioritize_hint_prefetch_for_summary`:5230; `_start_next_hint_prefetch`:5248; `_create_next_hint_prefetch_worker`:5255; `_on_hint_prefetch_result`:5284; `_on_hint_prefetch_error`:5298; `_on_hint_prefetch_finished`:5301; `_apply_hint_patch_to_visible_rows`:5306; `_set_detail_actions_busy`:5317; `_clear_detail_actions_busy`:5341; `_apply_fulfillment_flags_to_row`:5345; `_fulfillment_tooltip`:5369; `_on_print_clicked`:5384; `_on_print_label_clicked`:5410; `_on_custom_label_clicked`:5444; `_on_manual_plc_label_clicked`:5455; `_on_plc_statistics_clicked`:5458; `_on_print_plc_selected`:5461; `_cached_customer_email_for_summary`:5464; `_open_plc_post_popup`:5486; `_open_customs_declaration_dialog`:5602; `_on_print_music_clicked`:5620; `_on_send_invoice_clicked`:5715; `_on_table_selection_changed`:5751; `_on_table_clicked`:5758; `_select_visible_table_row`:5764; `eventFilter`:5788; `_run_fulfillment_chip_action`:5893; `_on_fulfillment_step_result`:5941; `_on_fulfillment_step_error`:5953; `_on_fulfillment_step_finished`:5960; `_run_row_action`:5964; `_open_redelivery_popup`:5983; `_show_redelivery_dialog`:6001; `_on_redelivery_prepare_error`:6017; `_apply_redelivery_outcome`:6021; `_on_redelivery_applied`:6052; `_on_redelivery_apply_error`:6060; `_run_selected_row_action`:6064; `_confirm_delete_draft`:6069; `_on_delete_draft_result`:6101; `_on_delete_draft_error`:6108; `_on_delete_draft_finished`:6115; `_resolve_plc_archive_path_for_summary`:6119; `_resolve_plc_archive_paths_for_summary`:6137; `_resolve_plc_customs_archive_path_for_summary`:6151; `_resolve_packing_list_archive_paths_for_summary`:6163; `_packing_list_menu_label`:6177; `_populate_packing_list_menus`:6184; `_populate_multi_shipment_menu`:6203; `_open_plc_evidence`:6222; `_open_archived_packing_list`:6237; `_reprint_archived_packing_list`:6241; `_prime_plc_archive_index`:6258; `_on_plc_archive_index_ready`:6282; `_on_plc_archive_index_error`:6293; `_on_open_plc_label_clicked`:6296; `_open_archived_plc_label`:6302; `_on_open_plc_customs_clicked`:6306; `_on_open_invoice_pdf_clicked`:6313; `_on_invoice_pdf_preview_result`:6335; `_on_invoice_pdf_preview_error`:6345; `_on_invoice_pdf_preview_finished`:6352; `_on_open_sevdesk_invoice_clicked`:6356; `_sevdesk_invoice_url`:6368; `_open_customer_mail`:6376; `_on_customer_mail_ready`:6424; `_on_customer_mail_error`:6447; `_open_customer_mail_outlook`:6450; `_outlook_sender_email`:6461; `_customer_mail_subject`:6470; `_customer_email_from_loaded_context`:6477; `_clean_email_value`:6501; `_open_wix_download_links`:6507; `_on_wix_download_links_ready`:6530; `_on_wix_download_links_error`:6543; `_on_wix_download_links_finished`:6547; `_open_refund_dialog`:6550; `_open_refunds_dialog`:6557; `_refresh_detail_for_selection`:6560; `_populate_detail_for_summary`:6595; `_hydrate_detail_for_selection`:6624; `_load_sevdesk_context`:6663; `_on_sevdesk_context_finished`:6697; `_on_sevdesk_context_loaded`:6703; `_on_sevdesk_context_error`:6755; `_reset_detail`:6760; `_close_invoice_detail`:6785; `_update_action_state`:6792; `_reset_wix_meta`:6814; `_prefill_detail_from_invoice_cache`:6823; `_apply_invoice_detail_context`:6850; `_apply_cached_wix_context`:6882; `_piece_blocks_from_cached_wix_items`:6917; `_load_wix_context`:6941; `_resolve_wix_order_summary`:7042; `_fetch_wix_order_line_items`:7056; `_on_wix_context_loaded`:7069; `_on_wix_context_error`:7118; `_on_wix_context_finished`:7141; `_load_phase_label`:7166; `_get_cached_wix_context`:7173; `_put_cached_wix_context`:7189; `_load_wix_meta`:7207; `_on_wix_meta_loaded`:7210; `_on_wix_meta_error`:7285; `_update_plc_controls`:7290; `_normalize_shipping_lines`:7343; `_set_shipping_editor_lines`:7351; `_current_shipping_lines`:7359; `_should_replace_shipping_lines`:7363; `_address_quality_score`:7373; `_adjust_shipping_editor_height`:7391; `_on_shipping_editor_changed`:7398; `_on_direct_label_print_result`:7415; `_on_direct_label_print_error`:7423; `_on_direct_invoice_print_result`:7430; `_on_direct_invoice_print_error`:7438; `_on_send_invoice_result`:7445; `_on_send_invoice_error`:7457; `_on_send_invoice_finished`:7464; `_on_create_draft_clicked`:7468; `_on_create_draft_result`:7496; `_on_create_draft_error`:7532; `_on_create_draft_finished`:7540; `_on_draft_product_plan_ready`:7543; `_on_draft_product_plan_finished`:7562; `_run_product_preflight_dialogs`:7565; `_run_draft_preview`:7575; `_on_draft_preview_finished`:7601; `_on_draft_preview_result`:7605; `_reset_stuecke`:7645; `_load_stuecke`:7659; `_clarify_unreleased_piece`:7662; `_create_unreleased_product_from_alias`:7715; `_on_add_unreleased_from_item`:7806; `clarify_unreleased_start_issues`:7813; `_split_unreleased_piece`:7841; `_on_stuecke_loaded`:7864; `_on_unreleased_catalog_warmed`:8007; `_on_piece_configured`:8019; `_on_piece_config_error`:8042; `_on_piece_config_finished`:8049; `_on_product_print_clicked`:8053; `_on_product_print_result`:8180; `_on_product_print_error`:8220; `_on_product_print_finished`:8227; `_on_individual_product_print_finished`:8233; `_default_piece_print_qty`:8240; `_set_piece_print_controls_enabled`:8243; `_on_product_manage_clicked`:8251; `_piece_header_text`:8266; `_piece_detail_lines`:8271; `_piece_stock_text`:8286; `_piece_stock_color`:8306; `_describe_piece_print_config`:8318; `_on_stuecke_error`:8335

| Zeile | Typ | Deklaration / Aufruf |
| ---: | --- | --- |
| 672 | UI / Aktion | `QLineEdit(self)` |
| 677 | UI / Aktion | `QPushButton('Vorschau laden')` |
| 681 | UI / Aktion | `QPlainTextEdit(self)` |
| 687 | UI / Aktion | `QCheckBox('Nach Erstellung in sevDesk öffnen', self)` |
| 696 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Ok &#124; QDialogButtonBox.StandardButton.Cancel, parent=self)` |
| 700 | Signal → Handler | `buttons.accepted.connect(self._accept_if_valid)` |
| 701 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 703 | Signal → Handler | `self._order_number.textChanged.connect(self._invalidate_preview)` |
| 723 | Signal → Handler | `self._btn_preview.clicked.connect(callback)` |
| 773 | UI / Aktion | `QPlainTextEdit(self)` |
| 783 | UI / Aktion | `QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)` |
| 784 | UI / Aktion | `QPushButton('PRINT')` |
| 785 | UI / Aktion | `buttons.addButton(self._btn_print, QDialogButtonBox.ButtonRole.AcceptRole)` |
| 786 | Signal → Handler | `buttons.rejected.connect(self.reject)` |
| 787 | Signal → Handler | `self._btn_print.clicked.connect(self._on_print_clicked)` |
| 795 | Popup / Modal | `QMessageBox.information(self, 'CUSTOM-LABEL', 'Bitte eine Lieferadresse mit mindestens zwei Zeilen eingeben.')` |
| 813 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 814 | Signal → Handler | `self._worker.signals.result.connect(self._on_print_result)` |
| 815 | Signal → Handler | `self._worker.signals.error.connect(self._on_print_error)` |
| 816 | Signal → Handler | `self._worker.signals.finished.connect(self._on_print_finished)` |
| 824 | Popup / Modal | `QMessageBox.warning(self, 'CUSTOM-LABEL', f'Label konnte nicht gedruckt werden:\n\n{exc}')` |
| 952 | Timer | `QTimer(self)` |
| 953 | Timer | `timer.setSingleShot(True)` |
| 954 | Signal → Handler | `timer.timeout.connect(clear_confirmation)` |
| 955 | Signal → Handler | `timer.timeout.connect(timer.deleteLater)` |
| 963 | Signaldefinition | `Signal(object, int)` |
| 964 | Signaldefinition | `Signal(object)` |
| 1219 | Timer | `QTimer(self)` |
| 1220 | Timer | `self._inventory_alert_timer.setInterval(60000)` |
| 1221 | Signal → Handler | `self._inventory_alert_timer.timeout.connect(self._refresh_inventory_alert_count)` |
| 1248 | Timer | `QTimer(self)` |
| 1249 | Timer | `self._wix_warm_timer.setSingleShot(True)` |
| 1250 | Signal → Handler | `self._wix_warm_timer.timeout.connect(self._launch_next_wix_warm_batch)` |
| 1266 | Timer | `QTimer(self)` |
| 1267 | Timer | `self._mollie_timer.setInterval(120000)` |
| 1268 | Signal → Handler | `self._mollie_timer.timeout.connect(self._refresh_mollie_alert_count)` |
| 1278 | Signal → Handler | `self._piece_delegate.print_clicked.connect(self._on_product_print_clicked)` |
| 1279 | Signal → Handler | `self._piece_delegate.manage_clicked.connect(self._on_product_manage_clicked)` |
| 1332 | Timer | `QTimer.singleShot(0, self._restore_last_start_overview)` |
| 1340 | UI / Aktion | `self._toolbar.add_button('refresh', 'Aktualisieren', tooltip='Erste Seite neu laden')` |
| 1345 | Signal → Handler | `refresh.clicked.connect(self._reload_first_page)` |
| 1346 | UI / Aktion | `self._toolbar.add_button('draft', 'Rechnungs-Entwurf', tooltip='Neuen sevDesk-Rechnungsentwurf aus Wix-Order-Nr erstellen')` |
| 1351 | Signal → Handler | `self._btn_draft.clicked.connect(self._on_create_draft_clicked)` |
| 1352 | UI / Aktion | `self._toolbar.add_button('shipping', 'VERSAND', tooltip='Offene Sendungen und Nachlieferungen bearbeiten')` |
| 1357 | Signal → Handler | `self._btn_shipping.clicked.connect(self.open_sendungen_dialog)` |
| 1358 | UI / Aktion | `self._toolbar.add_button('label', 'CUSTOM-LABEL', tooltip='Freie Lieferadresse eingeben und direkt als Label drucken')` |
| 1363 | Signal → Handler | `self._btn_custom_label.clicked.connect(self._on_custom_label_clicked)` |
| 1364 | UI / Aktion | `self._toolbar.add_button('manual_plc_label', 'PLC-LABEL', tooltip='PLC-Label mit manuell eingegebener Empfängeradresse erstellen')` |
| 1369 | Signal → Handler | `self._btn_manual_plc_label.clicked.connect(self._on_manual_plc_label_clicked)` |
| 1370 | UI / Aktion | `self._toolbar.add_button('plc_statistics', 'PLC-ÜBERSICHT', tooltip='Wochen-, Monats- und Jahresstatistik der gedruckten PLC-Labels')` |
| 1375 | Signal → Handler | `self._btn_plc_statistics.clicked.connect(self._on_plc_statistics_clicked)` |
| 1376 | UI / Aktion | `self._toolbar.add_button('special_order', 'Sonderauftrag', tooltip='Wix Payment Link fuer Sonderauftrag erstellen')` |
| 1381 | Signal → Handler | `self._btn_special_order.clicked.connect(self._on_special_order_clicked)` |
| 1383 | UI / Aktion | `self._toolbar.add_button('sendungen_alert', '✉ OFFENE SENDUNGEN', tooltip='Offene Versand-Mails anzeigen')` |
| 1395 | Signal → Handler | `self._btn_sendungen_alert.clicked.connect(self._on_sendungen_alert_clicked)` |
| 1397 | UI / Aktion | `self._toolbar.add_button('drucke_alert', '🖨 OPEN PRINTS', tooltip='Offene Druckaufträge anzeigen')` |
| 1406 | Signal → Handler | `self._btn_drucke_alert.clicked.connect(self._on_drucke_alert_clicked)` |
| 1408 | UI / Aktion | `self._toolbar.add_button('digital_licenses_alert', 'EXTERNE BESTELLUNG', tooltip='Bezahlte externe digitale Bestellungen anzeigen')` |
| 1420 | Signal → Handler | `self._btn_digital_licenses_alert.clicked.connect(self._on_digital_licenses_alert_clicked)` |
| 1422 | UI / Aktion | `self._toolbar.add_button('mollie_alert', '💳 MOLLIE AUTH', tooltip='Offene Mollie-Authorisierungen anzeigen')` |
| 1434 | Signal → Handler | `self._btn_mollie_alert.clicked.connect(self._on_mollie_alert_clicked)` |
| 1436 | UI / Aktion | `self._toolbar.add_button('inventory_alert', 'LAGERALARME', tooltip='Aktive Lageralarme, Alarmbestand und Tasks anzeigen')` |
| 1445 | Signal → Handler | `self._btn_inventory_alert.clicked.connect(self._on_inventory_alert_clicked)` |
| 1453 | Signal → Handler | `self._search_banner.reset_requested.connect(self._reset_search)` |
| 1483 | Signal → Handler | `self._table.clicked.connect(self._on_table_clicked)` |
| 1498 | UI / Aktion | `QPushButton('Weitere Rechnungen laden')` |
| 1502 | Signal → Handler | `self._btn_more.clicked.connect(self._load_more)` |
| 1542 | UI / Aktion | `QPushButton('PRINT SELECTED PRODUCTS')` |
| 1547 | Signal → Handler | `self._btn_print_all_products.clicked.connect(self._on_print_all_open_products_clicked)` |
| 1548 | UI / Aktion | `QPushButton('PRINT INVOICES')` |
| 1554 | Signal → Handler | `self._btn_print_run_invoices.clicked.connect(self._on_print_run_invoices_clicked)` |
| 1555 | UI / Aktion | `QPushButton('PRINT LABELS')` |
| 1561 | Signal → Handler | `self._btn_print_run_labels.clicked.connect(self._on_print_run_labels_clicked)` |
| 1625 | UI / Aktion | `QTabWidget()` |
| 1627 | Signal → Handler | `self._print_products_tabs.currentChanged.connect(self._on_print_products_tab_changed)` |
| 1636 | UI / Aktion | `self._print_products_tabs.addTab(current_page, 'AKTUELL')` |
| 1647 | UI / Aktion | `QToolButton()` |
| 1658 | Signal → Handler | `self._btn_close_detail.clicked.connect(self._close_invoice_detail)` |
| 1717 | Signal → Handler | `self._gb_info.toggled.connect(self._info_content.setVisible)` |
| 1731 | UI / Aktion | `QPlainTextEdit()` |
| 1737 | Signal → Handler | `self._shipping_editor.textChanged.connect(self._on_shipping_editor_changed)` |
| 1782 | UI / Aktion | `QAction('Rechnung', self)` |
| 1784 | Signal → Handler | `self._print_invoice_action.triggered.connect(self._on_print_clicked)` |
| 1785 | UI / Aktion | `QAction('Versandlabel', self)` |
| 1787 | Signal → Handler | `self._print_label_action.triggered.connect(self._on_print_label_clicked)` |
| 1788 | UI / Aktion | `QAction('PLC-Label', self)` |
| 1790 | Signal → Handler | `self._print_plc_action.triggered.connect(self._on_print_plc_selected)` |
| 1791 | UI / Aktion | `QMenu('Archivierte Packlisten', self)` |
| 1793 | Signal → Handler | `self._print_packing_lists_menu.aboutToShow.connect(self._populate_packing_list_menus)` |
| 1794 | UI / Aktion | `QAction('Noten / Produkte', self)` |
| 1796 | Signal → Handler | `self._print_music_action.triggered.connect(self._on_print_music_clicked)` |
| 1797 | UI / Aktion | `QMenu(self)` |
| 1805 | UI / Aktion | `self._print_menu.addAction(self._print_music_action)` |
| 1814 | UI / Aktion | `QToolButton()` |
| 1826 | UI / Aktion | `QAction('Rechnungs-PDF', self)` |
| 1828 | Signal → Handler | `self._view_invoice_action.triggered.connect(self._on_open_invoice_pdf_clicked)` |
| 1829 | UI / Aktion | `QAction('PLC-Label', self)` |
| 1831 | Signal → Handler | `self._view_plc_action.triggered.connect(self._on_open_plc_label_clicked)` |
| 1832 | UI / Aktion | `QAction('Zolldokument', self)` |
| 1834 | Signal → Handler | `self._view_customs_action.triggered.connect(self._on_open_plc_customs_clicked)` |
| 1835 | UI / Aktion | `QMenu('Archivierte Packlisten', self)` |
| 1837 | Signal → Handler | `self._view_packing_lists_menu.aboutToShow.connect(self._populate_packing_list_menus)` |
| 1838 | UI / Aktion | `QAction('Paketinhalt & Tracking', self)` |
| 1839 | Signal → Handler | `self._view_plc_evidence_action.triggered.connect(self._open_plc_evidence)` |
| 1840 | UI / Aktion | `QMenu(self)` |
| 1847 | UI / Aktion | `self._view_menu.addAction(self._view_plc_evidence_action)` |
| 1857 | UI / Aktion | `QToolButton()` |
| 1869 | UI / Aktion | `QPushButton()` |
| 1875 | Signal → Handler | `self._btn_open_sevdesk_invoice.clicked.connect(self._on_open_sevdesk_invoice_clicked)` |
| 1880 | UI / Aktion | `QPushButton(' WIX ORDER')` |
| 1886 | Signal → Handler | `self._btn_open_wix_order.clicked.connect(lambda: self._run_selected_row_action('wix'))` |
| 1890 | UI / Aktion | `QPushButton('✉️ Kundenmail')` |
| 1893 | Signal → Handler | `self._btn_customer_mail.clicked.connect(lambda: self._run_selected_row_action('mail'))` |
| 1897 | UI / Aktion | `QPushButton('✉️ Rechnung')` |
| 1901 | Signal → Handler | `self._btn_send_invoice.clicked.connect(self._on_send_invoice_clicked)` |
| 1905 | UI / Aktion | `QPushButton('Stornos & Gutschriften')` |
| 1908 | Signal → Handler | `self._btn_refunds.clicked.connect(self._open_refunds_dialog)` |
| 1911 | UI / Aktion | `QMenu(self)` |
| 1912 | UI / Aktion | `QMenu('PLC-Labels', self._multi_shipment_menu)` |
| 1913 | UI / Aktion | `QMenu('Packlisten', self._multi_shipment_menu)` |
| 1916 | Signal → Handler | `self._multi_shipment_menu.aboutToShow.connect(self._populate_multi_shipment_menu)` |
| 1917 | UI / Aktion | `QToolButton()` |
| 1935 | UI / Aktion | `QListView(self._gb_stuecke)` |
| 1977 | Signal → Handler | `self._search.search_changed.connect(self._on_search)` |
| 1980 | Signal → Handler | `sel.selectionChanged.connect(self._on_table_selection_changed)` |
| 1983 | Signal → Handler | `signals.printer_status_changed.connect(self._on_printer_status)` |
| 1991 | Timer | `QTimer.singleShot(0, self._initialize_printer_status)` |
| 1997 | Timer | `QTimer.singleShot(4000, self._start_search_index_sync)` |
| 2180 | Timer | `QTimer.singleShot(0, lambda s=summary, token=seq: self._hydrate_detail_for_selection(s, token))` |
| 2202 | Popup / Modal | `dlg.exec()` |
| 2209 | Popup / Modal | `dlg.exec()` |
| 2216 | Popup / Modal | `dlg.exec()` |
| 2223 | Popup / Modal | `dlg.exec()` |
| 2228 | Popup / Modal | `dlg.exec()` |
| 2242 | Popup / Modal | `dlg.exec()` |
| 2279 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 2280 | Signal → Handler | `self._index_sync_worker.signals.error.connect(lambda exc: logger.warning('Invoice search index sync failed: %s', exc))` |
| 2283 | Signal → Handler | `self._index_sync_worker.signals.finished.connect(lambda: setattr(self, '_index_sync_worker', None))` |
| 2312 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 2313 | Signal → Handler | `self._search_worker.signals.result.connect(self._on_search_result)` |
| 2314 | Signal → Handler | `self._search_worker.signals.error.connect(self._on_search_error)` |
| 2315 | Signal → Handler | `self._search_worker.signals.finished.connect(self._on_search_finished)` |
| 2417 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 2418 | Signal → Handler | `self._worker.signals.result.connect(self._on_load_result)` |
| 2419 | Signal → Handler | `self._worker.signals.error.connect(self._on_load_error)` |
| 2420 | Signal → Handler | `self._worker.signals.finished.connect(self._on_load_finished)` |
| 2619 | Timer | `QTimer.singleShot(0, run_refresh)` |
| 2639 | Timer | `QTimer.singleShot(2500, run_prefetch)` |
| 2649 | Hintergrundarbeit | `self._background_jobs.submit(queue=_SIDE_JOB_QUEUE, priority=priority, coalesce_key=coalesce_key, start_fn=start_fn, can_start=can_start)` |
| 2704 | Hintergrundarbeit | `self._background_jobs.submit(queue='badge-refresh', priority=20, coalesce_key='rechnungen-mollie-badges', start_fn=self._create_mollie_badge_worker, can_start=lambda: self._mollie_badge_worker is None or not self._mollie_badge_worker.isRunning())` |
| 2729 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 2730 | Signal → Handler | `self._mollie_badge_worker.signals.result.connect(self._on_mollie_badge_result)` |
| 2731 | Signal → Handler | `self._mollie_badge_worker.signals.finished.connect(lambda: setattr(self, '_mollie_badge_worker', None))` |
| 2793 | Popup / Modal | `dlg.exec()` |
| 2798 | Popup / Modal | `dlg.exec()` |
| 2811 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 2813 | Signal → Handler | `worker.signals.result.connect(self._on_inventory_alert_count)` |
| 2814 | Signal → Handler | `worker.signals.error.connect(self._on_inventory_alert_error)` |
| 2815 | Signal → Handler | `worker.signals.finished.connect(self._on_inventory_alert_finished)` |
| 2842 | Popup / Modal | `QMessageBox.warning(self, 'Lageralarme', str(exc))` |
| 2844 | Popup / Modal | `dlg.exec()` |
| 2849 | Popup / Modal | `dlg.exec()` |
| 2869 | Popup / Modal | `QMessageBox.information(self, 'Aktion', 'Bitte zuerst eine Rechnung in der Liste auswählen.')` |
| 2935 | Popup / Modal | `QMessageBox.warning(self, 'Fehler', f'Rechnungen konnten nicht geladen werden:\n\n{exc}')` |
| 3010 | Popup / Modal | `QMessageBox.warning(self, 'Suche', f'Rechnungssuche fehlgeschlagen:\n\n{exc}')` |
| 3177 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 3178 | Signal → Handler | `self._open_overview_worker.signals.result.connect(self._on_open_overview_result)` |
| 3179 | Signal → Handler | `self._open_overview_worker.signals.error.connect(self._on_open_overview_error)` |
| 3180 | Signal → Handler | `self._open_overview_worker.signals.finished.connect(self._on_open_overview_finished)` |
| 3409 | UI / Aktion | `tabs.addTab(page, '')` |
| 4174 | Popup / Modal | `QMessageBox.question(self, f"PRINT {('LABELS' if labels else 'INVOICES')}", f'{len(invoice_ids)} {output_label} dieses START-Laufs gesammelt drucken?', QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)` |
| 4211 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 4212 | Signal → Handler | `self._run_output_worker.signals.result.connect(self._on_print_run_output_result)` |
| 4213 | Signal → Handler | `self._run_output_worker.signals.error.connect(self._on_print_run_output_error)` |
| 4214 | Signal → Handler | `self._run_output_worker.signals.finished.connect(self._on_print_run_output_finished)` |
| 4233 | Popup / Modal | `QMessageBox.warning(self, f"PRINT {('LABELS' if labels else 'INVOICES')}", f'{message}\n\nFehlgeschlagen:\n{details}')` |
| 4240 | Popup / Modal | `QMessageBox.warning(self, 'Sammeldruck', f'Sammeldruck konnte nicht ausgefuehrt werden:\n\n{exc}')` |
| 4268 | Popup / Modal | `QMessageBox.information(self, 'PRINT SELECTED PRODUCTS', 'Keine aktivierten Print-Produkte in der aktuellen Liste gefunden.')` |
| 4275 | Popup / Modal | `QMessageBox.question(self, 'PRINT HISTORICAL RUN', 'Diese Produkte stammen aus einem abgeschlossenen Lauf.\n\nErneut drucken?', QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)` |
| 4286 | Popup / Modal | `QMessageBox.question(self, 'PRINT SELECTED PRODUCTS', 'Produkte bereits gedruckt.\n\nErneut drucken?', QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)` |
| 4372 | Hintergrundarbeit | `BackgroundWorker(worker_job)` |
| 4373 | Signal → Handler | `self._product_print_worker.signals.result.connect(self._on_product_print_result)` |
| 4374 | Signal → Handler | `self._product_print_worker.signals.result.connect(self._on_print_all_open_products_result)` |
| 4375 | Signal → Handler | `self._product_print_worker.signals.error.connect(self._on_product_print_error)` |
| 4376 | Signal → Handler | `self._product_print_worker.signals.finished.connect(self._on_product_print_finished)` |
| 4393 | UI / Aktion | `QCheckBox()` |
| 4398 | Signal → Handler | `checkbox.stateChanged.connect(lambda state, aggregate=item: self._on_open_product_check_changed(aggregate, state == Qt.CheckState.Checked.value))` |
| 4406 | UI / Aktion | `QSpinBox()` |
| 4414 | Signal → Handler | `qty_input.valueChanged.connect(lambda value, aggregate=item: self._on_open_product_quantity_changed(aggregate, value))` |
| 4474 | UI / Aktion | `QPushButton('+')` |
| 4495 | Signal → Handler | `add_unreleased_btn.clicked.connect(lambda _checked=False, aggregate=item: self._on_add_unreleased_from_item(aggregate))` |
| 4500 | UI / Aktion | `QToolButton()` |
| 4513 | Signal → Handler | `action.customContextMenuRequested.connect(lambda _pos, aggregate=item: self._on_open_product_manage_clicked(aggregate))` |
| 4522 | Signal → Handler | `action.clicked.connect(lambda _checked=False, aggregate=item, button=action: self._on_open_product_print_clicked(aggregate, button))` |
| 4531 | Signal → Handler | `action.clicked.connect(lambda _checked=False, aggregate=item: self._on_open_product_manage_clicked(aggregate))` |
| 4728 | Timer | `QTimer.singleShot(4000, restore)` |
| 4822 | Hintergrundarbeit | `self._background_jobs.submit_callable(queue='network-background', priority=_PRIORITY_WIX_WARMUP, key='wix-warmup', fn=lambda token, batch=tuple(refs): self._run_wix_warm_batch(batch, token), on_result=self._on_wix_warm_result, on_error=self._on_wix_warm_error, on_finished=self._on_wix_w…` |
| 5036 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5037 | Signal → Handler | `self._hint_worker.signals.result.connect(self._on_hint_prefetch_result)` |
| 5038 | Signal → Handler | `self._hint_worker.signals.error.connect(self._on_hint_prefetch_error)` |
| 5039 | Signal → Handler | `self._hint_worker.signals.finished.connect(self._on_hint_prefetch_finished)` |
| 5157 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5158 | Signal → Handler | `self._fulfillment_step_worker.signals.result.connect(self._on_direct_invoice_print_result)` |
| 5159 | Signal → Handler | `self._fulfillment_step_worker.signals.error.connect(self._on_direct_invoice_print_error)` |
| 5160 | Signal → Handler | `self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)` |
| 5171 | Popup / Modal | `QMessageBox.information(self, 'Labeldruck', 'Bitte zuerst eine vollständige Lieferadresse mit mindestens zwei Zeilen eingeben.')` |
| 5191 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5192 | Signal → Handler | `self._fulfillment_step_worker.signals.result.connect(self._on_direct_label_print_result)` |
| 5193 | Signal → Handler | `self._fulfillment_step_worker.signals.error.connect(self._on_direct_label_print_error)` |
| 5194 | Signal → Handler | `self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)` |
| 5206 | Popup / Modal | `dlg.exec()` |
| 5209 | Popup / Modal | `PlcLabelPrintDialog(self._container, None, self).exec()` |
| 5212 | Popup / Modal | `PlcStatisticsDialog(self._container.resolve(PlcStatisticsService), self).exec()` |
| 5270 | UI / Aktion | `box.addButton(reprint_label, QMessageBox.ButtonRole.AcceptRole)` |
| 5271 | UI / Aktion | `box.addButton('Label-PDF öffnen', QMessageBox.ButtonRole.ActionRole)` |
| 5275 | UI / Aktion | `box.addButton('Zoll-Original öffnen', QMessageBox.ButtonRole.ActionRole)` |
| 5277 | UI / Aktion | `box.addButton('Zoll-A5 öffnen', QMessageBox.ButtonRole.ActionRole)` |
| 5281 | UI / Aktion | `box.addButton('Neues Label erstellen', QMessageBox.ButtonRole.ActionRole)` |
| 5282 | UI / Aktion | `box.addButton('Abbrechen', QMessageBox.ButtonRole.RejectRole)` |
| 5284 | Popup / Modal | `box.exec()` |
| 5302 | Popup / Modal | `QMessageBox.warning(self, 'PLC-Nachdruck', f'Der Nachdruck konnte nicht vollständig eingereiht werden. Die archivierten PDFs bleiben erhalten.\n\n{exc}')` |
| 5312 | Popup / Modal | `QMessageBox.information(self, 'PLC-Nachdruck', f'Archivierter Nachdruck eingereiht: {job_text}')` |
| 5347 | Popup / Modal | `dlg.exec()` |
| 5370 | Popup / Modal | `dlg.exec()` |
| 5401 | Popup / Modal | `QMessageBox.information(self, 'Noten drucken', message)` |
| 5441 | Hintergrundarbeit | `BackgroundWorker(worker_job)` |
| 5442 | Signal → Handler | `self._product_print_worker.signals.result.connect(self._on_product_print_result)` |
| 5443 | Signal → Handler | `self._product_print_worker.signals.error.connect(self._on_product_print_error)` |
| 5444 | Signal → Handler | `self._product_print_worker.signals.finished.connect(self._on_product_print_finished)` |
| 5453 | Popup / Modal | `QMessageBox.question(self, 'Rechnung senden', f'Rechnung {summary.invoice_number or summary.id} wirklich an den Kunden senden?\n\nDer Versand wird danach sofort gestartet.', QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)` |
| 5477 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5478 | Signal → Handler | `self._invoice_mail_worker.signals.result.connect(self._on_send_invoice_result)` |
| 5479 | Signal → Handler | `self._invoice_mail_worker.signals.error.connect(self._on_send_invoice_error)` |
| 5480 | Signal → Handler | `self._invoice_mail_worker.signals.finished.connect(self._on_send_invoice_finished)` |
| 5664 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5665 | Signal → Handler | `self._fulfillment_step_worker.signals.result.connect(self._on_fulfillment_step_result)` |
| 5666 | Signal → Handler | `self._fulfillment_step_worker.signals.error.connect(self._on_fulfillment_step_error)` |
| 5667 | Signal → Handler | `self._fulfillment_step_worker.signals.finished.connect(self._on_fulfillment_step_finished)` |
| 5676 | Popup / Modal | `QMessageBox.information(self, 'Fulfillment aktualisiert', f"Rechnung {invoice}: Schritt '{chip}' wurde erneut ausgeführt.")` |
| 5683 | Popup / Modal | `QMessageBox.warning(self, 'Fulfillment-Fehler', f'Schritt konnte nicht ausgeführt werden:\n\n{exc}')` |
| 5723 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5724 | Signal → Handler | `worker.signals.result.connect(self._show_redelivery_dialog)` |
| 5725 | Signal → Handler | `worker.signals.error.connect(self._on_redelivery_prepare_error)` |
| 5726 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_redelivery_prepare_worker', None))` |
| 5741 | Popup / Modal | `dialog.exec()` |
| 5748 | Popup / Modal | `QMessageBox.warning(self, 'Nachlieferung', f'Rechnungskontext konnte nicht geladen werden:\n\n{exc}')` |
| 5774 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5775 | Signal → Handler | `worker.signals.result.connect(lambda _payload: self._on_redelivery_applied())` |
| 5776 | Signal → Handler | `worker.signals.error.connect(self._on_redelivery_apply_error)` |
| 5777 | Signal → Handler | `worker.signals.finished.connect(lambda: setattr(self, '_redelivery_apply_worker', None))` |
| 5783 | Popup / Modal | `QMessageBox.information(self, 'Nachlieferung gespeichert', 'Die Nachlieferung wurde angelegt und wartet auf den gewählten Versandmodus.')` |
| 5791 | Popup / Modal | `QMessageBox.warning(self, 'Nachlieferung', f'Speichern fehlgeschlagen:\n\n{exc}')` |
| 5803 | Popup / Modal | `QMessageBox.question(self, 'Rechnungsentwurf löschen', 'Rechnungsentwurf wirklich löschen?', QMessageBox.StandardButton.Yes &#124; QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)` |
| 5824 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 5825 | Signal → Handler | `self._delete_draft_worker.signals.result.connect(self._on_delete_draft_result)` |
| 5826 | Signal → Handler | `self._delete_draft_worker.signals.error.connect(self._on_delete_draft_error)` |
| 5827 | Signal → Handler | `self._delete_draft_worker.signals.finished.connect(self._on_delete_draft_finished)` |
| 5838 | Popup / Modal | `QMessageBox.warning(self, 'Rechnungsentwurf löschen', f'Der Rechnungsentwurf konnte nicht gelöscht werden:\n\n{exc}')` |
| 5926 | UI / Aktion | `menu.addAction(self._packing_list_menu_label(path, position))` |
| 5927 | Signal → Handler | `action.triggered.connect(lambda _checked=False, selected_path=path, selected_reference=reference, handler=callback: handler(selected_path, selected_reference))` |
| 5940 | UI / Aktion | `labels_menu.addAction(f'PLC-Label {position} – {reference}')` |
| 5941 | Signal → Handler | `action.triggered.connect(lambda _checked=False, selected_path=path: self._open_archived_plc_label(selected_path))` |
| 5945 | UI / Aktion | `packing_menu.addAction(self._packing_list_menu_label(path, position))` |
| 5946 | Signal → Handler | `action.triggered.connect(lambda _checked=False, selected_path=path: self._open_archived_packing_list(selected_path))` |
| 5961 | Popup / Modal | `dialog.exec()` |
| 5964 | Popup / Modal | `QMessageBox.warning(self, 'PLC-Nachweis', f'Der Paketnachweis konnte nicht geladen werden: {exc}')` |
| 5968 | Popup / Modal | `QMessageBox.warning(self, 'Packliste öffnen', 'Die archivierte Packliste konnte nicht geöffnet werden.')` |
| 5974 | Popup / Modal | `QMessageBox.warning(self, 'Packliste drucken', f'Der Nachdruck der archivierten Packliste konnte nicht eingereiht werden.\n\n{exc}')` |
| 5981 | Popup / Modal | `QMessageBox.information(self, 'Packliste drucken', f'Archivierte Packliste zum Druck eingereiht: {job_id[:8]}…')` |
| 5999 | Hintergrundarbeit | `self._background_jobs.submit_callable(queue='cpu', priority=5, key='plc-archive-index', fn=job, on_result=self._on_plc_archive_index_ready, on_error=self._on_plc_archive_index_error, on_finished=lambda: setattr(self, '_plc_archive_index_handle', None), owner=self, replace='coalesce_pend…` |
| 6020 | Timer | `QTimer.singleShot(0, lambda summary=pending: self._open_plc_post_popup(summary))` |
| 6033 | Popup / Modal | `QMessageBox.warning(self, 'PLC-PDF öffnen', 'Das PLC-Label konnte nicht geöffnet werden.')` |
| 6040 | Popup / Modal | `QMessageBox.warning(self, 'Zolldokument oeffnen', 'Das Zolldokument konnte nicht geoeffnet werden.')` |
| 6058 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 6059 | Signal → Handler | `self._invoice_pdf_preview_worker.signals.result.connect(self._on_invoice_pdf_preview_result)` |
| 6060 | Signal → Handler | `self._invoice_pdf_preview_worker.signals.error.connect(self._on_invoice_pdf_preview_error)` |
| 6061 | Signal → Handler | `self._invoice_pdf_preview_worker.signals.finished.connect(self._on_invoice_pdf_preview_finished)` |
| 6068 | Popup / Modal | `QMessageBox.warning(self, 'Rechnungs-PDF ansehen', 'Das Rechnungs-PDF konnte nicht geoeffnet werden.')` |
| 6075 | Popup / Modal | `QMessageBox.warning(self, 'Rechnungs-PDF ansehen', f'Rechnungs-PDF konnte nicht geladen werden:\n\n{exc}')` |
| 6091 | Popup / Modal | `QMessageBox.warning(self, 'sevDesk oeffnen', 'Die Rechnung konnte nicht in sevDesk geoeffnet werden.')` |
| 6107 | Popup / Modal | `QMessageBox.information(self, 'Kunden-Mail', 'Eine Kunden-Mail wird bereits vorbereitet.')` |
| 6147 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 6148 | Signal → Handler | `self._customer_mail_worker.signals.result.connect(lambda payload: self._on_customer_mail_ready(summary, payload))` |
| 6149 | Signal → Handler | `self._customer_mail_worker.signals.error.connect(self._on_customer_mail_error)` |
| 6150 | Signal → Handler | `self._customer_mail_worker.signals.finished.connect(lambda: setattr(self, '_customer_mail_worker', None))` |
| 6157 | Popup / Modal | `QMessageBox.information(self, 'Kunden-Mail', 'Für diese Rechnung konnte keine Kunden-E-Mail-Adresse ermittelt werden.')` |
| 6169 | Popup / Modal | `QMessageBox.warning(self, 'Kunden-Mail', f'Der Mail-Entwurf konnte nicht in Outlook Classic geöffnet werden.{detail}')` |
| 6177 | Popup / Modal | `QMessageBox.warning(self, 'Kunden-Mail', f'Mail konnte nicht vorbereitet werden:\n\n{exc}')` |
| 6237 | Popup / Modal | `QMessageBox.information(self, 'Download-Links', 'Diese Rechnung hat keine Wix-Order-Referenz.')` |
| 6246 | Popup / Modal | `QMessageBox.warning(self, 'Download-Links', 'Wix-Order konnte nicht aufgelöst werden.')` |
| 6255 | Popup / Modal | `QMessageBox.information(self, 'Refund in Wix erstellen', 'Refunds werden ausschließlich in Wix erstellt. Den aktuellen Beleg- und Prüfstatus findest du unter ‚Stornos & Gutschriften‘.')` |
| 6262 | Popup / Modal | `RefundsDialog(self._container, self).exec()` |
| 6297 | Timer | `QTimer.singleShot(0, lambda s=summary, token=seq: self._hydrate_detail_for_selection(s, token))` |
| 6375 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 6376 | Signal → Handler | `worker.signals.result.connect(self._on_sevdesk_context_loaded)` |
| 6377 | Signal → Handler | `worker.signals.error.connect(lambda exc: self._on_sevdesk_context_error(exc) if context_seq == self._sevdesk_context_seq and (not self._shutting_down) else None)` |
| 6382 | Signal → Handler | `worker.signals.finished.connect(lambda: self._on_sevdesk_context_finished(worker))` |
| 6717 | Hintergrundarbeit | `self._background_jobs.submit_callable(queue='ui-critical-network', priority=0, key='selected-wix-context', fn=job, on_result=self._on_wix_context_loaded, on_error=self._on_wix_context_error, on_finished=self._on_wix_context_finished, owner=self, replace='cancel_previous')` |
| 7080 | Popup / Modal | `QMessageBox.warning(self, 'Labeldruck', f'Label konnte nicht gedruckt werden:\n\n{exc}')` |
| 7095 | Popup / Modal | `QMessageBox.warning(self, 'Rechnungsdruck', f'Rechnung konnte nicht gedruckt werden:\n\n{exc}')` |
| 7107 | Popup / Modal | `QMessageBox.information(self, 'Rechnung gesendet', f'Rechnung {invoice} wurde an {recipient} gesendet.')` |
| 7114 | Popup / Modal | `QMessageBox.warning(self, 'Rechnung senden', f'Rechnung konnte nicht gesendet werden:\n\n{exc}')` |
| 7132 | Popup / Modal | `dlg.exec()` |
| 7146 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 7147 | Signal → Handler | `self._draft_product_worker.signals.result.connect(self._on_draft_product_plan_ready)` |
| 7148 | Signal → Handler | `self._draft_product_worker.signals.error.connect(self._on_create_draft_error)` |
| 7149 | Signal → Handler | `self._draft_product_worker.signals.finished.connect(self._on_draft_product_plan_finished)` |
| 7177 | Popup / Modal | `QMessageBox.information(self, 'Rechnungs-Entwurf erstellt', '\n'.join(message_lines))` |
| 7188 | Popup / Modal | `QMessageBox.warning(self, 'Rechnungs-Entwurf fehlgeschlagen', f'Der Entwurf konnte nicht erstellt werden:\n\n{exc}')` |
| 7210 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 7211 | Signal → Handler | `self._draft_worker.signals.result.connect(self._on_create_draft_result)` |
| 7212 | Signal → Handler | `self._draft_worker.signals.error.connect(self._on_create_draft_error)` |
| 7213 | Signal → Handler | `self._draft_worker.signals.finished.connect(self._on_create_draft_finished)` |
| 7244 | Hintergrundarbeit | `BackgroundWorker(job)` |
| 7246 | Signal → Handler | `worker.signals.result.connect(lambda payload: self._on_draft_preview_result(dlg, payload))` |
| 7247 | Signal → Handler | `worker.signals.error.connect(lambda exc: dlg.set_preview_result(f'Vorschau fehlgeschlagen:\n{exc}', ok=False))` |
| 7250 | Signal → Handler | `worker.signals.finished.connect(lambda current=worker: self._on_draft_preview_finished(current))` |
| 7418 | Popup / Modal | `dialog.exec()` |
| 7603 | UI / Aktion | `QSpinBox()` |
| 7614 | UI / Aktion | `QToolButton()` |
| 7629 | Signal → Handler | `print_btn.clicked.connect(lambda _checked=False, block=item, qty=qty_input: self._on_product_print_clicked(block, qty.value()))` |
| 7635 | UI / Aktion | `QToolButton()` |
| 7644 | Signal → Handler | `manage_btn.clicked.connect(lambda _checked=False, block=item: self._on_product_manage_clicked(block))` |
| 7745 | Hintergrundarbeit | `self._background_jobs.submit_callable(queue='printing', priority=20, key=f'product-print:{block.sku}:{time.monotonic_ns()}', fn=lambda _token: worker_job(), on_result=self._on_product_print_result, on_error=self._on_product_print_error, on_finished=finished, owner=self, replace='allow_p…` |
| 7787 | Popup / Modal | `QMessageBox.critical(self, 'Produktdruck fehlgeschlagen', f'Die Produkt-PDF konnte nicht ueber den hinterlegten Druckplan gedruckt werden:\n\n{exc}')` |

- AP06/F17 Packlisten-Print: PLC-Mehrpaket-PDF-Erzeugung und Queue-Write laufen jetzt in einem BackgroundWorker; der Button bleibt bis zum Ergebnis gesperrt und wiederholte Aufrufe werden ignoriert. Der Dialog bleibt waehrend des Drucklaufs offen, damit Erfolgs-/Fehlerfeedback am Owner ankommt. Neuer Fake-Test blockiert den Renderer, bestaetigt Qt-Heartbeat und genau einen Queue-Write nach Freigabe. Ruff bestanden; lokale UI-Tests sind mangels PySide6 nicht sammelbar, die geaenderten Packlisten-UI-Regressionen sind jedoch im Windows-CI-Run `43051392068` auf `3d79b6c` enthalten und bestanden.
- AP06/F17 Archiv-Packlistennachdruck: Der Druckwarteschlangen-Write aus dem Rechnungsmenue laeuft nun in einem lifecycle-verfolgten Worker; ein paralleler identischer UI-Aufruf startet keinen zweiten Auftrag. Die Regression wurde um einen blockierten Fake-Queue-Write, Qt-Heartbeat und Einmaligkeitspruefung erweitert. Ruff und git diff --check bestanden; die Qt-Regression fuer den Archivnachdruck ist im Windows-CI-Run `43051392068` auf `3d79b6c` enthalten und bestanden.
- Hosted-Windows-CI `43051392068` auf `3d79b6c`: Ruff bestanden; **2.190 Tests bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 Warnung (771,27 s)**. Der weiche MyPy-Lauf meldet unveraendert **359 Fehler in 63 Dateien**; keine Fehler in den geaenderten Rechnungs-/Packlistendateien. Aeltere rote Laeufe (`43048543834`, `43048922408`, `43049132860`, `43049995158`) scheiterten an einer ueberholten synchronen Assertion im Packlistendrucktest; nach der asynchronen Erwartungskorrektur besteht der komplette Lauf. Die Benutzer-Aenderung `bff18ad` blieb erhalten.
- AP06/F17 PLC-Nachbereitung: Nach erfolgreicher PLC-Antwort laufen Archivierung, Zoll-PDF-Aufbereitung, Druck-Queue, lokale Druckmarke, Teilerfuellung und Packlistenjournal sequenziell in einem lifecycle-geschuetzten Worker. Die Reihenfolge bleibt erhalten; Status/Fehler mit bereits archivierten Pfaden erscheinen erst nach dem Worker-Ergebnis. Send-/Finalize-Worker verhindern erneut Senden und Schliessen bis zum sicheren Ergebnis. 21 Packlisten-/PLC-Service-Unit-Tests, Ruff, Compileall und git diff --check bestanden; Qt-Regressionen pruefen Reihenfolge, Teilfehler und UI-Heartbeat im Hosted-Windows-Lauf. Hosted-Windows-CI `43055476237` auf `f0fc866`: Ruff bestanden; die vollstaendige Suite meldet **2.191 bestanden, 5 uebersprungen, 1 Warnung (606,61 s)**; MyPy bleibt als weicher Gate bei 359/63 ohne Fehler in plc_label_dialog.py.
- AP06/F17 PLC-Duplikat-Recovery: Der nach bestaetigtem Nachdruck aufgerufene Archiv-Queue-Write laeuft jetzt ebenfalls sequenziell im Worker; erneute Klicks werden ignoriert und Close/Abbrechen bis zum Queue-Ergebnis blockiert. Die Regression blockiert einen Fake-Queue-Write und prueft Heartbeat, Einmaligkeit und Dialoglebenszyklus. Ruff, Compileall und git diff --check bestanden; die Qt-Regression ist im Hosted-Windows-Lauf `43057972389` enthalten und bestanden.

- Hosted-Windows-CI `43057972389` auf `0ad418a`: Ruff bestanden; **2.192 Tests bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 Warnung (629,31 s)**. Die PLC-Duplikat-Recovery-Regression bestaetigt Heartbeat, genau einen Queue-Write sowie den Close-Schutz bis zum Ergebnis. Der weiche MyPy-Lauf meldet 359 Fehler in 63 Dateien; keine Fehler in der geaenderten PLC-Datei.

- AP06/F17 Produktdruck-PDF: `prepare_piece_pdf_print` liest und zaehlt die PDF-Seiten nicht mehr synchron im UI-Thread, sondern erst beim Ausfuehren des Druckjobs; fehlgeschlagene PDF-Vorbereitung wird als `failed` (sicher vor Spool) abgeschlossen, waehrend moeglicherweise gestartete Drucke weiterhin `unknown` bleiben. Der ungenutzte synchrone Wrapper wurde entfernt. Regression prueft, dass beim Vorbereiten keine Datei geoeffnet wird und fehlerhafte PDFs nicht in die Queue gelangen. Lokale Ruff-/Compileall-/Diff-Pruefungen bestanden; lokale Qt-Tests konnten mangels PySide6 nicht gesammelt werden. Hosted Windows CI `43062102264` auf `3fd37d5` (enthaelt `53398ad`): **2.193 bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 Warnung (676,17 s)**; beide PDF-Regressionsfaelle bestanden. Ruff gruen; weicher MyPy-Gate unveraendert bei 359 Fehlern/63 Dateien, keine Fehler in den geaenderten Druckdateien.

- AP06/F17 Druckerstatus-Preflight: Produktdruck liest den zentralen `PrinterStatusService`-Snapshot statt `discover_printers()` im UI-Klickpfad. Ein roter oder noch nicht initialisierter Status blockiert den Druck mit passender Meldung. `MainWindow` aktualisiert den Status jede Minute in einem Worker und stoppt den Timer beim Shutdown. Lokale venv (`.venv`, PySide6 6.11.0): **112 Rechnungs-/Produktdruck-/MainWindow-Tests bestanden**; gezieltes striktes MyPy fuer `print_dialog.py` und `main_window.py` sowie Ruff/Compileall bestanden. Hosted-Windows-CI `43065044735` auf `7435f69`: Ruff bestanden; **2.194 Tests bestanden, 5 optionale PostgreSQL-Tests uebersprungen, 1 Warnung (800,45 s)**. Der Druckerstatus-Snapshot-Test sowie MainWindow-Timer-/Shutdown-Regressionen bestanden. Der weiche MyPy-Lauf meldet global weiterhin 359 Fehler in 63 Dateien; `print_dialog.py` und `main_window.py` sind im gezielten strikten Lauf fehlerfrei.

## Fortschreibung 11.11.2026 – AP03 Claim-Reconciliation und Testumgebung

- **AP03 manueller Unknown-Claim-Abgleich: ERLEDIGT (Werkzeug), externe Abnahme weiterhin OFFEN.** `scripts/invoice_processing/reconcile_claim.py` listet unbekannte Claims und protokolliert einen manuellen Endzustand nur nach exakter Operation-ID, expliziter Wiederholungsbestätigung, Operator und mindestens acht Zeichen Readback-Nachweis. Es arbeitet ausschließlich auf `SettingKV` und ruft keine sevDesk-, Wix-, Mail- oder Druckschnittstelle auf. `failed` erlaubt einen erneuten Versuch und darf daher nur nach bestätigtem externem Nachweis verwendet werden. Reconciliation-Historie bleibt bei späteren Versuchen erhalten.
- Repository-, Claim- und CLI-Regressionen: **28 bestanden**. Ruff und `compileall` bestanden. Keine Verbindung zu einer Produktivdatenbank und keine externen Schreibaktionen ausgeführt.
- PySide6 wurde in der vorhandenen Projekt-venv gefunden: **6.11.0** (`.venv\\Scripts\\python.exe`). Frühere Einträge, die fehlendes PySide6 festhalten, beschreiben den damaligen Lauf; die lokale Testumgebung ist inzwischen verfügbar.
- Weiter offen bleiben die ledgerbasierte sevDesk-Part-Bestandsprojektion sowie die echte Mehr-PC-/Prozessabbruch-Recovery und Betriebsabnahme unter G2.

## START-Störung vom 11.11.2026, 20:54–20:59 Uhr

- **F24 – P1, ERLEDIGT (Code), Betriebsnachweis OFFEN:** Lokale `logs/xw_office.log` zeigen zwei START-Versuche. Beim Lauf um 20:58 scheiterten alle sieben physischen Rechnungen in der Finalisierung an `Physischer Bestand reicht ... verfügbar 0`; vier digitale Vorgänge im vorherigen Lauf bzw. im Folgelauf wurden erfolgreich weiterverarbeitet. Zwei bereits finalisierte physische Rechnungen meldeten zusätzlich `Product-Hub-Bestandsbuchung fehlgeschlagen: Movement would drive on_hand to -1`, wurden aber wegen abgeschlossener Folgeaktionen als Resume-Erfolg gezählt. Eine erneute Produktivaktion wurde zur Analyse nicht ausgelöst.
- Ursache 1: Desktop-Bootstrap injizierte `InvoiceInventoryBookingService` allein aufgrund einer konfigurierten Datenbank. Die lokale Konfiguration hat `inventory_master_enabled=False`, `inventory_shadow_enabled=False`. Der noch nicht freigegebene Product-Hub-Bestand wurde dadurch vor der Rechnungsfreigabe als Master geprüft. Korrektur: Die Hub-Rechnungsbuchung wird erst bei aktiviertem `inventory_master_enabled` eingebunden; bis dahin gilt der vorhandene Legacy-Bestandspfad.
- Ursache 2: Der einfache START-Klick übersprang die Bestandsvorprüfung; die vorhandene Fehlermeldung verwies auf `START + NOTENDRUCK`, obwohl diese Menüaktion am 11.11.2026 entfernt worden war. Korrektur: START ermittelt nun vor Produktklärung und finanziellen/externalen Writes den Bedarf, stoppt bei Fehlbestand und nennt `PRINT-PRODUKTE` oder Bestandskorrektur als nächsten Schritt. Die getrennte Produktdruckfunktion aktualisiert den Legacy-Bestand nach bestätigtem Druck.
- Fokusprüfung: **170 Rechnungs-/Inventar-/UI-Tests bestanden**, Ruff grün und MyPy für beide geänderten Quelldateien ohne Fehler. Aktuelle lokale venv enthält PySide6 6.11.0. Der Code wurde nicht gegen die Produktivschnittstellen ausgeführt. Für einen echten erneuten START müssen die im Dialog genannten physischen Artikel zuerst korrekt im Bestand verfügbar sein; bereits erfolgreiche digitale Vorgänge dürfen nicht blind wiederholt werden.

### F24-Fortschreibung: START ohne Bestandsbuchung bis zum Bauabschluss

Der Nutzer hat am 11.11.2026 festgelegt, dass der Anfangsbestand während der laufenden Bauarbeiten für START irrelevant ist. Die vorstehende Empfehlung, vor START unter `PRINT-PRODUKTE` zu drucken, gilt deshalb **derzeit nicht als Voraussetzung**. `inventory.start_stock_booking_enabled` steht in `config/default.yaml` standardmäßig auf `false`. Damit überspringt der START-Klick den Bestands-Preflight, die Legacy- und Hub-Bestandsprüfung, beide Buchungen nach Rechnungsfreigabe und reine Bestands-Retry-Arbeit. Rechnungspositionen, Freigabe, Belegdruck, Zahlungs-/Wix-/Mail-Schritte behalten ihre fachlichen Prüfungen und Claims.

Nach Abschluss der Bauarbeiten kann `inventory.start_stock_booking_enabled: true` gesetzt und die Desktop-App neu gestartet werden. Dann gelten wieder Bestands-Preflight und Legacy-Buchung. Die Product-Hub-Rechnungsbuchung benötigt zusätzlich das bereits vorhandene Cutover-Flag `product_hub.inventory_master_enabled: true`; dieses bleibt bis zur Betriebsabnahme aus. Vor dem Aktivieren müssen Anfangsbestand und offene historische Bestandswarnungen fachlich abgeglichen werden. Der Schalter ändert keine früheren Buchungen und führt keine rückwirkenden Buchungen aus.

Regressionen mit beiden Schalterzuständen: **194 gezielte Tests bestanden** (Rechnungsverarbeitung, Druckparität, Konfiguration, Bootstrap und Rechnungs-UI); Ruff und gezieltes MyPy für Bootstrap, Rechnungsservice und Tagesgeschäft-UI grün. Der reale START wurde wegen möglicher finanzieller/externer Schreibaktionen nicht testweise ausgelöst.


## Fortschreibung 11.11.2026 - START-Betriebsnachweis und UI-Last

- **START nach Bestands-Gate: im benutzergestarteten Lauf erfolgreich.** Das Log vom 11.11.2026 21:20-21:22 (App-Commit `356dcdb`, Standard `inventory.start_stock_booking_enabled: false`) zeigt `product_preflight` ohne Issues, danach sieben Rechnungen mit `processed=7 failures=0` und Gesamtdauer 102,2 s. Finalisierung, Rechnungs-/Labeldruck sowie die nachgelagerten Zahlungs-, Wix-Fulfillment- und Mailphasen wurden im Log jeweils als erfolgreich abgeschlossen. Es gibt in diesem Lauf keine Bestands-Preflight- oder Bestandsbuchungsfehler. Dieser Nachweis stammt aus dem vom Nutzer ausgeloesten Produktivlauf; Codex hat START nicht erneut ausgefuehrt.
- Die aelteren Fehlversuche um 20:54?20:59 auf Commit `0df679f` stoppten wie oben dokumentiert an verfuegbarem Bestand `0`. Der aktuelle erfolgreiche Lauf bestaetigt, dass der neue Standard-Schalter den START-Flow ohne Anfangsbestand freigibt. Keine weitere Codeaenderung am START-Flow war fuer diesen aktuellen Lauf n?tig.
- **Performancebeobachtung, Ursache offen:** Das Log beim Oeffnen/Aktualisieren der Rechnungsansicht enth?lt Eventloop-Luecken bis 4.787 ms und 2.490 ms; die Non-Draft-Seite mit 50 Zeilen dauerte dabei 4.772 ms. Ein weiterer Lauf brauchte 1.996 ms. Das ist ein belegter UI-Lag, aber die Logs isolieren noch keinen konkreten blockierenden Abschnitt. Vor einer Optimierung ist ein reproduzierbares Profiling der sevDesk-Listenabfrage, Zeilenaufbereitung und Qt-Tabellenaktualisierung erforderlich.
- Testumgebung erneut gepr?ft: Projekt-venv enth?lt PySide6 **6.11.0**. Die lokale Testumgebung benoetigt keine zus?tzliche Installation.

- Vollsuite in `.venv` nach START-Bestaetigung: **2.213 bestanden, 5 uebersprungen, 1 bestehende Starlette/httpx-Deprecation-Warnung (191,79 s)**. Der anschliessende globale Ruff-Lauf fand sechs ungenutzte Imports bzw. einen Lambda-Stilbefund in vier Service-Regressionstests; Imports bereinigt und Lambda in eine lokale Funktion umgeschrieben. Danach **Ruff global gruen** und die vier betroffenen Testmodule erneut mit **8 bestanden**. Der CI-Run fuer `c9ac9a5` hatte Pytest, Ruff und MyPy bereits erfolgreich abgeschlossen; der Jobabschluss und der nachfolgende Lauf fuer `356dcdb` waren bei der Pruefung noch ausstehend.

- **F25-Instrumentierung ergaenzt:** langsame sevDesk-Invoice-Seiten loggen nun getrennt Netzwerkabruf, JSON-Parsing, Modellnormalisierung, Sortierung und Summary-Observer; der Non-Draft-Batch trennt API-/Summary-Laden, Flags, Row-Erzeugung und Fulfillment-Anreicherung; die UI misst Row-Vorbereitung, Qt-Tabellenupdate und restliche Auswahl-/Layout-Arbeit. Die Ausgabe wird nur fuer Phasen ab 250 ms (Service) bzw. 100 ms (UI) geschrieben. Ursache und Optimierung bleiben offen, bis ein Folgelauf mit der instrumentierten Version diese Phasenwerte liefert.
- Gezielte Regressionen fuer Invoice-Client, Invoice-Processing und Rechnungsansicht: **180 bestanden**. Globale Ruff-Pruefung: gruen; gezieltes MyPy fuer die drei instrumentierten Quelldateien: gruen.

## PLC-Packlisten bei Einpaket-Sendungen am 11.11.2026

- **F26 - P2, ERLEDIGT (Code), Laufzeit bestaetigt mit Neustart erforderlich:** Die beiden vom Nutzer um 21:37 ausgeloesten PLC-Webservice-Laeufe reihten jeweils nach dem Label auch ein Packlisten-PDF auf `Paketmarke A5` ein. Die Logs zeigen zwei Codes je Lauf; das ist kein Beleg fuer zwei physische Pakete, weil eine Collo-Gruppe mehrere PLC-Codes enthalten kann. Der Dialog stand fuer diese Sendungen laut Nutzer auf einem Paket.
- Ursache: Der automatische Nachbereitungspfad druckte bei jedem nichtleeren `packing_contexts`. Auch ein einzelnes Paket erzeugt diesen Kontext fuer den unveraenderlichen Inhalts-Snapshot. Die PDF-Erzeugung und der Packlisten-Queue-Write sind nun an mindestens zwei `shipment.parcels` gebunden. Der manuelle Packlisten-Button hatte diese Grenze bereits.
- Der Einpaket-Kontext wird weiterhin vor dem externen PLC-Aufruf als `plc_parcel_manifest.contents_json` gespeichert; die PLC-Infoansicht zeigt den Paketinhalt auch ohne Packlisten-PDF. Die PLC-`ColloCodeList` wird getrennt gespeichert; zwei Codes in einer Collo-Gruppe werden nicht als zwei Pakete gezaehlt. An den Post-Webservice selbst werden Artikelpositionen fuer EU/AT-Sendungen nicht als `ColloArticleList` uebertragen; diese Liste ist im bestehenden SOAP-Mapping nur fuer Zollsendungen gesetzt.
- Laufzeitursache bestaetigt: Die beiden Drucklogs stammen von 21:37:07 und 21:37:34; Fix-Commit `711c05e` wurde erst um 21:45:16 erstellt. Bei der Nachpruefung lief `scripts/xw_office_gui.pyw` weiterhin aus demselben venv als Prozess mit Startzeit 21:36:40 und hatte deshalb noch den alten Modulcode geladen. Den laufenden GUI-Prozess nicht automatisch beendet; der neue Code wird beim naechsten normalen Neustart geladen.
- Nachweis: **45 gezielte PLC-Service-/Dialogtests bestanden**, darunter Regressionen fuer ein Paket ohne Packlisten-PDF/Queue trotz zweier Codes in einer Collo-Gruppe, zwei Pakete mit Packlisten-PDF/Queue und den Einpaket-Inhalt im lokalen Collo-Journal. Die aktuelle PLC-Dialogdatei besteht erneut mit **26 Tests**; Ruff und gezieltes MyPy sind gruen. Zusaetzlich bestanden 14 PLC-Info-/Archivtests. Es wurde kein weiterer produktiver PLC-Aufruf oder Druck durch Codex ausgeloest. Bereits gedruckte Packlisten bleiben historische Archivbelege.


## Fortschreibung 11.11.2026 - Rechnungslisten-I/O im Worker

Der Nachaudit fand in RechnungenView noch einen synchronen Cold-Cache-Pfad: SecretService.get_secret() kann beim ersten Zugriff ApiSecretRepository.get_all_ciphertexts() ausfuehren; ausserdem wurde InvoiceProcessingService fuer Rechnungslisten vor dem Workerstart lazy aufgeloest. Beides liegt jetzt im Lade-Worker. Die Cache-Invalidierung vor Refresh und der Suchindex-Sync werden ebenfalls vom Worker erledigt. Fehlt das sevDesk-Token, liefert der Worker eine leere Seite wie zuvor ohne Request.

Eine blockierte Fake-Secret-Pruefung bestaetigt, dass der Qt-Heartbeat weiterlaeuft und die Rechnungsliste nach Freigabe geladen wird. Die vollstaendige test_rechnungen_view_smoke.py besteht mit **94 Tests**; gezieltes striktes MyPy fuer view.py, globales Ruff und git diff --check sind gruen. Die Vollsuite besteht mit **2.220 Tests**, 5 optionalen PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-Deprecation-Warnung (161,76 s). Das behebt einen belegbaren Cold-Start/UI-Thread-I/O-Pfad; die F25-Laufzeitoptimierung bleibt offen, bis ein instrumentierter Echtlauf die neue Phasenverteilung liefert.

Im Nachaudit wurde ausserdem die 300-ms-Fulfillment-Phase der 50-Zeilen-Batches weiter zerlegt: sie las Fulfillment-Flags und START-Zurueckstellungen ueber zwei unabhaengige SettingKV-Datenbank-Rundreisen. `SettingKvRepository.get_values_json()` und der Rechnungslisten-Batch lesen diese beiden aktuellen Werte jetzt gemeinsam in einer Abfrage/einem Snapshot; es wird kein Cache eingefuehrt, sodass Aenderungen anderer PCs beim naechsten Batch sichtbar bleiben. Regressionen pruefen die Mehrfachwert-Abfrage und genau einen Snapshot-Aufruf. 23 gezielte Repository-/START-Tests, Ruff sowie striktes MyPy fuer `settings_kv.py` und `invoice_processing/service.py` sind gruen. Ein instrumentierter Echtlauf mit dem neuen Code steht noch aus; deshalb bleibt F25 TEILWEISE.

Nach der SettingKV-Aenderung bestand die lokale Vollsuite mit **2.222 Tests**, 5 optionalen PostgreSQL-Ueberspringungen und derselben bestehenden Starlette/httpx-Deprecation-Warnung (168,56 s). Nach dem Refund-Dialog-Fix und der Stabilisierung eines asynchronen Sendungen-UI-Tests bestand sie mit **2.223 Tests**, 5 Ueberspringungen und derselben Warnung (160,73 s). Nach dem Fast-Forward der aktuellen Ops-Aenderungen bis `488f636` besteht die gemeinsame Basis mit **2.226 Tests**, 5 Ueberspringungen und derselben Warnung (157,03 s); globales Ruff, `git diff --check` und gezieltes striktes MyPy sind gruen.

## Fortschreibung F17 - Refund-Dialog-Services im Worker

Der Nachaudit fand in `RefundsDialog` noch synchrone Container-Aufloesungen vor dem Workerstart: beim Laden der Refund-Liste, beim Oeffnen eines Gutschrift-PDFs und vor der Mailvorbereitung/-sendung. Diese Services werden jetzt innerhalb der jeweiligen Worker aufgeloest. Ein blockierender Fake prueft den Qt-Heartbeat bei Refund-Mailvorbereitung; die Listen-/PDF-Regressions pruefen ebenfalls, dass alle Service-Aufloesungen abseits des UI-Threads laufen. `test_refunds_dialog.py` besteht mit 3 Tests, gezieltes striktes MyPy und Ruff sind gruen. F17 bleibt TEILWEISE bis die verbleibenden UI-Pfade weiter geprueft sind.

Ein Vollsuite-Lauf direkt vor diesem Nachaudit deckte einen Test-Race in `test_offene_sendungen_dialog.py` auf: Der Fake erhoehte `refresh_called` im Worker, bevor das Qt-Ergebnis gerendert war. Der Test wartete zuvor nur auf den Worker-Nebeneffekt und las dadurch gelegentlich den Lade- statt Endstatus. Er wartet nun auf den sichtbaren abgeschlossenen UI-Status; die betroffenen Sendungen-/Refund-Dialogtests bestehen zusammen mit 14 Tests.

## Fortschreibung F20 - sevDesk-Cache-Typ im Runtime-Pfad

Der Desktop-Loglauf vom 12.11.2026 meldete bei SKU `XW-1201` `NameError: SevdeskPart is not defined`. `_cached_part_by_sku` wertete den Typ in einem `cast(...)` zur Laufzeit aus, obwohl `SevdeskPart` nur unter `TYPE_CHECKING` importiert war. Der Runtime-Import ist jetzt explizit. Die Regression prueft einen gecachten sevDesk-Part und dessen Bestand; `test_print_decision_engine.py` besteht mit **12 Tests**, Ruff und striktes MyPy fuer `print_decision.py` sind gruen. Die Vollsuite besteht nach diesem Fix mit **2.297 Tests, 5 optional uebersprungenen PostgreSQL-Tests und 1 bestehenden Starlette/httpx-Warnung (231,34 s)**; GitHub-CI fuer Commit `2ca5e49` (Run `43179094040`) ist fuer Ruff, Pytest und MyPy erfolgreich. Railway-Production-Deployments von `xw-inventory-worker` und `XW-Product-Hub` auf `2ca5e49` stehen beide auf `SUCCESS`.

## Fortschreibung F23 - Wix- und Website-Endpoint-Readback

Das Wix-Backend prueft vor dem Create ueber `POST /payment-links/v1/payment-links/search`, ob exakt ein Payment-Link dessen JSON-Feld `note.text.clientRequestKey` enthaelt; bei genau einem Treffer gibt es diesen Link zurueck statt einen neuen anzulegen. Die authentifizierte XW-Website-Funktion bietet dieselbe Suche als `action: readback` an. XW-Office ruft sie fuer einen `unknown`-Claim auf, wenn lokale Wix-REST-Zugangsdaten fehlen. Genau ein valider Treffer reconciliert den Claim zu `succeeded`; null, mehrere, malformed, limitierte oder fehlgeschlagene Antworten halten den Claim gesperrt und erzeugen keinen zweiten POST. Die Aenderungen wurden in Website-Commit `0f883d4` auf den verbundenen Main-Branch gepusht; XW-Office-Commit `5f6481c` traegt die Clientintegration und Regressionen. Wix-Commit `0f883d4` ist mit UI-Version `18585` erfolgreich publiziert. Der Live-Wix-REST-Search-Probe antwortete fuer einen eindeutigen Dummy-Key mit HTTP 200 und null Treffern; ein echter Match wurde nicht erzeugt oder geprueft.

Alle **15 Tests** in `test_special_order_service.py`, striktes MyPy fuer `service.py` und Ruff fuer Service/Test sind gruen. Die volle XW-Office-Suite besteht mit **2.297 Tests, 5 optionalen PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-Warnung (231,34 s)**. Website `check:all` ist gruen: TypeScript-Pruefung, ESLint und **155 Unit-Tests**. Wix dokumentiert `note.text` als durchsuchbares Feld im [Search-Payment-Links-Endpunkt](https://dev.wix.com/docs/api-reference/business-management/get-paid/payment-links/payment-links/search); der Live-Search-Probe mit Dummy-Key antwortete HTTP 200 und null Treffer. Die Wix-Notiz ist kein atomarer Deduplizierungsmechanismus; F23 bleibt bis zum Live-Exact-Match-Nachweis blockiert.

## Fortschreibung AP07 - sevDesk-Historie fuer Forecasts gebuendelt

Die auf `main` eingegangenen Commits `2e50584`, `30fa7b2` und `746937c` laden sevDesk-Rechnungen/Gutschriften sowie deren Positionen paginiert als begrenzte Snapshots und gruppieren sie anschliessend lokal nach Jahr bzw. Beleg-ID. Damit entfallen die monatlichen Dokumentabfragen und die Einzelabfragen je historischem Beleg, auch fuer Inventory-Feed-Poller; Anbieter ohne Bulk-Schnittstelle behalten den bisherigen Monats-/Einzelabruf als Fallback. Der Dokumentcache wird zusammen mit den Positions- und Kontaktcaches durch `clear_cache()` invalidiert. Die Daten bleiben read-only und werden nur fuer Forecast-/Auditberechnungen verwendet.

Bei der gezielten Pruefung bestanden `test_inventory_forecast_refresh.py`, `test_sevdesk_history_audit.py` und `test_zm_service.py` zusammen mit **11 Tests**; Ruff und gezieltes MyPy fuer die drei Produktionsdateien sind gruen. Fuer den Inventory-Feed-Batch und die anschliessende Normalisierung verschachtelter sevDesk-Partnummern bestehen die vier betroffenen Feed-/History-/Forecast-Module auf `e4a48dc` mit **27 Tests**; Ruff und gezieltes MyPy fuer die drei Feed-/History-Services sind gruen. Dabei wurde ein inzwischen unnoetiger `type: ignore`-Kommentar fuer `stdnum.eu.vat` entfernt, den MyPy als unbenutzt meldete. Die Vollsuite auf dem vorangehenden Stand `30fa7b2` bestand mit **2.228 Tests, 5 uebersprungen, 1 bestehender Starlette/httpx-Deprecation-Warnung (162,36 s)**; Hosted CI fuer `e4a48dc` laeuft noch. F19 bleibt TEILWEISE: ein gemeinsamer Versions-/Inhaltsrevision-Cache und die verbleibende Produkt-/Druckkonfigurationsaufloesung je SKU sind nicht Teil dieser Forecast-Buendelung.

## AP07-Nachkorrektur - sevDesk-Paginierung auf API-Limit begrenzt

Die sevDesk-API kuendigte ein hartes `limit`-Maximum von 1.000 an. Die neuen Forecast-Snapshot-Lader hatten 5.000 angefordert; damit haette der Produktivabruf HTTP 400 geliefert. Beide Bulk-Lader verwenden jetzt 1.000; `load_tax_resource` lehnt Werte ausserhalb 1 bis 1.000 vor dem Netzwerkaufruf ab. Ein HTTP-Fake prueft beide Bulk-Requests auf Limit 1.000 und eine weitere Regression prueft die lokale Ablehnung von 1.001. Beleg: [sevDesk API News zu Pagination-Limits](https://tech.sevdesk.com/api_news/posts/2025_03_11-api_pagination_limits/).

Sechs betroffene UVA-/ZM-/Forecast-/Feed-Module bestehen zusammen mit **89 Tests**; Ruff und gezieltes MyPy fuer `source_reads.py` und `zm_service.py` sind gruen. Die Vollsuite auf dem korrigierten lokalen Stand besteht mit **2.233 Tests, 5 uebersprungen, 1 bestehender Starlette/httpx-Deprecation-Warnung (156,77 s)**. Globaler Ruff-Lauf ist ebenfalls gruen.

## Fortschreibung F17 - Produktdruck-PDF-Pruefung im Worker

`ProductPrintConfigDialog` prueft lokale bzw. geteilte PDF-Pfade und oeffnet das Dokument jetzt nicht mehr synchron beim Dialogstart oder bei jeder Pfadeingabe. Die Pruefung wird entprellt in einem `BackgroundWorker` ausgefuehrt; ein spaetes Ergebnis fuer einen vorherigen Pfad wird verworfen. Wird waehrend der Pruefung gespeichert, wird der Dialog nach erfolgreicher Validierung automatisch abgeschlossen; bei Fehlern bleibt er offen und zeigt den konkreten Status. Abbruch invalidiert die Workerantwort ohne auf den Datei-/Netzwerkzugriff zu warten.

`test_rechnungen_product_print.py` besteht mit **15 Tests in drei aufeinanderfolgenden Laeufen**. Neue Qt-Regressionen blockieren `fitz.open` im Fake-Worker und pruefen den UI-Heartbeat, den Wechsel von Pfad A zu B waehrend A laeuft, den fortgesetzten Speichervorgang nach erfolgreicher Pruefung und das sichere Verwerfen des Ergebnisses nach Dialogschluss. Ruff und gezieltes MyPy fuer `print_dialog.py` sind gruen. Die anschliessende Vollsuite bestand auf diesem UI-Stand mit **2.242 Tests, 5 uebersprungen, 1 bestehender Starlette/httpx-Deprecation-Warnung (169,14 s)**; weitere UI-I/O-Pfade bleiben zu pruefen.

## Fortschreibung F17 - Lizenz-PDF-Pfadpruefung im Worker

Beim manuellen Zuordnen einer Druck-PDF in `DigitalLicensesDialog` lief `Path.is_file()` noch synchron vor dem bereits asynchronen Settings-Write. Auf langsamen oder getrennten Netzlaufwerken konnte dieser Metadatenzugriff den UI-Thread blockieren. Pruefung und Persistierung laufen jetzt im gleichen lifecycle-verfolgten Worker; ein fehlender Pfad wird vor jeder Settings-Aenderung als konkreter Fehler gemeldet. Zwei Qt-Regressionen blockieren `Path.is_file()` und pruefen den Eventloop-Heartbeat sowie, dass ein fehlender Pfad nichts speichert. Das Dialogmodul besteht mit **9 Tests**, globale Ruff-Pruefung und gezieltes MyPy fuer `digital_licenses_dialog.py` sind gruen. Die Vollsuite nach dieser Aenderung besteht mit **2.244 Tests, 5 uebersprungen, 1 bestehender Starlette/httpx-Deprecation-Warnung (171,43 s)**. F17 bleibt teilweise offen; die statische Nachpruefung weiterer UI-I/O- und Service-Aufloesungspfade laeuft weiter.

## Fortschreibung F17 - PLC-Archivsuche im Worker

Beim Wechsel der Rechnungszeile rief `RechnungenView._update_plc_controls()` bislang synchron die PLC-Archivsuche auf. Die Packlistensuche listet das Verzeichnis und prueft jede gefundene Datei; Label-/Zollpfade pruefen ebenfalls Dateimetadaten. Diese Arbeit laeuft nun im BackgroundJobManager. Die Ergebnisse werden nach Rechnungsschluessel und Archivgeneration zugeordnet; bei einem Auswahlwechsel werden veraltete Antworten verworfen, bei Archivrefresh werden laufende Suchen invalidiert. Menuezeitstempel werden aus dem versionierten Packlistennamen gelesen statt per `stat()` im UI. Ein blockierter Packlisten-Lookup bestaetigt den Qt-Heartbeat; Archivfehler blockieren einen neuen PLC-Auftrag, statt die Dublettenpruefung zu umgehen.

Die vollstaendige `test_rechnungen_view_smoke.py`-Suite besteht mit **95 Tests**; ein zusaetzlicher Test stellt sicher, dass das Packlistenmenue keine Dateimetadaten liest. Gezieltes MyPy fuer `view.py`, globales Ruff und `git diff --check` sind gruen. Die Vollsuite besteht nach Lizenz-PDF- und Archivsuche-Aenderungen mit **2.245 Tests, 5 uebersprungen, 1 bestehender Starlette/httpx-Deprecation-Warnung (159,37 s)**. F17 bleibt teilweise offen, bis die restlichen Dialog-I/O-Pfade weiter geprueft sind.

Nach Rebase auf `bfbb69e` (inklusive der zwischenzeitlichen Inventur-Projektionskorrektur) besteht die Vollsuite erneut mit **2.251 Tests, 5 uebersprungen, 1 bestehender Warnung (159,67 s)**. Die 95 Rechnungsansicht-Smokes, drei gezielten Projection-Regressionen, globales Ruff und gezieltes MyPy fuer `view.py` und `inventory_projection.py` bestehen ebenfalls.

## Fortschreibung G2 - Railway-Preflight reproduzierbar ausgefuehrt

`invoke_inventory_railway_preflight.ps1` funktioniert nun auch ohne globales Railway-Projekt-Linking: Projekt/Environment werden explizit angegeben, Service-IDs aus dem Railway-Inventar aufgeloest und die Projekt-venv fuer den lokalen read-only Python-Aufruf genutzt. PowerShell-Parser und vollstaendiger Railway-Lauf bestanden. Der Lauf vom 12.11.2026 00:11 CET meldet Health HTTP 200, Railway-Worker und Product Hub SUCCESS, Runtime-Readiness Exit 0 und DB-Readiness Exit 2 (`eligible=false`). Runtime-Zugangsdaten fuer sevDesk, Graph und Wix sowie Worker-Service sind `ready`; `inventory_master_enabled=false` und `inventory_shadow_enabled=false`.

Der read-only Snapshot zaehlt 432 Bestandspositionen, 0 Ledger-Bewegungen, 0 Rechnungsbuchungsmarker, 0 Inventur-Sessions, 432 Alarme, 726 Sync-Konflikte (710 offen), 432 Outbox-Ereignisse und 263 archivierte Payloads. Shadow/Ledger-Belege, sevDesk-Drift, Quellenvertrag und Sync-Queue blockieren die DB-Freigabe; Kanalprojektionen und Betriebsfreigabe bleiben `manual`. Provider-natives PostgreSQL-Backup ist im Hobby-Plan weiterhin nicht verfuegbar. G2 bleibt daher BLOCKIERT; es wurden keine Master-/Shadow-Flags oder Bestandsdaten geaendert.

Der produktionsnahe Projektions-Dry-Run auf `2731be8` meldet separat 0 Schreibungen, 0 Konflikte/Fehler und 432 Varianten, die wegen fehlender eindeutiger Wix-Produkt-/Inventarzuordnung uebersprungen wurden. Railway startete den Worker nach Main-Deployments automatisch um 00:07, 00:10 und 00:12 CET; fuer die ersten drei beobachteten Zyklen war Forecast `exit=0`, sevDesk-Sync `exit=1`, Rechnungen `processed=0`/`already_applied=0` und die Kanalprojektion bei `master_enabled=false` uebersprungen. Der Snapshot danach enthaelt weiterhin 0 Ledger-Bewegungen und 0 Buchungsmarker. Der vierte Lauf war beim letzten Log-Snapshot noch aktiv. Der neueste Hub-/Worker-Deploymentstand auf `4aef522` meldet SUCCESS.

### G2-Folgepruefung nach Worker-Abschluss (12.11.2026, 00:17 CET)

Der read-only Railway-Preflight wurde nach Abschluss des Worker-Laufs erneut
ausgefuehrt. Healthcheck HTTP 200, Runtime-Readiness Exit 0 (`eligible=true`) und
DB-Readiness Exit 2 (`eligible=false`) bestaetigen den unveraenderten Zustand;
`inventory_master_enabled` und `inventory_shadow_enabled` bleiben `false`.
Der Snapshot (Export 00:16:53 CET) zaehlt 432 Bestandspositionen, 0
Ledger-Bewegungen, 0 Rechnungsbuchungsmarker, 0 Inventur-Sessions, 432 Alarme,
726 Sync-Konflikte (710 offen), 432 Outbox-Ereignisse und 263 archivierte Payloads.

Der Worker auf Deployment `0108b761-d361-4187-a581-6b9d540c7d4c` (Commit
`4aef522`) beendete Forecast mit Exit 0; der sevDesk-Sync endete mit Exit 1,
`processed=0` und `already_applied=0`. Altbelege mit Unterdeckung, fehlender
stabiler Positions-ID oder uneindeutiger SKU bleiben in `needs_review`. Die
Kanalprojektion wurde wegen `master_enabled=false` uebersprungen. Es wurden keine
Ledger-/Buchungsdaten oder Betriebsflags geschrieben; Codex hat keinen Worker-Lauf
manuell ausgeloest. G2 bleibt BLOCKIERT durch Inventur, Konfliktbereinigung,
Shadow-Nachweis, provider-natives Backup und Betriebsfreigabe.

## Fortschreibung F17 - Produktdruck-Pfadaktionen im Worker

Im `ProductPrintConfigDialog` liefen die Metadatenpruefungen der Aktionen „PDF oeffnen“
(`Path.is_file()`) und „Ordner“ (`Path.exists()`) noch synchron. Auf Netzlaufwerken konnten
sie den UI-Thread blockieren. Beide Pruefungen laufen nun in einem lifecycle-verfolgten
Worker; die Desktop-Oeffnung erfolgt erst nach erfolgreicher Pruefung. Abbruch und
Dialogabschluss invalidieren den Worker, doppelte Pfadaktionen werden waehrenddessen
blockiert.

Zwei neue Qt-Regressionen halten `is_file()` bzw. `exists()` im Worker an und bestaetigen,
dass der Qt-Heartbeat weiterlaeuft und der passende PDF-/Ordnerpfad anschliessend geoeffnet
wird. `test_rechnungen_product_print.py` besteht mit **17 Tests**, Ruff und gezieltes
MyPy fuer `print_dialog.py` (bestehender `fitz`-Importfehlercode gezielt ausgenommen) sind
gruen. Die vollstaendige Rechnungs-UI-/Drucksuite und Hosted CI laufen fuer den neuen
Commit noch.

### F17-Nachtrag - Manuelle Rechnungs-/Label-/Noten-PDF-Einreihung

Der gemeinsame Dialog fuer manuelle Rechnungs-, Label- und Noten-PDFs oeffnete das
PDF nach der Druckerauswahl synchron mit `fitz.open()` und reihte anschliessend den
Druckauftrag im UI-Thread ein. Seitenzaehlung und Queue-Einreihung laufen jetzt in
einem `BackgroundWorker`; die Seitenauswahl wird zuvor im UI aus dem Qt-Druckdialog
in einfache Werte ueberfuehrt. Bei PDF-/Queue-Fehlern bleibt eine konkrete Warnung
am Dialog sichtbar.

Eine Qt-Regression blockiert die PDF-Oeffnung und bestaetigt UI-Heartbeat, korrekten
Seitenbereich und genau einen Queue-Auftrag. `test_rechnungen_product_print.py`
besteht jetzt mit **18 Tests**, globales Ruff und gezieltes MyPy fuer `print_dialog.py`
(gruppierter Fremdimport `fitz` ausgenommen) bestehen. Hosted CI fuer den gepushten
Vorgaengercommit laeuft; der neue Nachtrag wird mit dem Fixcommmit geprueft.

## Fortschreibung F17/F18 - PDF-Aktionen und Druckqueue-Race (12.11.2026)

Die Produktdruck-Konfiguration prueft „PDF oeffnen“ und „Ordner“ jetzt ohne
UI-Thread-Dateizugriffe. Im gemeinsamen manuellen Rechnung-/Label-/Noten-PDF-Dialog
laufen PDF-Seitenzaehlung und Druckqueue-Einreihung ebenfalls im Worker; die
Seitenauswahl wird im UI in einfache Werte umgewandelt. Ein paralleler Erststart
konnte zuvor ausserdem mehrere `_PrintQueueWorker` erzeugen: Workerstart, erster
Queue-Put und Shutdown sind jetzt mit einem gemeinsamen Lock serialisiert, und
neue Einreihungen werden nach Shutdown abgelehnt.

Regressionen blockieren Dateizugriffe und PDF-Oeffnung, pruefen den Qt-Heartbeat,
korrekte Seitenbereiche, genau einen Worker bei zwoelf gleichzeitigen Erstauftraegen
und alle erhaltenen Jobs. Die vollstaendige lokale Suite auf dem Rechnungs-/Druck-
Code-Stand von `2eb98f7` (nach Readiness-Doc-Fast-Forward `7d6b514`) besteht mit
**2.258 Tests, 5 uebersprungen und
1 bestehender Starlette/httpx-Deprecation-Warnung (165,28 s)**. Druck-/Queue-Tests:
23 bestanden; globales Ruff und gezieltes MyPy fuer `print_queue.py` und
`print_dialog.py` gruen. Striktes paketweites MyPy der 27 Rechnungsdateien ist
ebenfalls fehlerfrei; nur der nicht typisierte PyMuPDF-Import wird am Import-
Boundary markiert. Das globale MyPy-Gate bleibt wegen bestehender Fehler in
anderen Dateien separat offen.

### F25 - aktueller Rechnungslisten-/Eventloop-Beleg

Der letzte lokale Lauf mit 50 Rechnungen meldet `Invoice batch metric`
`load_ms=760`, `flags_ms=283`, `rows_ms=0`, `fulfillment_ms=307`, `total_ms=1351`;
diese Gesamtzeit enthaelt den Worker-Abruf. Die dazu protokollierten Eventloop-Gaps
liegen bei 91 ms und 69 ms. Seit dem erfolgreichen START-Lauf um 21:38:58 wurden
acht Eventloop-Samples mit einem Maximum von 116 ms beobachtet. Aeltere 334-487-ms-
Gaps fallen zeitlich in die START-Druckdispatch-Phase; die Logs belegen Korrelation,
aber keine Ursache. Der Rechnungslisten-Anteil ist mit dem aktuellen 50-Zeilen-Lauf abgenommen; die
Produktdruck-Dispatch-Luecken werden getrennt in F27 weiterverfolgt.

### G2 - frischer Produktions-Read-only-Nachweis (12.11.2026, 00:37 CET)

Nach `84cf681` wurde der Worker-Lauf read-only beobachtet: Forecast Exit 0, sevDesk-
Sync Exit 1 mit `processed=0` und `already_applied=0`; die Kanalprojektion blieb bei
`master_enabled=false` aus. Der Preflight danach lieferte Health HTTP 200, Runtime-
Readiness Exit 0 (`eligible=true`) und DB-Readiness Exit 2 (`eligible=false`). Der
Snapshot um 00:36:59 CET zaehlt 432 Bestandspositionen, 0 Ledger-Bewegungen, 0
Rechnungsbuchungsmarker, 0 Inventur-Sessions, 432 Alarme, 726 Sync-Konflikte
(710 offen), 432 Outbox-Ereignisse und 263 archivierte Payloads. Master und Shadow
blieben `false`; es wurden keine Bestands-/Providerdaten geschrieben. G2 bleibt
BLOCKIERT durch Inventur, Konfliktbereinigung, Shadow-Nachweis, Providerprojektionen,
provider-natives Backup und Betriebsfreigabe.

### G2-Folgepruefung nach Mapping-Fix (12.11.2026, 00:49 CET)

Der Worker- und Product-Hub-Deploy auf `894753b` ist SUCCESS (Deployments
`43c530e1-a0ec-485b-921e-1b2a5ac403c4` und `bb5f3c7f-ddfc-4c00-8ae3-28e067b56633`);
Healthcheck HTTP 200. Der automatische Worker-Lauf endete mit Forecast Exit 0,
sevDesk-Sync Exit 1 (`processed=0`, `already_applied=0`) und uebersprungener
Kanalprojektion bei deaktiviertem Master.

Der read-only Snapshot um 00:48:56 CET bestaetigt 432 Bestandspositionen, 0
Ledger-Bewegungen, 0 Rechnungsbuchungsmarker, 0 Inventur-Sessions, 432 Alarme,
726 Sync-Konflikte (710 offen), 432 Outbox-Ereignisse und 263 archivierte Payloads.
Runtime-Readiness Exit 0 (`eligible=true`), DB-Readiness Exit 2 (`eligible=false`).
`legacy_mutation_paths` bleibt `ready`; die Quellenpruefung meldet weiterhin 594
blockierende Auditprobleme, dazu 29 Mengenabweichungen und 710 offene Konflikte.
`inventory_master_enabled=false` und `inventory_shadow_enabled=false`; es gab keine
Ledger-/Buchungs- oder Providerdaten-Schreibungen. G2 bleibt durch Inventur,
Konfliktbereinigung, Shadow-Nachweis, Providerprojektionen, Backup und Sign-off blockiert.

## F17-Fortschreibung - Lageralarm-Popup-Serviceauflösung (12.11.2026)

`InventoryAlertsDialog` löst Inventory-, Task- und Mailservices jetzt erst im
jeweiligen `BackgroundWorker` auf. Damit liegen auch langsame Container-/DB-
Initialisierung beim Öffnen des Lageralarm-Popups nicht mehr im GUI-Thread. Die
Schreibaktionen erfassen ihre UI-Werte vor dem Workerstart und rufen die Services
innerhalb des Jobs auf. Eine neue Regression blockiert `container.resolve()` beim
ersten Laden und bestätigt, dass der Qt-Heartbeat während der Dialogerstellung
weiterläuft. `test_inventory_alerts_dialog.py`: **3 bestanden**; Ruff und striktes
MyPy für das Dialogmodul bestanden. F17 bleibt teilweise offen, bis die übrigen
statischen UI-I/O- und Callback-Pfade vollständig nachgeprüft sind.

## F17-Fortschreibung - Ueberweisungsservice beim Erstladen (12.11.2026)

`OffeneUeberweisungenDialog` erzeugt seinen Graph-/Settings-Service jetzt im
initialen Listen-Worker statt synchron im Konstruktor. Nach erfolgreichem Laden
bleibt dieselbe Serviceinstanz fuer Details und Aktionen erhalten. Ein blockierter
Fake fuer `container.resolve()` bestaetigt den Qt-Heartbeat waehrend des Erstladens.
`test_offene_ueberweisungen_dialog.py`: **9 bestanden**; Ruff und striktes MyPy
fuer das Dialogmodul bestanden. Weitere F17-Pfade bleiben zu auditieren.

## F17-Fortschreibung - Sonderauftragsservice beim Erstladen (12.11.2026)

`SpecialOrderDialog` loest den Wix-/Settings-Service jetzt erst im Worker auf,
der die Artikelliste laedt. Der Dialog wird sichtbar und der Eventloop bleibt
reaktionsfaehig, auch wenn die Servicefactory blockiert. Die Serviceinstanz wird
nach dem Laden fuer die bewusste Payment-Link-Aktion wiederverwendet. Zwei
Qt-Dialogtests, Ruff und striktes MyPy fuer das Dialogmodul bestanden.

## F17-Fortschreibung - Sendungsservice beim Erstladen (12.11.2026)

`OffeneSendungenDialog` erzeugt seinen Graph-/Settings-Service nun ebenfalls erst
im initialen Listen-Worker. Der Worker gibt die Serviceinstanz mit Liste und
Empfaengernamen zurueck; Detail- und Schreibaktionen verwenden danach dieselbe
Instanz. Eine blockierte Servicefactory bestaetigt den Qt-Heartbeat. Die vollstaendige
`test_offene_sendungen_dialog.py`-Suite besteht mit **12 Tests**; Ruff und striktes
MyPy fuer das Dialogmodul sind gruen.

## F17-Fortschreibung - Lieferkorrekturmanager beim Erstladen (12.11.2026)

`CustomerAftercareManagerDialog` loest seinen Repository-/Graph-Service jetzt im
Listenworker auf. Fallliste, Positionen und Aktionen verwenden nach dem ersten
Ergebnis dieselbe Instanz. Ein blockierter Service-Resolver bestaetigt den
Qt-Heartbeat. Die komplette Manager-/Tab-Regression besteht mit **14 Tests**;
Ruff und striktes MyPy fuer den Manager sind gruen.

## F17-Fortschreibung - Zusatzrechnungsdialogservice (12.11.2026)

`CustomerAftercareInvoiceDialog` loest Kontakt-, Rechnungs- und Aftercare-Service
nicht mehr im Konstruktor auf. Kontakte werden im Ladeworker gelesen; Erstellung
und Ueberspringen loesen ihre Services jeweils im bestaetigten Aktionsworker auf.
Ein blockierter Kontaktservice-Resolver bestaetigt den Qt-Heartbeat. Die Dialogsuite
besteht mit **8 Tests**, Ruff und striktes MyPy sind gruen.

## F17-Fortschreibung - PLC-Statistikservice im Worker (12.11.2026)

Beim Oeffnen der PLC-Statistik wurde der Repository-/Datenbankservice im Aufrufer
aufgeloest. Die Aufloesung geschieht jetzt zusammen mit dem Statistikladen im
Dialogworker. Ein blockierter Servicefactory-Fake bestaetigt den Qt-Heartbeat;
`test_plc_statistics_dialog.py` und `test_rechnungen_view_smoke.py` bestehen
zusammen mit **96 Tests**. Ruff und striktes MyPy fuer Dialog und Rechnungsansicht
sind gruen.

## F17-Fortschreibung - Digital-Licenses-Service beim Erstladen (12.11.2026)

`DigitalLicensesDialog` loest seinen Graph-/Settings-Service jetzt im Worker auf,
der die offenen Faelle laedt. Dateizuordnung, Lizenz-PDFs, Outlook-Entwurf und
Fulfillment greifen nach dem Erstladen auf dieselbe Serviceinstanz zu. Ein
blockierter Resolver bestaetigt den Qt-Heartbeat. Die Dialogsuite besteht mit
**10 Tests**; Ruff und striktes MyPy sind gruen.

## Qualitaetslauf nach F17-Serviceauflosungen (12.11.2026)

Nach den sieben Dialogaenderungen auf `00323f0` besteht die lokale Vollsuite mit
**2.268 Tests, 5 optionalen PostgreSQL-Ueberspringungen und 1 bestehenden
Starlette/httpx-Deprecation-Warnung (165,65 s)**. Globales Ruff besteht; striktes
MyPy fuer alle **27 Rechnungs-UI-Quelldateien** meldet 0 Fehler; `git diff --check`
ist sauber. Hosted CI fuer `00323f0` ist beim Dokumentieren noch `in_progress`.

## F17-Fortschreibung - OPEN-PRINTS-Service beim Erstladen (12.11.2026)

`OffeneDruckeDialog` loest den Mailbox-Service jetzt im Listenworker auf und
uebernimmt dessen Diagnosewert dort ebenfalls. Anhangsabruf, lokales Oeffnen und
Erledigen verwenden danach dieselbe Serviceinstanz. Eine blockierte Servicefactory
bestaetigt den Qt-Heartbeat; alle **4 OPEN-PRINTS-Dialogtests**, Ruff und striktes
MyPy fuer das Dialogmodul bestehen.

## F17-Fortschreibung - eingebetteter Nachlieferungs-Tab (12.11.2026)

`CustomerAftercareTab` loest den Aftercare-Service jetzt beim ersten Listenabruf
im Worker auf; Positionen und Fallaktionen verwenden danach dieselbe Instanz.
Das beseitigt die Servicefactory aus dem Rechnungsansicht-Aufbau. Eine blockierte
Factory bestaetigt den Qt-Heartbeat. Die gemeinsame Manager-/Tab-Suite besteht
mit **15 Tests**; Ruff und striktes MyPy fuer den Tab sind gruen.

## F17-Fortschreibung - PLC-Teilerfuellungsread (12.11.2026)

Der PLC-Dialog loest das gemeinsame `SettingKvRepository` jetzt im Kontextworker
auf und liest dort den gespeicherten Teilerfuellungsstand. Der Worker liefert die
berechneten offenen Mengen mit dem Wix-/sevDesk-Kontext; der GUI-Callback fuehrt
keinen PostgreSQL- oder Dateizugriff mehr aus. Fuer manuelle Sendungen wird der
Store nur bei tatsaechlicher Teilerfuellungsbuchung im Finalizer-Worker angelegt.
Die PLC-UI-Suite besteht mit **26 Tests**; Ruff und striktes MyPy fuer den Dialog
sind gruen.

## Vollsuite nach F17-Nachpruefung und PLC-Teilerfuellungsread (12.11.2026)

Auf dem Codecommit `afe5811` besteht die vollstaendige lokale Suite mit **2.272
Tests, 5 optionalen PostgreSQL-Ueberspringungen und 1 bestehenden
Starlette/httpx-Deprecation-Warnung (160,34 s)**. Globales Ruff ist gruen; striktes
MyPy fuer alle 27 Rechnungs-UI-Dateien meldet 0 Fehler; `git diff --check` ist
sauber. Der Hosted-CI-Testjob fuer `afe5811` ist beim Check noch `in_progress`.
Der Railway-Preflight-Fix auf `59ecdde` betrifft nur das read-only Operationsskript;
Product-Hub und Inventory-Worker bauen diesen Stand noch, ohne produktive
Bestandsflags oder -daten zu aendern.

## F17-Fortschreibung - PLC-Paketnachweis im Worker (12.11.2026)

Beim Oeffnen von „PLC-Infos“ loeste `RechnungenView` das
`PlcShipmentRepository` noch synchron auf, bevor der Dialog seine bereits
asynchrone Abfrage startete. Die Repository-Aufloesung erfolgt jetzt im
Ladeworker. Ein blockierter Container-Fake bestaetigt, dass Dialogaufbau und
Qt-Heartbeat weiterlaufen; der Dialog verwendet anschliessend dieselbe
Repository-Instanz fuer Nachladen, Codezuordnung und Trackingimport. Die
Rechnungsansicht- und PLC-Nachweisregressionen bestehen zusammen mit **98 Tests**;
Ruff und striktes MyPy fuer `view.py` und `plc_evidence_dialog.py` sind gruen.
Die Vollsuite auf diesem Arbeitsstand besteht mit **2.273 Tests, 5 optionalen
PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-Deprecation-Warnung
(164,48 s)**. Globales Ruff und striktes MyPy fuer alle 27 Rechnungs-UI-Dateien
sind ebenfalls gruen.

## F27-Fortschreibung - Produktdruck-Dispatch und Eventloop (11.11.2026)

Die laufende Desktop-Instanz startete um 21:36:40 auf dem damaligen Commit
`70ac3c2`. Beim ersten Laden wurden 50 Nichtentwurfsrechnungen in 1.257 ms
vorbereitet (sevDesk-/Kontextladen 557 ms, Flags 286 ms, Fulfillment 412 ms);
der direkte Rechnungs-Auswahl-Paint lag bei 3 ms. Gleichzeitig verzeichnete der
Eventloop 332 ms waehrend des Seitenladens. Beim START-Druck um 21:38 folgten
Luecken von 334 bis 487 ms zeitgleich mit Rechnungs- und Label-Print-Dispatch;
der Produkt-Preflight selbst lief 3.837 ms im Worker. Das trennt die schnelle
Auswahl-Anzeige vom laengeren Worker-Load, bestaetigt aber weiter UI-Luecken ueber
dem 250-ms-Ziel waehrend Druck-Dispatch. Die Instanz laeuft noch mit altem Code;
Das Log stammt von altem Commit `70ac3c2`; der aktuelle Lauf vom 12.11.2026
belegt F25 fuer den Rechnungslisten-Flow, enthielt aber keinen START-Produktdruck.
F27 bleibt offen, bis der aktuelle Druckdispatch ohne unbeabsichtigte physische
Ausgabe mit Fake-/Qt-Heartbeat-Messung und spaeterem Testdruck abgenommen ist.

### F17-Fortschreibung - Produktdruck-Konfiguration beim ersten Druck

`print_dialog.py::_configure_missing_piece_print` speichert bestaetigte
Produktdruck-Konfiguration jetzt in einem `BackgroundWorker`; Settings-Commit,
Katalog-Neuladen und Teileaufloesung laufen ausserhalb des UI-Threads. Der
aufrufende Einzel- oder Sammeldruck setzt erst nach Rueckkehr aus dem laufenden
Qt-Eventloop fort und bleibt bei Speicherfehlern geschlossen. Ein Regressionstest
haelt den Settings-Write an, bestaetigt Qt-Heartbeats, erzwingt einen
voruebergehenden Fehler und prueft den erfolgreichen Retry. Die 18 Tests aus
`test_rechnungen_product_print.py`, Ruff und striktes MyPy fuer
`print_dialog.py` sind gruen. Die Vollsuite besteht mit **2.273 Tests, 5
uebersprungen und 1 bestehender Starlette/httpx-Deprecation-Warnung (159,92 s)**.
F17 bleibt wegen weiterer offener UI-I/O-Pfade teilweise offen.

## F17-Fortschreibung - OPEN-PRINTS-Dateipruefung im Worker (12.11.2026)

Nach dem asynchronen Attachment-Download prueft `OffeneDruckeDialog` den lokalen
Dateipfad jetzt noch im Download-Worker. Der UI-Callback startet nur den
Windows-Datei-Handler und liest keine Dateimetadaten. Ein Regressionstest verfolgt
den Thread von `Path.is_file()` und bestaetigt die UI-Oeffnung des heruntergeladenen
Pfads. Alle **5 OPEN-PRINTS-Dialogtests**, Ruff und striktes MyPy fuer das
Dialogmodul sind gruen. Die Vollsuite nach beiden F17-Druck-/OPEN-PRINTS-
Aenderungen besteht mit **2.274 Tests, 5 uebersprungen und 1 bestehender
Starlette/httpx-Deprecation-Warnung (158,75 s)**; globales Ruff und der
`git diff --check` sind gruen.

## F17-Fortschreibung - Druckplan-Hinweis beim Konfigurationsdialog (12.11.2026)

Die Materialisierung bestehender Druckkonfiguration vor einem Druck und der rein
informative Lookup weiterer Titel-Druckplaene loesen `ProductCatalogService` jetzt
erst im Worker auf. Der Dialog zeigt den Hinweis nach erfolgreichem Read asynchron
an und verwirft spaete Resultate beim Schliessen. Blockierte Katalog-Fakes pruefen
Qt-Heartbeats und die spaete Anzeige; `test_rechnungen_product_print.py` besteht
mit **20 Tests**, Ruff und striktes MyPy fuer `print_dialog.py` sind gruen. Die
Vollsuite nach dem Katalog-Read-Nachtrag besteht mit **2.276 Tests, 5
uebersprungen und 1 bestehender Starlette/httpx-Deprecation-Warnung (156,34 s)**.

## F17-Fortschreibung - Ueberweisungs-PDF-Dateipruefung im Worker (12.11.2026)

`OffeneUeberweisungenDialog` schreibt die heruntergeladene Rechnungs-PDF und
prueft deren Vorhandensein jetzt vollstaendig im Aktionsworker. Der UI-Callback
startet danach nur den Windows-Datei-Handler. Ein Regressionstest blockiert den
Netzwerkabruf, bestaetigt den Qt-Heartbeat und verfolgt `Path.is_file()` als
Worker-Aufruf. Die 9 Dialogtests, Ruff und striktes MyPy fuer das Dialogmodul sind
gruen. Die Vollsuite nach beiden Dateipruefungen besteht mit **2.274 Tests, 5
uebersprungen und 1 bestehender Starlette/httpx-Deprecation-Warnung (149,06 s)**.

## Railway-Produktionsread-only-Check (12.11.2026)

`XW-Office` production hat keine staged changes. Product Hub und Inventory Worker
laufen auf `main` mit SUCCESS-Deployments vom 12.11.2026; beide PostgreSQL-Services
sind ebenfalls online. Die Health-Uebersicht zaehlt 135 historische Product-Hub-
und 7 Inventory-Worker-Fehldeployments in den letzten 72 Stunden, aber keine
Fehler seit den aktuellen erfolgreichen Deployments. Ein ausgelesener Product-Hub-
Fehllauf vom 11.11. scheiterte am fehlenden `stdnum`; der spaetere erfolgreiche
Stand enthaelt die Abhaengigkeit. Keine Railway-Konfiguration oder Produktivdaten
wurden geaendert. In den XW-Office-Deploydateien ist keine Cloudflare-Anbindung
gefunden; die verfuegbare Cloudflare-Integration bezieht sich auf ChatGPT-Sites
und ist fuer dieses native Rechnungsmodul nicht anwendbar.

## F17-Fortschreibung - Nachlieferungs-Tab-Serviceaufloesungen (12.11.2026)

Im eingebetteten Nachlieferungs-Tab wurden `OffeneSendungenService` vor dem
Workerstart fuer Lieferschein-Anzeige, Lieferscheindruck und Labeldruck sowie das
`CustomerAftercareRepository` vor dem Workerstart beim Speichern einer manuellen
Nachlieferung aufgeloest. Alle vier Aufloesungen liegen jetzt in den jeweiligen
Aktionsworkern. Eine blockierte Servicefactory beim Anzeigen eines Lieferscheins
belegt den weiterlaufenden Qt-Eventloop und die verzugsfreie PDF-Oeffnung nach
Freigabe. `CustomerAftercareManagerDialog` loest die Verfuegbarkeit des
relationalen Repositorys und den Legacy-`OffeneSendungenService` ebenfalls im
Worker auf; eine Sequenzpruefung verwirft die Antwort, wenn waehrenddessen ein
anderer Fall ausgewaehlt wurde. Der blockierte Repository-Fake bestaetigt den
Qt-Heartbeat und dass der Dialog erst nach der Resolver-Antwort erscheint.
`test_customer_aftercare_manager_dialog.py`: **17 Tests bestanden**; striktes
MyPy fuer beide Nachbetreuungsdateien und alle 27 Rechnungs-UI-Dateien sowie
globales Ruff sind gruen. Die Vollsuite besteht mit **2.278 Tests, 5 optionalen
PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-Deprecation-Warnung
(148,19 s)**. F17 bleibt offen, bis die restlichen UI-I/O- und Lifecycle-Pfade
geprueft sind.

## F17-Fortschreibung - Unreleased-Titelaufloesung im Worker (12.11.2026)

Beim Starten der Konfiguration fuer einen unbekannten Wix-Titel loeste
`_create_unreleased_product_from_alias` den Produktkatalog synchron auf und las
Alias-Mapping sowie vorhandene Katalogprodukte im UI-Thread. Diese Reads laufen
jetzt vor dem Edit-Dialog in einem `BackgroundWorker`; der Dialog wird nach dem
Ergebnis geoeffnet und der bestehende Settings-Write bleibt im bestaetigten
Workerpfad. Der Regressionstest blockiert die Titelaufloesung gezielt, prueft
einen Qt-Heartbeat und gibt den Worker auch bei einem fehlschlagenden Testlauf
zuverlaessig frei. Die Rechnungsansicht-Smoke-Suite besteht mit **95 Tests**,
der fokussierte Fortsetzungs-/Speicherpfad mit **2 Tests**; Ruff und striktes
MyPy fuer `view.py` sowie striktes MyPy fuer alle 27 Rechnungs-UI-Dateien sind
gruen. Die Vollsuite besteht mit **2.278 Tests, 5 optionalen PostgreSQL-
Ueberspringungen und 1 bestehenden Starlette/httpx-Deprecation-Warnung
(156,03 s)**; globales Ruff und `git diff --check` sind ebenfalls gruen. F17
bleibt bis zur Pruefung der uebrigen UI-I/O- und Lifecycle-Pfade offen.

## F17-Fortschreibung - kalte Produktkatalog-Aufloesung im START-Panel

Auch der Kaltpfad beim Anzeigen von START-Produktdetails ist jetzt abgesichert:
`_on_stuecke_loaded` verwendet nur eine bereits aufgeloeste Kataloginstanz im
GUI-Thread. Fehlt sie oder ist der Unreleased-Katalog noch nicht geladen,
uebernimmt ein sequenzgesicherter Worker sowohl `Container.resolve()` als auch
den ersten Settings-/Datei-Read. Ein blockierter Fake prueft Worker-Thread,
laufenden Qt-Heartbeat und spaetere Darstellung. Die Rechnungsansicht-Smoke-Suite
besteht mit **96 Tests**, striktes MyPy fuer alle 27 Rechnungs-UI-Dateien und
globales Ruff sind gruen. Die Vollsuite besteht mit **2.279 Tests, 5 optionalen
PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-Deprecation-Warnung
(150,87 s)**. F17 bleibt bis zum Abschluss der uebrigen UI-I/O- und
Lifecycle-Pruefung offen.

## F17-Fortschreibung - START-Verlauf im Hintergrund persistieren

Der gespeicherte PRINT-/UNRELEASED-Verlauf wurde beim Oeffnen synchron aus
SettingKV bzw. der lokalen Datei gelesen und nach START synchron geschrieben.
Beide Serviceaufloesungen und I/O-Vorgaenge laufen jetzt ueber einen
lifecycle-verfolgten Worker. Ein nachfolgender START-Snapshot wartet auf einen
laufenden Write und wird danach serialisiert gespeichert, sodass der neueste
Lauf nicht von einem aelteren, spaeter abgeschlossenen Write ueberschrieben wird.
Die ungenutzten synchronen Legacy-Lese-/Schreib-Helfer fuer denselben Snapshot
wurden entfernt.
Die Tests blockieren Read und Write, pruefen Qt-Heartbeats, Thread-Grenzen,
Restore nach Neustart und die Reihenfolge zweier Writes. `test_rechnungen_view_smoke.py`
besteht mit **98 Tests**; globales Ruff und striktes MyPy fuer alle 27
Rechnungs-UI-Dateien sind gruen. Die Vollsuite besteht mit **2.281 Tests, 5
optionalen PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-
Deprecation-Warnung (155,45 s)**. F17 bleibt fuer die weiteren UI-I/O- und
Lifecycle-Pfade offen.

## F17-Fortschreibung - Print-Produkte-Zeilen ohne synchronen Kataloglookup

Der Aufbau der sichtbaren Print-Produkte-Zeile fragte den Unreleased-Katalog
noch einmal synchron nach dem kanonischen Titel ab, obwohl dieselbe Aufloesung
bereits im Worker vorbereitet wurde. Die Zeile liest jetzt ausschliesslich den
vorbereiteten Cache; nach einer bestaetigten Titelanlage wird der sichtbare
Eintrag unmittelbar im UI-Cache auf den kanonischen Namen umgestellt. Ein
Kaltstarttest verhindert `ProductCatalogService.resolve()` beim Zeilenaufbau;
die bestehende Alias-Regression prueft weiterhin die sofortige Aktualisierung
vor dem Druckdialog. Die Rechnungsansicht-Smoke-Suite besteht mit **99 Tests**,
Ruff global und striktes MyPy fuer alle 27 Rechnungs-UI-Dateien sind gruen. Die
Vollsuite besteht mit **2.282 Tests, 5 optionalen PostgreSQL-Ueberspringungen
und 1 bestehenden Starlette/httpx-Deprecation-Warnung (150,15 s)**.

## F18-Fortschreibung - START-Verlauf-Worker beim Schliessen

Der Persistenzworker fuer START-Verlaeufe ist Teil des Rechnungsansicht-
Shutdown-Snapshots. Eine Regression haelt den ersten SettingKV-Write an, reiht
einen neueren Lauf ein, fordert das Schliessen an und bestaetigt, dass die
GUI-Methode sofort zurueckkehrt, der Shutdown-Zustand bis zum Ende beider Writes
offen bleibt und danach der neueste Lauf gespeichert ist. Der fokussierte
Test `test_start_history_settings_write_runs_off_ui_thread_and_keeps_latest_run`
besteht.

## F18-Fortschreibung - Nachlieferungsdialog nach Shutdown unterdruecken

Ein verspätetes Ergebnis der Nachlieferungsvorbereitung konnte nach Beginn des
Rechnungsansicht-Shutdowns noch den Dialog oeffnen; auch spaete Erfolgs- und
Fehlermeldungen waren moeglich. Die vier Ergebnis-/Fehler-Callbacks kehren bei
aktivem Shutdown jetzt ohne UI-Aktion zurueck. Eine blockierte Worker-Regression
bestaetigt, dass `prepare_shutdown()` nicht wartet und nach Freigabe des Workers
kein Dialog erscheint. Das Audit erfasste zusaetzlich spaete Rechnungslisten-,
Such-, Badge- und offene Produktuebersicht-Callbacks: sie verwerfen jetzt
Ergebnisse und Fehler nach Shutdown; der Rechnungslisten-Worker startet nach
Shutdown keine automatische Folgeseite. Eine Regression prueft, dass nach
Shutdown keine Warnungen, Badgeaenderungen oder Counts auftreten. Der
Rechnungsansicht-Smoke-Satz prueft zusaetzlich PDF-Vorschau, Kunden-Mail,
Entwurfloeschung, Sammel-/Einzeldruck, Fulfillment und Entwurfsfehler: nach
Shutdown erscheinen keine Dialoge und externe PDF-Oeffnungen werden verworfen.
Weitere Abschluss-Callbacks starten nach Shutdown keine offene Uebersicht,
Produktvorbereitung, Hint-Vorladung oder nachfolgenden Sammeldrucke; eine
verspaetete Produktvorpruefung startet keinen neuen sevDesk-Entwurf. Draft-
Vorschaufehler und -ergebnisse sowie geladene sevDesk-Detailkontexte greifen
nach Shutdown nicht mehr auf Dialoge oder Widgets zu. Die Regression prueft
diese Follow-up-Grenzen direkt. Der Smoke-Satz besteht mit **104 Tests**;
globales Ruff und striktes MyPy fuer alle 27 Rechnungs-UI-Dateien sind gruen.
Die Vollsuite besteht mit **2.287 Tests, 5 optionalen
PostgreSQL-Ueberspringungen und 1 bestehenden Starlette/httpx-Deprecation-
Warnung (164,16 s)**. Die Lifecycle-Pruefung F18 ist nach dem Audit aller
betroffenen Worker-, Dialog- und Close-Pfade abgeschlossen.

## F25-Fortschreibung - vorbereitete Rechnungszeilen und Live-Profil

Ein reproduzierbarer Qt-Smoke-Test spielt 50 bereits normalisierte Rechnungszeilen durch `_apply_load_result_data`, einschliesslich Sortierung, Tabellenmodell und Detailrefresh; die UI-Blockade bleibt unter 250 ms. Der Desktop-Loglauf vom 12.11.2026 auf Commit `c5629ea` zeigt beim Laden der 50 neuesten Nicht-Entwurfsrechnungen eine Hintergrunddauer von **1.353 ms**: Load 891 ms, Flags 288 ms, Fulfillment 171 ms und Row-Aufbereitung 1 ms. Beim Anwenden lag die gemessene Eventloop-Luecke bei **55 ms**. Das UI-Apply-Metriklogging greift ab 100 ms und erzeugte fuer diesen Lauf keinen Eintrag. Eine separate 381-ms-Luecke trat beim App-Start vor dem Listenladen auf und wird nicht der Tabellenaktualisierung zugerechnet. F25 ist fuer den Listen-Flow abgenommen; allgemeines Startup-Profiling liegt ausserhalb dieses Befunds.

## F20-Fortschreibung - Customer-Aftercare-Migrationsschema

Der strict-MyPy-Sweep fuer `ProductsView`, alle neun Customer-Aftercare-Services sowie `invoice_processing`, `sevdesk` und `draft_invoice` ist fehlerfrei. Zwei Customer-Aftercare-Migrationen hatten noch untypisierte SQLAlchemy-Spaltenobjekte. Die Spalten-Mappings sind jetzt als `dict[str, sa.Column[Any]]` typisiert. Ein SQLite-Regressionslauf prueft beide Migrationen zweimal auszufuehren, den Index und anschliessenden Downgrade auf die unveraenderten Ursprungsspalten. Der Migrationstest besteht; strict MyPy fuer beide Migrationen und Ruff fuer alle geaenderten Dateien sind gruen. Die Vollsuite besteht mit **2.290 Tests, 5 Ueberspringungen und 1 bestehenden Starlette/httpx-Warnung (192,36 s)**. Die globale lokale MyPy-Baseline sank auf **315 Fehler in 57 Dateien**. F20 und die Controller-Extraktion bleiben offen.

## F20-Fortschreibung - Graph-Nachrichten mit fehlenden Teilobjekten

Die Inbox-Auswertung behandelte optionale Graph-Objekte wie `body`, `from`,
`emailAddress`, `flag`, sevDesk-`contact` und Wix-`buyerInfo` nicht ueberall
null-sicher. Normalisierung auf leere Dictionaries verhindert Fehler bei
unvollstaendigen API-Nachrichten. Ein Regressionstest deckt null-Werte ab und
stellt sicher, dass BodyPreview und Kandidatenerkennung weiter funktionieren.
Ausserdem ist der Vorschlagsparameter von `list` auf `Sequence` erweitert, und
ein lokaler Variablenname kollidiert nicht mehr mit dem booleschen
Mailbox-Kennzeichen. Inbox-Tests: **5 bestanden**; Strict MyPy und Ruff fuer
die betroffene Datei sind gruen. Die Vollsuite besteht mit **2.289 Tests, 5
Ueberspringungen und 1 bestehenden Warnung (159,56 s)**. Die globale MyPy-
Baseline sank weiter auf **318 Fehler in 59 Dateien**. F20 bleibt offen.
