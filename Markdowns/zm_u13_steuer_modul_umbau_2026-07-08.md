# Zusammenfassende Meldung U13 - Umbauskizze fuer Steuern

Stand: 2026-07-08  
Ziel: Die funktionierende Legacy-Zusammenfassende Meldung aus `C:\Users\bernh\GitHub\sevDesk` kontrolliert, verbessert und als eigenstaendiger Bereich im PySide6-Modul `Steuern` von XW-Studio nutzbar machen, inklusive U13-Sendung an FinanzOnline.

## Kurzfazit

In XW-Studio gibt es bereits gute technische Vorarbeit fuer ZM/U13: `ZmService`, `u13_xml.py`, FileUpload-Backend und eine gekoppelte `UVA + ZM`-Sendung. Was fehlt, ist die vollwertige Legacy-Paritaet als eigener UI-Bereich im Untermenue `Steuern`.

Die Legacy-App hatte unter `Steuern-Management` einen eigenen Modus `Zusammenfassende Meldung` mit:

- eigener Monatsauswahl,
- Abruf/Stop,
- Fortschritt,
- Zusammenfassung und Details,
- UID-Korrektur,
- U13-Vorschau,
- Test-/Produktivmodus,
- DataBox-Protokollabruf,
- Preflight gegen bereits eingereichte U13-Meldungen.

Empfehlung: In XW-Studio bleibt `Steuern` das Hauptmodul, aber ZM/U13 bekommt einen eigenen, sichtbaren Arbeitsbereich neben UVA und EU-OSS. Die bestehende automatische U13-Nachsendung nach U30 sollte optional bleiben, aber die neue Hauptbedienung fuer U13 wird eigenstaendig und kontrollierbar.

## Offizielle Kontrollpunkte

Diese Punkte wurden am 2026-07-08 kurz gegen offizielle Quellen geprueft:

- Das BMF beschreibt fuer Datenstromuebermittlung, dass externe Software XML-Dateien nach den veroeffentlichten Strukturen erzeugt; beim Absenden erfolgt eine formale Pruefung, die inhaltliche Verarbeitung wird ueber das Uebermittlungsprotokoll in den Nachrichten beurteilt. Eine Testuebermittlung gilt nicht als eingebracht. Quelle: BMF, "Informationen fuer die Datenstromuebermittlung"  
  https://www.bmf.gv.at/services/finanzonline/informationen-fuer-softwarehersteller/datenstromuebermittlung.html

- Laut USP/BMF sind in die ZM innergemeinschaftliche Lieferungen, Verbringungen und bestimmte grenzueberschreitende Dienstleistungen aufzunehmen; pro UID ist der Gesamtwert fuer den Meldezeitraum anzugeben. Wenn keine meldepflichtigen Umsaetze vorhanden sind, ist keine ZM zu uebermitteln. Die ZM ist elektronisch ueber FinanzOnline einzureichen. Quelle: USP, "Zusammenfassende Meldung (ZM)", letzte Aktualisierung 2026-01-01  
  https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/zusammenfassende-meldung-zm.html

Konsequenz fuer die App: Ein erfolgreicher SOAP/FileUpload-Rueckgabecode reicht als UI-Erfolg nicht aus. XW-Studio sollte Upload, DataBox-Protokoll und Einbringungsstatus getrennt anzeigen.

## Relevante Legacy-Funde

### Konsolen-Skript

Datei: `C:\Users\bernh\GitHub\sevDesk\Zusammenfassende Meldung.py`

Fachlogik:

- Monatseingabe `MM/YY`.
- Rechnungsabruf mit `embed=contact`.
- Filter:
  - `invoiceDate_from`
  - `invoiceDate_to`
  - finalisierte Rechnungen `status >= 100`
  - innergemeinschaftlich ueber `taxType == "eu"` oder `taxRule.id == "3"`
- UID:
  - Normalisierung auf Grossbuchstaben und alphanumerisch.
  - Pruefung mit `python-stdnum`.
  - bei ungueltiger UID interaktive Korrektur.
- Betrag:
  - Netto aus `sumNet`, Fallback `sumNetAccounting`.
  - kaufmaennische Rundung auf ganze Euro.
- Ausgabe:
  - Summen je UID.
  - ungueltige UID mit Rechnungsnummern.

Diese Logik war die robuste fachliche Basis.

### Legacy-PyUI im Steuern-Modus

Datei: `C:\Users\bernh\GitHub\sevDesk\sevdesk_wix_fulfillment\ui\uva_panel.py`

Relevante Struktur:

- `OPTIONS = ["UVA", "Zusammenfassende Meldung", "EU-OSS"]`
- eigener Frame fuer `Zusammenfassende Meldung`
- UI-Elemente:
  - `Monat/Jahr`
  - `Abruf starten`
  - `Stop`
  - Fortschritt
  - `Zusammenfassung`
  - `Details`
  - `FinanzOnline Uebermittlung (U13)`
  - `Vorschau (U13)`
  - `Daten an Finanzonline senden (U13)`
  - `Testmodus (T)`
  - `Protokoll oeffnen`
  - `DataBox aktualisieren`

Wichtige Legacy-Funktionen:

- `_run_zm_v2()`
  - ruft Rechnungen und CreditNotes ab,
  - sammelt nach UID,
  - zieht CreditNotes mit negativem Vorzeichen ab,
  - speichert UID-Korrekturen in `state.json`,
  - blockiert Upload bei ungueltiger/fehlender UID,
  - erzeugt `ZMResult`.

- `_on_zm_finanzonline_preview()`
  - baut U13-XML,
  - validiert gegen XSD,
  - zeigt Vorschau plus XML.

- `_on_zm_finanzonline_send()`
  - blockiert bei fehlenden Daten, ungueltigen UIDs oder keinen Zeilen,
  - prueft FinanzOnline ENV,
  - validiert XSD,
  - fragt vor Sendung explizit nach,
  - prueft DataBox auf bereits eingereichte U13,
  - fragt bei Treffer nach Berichtigung,
  - sendet U13,
  - holt nach Upload das Protokoll.

- `_on_zm_finanzonline_databox_refresh()`
  - listet DataBox-Eintraege,
  - sucht passendes U13-Protokoll,
  - speichert Protokoll lokal.

Das ist fachlich der Zielumfang fuer die PySide6-Migration.

### Legacy-FinanzOnline-Schicht

Datei: `C:\Users\bernh\GitHub\sevDesk\finanzonline_zm.py`

Kernfunktionen:

- `ZMRow`, `ZMResult`, `SubmissionReceipt`
- `build_u13_xml_from_zm_result()`
- `validate_u13_xml()`
- `format_u13_preview()`
- `send_u13_to_finanzonline()`
- Protokollspeicherung unter `analysis_cache/finanzonline/protocols`

Wichtig: Legacy kapselt Upload und Protokollsuche staerker als die aktuelle XW-Studio-U13-Sendung.

## Aktueller XW-Studio-Stand

### UI

Datei: `src/xw_studio/ui/modules/taxes/view.py`

Aktuell:

- `QTabWidget` mit:
  - `UVA`
  - `EU-OSS`
  - `Ausgaben`
- Im UVA-Tab:
  - Button `UVA berechnen`
  - Button `UVA + ZM an FinanzOnline senden`
  - ZM-Preview wird als Textblock in die UVA-Ausgabe gemischt.

Problem:

- ZM ist nicht eigenstaendig bedienbar.
- Keine eigene ZM-Tabelle.
- Keine eigene U13-Vorschau.
- Keine eigene U13-Sendung.
- Kein sichtbarer DataBox-/Protokollstatus fuer U13.
- Keine UID-Korrekturverwaltung in der PySide6-Oberflaeche.

### Services

Datei: `src/xw_studio/services/finanzonline/zm_service.py`

Bereits gut:

- Soll-Berechnung nach `invoiceDate`.
- Filter auf ZM-relevante Rechnungen.
- UID-Normalisierung und Validierung.
- Gruppierung nach UID und Art:
  - `delivery`
  - `service`
  - `dreieck`
- `render_preview_text()`.

Wichtige Luecke gegenueber Legacy:

- `ZmInvoiceProvider` liefert aktuell nur Rechnungen.
- CreditNotes werden im aktuellen Service nicht verarbeitet.
- UID-Korrekturen koennen nicht gepflegt oder persistent angewandt werden.
- Detailzeilen je Rechnung/CreditNote fehlen als strukturiertes Ergebnis.

Datei: `src/xw_studio/services/finanzonline/u13_xml.py`

Bereits gut:

- U13-XML-Erzeugung.
- XSD-Validierung.
- `SOLEI=J` fuer sonstige Leistungen.
- `DREIECK=J` fuer Dreieck.
- Kundinfo wird gekuerzt.

Datei: `src/xw_studio/services/finanzonline/uva_soap.py`

Bereits gut:

- FileUpload-Backend kann `U30` und `U13` senden.
- Session-Login, Upload, Logout.
- XSD-Validierung vor Upload.

Luecken:

- Kein DataBox-Download im XW-Studio-FinanzOnline-Backend.
- Kein Preflight gegen bereits eingereichte U13.
- `UvaSubmitResult` hat kein eigenes Protokollfeld fuer gespeicherte U13-Protokolle.
- Upload-Rueckmeldung und endgueltiger Einbringungsstatus werden nicht sauber getrennt.

Datei: `src/xw_studio/services/finanzonline/uva_service.py`

Aktuell:

- `calculate_month()` berechnet UVA und haengt `zm_text` an.
- `submit_month()` sendet zuerst U30, danach U13, wenn ZM-Zeilen vorhanden sind.

Problem:

- Der gekoppelte Pfad ist praktisch, aber fuer Kontrolle ungeeignet, wenn man U13 separat pruefen oder erneut senden muss.
- Eine U13-Berichtigung nach bereits gesendeter U30 ist in der UI nicht sauber abbildbar.

## Zielbild fuer PySide6

### Steuern-Navigation

Kurzfristig kann `QTabWidget` weiter genutzt werden, weil `Steuern` aktuell nur wenige Bereiche hat. Mittelfristig ist eine vertikale Auswahl wie im Legacy-Frame sauberer:

- `UVA / U30`
- `Zusammenfassende Meldung / U13`
- `EU-OSS`
- `Ausgaben`

Wenn der Umbau klein bleiben soll, reicht Phase 1 mit einem neuen Tab `ZM / U13` zwischen UVA und EU-OSS. Wenn der Steuern-Bereich weiter wachsen soll, sollte direkt eine linke Auswahl mit `QStackedWidget` gebaut werden.

Empfehlung: Fuer diesen Umbau direkt eine kompakte linke Auswahl in `TaxesView`, weil damit U30, U13 und OSS als getrennte Workflows sichtbar werden und nicht mehrere breite Tabs um Platz konkurrieren.

### ZM/U13-Seite

Obere Steuerleiste:

- Jahr
- Monat
- optional spaeter: Quartal/Monat-Modus
- Button `ZM berechnen`
- Button `Stop`
- Button `Neu aus sevDesk laden`
- Datenstand/Quelle

KPI-Zeile:

- gepruefte Rechnungen
- ZM-relevante Rechnungen
- beruecksichtigte CreditNotes
- UID-Zeilen
- Summe gerundet
- blockierende Fehler

Hauptbereich:

- Tabelle `ZM-Zeilen`
  - UID
  - Kunde
  - Art (`Lieferung`, `Sonstige Leistung`, `Dreieck`)
  - Betrag gerundet
  - Rechnungen
  - CreditNotes
  - Status

- Tabelle oder Detailbereich `Belege`
  - Belegtyp (`Invoice`, `CreditNote`)
  - Nummer
  - Datum
  - Kunde
  - UID roh
  - UID normalisiert
  - Netto roh
  - Vorzeichen
  - ZM-Art
  - Grund der Auswahl

- Bereich `Pruefungen`
  - ungueltige/fehlende UIDs
  - AT-UID versehentlich in EU-Umsatz
  - Betrag auf 0 gerundet
  - Rechnung ohne Kontakt/UID
  - nicht klassifizierbare EU-Steuerlogik

FinanzOnline-Bereich:

- `U13-Vorschau`
- `XML anzeigen`
- `XML speichern`
- `Testmodus (T)` als Default aktiv
- `Produktiv senden` nur mit zweistufiger Bestaetigung
- `DataBox Preflight`
- `DataBox Protokoll aktualisieren`
- `Protokoll oeffnen`
- klares Statusmodell:
  - `berechnet`
  - `XML validiert`
  - `Testupload OK`
  - `Produktivupload angenommen`
  - `Protokoll gefunden`
  - `eingebracht laut Protokoll`
  - `Protokoll fehlt`
  - `Fehler`

## Fachliche Regeln

### Zeitraum

Start mit Monatsmeldung, weil Legacy und aktuelle Services monatlich arbeiten.

Optional spaeter:

- Quartalsmodus, wenn fuer den Betrieb relevant.
- Automatischer Vorschlag nach Umsatzschwellen nur als Hinweis, nicht als harte Steuerlogik.

### Berechnungsprinzip

ZM/U13 bleibt eine Soll-Berechnung nach Rechnungsdatum.

Nicht mit UVA-IST verwechseln:

- UVA in XW-Studio: IST nach Zahlungsdaten.
- ZM/U13: Soll nach `invoiceDate` bzw. `creditNoteDate`.

Die UI muss das sichtbar sagen, damit man Monatsabweichungen zwischen UVA und ZM nicht als Fehler interpretiert.

### Auswahl ZM-relevanter Umsaetze

Aus Legacy und aktuellem Service:

- innergemeinschaftliche Lieferung:
  - `taxType == "eu"`
  - oder `taxRule.id == "3"`
  - oder Steuertext enthaelt innergemeinschaftliche Lieferung
- sonstige Leistung:
  - `taxRule.id in {"5", "21"}`
  - oder Steuertext enthaelt `Reverse Charge` / `Sonstige Leistung`
- Dreieck:
  - Steuertext enthaelt `DREIECK`

Verbesserung:

- Auswahlgrund je Beleg speichern.
- Belege nicht nur aggregiert anzeigen.
- Klassifikation testbar machen.

### UID

Regeln:

- UID normalisieren: Grossbuchstaben, nur alphanumerisch.
- UID mit `python-stdnum` pruefen.
- AT-UID fuer ZM-Ausland blockieren.
- Fehlende/ungueltige UID blockiert Produktivsendung.
- UID-Korrekturen persistent speichern, aber sichtbar machen.

Persistenzvorschlag:

- DB-Key `taxes.zm.uid_corrections`
- Fallback ohne DB: `state/finanzonline/zm_uid_corrections.json`

UI:

- Button `UID korrigieren`
- Dialog:
  - Kunde
  - Belegnummern
  - alte UID
  - neue UID
  - Validierung sofort
  - Option `Korrektur dauerhaft merken`

### CreditNotes

Legacy `_run_zm_v2()` beruecksichtigt CreditNotes. XW-Studio sollte das wieder tun.

Regeln:

- CreditNotes nach `creditNoteDate`.
- CreditNotes mit ZM-relevanter Steuerlogik und EU-Kontakt beruecksichtigen.
- Betrag mit negativem Vorzeichen aggregieren.
- Wenn CreditNote keine Kontakt-/UID-Daten eingebettet hat:
  - Kontakt-Fallback laden.
  - optional Ursprungrechnung laden, aber im Ergebnis als Fallback kennzeichnen.

Wichtig: Die aktuelle XW-Studio-Implementierung hat diesen Teil nicht vollstaendig. Das ist der groesste fachliche Paritaets-Gap gegenueber der funktionierenden Legacy.

### Nullmeldung

Wenn keine ZM-Zeilen vorhanden sind:

- Keine U13 senden.
- UI zeigt `Keine ZM-relevanten Umsaetze fuer diesen Zeitraum`.
- Kein Fehlerzustand.

## Service-Umbau

### Neue/erweiterte Modelle

Erweiterung von `zm_service.py`:

- `ZmDocumentRow`
  - `source_type`: `invoice` oder `credit_note`
  - `source_id`
  - `number`
  - `date`
  - `customer`
  - `uid_raw`
  - `uid_normalized`
  - `uid_valid`
  - `kind`
  - `amount_net`
  - `signed_amount_net`
  - `selection_reason`
  - `warnings`

- `ZmCorrection`
  - `source_uid`
  - `target_uid`
  - `created_at`
  - `note`

- `ZmCalculationResult` erweitern:
  - `document_rows`
  - `creditnotes_considered`
  - `corrections_applied`
  - `blocking_errors`
  - `source_stats`

### Provider

Aktueller Provider:

- `load_invoices(year, month)`

Erweitern zu:

- `load_invoices(year, month)`
- `load_credit_notes(year, month)`
- `load_contact(contact_id)`
- optional `load_origin_invoice(invoice_id)`

Konkrete Klasse:

- `SevdeskZmDocumentProvider`
  - nutzt `SevdeskConnection`
  - paginiert wie Legacy
  - `embed=contact`
  - Kontakt-Fallback wie aktueller Provider
  - getrennte Fetch-Statistik fuer Rechnungen und CreditNotes

### XML/Submission

`u13_xml.py` ist fachlich als Startpunkt gut. Ergaenzen:

- XML-Export als Datei aus UI.
- Preview-Dataclass:
  - `xml_payload`
  - `validated`
  - `validation_error`
  - `file_name`

`uva_soap.py` erweitern oder eigene Klasse:

- `FinanzOnlineFileUploadBackend` um DataBox-Funktionen erweitern, oder separater `FinanzOnlineDataboxClient`.
- Ergebnis fuer U13:
  - `upload_rc`
  - `upload_message`
  - `session_id`
  - `xml_validated`
  - `protocol_path`
  - `protocol_status`
  - `is_test_mode`

Wichtig: Nicht alles in `UvaSubmitResult` stopfen. Besser:

- `FinanzOnlineUploadResult`
- `FinanzOnlineProtocolResult`
- `ZmSubmitResult`

### Idempotenz und Preflight

Vor Produktivsendung:

1. XML berechnen.
2. XSD validieren.
3. Hash bilden.
4. lokalen Submission-Log pruefen.
5. DataBox auf bereits eingereichte U13 fuer Periode pruefen.
6. Bei Treffer:
   - nicht automatisch senden.
   - UI zeigt Treffer.
   - User muss `Berichtigung / erneut senden` explizit bestaetigen.

Persistenz:

- DB-Key oder Tabelle spaeter:
  - `period`
  - `meldung = U13`
  - `mode = T/P`
  - `xml_hash`
  - `sent_at`
  - `upload_rc`
  - `protocol_path`
  - `status`

Ohne DB:

- `state/finanzonline/u13_submissions.json`

## UI-Umbau in `TaxesView`

### Variante A: kleiner Umbau

`QTabWidget` behalten und neuen Tab einfuegen:

- `UVA`
- `ZM / U13`
- `EU-OSS`
- `Ausgaben`

Vorteil:

- kleinster Eingriff.
- bestehende Tests leichter anpassbar.

Nachteil:

- Steuern bleibt tablastig.
- Workflow-Status ueber Tabs hinweg schlechter sichtbar.

### Variante B: empfohlener Umbau

`TaxesView` auf linke Auswahl + `QStackedWidget` umbauen:

```text
+--------------------------------------------------------------+
| Steuern                                      Status / Quelle   |
+--------------------+-----------------------------------------+
| Umsatzsteuer        | Zusammenfassende Meldung / U13          |
|  UVA / U30          | Zeitraum, Aktionen, Testmodus            |
|  ZM / U13           | KPI-Zeile                                |
|  EU-OSS             |-----------------------------------------|
|                    | ZM-Zeilen-Tabelle                        |
| Pruefung            |-----------------------------------------|
|  Ausgaben           | Belegdetails / UID-Probleme              |
|                    |-----------------------------------------|
| FinanzOnline        | XML / Upload / DataBox-Protokoll         |
+--------------------+-----------------------------------------+
```

Vorteil:

- U30, U13 und OSS werden als eigene Workflows wahrgenommen.
- Breite bleibt fuer Tabellen verfuegbar.
- Weitere Steuerwerkzeuge passen besser hinein.

Empfehlung: Variante B, aber technisch in zwei Commits:

1. ZM/U13-Seite als neuer interner Widget-Baustein.
2. Danach Steuern-Navigation von Tabs auf Stack umstellen.

## Bedienlogik

### Berechnen

1. User waehlt Jahr/Monat.
2. `ZM berechnen` startet BackgroundWorker.
3. Worker ruft `ZmService.calculate_month()`.
4. Ergebnis befuellt:
   - KPIs
   - ZM-Zeilen
   - Belegdetails
   - Pruefungen
5. U13-Vorschau wird aktiv, wenn Ergebnis vorhanden ist.
6. U13-Sendung wird aktiv, wenn:
   - mindestens eine Zeile vorhanden ist,
   - keine blockierenden UID-Fehler vorhanden sind,
   - FinanzOnline-Zugang konfiguriert ist.

### Vorschau

1. U13-XML bauen.
2. XSD validieren.
3. Preview-Dialog:
   - Periode
   - FASTNR maskiert
   - Test/Produktiv
   - Zeilenanzahl
   - Summe
   - XML
   - Validierungsstatus

### Testsendung

1. Testmodus bleibt Default.
2. Nach Upload:
   - Upload-Rueckmeldung anzeigen.
   - DataBox-Protokoll suchen.
   - klar anzeigen: `Testupload - nicht eingebracht`.

### Produktivsendung

1. Nur wenn Testmodus bewusst deaktiviert wurde.
2. Warn-/Bestaetigungsdialog:
   - Periode
   - Zeilen
   - Summe
   - `Produktiv (P)`
   - Hinweis: Protokoll entscheidet ueber Einbringung.
3. Preflight DataBox:
   - wenn bereits U13 fuer Periode gefunden: blockieren und Berichtigungsbestaetigung verlangen.
4. Upload.
5. Protokoll abrufen.
6. Status speichern.

## Testplan

### Unit-Tests

Erweitern:

- `tests/unit/test_zm_service.py`
  - CreditNote reduziert UID-Summe.
  - CreditNote ohne Kontakt nutzt Fallback.
  - UID-Korrektur wird angewandt.
  - AT-UID blockiert.
  - Delivery/Service/Dreieck werden getrennt gruppiert.
  - Betrag 0 nach Rundung wird als Hinweis ignoriert.

- `tests/unit/test_uva_soap_mock.py`
  - U13-XML enthaelt `SOLEI=J` fuer `service`.
  - U13-XML enthaelt `DREIECK=J` fuer `dreieck`.
  - FileUpload sendet `art=U13`.
  - Testmodus sendet `uebermittlung=T`.
  - Produktivmodus sendet `uebermittlung=P`.

Neu:

- `tests/unit/test_zm_submission_service.py`
  - blockiert ohne Zeilen.
  - blockiert bei invalid UID.
  - blockiert bei XSD-Fehler.
  - DataBox-Preflight verhindert Doppelsendung.
  - Berichtigungsflag erlaubt erneute Sendung.

### UI-Tests

Neu:

- `tests/ui/test_taxes_zm_view.py`
  - Steuern-Modul laedt.
  - ZM/U13-Auswahl sichtbar.
  - Berechnen mit Fake-Service befuellt Tabellen.
  - Sendebutton disabled bei invalid UID.
  - Sendebutton enabled bei validen Zeilen.
  - Testmodus ist default aktiv.

### Regression gegen Legacy

Fixture aus Legacy:

- Beispielmonat Mai 2026 aus bisheriger Doku:
  - gelesene Rechnungen: 127
  - ZM-relevante Rechnungen: 10
  - ZM-Zeilen: 4
  - Summe gerundet: 2.733 EUR

Akzeptanz:

- Neue PySide6-Berechnung reproduziert diese Werte.
- Wenn CreditNotes im Monat existieren, werden sie wie Legacy `_run_zm_v2()` beruecksichtigt.

## Migrationsphasen

### Phase 1: Service-Paritaet

- `ZmInvoiceProvider` zu `ZmDocumentProvider` erweitern.
- CreditNotes aufnehmen.
- Detailzeilen einfuehren.
- UID-Korrekturservice einfuehren.
- Legacy-kompatible Monatsberechnung mit Tests absichern.

Keine UI-Aenderung ausser optionaler interner Nutzung.

### Phase 2: Eigenstaendige ZM/U13-UI

- Neues Widget `ZmU13View` unter `src/xw_studio/ui/modules/taxes/`.
- `TaxesView` bindet ZM-Seite ein.
- Tabellen statt reiner Textausgabe.
- UID-Korrekturdialog.
- Vorschau/Export.

### Phase 3: FinanzOnline kontrolliert

- Eigener `ZmSubmissionService`.
- U13-Preview mit XSD.
- Testupload.
- Produktivupload mit doppelter Bestaetigung.
- DataBox-Protokollsuche.
- Protokoll lokal speichern.

### Phase 4: Steuern-Navigation aufraeumen

- Weg von breitem `QTabWidget`, falls gewuenscht.
- Linke Auswahl + `QStackedWidget`.
- Statusleisten fuer U30/U13/OSS vereinheitlichen.

### Phase 5: Alte Kopplung UVA + ZM pruefen

Optionen:

- `UVA + ZM senden` bleibt als Komfortfunktion, nutzt aber denselben `ZmSubmissionService`.
- Oder: U30 sendet nur U30; nach Erfolg zeigt die UI `Jetzt U13 pruefen/senden`.

Empfehlung:

- U30 und U13 fachlich getrennt halten.
- Komfortbutton nur anbieten, wenn beide Previews vorab validiert wurden.

## Risiken und Gegenmassnahmen

| Risiko | Gegenmassnahme |
| --- | --- |
| Doppelte Produktivsendung | lokaler Submission-Log + DataBox-Preflight + Bestaetigungsdialog |
| Upload formal OK, aber nicht eingebracht | DataBox-Protokoll als eigener Status, nicht nur Upload-rc |
| Ungueltige UID | blockierender Fehler, Korrekturdialog, persistente Korrekturen |
| CreditNotes fehlen | Provider um CreditNotes erweitern und gegen Legacy testen |
| UVA/IST und ZM/SOLL werden verwechselt | UI zeigt Berechnungsprinzip permanent an |
| XML-Struktur aendert sich | XSD-Pfad konfigurierbar, Validierung vor Upload zwingend |
| Testmodus wird fuer Produktiv gehalten | Testmodus farblich/statusmaessig klar markieren; Testupload als nicht eingebracht anzeigen |

## Konkrete Akzeptanzkriterien

- Im Modul `Steuern` ist `Zusammenfassende Meldung / U13` als eigener Bereich sichtbar.
- ZM fuer einen Monat laesst sich berechnen, ohne UVA zu starten.
- Ergebnis zeigt ZM-Zeilen und Belegdetails strukturiert.
- Fehlende/ungueltige UID blockiert U13-Produktivsendung.
- UID-Korrekturen koennen eingegeben und wiederverwendet werden.
- U13-XML kann vor der Sendung angezeigt und XSD-validiert werden.
- Testsendung an FinanzOnline funktioniert ueber FileUpload.
- Produktivsendung verlangt explizite Bestaetigung und prueft vorher DataBox/lokalen Submission-Log.
- Nach Sendung kann das U13-Protokoll aus der DataBox geholt und geoeffnet werden.
- Keine U13 wird gesendet, wenn keine ZM-Zeilen vorhanden sind.

## Empfohlener naechster Schritt

Zuerst Phase 1 umsetzen: `ZmService` auf echte Legacy-Paritaet bringen, insbesondere CreditNotes und UID-Korrekturen. Danach die eigenstaendige PySide6-Seite bauen. Die FinanzOnline-Sendung sollte erst dann produktiv freigeschaltet werden, wenn Service-Tests, XSD-Validierung und ein Testupload mit DataBox-Protokoll erfolgreich sind.
