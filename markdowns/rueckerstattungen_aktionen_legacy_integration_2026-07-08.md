# Rueckerstattungen in RECHNUNGEN integrieren

Datum: 2026-07-08  
Ziel: Den Legacy-Punkt **Rueckerstattungen** intelligent in die neue PySide6-App integrieren, als Symbolbutton in der Spalte `AKTIONEN` der Rechnungen-Tabelle.

## Zielbild

In `RECHNUNGEN` bekommt jede fachlich geeignete Rechnung in der Spalte `AKTIONEN` einen Refund-Iconbutton. Nach Klick oeffnet sich ein PySide6-Popup fuer genau diese Rechnung. Das Popup laedt den Refund-Kontext im Hintergrund und zeigt die relevanten Legacy-Auswahlmoeglichkeiten verbessert an:

- Vollstorno / vollstaendige Rueckerstattung.
- Teilrueckerstattung ueber ausgewaehlte Rechnungspositionen.
- Versandkosten optional mit rueckerstatten, wenn Wix diese als refundierbar meldet.
- Kundeninfo/Gutschriftmail optional senden.
- Wix-Zahlungsrefund ausloesen, wenn eine Wix-Order und refundierbare Zahlungen vorhanden sind.
- Bei fehlendem Wix-Refund oder Ueberweisung: klare Meldung mit manueller Rueckueberweisung und Bankdaten, soweit ermittelbar.

Nach Klick auf den abschliessenden Button laeuft die Ausfuehrung im Hintergrund. Danach bekommt der Nutzer eine eindeutige Erfolg-/Teil-Erfolg-/Fehlermeldung, das Popup schliesst sich, und die Rechnungsliste wird aktualisiert.

## Ausgangslage in der neuen App

### Bereits vorhanden

Neue App:

- `icons/refund.png` existiert.
- `src/xw_office/ui/modules/rechnungen/refund_dialog.py` existiert als einfacher Full-Refund-Dialog.
- `src/xw_office/services/sevdesk/refund_client.py` kann:
  - `cancel_invoice(invoice_id)`
  - `create_credit_note_from_invoice(invoice_id)`
- `src/xw_office/services/wix/client.py` kann:
  - `get_order_refundability(order_id)`
  - `refund_order_payments(order_id, payment_refunds, ...)`
  - `refund_full_order(reference, ...)`
- `InvoiceClient` hat bereits `fetch_invoice_positions(invoice_id)`.
- `InvoiceClient` hat bereits `get_invoice_check_account_transactions(invoice_id)`.
- `bootstrap.py` registriert `SevDeskRefundClient`.

Aktuelle `RECHNUNGEN`-Integration:

- `_ActionsDelegate` in `src/xw_office/ui/modules/rechnungen/view.py` rendert aktuell `post`, `wix`, `mail`.
- `_run_row_action()` behandelt aktuell `post`, `wix`, `mail`.
- `_open_refund_dialog()` existiert bereits, wird aber aus der `AKTIONEN`-Spalte nicht erreicht.
- Der vorhandene Dialog ist Full-Refund-only und nutzt `cancel_invoice()` plus `refund_full_order()`.

### Luecke

Die Legacy-Funktion ist fachlich reicher als der aktuelle Dialog:

- Suche nach Rechnungen ist im Zeilenbutton nicht mehr noetig, weil die Rechnung schon feststeht.
- Positionen und Teilmengen sind aber weiterhin wichtig.
- Versandkosten-Auswahl fehlt im neuen Dialog.
- Bestehende Gutschriften werden nicht angezeigt.
- Manuelle Rueckueberweisung und Bankdaten werden nicht ausgewiesen.
- Der `AKTIONEN`-Iconbutton fehlt.
- Teilrueckerstattung ist in Tests/Dokumentation als Backend-nah, aber UI-fehlend markiert.

## Legacy-Befund

Legacy-Dateien:

- `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\services\refund_manager.py`
- `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\ui\widgets\refunds_panel.py`

Wichtige Legacy-Service-Methoden:

- `RefundManager.search_candidates()`:
  - Suche nach Rechnungsnummer, Name oder Wix-Order.
  - Fuer den neuen AKTIONEN-Button nicht direkt benoetigt.
- `RefundManager.load_invoice_context()`:
  - laedt Rechnungspositionen.
  - analysiert Wix-Order.
  - laedt Wix-Refundability.
  - ermittelt bestehende Gutschriften.
  - ermittelt Bankdaten aus CheckAccountTransactions.
- `RefundManager.execute_refund()`:
  - sammelt ausgewaehlte Positionen und Mengen.
  - erstellt CreditNote aus Rechnung.
  - loescht nicht ausgewaehlte CreditNote-Positionen.
  - passt Mengen fuer ausgewaehlte Positionen an.
  - fuehrt Wix-Refund fuer LineItems und optional Shipping aus.
  - sendet optional Gutschriftmail.
  - meldet manuelle Rueckueberweisung, wenn Wix nicht durchgefuehrt werden konnte.
- `RefundManager._build_refund_lines()`:
  - matched sevDesk-Positionen auf Wix-LineItems ueber SKU und Name.
  - begrenzt refundierbare Menge anhand Wix-Refundability.

Wichtige Legacy-UI-Auswahlmoeglichkeiten:

- Suchmodus `Re-Nr`, `Name`, `Wix-Order`.
- Zeitfenster "letzte 30 Tage" und "Weitere 30 Tage laden".
- Checkbox `Versand mit rueckerstatten`.
- Checkbox `Infomail senden`.
- Pro Position:
  - aktiv/inaktiv.
  - Menge.
  - maximale refundierbare Menge.
  - SKU/Name.
- Ergebnistext mit:
  - Gutschrift.
  - Betrag.
  - Wix Refund ja/nein.
  - Infomail gesendet/nicht gesendet.
  - Wix-/Mail-Fehler.
  - Hinweis auf manuelle Rueckueberweisung.
  - Bankdaten.

## Was nicht blind uebernommen werden soll

Nicht uebernehmen:

- Tkinter/ttkbootstrap UI-Struktur.
- `threading.Thread` direkt im Widget.
- Suchpanel als Hauptworkflow fuer den Zeilenbutton.
- Unstrukturierte `dict`-Rueckgaben als interner Hauptvertrag.
- Legacy-Imports wie `from services.refund_manager import RefundManager`.
- UI-nahe Formatierungslogik im Service.

Intelligent uebernehmen:

- Fachliche Schritte: Kontext laden, Positionen auswahlen, Versand, Mail, Wix Refund, manuelle Rueckzahlung.
- Matching-Idee zwischen sevDesk-Position und Wix-LineItem.
- Pruefung bestehender Gutschriften.
- Sicherheitsmeldungen bei nicht automatisch refundierbaren Faellen.
- Ergebniszusammenfassung.

## Neuer fachlicher Service

Vorschlag: neuer Service unter:

```text
src/xw_office/services/refunds/
  __init__.py
  models.py
  service.py
```

### Modelle

`RefundMode`

- `FULL_CANCEL_AND_REFUND`
- `PARTIAL_CREDIT_NOTE_AND_REFUND`
- `CREDIT_NOTE_ONLY_MANUAL_TRANSFER`

`RefundContext`

- `invoice_id`
- `invoice_number`
- `invoice_date`
- `customer_name`
- `customer_email`
- `order_reference`
- `wix_order_id`
- `order_found`
- `lines: list[RefundLine]`
- `shipping_available_amount`
- `existing_credit_count`
- `existing_credit_total`
- `bank_info`
- `warnings`

`RefundLine`

- `key`
- `name`
- `sku`
- `quantity`
- `max_refundable_qty`
- `unit_gross`
- `sum_gross`
- `tax_rate`
- `wix_line_item_id`
- `wix_match_status`

`RefundSelection`

- `mode`
- `selected_quantities: dict[str, Decimal]`
- `include_shipping`
- `send_wix_customer_email`
- `send_credit_note_email`
- `reason`

`RefundExecutionResult`

- `success`
- `severity`: `success`, `partial`, `error`
- `invoice_number`
- `credit_note_id`
- `credit_note_number`
- `cancelled_invoice`
- `selected_total_amount`
- `wix_refund_done`
- `wix_refund_error`
- `credit_note_mail_sent`
- `credit_note_mail_error`
- `manual_transfer_required`
- `bank_info`
- `message_lines`

### Service API

```python
class RefundService:
    def load_context(self, summary: InvoiceSummary) -> RefundContext: ...
    def execute(self, context: RefundContext, selection: RefundSelection) -> RefundExecutionResult: ...
```

### Service-Abhaengigkeiten

- `InvoiceClient`
- `SevDeskRefundClient`
- `WixOrdersClient`
- optional `MailDeliveryService` oder sevDesk-Mail-Methode.

### Fehlende oder zu ergaenzende Client-Methoden

Teilweise sind diese in der neuen App schon vorhanden, teilweise nicht zentral im Refund-Client:

- `InvoiceClient.fetch_invoice_positions(invoice_id)` ist vorhanden.
- `InvoiceClient.get_invoice_check_account_transactions(invoice_id)` ist vorhanden.
- `SevDeskRefundClient.create_credit_note_from_invoice(invoice_id)` ist vorhanden.
- Ergaenzen:
  - `SevDeskRefundClient.fetch_credit_notes_by_origin_invoice(invoice_id)` oder geeignete `InvoiceClient`/`CreditNoteClient`-Methode.
  - `SevDeskRefundClient.fetch_credit_note_positions(credit_note_id)`.
  - `SevDeskRefundClient.save_credit_note(...)`.
  - `SevDeskRefundClient.send_credit_note_via_email(...)`, falls nicht ueber `MailDeliveryService` geloest.

Empfehlung: Langfristig einen eigenen `CreditNoteClient` statt immer mehr Methoden im `SevDeskRefundClient`, weil Gutschriften ein eigener sevDesk-Dokumenttyp sind.

## UI-Konzept fuer Popup

Datei:

```text
src/xw_office/ui/modules/rechnungen/refund_dialog.py
```

Den bestehenden Dialog nicht einfach aufblasen, sondern zu einem Workflow-Dialog umbauen oder durch `RefundWorkflowDialog` ersetzen.

### Oeffnen

Klick auf Refund-Icon in `AKTIONEN`:

1. Dialog wird sofort sichtbar.
2. Kopfbereich zeigt Rechnung aus `InvoiceSummary`:
   - Rechnungsnummer.
   - Kunde.
   - Betrag.
   - Wix-Order-Ref.
3. Dialog zeigt Ladezustand "Rueckerstattungsdaten werden geladen".
4. `RefundService.load_context(summary)` laeuft im `BackgroundWorker` oder ueber `BackgroundJobManager`.
5. Nach Kontext-Ladung werden Optionen aktiviert.

### Dialogbereiche

Bereich 1: Rechnung

- Rechnung.
- Kunde.
- Datum.
- Betrag.
- Wix-Order.
- Bestehende Gutschriften: Anzahl und Summe.
- Warnhinweise:
  - keine Wix-Order gefunden.
  - keine refundierbare Zahlung.
  - vorhandene Gutschriften.
  - Positionen ohne Wix-Match.

Bereich 2: Rueckerstattungsart

Segmented Control oder Radio-Gruppe:

- **Vollstorno + voller Zahlungsrefund**
  - nutzt `cancel_invoice()`.
  - nur aktiv, wenn fachlich sinnvoll.
  - deutlich als nicht reversibel markieren.
- **Teilrueckerstattung / Gutschrift**
  - nutzt `create_credit_note_from_invoice()`.
  - Positionen und Mengen waehlen.
  - Standardmodus, weil sicherer und flexibler.
- **Gutschrift / manuelle Rueckzahlung**
  - wenn Wix nicht refundierbar ist.
  - erzeugt Gutschrift und weist auf manuelle Rueckueberweisung hin.

Bereich 3: Positionen

Tabelle oder kompakte Liste:

| Auswahl | Position | SKU | Menge | max. refundierbar | Menge refund | Einzel brutto | Summe |
|---|---|---|---:|---:|---:|---:|---:|

Controls:

- Checkbox pro Position.
- `QDoubleSpinBox` oder `QSpinBox` fuer Menge.
- Menge begrenzen auf `max_refundable_qty`.
- Positionszeilen ohne Wix-Match anzeigen, aber fuer Wix-Refund markieren:
  - sevDesk-Gutschrift moeglich.
  - Wix-LineItem-Refund nicht automatisch moeglich.

Bereich 4: Zusatzoptionen

- Checkbox `Versand mit rueckerstatten`, nur aktiv wenn `shipping_available_amount > 0`.
- Checkbox `Wix-Kundenmail senden`.
- Checkbox `Gutschriftmail senden`.
- Freitext `Grund / Notiz`, z. B. "Storno RE-...".

Bereich 5: Ergebnisvorschau

Vor Ausfuehrung live berechnen:

- Ausgewaehlter Positionsbetrag.
- Versandbetrag.
- Voraussichtliche Gesamtsumme.
- Automatisch via Wix refundierbar: ja/nein/teilweise.
- Manuelle Rueckzahlung erforderlich: ja/nein.

### Abschlussbutton

Button: `Rueckerstattung ausfuehren`

Verhalten:

1. Validierung im Dialog:
   - Kontext geladen.
   - mindestens eine Position oder Vollstorno.
   - Menge > 0.
   - keine Menge ueber Max.
   - Warnung bei bestehenden Gutschriften bestaetigen lassen.
   - Warnung bei Vollstorno bestaetigen lassen.
2. Button disabled und Status "Wird ausgefuehrt".
3. `RefundService.execute(...)` im Worker.
4. Bei Ergebnis:
   - `QMessageBox.information` bei Erfolg.
   - `QMessageBox.warning` bei Teil-Erfolg.
   - `QMessageBox.critical` oder `warning` bei Fehler.
5. Popup schliesst sich danach mit `accept()`.
6. Rechnungenliste reload/row refresh.

Validierungsfehler vor Start schliessen den Dialog nicht, weil der Nutzer sie korrigieren kann.

## AKTIONEN-Spalte

Datei:

```text
src/xw_office/ui/modules/rechnungen/view.py
```

### Delegate erweitern

Aktuell:

```python
_ACTION_KEYS = ("post", "wix", "mail")
```

Neu:

```python
_ACTION_KEYS = ("post", "wix", "mail", "refund")
_ICON_FILES = {
    "post": "post.png",
    "wix": "wix.png",
    "mail": "mail_sent.png",
    "refund": "refund.png",
}
```

Spaltenbreite `AKTIONEN` von ca. 120 auf ca. 148-160 erhoehen, je nach Icon-Gap.

Tooltip in `InvoiceSummary.as_table_row()`:

Aktuell sinngemaess:

```text
Post Label Center / Wix-Bestellung / Kunden-Mail
```

Neu:

```text
Post Label Center / Wix-Bestellung / Kunden-Mail / Rueckerstattung
```

### Action dispatch

`_run_row_action(summary, action)` erweitern:

```python
if action == "refund":
    self._open_refund_dialog(summary)
    return
```

### Verfuegbarkeit

Nicht jede Rechnung sollte den Refund-Button aktiv bekommen.

Minimalregel:

- Keine Refund-Aktion fuer reine Entwurfszeilen ohne Rechnungsnummer.
- Keine Refund-Aktion fuer bereits stornierte Rechnungen, wenn Status sauber erkennbar ist.
- Bei fehlender Wix-Order darf Button aktiv bleiben, aber Dialog zeigt "nur Gutschrift/manuelle Rueckzahlung".

Technisch:

- Row-Payload um `__refund_enabled__` und `__tooltip__AKTIONEN` erweitern.
- `_ActionsDelegate.paint()` kann disabled icons mit reduzierter Opacity zeichnen.
- `action_at_x()` soll weiterhin den Key liefern, aber `_run_row_action()` validiert final.

Pragmatischer erster Schritt:

- Refund-Icon immer fuer Rechnungen mit `summary.id` anzeigen.
- Dialog entscheidet, welche Modi aktiv sind.
- Danach feineres Disabled-Rendering nachziehen.

## Ausfuehrungslogik

### Vollstorno + voller Refund

Geeignet fuer komplette Stornos.

Ablauf:

1. `SevDeskRefundClient.cancel_invoice(invoice_id)`.
2. Wenn `order_reference` vorhanden:
   - `WixOrdersClient.refund_full_order(order_reference, send_customer_email=...)`.
3. Ergebnis:
   - Erfolg, wenn sevDesk-Storno erfolgreich und Wix bei vorhandener Order erfolgreich.
   - Teil-Erfolg, wenn sevDesk erfolgreich, Wix aber nicht bestaetigt.

Hinweis:

- Dieser Modus entspricht am ehesten dem aktuellen `RefundDialog`.
- Nicht als Default setzen, weil `cancelInvoice` nicht reversibel ist.

### Teilrueckerstattung / Gutschrift

Geeignet fuer einzelne Positionen, Teilmengen oder Versandkorrekturen.

Ablauf nach Legacy-Prinzip:

1. `create_credit_note_from_invoice(invoice_id)`.
2. CreditNote-Positionen laden bzw. aus API-Response lesen.
3. Nicht ausgewaehlte Positionen entfernen.
4. Ausgewaehlte Positionen auf gewuenschte Menge setzen.
5. Versand optional beruecksichtigen, falls als Wix-Shipping refundierbar.
6. Wix `refund_order_payments(order_id, payment_refunds)` mit:
   - `lineItems` fuer gematchte Wix-LineItems.
   - `shipping` fuer Versand.
7. Optional Gutschriftmail senden.

Wichtig:

- Wenn Wix nur ganzzahlige LineItem-Mengen akzeptiert, im Dialog bei betroffenen Positionen nur ganze Mengen zulassen.
- Wenn sevDesk Dezimalmengen erlaubt, aber Wix nicht, UI muss das sichtbar machen.
- Wenn keine Wix-LineItems matchen, trotzdem sevDesk-Gutschrift erlauben, aber "manuelle Rueckzahlung erforderlich" markieren.

### Gutschrift / manuelle Rueckzahlung

Geeignet fuer:

- Ueberweisung.
- Keine Wix-Order.
- Keine refundierbare Wix-Zahlung.
- Wix-Fehler nach sevDesk-Gutschrift.

Ablauf:

1. CreditNote wie oben erstellen.
2. Kein Wix-Refund.
3. Ergebnis zeigt Bankdaten aus `get_invoice_check_account_transactions()`, soweit vorhanden.

## Fehler- und Sicherheitskonzept

### Doppelklickschutz

- Dialog-Button beim Ausfuehren sofort deaktivieren.
- `self._refund_worker` oder `BackgroundJobManager` verhindert parallele Refunds.
- Service-seitig optional Idempotency-Key:
  - `refund:{invoice_id}:{selection_hash}`.
  - Mindestens als Audit in `state/refunds/` oder DB.

### Bestehende Gutschriften

Beim Kontextladen:

- vorhandene Gutschriften ermitteln.
- Anzahl und Summe anzeigen.
- Wenn vorhanden, vor Ausfuehrung eine explizite Warnbestaetigung verlangen.

### Teil-Erfolg

Teil-Erfolg ist realistisch und muss sauber behandelt werden:

- sevDesk-Gutschrift/Storno erfolgreich, Wix fehlgeschlagen.
- Wix erfolgreich, Mail fehlgeschlagen.
- Gutschrift erstellt, aber Mail nicht versendet.

UI:

- Nicht als kompletter Fehler darstellen.
- Meldung mit naechsten Schritten:
  - "Wix manuell pruefen"
  - "Rueckueberweisung manuell pruefen"
  - "Mail separat senden"

### Reload

Nach Abschluss:

- Popup schliesst.
- Rechnungsliste wird aktualisiert.
- Optional Statusbar:
  - `Rueckerstattung erstellt: RE-...`
- Spaeter: Fulfillment-/Audit-Spalte aktualisieren.

## Async- und Performance-Vorgaben

Alle externen Operationen laufen im Hintergrund:

- Kontext laden:
  - sevDesk Invoice Positions.
  - Wix Order.
  - Wix Refundability.
  - vorhandene CreditNotes.
  - Bankdaten.
- Ausfuehren:
  - sevDesk cancel/create credit note/save.
  - Wix refund.
  - Mail.

Keine Netzwerkarbeit im Klickhandler.

Falls der aktuelle Arbeitsstand mit `BackgroundJobManager` fertig ist:

- Refund-Kontext in Queue `network`.
- Refund-Ausfuehrung in Queue `network` mit hoechster Prioritaet und Doppelklickschutz.

Sonst:

- Bestehender `BackgroundWorker` reicht fuer erste Umsetzung.

## Tests

### Unit Tests Service

Neue Tests:

```text
tests/unit/test_refund_service.py
```

Faelle:

- Kontext laedt Positionen, Wix-Refundability und Bankdaten.
- Positionen werden ueber SKU auf Wix-LineItems gematcht.
- Positionen werden ueber Namen gematcht, wenn SKU fehlt.
- Bestehende CreditNotes werden als Warnung/Summe dargestellt.
- Teilrefund erstellt CreditNote und entfernt nicht ausgewaehlte Positionen.
- Teilrefund passt Mengen korrekt an.
- Wix-LineItem-Refund wird mit integer quantity gebaut.
- Versand wird nur eingebaut, wenn verfuegbar und ausgewaehlt.
- Ohne Wix-Order wird `manual_transfer_required=True`.
- Mailfehler fuehrt zu Teil-Erfolg, nicht zu komplettem Rollback.

### UI Tests Delegate

Erweitern:

```text
tests/ui/test_rechnungen_view_smoke.py
```

Faelle:

- `_ActionsDelegate._ACTION_KEYS` enthaelt `refund`.
- `action_at_x()` erkennt das Refund-Icon.
- `_run_row_action(summary, "refund")` ruft `_open_refund_dialog(summary)`.
- Tooltip enthaelt Rueckerstattung.

### UI Tests Dialog

Neue oder erweiterte Tests:

```text
tests/ui/test_refund_dialog.py
```

Faelle:

- Dialog zeigt sofort Rechnungsdaten.
- Kontext-Load aktiviert Positionsauswahl.
- Versandcheckbox ist nur aktiv, wenn Betrag vorhanden.
- Execute-Button bleibt disabled ohne Auswahl.
- Execute startet Worker und deaktiviert Button.
- Erfolgsmeldung schliesst Dialog.
- Fehlermeldung schliesst Dialog nach Ausfuehrungsfehler, aber nicht bei Validierungsfehler.

### Bestehende Tests aktualisieren

- `tests/unit/test_refund_flow.py` erweitern statt ersetzen.
- Parity-Tests, die "Partial refund UI missing" markieren, nach Umsetzung auf aktiv stellen.

## Umsetzung in Phasen

### Phase 1 - Button und bestehender Full-Refund-Weg

Ziel: Refund-Icon in `AKTIONEN`, Klick oeffnet bestehenden Dialog.

Schritte:

1. `_ActionsDelegate` um `refund.png` erweitern.
2. Spaltenbreite `AKTIONEN` anpassen.
3. Tooltip anpassen.
4. `_run_row_action()` um `refund` erweitern.
5. Tests fuer Delegate und Dispatch ergaenzen.

Ergebnis:

- Nutzer kann Refund aus der Zeile starten.
- Funktional noch Full-Refund-only.

### Phase 2 - Neuer RefundService und Kontextladen

Ziel: Legacy-Kontext intelligent in Service-Modelle uebertragen.

Schritte:

1. `services/refunds/models.py` anlegen.
2. `services/refunds/service.py` anlegen.
3. Legacy-Logik fuer `_build_refund_lines()` kontrolliert portieren.
4. Fehlende sevDesk-CreditNote-Methoden ergaenzen.
5. Service im Container registrieren.
6. Unit-Tests fuer Kontext und Matching.

Ergebnis:

- Dialog kann Positionen, Versand und Warnungen anzeigen.
- Noch keine Ausfuehrung oder nur Dry-Run.

### Phase 3 - PySide6 RefundWorkflowDialog

Ziel: Popup mit Legacy-Auswahlmoeglichkeiten, aber PySide6-native.

Schritte:

1. Dialog-Layout neu bauen:
   - Kopf.
   - Moduswahl.
   - Positionstabelle.
   - Zusatzoptionen.
   - Vorschau.
2. Kontext im Worker laden.
3. Auswahllogik und Summe live berechnen.
4. Validierung implementieren.
5. UI-Tests.

Ergebnis:

- Nutzer kann Teilpositionen und Versand auswaehlen.
- Noch ohne produktive Ausfuehrung, falls Phase 2 nur Dry-Run war.

### Phase 4 - Ausfuehrung und Ergebnis

Ziel: Echte Rueckerstattung ausfuehren.

Schritte:

1. `RefundService.execute()` implementieren.
2. Vollstorno-Modus an bestehenden `cancel_invoice + refund_full_order` koppeln.
3. Teilrefund-Modus an CreditNote-Erstellung und Wix-LineItem-Refund koppeln.
4. Teil-Erfolg sauber modellieren.
5. Dialog schliesst nach Ergebnis.
6. Rechnungsliste aktualisieren.
7. Audit-Log schreiben.

Ergebnis:

- Produktiver neuer Rueckerstattungsfluss.

### Phase 5 - Rueckbau und Politur

Schritte:

1. Alten Full-Refund-Dialog-Code entfernen oder als Modus im neuen Dialog belassen.
2. Parity-Dokumentation aktualisieren.
3. Refunds-Queue im Tagesgeschaeft optional auf neuen Dialog verlinken.
4. Status/Audit in Detailpanel anzeigen.
5. Performance-Metriken fuer Kontextladen und Ausfuehrung loggen.

## Offene fachliche Entscheidungen

Diese Punkte sollten vor produktiver Umsetzung bestaetigt werden:

1. Soll der Standardmodus im Dialog **Teilrueckerstattung/Gutschrift** sein?
   - Empfehlung: ja, weil sicherer als `cancelInvoice`.
2. Soll **Vollstorno** ueberhaupt im gleichen Dialog bleiben?
   - Empfehlung: ja, aber mit deutlicher Warnung und zweiter Bestaetigung.
3. Soll bei Teilrueckerstattung die Gutschrift automatisch per sevDesk-Mail versendet werden?
   - Empfehlung: Checkbox, default an, wenn Kundenmail ermittelbar.
4. Soll ein Wix-Kundenmail-Flag getrennt von der sevDesk-Gutschriftmail steuerbar sein?
   - Empfehlung: ja, zwei Checkboxen.
5. Soll das Popup bei Ausfuehrungsfehler immer schliessen?
   - User-Wunsch: Erfolg/Error-Meldung und Popup schliesst.
   - Empfehlung: Validierungsfehler bleiben offen, Ausfuehrungsfehler schliessen nach Meldung.

## Minimaler erster Patchumfang

Wenn schnell ein sichtbarer Fortschritt gebraucht wird:

1. `_ActionsDelegate` um `refund` erweitern.
2. `_run_row_action()` um `refund` erweitern.
3. Existing `RefundDialog` ueber AKTIONEN erreichbar machen.
4. Tests fuer Icon und Dispatch.

Danach erst den grossen RefundService und Dialog umbauen.

## Risiken

- sevDesk CreditNote-Save-Payloads sind empfindlich. Vor Live-Betrieb mit Mock und einer Testrechnung pruefen.
- Wix-LineItem-Refund erwartet je nach API nur bestimmte Felder und ggf. ganzzahlige Mengen.
- `cancelInvoice` ist irreversibel.
- Teil-Erfolg ist fachlich normal und darf nicht verschluckt werden.
- Doppelte Gutschriften muessen verhindert oder mindestens deutlich gewarnt werden.

## Akzeptanzkriterien

- In `RECHNUNGEN` ist in der Spalte `AKTIONEN` ein Refund-Symbol sichtbar.
- Klick auf das Refund-Symbol oeffnet ein Popup fuer genau diese Rechnung.
- Popup laedt Kontext asynchron und blockiert die App nicht.
- Popup zeigt Positionen, Mengen, Versandoption, Mailoptionen und bestehende Gutschriften.
- Abschlussbutton fuehrt den gewaehlten Refund im Hintergrund aus.
- Nach Abschluss erscheint eine klare Erfolg-/Teil-Erfolg-/Fehlermeldung.
- Popup schliesst nach der Abschlussmeldung.
- Rechnungen-Liste wird aktualisiert.
- Unit- und UI-Tests decken Button, Dialog und Service ab.

