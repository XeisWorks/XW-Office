# OFFENE UEBERWEISUNGEN - Betriebsleitfaden

Stand: 2026-07-10

## Ziel

Die Funktion OFFENE UEBERWEISUNGEN verarbeitet offene Transfer-Mails aus dem dedizierten Postfach und fuehrt sie in DAILY BUSINESS als bearbeitbare Faelle mit QR-Generierung.

## Technischer Aufbau

- Datenquelle: Microsoft Graph Inbox fuer `MS_GRAPH_TRANSFER_MAILBOX`
- Primäre Offen-Logik: Message `flag.flagStatus != complete`
- UI-Einstieg: DAILY BUSINESS -> roter Button `UEBERWEISUNG OFFEN (n)`
- Dialog: Fallliste, Mail-/Thread-Detail, Zahlungsformular, QR-Erzeugung
- Persistenz: `daily_business.open_transfers.*` (DB), sonst lokaler Fallback in `state/open_transfers_state.json`

## Voraussetzungen

Folgende Secrets muessen gesetzt sein:

- `MS_GRAPH_TENANT_ID`
- `MS_GRAPH_CLIENT_ID`
- `MS_GRAPH_TRANSFER_MAILBOX` (empfohlen: `transfer@xeisworks.at`)
- optional `OPENAI_API_KEY` fuer bessere Zusammenfassung/Fallback-Extraktion

Empfohlene Rechte fuer Graph:

- `Mail.Read`
- `Mail.Read.Shared`
- `Mail.ReadWrite`
- `Mail.ReadWrite.Shared` (bei Shared Mailbox)

## Tagesablauf

1. DAILY BUSINESS oeffnen.
2. Bei offenen Faellen erscheint `UEBERWEISUNG OFFEN (n)`.
3. Button klicken -> Dialog oeffnet.
4. Fall waehlen, Zusammenfassung pruefen, Zahlungsfelder kontrollieren.
5. Falls noetig manuell korrigieren.
6. `QR-Code generieren` fuer Banking-App erzeugen.
7. Nach realer Zahlung `Ueberweisung durchgefuehrt` klicken.

Wichtig:

- `Spaeter - Alarm bleibt` schliesst nur den Dialog und erhoeht den Deferred-Zaehler.
- `Ueberweisung durchgefuehrt` setzt Outlook-Flag auf `complete`.
- Wenn Graph-PATCH fehlschlaegt, bleibt der Fall offen.

## QR-Extraktion und Prioritaet

Reihenfolge der Zahlungsdaten-Ermittlung:

1. Manuelle Werte (UI)
2. Bestehender EPC-QR im PDF (optional OpenCV/PyMuPDF)
3. PDF-Text (Regex/Validator)
4. Mail/Thread-Text
5. OpenAI-Fallback (wenn Key gesetzt)

Validierung vor QR-Erzeugung:

- Empfaenger Pflicht, max. 70 Zeichen
- IBAN Pflicht und gueltig
- BIC optional, falls gesetzt gueltig
- Betrag Pflicht, > 0
- Waehrung fix `EUR`
- Verwendungszweck max. 140 Zeichen

## Datei- und Datenorte

- QR-Ausgabe: `state/generated/transfer_qr/`
- Temporaere PDF-Anzeige: `state/tmp/`
- Hauptservice: `src/xw_studio/services/transfers/service.py`
- QR-Kern: `src/xw_studio/services/transfers/payment_qr.py`
- Dialog: `src/xw_studio/ui/modules/rechnungen/offene_ueberweisungen_dialog.py`

## Troubleshooting

### Button bleibt 0 trotz Mails

- Pruefen, ob `MS_GRAPH_TRANSFER_MAILBOX` korrekt gesetzt ist.
- Pruefen, ob die Mails in diesem Postfach wirklich in Inbox liegen.
- Pruefen, ob Mails in Outlook bereits als erledigt markiert sind (`flagStatus=complete`).

### Badge-Refresh fordert Login nicht an

Das ist gewollt: Silent-Refresh startet keinen Device-Flow. Ohne Silent-Token wird Cache verwendet.

### `Ueberweisung durchgefuehrt` wirkt nicht

- Graph-Rechte auf `Mail.ReadWrite` / `Mail.ReadWrite.Shared` pruefen.
- Bei Shared Mailbox Delegationsrechte im Tenant pruefen.

### QR kann nicht erzeugt werden

- Pflichtfelder im Formular pruefen (Empfaenger, IBAN, Betrag).
- Bei ungueltiger IBAN/BIC wird absichtlich blockiert.

### PDF hat QR, aber nichts wird erkannt

- OpenCV/PyMuPDF sind optional. Ohne diese Libraries bleibt nur Text-/AI-Extraktion.
- Falls installiert, pruefen ob QR in den ersten 2 Seiten erkennbar ist.

## Betriebsempfehlung

- Transfer-Postfach dediziert halten (keine gemischten Themen).
- Faelle zeitnah mit Outlook-Complete abschliessen, damit Count sauber bleibt.
- Bei wiederkehrenden Rechnungsformaten manuelle Korrekturen als Referenz verwenden.
