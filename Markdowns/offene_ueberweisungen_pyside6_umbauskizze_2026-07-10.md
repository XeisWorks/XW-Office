# OFFENE UEBERWEISUNGEN in XW-Studio / PySide6 - Umbauskizze

Stand: 2026-07-10

## Review + Verbesserung der Skizze (umgesetzt)

Die Skizze war fachlich bereits sehr gut. Fuer die tatsaechliche Umsetzung wurden nur gezielte Praezisierungen vorgenommen:

1. Transfer-Button-Text wurde einheitlich auf `UEBERWEISUNG OFFEN` festgelegt (Singular plus Count), damit die Badge-Darstellung konsistent bleibt.
2. Silent-Refresh bleibt strikt non-interaktiv: Ohne vorhandenes MSAL-Silent-Token wird immer Cache genutzt; kein Device-Flow aus Badge-Refresh.
3. Outlook bleibt die fuehrende Done-Quelle: `Ueberweisung durchgefuehrt` markiert zuerst in Graph `flagStatus=complete`; nur bei Erfolg wird lokal als erledigt/auditiert gespeichert.
4. Transfer-Postfach wurde als eigene Secret-Variable umgesetzt: `MS_GRAPH_TRANSFER_MAILBOX` (Default `transfer@xeisworks.at`).
5. QR-Erzeugung ist deterministisch via `segno.helpers.make_epc_qr(...)`; OpenAI bleibt nur fuer Zusammenfassung/Extraktion-Fallback.

## Umsetzungsstatus (autonom)

### Phase 1 - Graph und Service-Grundlage

Status: erledigt.

Umgesetzt:

- `GraphMailClient` erweitert um:
  - `flag`/`internetMessageId` in Inbox-Listing
  - `get_message_body(...)`
  - `list_pdf_attachments(...)`
  - `download_attachment_bytes(...)`
  - `get_conversation_thread_text(...)`
  - `mark_message_followup_complete(...)`
- Neues Service-Paket `src/xw_studio/services/transfers/`:
  - `models.py`
  - `payment_qr.py`
  - `service.py` (`OffeneUeberweisungenService`)
- Persistenz-Keys fuer Transfers implementiert (`daily_business.open_transfers.*`) plus lokaler Fallback-State.

### Phase 2 - Roter Button im Rechnungen-Untermenue

Status: erledigt.

Umgesetzt:

- Toolbar-Button von Queue-Proxy auf echte Transfer-Funktion umgestellt.
- Text auf `UEBERWEISUNG OFFEN` umgestellt.
- Count kommt primaer aus `OffeneUeberweisungenService.refresh_count_from_graph_silent(...)`.
- Fallback auf vorhandenen Daily-Business-Queue-Count bleibt aktiv.
- Fester Abstand vor START (`addSpacing(18)`) eingefuegt.

### Phase 3 - PySide6-Dialog ohne QR

Status: erledigt (Basis + produktiv nutzbar).

Umgesetzt:

- Neuer Dialog `offene_ueberweisungen_dialog.py` mit:
  - Fallliste links
  - Metadaten/Thread/Summary rechts
  - Buttons `Rechnung zeigen`, `Spaeter - Alarm bleibt`, `Ueberweisung durchgefuehrt`
- `Ueberweisung durchgefuehrt` setzt Outlook-Flag via Graph und entfernt Fall erst danach aus offenem Bestand.
- `Spaeter` erhoeht `defer_count`, setzt `deferred_at`, laesst Fall offen.

### Phase 4 - Payment Extraction und Formular

Status: erledigt (MVP mit Validierung und OpenAI-Fallback).

Umgesetzt:

- Formularfelder fuer Zahlungsdaten sind editierbar.
- Extraktion aus PDF-Text, Mail/Thread und optional OpenAI-Fallback.
- Manuelle Werte ueberschreiben erkannte Werte.
- Feldquellen werden im Payment-Modell gepflegt.

### Phase 5 - QR-Code-Dialog

Status: erledigt.

Umgesetzt:

- `payment_qr_dialog.py` erstellt.
- QR als PNG wird nach `state/generated/transfer_qr/` geschrieben.
- Anzeige im Dialog inklusive Zahlungsdaten, `PNG oeffnen`, `Ordner oeffnen`.

### Phase 6 - Politur, Migration, Betrieb

Status: teilweise erledigt.

Umgesetzt:

- Legacy-`open_transfers_state.json` wird nicht importiert.
- Neue Unit-Tests hinzugefuegt:
  - `tests/unit/test_offene_ueberweisungen_service.py`
  - `tests/unit/test_payment_qr.py`
- Fokus-Tests laufen grün.

Offen fuer Folgeiteration:

- Erweiterte UI-Tests fuer Dialog/Toolbar.
- Optional OCR/OpenCV-Paritaet wie im Legacy.
- Detailliertere Audit-Ansichten im UI.

## Kurzfazit

Die Legacy-Funktion ist nicht nur eine Liste, sondern ein Graph-Mail-Workflow fuer das dedizierte Postfach `transfer@xeisworks.at`, kombiniert mit PDF-Anhang-Analyse und EPC-SEPA-QR-Code-Erzeugung. In XW-Studio gibt es bereits vorbereitete UI-Stellen:

- `src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py`
  - roter Alert-Button fuer Ueberweisungen ist bereits vorbereitet und versteckt.
  - Position ist bereits links von `START`, `STOP`, `Beenden`.
- `src/xw_studio/services/daily_business/service.py`
  - Queue-Kanal `transfers` existiert, ist aber nur eine Stichwort-Klassifikation aus offenen sevDesk-Rechnungen.
- `src/xw_studio/ui/modules/rechnungen/offene_sendungen_dialog.py`
  - gutes PySide6-Muster fuer mailbasierte offene Aufgaben.
- `src/xw_studio/services/mailing/graph_client.py`
  - MS-Graph-Grundlage existiert, ist fuer Ueberweisungen aber noch zu schmal.

Empfehlung: Die neue Funktion als eigenen PySide6-Service `OffeneUeberweisungenService` plus eigenen Dialog bauen. Nicht den generischen `QueuePopupDialog` weiter ausdehnen. Der generische Dialog ist fuer einfache Tabellen gut, aber fuer Rechnungsanhang, Zahlungsfelder, Zusammenfassung, manuelle Korrektur, QR-Vorschau, "spaeter" und "durchgefuehrt" zu begrenzt.

## Geklaerte Entscheidungen

Festlegungen nach Rueckfrage:

1. Jede Mail in `transfer@xeisworks.at` gilt als offene Ueberweisung, solange sie in Outlook nicht als erledigt markiert ist.
2. `Spaeter` schliesst nur den Dialog. Es gibt keine Zeit-Auswahl und keine Ausblendung.
3. `Ueberweisung durchgefuehrt` soll die Mail in Outlook Classic als erledigt markieren.
4. Der Legacy-State `open_transfers_state.json` wird nicht migriert.
5. OpenAI darf fuer Mailverlauf und Rechnungs-PDFs verwendet werden.

### Klaerung zu Outlook Classic "als erledigt markieren"

Technisch ist das sinnvoll und machbar. Outlook verwendet fuer Mail-Nachverfolgung ein Follow-up-Flag. Microsoft Graph stellt dieses Feld als `message.flag` bereit. Der Status kann `notFlagged`, `flagged` oder `complete` sein. Der Status `complete` entspricht dem erledigten Follow-up-Zustand.

Relevante Microsoft-Graph-Punkte:

- Das Message-Objekt hat ein `flag`-Feld fuer Status, Start-, Due- und Completion-Daten.
- Das `followupFlag` kennt `flagStatus` mit den Werten `notFlagged`, `complete`, `flagged`.
- `PATCH /users/{mailbox}/messages/{id}` kann das `flag`-Feld aktualisieren.
- Dafuer ist `Mail.ReadWrite` erforderlich.

Quellen:

- Microsoft Graph `message` resource: https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0
- Microsoft Graph `followupFlag`: https://learn.microsoft.com/en-us/graph/api/resources/followupflag?view=graph-rest-1.0
- Microsoft Graph `Update message`: https://learn.microsoft.com/en-us/graph/api/message-update?view=graph-rest-1.0

Empfohlene Konsequenz:

- Outlook ist die fuehrende Erledigt-Quelle.
- Der PySide6-Alarm zaehlt alle Mails aus `transfer@xeisworks.at`, deren `flag.flagStatus != "complete"` ist.
- Wenn du eine Mail direkt in Outlook Classic als erledigt markierst, verschwindet sie nach dem naechsten Graph-Refresh auch aus XW-Studio.
- Wenn du im PySide6-Dialog `Ueberweisung durchgefuehrt` klickst, setzt XW-Studio per Graph `flag.flagStatus = "complete"` und speichert zusaetzlich einen lokalen Audit-Snapshot.
- Wenn der Graph-PATCH fehlschlaegt, bleibt der Fall offen. Kein stilles lokales "done", weil sonst Outlook und PySide6 auseinanderlaufen.

Graph-Payload fuer `Ueberweisung durchgefuehrt`:

```json
{
  "flag": {
    "flagStatus": "complete",
    "completedDateTime": {
      "dateTime": "2026-07-10T10:30:00",
      "timeZone": "UTC"
    }
  },
  "isRead": true
}
```

## Gewuenschtes Zielbild

Wenn eine relevante Mail im Postfach `transfer@xeisworks.at` liegt und noch nicht als erledigt markiert wurde, erscheint im Untermenue `RECHNUNGEN` ein auffaelliger roter Button:

```text
UEBERWEISUNG OFFEN (n)
```

Position:

- links neben `START`, `STOP`, `Beenden`
- mit sichtbarem Abstand zur START/STOP/Beenden-Gruppe
- weiterhin nur sichtbar, wenn `n > 0`

Klickverhalten:

- Bei genau einem offenen Fall: Dialog direkt auf diesen Fall oeffnen.
- Bei mehreren offenen Faellen: Dialog mit linker Fallliste und rechter Detailansicht oeffnen.

Dialog-Inhalte:

- intelligente Zusammenfassung des Mailverkehrs
- Mail-Metadaten: Absender, Betreff, Eingangsdatum, Conversation-ID
- Rechnung/PDF-Anhang, falls vorhanden
- editierbare Zahlungsfelder:
  - Empfaenger
  - IBAN
  - BIC
  - Betrag
  - Waehrung, fix `EUR`
  - Zahlungsreferenz / Verwendungszweck
  - Rechnungsnummer
  - optional Faelligkeit
  - optional interne Notiz
- Feldquellen und Plausibilitaet:
  - `mail`
  - `thread`
  - `pdf_text`
  - `pdf_existing_qr`
  - `openai`
  - `manual`

Buttons:

- `Rechnung zeigen`
  - oeffnet PDF-Anhang, wenn vorhanden.
  - bei mehreren PDFs: vorher Auswahl.
- `QR-Code generieren`
  - verwendet die aktuell sichtbaren, editierbaren Felder.
  - manuelle Korrekturen haben immer Vorrang.
- `Spaeter`
  - schliesst Dialog oder markiert Fall als verschoben.
  - Alarm bleibt sichtbar und Count bleibt offen.
  - speichert nur `deferred_at`, optional `defer_count` und Notiz.
- `Ueberweisung durchgefuehrt`
  - setzt die Mail per Microsoft Graph auf Follow-up-Status `complete`.
  - speichert erst danach einen lokalen Audit-Snapshot.
  - entfernt Fall aus offener Liste, weil Outlook nun erledigt ist.
  - schliesst Dialog, wenn danach kein offener Fall mehr vorhanden ist.
  - aktualisiert den roten Button.

## Legacy-Analyse

### Legacy-UI

Relevante Datei:

```text
C:/Users/bernh/GitHub/sevDesk/sevdesk_wix_fulfillment/ui/app.py
```

Gefundene Punkte:

- Legacy initialisiert einen eigenen Graph-Client fuer das Transfer-Postfach.
- Konfigurationswert:
  - `transfer_mailbox_user`
  - Default/Fallback: `transfer@xeisworks.at`
- Das Panel wird als `ToSendPanel` aufgebaut mit:
  - `title="OFFENE UEBERWEISUNGEN"`
  - `state_filename="open_transfers_state.json"`
  - `enable_shipping_tools=False`
  - `enable_qr_tools=True`
  - Count-Callback fuer roten Daily-Business-Hinweis

Das ist wichtig: Legacy behandelt offene Ueberweisungen nicht als Rechnungsliste, sondern als Mail-Inbox-Aufgabenliste.

### Legacy-Mail-Panel

Relevante Datei:

```text
C:/Users/bernh/GitHub/sevDesk/sevdesk_wix_fulfillment/ui/to_send_panel.py
```

Wichtige Funktionen:

- `refresh()`
  - liest Inbox-Mails via Graph.
  - filtert erledigte Mails ueber State-Datei.
- `_open_attachments_or_thread()`
  - zeigt PDF-Anhaenge.
  - falls kein PDF vorhanden ist, zeigt den Conversation-Thread.
- `_generate_qr_from_selected_message()`
  - sucht PDF-Anhaenge.
  - laesst bei mehreren Anhaengen auswaehlen.
- `_generate_qr_from_attachment()`
  - laedt PDF-Bytes via Graph.
  - ruft `generate_epc_qr_from_pdf_bytes(...)` auf.
  - zeigt `PaymentQrDialog`.
- `_mark_done_by_id()`
  - schreibt erledigte Message-ID in `state/open_transfers_state.json`.

Schwachstellen der Legacy-Loesung:

- Nur "done", aber kein echtes "spaeter" / "deferred".
- Erledigt-Status ist nur lokaler State, nicht Outlook-Status.
- QR-Dialog ist Tkinter, nicht PySide6.
- Extraktion ist stark PDF-zentriert; Mailverlauf und Rechnung sollten gemeinsam bewertet werden.
- Count kommt nur aus der Panel-Liste, nicht als eigener wiederverwendbarer Service.
- Kein strukturiertes Datenmodell fuer Zahlungsfelder, Quellen und Vertrauen.

### Legacy-QR-Erzeugung

Relevante Datei:

```text
C:/Users/bernh/GitHub/sevDesk/sevdesk_wix_fulfillment/services/payment_qr.py
```

Wichtige Bausteine:

- IBAN/BIC-Validierung via `python-stdnum`.
- PDF-Textauszug via `pypdf` und `pdfplumber`.
- Scan-/OCR-Fallback via PyMuPDF, Pillow, Tesseract.
- optional OpenAI-Fallback fuer strukturierte Extraktion.
- vorhandenen EPC-QR im PDF erkennen und uebernehmen, wenn OpenCV verfuegbar ist.
- QR-Erzeugung via `segno.helpers.make_epc_qr(...)`.

Das ist fachlich ein guter Kern. Fuer XW-Studio sollte er aber in eine PySide6-taugliche Service-Schicht umgezogen und entschlackt werden.

## XW-Studio-Analyse

### Bereits vorbereitete UI

Relevante Datei:

```text
src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py
```

Ist-Zustand:

- `_btn_transfer_alert = self._build_alert_button("UEBERWEISUNGEN")`
- Button wird initial versteckt.
- Button wird links von `START`, `STOP`, `Beenden` in die Action-Bar eingefuegt.
- `_refresh_badges()` setzt `counts["transfer"]` aus `counts["transfers"]`.
- `_on_transfer_alert_clicked()` oeffnet aktuell nur den generischen Queue-Dialog:
  - `open_queue_dialog("transfers", "OFFENE UEBERWEISUNGEN", ...)`

Empfohlene Anpassung:

- Button-Text auf `UEBERWEISUNG OFFEN` aendern.
- Bei Count > 1: `UEBERWEISUNGEN OFFEN (n)` oder weiterhin `UEBERWEISUNG OFFEN (n)`.
- Vor `START` eine feste Luecke einfuegen, z. B. `bar_lay.addSpacing(18)`.
- Klick nicht mehr auf `QueuePopupDialog`, sondern auf `OffeneUeberweisungenDialog`.

### Current transfer source ist noch falsch

Relevante Datei:

```text
src/xw_studio/services/daily_business/service.py
```

Ist-Zustand:

- Queue `transfers` existiert.
- Live-Daten kommen aus offenen sevDesk-Rechnungen mit Hinweisen wie:
  - `ueberweisung`
  - `banktransfer`
  - `vorkasse`
  - `zahlungsanweisung`
  - `payment qr`
  - `epc qr`
- Das ist fuer den roten Button nur ein Provisorium.

Soll-Zustand:

- Count fuer Ueberweisungen kommt primaer aus `transfer@xeisworks.at`.
- sevDesk-Rechnungen koennen als Zusatzkontext dienen, aber nicht als primaere Quelle.
- Der bestehende Queue-Kanal `transfers` kann als Fallback/Kompatibilitaet bleiben.

### GraphMailClient-Luecke

Relevante Datei:

```text
src/xw_studio/services/mailing/graph_client.py
```

Ist-Zustand:

- kann Inbox-Mails listen.
- kann Mails senden.
- kann silent token pruefen.

Fehlt fuer Ueberweisungen:

- `get_message_body(message_id)`
- `list_pdf_attachments(message_id)`
- `download_attachment_bytes(message_id, attachment_id)`
- `get_conversation_thread_text(conversation_id, days, top)`
- optional `get_message_by_internet_message_id(...)`

Empfehlung:

- Diese Methoden aus dem Legacy-Client uebernehmen und sauber typisieren.
- Dabei die XW-Studio-Variante als zentrale Quelle behalten, nicht einen zweiten Graph-Client importieren.

### Bereits vorhandenes PySide6-Muster

Relevante Dateien:

```text
src/xw_studio/services/sendungen/service.py
src/xw_studio/ui/modules/rechnungen/offene_sendungen_dialog.py
```

Gut uebernehmbar:

- eigener Service statt UI-logiklastigem Panel
- `refresh_from_graph(...)`
- `refresh_count_from_graph_silent(...)`
- lokale/DB-gestuetzte Case-Persistenz
- OpenAI-Zusammenfassung mit Fallback
- Dialog mit linker Liste und rechter Detailansicht

Nicht 1:1 uebernehmen:

- Sendungen extrahieren Adresslabel; Ueberweisungen brauchen Zahlungsdaten, Validierung, QR und Audit-Snapshot.

## QR-Code-Generator: empfohlene Methode

### Entscheidung

QR-Code-Erzeugung nicht mit OpenAI bauen. Der QR selbst soll deterministisch nach EPC-SEPA-Standard erzeugt werden.

Empfohlene Bibliothek:

```text
segno.helpers.make_epc_qr(...)
```

Warum:

- `segno` ist bereits in `pyproject.toml` vorhanden.
- Die Legacy-Funktion verwendet bereits `segno`.
- EPC-QR-Codes haben ein klar definiertes Payload-Format.
- Ein LLM waere fuer QR-Payload-Erzeugung unnoetig riskant.
- OpenAI ist sinnvoll fuer:
  - Zusammenfassung des Mailverlaufs
  - Extraktion unstrukturierter Rechnungsdaten
  - Vision-Fallback bei Scan-PDFs
  - niemals als alleinige Quelle ohne Validierung

Externe Referenzen:

- European Payments Council, EPC069-12 v3.1: Quick Response Code Guidelines for SCT  
  https://www.europeanpaymentscouncil.eu/document-library/guidance-documents/quick-response-code-guidelines-enable-data-capture-initiation
- Segno EPC QR documentation  
  https://segno.readthedocs.io/en/latest/epc-qrcodes.html

Aus der EPC-Quelle relevant:

- Der Standard ist fuer SEPA Credit Transfer gedacht.
- Er passt fuer Rechnungen, bei denen die Zahlungsdaten auch im Klartext auf der Rechnung stehen.
- Fuer Point-of-Interaction-/Terminal-Szenarien ist ein anderer EPC-Kontext relevant; fuer unseren Rechnungsdialog ist EPC069-12 passend.

### Technische Regeln

Validierung vor QR-Erzeugung:

- Empfaenger:
  - Pflichtfeld
  - maximal 70 Zeichen
- IBAN:
  - Pflichtfeld
  - Normalisierung ohne Leerzeichen
  - Validierung via `python-stdnum`
- BIC:
  - optional fuer EWR-Zahlungen
  - wenn vorhanden, validieren
- Betrag:
  - Pflichtfeld
  - Decimal
  - groesser 0
  - zwei Nachkommastellen
- Waehrung:
  - fix `EUR`
- Verwendungszweck / Zahlungsreferenz:
  - optional, aber empfohlen
  - maximal 140 Zeichen
  - wenn leer und Rechnungsnummer vorhanden: Rechnungsnummer verwenden

QR-Erzeugung:

```python
from segno import helpers

qr = helpers.make_epc_qr(
    name=payment.name,
    iban=payment.iban,
    amount=payment.amount,
    text=payment.remittance_text or None,
    bic=payment.bic or None,
)
qr.save(path, kind="png", scale=10)
```

### Extraktionsstrategie

Mehrstufig und nachvollziehbar:

1. PDF-Anhang auf vorhandenen EPC-QR pruefen.
   - Nur wenn OpenCV vorhanden ist.
   - Wenn erfolgreich: Zahlungsdaten aus EPC-Payload parsen.
2. PDF-Textlayer extrahieren.
   - `pypdf`
   - `pdfplumber`
3. Regex-/Validator-Extraktion.
   - IBAN
   - BIC
   - Betrag
   - Rechnungsnummer
   - Verwendungszweck
   - Empfaenger
4. Mailverlauf als Kontext ergaenzen.
   - Betreff
   - Body
   - Conversation-Thread
5. OpenAI nur als Fallback.
   - strukturierte JSON-Ausgabe
   - Felder mit Quelle `openai`
   - danach harte Validierung mit `python-stdnum` und Decimal
6. Manuelle UI-Korrektur.
   - Quelle wird `manual`.
   - Manuelle Werte ueberschreiben alles.

Empfohlener Standard fuer Scan-PDFs:

- Nicht zwingend Tesseract als Systemabhaengigkeit einbauen.
- PyMuPDF rendert Seite 1-2 als Bild.
- OpenAI Vision extrahiert Zahlungsdaten nur, wenn Textlayer/Regex nicht reichen.
- Optional kann Tesseract spaeter als Offline-Fallback hinzukommen.

Abhaengigkeiten:

- Bereits vorhanden:
  - `segno`
  - `python-stdnum`
  - `pypdf`
  - `pdfplumber`
  - `PyMuPDF`
  - `Pillow`
  - `openai`
  - `numpy`
- Fuer volle Legacy-Paritaet optional ergaenzen:
  - `opencv-python` fuer vorhandene QR-Codes im PDF erkennen.
  - `pytesseract` plus externe Tesseract-Installation fuer lokale OCR.

## Zielarchitektur

### Neue Paketstruktur

```text
src/xw_studio/services/transfers/
  __init__.py
  models.py
  service.py
  payment_qr.py

src/xw_studio/ui/modules/rechnungen/
  offene_ueberweisungen_dialog.py
  payment_qr_dialog.py
```

Alternative:

- `payment_qr_dialog.py` kann auch unter `src/xw_studio/ui/dialogs/` liegen, wenn spaeter andere Module QR-Codes nutzen.
- `payment_qr.py` kann unter `src/xw_studio/services/payments/` liegen, wenn der bestehende `services/payments`-Namespace fachlich bevorzugt wird.

### Datenmodelle

Datei:

```text
src/xw_studio/services/transfers/models.py
```

Vorschlag:

```python
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class TransferCaseStatus(str, Enum):
    OPEN = "open"
    DONE = "done"


class TransferFieldSource(str, Enum):
    MAIL = "mail"
    THREAD = "thread"
    PDF_TEXT = "pdf_text"
    PDF_EXISTING_QR = "pdf_existing_qr"
    OPENAI = "openai"
    MANUAL = "manual"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TransferAttachment:
    id: str
    name: str
    content_type: str
    size: int | None = None


@dataclass
class TransferPaymentData:
    recipient: str = ""
    iban: str = ""
    bic: str = ""
    amount: Decimal | None = None
    currency: str = "EUR"
    remittance_text: str = ""
    invoice_number: str = ""
    due_date: str = ""
    source_by_field: dict[str, TransferFieldSource] = field(default_factory=dict)
    confidence_by_field: dict[str, float] = field(default_factory=dict)


@dataclass
class TransferCase:
    id: str
    internet_message_id: str
    conversation_id: str
    received_at: str
    sender: str
    subject: str
    snippet: str
    body: str
    thread_text: str = ""
    summary: str = ""
    attachments: list[TransferAttachment] = field(default_factory=list)
    payment: TransferPaymentData = field(default_factory=TransferPaymentData)
    status: TransferCaseStatus = TransferCaseStatus.OPEN
    outlook_flag_status: str = "notFlagged"
    outlook_completed_at: str = ""
    deferred_at: str = ""
    defer_count: int = 0
    done_at: str = ""
    done_note: str = ""
    qr_path: str = ""
```

Wichtig:

- `deferred_at` ist kein eigener "nicht sichtbar"-Status.
- "Spaeter" laesst `status=OPEN`.
- Button/Alarm zaehlt weiterhin alle offenen Faelle, auch verschobene.
- `outlook_flag_status == "complete"` ist die fuehrende Erledigt-Information.
- `done_at` ist nur Audit/Cache-Spiegel nach erfolgreichem Outlook-Update.

### Persistenz

Primaer:

- `SettingKvRepository`, analog zu `OffeneSendungenService`.

Keys:

```text
daily_business.open_transfers.cases
daily_business.open_transfers.done_audit
daily_business.open_transfers.manual_fields
daily_business.open_transfers.raw_graph
daily_business.open_transfers.qr_history
```

Optional fuer lokale DB-lose Entwicklung:

```text
state/open_transfers_state.json
```

Empfehlung:

- In XW-Studio konsequent `SettingKvRepository` verwenden, wenn DB konfiguriert ist.
- Bei fehlender DB lokal in `state/open_transfers_state.json` fallbacken.
- Legacy-State nicht importieren.
- Der lokale Done-/Audit-State darf den Outlook-Status nicht ersetzen. Wenn eine Mail in Outlook nicht `complete` ist, bleibt sie offen.

Audit-Inhalt fuer erledigte Faelle:

```json
{
  "message_id": "...",
  "done_at": "2026-07-10T10:30:00+00:00",
  "outlook_flag_status": "complete",
  "subject": "...",
  "received_at": "...",
  "payment_snapshot": {
    "recipient": "...",
    "iban": "...",
    "bic": "...",
    "amount": "123.45",
    "currency": "EUR",
    "remittance_text": "RE-123"
  },
  "qr_path": "state/generated/transfer_qr/..."
}
```

### Secrets / Konfiguration

Ist-Zustand:

- `OPENAI_API_KEY` wird bereits von `SecretService` unterstuetzt.
- `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_TENANT_ID`, `MS_GRAPH_MAILBOX` werden bereits unterstuetzt.

Neu empfohlen:

```text
MS_GRAPH_TRANSFER_MAILBOX=transfer@xeisworks.at
```

Warum nicht `MS_GRAPH_MAILBOX` wiederverwenden:

- `MS_GRAPH_MAILBOX` ist aktuell fuer normale Mail-/Sendungen-Workflows gedacht.
- Transfer-Postfach ist fachlich ein separater Eingang.
- Getrennte Konfiguration verhindert, dass `OFFENE SENDUNGEN` und `OFFENE UEBERWEISUNGEN` versehentlich dasselbe Postfach lesen.

Anpassungen:

- `.env.example`
  - `MS_GRAPH_TRANSFER_MAILBOX=transfer@xeisworks.at`
- `SecretService.SUPPORTED_SECRET_KEYS`
  - `MS_GRAPH_TRANSFER_MAILBOX`
- Settings-UI Extra Secrets
  - `MS_GRAPH_TRANSFER_MAILBOX`
- `GraphMailClient` Scopes
  - fuer Transfer-Workflow mindestens `Mail.ReadWrite`
  - `Mail.ReadWrite.Shared`, falls `transfer@xeisworks.at` als Shared Mailbox/delegierter Zugriff betrieben wird
  - vorhandene `Mail.Read`-Scopes reichen fuer `Ueberweisung durchgefuehrt` nicht aus

## Neuer Service: OffeneUeberweisungenService

Datei:

```text
src/xw_studio/services/transfers/service.py
```

Konstruktor:

```python
class OffeneUeberweisungenService:
    def __init__(
        self,
        settings_repo: SettingKvRepository | None,
        secrets: SecretService,
        invoice_processing: InvoiceProcessingService | None = None,
    ) -> None:
        ...
```

Methoden:

```python
def open_count(self) -> int:
    ...

def load_open_cases(self) -> list[TransferCase]:
    ...

def refresh_from_graph(
    self,
    *,
    lookback_days: int = 60,
    max_items: int = 150,
    allow_interactive_auth: bool = True,
) -> list[TransferCase]:
    ...

def refresh_count_from_graph_silent(
    self,
    *,
    lookback_days: int = 60,
    max_items: int = 150,
) -> int:
    ...

def summarize_case(self, case_id: str) -> str:
    ...

def extract_payment_data(self, case_id: str, attachment_id: str | None = None) -> TransferPaymentData:
    ...

def generate_qr(self, case_id: str, payment: TransferPaymentData) -> Path:
    ...

def mark_deferred(self, case_id: str, note: str = "") -> None:
    ...

def mark_done_in_outlook(self, case_id: str, payment: TransferPaymentData, qr_path: str = "", note: str = "") -> None:
    ...

def mark_outlook_flag_complete(self, message_id: str) -> None:
    ...

def list_pdf_attachments(self, case_id: str) -> list[TransferAttachment]:
    ...

def download_attachment_bytes(self, case_id: str, attachment_id: str) -> bytes:
    ...
```

### Graph-Refresh-Regeln

Primaere Quelle:

- Inbox von `MS_GRAPH_TRANSFER_MAILBOX`
- Default: `transfer@xeisworks.at`

Filter:

- Weil das Postfach dediziert ist, zaehlen grundsaetzlich alle Inbox-Mails als offene Ueberweisung.
- Trotzdem ausfiltern:
  - leere Systemmails
  - no-reply-Spam, falls bekannt
  - Mails mit `flag.flagStatus == "complete"`
- Mails mit `flag.flagStatus == "notFlagged"`, fehlendem `flag` oder `flag.flagStatus == "flagged"` bleiben offen.
- Der Filter wird robust clientseitig angewendet, weil die Graph-Unterstuetzung fuer verschachtelte Filter je nach Endpoint/Query begrenzt sein kann.
- `list_inbox_messages(...)` muss deshalb `flag` per `$select` mitladen.

Lookback:

- Default 60 Tage statt 20 Tage.
- Grund: Ueberweisungen koennen laenger liegen bleiben.
- UI zeigt bei alten Faellen auffaellig das Alter.

Silent Refresh:

- Badge-Refresh darf keine interaktive Graph-Anmeldung starten.
- Wenn kein Silent Token vorhanden ist:
  - gecachten Stand verwenden.
  - Status im Dialog anzeigen: `Graph-Anmeldung erforderlich`.

Manueller Refresh:

- Im Dialog darf `allow_interactive_auth=True` verwendet werden.
- Dann kann Device Flow starten, falls Token fehlt.

### Outlook-Erledigt-Update

`Ueberweisung durchgefuehrt` macht zwei Schritte:

1. Microsoft Graph `PATCH` auf die Message:

```http
PATCH /users/transfer@xeisworks.at/messages/{message_id}
Content-Type: application/json
```

```json
{
  "flag": {
    "flagStatus": "complete",
    "completedDateTime": {
      "dateTime": "<utc-now-without-timezone-suffix>",
      "timeZone": "UTC"
    }
  },
  "isRead": true
}
```

2. Erst bei Erfolg:
   - Audit-Snapshot speichern.
   - Fall aus der offenen Liste entfernen.
   - Badge neu berechnen.

Fehlerverhalten:

- Wenn Graph `PATCH` fehlschlaegt, bleibt der Fall offen.
- Es gibt keinen stillen lokalen Done-Fallback.
- Optionaler UI-Text: `Outlook konnte nicht als erledigt markiert werden; Alarm bleibt aktiv.`

### Zusammenfassung

Ziel:

- Schnell erkennen, warum die Mail an `transfer@xeisworks.at` weitergeleitet wurde.
- Keine Zahlungsfelder blind uebernehmen.

Prompt-Ziel:

```text
Fasse den Mailverkehr fuer eine manuelle Ueberweisung zusammen.
Nenne:
1. Was soll bezahlt werden?
2. Wer ist Zahlungsempfaenger?
3. Welche Rechnung/Referenz gehoert dazu?
4. Betrag und Faelligkeit, falls vorhanden.
5. Welche Punkte sind unsicher oder fehlen?
Antworte auf Deutsch, knapp, sachlich.
```

Fallback ohne OpenAI:

- Betreff
- Absender
- erste 700-1000 Zeichen aus Thread/PDF-Text
- erkannte Felder als Liste
- fehlende Pflichtfelder markieren

### Zahlungsdaten-Extraktion

Felder werden nie nur "geglaubt", sondern immer mit Validierung und Quelle versehen.

Priorisierung:

1. Manuell gespeicherte Felder
2. vorhandener EPC-QR im PDF
3. PDF-Text
4. Mail-Thread
5. OpenAI-Fallback

Beispiel fuer Feldquellen:

```json
{
  "recipient": "pdf_text",
  "iban": "pdf_existing_qr",
  "bic": "pdf_existing_qr",
  "amount": "pdf_text",
  "remittance_text": "manual"
}
```

UI-Anzeige:

- Gruener Hinweis: Feld validiert.
- Gelber Hinweis: Feld fehlt oder unsicher.
- Roter Hinweis: IBAN/Betrag ungueltig.
- Neben jedem Feld kleine Quelle, z. B. `PDF`, `QR`, `AI`, `Manuell`.

## Neuer Dialog: OffeneUeberweisungenDialog

Datei:

```text
src/xw_studio/ui/modules/rechnungen/offene_ueberweisungen_dialog.py
```

Layout:

```text
+---------------------------------------------------------------+
| OFFENE UEBERWEISUNGEN                         Aktualisieren   |
+---------------------------+-----------------------------------+
| Liste                     | Meta                              |
| 10.07.  Max Mustermann    | Von / Betreff / Datum / Alter     |
| 08.07.  druck.at          |-----------------------------------|
| ...                       | Zusammenfassung                   |
|                           |-----------------------------------|
|                           | Zahlungsdaten                     |
|                           | Empfaenger [...................]  |
|                           | IBAN       [...................]  |
|                           | BIC        [...................]  |
|                           | Betrag     [........] EUR         |
|                           | Referenz   [...................]  |
|                           |-----------------------------------|
|                           | Rechnung zeigen | QR generieren   |
|                           | Spaeter        | Durchgefuehrt    |
+---------------------------+-----------------------------------+
```

Widgets:

- Links:
  - `QListWidget` oder `DataTable`
  - Spalten/Anzeige:
    - Eingangsdatum
    - Absender
    - Betreff
    - Betrag, falls erkannt
    - Warnsymbol bei fehlenden Pflichtfeldern
    - `verschoben`-Marker, ohne den Fall zu verstecken
- Rechts:
  - `QLabel` fuer Metadaten
  - `QPlainTextEdit` fuer Thread
  - `QPlainTextEdit` fuer Zusammenfassung
  - Formular mit `QLineEdit` / `QDoubleSpinBox` / `QPlainTextEdit`
  - Quellen-/Validierungslabels
- Unten:
  - Aktionsbuttons

Button-Details:

#### `Rechnung zeigen`

Aktiv, wenn mindestens ein PDF-Anhang vorhanden ist.

Verhalten:

- 0 PDFs:
  - Info: `Keine PDF-Rechnung in dieser Mail gefunden.`
- 1 PDF:
  - PDF in bestehendem `PdfPreviewDialog` oeffnen, wenn kompatibel.
  - sonst temporaer speichern und mit Systemviewer oeffnen.
- >1 PDF:
  - kleiner Auswahl-Dialog.

#### `QR-Code generieren`

Vorbedingungen:

- Empfaenger vorhanden
- IBAN valide
- Betrag valide
- Waehrung `EUR`

Verhalten:

- Aktuelle Formularwerte lesen.
- Validieren.
- QR in Zielordner schreiben:

```text
state/generated/transfer_qr/
```

Dateiname:

```text
epc_qr_<safe_subject_or_invoice>_<yyyymmdd_hhmmss>.png
```

Danach:

- PySide6-QR-Dialog oeffnen.
- QR-Grafik anzeigen.
- Payload-Felder anzeigen.
- Button `PNG oeffnen`.
- Optional Button `Ordner oeffnen`.

#### `Spaeter`

Vorgeschlagener Buttontext:

```text
Spaeter - Alarm bleibt
```

Verhalten:

- Speichert optional `deferred_at` und `defer_count += 1`.
- Schliesst nur den Dialog.
- Veraendert Outlook nicht.
- Fall bleibt offen.
- Roter Button bleibt sichtbar.
- Keine Auswahl `heute/morgen/naechste Woche`.

#### `Ueberweisung durchgefuehrt`

Vorgeschlagener Buttontext:

```text
Ueberweisung durchgefuehrt
```

Verhalten:

- Vorher Confirm-Dialog:

```text
Diese Ueberweisung als durchgefuehrt markieren?
Die Mail wird in Outlook als erledigt markiert.
Der Alarm verschwindet danach fuer diesen Fall.
```

- Setzt per Graph `flag.flagStatus = "complete"` und `isRead = true`.
- Speichert erst nach erfolgreichem Graph-Update den erledigt-Snapshot.
- Entfernt Fall aus offener Liste.
- Wenn keine Faelle offen:
  - Dialog schliessen.
  - roten Button verstecken.
- Outlook-Mail wird nicht geloescht und nicht verschoben.

Optional:

- Wenn sich in der Praxis zeigt, dass Outlook Classic den Graph-Status `complete` bei vorher nicht markierten Mails nicht sauber sichtbar darstellt, waere als zweite Option ein Ordner `Erledigt` oder eine Kategorie moeglich.
- Diese zweite Option ist vorerst nicht Teil des Zielverhaltens.

## Integration in Rechnungen-Toolbar

Datei:

```text
src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py
```

Geplante Aenderungen:

1. Import:

```python
from xw_studio.services.transfers.service import OffeneUeberweisungenService
```

2. In `_refresh_badges()`:

```python
transfers_service: OffeneUeberweisungenService = self._container.resolve(OffeneUeberweisungenService)
counts["transfer"] = max(
    0,
    int(transfers_service.refresh_count_from_graph_silent(lookback_days=60, max_items=150)),
)
```

Fallback:

- Wenn Graph/Service fehlschlaegt, bisherigen `DailyBusinessService`-Count verwenden.
- Wenn Graph erreichbar ist, gilt ausschliesslich: offene Mails = Transfer-Inbox-Mails mit `flag.flagStatus != "complete"`.

3. Button-Text:

```python
self._btn_transfer_alert = self._build_alert_button("UEBERWEISUNG OFFEN")
```

4. Platzierung:

```python
bar_lay.addWidget(self._btn_sendungen_alert)
bar_lay.addWidget(self._btn_transfer_alert)
bar_lay.addWidget(self._btn_mollie_alert)
bar_lay.addSpacing(18)
bar_lay.addWidget(self._btn_start)
```

5. Klick:

```python
def _on_transfer_alert_clicked(self) -> None:
    count = self._rechnungen_view.open_ueberweisungen_dialog()
    self._transfer_count = max(0, int(count))
    self._update_alert_button(self._btn_transfer_alert, "UEBERWEISUNG OFFEN", self._transfer_count)
```

## Integration in RechnungenView

Datei:

```text
src/xw_studio/ui/modules/rechnungen/view.py
```

Neue Methode:

```python
def open_ueberweisungen_dialog(self) -> int:
    dlg = OffeneUeberweisungenDialog(self._container, self)
    dlg.exec()
    return dlg.open_count()
```

Bestehender `open_queue_dialog("transfers", ...)` bleibt als Fallback fuer einfache Queue-Daten erhalten, wird aber nicht mehr vom roten Transfer-Button genutzt.

## Service-Registrierung

Datei:

```text
src/xw_studio/bootstrap.py
```

Registrierung:

```python
container.register(
    OffeneUeberweisungenService,
    lambda c: OffeneUeberweisungenService(
        c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        c.resolve(SecretService),
        c.resolve(InvoiceProcessingService),
    ),
)
```

## Payment QR Portierung

Quelle:

```text
C:/Users/bernh/GitHub/sevDesk/sevdesk_wix_fulfillment/services/payment_qr.py
```

Ziel:

```text
src/xw_studio/services/transfers/payment_qr.py
```

Portierungsstrategie:

- Kernfunktionen uebernehmen:
  - IBAN/BIC-Normalisierung
  - Amount-Parsing
  - PDF-Text-Extraktion
  - Regex-Extraktion
  - OpenAI-Fallback
  - EPC-QR-Erzeugung via `segno`
- Tkinter/UI-Code nicht uebernehmen.
- Dateischreibzugriffe ueber klaren `output_dir`.
- OpenCV/Tesseract optional kapseln.
- Fehler als `PaymentQrError` mit nutzerverstaendlicher Meldung.

Empfohlene API:

```python
def extract_payment_data_from_sources(
    *,
    mail_text: str = "",
    thread_text: str = "",
    pdf_bytes: bytes | None = None,
    filename_hint: str = "",
    use_openai_fallback: bool = True,
) -> TransferPaymentData:
    ...


def create_epc_qr_from_payment_data(
    payment: TransferPaymentData,
    *,
    output_dir: Path,
    filename_hint: str = "",
) -> Path:
    ...
```

## OpenAI-Einsatz

### Nutzen

OpenAI ist hier sinnvoll fuer:

- Mailverkehr zusammenfassen.
- Zahlungsdaten aus freiem Mailtext und schwierigen PDFs extrahieren.
- Scan-PDFs ueber Vision analysieren, wenn lokale Textextraktion scheitert.

### Nicht nutzen fuer

- QR-Code-Payload ohne Validierung.
- "Ueberweisung durchgefuehrt" automatisch entscheiden.
- Automatische Bank-Aktion.

### Sicherheitsregeln

- OpenAI-Ergebnis ist nur Vorschlag.
- IBAN/BIC/Betrag werden lokal validiert.
- UI zeigt Quelle `AI`.
- User sieht und kann jedes Feld korrigieren.
- QR wird aus den aktuell sichtbaren Feldern erzeugt.
- Bei unvollstaendigen Pflichtfeldern kein QR.

## Tests

### Unit Tests

Neue Dateien:

```text
tests/unit/test_offene_ueberweisungen_service.py
tests/unit/test_payment_qr.py
```

Tests fuer Service:

- Graph-Mails werden zu `TransferCase`.
- Mails mit `flag.flagStatus == "complete"` werden nicht als offen geladen.
- Mails mit `notFlagged`, `flagged` oder fehlendem `flag` werden als offen geladen.
- `Spaeter` laesst Fall offen und Count unveraendert.
- `Ueberweisung durchgefuehrt` ruft Graph `PATCH` mit `flag.flagStatus = "complete"` auf.
- Bei erfolgreichem Graph-Update wird ein Audit-Snapshot geschrieben.
- Bei fehlgeschlagenem Graph-Update bleibt der Fall offen.
- In Outlook Classic manuell erledigte Mails verschwinden nach Refresh aus XW-Studio.
- Silent Refresh ohne Token nutzt Cache und startet keinen Device Flow.
- Transfer-Postfach kommt aus `MS_GRAPH_TRANSFER_MAILBOX`.
- Transfer-Graph-Client verwendet `Mail.ReadWrite` bzw. `Mail.ReadWrite.Shared`.

Tests fuer Extraktion:

- IBAN mit Leerzeichen wird normalisiert.
- ungueltige IBAN blockiert QR.
- Betrag `1.234,56` wird zu Decimal `1234.56`.
- Rechnungsnummer wird als Referenz verwendet, wenn Verwendungszweck leer ist.
- manuelle Felder ueberschreiben PDF/OpenAI-Felder.

Tests fuer QR:

- `create_epc_qr_from_payment_data` erzeugt PNG.
- Pflichtfelder fehlen -> `PaymentQrError`.
- BIC ungueltig -> wird entfernt oder Fehler, je nach festgelegtem Verhalten.
- Referenz > 140 Zeichen wird gekuerzt oder blockiert, festlegen und testen.

### UI Tests

Neue/erweiterte Datei:

```text
tests/ui/test_rechnungen_view_smoke.py
```

Tests:

- Transfer-Button ist bei Count 0 versteckt.
- Transfer-Button zeigt `UEBERWEISUNG OFFEN (1)` bei Count 1.
- Transfer-Button steht vor `START`.
- Zwischen letztem Alert und `START` existiert Spacing.
- Klick ruft `open_ueberweisungen_dialog()`.

Neue Datei:

```text
tests/ui/test_offene_ueberweisungen_dialog.py
```

Tests:

- Dialog zeigt Fallliste.
- Auswahl befuellt Metadaten und Felder.
- `Spaeter` ruft Service `mark_deferred`.
- `Spaeter` schliesst den Dialog und laesst Count unveraendert.
- `Ueberweisung durchgefuehrt` ruft Service `mark_done_in_outlook`.
- `QR-Code generieren` nutzt bearbeitete Formularwerte.

### Integrations-/Smoke-Test

Optional:

```text
tests/integration/test_open_transfers_graph_smoke.py
```

Nur mit Opt-in Env:

```text
XW_RUN_GRAPH_SMOKE=1
```

Prueft:

- Graph-Client kann Transfer-Postfach listen.
- keine secrets im Log.
- kein interaktiver Login im normalen Testlauf.

## Umsetzung in Phasen

### Phase 1 - Graph und Service-Grundlage

Ziel:

- Ueberweisungsfaelle aus `transfer@xeisworks.at` laden und zaehlen.

Tasks:

- `MS_GRAPH_TRANSFER_MAILBOX` in Secrets/Settings/.env.example aufnehmen.
- Graph-Scopes fuer Transfer auf `Mail.ReadWrite` / bei Shared Mailbox `Mail.ReadWrite.Shared` erweitern.
- `GraphMailClient` erweitern:
  - Body
  - Thread
  - Attachments
  - Attachment Download
  - `flag` im Message-Listing
  - `mark_message_followup_complete(message_id)`
- `services/transfers/models.py` anlegen.
- `OffeneUeberweisungenService` anlegen.
- Service in `bootstrap.py` registrieren.
- Unit Tests fuer Count, Outlook-Erledigt und Deferred.

Akzeptanz:

- Service liefert offene Faelle aus Cache/Graph.
- `open_count()` funktioniert ohne UI.
- Mails mit Outlook-Flag `complete` zaehlen nicht als offen.
- Kein Device Flow beim Badge-Silent-Refresh.

### Phase 2 - Roter Button im Rechnungen-Untermenue

Ziel:

- Button verhaelt sich genau wie gewuenscht.

Tasks:

- Button-Text auf `UEBERWEISUNG OFFEN`.
- Count aus `OffeneUeberweisungenService`.
- Fallback auf bestehenden `DailyBusinessService.transfers`.
- Spacing vor START/STOP/Beenden einfuegen.
- Klick auf neuen Dialog vorbereiten.

Akzeptanz:

- Bei offener Mail sichtbar.
- Bei keiner offenen Mail versteckt.
- Wenn Mail in Outlook Classic als erledigt markiert wurde, verschwindet der Button nach Refresh.
- Button bleibt links von START/STOP/Beenden.

### Phase 3 - PySide6-Dialog ohne QR

Ziel:

- Fall anzeigen, Thread zusammenfassen, PDF zeigen, spaeter und Outlook-Erledigt verwalten.

Tasks:

- `OffeneUeberweisungenDialog`.
- Fallliste links.
- Detail rechts.
- Thread/Body laden.
- PDF-Anhaenge listen.
- `Rechnung zeigen`.
- `Spaeter - Alarm bleibt`.
- `Ueberweisung durchgefuehrt`.

Akzeptanz:

- Dialog kann Faelle bedienen.
- `Spaeter` entfernt keinen Alarm.
- `Durchgefuehrt` setzt Outlook-Follow-up auf `complete` und entfernt erst dann den Fall aus Count.

### Phase 4 - Payment Extraction und Formular

Ziel:

- Zahlungsfelder aus Mail/PDF vorausfuellen, editierbar anzeigen.

Tasks:

- `payment_qr.py` Kern aus Legacy portieren.
- PDF-Text extrahieren.
- Regex/Validatoren.
- Feldquellen speichern.
- OpenAI-Fallback fuer fehlende Felder.
- UI-Validierungslabels.

Akzeptanz:

- Felder werden aus typischen Rechnungen befuellt.
- Ungueltige Pflichtfelder blockieren QR.
- User kann alles manuell korrigieren.

### Phase 5 - QR-Code-Dialog

Ziel:

- EPC-SEPA-QR aus sichtbaren Feldern erzeugen.

Tasks:

- `PaymentQrDialog` in PySide6.
- QR als PNG speichern.
- QR anzeigen.
- `PNG oeffnen`.
- manuelle Korrektur -> neu generieren.
- QR-Historie im Case speichern.

Akzeptanz:

- QR laesst sich mit Banking-App scannen.
- Manuell geaenderter Betrag/Referenz landet im QR.
- Kein QR bei ungueltiger IBAN/Betrag.

### Phase 6 - Politur, Migration, Betrieb

Tasks:

- Legacy `open_transfers_state.json` nicht importieren.
- Alte QR-Ausgaben optional nicht migrieren, nur referenzieren.
- Logs/audit ohne sensible Volltexte.
- Dokumentation in Settings/README.
- Regression Tests fuer Rechnungen-Toolbar.

Akzeptanz:

- Keine bestehende Rechnungen-/START-Funktion bricht.
- Offene Ueberweisungen ersetzen den generischen Queue-Dialog.

## Edge Cases

- Manuell in Outlook Classic als erledigt markiert:
  - Beim naechsten Refresh wird `flag.flagStatus == "complete"` erkannt.
  - Fall verschwindet aus XW-Studio.
  - Lokaler Audit-Snapshot kann fehlen; das ist ok, weil Outlook fuehrend ist.
- Mail ohne PDF:
  - Thread anzeigen.
  - Zahlungsfelder aus Mailtext extrahieren.
  - `Rechnung zeigen` deaktiviert.
- Mehrere PDFs:
  - Auswahl vor Anzeige/Extraktion.
  - zuletzt ausgewaehlte PDF pro Case merken.
- PDF mit vorhandenem EPC-QR:
  - Zahlungsdaten daraus uebernehmen.
  - QR ggf. als "vorhanden" anzeigen.
  - User kann trotzdem neu generieren.
- Scan-PDF ohne Text:
  - OpenAI Vision fallback, wenn API-Key vorhanden.
  - sonst klare Meldung.
- Unklare Betraege:
  - nicht automatisch final uebernehmen.
  - Betrag-Feld gelb markieren.
- BIC fehlt:
  - fuer EWR-SEPA meist ok.
  - QR ohne BIC erlauben, sofern Banking-App-Test passt.
- `Spaeter` mehrfach:
  - `defer_count` hochzaehlen.
  - optional in Liste `3x verschoben` anzeigen.
- Erledigt versehentlich:
  - spaeter optional `Erledigt zuruecknehmen` einbauen.
  - technisch: Graph-PATCH auf `flag.flagStatus = "notFlagged"` oder `flagged`, je nach gewuenschtem Outlook-Zustand.

## Verbleibende offene Frage

- Welche Banking-App soll als Haupttest fuer EPC-QR gelten? Empfehlung: die App, mit der du diese Ueberweisungen tatsaechlich durchfuehrst.

## Empfehlung fuer die erste Implementierung

Minimal, aber wirklich nutzbar:

1. Service liest `transfer@xeisworks.at`.
2. Roter Button `UEBERWEISUNG OFFEN (n)`.
3. Dialog mit Fallliste, Thread, PDF-Anzeige.
4. Formular mit editierbaren Zahlungsfeldern.
5. QR-Erzeugung via `segno`.
6. `Spaeter - Alarm bleibt`.
7. `Ueberweisung durchgefuehrt` setzt Outlook-Follow-up auf `complete`.

OpenAI:

- sofort fuer Zusammenfassung und Fallback-Extraktion nutzen.
- aber nie ohne lokale Validierung.

Nicht in Phase 1 erzwingen:

- Outlook-Mail verschieben.
- Tesseract installieren.
- vollautomatische sevDesk-Eingangsbeleg-Zuordnung.
- Automatisches Bezahlen.
