# START-Button Rechnungen: Ablaufvergleich und Live-Test-Check

Stand: 2026-05-22

## Kurzfazit

Aktualisiert nach Umsetzung am 2026-05-22: Der neue START-Button in XW-Studio kann fuer den ersten Test verwendet werden. Die sicherheitskritischen Luecken gegenueber Legacy sind jetzt geschlossen:

1. `sendBy VM` wird im START-Pfad nicht mehr verwendet. Digital-only und "Nur Rechnungen" versenden primaer ueber sevDesk `sendViaEmail`.
2. Das neue sevDesk-PDF-Format aus dem Q1-2026-Update wird verarbeitet: `objects.pdf` und `pdf` werden als Base64-PDF erkannt, `render` fragt `getAsPdf=true` an, und der START-Flow nutzt das Render-PDF direkt. Zusaetzlich gibt es wie im Legacy-Flow mehrere PDF-Versuche.
3. Der START-Button hat nun einen Menuepunkt `START SELECTED (markierte Rechnungen)`. Dieser verarbeitet nur die selektierten Rechnungen aus der XW-Rechnungsliste.
4. Physische Rechnungsmails laufen nach Druck/Fulfillment primaer ueber sevDesk `sendViaEmail`; Microsoft Graph ist nur noch Fallback. Damit hilft das neue sevDesk-OAuth-Update direkt beim Standardpfad.
5. Der Notendruck laeuft im START-/Nachdruck-Inventarworkflow und im manuellen Detailpanel ueber das neue interne Printmodul (`planned_pdf_printer` -> PyMuPDF/QPrinter). Es gibt keinen Acrobat-/Adobe-Shell-Pfad fuer diesen Druck.

Empfohlener Live-Test heute: zuerst eine oder wenige Rechnungen in der XW-Rechnungsliste markieren, dann `START` -> `START SELECTED (markierte Rechnungen)` verwenden.

## Umsetzungsphasen

### Phase 1: START SELECTED

Status: umgesetzt.

Dateien:

- `src/xw_studio/ui/widgets/data_table.py`
- `src/xw_studio/ui/modules/rechnungen/view.py`
- `src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py`
- `src/xw_studio/services/invoice_processing/service.py`

Umsetzung:

- Die Rechnungstabelle unterstuetzt Mehrfachauswahl.
- `RechnungenView.selected_summaries()` liefert die markierten Rechnungen.
- Der START-Button hat den zusaetzlichen Menuepunkt `START SELECTED (markierte Rechnungen)`.
- Der Preflight zaehlt bei START SELECTED nur die selektierten Rechnungen.
- Produkt-Preflight und Batchlauf werden auf die selektierten sevDesk-IDs begrenzt.
- `InvoiceProcessingService.run_start_fullflow(invoice_ids=[...])` verarbeitet nur diese IDs.

### Phase 2: Mailversand absichern

Status: umgesetzt.

Dateien:

- `src/xw_studio/services/invoice_processing/service.py`
- `src/xw_studio/services/sevdesk/invoice_client.py`
- `Markdowns/sevdesk_sendviaemail_mailstrategie_2026-05-22.md`

Umsetzung:

- `sendBy VM` wird im START-Pfad nicht mehr genutzt.
- Manueller/physischer Rechnungsversand versucht zuerst sevDesk `sendViaEmail`.
- Wenn sevDesk-Mail fehlschlaegt oder nicht verfuegbar ist, wird Microsoft Graph genutzt.
- Damit kann das sevDesk-OAuth-2.0-Update fuer Microsoft 365 direkt im Standardpfad fuer Rechnungsmails helfen.

### Phase 3: Notendruck ohne Acrobat

Status: umgesetzt und per Test abgesichert.

Dateien:

- `src/xw_studio/services/inventory/service.py`
- `src/xw_studio/services/printing/planned_pdf_printer.py`
- `src/xw_studio/ui/modules/rechnungen/print_dialog.py`
- `src/xw_studio/ui/modules/rechnungen/view.py`
- `tests/unit/test_planned_pdf_printer.py`
- `tests/unit/test_inventory_start_workflow.py`

Umsetzung:

- Der manuelle Button `Noten drucken` im Detailpanel nutzt `run_piece_pdf_print()`.
- `run_piece_pdf_print()` ruft `print_pdf_by_plan()` auf.
- `print_pdf_by_plan()` verwendet `QPrinter` und den internen PyMuPDF-Renderer `print_pdf()`.
- Der START-/Nachdruck-Inventarworkflow druckt Produkt-PDFs jetzt ebenfalls ueber `print_pdf_by_plan()`.
- Wenn PDF-Pfad, Datei oder Druckprofil fehlen, wird kein Bestand hochgezaehlt; stattdessen erscheint ein Hinweis im Ergebnisdialog.
- Test `test_print_pdf_by_plan_uses_internal_renderer_without_shelling_out` stellt sicher, dass weder `subprocess.Popen` noch `os.startfile` verwendet werden.

Ergebnis: Kein Acrobat-Flackern aus XW-Studio fuer den Notendruckpfad.

### Phase 4: Preflight, Ergebnisdialoge und Tests

Status: umgesetzt.

Dateien:

- `src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py`
- `tests/unit/test_invoice_processing_service.py`
- `tests/unit/test_invoice_client.py`
- `tests/unit/test_printing_parity_e2e.py`
- `tests/unit/test_inventory_start_workflow.py`
- `tests/unit/test_planned_pdf_printer.py`

Umsetzung:

- START-Ergebnisdialog zeigt Inventar-/Druckhinweise.
- Nachdruck-Ergebnisdialog zeigt Druckhinweise.
- Ein Altfehler im START-Preflight wurde behoben: das Statussignal ist nun in beiden Dialogzweigen verfuegbar.
- Tests decken START SELECTED, sevDesk-first-Mailversand, Graph-Fallback, neues sevDesk-PDF-Format und internen Notendruck ab.

Validierung:

```text
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/unit/test_printing_parity_e2e.py tests/unit/test_invoice_client.py tests/unit/test_invoice_processing_fullflow.py tests/unit/test_inventory_start_workflow.py tests/unit/test_invoice_processing_service.py tests/unit/test_planned_pdf_printer.py
54 passed
```

## Legacy sevDesk: START ALL

Codepfad:

- `sevdesk_wix_fulfillment/ui/app.py`
  - `start_batch_all()` laedt alle offenen Rechnungs-IDs.
  - `_start_batch_for_invoice_ids()` startet Produkt-/Daten-Preflight.
  - `_process_batch()` verarbeitet die Rechnungen nacheinander.
- `sevdesk_wix_fulfillment/services/invoice_processor.py`
  - `process_invoice_with_analysis()` ist der zentrale Workflow.
  - `_send_type_for_invoice()` waehlt `VM` fuer digital-only, sonst `PRN`.
  - `finalize_invoice_async()` triggert sevDesk `sendBy`.
  - `_print_and_fulfill()` druckt Rechnung und Label und setzt Wix-Fulfillment.
  - `_send_invoice_email_copy()` sendet die Kundenmail ueber sevDesk `sendViaEmail`.

Legacy-Ablauf START ALL:

1. Offene Rechnungen aus der linken Liste einsammeln.
2. Produkt-/Wix-/Adressanalyse je Rechnung vorbereiten.
3. Fehlende Produktdaten pruefen und ggf. Rechnung ueberspringen.
4. sevDesk-Rechnung finalisieren:
   - digital-only: `sendBy VM`, dadurch Mailversand ueber sevDesk.
   - physisch: gedruckter Versandtyp, danach lokaler Druck.
5. PDF mit Retry holen.
6. Rechnung auf Drucker `Rechnungen` drucken.
7. Versandlabel drucken.
8. Inventory-Fulfillment-Hook und Wix-Fulfillment ausfuehren.
9. B2C-Zahlung importieren/buchen, falls anwendbar.
10. Kundenmail fuer physische Rechnungen ueber sevDesk `sendViaEmail` senden.
11. Ergebnis im rechten Analysis-Panel als Verarbeitungslog anzeigen.

## XW-Studio: START

Codepfad:

- `src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py`
  - `_on_start_clicked()` erstellt den ersten Preflight.
  - `_on_start_preflight_ready()` zeigt den START-Dialog.
  - `_on_start_product_preflight_ready()` fuehrt Produktplan und Batch aus.
- `src/xw_studio/services/invoice_processing/service.py`
  - `run_start_fullflow()` verarbeitet alle offenen Entwuerfe.
  - `_run_finalize_step()` triggert sevDesk `sendBy`.
  - `_run_invoice_print_step()` druckt die Rechnung.
  - `_run_label_print_step()` druckt das Label.
  - `_run_product_step()` prueft/erstellt Wix-Fulfillment.
  - `_run_mail_step()` sendet primaer ueber sevDesk `sendViaEmail`, Graph nur als Fallback.

XW-Ablauf bei Direktklick START / Vollflow:

1. Offene Entwuerfe mit Status `100` zaehlen.
2. Inventar-Preflight aus `daily_business.pending_requirements` bauen.
3. START-Dialog anzeigen:
   - "Rechnungen + Druck" = Vollflow.
   - "Nur Rechnungen" = sevDesk-Finalisierung/Mail, kein Druck/Fulfillment.
4. Produktdaten-Preflight aus Wix-Referenzen bauen und ggf. Dialoge anzeigen.
5. Alle offenen Entwuerfe laden.
6. Je Rechnung:
   - Produktmapping reparieren, soweit moeglich.
   - Digital-only erkennen.
   - Finalisieren:
     - physisch im Vollflow: `sendBy VPR`.
     - digital-only oder Nur-Rechnungen: kein `sendBy VM`; Mailversand per `sendViaEmail`.
   - Im Vollflow fuer physische Rechnungen:
     - PDF rendern/holen, mit neuen `objects.pdf`-Payloads und Retry.
     - Rechnung drucken.
     - Label drucken.
     - Wix-Fulfillment setzen.
     - Kundenmail ueber sevDesk `sendViaEmail` senden; Graph nur als Fallback.
7. Fulfillment-Chips in der Rechnungsliste persistieren.
8. Wenn der Batch fehlerfrei war, Inventarbestand aus dem Preflight fortschreiben.
9. Rechnungsliste und Badges aktualisieren.

## Invoice-List-Buttons: Legacy

Legacy `InvoiceListFrame` zeigt Datum, Name, Betrag, Gewicht, Order, Land, Adresse, Print-Hinweis, Notiz und PLC.

Wichtige Interaktionen:

- Klick auf PLC-Spalte: direkter PLC-Labeldruck fuer die jeweilige Rechnung.
- Mehrfachauswahl: Grundlage fuer `START SELECTED`.
- Analysis-Panel rechts:
  - `PRINT SELECTED`: Noten/Produktdruck fuer die ausgewaehlte Rechnung.
  - `RECHNUNG DRUCKEN`: Rechnungs-Reprint.
  - `LABEL DRUCKEN`: Label-Reprint aus bearbeitbarer Lieferadresse.
- BatchControls:
  - `START ALL`: kompletter Batch wie oben.
  - `START SELECTED`: gleicher Batch nur fuer markierte Rechnungen.
  - `PRINT ALL`: Produkt-/Notendruck-Auswahl fuer alle offenen Rechnungen, ohne Finalisierung.
  - `CHECK PRODUCTS`: Produktcheck ohne START.
  - `STOP`: Abbruch vor der naechsten Rechnung.

## Invoice-List-Buttons: XW-Studio

Die XW-Rechnungsliste hat eigene Aktions- und Statusspalten:

- Spalte `AKTIONEN`:
  - Post/PLC-Icon: PLC-Labeldialog.
  - Wix-Icon: Wix-Order/Dashboard- bzw. Download-Link-Kontext.
- Spalte `FULFILLMENT`:
  - Label, Rechnung, Produkt, Mail, Wix, Payment als klickbare Chips.
  - Klick fuehrt den jeweiligen Schritt fuer diese Rechnung erneut aus, ausser Payment ist aktuell deaktiviert.
- Detailpanel rechts:
  - `Rechnung drucken`
  - `PLC-Label drucken`
  - `Noten drucken`
  - `Rechnung senden`
  - editierbare Lieferadresse mit Labeldruck.
- Toolbar:
  - `Rechnungs-Entwurf`
  - `CUSTOM-LABEL`
  - `OFFENE SENDUNGEN`, wenn offene Versandmails vorhanden sind.
  - `MOLLIE AUTH`, wenn offene Mollie-Autorisierungen vorhanden sind.

## sevDesk-Updates aus `updates_sevdesk.txt`

### PDF Rendering ab 2026-04-07

sevDesk liefert bei `render`, `changeParameter` und `sendByWithRender` keine `thumbs`/`pages` mehr, sondern ein vollstaendiges Base64-PDF in `pdf`. Laut Update konnte man sich vorher bereits mit `getAsPdf=true` vorbereiten.

Umgesetzt in XW-Studio:

- `InvoiceClient.render_invoice_pdf()` sendet `getAsPdf=true`.
- `InvoiceClient.extract_pdf_from_payload()` erkennt `pdf`, `base64`, `pdfBase64`, `documentBase64`, Data-URI-PDFs und `objects.pdf`.
- `InvoiceProcessingService._get_invoice_pdf_bytes()` nutzt das Render-PDF direkt, bevor `getPdf` fallbackt.

### OAuth 2.0 fuer sevDesk-Mailversand

Das Update betrifft den sevDesk-internen Versand ueber Microsoft 365/Outlook. Es hilft besonders dann, wenn XW-Studio den sevDesk-Endpunkt `sendViaEmail` nutzt.

Aktueller Stand nach Fix:

- Digital-only und "Nur Rechnungen" nutzen sevDesk `sendViaEmail`; hier hilft die sevDesk-OAuth-Konfiguration direkt.
- Physische Vollflow-Rechnungen nutzen nach Druck/Fulfillment ebenfalls primaer sevDesk `sendViaEmail`. Wenn sevDesk-Mail scheitert, fallbackt XW-Studio auf Microsoft Graph.

## Umgesetzt

Geaenderte Dateien:

- `src/xw_studio/services/invoice_processing/service.py`
  - entfernt `sendBy VM` aus dem START-Pfad.
  - nutzt sevDesk `sendViaEmail` als primaeren Mailweg.
  - nutzt Graph nur noch als Mail-Fallback.
  - nutzt Render-PDFs direkt.
  - fuehrt PDF-Retry mit Backoff ein.
  - verarbeitet optional nur selektierte Rechnungs-IDs.
- `src/xw_studio/services/sevdesk/invoice_client.py`
  - fragt `getAsPdf=true` an.
  - dekodiert neues `objects.pdf`/`pdf`-Format.
- `src/xw_studio/ui/widgets/data_table.py`
  - liefert selektierte Source-Zeilen und Row-Payloads.
- `src/xw_studio/ui/modules/rechnungen/view.py`
  - aktiviert Mehrfachauswahl und liefert selektierte Rechnungs-Summaries.
- `src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py`
  - ergaenzt `START SELECTED`.
  - zeigt Druck-/Inventarhinweise im Ergebnis.
- `src/xw_studio/services/inventory/service.py`
  - druckt START-/Nachdruck-Produkt-PDFs ueber das neue Printmodul.
  - verhindert Bestandserhoehung, wenn der physische Notendruck nicht ausgefuehrt werden konnte.
- `tests/unit/test_printing_parity_e2e.py`
  - Digital-only und Mail-only erwarten sevDesk `sendViaEmail` statt `sendBy VM`.
- `tests/unit/test_invoice_client.py`
  - deckt neues PDF-Payloadformat und `getAsPdf=true` ab.
- `tests/unit/test_invoice_processing_service.py`
  - deckt START SELECTED, sevDesk-first-Mailversand und Graph-Fallback ab.
- `tests/unit/test_inventory_start_workflow.py`
  - deckt physischen Produktdruck und Warnungen ab.
- `tests/unit/test_planned_pdf_printer.py`
  - deckt internen Renderer ohne Shell/Acrobat ab.

Validierung:

```text
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/unit/test_printing_parity_e2e.py tests/unit/test_invoice_client.py tests/unit/test_invoice_processing_fullflow.py tests/unit/test_inventory_start_workflow.py tests/unit/test_invoice_processing_service.py tests/unit/test_planned_pdf_printer.py
54 passed
```

## Restempfehlungen nach Umsetzung

Prioritaet 2: Preflight aussagekraeftiger machen

Der START-Dialog zeigt aktuell Inventarbedarf aus `daily_business.pending_requirements`, aber keine vollstaendige Liste der konkreten Rechnungen, Mail-Backends, Drucker und Risiken.

Empfehlung:

- Preflight-Tabelle mit Rechnung, Kunde, Wix-Ref, digital/physisch, Lieferadresse vorhanden, Mailquelle, Druckerstatus.
- Warnung, wenn sevDesk-Mail/OAuth nicht bereit ist; Graph-Auth als Fallback-Status anzeigen.
- Warnung, wenn `daily_business.pending_requirements` fehlt: Inventar wird dann nicht fortgeschrieben.

Prioritaet 3: Fulfillment-Status erweitern

Aktuell gibt es boolsche Chips. Fuer Fehlersuche waeren hilfreich:

- `mail_backend`
- `mail_to`
- `send_type`
- `pdf_source` (`render.pdf` oder `getPdf`)
- letzte konkrete Fehlermeldung je Schritt, nicht nur global.

## Live-Test-Checkliste fuer heute

Vor dem Klick:

1. In sevDesk pruefen, wie viele Rechnungen aktuell Status `Entwurf`/`100` haben. START nimmt alle.
2. Drucker `Rechnungen` und `Brother QL-800` pruefen.
3. Fuer Rechnungsmails sicherstellen, dass sevDesk E-Mail/OAuth fuer M365 eingerichtet ist.
4. Graph in XW-Studio ist nur noch Fallback; falls moeglich trotzdem Auth pruefen.
5. Fuer den ersten Test Rechnungen markieren und im START-Menue `START SELECTED (markierte Rechnungen)` waehlen.

Empfohlener erster Lauf:

- 1-2 Test-Entwuerfe in der Rechnungsliste markieren.
- START-Menue oeffnen und `START SELECTED (markierte Rechnungen)` waehlen.
- Im START-Dialog Vollflow bestaetigen.
- Nach Abschluss pruefen:
  - Rechnung in sevDesk nicht mehr Entwurf.
  - Rechnung gedruckt.
  - Label gedruckt.
  - Noten-PDFs wurden ohne Acrobat-Fenster gedruckt.
  - Wix-Fulfillment gesetzt.
  - Kundenmail angekommen oder im Graph/sevDesk-Sent-Ordner sichtbar.
  - Fulfillment-Chips in XW-Studio gruen bzw. Fehlertext plausibel.
