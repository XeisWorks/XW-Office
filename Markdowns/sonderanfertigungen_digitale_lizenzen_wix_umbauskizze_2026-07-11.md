# Umbau-Skizze: Sonderanfertigungen, digitale Musiknoten-Lizenzen und Wix Payment Links

Stand: 11.07.2026  
Betroffene Projekte:

- `C:\Users\bernh\GitHub\XW-Studio`
- `C:\Users\bernh\GitHub\XW-Website_v2`
- Legacy-Referenz: `C:\Users\bernh\GitHub\sevDesk`

## 1. Zielbild

XW-Studio erhält einen zentralen Workflow für individuell bepreiste Aufträge und digitale Sonderlieferungen, ohne für jeden Auftrag ein dauerhaftes Wix-Produkt anlegen zu müssen.

Es gibt drei explizite Auftragsarten:

1. **Physische Sonderanfertigung**
2. **Digitale Sonderanfertigung**
3. **Bestehende Musiknote als digitale Sonderlieferung**

XW-Studio erzeugt einen einmal verwendbaren Wix Payment Link, öffnet danach einen vollständig bearbeitbaren englischen Outlook-Classic-Mailentwurf und überlässt das endgültige Absenden dem Benutzer.

Nach erfolgreicher Zahlung erscheinen digital auszuliefernde Bestellungen im Rechnungs-Untermenü als Alarm **DIGITALE LIZENZEN OFFEN**. Dort wird pro bestelltem Musiknotenprodukt die hinterlegte Druck-PDF gefunden, mit dem Kundennamen lizenziert, im festgelegten Lizenzordner gespeichert und einem englischen Outlook-Entwurf angehängt.

Der bestehende externe Wix-sevDesk-Mechanismus erstellt weiterhin den sevDesk-Rechnungsentwurf. XW-Studio erzeugt keinen zweiten Entwurf.

## 2. Verbindliche fachliche Entscheidungen

### 2.1 Checkout und Bezahlung

- Jeder erzeugte Link gehört zu genau einem Auftrag.
- Der Link darf genau einmal erfolgreich bezahlt werden.
- Es wird immer der vollständige Betrag online bezahlt.
- Sonderaufträge werden nicht mit normalen Warenkorbprodukten vermischt.
- Eine vollständige echte Rechnungsadresse ist Pflicht.
- Die Mail wird nicht automatisch versendet; XW-Studio öffnet Outlook Classic mit einem bearbeitbaren Entwurf.
- Änderungen an Betrag oder Leistung erzeugen einen neuen Payment Link; der alte Link wird deaktiviert.

### 2.2 Preis

- Der eingegebene bzw. aus dem Produkt übernommene Endpreis bleibt der zu bezahlende Endpreis.
- Beispiel: Ein in Wix mit 24 EUR geführtes Produkt kostet den US-Kunden ebenfalls 24 EUR.
- Bei einer digitalen Drittlandleistung enthält dieser Endpreis 0 EUR österreichische Umsatzsteuer; der Preis wird nicht um eine zuvor enthaltene Umsatzsteuer reduziert.
- `Digital Delivery Handling` wird bei Auftragsart 3 genau einmal je Auftrag ergänzt, unabhängig von der Zahl der Musiknotenprodukte.
- Der Preis von `Digital Delivery Handling` wird aus dem bestehenden Wix-Katalogprodukt gelesen und nicht im Dialog frei verändert.

### 2.3 Lagerbestand

**Harte Invariante:** Ein digitaler Sonderverkauf darf den Wix-Lagerbestand eines physischen Musiknotenprodukts nicht verändern.

Ebenso darf er nicht:

- als physischer Druckauftrag gelten,
- ein Versandlabel anfordern,
- eine Versandmethode verlangen,
- den normalen physischen Fulfillment-Flow starten.

### 2.4 Digitale Lizenzierung

- Ein Musiknotenprodukt besitzt genau eine auszuliefernde PDF.
- Quelle ist immer `print_file_path` des bestehenden Produktkatalogs.
- Fehlt der Druckpfad, muss der Benutzer im Lizenzdialog per Dateiauswahl eine PDF zuordnen.
- Die neu gewählte Datei wird nach Bestätigung dauerhaft als Druckpfad des Produkts gespeichert.
- Wasserzeichenname ist immer `Vorname Nachname`; Firma wird ignoriert.
- Ausgabeordner ist standardmäßig:

  `C:\Users\bernh\OneDrive - XeisWorks\02 XeisWorks\24 Digitale Lizensierung`

- Dateiname basiert auf dem Legacy-Verhalten und erhält bei Kollisionen automatisch `(2)`, `(3)` usw.
- Bereits vorhandene Dateien werden niemals still überschrieben.
- Der Alarm verschwindet erst nach explizitem **Versand als erledigt markieren**.
- Nach diesem Abschluss wird die Wix-Bestellung als ausgeführt/fulfilled markiert.

## 3. Abgrenzung zum bisherigen Legacy-Flow

Die Seite `Digitale Noten.cs5n0.js` sucht derzeit physische Produkte, legt das ausgewählte Produkt und `Digital Delivery Handling` in den normalen Warenkorb und wendet den Coupon `SHEETMUSICDIGITAL` an. Kunden aus nicht belieferten Ländern müssen dadurch ein beliebiges verfügbares Land wählen.

Dieser Ablauf wird für neue Sonderlieferungen ersetzt, weil er fachlich falsche Daten erzeugt:

- falsches Rechnungs- oder Lieferland,
- physisches Produkt in einem tatsächlich digitalen Auftrag,
- künstliche Versandkostenkorrektur per Coupon,
- unzuverlässige Steuerzuordnung,
- keine saubere digitale Auslieferungswarteschlange.

Der neue Flow verwendet keinen Versandcoupon. Digitale Positionen sind nicht versandpflichtig; daher entstehen keine Versandkosten.

Die bestehende öffentliche Seite kann nach erfolgreichem Rollout deaktiviert oder auf einen Anfragehinweis umgestellt werden. Sie soll nicht sofort entfernt werden, bevor der neue End-to-End-Flow produktiv verifiziert wurde.

## 4. Gesamtarchitektur

```text
XW-Studio: Auftrag anlegen
        |
        | HTTPS, authentisiert, idempotenter Client-Request-Key
        v
XW-Website_v2 Backend
        |
        | Wix Payment Links API
        v
persönlicher Wix Checkout-Link
        |
        | Kunde bezahlt im Wix Checkout
        v
Wix eCommerce Order + Payment Status
        |                         |
        | bestehende Integration | Wix Orders API
        v                         v
sevDesk-Entwurf             XW-Studio Poll/Cache
                                  |
                                  v
                       DIGITALE LIZENZEN OFFEN
                                  |
                     Lizenzieren & Mail vorbereiten
                                  |
           Druckpfad -> Wasserzeichen -> Lizenzordner
                                  |
                                  v
                     Outlook-Classic-Entwurf
                                  |
                      manuell senden + erledigen
                                  |
                                  v
                   lokaler Audit + Wix Fulfillment
```

## 5. Auftragsarten und Wix-Positionen

### 5.1 Physische Sonderanfertigung

Eingaben:

- Empfänger-E-Mail
- Vorname
- Nachname
- Titel
- ausführliche Beschreibung
- Menge, standardmäßig 1
- fixer Endpreis
- optionale interne Notiz
- Ablaufdatum
- Wix-Steuergruppe bzw. fachlich geeignete Steuerklasse

Wix-Payload:

- Payment-Link-Typ `ECOM`
- eine `CUSTOM` Line Item
- `physicalProperties.shippable = true`
- `paymentsLimit = 1`
- Währung `EUR`
- Ablaufdatum

Konsequenzen:

- Wix verlangt eine zulässige Lieferadresse und Versandmethode.
- Nur in Wix aktivierte Versandländer sind auswählbar.
- Wix berechnet Steuer und Versand nach den vorhandenen Einstellungen.
- In sevDesk muss die Position als freie Rechnungsposition ankommen; es wird kein dauerhafter Produktartikel vorausgesetzt.

### 5.2 Digitale Sonderanfertigung

Eingaben wie bei der physischen Sonderanfertigung, jedoch ohne Versand.

Wix-Payload:

- Payment-Link-Typ `ECOM`
- eine `CUSTOM` Line Item
- `physicalProperties.shippable = false`
- `paymentsLimit = 1`
- tatsächliche Rechnungsadresse bleibt Pflicht

Konsequenzen:

- keine Versandzone und keine Versandmethode erforderlich,
- auch Kunden aus nicht belieferten Drittländern können ihre echte Rechnungsadresse verwenden,
- keine automatische PDF-Lizenzierung, sofern keine bestehende Produkt-SKU/Datei zugeordnet wurde,
- sevDesk erhält eine freie Rechnungsposition.

Die konkrete digitale Auslieferung einer freien Sonderanfertigung ist zunächst außerhalb des Musiknoten-Lizenzalarms, außer der Auftrag wird explizit mit einer fertigen PDF-Datei versehen. Diese optionale Erweiterung ist Phase 2.

### 5.3 Bestehende Musiknote als digitale Sonderlieferung

Eingaben:

- Empfänger-E-Mail
- Vorname
- Nachname
- ein oder mehrere vorhandene Wix-Produkte
- Menge je Produkt, standardmäßig 1
- automatisch übernommener fixer Endpreis je Produkt
- automatisch einmal `Digital Delivery Handling`
- Ablaufdatum

Der Dialog durchsucht den Wix-Katalog. Angezeigt werden mindestens:

- Name
- SKU
- Preis
- Produktbild
- Wix-Produkt-ID
- vorhandener XW-Studio-Druckpfad
- sevDesk-Artikelstatus, soweit lokal verfügbar

## 6. Entscheidung zur lagerneutralen Wix-Abbildung

Die Payment Links API unterstützt sowohl Katalogpositionen mit überschriebenen physischen Eigenschaften als auch Custom Line Items mit eigener SKU. Vor dem produktiven Rollout ist ein kleiner Live-Spike zwingend.

### 6.1 Variante A: Katalogposition mit `shippable = false`

Vorteile:

- Wix-Katalogreferenz bleibt erhalten.
- SKU und Produktidentität bleiben nativ erhalten.
- bestehende Wix-sevDesk-Zuordnung hat die höchste Chance, den vorhandenen sevDesk-Artikel direkt zu verknüpfen.

Risiko:

- Wix könnte bei einer bezahlten Katalogposition trotzdem den Lagerbestand reduzieren.

### 6.2 Variante B: Custom Line Item mit Ursprungs-SKU

Payload je Musiknote:

- `type = CUSTOM`
- Name aus dem Wix-Produkt
- Endpreis aus dem Wix-Produkt
- Beschreibung mit Kennzeichnung `Digital licensed delivery`
- `physicalProperties.sku = <bestehende SKU>`
- `physicalProperties.shippable = false`
- Bild aus dem Wix-Produkt
- geeignete Wix-Steuergruppe

Vorteile:

- kein Katalog-Bestandsabgang,
- keine physische Versandsemantik,
- SKU bleibt in der Orderposition erhalten.

Risiko:

- die externe Wix-sevDesk-Integration könnte die Position trotz SKU als freie Position statt als vorhandenen Artikel anlegen.

### 6.3 Verbindlicher Auswahlalgorithmus

1. Mit einem Testprodukt und Testbestand einen Katalog-Payment-Link mit `catalogOverrideFields.physicalProperties.shippable = false` erzeugen.
2. Vollständig bezahlen.
3. Vorher-/Nachher-Bestand über Wix API vergleichen.
4. sevDesk-Entwurf auf Artikelverknüpfung prüfen.
5. Falls der Bestand unverändert bleibt: Variante A verwenden.
6. Falls der Bestand sinkt: Variante B verwenden.
7. Falls Variante B den sevDesk-Artikel nicht verknüpft: XW-Studio repariert ausschließlich die Artikelreferenz im bereits automatisch erzeugten sevDesk-Entwurf anhand der SKU. Es erzeugt keinen neuen Entwurf und verändert weder Preis noch Steuer noch Beschreibung.

Ein automatisches nachträgliches Zurückbuchen von Wix-Bestand ist nicht die bevorzugte Lösung. Das wäre fehleranfällig bei Parallelbestellungen, Stornos und Retries.

### 6.4 `Digital Delivery Handling`

Auch dieses Produkt wird genau einmal pro Auftrag eingebracht.

- Wenn Katalogpositionen lagerneutral funktionieren: echte Katalogreferenz, `shippable = false`.
- Andernfalls: Custom Line Item mit SKU und Preis des Handling-Produkts.
- Es darf keine physische Fulfillment-Menge erzeugen.
- Das Handling-Produkt wird niemals als zu lizenzierende PDF-Position behandelt.

Die stabile Identifikation erfolgt primär über die Wix-Produkt-ID und zusätzlich über eine konfigurierte SKU. Der Name allein ist kein belastbarer Schlüssel.

## 7. Steuerlogik

### 7.1 Grundsatz

Steuer wird nicht allein aus dem Land abgeleitet, sondern aus:

- Auftragsart,
- tatsächlicher Leistungsart,
- Rechnungsland,
- vorhandener Wix-Steuerkonfiguration,
- Steuerdaten der erzeugten Wix-Order.

### 7.2 Physische Sonderanfertigung

- Inland/EU bzw. aktiviertes Versandland: Wix berechnet nach vorhandener Konfiguration.
- Tatsächliche Ausfuhr einer Ware in ein Drittland: steuerfreie Ausfuhrlieferung nur bei tatsächlicher Versendung und erforderlichem Ausfuhrnachweis.
- Nicht aktivierte Versandländer werden für physische Aufträge nicht künstlich freigeschaltet.

### 7.3 Digitale Lieferung

- Rechnungsadresse ist Pflicht und Steuergrundlage.
- EU-B2C: Wix-Zielland-Steuer gemäß vorhandener Wix-Konfiguration; Werte der finalen Wix-Order werden in sevDesk gespiegelt.
- Drittland-B2C: fixer Endpreis, österreichische Umsatzsteuer 0.
- Drittland-digital ist keine Ausfuhrlieferung nach § 7 UStG.
- In sevDesk ist grundsätzlich die Regel **Nicht im Inland steuerbare Leistung** zu verwenden, im aktuellen sevDesk-Steuermodell `taxRule.id = 17`, Positionssteuersatz 0.
- Physische Ausfuhr wäre dagegen `taxRule.id = 2`.

### 7.4 sevDesk-Entwurf

Der bestehende Wix-sevDesk-Prozess bleibt Eigentümer der Entwurfserstellung. XW-Studio darf danach nur gezielt korrigieren, wenn der automatisch erzeugte Entwurf die fachlich falsche Steuerregel oder eine fehlende Artikelverknüpfung besitzt.

Korrekturen müssen idempotent sein und vor dem Schreiben prüfen:

- Wix-Order-ID/Bestellnummer stimmt,
- Entwurfstatus ist weiterhin `100`,
- Rechnung ist noch nicht finalisiert,
- erwartete Positionen und Beträge stimmen,
- keine manuelle Bearbeitung würde überschrieben.

Bei Abweichungen wird kein stiller Patch durchgeführt. Der Fall erhält im Alarmdialog den Status **sevDesk-Prüfung erforderlich**.

## 8. XW-Studio: neues Modul „Sonderauftrag“

### 8.1 Platzierung

Empfohlen wird ein neuer Haupt- oder Schnellzugriff **Sonderauftrag**. Alternativ kann er in Produkte liegen; fachlich ist er jedoch ein Verkaufsvorgang und kein Produktpflegevorgang.

Der Dialog besitzt oben drei große Auswahlkarten:

- Physische Sonderanfertigung
- Digitale Sonderanfertigung
- Musiknote digital lizenzieren

### 8.2 Gemeinsame Felder

- Vorname, Pflicht
- Nachname, Pflicht
- E-Mail, Pflicht und syntaktisch validiert
- Sprache der Link-Mail: zunächst Englisch
- Ablaufdatum, Standard 14 Tage
- interne Auftragsreferenz, automatisch `SA-YYYY-NNNN`
- interne Notiz

### 8.3 Freie Sonderanfertigung

- Titel, Pflicht
- Beschreibung, Pflicht, mehrzeilig
- Menge
- fixer Endpreis
- physisch/digital aus Auftragsart
- Preisvorschau
- voraussichtliche Steueranzeige mit Hinweis, dass Wix final anhand der Rechnungs-/Lieferadresse berechnet

### 8.4 Musiknoten-Auswahl

- Suchfeld mit verzögerter Wix-Katalogsuche
- Ergebnisliste mit Mehrfachauswahl
- Warenkorbartige Auswahl rechts
- je Produkt Name, SKU, Bild, Preis, Menge und Druckpfadstatus
- `Digital Delivery Handling` automatisch als eigene Zeile, nicht entfernbar
- Gesamtsumme

### 8.5 Aktionen

- **Preview**: zeigt den vollständigen Payment-Link-Payload ohne Mutation.
- **Create payment link**: erzeugt den Link einmalig.
- **Open Outlook draft**: nach erfolgreicher Erstellung automatisch; zusätzlich wiederholbar.
- **Copy link**: kopiert die URL.
- **Deactivate link**: deaktiviert einen noch unbezahlten Link.
- **Create replacement**: deaktiviert den alten Link und erzeugt nach Bestätigung einen neuen.

### 8.6 Idempotenz

Ein Doppelklick oder Timeout darf nicht mehrere Links erzeugen.

- XW-Studio generiert vor dem Request eine UUID `client_request_id`.
- Das Website-Backend persistiert Request-ID und resultierende Wix-Payment-Link-ID.
- Wiederholte Requests mit gleicher ID geben denselben Link zurück.
- Nach unklarem Timeout fragt XW-Studio zuerst den Requeststatus ab.

## 9. XW-Website_v2: Backend

### 9.1 Neue Backend-Datei

Vorschlag:

- `src/backend/specialOrders.web.js`

Öffentliche Site-Member-Berechtigungen sind für diesen administrativen Workflow ungeeignet. Der Endpoint muss durch ein starkes Shared-Secret/HMAC-Verfahren oder einen Wix-kompatiblen administrativen API-Zugang geschützt werden.

### 9.2 Backend-Aufgaben

- Request authentisieren.
- Payload streng validieren.
- Preise bei Katalogprodukten serverseitig erneut aus Wix lesen.
- `Digital Delivery Handling` serverseitig über konfigurierte Produkt-ID ergänzen.
- Client darf weder Handling-Preis noch Produkt-ID frei einschleusen.
- Payment Link über elevated Wix-Berechtigung erzeugen.
- `paymentsLimit = 1` setzen.
- Ablaufdatum setzen.
- interne Referenz und Modus als Note/Tags/Extended Fields speichern.
- URL, Link-ID und normalisierte Positionen zurückgeben.

### 9.3 Konfiguration

Keine fachlichen IDs hart im Seiten-Code verteilen. Benötigt werden zentrale Einstellungen für:

- `DIGITAL_DELIVERY_HANDLING_PRODUCT_ID`
- erwartete Handling-SKU
- Payment-Link-Ablaufdauer
- erlaubte Währung `EUR`
- API-HMAC-Secret im Wix Secrets Manager
- optional erlaubte XW-Studio-Client-ID

### 9.4 Sicherheitsregeln

- Secrets niemals in Frontend/Page-Code.
- Zeitstempel und Nonce gegen Replay-Angriffe.
- HMAC über kanonischen Requestbody.
- maximale Beschreibungslänge, Mengen und Beträge serverseitig begrenzen.
- nur Produkte aus dem eigenen Wix-Store akzeptieren.
- Logging ohne vollständige personenbezogene Daten und ohne Secrets.
- Audit enthält Request-ID, Modus, Produkt-IDs, Betrag, Link-ID, Zeitpunkt und Ergebnis.

## 10. Lokales Datenmodell in XW-Studio

Vorschlag für neue Tabellen oder äquivalente persistente Modelle.

### 10.1 `special_order`

```text
id                         UUID / PK
client_request_id          UUID / UNIQUE
internal_reference         TEXT / UNIQUE
mode                       physical_custom | digital_custom | digital_catalog
customer_first_name        TEXT
customer_last_name         TEXT
customer_email             TEXT
currency                   TEXT
total_amount               DECIMAL
wix_payment_link_id        TEXT / UNIQUE nullable
wix_payment_link_url       TEXT nullable
wix_payment_link_status    TEXT
wix_order_id               TEXT nullable
wix_order_number           TEXT nullable
created_at                 TIMESTAMP
expires_at                 TIMESTAMP nullable
paid_at                    TIMESTAMP nullable
deactivated_at             TIMESTAMP nullable
last_sync_at               TIMESTAMP nullable
last_error                 TEXT
```

### 10.2 `special_order_item`

```text
id                         UUID / PK
special_order_id           FK
line_no                    INTEGER
kind                       custom | catalog | handling
wix_product_id             TEXT nullable
catalog_app_id             TEXT nullable
sku                        TEXT nullable
name                       TEXT
description                TEXT
quantity                   INTEGER
unit_amount                DECIMAL
shippable                  BOOLEAN
source_print_file_path     TEXT nullable
```

### 10.3 `digital_license_case`

```text
id                         UUID / PK
wix_order_id               TEXT / UNIQUE
wix_order_number           TEXT
customer_first_name        TEXT
customer_last_name         TEXT
customer_email             TEXT
payment_status             TEXT
case_status                waiting | ready | partial | draft_opened | sent | error
detected_at                TIMESTAMP
prepared_at                TIMESTAMP nullable
outlook_draft_opened_at    TIMESTAMP nullable
completed_at               TIMESTAMP nullable
wix_fulfilled_at           TIMESTAMP nullable
completed_note             TEXT
last_error                 TEXT
```

### 10.4 `digital_license_file`

```text
id                         UUID / PK
case_id                    FK
wix_line_item_id           TEXT
wix_product_id             TEXT nullable
sku                        TEXT
product_name               TEXT
source_path                TEXT
output_path                TEXT nullable
source_sha256              TEXT nullable
output_sha256              TEXT nullable
watermark_name             TEXT
status                     pending | created | attached | error
created_at                 TIMESTAMP nullable
last_error                 TEXT
```

Unique Constraints verhindern doppelte Fälle und Dateien nach Refresh/Retry.

## 11. Erkennung „DIGITALE LIZENZEN OFFEN“

### 11.1 Quelle

Die Warteschlange wird aus Wix Orders aufgebaut und lokal gecacht. Ein Order-Fall ist relevant, wenn:

- `paymentStatus` vollständig bezahlt/approved ist,
- die Order das konfigurierte Handling-Produkt bzw. dessen Marker enthält,
- mindestens eine weitere Musiknotenposition vorhanden ist,
- der lokale Fall noch nicht abgeschlossen ist.

Der Produktname allein reicht nicht zur Erkennung. Reihenfolge:

1. Wix-Produkt-ID
2. SKU
3. explizites Special-Order-Tag/Extended Field
4. Name nur als diagnostischer Legacy-Fallback

### 11.2 Kein Alarm bei

- unbezahlter Order,
- fehlgeschlagener oder stornierter Zahlung,
- abgelaufenem Payment Link ohne Order,
- vollständig abgeschlossenem lokalen Lizenzfall,
- reiner freier digitaler Sonderanfertigung ohne zugeordnetes Musiknotenprodukt,
- normalem physischen Auftrag.

### 11.3 Polling

- in den vorhandenen 60-Sekunden-Badge-Refresh integrieren,
- API-lastige Vollsynchronisation mit eigenem TTL, z. B. 5 Minuten,
- beim Öffnen des Dialogs expliziter Refresh,
- lokale Ergebnisse während des Refresh sichtbar lassen,
- Wix-Order-Cache wiederverwenden,
- keine doppelte Orderabfrage aus verschiedenen Views.

## 12. Alarm-Button und Dialog

### 12.1 Button

Beschriftung:

```text
DIGITALE LIZENZEN OFFEN (3)
```

Der Button verwendet das bestehende rote Alarmdesign neben `OFFENE SENDUNGEN`, `UEBERWEISUNG OFFEN` und `MOLLIE AUTH`.

### 12.2 Dialogaufbau

Linke Tabelle:

- Wix-Bestellung
- bezahlt am
- Kunde
- Produkte
- Dateienstatus
- Mailstatus
- sevDesk-Status
- letzter Fehler

Rechter Detailbereich:

- tatsächliche Rechnungsadresse
- Vorname/Nachname und daraus gebildeter Wasserzeichenname
- E-Mail
- Bestellpositionen und Preise
- Liste der Musiknoten-PDFs
- sichtbarer Quell- und Zielpfad je Produkt
- Warnungen
- Audit-Timeline

### 12.3 Aktionen

- **Refresh**
- **Quell-PDF auswählen** bei fehlendem oder ungültigem Druckpfad
- **Lizenzieren & Mail vorbereiten**
- **Outlook-Entwurf erneut öffnen**
- **Zielordner öffnen**
- **Versand als erledigt markieren**
- **Später – Alarm bleibt**
- optional **Fehlernotiz**

## 13. PDF-Quellpfad

### 13.1 Auflösung

Für jede zu lizenzierende SKU:

1. Produkt aus `ProductCatalogService` laden.
2. `print_file_path` über die bestehende Shared-Path-Auflösung normalisieren.
3. Prüfen: vorhanden, reguläre Datei, Suffix `.pdf`, lesbar.
4. Bei Erfolg in der Vorschau anzeigen.
5. Bei Fehlen Dateiauswahldialog öffnen.

### 13.2 Fehlender Pfad

Popup-Text:

```text
Für „{Produktname}“ ({SKU}) ist noch keine Druck-PDF hinterlegt.
Bitte wählen Sie die auszuliefernde PDF aus.
```

Nach Auswahl zeigt ein Bestätigungsdialog:

- SKU und Produktname
- gewählte Datei
- Option standardmäßig aktiv: `Als Druckpfad des Produkts speichern`

Ohne gültige Datei bleibt der Fall offen; die übrigen Produkte dürfen optional bereits vorbereitet werden, der Mailentwurf wird aber erst geöffnet, wenn alle erforderlichen Dateien erfolgreich erzeugt wurden.

## 14. Zentraler PDF-Lizenzierungsservice

### 14.1 Neue Service-Datei

Vorschlag:

- `src/xw_studio/services/layout/pdf_licensing.py`

Der Service wird sowohl vom Layout-Register als auch vom Alarmdialog benutzt.

### 14.2 Übernommenes Legacy-Verhalten

Quelle:

- `C:\Users\bernh\GitHub\sevDesk\sevdesk_wix_fulfillment\notes_layout\watermark_side_a4.py`

Verhalten:

- PyMuPDF/`fitz`
- Wasserzeichen auf jeder Seite links 90 Grad und rechts 270 Grad
- Standardtext:

  `Licensed Copy for {user_name} - Redistribution Prohibited`

- Helvetica, 12 pt
- Seitenrand 6 mm
- Opazität 0,5
- Quelldatei niemals verändern

### 14.3 Dateinamen

Basislogik:

- Enthält der Quellname ` GESAMT`, wird dieses Token durch ` - Vorname Nachname` ersetzt.
- Andernfalls wird ` - Vorname Nachname` vor `.pdf` angefügt.

Beispiel:

```text
Riserva GESAMT.pdf
-> Riserva - Jane Doe.pdf
```

Kollisionen:

```text
Riserva - Jane Doe.pdf
Riserva - Jane Doe (2).pdf
Riserva - Jane Doe (3).pdf
```

Die nächste freie Nummer wird atomar reserviert. Ein paralleler Worker darf nicht denselben Zielnamen wählen.

### 14.4 Dateisicherheit

- Ausgabe zunächst in temporäre Datei im Zielordner schreiben.
- PDF nach dem Schreiben erneut öffnen.
- Seitenanzahl muss der Quelle entsprechen.
- Wasserzeichentext muss mindestens auf der ersten und letzten Seite extrahierbar sein.
- Erst danach atomar auf finalen Namen umbenennen.
- Bei Fehler temporäre Datei entfernen, Quelle unverändert lassen und Alarm offen halten.
- SHA-256 von Quelle und Ausgabe im Audit speichern.

## 15. Neues Layout-Register „PDF-Lizenzierung“

Einbau in:

- `src/xw_studio/ui/modules/layout/view.py`

Empfohlene Position: direkt nach `A5 -> A4`.

Felder:

- Quell-PDF
- Wasserzeichenname `Vorname Nachname`
- Zielordner, Standard Lizenzordner
- nicht editierbare Vorschau des Wasserzeichentexts
- optional erweiterte Einstellungen für Schriftgröße, Rand und Opazität; standardmäßig eingeklappt

Aktionen:

- **PDF auswählen**
- **Lizenzierte PDF erstellen**
- **Ausgabeordner öffnen**

Das Register ist ein manuelles Werkzeug und verändert keine Orders, Produktpfade oder Alarmfälle.

## 16. Outlook-Classic-Entwurf

### 16.1 Erweiterung des bestehenden Composers

Bestehende Datei:

- `src/xw_studio/services/mailing/outlook_compose.py`

Neue Parameter:

```python
compose_outlook_mail(
    to_email: str,
    subject: str,
    sender_smtp: str,
    html_body: str = "",
    attachments: list[str] | None = None,
)
```

Anforderungen:

- weiterhin in isoliertem Subprozess ausführen,
- Outlook-Signatur erhalten,
- HTML-Body oberhalb der Signatur einsetzen,
- alle Anhänge vor `Display(False)` hinzufügen,
- Dateiexistenz und maximale Gesamtgröße vor COM-Aufruf prüfen,
- Entwurf anzeigen, niemals `Send()` aufrufen,
- sichtbares Absenderkonto nach `Display` erneut setzen.

### 16.2 Englischer Betreff

```text
Your licensed sheet music – {product_summary}
```

Bei mehreren Produkten:

```text
Your licensed sheet music – Wix order {order_number}
```

### 16.3 Englische Mailvorlage

```html
<p>Dear {first_name} {last_name},</p>

<p>Thank you very much for your order.</p>

<p>Please find your personally licensed sheet music attached:</p>

{product_list_html}

<p>The attached files are licensed exclusively to {first_name} {last_name}.
They may not be redistributed, forwarded, uploaded, copied for third parties,
or made publicly available.</p>

<p>Wix order: {order_number}</p>

<p>Kind regards,<br>
XeisWorks<br>
Mag. Bernhard Holl<br>
Johnsbach 92<br>
8912 Admont<br>
Austria<br>
office@xeisworks.at<br>
www.xeisworks.at</p>
```

Der Entwurf bleibt vollständig veränderbar.

### 16.4 Payment-Link-Mail

Auch die Mail beim Anlegen des Sonderauftrags wird auf Englisch vorbereitet.

Betreff:

```text
Your personal payment link – {order_title}
```

Inhalt:

```html
<p>Dear {first_name} {last_name},</p>

<p>Thank you for your enquiry.</p>

<p>You can review and pay for your individual order using the secure link below:</p>

<p><a href="{payment_link_url}">Open secure checkout</a></p>

<p>Order: {order_title}<br>
Total amount: {total_amount} EUR<br>
Payment link valid until: {expiration_date}</p>

<p>Kind regards,<br>...</p>
```

## 17. Erledigt- und Fulfillment-Logik

### 17.1 Warum nicht automatisch nach Öffnen des Entwurfs erledigen

Ein geöffneter Outlook-Entwurf beweist nicht, dass die Mail versendet wurde. Deshalb:

- `prepared_at`: PDFs erfolgreich erzeugt
- `outlook_draft_opened_at`: Entwurf erfolgreich geöffnet
- `completed_at`: Benutzer bestätigt Versand manuell

### 17.2 Manuelle Bestätigung

Button **Versand als erledigt markieren** zeigt:

```text
Wurden die lizenzierte(n) PDF-Datei(en) geprüft und die E-Mail tatsächlich versendet?

Danach wird der Fall lokal abgeschlossen und die Wix-Bestellung als ausgeführt markiert.
```

Nur bei Bestätigung:

1. lokalen Auditstatus schreiben,
2. Wix-Fulfillment für die digitalen Musiknotenpositionen erzeugen bzw. Order als fulfilled markieren,
3. Ergebnis erneut von Wix lesen,
4. Alarm erst bei erfolgreichem lokalen Abschluss ausblenden.

Falls Wix-Fulfillment fehlschlägt:

- lokaler Mailversand bleibt dokumentiert,
- Fallstatus `sent_fulfillment_pending`,
- Alarm bleibt sichtbar mit Aktion **Wix-Ausführung erneut bestätigen**,
- kein zweiter Mailentwurf wird automatisch geöffnet.

### 17.3 Fulfillment-Positionen

- `Digital Delivery Handling` wird nicht als physische Versandposition behandelt.
- Bei Custom-Items muss geprüft werden, ob Wix Fulfillment-APIs diese Positionen akzeptieren.
- Falls Wix bei vollständig nicht versandpflichtigen Orders automatisch fulfilled setzt, wird kein redundantes Fulfillment erzeugt; der gelesene Status wird nur auditiert.

## 18. sevDesk-Nachprüfung

Da der sevDesk-Entwurf bereits automatisch entsteht, benötigt der Lizenzfall lediglich eine read/repair-Prüfung.

Prüfungen:

- Entwurf mit Wix-Bestellnummer vorhanden?
- vorhandene Musiknotenposition mit richtigem sevDesk-Part verbunden?
- `Digital Delivery Handling` korrekt vorhanden?
- Endpreise entsprechen der Wix-Order?
- Steuerregel entspricht Leistungsart und Rechnungsland?

Bei fehlender Part-Verknüpfung:

- SKU aus Wix-Line-Item verwenden,
- bestehenden sevDesk-Part suchen,
- nur `part` und gegebenenfalls `unity` an der bestehenden Position ergänzen,
- Name, Text, Preis, Menge und Steuer nicht überschreiben.

Bei falscher Steuerregel:

- nicht automatisch korrigieren, solange die genaue Factory-Payload für das produktive sevDesk-Konto nicht durch einen Testentwurf verifiziert wurde,
- Dialog zeigt Soll/Ist und bietet später eine explizite Reparaturaktion,
- Phase-1-Go-Live darf bei Drittland-digital erst erfolgen, wenn ein Testentwurf korrekt `taxRule 17` enthält.

## 19. Fehlerfälle

### 19.1 Payment Link

- Backend nicht erreichbar: lokaler Entwurf bleibt unveröffentlicht, Retry möglich.
- unbekannter Timeout: Status über `client_request_id` abfragen, keinen neuen Link blind erzeugen.
- Wix lehnt Steuergruppe ab: Link nicht erzeugt, verständliche Fehlermeldung.
- Handling-Produkt fehlt oder ist inaktiv: Vorgang blockieren.

### 19.2 Bestellung

- Order noch nicht bezahlt: kein Lizenzalarm.
- Zahlung später storniert/refunded: abgeschlossene Lieferung nicht automatisch löschen; separater Prüfhinweis.
- Orderposition ohne SKU: Fall blockiert mit manueller Zuordnung.
- mehrere Handling-Positionen: Warnung und keine automatische Freigabe.

### 19.3 PDF

- Druckpfad fehlt: Dateiauswahl.
- Pfad ungültig: Dateiauswahl und dauerhafte Reparatur anbieten.
- PDF passwortgeschützt oder beschädigt: keine Ausgabe, Alarm bleibt.
- Zieldatei existiert: nächster Suffix, kein Überschreiben.
- OneDrive nicht verfügbar: verständlicher Fehler, optional alternativen Zielordner wählen; Standardpfad nicht still ändern.

### 19.4 Outlook

- Outlook-Konto fehlt: PDFs bleiben vorbereitet, Alarm bleibt.
- COM hängt: Subprozess-Timeout, keine UI-Blockade.
- Anhang zu groß: Gesamtgröße anzeigen und Entwurf nicht unbemerkt ohne Datei öffnen.
- erneutes Öffnen: neuer Entwurf erlaubt, im Audit zählen; keine neue PDF nötig, sofern bestehende Datei und Hash gültig sind.

## 20. Tests

### 20.1 Unit Tests XW-Studio

- Auftragsmodus-Validierung
- Handling-Produkt genau einmal
- feste Endpreisberechnung
- Drittland-digital ergibt 0 österreichische USt-Klassifikation
- physische und digitale Modi werden nicht verwechselt
- Erkennung bezahlter digitaler Order
- unbezahlte Order erzeugt keinen Alarm
- Handling-Produkt wird nicht lizenziert
- Mehrfachprodukte ergeben mehrere Dateien, einmal Handling
- Druckpfad-Auflösung
- fehlender Druckpfad blockiert bis Auswahl
- Wasserzeichenname ausschließlich Vorname/Nachname
- Firma wird ignoriert
- Legacy-Dateinamenersetzung `GESAMT`
- Kollisionen `(2)`, `(3)`
- Quelldatei bleibt unverändert
- Wasserzeichen auf erster und letzter Seite
- Outlook-Payload enthält alle Anhänge und englischen Text
- lokaler Abschluss ist idempotent
- Wix-Fulfillment-Fehler behält Alarm
- Part-Reparatur verändert keine kommerziellen Felder

### 20.2 Website-Unit-Tests

- Auth/HMAC gültig und ungültig
- Replay/abgelaufener Timestamp
- serverseitige Katalogpreisauflösung
- Client kann Handling-Preis nicht manipulieren
- `paymentsLimit = 1`
- digitale Line Items `shippable = false`
- physische Custom Line Item `shippable = true`
- Idempotenz über `client_request_id`
- Betrags- und Längenlimits

### 20.3 Live-Spike vor Implementierungsentscheidung

Mit Testprodukt, Testbestand und kleinem Betrag:

1. Katalogposition nicht versandpflichtig erzeugen.
2. Payment Link mit echter US-Rechnungsadresse öffnen.
3. Prüfen, dass kein Versandland und keine Versandmethode verlangt werden.
4. Steuerberechnung nach Rechnungsadresse prüfen.
5. Bezahlen.
6. Wix-Orderstruktur exportieren.
7. Bestand vorher/nachher vergleichen.
8. sevDesk-Entwurf und Artikelverknüpfung prüfen.
9. Payment- und Fulfillmentstatus prüfen.
10. Danach Variante A oder B verbindlich festlegen.

### 20.4 End-to-End-Szenarien

- AT digitale Musiknote
- DE digitale Musiknote mit Wix-Ziellandsteuer
- weiteres EU-Land mit vorhandener Steuerkonfiguration
- USA digitale Musiknote, echter US-Billing-Country, kein Versand, fixer Endpreis, 0 österreichische USt
- mehrere Musiknoten plus einmal Handling
- fehlender Druckpfad und Popup-Zuordnung
- wiederholte Bestellung desselben Kunden erzeugt `(2)`
- Outlook-Entwurf mit mehreren Anhängen
- manuell erledigt und Wix fulfilled
- physische Sonderanfertigung in erlaubtes Versandland
- physische Sonderanfertigung in nicht erlaubtes Versandland wird im Checkout abgelehnt

## 21. Rollout in Phasen

### Aktueller Umsetzungsstand 2026-07-11

Phase 1 wurde in XW-Studio umgesetzt:

- Legacy-Funktion `Wasserzeichen seitlich A4` nach PySide6 portiert.
- Dateikollisionen werden mit `(2)`, `(3)` usw. geloest; vorhandene Dateien werden nicht still ueberschrieben.
- Neues Layout-Register `Wasserzeichen seitlich A4` ergaenzt.
- Outlook-Classic-Composer um Body und mehrere Anhaenge erweitert.
- Zentraler Service fuer digitale Musiknotenlizenzen angelegt.
- Alarmbutton `DIGITALE LIZENZEN OFFEN` im Rechnungen-Untermenue ergaenzt.
- Detaildialog fuer offene digitale Lizenzen ergaenzt.
- Fehlende Druck-PDF kann per Dateiauswahl zugeordnet werden.
- Lizenzierte PDFs werden erstellt, im Lizenzordner gespeichert und an einen englischen Outlook-Entwurf angehaengt.
- Manueller Abschluss fuehrt ein lokales Audit und stoesst Wix-Fulfillment an.

Naechste technische Phase:

- Mit einer echten bezahlten Testorder pruefen, ob Wix fuer diesen Ordertyp digitale Fulfillment-Items liefert.
- Pruefen, ob die bestehende Wix-sevDesk-Automatik den gewuenschten Artikelbezug erzeugt.
- Website-Backend fuer Wix Payment Links erst danach anbinden.
- Lagerneutralitaet der digitalen Katalog-/Custom-Line-Item-Variante produktionsnah testen.
- TaxRule-17/Steuerlogik anhand eines Drittland-Testentwurfs verifizieren, bevor automatische Korrekturen aktiviert werden.

### Phase 0: Beweis-Spike

- Wix-Bestandsverhalten testen.
- Order-Payload sichern.
- sevDesk-Entwurf prüfen.
- Drittland-Steuerregel mit Testentwurf verifizieren.
- Keine produktive UI-Freigabe vor Abschluss.

### Phase 1: Zentrale Grundlagen

- Datenbankmigrationen
- Payment-Link-Backend
- XW-Studio-Client und Auth
- zentraler PDF-Lizenzierungsservice
- Outlook-Composer mit HTML und Anhängen
- neues Layout-Register

### Phase 2: Sonderauftrag-Dialog

- drei Auftragsarten
- Wix-Produktsuche und Mehrfachauswahl
- Handling-Automatik
- Linkerzeugung
- englischer Outlook-Linkentwurf
- lokales Audit

### Phase 3: Digitale Lizenzwarteschlange

- Order-Erkennung
- Alarmbutton und Count
- Detaildialog
- Druckpfad-Reparatur
- Mehrfachlizenzierung
- Outlook-Entwurf
- manueller Abschluss und Wix Fulfillment

### Phase 4: sevDesk-Härtung

- reine Read-Prüfung zunächst
- Part-Link-Reparatur nach Test
- TaxRule-17-Reparatur erst nach produktionsnahem Test
- Audit und Konfliktschutz

### Phase 5: Legacy-Ablösung

- neuen Flow mehrere reale Aufträge parallel beobachten
- alte Seite `Digitale Noten` zunächst mit Hinweis versehen
- Coupon `SHEETMUSICDIGITAL` erst nach stabiler Ablösung deaktivieren
- Legacy-Seite und Extra-Logik anschließend entfernen oder archivieren

## 22. Akzeptanzkriterien

Der Umbau gilt als fachlich abgeschlossen, wenn:

1. Ein individueller physischer oder digitaler Auftrag ohne neues dauerhaftes Produkt erzeugt werden kann.
2. Ein oder mehrere bestehende Musiknotenprodukte digital verkauft werden können.
3. `Digital Delivery Handling` genau einmal je digitalem Musiknotenauftrag berechnet wird.
4. Ein US-Kunde seine echte US-Rechnungsadresse verwenden kann, ohne dass USA als Versandland aktiviert wird.
5. Kein digitaler Sonderverkauf den Wix-Lagerbestand verändert.
6. Kein digitaler Sonderverkauf physischen Druck oder Versand auslöst.
7. Der bestehende sevDesk-Entwurf genau einmal erzeugt und der vorhandene Musiknotenartikel verknüpft wird.
8. EU-Steuern aus Wix übernommen werden und Drittland-digital nicht als Ausfuhrlieferung klassifiziert wird.
9. Nur vollständig bezahlte Orders in `DIGITALE LIZENZEN OFFEN` erscheinen.
10. Fehlende Druckpfade per Popup repariert werden können.
11. Jede Musiknotenposition genau eine personalisierte PDF erzeugt.
12. Wiederholungen Dateisuffixe `(2)`, `(3)` statt Überschreiben verwenden.
13. Outlook Classic einen englischen, bearbeitbaren Entwurf mit allen Anhängen öffnet.
14. Kein Mailversand automatisch erfolgt.
15. Der Alarm erst nach expliziter Versandbestätigung verschwindet.
16. Die Wix-Order danach als ausgeführt dokumentiert ist.
17. Alle Mutationen idempotent und auditiert sind.

## 23. Empfohlene konkrete Reihenfolge

1. Live-Spike mit Katalogposition und Bestandsmessung.
2. Entscheidung Katalogposition versus Custom Item mit SKU.
3. sevDesk-Testentwurf auf Part und `taxRule 17` prüfen.
4. PDF-Lizenzierungsservice samt Tests aus Legacy übernehmen.
5. Layout-Register `PDF-Lizenzierung` bauen.
6. Outlook-Composer um HTML und Anhänge erweitern.
7. Website-Backend für idempotente Payment Links bauen.
8. Sonderauftrag-Dialog mit drei Modi bauen.
9. Lokales Auftrags-/Lizenz-Audit modellieren.
10. Alarm `DIGITALE LIZENZEN OFFEN` implementieren.
11. Fulfillment und manuellen Abschluss anbinden.
12. Reale Pilotaufträge durchführen.
13. Erst danach Legacy-Seite und Coupon außer Betrieb nehmen.

Diese Reihenfolge minimiert das Risiko, versehentlich Lagerbestand, Steuerlogik oder bestehende sevDesk-Automatik zu beschädigen.
