# XW-Office: gefuehrte digitale Lizenzlieferung

Stand: 2026-09-15  
Zielsystem: `XW-Studio` / `XW-Office`  
Referenzfall: Wix-Bestellung `#21222`  
Status dieses Dokuments: verbindliche Umsetzungsgrundlage, noch keine Code-Umsetzung

## 1. Ziel

Bezahlte Bestellungen aus dem Wix-Payment-Link-Flow fuer digitale Noten muessen in XW-Office als eigener, manuell kontrollierter Liefertyp verarbeitet werden.

Der Ablauf soll:

1. die Rechnung in sevDesk finalisieren und die Zahlung wie bisher verarbeiten,
2. weder Rechnung noch Versandlabel physisch drucken,
3. weder die normale sevDesk-Rechnungsmail senden noch Wix vorzeitig als geliefert markieren,
4. nach `START` fragen, ob die digitale Lieferung jetzt ausgefuehrt werden soll,
5. bei `Nein` einen persistenten Alarm in `RECHNUNGEN` stehen lassen,
6. bei `Ja` einen gefuehrten Wizard starten,
7. fehlende Druck-PDFs abfragen und dauerhaft dem Produkt zuordnen,
8. pro eindeutigem Titel genau eine seitlich personalisierte PDF erzeugen,
9. die erzeugten Noten-PDFs im gemeinsamen OneDrive-Ordner speichern und zur Kontrolle oeffnen,
10. erst nach ausdruecklicher PDF-Bestaetigung einen gespeicherten Outlook-Classic-Entwurf mit Rechnung und Noten erstellen,
11. erst nach der manuellen Bestaetigung `E-Mail wurde gesendet` Wix-Fulfillment und lokalen Abschluss setzen.

Der Benutzer versendet die E-Mail selbst in Outlook Classic. XW-Office darf das blosse Erstellen oder Oeffnen eines Entwurfs niemals als erfolgreichen Versand behandeln.

## 2. Festgelegte Produktentscheidungen

- Das Popup erscheint nach dem normalen `START`-Lauf.
- `Nein` erzeugt keinen Outlook-Entwurf. Der Fall bleibt hinter einem Alarm offen.
- Ein Klick auf den Alarm oeffnet den neuen Wizard.
- Erledigt wird erst nach dem expliziten Klick auf `E-Mail wurde gesendet`.
- Die Rechnung wird vorher in sevDesk finalisiert, aber nicht automatisch per sevDesk-Mail versendet und nicht physisch gedruckt.
- Pro Titel wird genau eine lizenzierte PDF erzeugt; die bestellte Menge vervielfacht die Datei nicht.
- Fuer das Wasserzeichen wird der vollstaendige bereinigte Kundenname verwendet.
- Der Zielordner wird rechnerunabhaengig ueber den gemeinsamen OneDrive-Pfad aufgeloest.
- Bereits als `FULFILLED` gemeldete Altfaelle wie `#21222` muessen wiederaufnehmbar sein und duerfen kein zweites Wix-Fulfillment erzeugen.
- Es wird kein XW-Flow-Task angelegt. XW-Office bleibt fuer diesen operativen Vorgang das fuehrende System.

## 3. Ist-Analyse

### 3.1 Wix-Website

Relevante Dateien:

- `XW-Website_v2/src/pages/Digitale Noten.cs5n0.js`
- `XW-Website_v2/src/backend/digitalSheetMusicOrder.web.js`

Der Website-Flow erstellt einen nicht versendbaren Payment Link. Fuer jeden ausgewaehlten Titel werden eine Custom-Position des Notenprodukts und eine Position `Digital Delivery Handling` angelegt. Die Positionen sind nicht versendbar und tragen den Custom-Typ `PAYLINK_ITEM`.

Der Vertrag ist fuer den geplanten XW-Office-Umbau ausreichend. Im Regelfall sind im Website-Repo keine Produktivaenderungen erforderlich.

### 3.2 wix-sevdesk-api

Die API verarbeitet diese Bestellung bereits korrekt bis zum sevDesk-Rechnungsentwurf. Der Umbau darf die funktionierende Rechnungserzeugung nicht duplizieren oder durch eine zweite Integrationsroute ersetzen.

Im Regelfall sind im Repo `wix-sevdesk-api` keine Produktivaenderungen erforderlich. Seine Aufgabe endet weiterhin mit der korrekten Rechnungserzeugung beziehungsweise -bereitstellung in sevDesk.

### 3.3 XW-Office

Bereits vorhanden:

- `WixOrdersClient.is_reference_digital_only()` erkennt nicht versendbare Positionen als digital-only.
- `WixOrdersClient.is_reference_manual_digital_license()` erkennt derzeit digital-only plus Custom-Payment-Link.
- `InvoiceProcessingService.run_start_fullflow()` ueberspringt bei digital-only bereits Rechnung- und Labeldruck.
- `DigitalLicenseService` findet externe digitale Bestellungen, ordnet Druckpfade zu, ruft `LayoutToolsService.watermark_side_a4_pdf()` auf und erstellt einen Outlook-Entwurf.
- `DigitalLicensesDialog` zeigt offene Faelle an.
- In `TagesgeschaeftView` existiert bereits der Alarm `EXTERNE BESTELLUNG`.
- `outlook_compose.py` isoliert Outlook COM in einem Subprozess und erhaelt die Outlook-Signatur.

Aktuelle Fehlstellen:

- Der normale `START`-Flow und der Lizenzierungsflow laufen getrennt.
- `START` kann Wix-Fulfillment und den normalen Rechnungsversand bereits ausfuehren, bevor die lizenzierte PDF kontrolliert wurde.
- Die Rechnung wird nicht an den Lizenzmail-Entwurf angehaengt.
- Das lizenzierte PDF wird nach der Erzeugung nicht automatisch geoeffnet.
- Es gibt keinen gefuehrten, persistenten Zwischenzustand.
- Der Abschluss wird aktuell nur in `settings_kv` unter `digital_licenses.completed` gespeichert.
- Der Standard-Ausgabeordner ist auf einen einzelnen Windows-Benutzer hartcodiert.
- `_license_name()` reduziert den Namen auf maximal zwei Bestandteile.
- Wiederholtes Vorbereiten erzeugt wegen `_next_available_path()` unnoetige Dateiduplikate.
- Outlook-Entwuerfe werden nicht mit einer stabilen `EntryID` fuer spaeteres Wiedereroeffnen verwaltet.

### 3.4 Referenzfall `#21222`

Der lokale Wix-Cache zeigt fuer `#21222`:

- Status `APPROVED`, Zahlung `PAID`, Fulfillment `FULFILLED`,
- Notenposition `Riserva`, SKU `XW-4573`, nicht versendbar,
- Zusatzposition `Digital Delivery Handling`, SKU `XW-033`, nicht versendbar,
- beide Positionen als `PAYLINK_ITEM`.

Der Fall belegt den Architekturfehler: Wix kann bereits erfuellt sein, obwohl der kontrollierte Lizenzversand noch offen ist. Die neue Wiederaufnahme darf deshalb nicht allein vom Wix-Fulfillmentstatus oder von offenen sevDesk-Entwuerfen abhaengen.

## 4. Fachliche Klassifikation

Es werden drei fachlich getrennte Liefertypen benoetigt:

```text
PHYSICAL
  -> bisheriger Druck-, Label-, Fulfillment- und Mailablauf

AUTOMATIC_DIGITAL
  -> bestehende echte Wix-Digitalprodukte
  -> kein physischer Druck
  -> bisheriger automatischer Rechnungs-/Fulfillmentweg bleibt unveraendert

MANUAL_LICENSED_DELIVERY
  -> nicht versendbare Custom-Payment-Link-Bestellung fuer personalisierte Noten
  -> kein physischer Druck
  -> kein automatischer Rechnungsversand
  -> kein Wix-Fulfillment vor Benutzerbestaetigung
  -> neuer Wizard
```

### 4.1 Erkennungsregel

`MANUAL_LICENSED_DELIVERY` gilt nur, wenn alle folgenden Bedingungen erfuellt sind:

1. Es gibt mindestens eine gueltige Wix-Position.
2. Alle fachlich zu liefernden Positionen sind nicht versendbar beziehungsweise digital.
3. Mindestens eine Position ist `PAYLINK_ITEM`.
4. Es gibt einen belastbaren Lizenzlieferungsmarker, primaer die Position `Digital Delivery Handling` beziehungsweise den bestehenden normalisierten Handling-Token.

Nur `all digital + irgendein Custom-Item` ist langfristig zu breit. Die Handling-Position reduziert Fehlklassifikationen anderer Custom-Payment-Links.

Die Erkennung soll zentral als fachliche Methode bereitstehen, zum Beispiel:

```python
WixOrdersClient.classify_delivery(reference) -> DeliveryKind
```

oder mindestens:

```python
WixOrdersClient.is_reference_manual_licensed_delivery(reference) -> bool
```

`is_reference_manual_digital_license()` kann aus Kompatibilitaetsgruenden delegieren. Es darf keine voneinander abweichenden Erkennungsregeln in `InvoiceProcessingService` und `DigitalLicenseService` geben.

### 4.2 Handling-Position

`Digital Delivery Handling` ist keine auszuliefernde Noten-PDF. Sie wird:

- in Rechnung und Zahlung belassen,
- aus der Liste der zu personalisierenden Titel ausgeschlossen,
- nicht als fehlender Druckpfad angezeigt,
- bei der Ermittlung `eine PDF pro Titel` ignoriert.

## 5. Soll-Zustandsmaschine

Ein Lizenzfall ist ein langlebiger Geschaeftsvorgang und benoetigt eine eigene persistente Zustandsmaschine.

```text
DISCOVERED
    |
    | START finalisiert Rechnung und verbucht Zahlung
    v
PENDING_DECISION ---- Benutzer klickt Nein ----> DEFERRED
    |                                           |
    | Benutzer klickt Ja                        | Alarm / Wizard fortsetzen
    +-------------------------------------------+
    v
PREPARING_FILES
    |
    v
AWAITING_PDF_REVIEW
    |             \
    | korrekt      \ nicht korrekt / spaeter
    v               -> AWAITING_PDF_REVIEW oder DEFERRED
DRAFT_READY
    |
    | Benutzer klickt "E-Mail wurde gesendet"
    v
COMPLETING
    |
    | Wix bereits fulfilled -> idempotent ueberspringen
    | sonst Fulfillment ohne Wix-Kundenmail erstellen
    v
COMPLETED
```

Jeder nichtterminale Zustand kann bei einem technischen Fehler nach `ERROR` wechseln. `ERROR` behaelt den letzten fachlich erfolgreichen Schritt und bietet `Erneut versuchen`. Ein Retry darf keine zweite Rechnungsmail, kein doppeltes Wix-Fulfillment und keine unkontrollierte zweite Lizenzdatei erzeugen.

### 5.1 Offene Zustaende

Fuer Alarm und Wizard gelten als offen:

- `DISCOVERED`
- `PENDING_DECISION`
- `DEFERRED`
- `PREPARING_FILES`
- `AWAITING_PDF_REVIEW`
- `DRAFT_READY`
- `COMPLETING`
- `ERROR`

Nur `COMPLETED` verschwindet aus dem Alarm.

## 6. Persistenz

### 6.1 Empfehlung: eigene Tabelle

Die bisherige JSON-Liste `digital_licenses.completed` reicht fuer einen mehrstufigen, wiederaufnehmbaren Workflow nicht aus. Eine eigene PostgreSQL-Tabelle ist vorzuziehen.

Vorgeschlagener Name:

```text
digital_license_fulfillments
```

Vorgeschlagene Kernfelder:

| Feld | Zweck |
|---|---|
| `id` | interner Primaerschluessel |
| `invoice_id` | eindeutige sevDesk-Rechnungs-ID, Unique Constraint |
| `invoice_number` | lesbare Anzeige und Dateiname |
| `order_reference` | Wix-Bestellnummer, indexiert |
| `state` | aktueller Workflowzustand |
| `invoice_finalized_at` | Nachweis der Finalisierung |
| `payment_processed_at` | Nachweis des Zahlungs-Schritts |
| `deferred_at` | Zeitpunkt von `Nein` oder `Spaeter` |
| `licensed_files_json` | persistierte Dateiliste mit SKU, Titel, Pfad und Fingerprint |
| `invoice_attachment_path` | stabiler lokaler Pfad der Rechnungs-PDF fuer den Entwurf |
| `outlook_entry_id` | gespeicherte Outlook-Entwurfs-ID, falls verfuegbar |
| `outlook_store_id` | zugehoerige Store-ID |
| `draft_created_at` | Zeitpunkt der Entwurfserstellung |
| `wix_fulfilled_at` | lokaler Nachweis oder bestaetigter bereits-erfuellt-Status |
| `completed_at` | manueller Gesamtabschluss |
| `last_error` | letzter technischer Fehler, gekuerzt und ohne Payload/PII-Dump |
| `created_at`, `updated_at` | Audit und Sortierung |

Kundenname und E-Mail muessen nicht dauerhaft dupliziert werden, sofern sie beim Oeffnen stabil ueber Wix/sevDesk geladen werden koennen. Falls sie fuer Crash-Recovery gespeichert werden, nur die benoetigten Werte und niemals komplette API-Payloads speichern.

### 6.2 Dateien und Klassen

Neu vorzusehen:

- `src/xw_office/models/digital_license_fulfillment.py`
- `src/xw_office/repositories/digital_license_fulfillment.py`
- `src/xw_office/migrations/versions/008_digital_license_fulfillment.py`
- Exporte in `src/xw_office/models/__init__.py` und `src/xw_office/repositories/__init__.py`
- Registrierung in `src/xw_office/bootstrap.py`

Die Migration darf die bestehende Einstellung `digital_licenses.completed` nicht blind loeschen. Bereits dort abgeschlossene Rechnungs-IDs werden beim ersten Reconcile als `COMPLETED` uebernommen oder weiterhin als Legacy-Abschluss respektiert.

### 6.3 Eindeutigkeit und Nebenlaeufigkeit

- Unique Constraint auf `invoice_id`.
- Optional zusaetzlicher Unique Constraint auf eine nichtleere `order_reference`, falls fachlich garantiert eine Rechnung pro Bestellung existiert.
- Zustandswechsel erfolgen transaktional.
- `complete` muss idempotent sein.
- Badge-Refresh, START und Wizard duerfen denselben Fall parallel lesen, aber nicht doppelt anlegen.
- Ein `updated_at`- oder Versionscheck verhindert, dass ein alter Wizardzustand einen neueren Abschluss ueberschreibt.

## 7. Aenderung des START-Ablaufs

### 7.1 Grundregel

`InvoiceProcessingService.run_start_fullflow()` muss `MANUAL_LICENSED_DELIVERY` vor dem generischen digital-only-Zweig erkennen.

Fuer diesen Typ werden ausgefuehrt:

1. Produkt-Mapping beziehungsweise bestehende Draft-Reparatur,
2. Rechnung finalisieren,
3. Zahlung verarbeiten/buchen,
4. Lizenzfall persistent anlegen oder aktualisieren,
5. Fall-ID im START-Ergebnis an die UI zurueckgeben.

Nicht ausgefuehrt werden:

- `_run_invoice_print_step()`
- `_run_label_print_step()`
- normaler Produkt-/Notendruck
- `_run_mail_step()` beziehungsweise `send_invoice_mail_for_invoice()`
- `_run_product_step()` vor dem manuellen Versandabschluss

Normale physische und automatische digitale Bestellungen duerfen ihr Verhalten nicht aendern.

### 7.2 Rechnung finalisieren, ohne sie zu senden oder zu drucken

Der bestehende digital-only-Zweig delegiert die Finalisierung an `sendViaEmail`. Das ist fuer den neuen Flow ungeeignet, weil die Rechnung zusammen mit den Noten manuell ueber Outlook versendet werden soll.

Vorzusehen ist eine explizite Methode, beispielsweise:

```python
finalize_invoice_without_physical_output(summary) -> FinalizedInvoice
```

Technischer Kandidat ist der bereits verwendete sevDesk-`sendBy`-Pfad mit `sendType="VPR"` und `sendDraft=False`, jedoch ohne anschliessenden Aufruf des lokalen Druckers. Vor dem Rollout muss ein Live-Sandbox-/kontrollierter Test bestaetigen:

- die Rechnung wechselt verlaesslich aus dem Entwurfsstatus,
- eine definitive Rechnungsnummer wird vergeben,
- keine Mail wird von sevDesk versendet,
- kein lokaler Druckjob wird erzeugt,
- `getPdf?preventSendBy=true` liefert danach die richtige finale Rechnung.

`invoice_printed=True` darf dabei nicht gesetzt werden, weil kein physischer Druck stattgefunden hat. Der Finalisierungsstatus gehoert in den Lizenzfall oder in ein neues, fachlich korrekt benanntes Fulfillment-Feld.

### 7.3 Rueckgabe an die UI

Das START-Ergebnis wird ergaenzt, zum Beispiel:

```python
{
    "processed": 3,
    "failures": 0,
    "successful": 3,
    "pending_digital_license_case_ids": ["..."],
}
```

Ein erfolgreich vorbereiteter Lizenzfall ist kein START-Fehler. Die START-Zusammenfassung zeigt getrennt:

```text
Digitale Lieferungen offen: 1
```

### 7.4 Popup nach START

In `TagesgeschaeftView` wird nach Abschluss des BackgroundWorkers auf dem UI-Thread geprueft, ob neue offene Lizenzfaelle gemeldet wurden.

Bei genau einem Fall:

```text
Digitale Lieferung

Bestellung #21222 wurde als manuell zu liefernde digitale Notenbestellung vorbereitet.

Digitale Lieferung jetzt ausfuehren?

[Ja, Wizard oeffnen] [Nein, spaeter]
```

Bei mehreren Faellen wird ein gemeinsames Popup mit Anzahl angezeigt. `Ja` oeffnet den Wizard mit dem ersten offenen Fall; die restlichen bleiben in der Wizard-Liste. Es werden keine gestapelten Einzel-Popups erzeugt.

Bei `Nein`:

- Zustand `DEFERRED`,
- kein Outlook-Entwurf,
- keine PDF-Erzeugung,
- kein Wix-Fulfillment,
- Alarm bleibt sichtbar.

## 8. Alarm in RECHNUNGEN

Der bestehende Button `EXTERNE BESTELLUNG` wird fachlich klar umbenannt:

```text
DIGITALE LIEFERUNG OFFEN (n)
```

Alternativ, falls der Platz nicht reicht:

```text
DIGITAL OFFEN (n)
```

Bevorzugt wird die erste, selbsterklaerende Variante.

Der Count kommt aus der neuen persistenten Tabelle und nicht aus einem teuren Vollscan aller Rechnungen bei jedem 60-Sekunden-Badge-Refresh. Ein separater Reconcile aktualisiert neue Faelle.

Ein Klick oeffnet den Wizard. Der Alarm verschwindet fuer einen Fall ausschliesslich nach `COMPLETED`.

## 9. Wizard

Die bestehende Datei `digital_licenses_dialog.py` soll nicht nur um weitere lose Buttons ergaenzt werden. Sie wird zu einem klaren Wizard beziehungsweise Manager mit Liste links und gefuehrten Schritten rechts umgebaut. Eine Aufteilung in Controller/Pages ist einer weiter wachsenden Einzelklasse vorzuziehen.

Moegliche Dateien:

- `ui/modules/rechnungen/digital_license_wizard.py`
- `ui/modules/rechnungen/digital_license_pages.py`
- bestehendes `digital_licenses_dialog.py` entweder als Listen-Host weiterverwenden oder gezielt ersetzen

### 9.1 Schritt 1: Bestellung pruefen

Anzeige:

- Wix-Bestellnummer
- sevDesk-Rechnungsnummer
- vollstaendiger Kundenname
- Empfaengeradresse
- Liste der Titel mit SKU und Menge
- Status des Druckpfads
- Hinweis, dass je Titel eine PDF erzeugt wird, unabhaengig von der Menge

Aktionen:

- `Weiter`
- `Spaeter`
- bei Fehlern `Daten aktualisieren`

Leere oder unplausible Kunden-E-Mail blockiert den Entwurf. Ein fehlender Kundenname blockiert die Wasserzeichenerzeugung. Beide Fehler werden im Wizard konkret angezeigt.

### 9.2 Schritt 2: Druck-PDFs zuordnen

Fuer jeden eindeutigen Titel wird der hinterlegte Produkt-Druckpfad geladen. Dabei ist sowohl `print_file_path` als auch die tatsaechliche Existenz einer PDF zu pruefen.

Fehlt ein Pfad:

1. Wizard markiert exakt den betroffenen Titel.
2. Dateiauswahl `PDF (*.pdf)` wird angeboten.
3. Auswahl wird validiert.
4. Bei vorhandener SKU wird der Pfad ueber `ProductCatalogService` und `InventoryService.update_product_fields()` dauerhaft gespeichert.
5. Bei leerer SKU bleibt die Zuordnung fallbezogen; sie darf nicht scheinbar erfolgreich in einen nicht existierenden Produktdatensatz geschrieben werden.

Alle Titel muessen einen gueltigen Pfad besitzen, bevor die Erzeugung startet.

### 9.3 Schritt 3: Personalisierte PDFs erzeugen

Wiederverwendet wird ausschliesslich die bestehende Kernfunktion:

```python
LayoutToolsService.watermark_side_a4_pdf(...)
```

Damit bleibt die Ausgabe identisch mit `LAYOUT > WASSERZEICHEN SEITLICH A4`.

Regeln:

- vollstaendiger bereinigter Kundenname, nicht nur die ersten zwei Woerter,
- genau eine Ausgabe pro eindeutigem Titel,
- `quantity` wird angezeigt, vervielfacht die Datei aber nicht,
- Handling-Position wird ignoriert,
- Quelldatei wird niemals ueberschrieben,
- Ausgabe wird persistent dem Lizenzfall zugeordnet,
- ein Retry mit unveraenderter Quelle und unveraendertem Namen verwendet dieselbe bereits erzeugte Datei.

Fuer die Retry-Erkennung wird je Ausgabe mindestens gespeichert:

```text
SKU/Titel + normalisierter Lizenzname + Quellpfad + SHA-256 der Quelldatei
```

Aendert sich die Quelle oder der Lizenzname, muss eine neue Ausgabe erzeugt und erneut geprueft werden.

### 9.4 Zielordner

Fachlicher Zielordner:

```text
OneDrive - XeisWorks\02 XeisWorks\24 Digitale Lizensierung
```

Der Windows-Benutzername darf nicht hartcodiert sein. Vorgeschlagen wird eine Konfiguration in `config/default.yaml`:

```yaml
digital_licenses:
  output_dir: "C:\\Users\\XeisWorks\\OneDrive - XeisWorks\\02 XeisWorks\\24 Digitale Lizensierung"
```

Der Wert dient als kanonischer Shared-Path und wird mit `core/shared_paths.py` auf den lokalen OneDrive-Root abgebildet. Die Aufloesung muss auch funktionieren, wenn der letzte Zielordner noch nicht existiert; nach erfolgreicher Root-Aufloesung darf der Service ihn anlegen.

Aufloesungsreihenfolge:

1. explizit konfigurierter existierender Pfad,
2. `OneDriveCommercial`,
3. `OneDrive`,
4. `USERPROFILE\OneDrive - XeisWorks`,
5. klarer Fehler mit dem erwarteten Pfad.

Kein stiller Fallback in einen fremden Benutzerordner.

### 9.5 Dateien oeffnen und kontrollieren

Nach erfolgreicher Erzeugung werden alle Noten-PDFs mit dem Windows-Standardprogramm geoeffnet. Das Oeffnen geschieht auf dem UI-gesteuerten Pfad nach Ende des BackgroundJobs.

Der Wizard wechselt auf:

```text
PDF-Kontrolle

Die personalisierten PDFs wurden geoeffnet.
Bitte kontrolliere Name, Seiten, Lesbarkeit und Vollstaendigkeit.

[PDFs sind korrekt] [Erneut oeffnen] [Neu erzeugen] [Spaeter]
```

Nur `PDFs sind korrekt` erlaubt den naechsten Schritt. `Spaeter` behaelt die erzeugten Dateien und den Zustand `AWAITING_PDF_REVIEW`; der Alarm bleibt bestehen.

### 9.6 Rechnungs-PDF vorbereiten

Nach erfolgter sevDesk-Finalisierung wird die finale Rechnung mit der bereits zentral vorhandenen PDF-Logik geladen. Die private Methode `_get_invoice_pdf_bytes()` soll nicht aus der UI heraus verwendet werden. Stattdessen ist eine kleine oeffentliche Service-Methode vorzusehen, beispielsweise:

```python
export_final_invoice_pdf(invoice_id, target_dir) -> Path
```

Sie muss dieselben Plausibilitaetspruefungen auf PDF-Signatur und Rechnungsnummer verwenden wie der bestehende Rechnungsversand.

Die Rechnungs-PDF kann in einem stabilen App-State-Unterordner liegen, zum Beispiel:

```text
state/generated/digital-licenses/<invoice-id>/<invoice-number>.pdf
```

Sie muss mindestens bis zum Abschluss des Vorgangs bestehen bleiben. Dieser State-Ordner darf nicht versehentlich in Git aufgenommen werden.

### 9.7 Outlook-Classic-Entwurf

Erst nach bestaetigter PDF-Kontrolle wird der Outlook-Entwurf erzeugt.

Anhaenge in dieser Reihenfolge:

1. finale Rechnung als PDF,
2. je Titel eine personalisierte Noten-PDF.

Empfohlener Betreff:

```text
Your XeisWorks order #21222 – invoice and licensed sheet music
```

Empfohlener englischer Text:

```text
Dear <First name>,

Thank you very much for your order.

Please find attached the invoice and the personally licensed sheet music for your XeisWorks order #<order number>.

The sheet music is licensed to <full customer name> and is intended for the license holder's personal use. Please do not share, upload, resell, or redistribute the files.

If you have any questions, please feel free to contact us.

Best regards,
XeisWorks
```

Die vorhandene Outlook-Signatur bleibt erhalten. Falls die Signatur bereits den Abschluss enthaelt, darf der Text spaeter konfigurierbar gemacht werden; fuer die erste Umsetzung ist obiger Text ausreichend.

### 9.8 Outlook-Entwurf wirklich speichern

`outlook_compose.py` ist zu erweitern:

1. Mail im Drafts-Ordner des konfigurierten Absenderkontos erzeugen.
2. `Display(False)` ausfuehren, damit Outlook die Signatur einsetzt.
3. Absender erneut setzen.
4. Body vor die Signatur setzen.
5. alle Anhaenge hinzufuegen.
6. explizit `mail.Save()` aufrufen.
7. `EntryID` und `StoreID` als JSON an den aufrufenden Prozess zurueckgeben.
8. Entwurf sichtbar lassen.

Der Subprozessvertrag wird rueckwaertskompatibel erweitert. Beispielausgabe:

```json
{
  "ok": true,
  "entry_id": "...",
  "store_id": "..."
}
```

Sind IDs nicht verfuegbar, bleibt der gespeicherte Entwurf dennoch gueltig; der Wizard zeigt dann nur an, dass ein gezieltes Wiedereroeffnen nicht garantiert werden kann.

Bei Zustand `DRAFT_READY` bietet der Wizard:

- `Outlook-Entwurf erneut oeffnen`
- `E-Mail wurde gesendet`
- `Spaeter`

Das Wiedereroeffnen soll nach Moeglichkeit ueber `Namespace.GetItemFromID(entry_id, store_id)` erfolgen und keinen zweiten Entwurf anlegen. Ist der Entwurf geloescht oder nicht mehr auffindbar, fragt der Wizard vor dem Erstellen eines Ersatzentwurfs nach.

## 10. Manueller Abschluss

Nach Klick auf `E-Mail wurde gesendet` erscheint eine letzte Bestaetigung:

```text
Hast du die E-Mail mit Rechnung und allen personalisierten Noten-PDFs in Outlook gesendet?

[Ja, Versand abschliessen] [Zurueck]
```

Erst `Ja, Versand abschliessen` startet den Abschlussjob.

Reihenfolge:

1. Fall transaktional auf `COMPLETING` setzen.
2. aktuellen Wix-Fulfillmentstatus laden.
3. falls bereits `FULFILLED`: als bestaetigt behandeln und keinen Create-Aufruf senden.
4. andernfalls fulfillable Items normalisieren und `create_fulfillment(..., notify_customer=False)` ausfuehren.
5. Erfolg durch Wix-Antwort, vorhandenes Fulfillment oder Status `FULFILLED` bestaetigen.
6. lokalen Zustand auf `COMPLETED` setzen.
7. `completed_at` und `wix_fulfilled_at` speichern.
8. Alarm und Rechnungsansicht aktualisieren.

Schlaegt Wix fehl, bleibt der Fall offen in `ERROR` beziehungsweise `COMPLETING`. Die bereits manuell gesendete E-Mail wird im UI klar als bestaetigt angezeigt; ein Retry darf nur Wix und lokalen Abschluss wiederholen, niemals automatisch noch eine Mail erzeugen.

## 11. Wiederaufnahme und Altfall `#21222`

### 11.1 Reconcile

`DigitalLicenseService.reconcile_candidates()` durchsucht geeignete sevDesk-Statusbereiche und klassifiziert die zugehoerigen Wix-Bestellungen. Fuer jeden erkannten Fall wird idempotent ein Datensatz angelegt.

Der Reconcile laeuft:

- unmittelbar nach einem START-Lauf fuer dessen Rechnungen,
- beim manuellen Aktualisieren des Digital-Wizards,
- beim App-Start oder zeitlich gedrosselt im Hintergrund,
- nicht bei jedem Badge-Count als ungebremster Live-Vollscan.

### 11.2 Bereits erfuellte Wix-Bestellungen

Ein Wix-Status `FULFILLED` bedeutet nicht automatisch, dass die personalisierte E-Mail versendet wurde. Ohne lokalen `COMPLETED`-Nachweis bleibt der Fall offen.

Fuer `#21222` gilt daher:

- als `MANUAL_LICENSED_DELIVERY` erkennen,
- auch bei `FULFILLED` in den offenen Wizard aufnehmen,
- Rechnung/Noten wie normal vorbereiten,
- nach manueller Versandbestaetigung keinen zweiten Fulfillment-Aufruf senden,
- lokalen Fall `COMPLETED` setzen.

Kein produktiver Code darf speziell auf die Nummer `21222` verzweigen. Sie ist ausschliesslich Referenz- und Abnahmetestfall.

### 11.3 Bereits separat versendete Rechnung

Falls sevDesk fuer einen Altfall bereits einen Rechnungsversand meldet, wird dies im Wizard als Hinweis angezeigt:

```text
Hinweis: sevDesk meldet bereits einen frueheren Rechnungsversand. Der kombinierte Outlook-Entwurf kann trotzdem erstellt werden.
```

Der Lizenzversand darf dadurch nicht blockiert werden. Es wird aber niemals versucht, die fruehere Mail rueckgaengig zu machen.

## 12. Service-Schnittstellen

Die genaue Benennung kann bei der Umsetzung angepasst werden; die Verantwortungsgrenzen sollen erhalten bleiben.

```python
class DigitalLicenseService:
    def reconcile_candidates(self, *, invoice_ids: list[str] | None = None) -> list[DigitalLicenseCase]: ...
    def list_open_cases(self) -> list[DigitalLicenseCase]: ...
    def open_count(self) -> int: ...
    def defer(self, case_id: str) -> DigitalLicenseCase: ...
    def apply_print_path(self, case_id: str, line_key: str, path: str) -> DigitalLicenseCase: ...
    def generate_licensed_files(self, case_id: str) -> PreparedLicenseFiles: ...
    def mark_files_reviewed(self, case_id: str) -> DigitalLicenseCase: ...
    def create_or_open_outlook_draft(self, case_id: str) -> OutlookDraftResult: ...
    def confirm_mail_sent_and_complete(self, case_id: str) -> DigitalLicenseCase: ...
```

`InvoiceProcessingService` stellt fachlich benoetigte Rechnungsoperationen oeffentlich bereit, ohne dass `DigitalLicenseService` auf private Methoden zugreift:

```python
def finalize_without_delivery(self, summary: InvoiceSummary) -> InvoiceSummary: ...
def export_final_invoice_pdf(self, invoice_id: str, target_dir: Path) -> Path: ...
```

Externe API-Antworten bleiben mit den im Projekt vorgesehenen Pydantic-Modellen validiert. Vollstaendige rohe Wix-, sevDesk- oder Outlook-Payloads gehoeren weder in den Workflowdatensatz noch in Logs.

## 13. Konkrete Datei-Aenderungen

### 13.1 XW-Studio / XW-Office

Voraussichtlich zu aendern:

- `src/xw_office/services/wix/client.py`
  - zentrale Liefertyp-Klassifikation
  - strikter Handling-Marker
  - idempotente Fulfillment-Pruefung weiterverwenden

- `src/xw_office/services/invoice_processing/service.py`
  - manuellen Lizenztyp vor generischem digital-only behandeln
  - Rechnung ohne Mail/physische Ausgabe finalisieren
  - normale Mail und vorzeitiges Wix-Fulfillment ueberspringen
  - Fall-IDs im START-Ergebnis liefern
  - oeffentlichen finalen PDF-Export anbieten

- `src/xw_office/services/digital_licenses/service.py`
  - von Completed-JSON zu persistenter Zustandsmaschine umbauen
  - Reconcile, Defer, PDF-Erzeugung, Review, Outlook und Complete trennen
  - vollen Kundennamen verwenden
  - Titel deduplizieren
  - Rechnung als Anhang aufnehmen
  - Altfall-/Already-Fulfilled-Logik

- `src/xw_office/services/mailing/outlook_compose.py`
  - Entwurf explizit speichern
  - EntryID/StoreID rueckgeben
  - vorhandenen Entwurf wiedereroeffnen

- `src/xw_office/core/shared_paths.py`
  - gemeinsamen OneDrive-Zielordner auch dann korrekt aufloesen, wenn der letzte Unterordner erst angelegt werden muss

- `src/xw_office/core/config.py`
- `config/default.yaml`
  - `digital_licenses.output_dir`

- `src/xw_office/ui/modules/rechnungen/tagesgeschaeft_view.py`
  - Popup nach START
  - Alarmtext und DB-basierter Count
  - Wizard fuer konkreten Fall oeffnen

- `src/xw_office/ui/modules/rechnungen/view.py`
  - neue Wizard-Schnittstelle beziehungsweise bestehenden Dialog ersetzen

- `src/xw_office/ui/modules/rechnungen/digital_licenses_dialog.py`
  - Umbau oder Ablösung durch Wizard/Manager

- neue Model-, Repository- und Migrationsdateien aus Abschnitt 6

- `src/xw_office/bootstrap.py`
  - Repository und neue Abhaengigkeiten registrieren

### 13.2 XW-Website_v2

Keine fachliche Produktivaenderung geplant. Nur falls ein Contract-Test fehlt, sollte abgesichert werden, dass der erzeugte Payment Link weiterhin:

- Notenposition(en) als nicht versendbar,
- `Digital Delivery Handling`,
- den Modus `digital_sheet_music`

enthaelt.

### 13.3 wix-sevdesk-api

Keine fachliche Produktivaenderung geplant. Bestehende Rechnungslogik bleibt die Quelle fuer den sevDesk-Entwurf. Nur bei einem waehrend der Umsetzung nachgewiesenen Vertragsbruch darf dieses Repo erweitert werden.

### 13.4 XW-Flow

Keine Aenderung. Es wird bewusst kein Task erzeugt.

## 14. Fehlerverhalten

| Fehler | Erwartetes Verhalten |
|---|---|
| Wix-Bestellung nicht erreichbar | Fall nicht als physisch behandeln; Reconcile spaeter erneut versuchen |
| Klassifikation unklar | START darf sicherheitsorientiert stoppen/markieren, nicht drucken |
| Kundenname fehlt | Wasserzeichen blockieren, konkrete Korrektur anzeigen |
| E-Mail fehlt/ungueltig | Outlook-Schritt blockieren, vorherige PDFs behalten |
| Druckpfad fehlt | Titelbezogene Dateiauswahl anbieten |
| Quelldatei fehlt/kein PDF | keine Ausgabe; Pfad als ungueltig markieren |
| Wasserzeichen teilweise fehlgeschlagen | keine Review-Freigabe; erfolgreiche Dateien nicht als Gesamtabschluss werten |
| PDF kann nicht geoeffnet werden | Datei behalten, Pfad anzeigen und erneutes Oeffnen erlauben |
| Rechnung noch nicht final | Outlook-Schritt blockieren; Finalisierung erneut versuchen |
| Rechnungs-PDF unplausibel | keinen Entwurf erzeugen |
| Outlook nicht verfuegbar/Timeout | Zustand offen lassen; PDFs und Rechnung behalten |
| Entwurf gespeichert, App stuerzt ab | `DRAFT_READY`; Alarm erlaubt Wiedereroeffnen |
| Benutzer schliesst Outlook ohne Versand | Fall bleibt `DRAFT_READY` und im Alarm |
| Benutzer sendet, bestaetigt aber nicht | Fall bleibt offen; spaetere manuelle Bestaetigung moeglich |
| Wix bereits `FULFILLED` | als Erfolg behandeln, keinen Create-Aufruf senden |
| Wix-Abschluss nach Mail scheitert | Mailstatus behalten; Retry nur fuer Wix/lokalen Abschluss |

## 15. Tests

### 15.1 Unit-Tests: Klassifikation

In beziehungsweise neben `tests/unit/test_wix_orders_client.py`:

- physische Bestellung bleibt `PHYSICAL`,
- echtes Wix-Digitalprodukt bleibt `AUTOMATIC_DIGITAL`,
- alle nicht versendbar + `PAYLINK_ITEM` + Handling wird `MANUAL_LICENSED_DELIVERY`,
- Custom-Payment-Link ohne Handling wird nicht versehentlich zum Lizenzflow,
- gemischte physische/digitale Bestellung wird nicht als manual licensed klassifiziert,
- leere Positionen liefern `UNKNOWN`/sicheren Fehler statt physisch,
- Handling-Erkennung ist case-insensitive.

### 15.2 Unit-Tests: START

In `tests/unit/test_invoice_processing_fullflow.py`:

- manual licensed finalisiert die Rechnung,
- bucht/verarbeitet die Zahlung,
- ruft keinen Rechnungsdruck auf,
- ruft keinen Labeldruck auf,
- ruft keinen Produktdruck auf,
- ruft keine normale Rechnungs-Mail auf,
- ruft kein Wix-Fulfillment auf,
- gibt die Lizenzfall-ID als pending zurueck,
- normales digital-only und physical bleiben unveraendert,
- Verhalten gilt fuer beide START-Modi,
- Retry legt keinen zweiten Lizenzfall an.

### 15.3 Unit-Tests: DigitalLicenseService

Bestehendes `tests/unit/test_digital_license_service.py` erweitern/umbauen:

- Handling-Zeile wird ignoriert,
- eine PDF pro eindeutigem Titel trotz Menge groesser eins,
- voller Kundenname im Wasserzeichen,
- fehlender Pfad blockiert nur den betroffenen Titel,
- SKU-Pfad wird dauerhaft gespeichert,
- leere SKU wird fallbezogen behandelt,
- unveraenderter Retry verwendet vorhandene Ausgabe,
- geaenderte Quelle erzeugt neue Ausgabe und verlangt neues Review,
- Rechnung ist Bestandteil der Attachment-Liste,
- `defer()` erzeugt keinen Outlook-Entwurf,
- Draft-Erstellung setzt nicht `COMPLETED`,
- `confirm_mail_sent_and_complete()` erzeugt genau ein Wix-Fulfillment,
- bereits `FULFILLED` erzeugt keinen Wix-Create-Aufruf,
- Wix-Fehler nach Mailbestaetigung bleibt retrybar,
- Legacy-Completed-Eintrag bleibt abgeschlossen.

### 15.4 Unit-Tests: Outlook

In `tests/unit/test_outlook_compose.py`:

- richtiges Absenderkonto und dessen Drafts-Ordner,
- `Display` vor Body/Save zur Signaturerhaltung,
- Absender nach `Display` erneut gesetzt,
- Body wird vor vorhandene Signatur gesetzt,
- Rechnung plus alle Noten werden angehaengt,
- `Save()` wird explizit aufgerufen,
- EntryID/StoreID werden zurueckgegeben,
- bestehender Entwurf wird per ID geoeffnet,
- fehlender Anhang erzeugt klaren Fehler und keinen scheinbaren Erfolg.

### 15.5 UI-Tests

In `tests/ui/test_rechnungen_view_smoke.py` oder neuen fokussierten Dateien:

- START-Ergebnis mit einem Fall zeigt das Ja/Nein-Popup,
- `Nein` behaelt Alarm und erzeugt keinen Draft,
- Alarmklick oeffnet Wizard,
- fehlende Druck-PDF verhindert Weiter,
- nach Erzeugung werden PDFs geoeffnet,
- ohne Review-Bestaetigung kein Outlook-Schritt,
- `PDFs sind korrekt` aktiviert Draft-Erstellung,
- Draft-Erstellung zeigt Abschlussseite, entfernt Alarm aber nicht,
- `E-Mail wurde gesendet` plus Bestaetigung schliesst ab,
- `Spaeter` in jedem manuellen Schritt laesst den Fall wiederaufnehmbar,
- mehrere Faelle erzeugen kein Popup-Stapeln,
- Worker laufen nicht im UI-Thread.

### 15.6 Repository-/Migrationstests

- Upsert ist idempotent.
- paralleler Upsert erzeugt nur einen Fall.
- nur `COMPLETED` fehlt im Open-Count.
- Zustandswechsel folgen der erlaubten State Machine.
- alte `digital_licenses.completed`-Daten werden respektiert.
- Migration upgrade/downgrade beziehungsweise projektuebliches Migrationsverhalten funktioniert.

### 15.7 Referenz-Abnahmetest `#21222`

Mit echten Daten, aber ohne personenbezogene Daten in Testlogs:

1. Reconcile findet den Fall trotz Wix `FULFILLED`.
2. Alarm zeigt genau einen offenen Fall, sofern noch kein lokaler Abschluss existiert.
3. Wizard zeigt `Riserva` / `XW-4573` und ignoriert `Digital Delivery Handling`.
4. Druckpfad wird geladen oder abgefragt.
5. genau eine personalisierte Noten-PDF wird erzeugt und geoeffnet.
6. Outlook-Entwurf enthaelt Rechnung und genau eine Noten-PDF.
7. Wix-Create-Fulfillment wird nicht erneut aufgerufen.
8. Nach manueller Versandbestaetigung verschwindet der Fall aus dem Alarm.

## 16. Sicherheits- und Betriebsanforderungen

- Keine automatische Mail mit den lizenzierten Dateien senden.
- Keine komplette Wix-/sevDesk-/Outlook-Payload loggen.
- Keine PDF-Inhalte oder personenbezogenen Daten in Tests/Snapshots aufnehmen.
- Dateipfade in Logs bei Bedarf reduzieren; keine Mailtexte produktiver Kunden protokollieren.
- Outlook bleibt in einem begrenzten Subprozess mit Timeout.
- PDF-Erzeugung, sevDesk-Zugriffe, Wix-Zugriffe und Outlook-COM laufen nicht im Qt-UI-Thread.
- Das Schliessen der App wartet nach bestehendem Worker-Muster oder bricht sicher zwischen fachlichen Schritten ab.
- Quelldateien werden nie veraendert oder geloescht.
- Generierte Lizenzdateien werden bei Fehlern nicht automatisch geloescht.
- Kein Force-Push; Umsetzung gemaess Repository-Regel auf aktuellem `main`, getestet, integriert und nach `origin/main` gepusht.
- Das geschuetzte Architekturarchiv `markdowns/XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md` bleibt unberuehrt.

## 17. Empfohlene Bauphasen fuer Codex 5.6 Luna oder Claude Code

### Phase 1: Domain und Persistenz

1. DeliveryKind-Klassifikation zentralisieren.
2. Model, Repository und Migration fuer Lizenzfaelle anlegen.
3. Legacy-Completed-Kompatibilitaet implementieren.
4. Repository- und Klassifikationstests gruen machen.

Abschlusskriterium: Ein Fall kann idempotent entdeckt, gespeichert, gezaehlt und abgeschlossen werden, noch ohne UI.

### Phase 2: START sauber trennen

1. manual licensed im START vor generic digital erkennen.
2. Finalisierung ohne Mail/physische Ausgabe implementieren und kontrolliert pruefen.
3. Zahlung verarbeiten.
4. Mail, Druck und Wix-Fulfillment fuer diesen Typ unterdruecken.
5. pending Fall-IDs im START-Ergebnis liefern.

Abschlusskriterium: Automatisierte Tests beweisen, dass dieser Typ keinen physischen oder elektronischen Versand vorwegnimmt.

### Phase 3: Datei- und Rechnungsaufbereitung

1. OneDrive-Aufloesung und Konfiguration.
2. voller Lizenzname.
3. Deduplizierung `eine PDF pro Titel`.
4. idempotente Ausgabe-Fingerprints.
5. oeffentlicher Export der finalen Rechnungs-PDF.

Abschlusskriterium: Service erzeugt reproduzierbar alle benoetigten Dateien und kann nach einem Neustart fortsetzen.

### Phase 4: Outlook-Vertrag

1. Draft explizit speichern.
2. EntryID/StoreID zurueckgeben.
3. bestehenden Draft wiedereroeffnen.
4. Rechnung und Noten anhaengen.
5. Tests mit COM-Fakes erweitern.

Abschlusskriterium: Ein gespeicherter Entwurf kann ohne Duplikat wieder geoeffnet werden; Draft-Erstellung schliesst den Fall nicht ab.

### Phase 5: Wizard und Alarm

1. Alarm umbenennen und DB-Count verwenden.
2. Wizardseiten implementieren.
3. PDF-Oeffnen und Review-Gate.
4. Popup nach START.
5. manuelle Versandbestaetigung und Abschlussjob.

Abschlusskriterium: Gesamtablauf ist aus Benutzerperspektive ohne versteckte Nebenwege bedienbar.

### Phase 6: Recovery und Live-Abnahme

1. Reconcile fuer Altfaelle.
2. `#21222` kontrolliert wiederaufnehmen.
3. Already-Fulfilled-Idempotenz pruefen.
4. Outlook-Entwurf und Anhaenge kontrollieren.
5. manuellen Abschluss pruefen.
6. volle relevante Test-Suite ausfuehren.

Abschlusskriterium: `#21222` ist lokal abgeschlossen, ohne doppeltes Wix-Fulfillment und ohne automatischen zweiten Rechnungsversand.

## 18. Definition of Done

Die Umsetzung ist erst fertig, wenn alle folgenden Aussagen wahr sind:

- Payment-Link-Lizenzbestellungen werden eindeutig von physischen und normalen digitalen Bestellungen getrennt.
- `START` finalisiert und verarbeitet die Rechnung, druckt aber weder Rechnung noch Label.
- `START` sendet fuer diesen Typ keine sevDesk-/Graph-Rechnungsmail.
- `START` markiert Wix nicht vorzeitig als erfuellt.
- Nach START erscheint die vereinbarte Ja/Nein-Frage.
- `Nein` erstellt keinen Entwurf und belaesst einen persistenten Alarm.
- Alarmklick oeffnet den Wizard am offenen Fall.
- Fehlende Produkt-PDFs koennen im Wizard dauerhaft zugeordnet werden.
- Pro eindeutigem Titel entsteht genau eine PDF.
- Das Wasserzeichen nutzt den vollstaendigen Kundenname und dieselbe Layout-Kernfunktion wie das bestehende A4-Seitenwasserzeichen.
- Ausgabe landet rechnerunabhaengig im gemeinsamen Ordner `02 XeisWorks\24 Digitale Lizensierung`.
- Alle Noten-PDFs werden vor der Mailerstellung geoeffnet.
- Ohne ausdrueckliche PDF-Freigabe wird kein Outlook-Entwurf erzeugt.
- Der gespeicherte Outlook-Entwurf enthaelt Empfaenger, englischen Betreff/Text, finale Rechnung und alle Noten-PDFs.
- Outlook-Signatur und konfiguriertes Absenderkonto bleiben erhalten.
- Entwurfserstellung gilt nicht als Versand.
- Erst `E-Mail wurde gesendet` plus Bestaetigung schliesst den Fall ab.
- Wix-Fulfillment ist idempotent; bereits erfuellte Bestellung `#21222` wird nicht erneut erfuellt.
- Technische Fehler lassen den Fall sichtbar und wiederaufnehmbar.
- Normaler physischer und automatischer digital-only Ablauf bestehen ihre Regressionstests unveraendert.
- Alle neuen Unit-, UI-, Repository- und Migrations-Tests sind gruen.

## 19. Nicht-Ziele

- Kein automatischer E-Mail-Versand aus Outlook.
- Keine automatische Erkennung, ob der Benutzer in Outlook wirklich auf `Senden` geklickt hat.
- Kein XW-Flow-Task.
- Kein neues Wasserzeichenverfahren; die bestehende A4-Seitenwasserzeichenlogik wird wiederverwendet.
- Keine Aenderung der Preis-, Steuer- oder Rechnungserzeugungslogik in `wix-sevdesk-api`, solange kein konkreter Fehler nachgewiesen wird.
- Keine Sonderbehandlung im Produktivcode nur fuer Bestellnummer `21222`.

