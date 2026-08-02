# Zahlungsclearing: book_invoice-Haertung

Stand: 08.07.2026

## Ziel

Die PySide6-App soll den aktuellen Zahlungsclearing-Flow behalten, aber beim eigentlichen
sevDesk-Buchen dieselbe robuste `book_invoice`-Semantik verwenden wie das Legacy-System.

Wichtig ist die Trennung:

- Der aktuelle PySide6-Flow ist fuehrend fuer Analyse, Matching, Batch-Auswahl,
  Revalidierung und UI.
- Das Legacy ist fuehrend fuer den konkreten sevDesk-Buchungsaufruf und die
  Nachpruefung der Buchung.

## Quellen

Legacy:

- `C:\Users\XeisWorks\GitHub\sevDesk\zahlungsabgleich.py`
- `C:\Users\XeisWorks\GitHub\sevDesk\integrations\sevdesk_api.py`

Aktuelle App:

- `src/xw_office/services/clearing/service.py`
- `src/xw_office/services/clearing/gateways.py`
- `src/xw_office/services/sevdesk/invoice_client.py`
- `src/xw_office/services/invoice_processing/service.py`
- `src/xw_office/ui/modules/payment_clearing/view.py`

## Legacy-Verhalten

`zahlungsabgleich.py` ruft fuer bestaetigte Matches `sevdesk_api.sevdesk_book_invoice(...)`.
Die relevante Implementierung liegt in `integrations/sevdesk_api.py`.

Der Legacy-Vertrag:

1. Betrag auf zwei Nachkommastellen normalisieren.
2. Rechnung live laden.
3. Wenn die Rechnung bereits bezahlt ist, nicht erneut buchen.
4. CheckAccountTransaction live laden.
5. Wenn die Transaktion bereits Status `400` hat, als bereits gebucht behandeln.
6. Wenn die Transaktion zu einem anderen Konto gehoert, nicht buchen.
7. Buchhaltungssystemversion lesen.
8. Bei Version `1.0`: `CheckAccountTransaction/{transaction_id}/linkInvoice`.
9. Bei neueren Versionen: `Invoice/{invoice_id}/bookAmount`.
10. Danach Rechnung und Transaktion erneut laden.
11. Nur wenn die Rechnung bezahlt ist, gilt die Buchung als bestaetigt.
12. Wenn die Rechnung bezahlt ist, die Transaktion aber nicht Status `400` hat,
    wird Status `400` nachgezogen.

Das richtige v2-Payload fuer `bookAmount`:

```json
{
  "amount": 29.9,
  "date": 1783065600,
  "type": "FULL_PAYMENT",
  "checkAccount": {
    "id": 11,
    "objectName": "CheckAccount"
  },
  "checkAccountTransaction": {
    "id": 99,
    "objectName": "CheckAccountTransaction"
  },
  "createFeed": false
}
```

Das ist der kritische Punkt: Nicht nur `linkInvoice` und nicht ein nacktes
`bookAmount` ohne `checkAccountTransaction`, sondern genau der Legacy-Pfad fuer die
aktive Buchhaltungssystemversion.

## Aktueller PySide6-Flow

Der aktuelle Flow ist fachlich weiter als das Legacy-Skript:

1. Analyse ist read-only.
2. Stripe, Mollie, Wix, sevDesk-Rechnungen und vorhandene sevDesk-Transaktionen werden
   in normalisierte Fachmodelle ueberfuehrt.
3. Provider-ID wird ueber Wix zur Wix-Order-Nr. aufgeloest.
4. Wix-Order-Nr. wird gegen sevDesk-Rechnungsreferenzen gematcht.
5. Doppelte Referenzen, Betragsabweichungen, Entwuerfe und bereits bezahlte Rechnungen
   werden nicht automatisch gebucht.
6. SEPA-Zahlungen werden aus vorhandenen sevDesk-Transaktionen erkannt.
7. Erst nach UI-Bestaetigung schreibt der Batch.
8. Vor jedem Schreiben wird die aktuelle Rechnung erneut geprueft.
9. Fehlende Provider-Transaktionen werden idempotent importiert.
10. Einzelne Fehler stoppen nicht den gesamten Batch.

Dieser Ablauf bleibt erhalten.

## Umsetzung

### Gemeinsame Buchungsdetails

Neu:

- `src/xw_office/services/sevdesk/payment_booking.py`

Dieser Helper kapselt die Legacy-relevanten Details:

- `normalize_booking_amount(...)`
- `is_paid_invoice_object(...)`
- `book_amount_payload(...)`
- `response_payload(...)`
- `raise_on_error_envelope(...)`

Grund: sevDesk kann HTTP 200 liefern und trotzdem ein `error`-Objekt im JSON enthalten.
Das wird nun explizit als Fehler behandelt.

### Invoice-Client

`InvoiceClient.book_invoice_with_transaction(...)` bleibt die Methode des aktuellen
Rechnungsprozesses. Sie nutzt jetzt aber:

- das gemeinsame `bookAmount`-Payload,
- die gemeinsame Paid-Erkennung,
- Error-Envelope-Pruefung,
- Legacy-Fallback fuer `linkInvoice` mit `PUT` und danach `PATCH`.

Damit bleibt der aktuelle Rechnungsprozess erhalten, nutzt aber denselben
sevDesk-Buchungsvertrag wie das Legacy.

### Payment-Clearing-Gateway

`SevdeskClearingGateway.book_invoice(...)` wurde von einer einfachen Schreiboperation
zu einer bestaetigenden Buchungssequenz erweitert:

1. Rechnung live per ID laden.
2. Bereits bezahlt erkennen.
3. Transaktion live laden.
4. Status `400` erkennen.
5. Kontomismatch erkennen.
6. Buchhaltungssystemversion entscheiden.
7. Version `1.0`: `linkInvoice` mit PUT/PATCH-Fallback.
8. Version `>1.0`: `Invoice/{id}/bookAmount` mit `checkAccountTransaction`.
9. Rechnung und Transaktion nach dem Schreiben erneut laden.
10. Nur bestaetigte Buchungen als `booked` melden.

Rueckgabe ist jetzt ein Status-Dict analog zum Rechnungsprozess:

- `booked`
- `already_booked`
- `invoice_already_paid`
- `account_mismatch`
- `not_booked`

### Payment-Clearing-Service

`PaymentClearingService.book_selected(...)` wertet den Rueckgabestatus jetzt aus.

Erfolg:

- `booked`
- `already_booked`
- `invoice_already_paid`

Fehler:

- jeder andere bestaetigte Status, besonders `not_booked` und `account_mismatch`

Zusaetzliche Haertung:

- Wenn die Rechnung beim Live-Recheck bereits bezahlt ist, wird keine neue
  CheckAccountTransaction importiert.
- Wenn nach dem Import die eigentliche Rechnungsbuchung nicht bestaetigt wird, bleibt
  die neu erzeugte Transaktions-ID im Fehlerergebnis sichtbar.

## Tests

Ergaenzt in `tests/unit/test_payment_clearing_service.py`:

- v2 nutzt `PUT /Invoice/{id}/bookAmount` mit `checkAccountTransaction`.
- v1 nutzt `linkInvoice` und faellt von `PUT` auf `PATCH` zurueck.
- Ein Rueckgabestatus `not_booked` wird im Batch als Fehler behandelt.
- Eine inzwischen bezahlte Rechnung erzeugt keine neue Konto-Transaktion.

## Betriebsnotiz

Diese Aenderung fuehrt keine Live-Schreiboperation aus. Sie aendert die lokale
Implementierung und die Tests. Ein echter sevDesk-Schreibtest sollte weiterhin nur mit
separater Freigabe und einem einzelnen bekannten Testfall erfolgen.
