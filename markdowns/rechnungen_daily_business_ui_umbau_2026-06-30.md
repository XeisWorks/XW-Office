# Umbau RECHNUNGEN / Tagesgeschäft UI – 2026-06-30

## Ziel

Das Untermenü `RECHNUNGEN` soll nach App-Start direkt geöffnet werden und die bisherige Tagesgeschäft-Bedienung kompakter werden:

- PySide6-App startet direkt in `RECHNUNGEN`, nicht im Start-Dashboard.
- Nur noch ein sichtbarer `START`-Button als geteilter Button:
  - Hauptklick: normaler `START`
  - Dropdown: `Selected`, `+ Notendruck`, `+ Notendruck Selected`
- Die eigene Überschrift `Tagesgeschäft` entfällt.
- Die Zeile oben enthält links die Alltagsaktionen:
  - `Aktualisieren`
  - `Entwurf`
  - `Custom-Label`
  - `START`
  - `STOP`
- Rechts werden rote Alert-Buttons nur eingeblendet, wenn wirklich offene Aufgaben vorhanden sind:
  - `OFFENE SENDUNGEN`
  - `ÜBERWEISUNGEN`
  - `MOLLIE AUTH`
- Nach Abschluss eines START-Laufs wird rechts unten im Rechnungen-Analysis-Panel eine strukturierte Zusammenfassung angezeigt. Initial bleibt der Bereich leer.

## Legacy-Vergleich

Legacy-App `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\ui\app.py`:

- hatte einen unteren Daily-Business-Bereich mit Aux-Panels:
  - `Offene Sendungen`
  - `Offene Überweisungen`
  - `Mollie - Authorized Orders`
  - weitere Kanäle wie Gutscheine/Rückerstattungen/Download-Links
- rote Hervorhebung erfolgte über Count > 0.
- `Offene Sendungen` und `Offene Überweisungen` nutzten mail-/Graph-basierte Panels.
- `Mollie Authorized Orders` nutzte einen direkten Mollie-Client und konnte Sendungen für remaining lines erstellen.

Neue PySide6-App:

- hat bereits `OffeneSendungenService` und `OffeneSendungenDialog`.
- hat bereits `DailyBusinessService` mit Queue-Kanälen `mollie`, `gutscheine`, `downloads`, `refunds`.
- hat eine generische `_QueueTabView` in `tagesgeschaeft_view.py`, die Queue-Zeilen aus `DailyBusinessService` anzeigen kann.
- echte Live-Mollie-Aktionen wie `create_shipment_for_remaining_lines` sind noch nicht als XW-Office-Service vorhanden.

## Umsetzung in Phasen

### Phase 1 – Startnavigation

`MainWindow` öffnet nach Aufbau und Signalverdrahtung direkt `ModuleKey.RECHNUNGEN`.

Wichtig:

- Home bleibt als Modul erhalten.
- Sidebar muss ebenfalls auf `Rechnungen` synchronisiert werden.

### Phase 2 – Toolbar-Konsolidierung

`RechnungenView` behält die vorhandenen Methoden für:

- erste Seite neu laden
- Rechnungsentwurf erstellen
- Custom-Label öffnen
- Sendungen/Mollie-Queue öffnen

Diese Funktionen werden über kleine öffentliche Wrapper von `TagesgeschaeftView` aus ausgelöst.

Die alte Toolbar innerhalb `RechnungenView` wird aus dem sichtbaren Layout entfernt, wenn sie vom übergeordneten Tagesgeschäft verwaltet wird.

### Phase 3 – START als Splitbutton

Ein `QToolButton` ersetzt die drei bisherigen START-Buttons:

- Button-Hauptfläche: `START`
- Dropdown:
  - `Selected`
  - `+ Notendruck`
  - `+ Notendruck Selected`

Die bestehende START-Logik bleibt unverändert, nur die UI-Auslöser ändern sich.

### Phase 4 – Bedingte rote Alert-Buttons

`TagesgeschaeftView._refresh_badges()` lädt:

- offene Rechnungen
- offene Sendungen
- Mollie-Queue
- Refund-/Überweisungsqueue

Sichtbarkeit:

- Count > 0 => Button sichtbar mit Count
- Count == 0 => Button versteckt

Button-Aktionen:

- `Sendungen`: öffnet `OffeneSendungenDialog`.
- `Mollie`: öffnet generischen Queue-Popupdialog für `mollie`.
- `Überweisungen`: öffnet generischen Queue-Popupdialog für `transfers`.

Der neue `transfers`-Kanal wird in `DailyBusinessService` separat geführt:

- gespeicherte Queue: `daily_business.queue.transfers`
- gespeicherte Count-Quelle: `daily_business.pending_counts.transfers`
- Live-Klassifikation aus Rechnungen über Hinweise wie `Überweisung`, `Ueberweisung`, `Vorkasse`, `Banktransfer`, `IBAN`, `EPC QR`, `offene Zahlung`.

### Phase 5 – START-Zusammenfassung im Analysis-Panel

Nach `_on_start_executed()` wird eine strukturierte Zusammenfassung an die eingebettete `RechnungenView` übergeben.

Inhalt:

- Modus
- Notendruck ja/nein
- verarbeitet / erfolgreich / Fehler
- Inventar-/Druckhinweise
- neu angelegte sevDesk-Produkte
- Laufstatus gestoppt/abgeschlossen

Anzeige:

- rechts unten im Detail-/Analysis-Panel
- nur nach START-Abschluss
- initial versteckt

### Phase 6 – Tests

Gezielte Tests:

- `TagesgeschaeftView` hat nur noch einen START-Splitbutton.
- Dropdown-Aktionen sind vorhanden.
- Alert-Buttons werden anhand Count ein-/ausgeblendet.
- `RechnungenView` kann externe Toolbar-Verwaltung aktivieren.
- relevante START-/Rechnungen-Tests bleiben grün.

## ENV / Konfiguration

Für die in dieser Phase umgesetzte UI reichen die vorhandenen Datenquellen.

Für echte Live-Funktionen:

- Offene Sendungen / Überweisungen per Microsoft Graph:
  - `MS_GRAPH_TENANT_ID`
  - `MS_GRAPH_CLIENT_ID`
  - `MS_GRAPH_MAILBOX`
  - optional App-/Device-Flow-Konfiguration je nach Graph-Setup
- AI-Zusammenfassung in offenen Sendungen:
  - `OPENAI_API_KEY`
- Mollie Live-Authorized-Orders / Settlement-/Payment-Abgleich:
  - `MOLLIE_ACCESS_TOKEN` oder `MOLLIE_OAUTH_TOKEN`
  - alternativ `MOLLIE_API_KEY`
- Stripe-Clearing:
  - `STRIPE_SECRET_KEY`

Hinweis: XW-Office kann aktuell Mollie-Clearing lesen und Queue-Zeilen anzeigen, aber das Legacy-Feature “Authorized Order versenden” ist noch kein vollwertiger PySide6-Service. Dafür wäre eine eigene Phase nötig.
