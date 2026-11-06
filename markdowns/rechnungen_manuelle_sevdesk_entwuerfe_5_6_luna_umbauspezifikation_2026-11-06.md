# RECHNUNGEN: Manuelle sevDesk-Entwürfe ohne Wix-Order vollständig verarbeiten

**Stand:** 2026-11-06  
**Zielmodell für die Umsetzung:** Codex 5.6 Luna  
**Status:** verbindliche Umbauspezifikation  
**Repository:** `XW-Office`  
**Referenz-Repository:** `wix-sevdesk-api` (nur Ist- und Datenvertragsanalyse)

## 1. Zielentscheidung

Ein direkt in sevDesk angelegter Rechnungsentwurf mit Status `100` soll im
Untermenü **RECHNUNGEN** wie ein regulärer Arbeitsvorgang behandelt werden,
auch wenn er weder aus Wix stammt noch durch `wix-sevdesk-api` erzeugt wurde.

Der manuelle Entwurf soll insbesondere:

- in der Entwurfsliste erscheinen;
- in der Statusspalte mit der vorhandenen roten Entwurfsmarkierung erscheinen;
- Kunde, E-Mail, Rechnungsadresse und Rechnungspositionen aus sevDesk laden;
- die Rechnungsadresse als initiale Versandadresse verwenden, wenn keine
  eigene Lieferadresse vorhanden ist;
- normalen Adresslabel-, PLC-Label-, Zoll-, Rechnungs- und Produktdruck
  ermöglichen, soweit die jeweils benötigten Daten vollständig sind;
- PDF-Vorschau, Öffnen/Bearbeiten in sevDesk, Kundenmail, Rechnungsversand und
  Nachlieferungsfunktionen quellenrichtig unterstützen;
- im START-Flow sicher verarbeitet werden können, ohne irgendeine Wix-Aktion
  auszulösen.

Bewusste Ausnahme:

- Es gibt keine Wix-Bestellung, daher keine Wix-Ordernummer, keinen
  `WIX ORDER`-Button, kein Wix-Fulfillment und keine Wix-Zahlungsbuchung.
- Die Spalte `WIX` bleibt für diesen Datensatz ohne Nummer und zeigt `—`.
- Wix-spezifische Fulfillment-Schritte werden als **nicht anwendbar** und
  nicht als Fehler dargestellt.

Die Lösung wird in `XW-Office` umgesetzt. `wix-sevdesk-api` bleibt für diesen
Umbau unverändert.

## 2. Präzisierung des Benutzerwunsches

„Alle Annehmlichkeiten“ bedeutet nicht, Wix künstlich nachzubilden. Gemeint
ist Funktionsparität auf Basis der tatsächlich vorhandenen Quelle:

| Fähigkeit | Wix-importierter Entwurf | Manueller sevDesk-Entwurf |
| --- | --- | --- |
| Liste und roter Entwurfsstatus | sevDesk | sevDesk |
| Rechnungskopf | sevDesk, teilweise Wix ergänzt | sevDesk |
| Kunde und E-Mail | Wix bevorzugt, sevDesk als Fallback | sevDesk |
| Versandadresse | Wix-Versandadresse bevorzugt | sevDesk-Lieferadresse, sonst Rechnungsadresse |
| Produkte | Wix-Positionen plus Katalog | sevDesk-`InvoicePos` plus Part-/Produktkatalog |
| Rechnungs-PDF | sevDesk | sevDesk |
| Adresslabel | aufgelöste Versandadresse | aufgelöste Versandadresse |
| PLC-/Zolldokument | Wix-Produkte plus Katalogdaten | sevDesk-Produkte plus Katalogdaten/manuelle Ergänzung |
| Produktdruck | bestehender Druckplan | derselbe bestehende Druckplan |
| Kundenmail | Wix-/sevDesk-Mail | sevDesk-Mail |
| Rechnung senden | sevDesk | sevDesk |
| Wix-Order öffnen | ja | nein |
| Wix-Fulfillment | ja | nicht anwendbar |
| Wix-Zahlungsabgleich | je nach Order | nicht anwendbar |

Die Implementierung muss deshalb von einer **quellenneutralen Rechnung mit
Fähigkeiten** ausgehen und darf Funktionsverfügbarkeit nicht länger pauschal
an `order_reference` koppeln.

## 3. Nachgewiesener Ist-Zustand

### 3.1 Was bereits funktioniert

Die Entwürfe selbst fehlen im aktuellen Code nicht grundsätzlich:

- `RechnungenView._reload_first_page()` startet mit Status `100`.
- `InvoiceProcessingService.load_invoice_batch()` lädt direkt über sevDesk.
- `InvoiceClient.list_invoice_summaries()` übergibt `status=100` und filtert
  zusätzlich clientseitig, falls sevDesk den Filter ignoriert.
- `InvoiceSummary.status_color()` liefert für Status `100` rot.
- `_InvoiceStatusDelegate` zeichnet daraus den roten Punkt in der Spalte mit
  der Lupe.
- `InvoiceSummary.as_table_row()` zeigt ohne Wix-Referenz in `WIX` bereits `—`.

Die rote Markierung ist daher kein neu zu bauendes Feature. Sie wird als
verbindlicher Bestand erhalten und mit einem Regressionstest abgesichert.

### 3.2 Die eigentliche Funktionslücke

Die Lücke beginnt nach der Auswahl der Rechnungszeile:

```text
Status-100-Liste aus sevDesk
        |
        v
Rechnung ausgewählt
        |
        +-- order_reference vorhanden --> Wix-Kontext + Wix-Positionen
        |
        +-- keine order_reference -------> Produktbereich wird zurückgesetzt
```

`RechnungenView._hydrate_detail_for_selection()` ruft ohne
`order_reference` derzeit `_reset_stuecke()` auf. Das geschieht, obwohl
`InvoiceClient.fetch_invoice_positions(invoice_id)` bereits existiert und die
sevDesk-Positionen über `/InvoicePos?invoice[id]=...&embed=part` lesen kann.

Weitere Wix-Zentrierungen:

- Der Detailbutton `WIX ORDER` wird für jede ausgewählte Rechnung aktiviert.
- `Kundenmail` erzeugt einen Betreff mit `Wix-Order-Nr. —`.
- Der PLC-Dialog erwartet überwiegend `WixOrderItem` und bezeichnet seine
  Referenz als Wix-Ordernummer.
- Produktblöcke werden hauptsächlich über
  `PrintDecisionEngine.get_piece_blocks(wix_items, ...)` erzeugt.
- Fulfillment-Chips unterscheiden teilweise nur `true` und `false`, aber
  nicht `nicht anwendbar`.
- START behandelt einen Entwurf ohne Wix zwar teilweise weiter, hinterlässt
  den Wix-/Produktstatus aber als roten, missverständlichen Fehlzustand und
  kann die Lieferart nicht sicher aus sevDesk-Positionen bestimmen.

### 3.3 Bereits vorhandene, wiederverwendbare Bausteine

| Baustein | Wiederverwendung |
| --- | --- |
| `InvoiceClient.fetch_invoice_by_id()` | vollständiger sevDesk-Rechnungskopf |
| `InvoiceClient.fetch_invoice_positions()` | exakte Rechnungspositionen |
| `PartClient` | Part-ID, SKU, Name, Lagerstatus und digital/physisch |
| `ProductCatalogService` | kanonisches Produkt, Druckdatei, Komponenten |
| `PrintDecisionEngine` | Lager- und Druckentscheidung |
| `InvoiceProcessingService` | PDF, Rechnungsmail, Label, START, Status |
| `CustomerAftercareRedeliveryService` | liest heute schon sevDesk-Positionen für Nachlieferungen |
| `PlcLabelPrintDialog` | Label, Zollformular, Archiv und Nachdruck |
| `BackgroundWorker` / Sequenzzähler | asynchrones Laden ohne UI-Blockade |

Es wird kein paralleles Rechnungs-, Produkt- oder Drucksystem eingeführt.

## 4. Befund im Referenz-Repository `wix-sevdesk-api`

`wix-sevdesk-api` erzeugt aus Wix-Bestellungen sevDesk-Entwürfe mit Status
`100`. Der Importvertrag ist in `src/services/sevdesk.Invoice.js` erkennbar:

- `customerInternalNote` enthält die Wix-Bestellnummer, optional nach einer
  Bestellreferenz im Format `PO | 12345`;
- Wix-Positionen werden als `invoicePosSave` gespeichert;
- wenn ein sevDesk-Part gefunden wurde, enthält die Position eine
  `part`-Referenz;
- SKU bzw. Beschreibung werden in `text` geschrieben;
- Versandkosten werden als eigene Position ergänzt.

`InvoiceDraftSummary.js` liest ebenfalls Status-100-Rechnungen und deren
`InvoicePos`, liefert aber nur einen aggregierenden Bericht. Dieser Endpoint
ist kein Detail- oder Bearbeitungscontract für XW-Office und wird nicht als
neue Abhängigkeit verwendet.

Verbindliche Architekturentscheidung:

```text
Manueller sevDesk-Entwurf
        |
        v
XW-Office InvoiceClient
        |
        +-- /Invoice/{id}
        +-- /InvoicePos?invoice[id]={id}&embed=part
        +-- vorhandener Part-/Produktkatalog

Kein Umweg über wix-sevdesk-api.
```

## 5. Quellen- und Fähigkeitsmodell

### 5.1 Herkunft nicht mit einer Regex gleichsetzen

Der vorhandene `extract_wix_order_number()` erkennt jede passende
fünfstellige Zahl in Referenzfeldern. Eine manuell eingetragene fünfstellige
Kunden- oder Bestellreferenz kann dadurch fälschlich wie eine Wix-Order
aussehen.

Neu wird zwischen Kandidat, bestätigter Zuordnung und reinem sevDesk-Beleg
unterschieden:

```text
InvoiceOrigin
  SEVDESK_ONLY
  WIX_CANDIDATE
  WIX_CONFIRMED
```

Regeln:

1. Kein extrahierbarer Kandidat: sofort `SEVDESK_ONLY`.
2. Kandidat plus exakter Treffer im vorhandenen persistenten Wix-Cache:
   `WIX_CONFIRMED`.
3. Kandidat ohne Cachetreffer: `WIX_CANDIDATE`; beim Öffnen im Hintergrund
   exakt auflösen.
4. Exakter Wix-Treffer: zu `WIX_CONFIRMED` hochstufen.
5. Kein Treffer: zu `SEVDESK_ONLY` zurückstufen; die ursprüngliche
   sevDesk-Referenz bleibt als normale Belegreferenz sichtbar.

Ein bloßer Kandidat darf den `WIX ORDER`-Button, Wix-Fulfillment oder
Wix-Zahlungsaktionen nicht aktivieren.

Historische importierte Rechnungen bleiben kompatibel. Es ist weder ein
Backfill noch eine Änderung ihres `customerInternalNote` nötig.

### 5.2 Explizite Fähigkeiten

Der aufgelöste Kontext enthält mindestens:

```text
InvoiceCapabilities
  has_wix_order
  has_customer_email
  has_shipping_address
  has_invoice_pdf
  has_product_positions
  has_printable_products
  can_print_address_label
  can_create_plc_label
  can_create_customs_document
  can_send_invoice
  can_open_sevdesk
```

UI und START fragen diese Fähigkeiten ab. Sie prüfen nicht verstreut
`if summary.order_reference` und leiten daraus fachfremde Entscheidungen ab.

## 6. Quellenneutraler Rechnungskontext

### 6.1 Neues Modell

Im Service-Layer wird ein gemeinsamer Kontext eingeführt, zum Beispiel in
`src/xw_office/services/invoice_processing/context.py`:

```text
InvoiceWorkContext
  summary
  origin
  wix_order_number_candidate
  confirmed_wix_order_number
  customer_name
  customer_email
  billing_address_lines
  shipping_address_lines
  shipping_address_source
  positions
  capabilities
  warnings
  source_updated_at
```

Positionen werden nicht direkt als `PieceBlock` modelliert, sondern zuerst
fachlich normalisiert:

```text
InvoiceWorkPosition
  source_id
  position_number
  part_id
  sku
  sku_source
  name
  description
  quantity_decimal
  kind
  printable
  product
  warnings
```

`kind` kennt mindestens:

- `PRODUCT`
- `SHIPPING`
- `SERVICE`
- `DISCOUNT`
- `UNKNOWN`

Damit werden Rechnungsposition, Versandzeile und druckbares Produkt nicht
mehr miteinander verwechselt.

### 6.2 SKU-Auflösung

Verbindliche Priorität:

1. `InvoicePos.part.partNumber` bzw. eingebettete SKU;
2. `InvoicePos.part.id` über den bestehenden `PartClient`-Cache;
3. streng validierte SKU aus `InvoicePos.text`, zum Beispiel `XW-...`;
4. eindeutige Zuordnung im `ProductCatalogService`;
5. sonst keine erfundene SKU, sondern sichtbare ungelöste Position.

Bei einem warmen Part-Cache entsteht kein einzelner Netzaufruf pro Position.
Ein kalter Cache wird einmal gebündelt geladen. Nur ein echter, ausdrücklich
benötigter Fallback darf `PartClient.get_part_by_id()` verwenden.

### 6.3 Positionsregeln

- Positionen mit Part-Referenz sind grundsätzlich Produktkandidaten.
- Part-lose Namen wie `Versand`, `Versandkosten`, `Shipping` oder `Porto`
  werden als `SHIPPING` behandelt.
- Negative Positionen bzw. Rabattzeilen werden nicht gedruckt und nicht als
  physischer Artikel gebucht.
- Freitextleistungen bleiben sichtbar, sind aber ohne eindeutiges Produkt
  nicht automatisch druck- oder bestandswirksam.
- Bruchmengen werden nie still auf ganze Stück gerundet. Ein physischer
  Druckvorgang verlangt eine positive ganze Stückzahl; andernfalls erscheint
  eine klare Warnung und der Druckbutton bleibt für diese Position gesperrt.
- Fehlende SKU oder fehlendes Produkt versteckt die Rechnungsposition nicht.
  Die UI zeigt `Nicht zugeordnet` und bietet den vorhandenen Produkt-/Druckplan-
  Pflegeweg an.
- Versandpositionen erscheinen nicht im Produktdruck, können aber für
  Versandart und Preisprüfung erhalten bleiben.

### 6.4 Umwandlung in den bestehenden Druckpfad

`PrintDecisionEngine` erhält eine quellenneutrale Builder-Methode, etwa:

```text
get_piece_blocks_from_invoice_positions(positions, invoice_ref)
```

Intern verwendet sie dieselben Katalog-, Druckplan- und Lagerregeln wie der
Wix-Pfad. Alternativ kann eine gemeinsame interne Produktzeile beide Adapter
bedienen:

```text
WixOrderItem --------+
                     +--> NeutralProductLine --> PieceBlock
InvoiceWorkPosition -+
```

Die Wix-Sonderlogik für kundenspezifische XW-010-Titel wird nur ausgeführt,
wenn die dafür erforderlichen Wix-Customfelder tatsächlich vorhanden sind.
Ein sevDesk-Text darf nicht ungeprüft als äquivalentes Wix-Customfeld gelten.

## 7. Versandadresse

### 7.1 Fachliche Priorität

Für einen manuellen sevDesk-Entwurf gilt:

1. in der laufenden Ansicht bewusst manuell korrigierte Versandadresse;
2. vollständige explizite Lieferadresse aus der Rechnung;
3. vollständiger Adresssnapshot aus `invoice.address`;
4. strukturierte Rechnungsfelder
   `addressName/addressStreet/addressZip/addressCity/addressCountry`;
5. nur bei unvollständigem Snapshot die aktuelle Kontaktadresse als letzter
   Fallback.

Die Rechnungsadresse wird also initial als Versandadresse **kopiert**, nicht
als dieselbe fachliche Eigenschaft behandelt.

UI-Status bei diesem Fallback:

```text
Versandadresse aus Rechnungsadresse übernommen
```

Eine vorhandene explizite Lieferadresse zeigt dagegen:

```text
Versandadresse aus sevDesk-Lieferadresse
```

### 7.2 Notwendige Parser-Korrektur

`_shipping_lines_from_invoice_data()` liest heute vor allem generische Felder
wie `street`, `zip` und `city`. Für reale sevDesk-Rechnungen müssen zusätzlich
die gespeicherten Snapshot-Felder und der mehrzeilige Wert `address`
ausgewertet werden.

Die Adressnormalisierung wird an einer Stelle zentralisiert. Die ähnliche
Logik in `CustomerAftercareRedeliveryService._invoice_address_lines()` soll
denselben Resolver nutzen, damit Detailansicht, Nachlieferung, Label und START
nicht unterschiedliche Adressen erzeugen.

### 7.3 Keine stille Änderung in sevDesk

Die automatische Kopie ist zunächst eine XW-Office-Arbeitsadresse für Druck
und Vorschau. Sie schreibt nicht automatisch in den sevDesk-Entwurf zurück.
Das verhindert eine unbeabsichtigte Änderung steuerlich relevanter oder
historischer Rechnungsdaten.

Die vorhandenen manuellen Änderungen in `_shipping_address_overrides` bleiben
für die laufende Sitzung wirksam. Eine dauerhafte Speicherung oder ein
expliziter Button `In sevDesk speichern` ist ein separates Folgefeature und
erfordert einen geprüften sevDesk-Payloadvertrag. Es darf nicht nebenbei in
diesem Umbau eingeführt werden.

## 8. Verhalten der Rechnungsansicht

### 8.1 Liste

Für einen manuellen Status-100-Entwurf:

- `sevDesk`: Entwurfsnummer, falls vorhanden, sonst bestehende Entwurfsanzeige;
- `WIX`: `—`, Tooltip `Keine Wix-Bestellung – manueller sevDesk-Entwurf`;
- `Datum`, `Betrag`, `Kunde`: aus sevDesk;
- Lupe/Status: roter Punkt, Tooltip `Entwurf`;
- `Hinweise`: sevDesk-Notiz-, Adress- und Produktwarnungen, soweit geladen;
- `AKTIONEN`: PLC, Zoll und Nachlieferung nach Fähigkeiten;
- `FULFILLMENT`: Wix und Wix-Zahlung grau als `nicht anwendbar`, nicht rot.

Es wird keine neue Herkunftsspalte benötigt. Im Detailkopf erscheint jedoch
ein Badge `sevDesk · manuell`.

### 8.2 Auswahl und Hintergrundladen

Der Auswahlpfad lautet neu:

```text
Rechnung auswählen
  -> sofort Summary rendern
  -> gecachten sevDesk-Kontext rendern
  -> Rechnungskopf + InvoicePos asynchron laden
  -> Adresse, E-Mail, Fähigkeiten und Produkte aktualisieren
  -> bei bestätigtem Wix-Bezug zusätzlich Wix-Kontext laden
```

Für jede Auswahl wird der vorhandene Sequenzschutz beibehalten. Eine verspätete
Antwort für Rechnung A darf nach schnellem Wechsel niemals in Rechnung B
gerendert werden.

### 8.3 Detailfelder

Bezeichnungen werden quellenneutral:

- `Wix-Kunde` wird zu `Kunde`;
- `Wix-E-Mail` wird zu `E-Mail`;
- `Wix-Order-Nr.` wird nur bei bestätigter Wix-Order angezeigt;
- alternativ zeigt der Referenzbereich `sevDesk-Referenz` bzw.
  `Keine externe Bestellung`;
- Produktbereich zeigt `Produkte aus sevDesk` als Quellenhinweis;
- Versandadresse zeigt ihre genaue Quelle.

## 9. Aktionen und Buttons

### 9.1 Verfügbarkeitsmatrix

| Aktion | Manueller Entwurf | Bedingung |
| --- | --- | --- |
| Drucken · Rechnung | ja | PDF renderbar, Drucker freigegeben |
| Drucken · Adresslabel | ja | zustellfähige Adresse |
| Drucken · PLC-Label | ja | Adresse, Versandparameter und Pflichtdaten vollständig |
| Drucken · Noten/Produkte | ja | mindestens ein druckbares Produkt |
| Ansehen · Rechnungs-PDF | ja | sevDesk-PDF renderbar |
| Ansehen · PLC/Zoll/Packliste | ja | lokales Archivdokument vorhanden |
| In sevDesk öffnen/bearbeiten | ja | immer mit sevDesk-ID |
| WIX ORDER | nein | Button verborgen |
| Kundenmail | ja | gültige sevDesk-E-Mail |
| Rechnung senden | ja | gültige E-Mail und sevDesk-Preflight |
| Stornos & Gutschriften | ja | globale bestehende Funktion |
| Nachlieferung | ja | sevDesk-Kontext und Datenbank verfügbar |

### 9.2 `WIX ORDER`

Der Button wird nicht nur deaktiviert, sondern bei `SEVDESK_ONLY` verborgen.
Das Aktionsraster wird ohne leeres Loch neu angeordnet. Bei
`WIX_CANDIDATE` bleibt er ebenfalls verborgen, bis die Zuordnung bestätigt
ist.

### 9.3 Kundenmail

Die Aktion verwendet bei manuellen Entwürfen die E-Mail aus dem sevDesk-
Rechnungskopf bzw. eingebetteten Kontakt. Der Betreff lautet quellenrichtig,
zum Beispiel:

```text
sevDesk-Rechnungsentwurf 4711
```

bzw. nach Vergabe der Rechnungsnummer:

```text
sevDesk-Rechnung RE-261234
```

`Wix-Order-Nr. —` darf nicht mehr im Betreff erscheinen. Fehlt eine gültige
E-Mail, bleibt der Button deaktiviert und erklärt dies im Tooltip.

### 9.4 Rechnung senden

Bei Status `100` muss der Bestätigungsdialog ausdrücklich erklären, dass der
Versand den Entwurf finalisieren und eine Rechnungsnummer vergeben kann. Der
Dialog zeigt den ermittelten Empfänger. Fehlender Empfänger, unvollständiger
Kontakt oder nicht renderbares PDF blockieren den Versand vor dem
Seiteneffekt.

### 9.5 Nachlieferung

Der vorhandene Nachlieferungsservice liest bereits `InvoicePos`. Die gemeinsame
Positions- und Adressnormalisierung wird dort wiederverwendet. Eine fehlende
Wix-Order darf keine Fehlermeldung verursachen; Ursprungsreferenz ist dann die
sevDesk-Rechnungs-ID bzw. -nummer.

## 10. PLC-, Zoll- und Packlistenfluss

### 10.1 Quellenneutrales Versandmodell

Der PLC-Dialog darf intern nicht länger zwingend `WixOrderItem` voraussetzen.
Ein gemeinsames Modell wird eingeführt:

```text
ShipmentItem
  source
  source_item_id
  sku
  name
  quantity
  unit_weight_kg
  unit_value
  currency
  customs_description
  tariff_number
  origin_country
  warnings
```

Adapter:

- `ShipmentItem.from_wix_item(...)`
- `ShipmentItem.from_sevdesk_position(...)`

Produkt-Hub-/Katalogdaten ergänzen Gewicht und Zolldaten über die SKU. Fehlen
Pflichtdaten, bleiben sie im Dialog editierbar; das konkrete Zoll- oder
Labelkommando bleibt bis zur Vollständigkeit gesperrt.

### 10.2 Referenz

Für manuelle Entwürfe lautet die stabile Versand- und Archivreferenz:

```text
invoice_number or "SEVDESK-{invoice_id}"
```

Die Dialogbeschriftung wird von `Wix-Order-Nr.` auf `Sendungsreferenz`
umgestellt, wenn keine Wix-Order vorhanden ist. Dateiname, Statistik,
Archivsuche und Nachdruck verwenden dieselbe Referenz.

### 10.3 Verhalten ohne Produktdaten

- Ein normales Adresslabel kann mit vollständiger Adresse auch ohne
  Produktpositionen erstellt werden.
- Ein EU-PLC-Label kann erstellt werden, sobald die vom gewählten Produkt
  verlangten Versanddaten vollständig sind.
- Ein Nicht-EU-Zolldokument wird ohne belastbare Inhalts-, Wert-, Gewichts-
  und Zollangaben blockiert.
- Es werden keine Werte oder Zolltarifnummern aus Produktnamen geraten.

## 11. Fulfillment-Status und START

### 11.1 `nicht anwendbar` als eigener Zustand

`FulfillmentFlags` erhält additive Anwendbarkeitsfelder, mindestens:

```text
product_applicable
wix_applicable
payment_applicable
mail_applicable
```

Darstellung:

- erfolgreich: grün;
- anwendbar, noch nicht erledigt/fehlgeschlagen: entsprechend vorhandenem
  Status;
- nicht anwendbar: grau mit Tooltip `Für diesen Beleg nicht anwendbar`.

Für alte JSON-Payloads gelten kompatible Defaults:

- `wix_applicable = bool(order_reference)`;
- `payment_applicable` wie bisher;
- sonstige neue Felder werden aus dem aktuellen Kontext abgeleitet.

Es ist keine relationale Migration erforderlich, weil der bestehende
Settings-Payload additiv gelesen werden kann.

### 11.2 START-Preflight

START muss für jede Rechnung vor Seiteneffekten die Lieferart bestimmen:

```text
PHYSICAL
DIGITAL
SERVICE_ONLY
UNKNOWN
```

Ableitung bei manuellen sevDesk-Entwürfen:

- mindestens ein eindeutig physisches Produkt: `PHYSICAL`;
- ausschließlich eindeutig digitale Produkte: `DIGITAL`;
- nur Leistungen/Versand ohne lieferbares Produkt: `SERVICE_ONLY`;
- ungelöste produktartige Position oder widersprüchliche Daten: `UNKNOWN`.

`UNKNOWN` darf nicht still wie eine physische Bestellung verarbeitet werden.
Der START-Preflight zeigt den Fall und verlangt Zuordnung, bewusste Behandlung
oder Überspringen.

### 11.3 Ablauf für manuellen physischen Entwurf

```text
sevDesk-Kontext und InvoicePos laden
  -> Produkt-/Druckplan-Preflight
  -> Versandadresse prüfen
  -> optionale Produktdrucke vorbereiten
  -> Rechnung finalisieren/drucken
  -> genau ein Versandlabel drucken
  -> Rechnungsmail senden
  -> Wix-Fulfillment: N/A
  -> Wix-Zahlung: N/A
```

Kein Schritt darf `WixOrdersClient.resolve_order()`,
`create_fulfillment()` oder eine Wix-Bestandsbuchung aufrufen.

Ein durch den bestehenden Produktdruck bestätigter Druck darf den zugeordneten
sevDesk-Part-Bestand weiterhin über den vorhandenen, auditierbaren
`PrintDecisionEngine` aktualisieren. Das ist sevDesk-Bestandsführung und kein
Wix-Fulfillment.

### 11.4 Digital und Service-only

- `DIGITAL`: kein Adresslabel und kein physischer Produktdruck; PDF/Mail nach
  bestehender Bestätigung möglich.
- `SERVICE_ONLY`: ebenfalls kein Versandlabel; Rechnung finalisieren und
  senden, sofern der Benutzer diesen START-Modus bestätigt.
- Unvollständige E-Mail oder ein nicht renderbares PDF blockieren nur die
  betroffene Rechnung und bleiben retryfähig.

### 11.5 Einzelne Fulfillment-Chips

- Klick auf den Wix-Chip ist bei `wix_applicable=false` wirkungslos und zeigt
  keinen Retry-Cursor.
- Produkt-Retry für einen manuellen Entwurf prüft sevDesk-Positionen und
  Druckbereitschaft, nicht Wix-Fulfillment.
- Mail-, Rechnungs- und Label-Retry bleiben verfügbar, wenn ihre Fähigkeiten
  erfüllt sind.

## 12. Konkrete Codeänderungen

| Datei/Bereich | Änderung |
| --- | --- |
| `services/sevdesk/invoice_client.py` | Summary um Updatezeit/Adressdaten ergänzen; `InvoicePos` typisieren; Abruf mit `limit=1000`, Sortierung und robustem Payload-Parsing |
| `services/invoice_processing/context.py` (neu) | quellenneutraler `InvoiceWorkContext`, Positionstypen, Herkunft, Fähigkeiten, Adress- und Positionsnormalisierung |
| `services/invoice_processing/service.py` | Kontext laden/cachen; sevDesk-Positionen in Produktblöcke überführen; Mailbetreff, Fulfillment und START quellenabhängig machen |
| `services/products/print_decision.py` | neutralen Produktzeilenadapter bzw. sevDesk-Builder ergänzen; bestehende Wix-Sonderfälle bewahren |
| `services/customer_aftercare/redelivery.py` | gemeinsamen Adress-/Positionsresolver nutzen, doppelte Parserlogik entfernen |
| `ui/modules/rechnungen/view.py` | manuellen Auswahlpfad, Worker/Sequenzschutz, Quellenlabels, Buttons und Fähigkeiten implementieren |
| `ui/modules/rechnungen/plc_label_dialog.py` | `ShipmentItem`, quellenneutrale Referenz, sevDesk-Positionen, Pflichtfeldvalidierung |
| `ui/modules/rechnungen/tagesgeschaeft_view.py` | START-Preflight und Statusdarstellung für sevDesk-only Entwürfe erweitern |
| `bootstrap.py` | neuen Resolver/Service verdrahten, falls er als eigene Klasse umgesetzt wird |
| `tests/...` | Unit-, UI-, Integration- und Fullflow-Regressionen ergänzen |

### 12.1 Bestehende Methoden, die gezielt geändert werden

In `view.py` insbesondere:

- `_hydrate_detail_for_selection()`
- `_prefill_detail_from_invoice_cache()`
- `_apply_invoice_detail_context()`
- `_reset_wix_meta()` bzw. dessen quellenneutrale Ablösung
- `_update_plc_controls()`
- `_cached_customer_email_for_summary()`
- `_open_plc_post_popup()`
- `_open_customs_declaration_dialog()`
- `_customer_mail_subject()`
- `_on_stuecke_loaded()`
- Fulfillment-Chip-Hit-Test und -Retry

In `invoice_processing/service.py` insbesondere:

- `get_invoice_detail_context()`
- `get_cached_invoice_detail_context()`
- `_shipping_lines_from_invoice_data()`
- `_rows_with_fulfillment()`
- `_load_start_target_summaries()`
- `_run_start_fullflow_print_first()`
- `_run_product_step()`
- `_run_payment_step()`
- `_run_mail_step()`

Die Methoden werden nicht weiter mit zusätzlichen booleschen Sonderfällen
überladen. Herkunft und Fähigkeiten werden im gemeinsamen Kontext berechnet.

## 13. Cache, Aktualität und Performance

Manuelle Entwürfe werden in sevDesk häufig nach dem ersten Speichern weiter
bearbeitet. Ein Cache nur nach Rechnungs-ID kann deshalb veraltete Positionen
oder Adressen anzeigen.

Verbindliche Regeln:

- `InvoiceSummary` übernimmt das sevDesk-`update`-Feld als
  `source_updated_at`.
- Detail- und Positionscache werden mit Rechnungs-ID plus Updatefingerprint
  validiert.
- Eine Listenaktualisierung invalidiert Detail-/Positionsdaten, wenn sich der
  Fingerprint geändert hat.
- Status-100-Kontexte erhalten eine kurze TTL; finalisierte Rechnungen dürfen
  länger gecacht werden.
- Positionen werden beim Öffnen der Zeile und für den exakten START-Umfang
  geladen, nicht ungezügelt für die gesamte Historie.
- Mehrere gleichzeitige Anforderungen derselben Rechnung werden
  zusammengeführt.
- Der bestehende gemeinsame sevDesk-Rate-Limiter und Retry-/Cooldown-Pfad
  bleibt die einzige Netzsteuerung.
- Keine `Promise.all`-ähnliche unbeschränkte Parallelisierung über alle
  Entwürfe nach dem Vorbild des aggregierenden Node-Reports.

Zielwerte für die Abnahme:

- Auswahl zeigt Summary sofort, ohne UI-Thread-Netzwerkzugriff;
- gecachter Kontext wird sofort sichtbar;
- ein einzelner manueller Entwurf benötigt höchstens einen Invoice- und einen
  InvoicePos-Abruf, solange sein Updatefingerprint unverändert bleibt;
- schneller Zeilenwechsel zeigt nie fremde Positionen.

## 14. Fehler- und Sonderfälle

| Fall | Verhalten |
| --- | --- |
| Entwurf ohne Kontakt | sichtbar; Mail und Finalisierung mit Kontaktpflicht blockiert |
| Entwurf ohne Rechnungsnummer | stabile Referenz `SEVDESK-{id}` |
| Rechnung ohne strukturierte Adresse | mehrzeiliges `address` parsen |
| Rechnung nur mit Kontaktadresse | als letzter Fallback, Quelle sichtbar |
| explizite Lieferadresse vorhanden | nicht mit Rechnungsadresse überschreiben |
| manuelle Adresskorrektur | für Sitzung und aktuelle Aktionen maßgeblich |
| `InvoicePos` ohne Part | sichtbar, nicht automatisch druck-/bestandswirksam |
| Versandkostenposition | nicht als Produkt drucken |
| negative/Rabattposition | nicht als Produkt drucken |
| Bruchmenge | sichtbar, Produktdruck blockiert |
| unbekannte SKU | Warnung und Zuordnungsweg, kein Raten |
| fünfstellige manuelle Referenz | Wix nur nach exakter Bestätigung aktivieren |
| Wix nicht erreichbar | sevDesk-Funktionen bleiben nutzbar; Kandidat bleibt unbestätigt |
| sevDesk-Positionsfehler | Rechnungskopf bleibt sichtbar; Produkte zeigen Retryfehler |
| fehlende PLC-Zolldaten | normales Label ggf. möglich, Zollkommando blockiert |
| App-Wechsel während Fetch | veraltetes Ergebnis durch Sequenzprüfung verwerfen |
| Entwurf zwischenzeitlich finalisiert | Kontext neu laden, Status und Buttons aktualisieren |

## 15. Sicherheit, Datenschutz und Seiteneffekte

- Keine sevDesk- oder Wix-Tokens in Logs, Markdown, Tests oder Commits.
- Logs enthalten Rechnungs-ID, Quelltyp, Positionsanzahl, Dauer und
  Fehlerklasse, aber keine vollständige Kundenadresse oder Mailtexte.
- Keine Netzaufrufe im Qt-UI-Thread.
- Kein automatischer Schreibzugriff auf sevDesk beim bloßen Auswählen einer
  Rechnung.
- Kein automatisches Wix-Fulfillment ohne `WIX_CONFIRMED`.
- Keine automatische Bestandsbuchung für ungelöste oder part-lose Positionen.
- Kein Rechnungsversand ohne sichtbaren Empfänger und Bestätigung.
- Kein Zollformular mit geratenen Warenwerten, Gewichten oder Tarifnummern.
- Bestehende manuelle UI-Eingaben dürfen von später eintreffenden Worker-
  Ergebnissen nicht überschrieben werden.

## 16. Migration und Backfill

### 16.1 MVP

Für den Kernumbau ist keine relationale Datenbankmigration nötig:

- Rechnung und Positionen bleiben in sevDesk die Quelle der Wahrheit;
- Produkt- und Druckplandaten existieren bereits im XW-Office-Katalog;
- Herkunft und Fähigkeiten werden zur Laufzeit abgeleitet;
- Fulfillment-JSON wird additiv und rückwärtskompatibel erweitert;
- vorhandene Entwürfe erscheinen ohne Import oder Backfill.

### 16.2 Kein Adress-Schattenbestand

Automatisch abgeleitete Adressen werden nicht in eine neue lokale Tabelle
kopiert. Eine spätere dauerhafte manuelle Versandadresskorrektur braucht einen
separaten, bewusst entschiedenen Datenvertrag mit Quelle, Bearbeiter,
Fingerprint und Konfliktverhalten. Dieser Umbau erzeugt keinen neuen
JSON-Schattenbestand.

## 17. Umsetzungsphasen

### Phase A – Domäne und Parser

1. `InvoiceOrigin`, Fähigkeiten, `InvoiceWorkContext` und
   `InvoiceWorkPosition` einführen.
2. sevDesk-Rechnungskopf und Adresssnapshot vollständig normalisieren.
3. `InvoicePos` typisieren, sortieren und klassifizieren.
4. Part-/SKU-Auflösung mit Tests implementieren.
5. Cache-Fingerprint und Invalidierung ergänzen.

Ergebnis: rein lesender, getesteter sevDesk-Kontext ohne UI-Änderung.

### Phase B – Detailansicht und Produktdruck

1. Auswahl ohne Wix-Referenz auf den neuen Kontext umstellen.
2. Kunde, E-Mail, Referenz und Versandadressquelle quellenneutral anzeigen.
3. sevDesk-Positionen als Produktblöcke darstellen.
4. bestehende Druckpläne, Bestand und Pflegedialoge anbinden.
5. Wix-Detailpfad unverändert regressionsprüfen.

Ergebnis: manuelle Entwürfe sind vollständig einsehbar und Produkte können
gezielt gedruckt werden.

### Phase C – Aktionen und PLC

1. Buttonmatrix über Fähigkeiten steuern.
2. `WIX ORDER` bei sevDesk-only verbergen.
3. Kundenmailbetreff und sevDesk-Mailfallback korrigieren.
4. PLC auf `ShipmentItem` und quellenneutrale Referenz umstellen.
5. Label-, Zoll-, Archiv- und Nachdrucktests ergänzen.

Ergebnis: alle nicht-Wix-spezifischen Einzelaktionen funktionieren.

### Phase D – Fulfillment und START

1. Anwendbarkeitsfelder und grauen N/A-Status einführen.
2. Lieferart aus sevDesk-Positionen bestimmen.
3. `UNKNOWN` in den Preflight aufnehmen.
4. manuellen physischen, digitalen und Service-only Ablauf implementieren.
5. Wix- und Zahlungsaktionen für sevDesk-only technisch ausschließen.
6. Retry- und Wiederanlaufverhalten testen.

Ergebnis: manuelle Entwürfe sind auch im Tagesgeschäft betriebssicher.

### Phase E – Rollout und Bereinigung

1. Telemetrie und strukturierte Logs prüfen.
2. vorhandene doppelte Adress-/Positionsparser auf den gemeinsamen Resolver
   umstellen.
3. gezielte Regressionstests und manuellen Drucktest durchführen.
4. Dokumentation bei tatsächlichen Implementierungsabweichungen aktualisieren.

## 18. Testplan

### 18.1 Unit-Tests

Mindestens ergänzen:

- `tests/unit/test_invoice_client.py`
  - Status `100` bleibt Entwurf;
  - fehlende Wix-Referenz erzeugt keine Wix-Nummer;
  - InvoicePos-Abruf verwendet Invoice-ID, `embed=part`, `limit=1000`;
  - Positionen werden nach `positionNumber` sortiert;
  - Snapshotfelder und mehrzeiliges `address` werden korrekt gelesen.
- neue Tests für `InvoiceWorkContext`
  - Herkunft `SEVDESK_ONLY`, `WIX_CANDIDATE`, `WIX_CONFIRMED`;
  - Adresspriorität;
  - SKU-Auflösung per eingebettetem Part, Part-ID und strengem Textfallback;
  - Versand-, Service-, Rabatt-, Freitext- und Bruchmengenklassifikation.
- `tests/unit/test_invoice_processing_service.py`
  - manueller Detailkontext;
  - quellenrichtiger Mailbetreff;
  - Fulfillment-N/A;
  - kein Wix-Clientaufruf bei sevDesk-only.
- `tests/unit/test_invoice_processing_fullflow.py`
  - physischer manueller Entwurf;
  - digitaler manueller Entwurf;
  - Service-only;
  - unknown blockiert vor Seiteneffekt;
  - Wix-/Payment-Schritte bleiben N/A.
- `tests/unit/test_rechnungen_product_print.py`
  - sevDesk-Position verwendet denselben Druckplan wie Wix;
  - ungelöste Position bucht keinen Bestand.

### 18.2 UI-Tests

In `tests/ui/test_rechnungen_view_smoke.py` und
`tests/ui/test_plc_label_dialog_feedback.py`:

- manueller Entwurf erscheint mit rotem Statuspunkt;
- `WIX` zeigt `—`;
- `WIX ORDER` ist verborgen;
- Kunde und E-Mail kommen aus sevDesk;
- Rechnungsadresse wird initial in Versandadresse übernommen;
- Quellenhinweis ist sichtbar;
- Produkte aus InvoicePos erscheinen mit Menge, Name und SKU;
- Versandposition erscheint nicht als druckbares Produkt;
- Kundenmail ohne E-Mail ist deaktiviert;
- Kundenmailbetreff enthält kein Wix-Platzhalterfeld;
- PLC verwendet Rechnungsnummer bzw. `SEVDESK-{id}`;
- Zollaktion bleibt bei fehlenden Pflichtdaten gesperrt;
- Wix-verknüpfte Rechnung behält den bisherigen Wix-Pfad.

### 18.3 Integrationstests

- `tests/integration/test_rechnungen_rapid_switch.py` um verspätete
  sevDesk-Positionsantworten erweitern.
- Fake-sevDesk liefert zwei Entwürfe, davon einen manuell und einen
  Wix-verknüpft; beide Pfade dürfen sich nicht gegenseitig überschreiben.
- Aktualisierung des manuellen Entwurfs in sevDesk ändert den
  Updatefingerprint und invalidiert den Positionscache.
- Rate-Limit/429 erzeugt einen verständlichen Retryzustand und blockiert die
  UI nicht.

### 18.4 Manuelle Abnahme

Mit einem eigens angelegten sevDesk-Entwurf testen:

1. Privatkunde mit vollständiger Rechnungsadresse und E-Mail.
2. Mindestens ein echter sevDesk-Part mit SKU und Menge.
3. Eine Versandkosten- oder Freitextposition.
4. Keine Wix-Referenz.
5. Ansicht in RECHNUNGEN öffnen und Daten vergleichen.
6. Adresslabel drucken.
7. PLC-Label in EU-Konstellation erzeugen und archivieren.
8. Produktdruck samt Lagerverhalten prüfen.
9. Rechnungsvorschau öffnen.
10. Kundenmailentwurf prüfen.
11. START SELECTED im kontrollierten Testmodus durchführen.
12. Verifizieren, dass keinerlei Wix-Fulfillment oder Wix-Zahlungsaktion
    ausgelöst wurde.

Ein separater Nicht-EU-Test prüft, dass fehlende Zolldaten blockieren und
nach manueller Vervollständigung ein korrektes Dokument erzeugt wird.

## 19. Verbindliche Akzeptanzkriterien

### LIST-01 – Manueller Entwurf sichtbar

Gegeben ist eine direkt in sevDesk angelegte Rechnung mit Status `100` und
ohne Wix-Referenz. Nach Aktualisierung erscheint sie in RECHNUNGEN.

### LIST-02 – Roter Entwurfsstatus

Die Lupe-/Statusspalte zeigt den roten Entwurfspunkt mit verständlichem
Tooltip.

### LIST-03 – Keine Wix-Nummer

Die Spalte `WIX` zeigt `—`; eine beliebige fehlende Referenz wird nicht durch
eine sevDesk-ID ersetzt.

### SOURCE-01 – Keine falsche Wix-Zuordnung

Eine manuelle fünfstellige Referenz aktiviert ohne exakten Wix-Treffer weder
Wix-Button noch Wix-Fulfillment.

### DETAIL-01 – sevDesk-Kundendaten

Kunde und E-Mail werden aus dem sevDesk-Rechnungskontext dargestellt.

### ADDRESS-01 – Rechnungsadresse als Fallback

Ohne eigene Lieferadresse ist die Versandadresse beim Öffnen vollständig aus
der Rechnungsadresse vorbelegt und als solche gekennzeichnet.

### ADDRESS-02 – Lieferadresse gewinnt

Eine vorhandene abweichende Lieferadresse wird niemals von der
Rechnungsadresse überschrieben.

### PRODUCT-01 – sevDesk-Positionen

Produktname, SKU und Menge werden aus `InvoicePos`/Part angezeigt, ohne Wix
abzufragen.

### PRODUCT-02 – Nichtproduktpositionen

Versand, Rabatt, Leistung und Freitext werden nicht automatisch als
physische Druckartikel behandelt.

### PRODUCT-03 – Bestehender Druckplan

Eine eindeutig gemappte SKU verwendet denselben Produktkatalog, Druckplan
und Bestandsmechanismus wie eine Wix-importierte Rechnung.

### ACTION-01 – Wix verborgen

Im Detail eines sevDesk-only Entwurfs ist `WIX ORDER` nicht sichtbar und in
der Tabellenaktion nicht ausführbar.

### ACTION-02 – Kundenmail

Mit gültiger sevDesk-E-Mail öffnet `KUNDENMAIL` einen quellenrichtigen Entwurf
ohne `Wix-Order-Nr. —`.

### ACTION-03 – Rechnung senden

Der Versand eines Entwurfs zeigt Empfänger und Finalisierungsfolge vor dem
Seiteneffekt; ohne Empfänger erfolgt kein Versand.

### LABEL-01 – Normales Versandlabel

Mit zustellfähiger Rechnungsadresse lässt sich ein Versandlabel drucken.

### PLC-01 – PLC ohne Wix

Ein PLC-Label kann mit Rechnungsnummer bzw. sevDesk-ID als Sendungsreferenz
erstellt, archiviert, geöffnet und nachgedruckt werden.

### PLC-02 – Zollschutz

Ein Nicht-EU-Zolldokument wird ohne vollständige Waren-, Wert-, Gewichts- und
Zolldaten nicht ausgelöst.

### START-01 – Kein Wix-Seiteneffekt

START SELECTED für einen manuellen Entwurf ruft weder Wix-Auflösung,
Fulfillment noch Wix-Zahlungsbuchung auf.

### START-02 – N/A statt Fehler

Wix- und Wix-Zahlungschips erscheinen grau als nicht anwendbar und erzeugen
keinen roten Fehlstatus.

### START-03 – Unklare Lieferart

Ungelöste produktartige Positionen stoppen die betroffene Rechnung im
Preflight vor Finalisierung, Druck, Label und Mail.

### REGRESSION-01 – Wix-Pfad unverändert

Ein bestätigter Wix-Entwurf behält Wix-Versandadresse, Wix-Positionen,
Wix-Orderbutton, Wix-Fulfillment und bestehende Druckfunktionen.

### PERFORMANCE-01 – Schneller Zeilenwechsel

Beim schnellen Wechsel zwischen Rechnungen erscheinen nie Adresse oder
Produkte einer zuvor ausgewählten Rechnung.

## 20. Rollout und Beobachtbarkeit

Empfohlener Rollout:

1. Kontextresolver und rein lesende Produktanzeige aktivieren.
2. Einzelaktionen für Label, Produktdruck und Kundenmail freigeben.
3. PLC-/Zollpfad aktivieren.
4. START-Unterstützung nach erfolgreicher manueller Abnahme freigeben.

Falls ein Feature-Flag verwendet wird, soll es den neuen manuellen Kontext
als Ganzes steuern, zum Beispiel:

```yaml
rechnungen:
  manual_sevdesk_drafts_enabled: true
```

Zu protokollierende Metriken:

- Ladezeit Rechnungskopf;
- Ladezeit InvoicePos;
- Cachehit/-miss;
- Anzahl Positionen und ungelöste Positionen;
- ermittelte Herkunft und Lieferart;
- geblockte Aktionen nach Grund;
- ausdrücklich übersprungene Wix-Schritte;
- START-Erfolg/Fehler pro Phase.

Keine Adressen, E-Mail-Inhalte oder vollständigen Kundennotizen in Metriken.

## 21. Nicht-Ziele

- Keine künstliche Wix-Order für manuelle sevDesk-Rechnungen.
- Keine nachträgliche Wix-Bestellung nur für Fulfillmentzwecke.
- Keine Änderung an `wix-sevdesk-api` für den Kernumbau.
- Kein automatisches Zurückschreiben der Versandadresse in sevDesk.
- Keine neue lokale Rechnungs- oder Positionsdatenbank.
- Keine geratenen SKU-, Gewichts-, Wert- oder Zolldaten.
- Keine automatische Finalisierung allein durch das Öffnen der Detailansicht.
- Keine Änderung des geschützten Content-Studio-Archivs.

## 22. Anweisung an Codex 5.6 Luna

Vor der Umsetzung:

1. `AGENTS.md` vollständig lesen und befolgen.
2. Mit sauberem Arbeitsbaum `main` verwenden.
3. `git pull --ff-only origin main` ausführen.
4. Die genannten Services, UI-Pfade und Tests erneut gegen den aktuellen
   Code prüfen.
5. Keine fachfremden Benutzeränderungen überschreiben.

Während der Umsetzung:

1. Phasen A bis E in kleinen, testbaren Schritten umsetzen.
2. Keine Netzarbeit in den UI-Thread verlagern.
3. Wix- und sevDesk-Pfade über gemeinsame Modelle zusammenführen, nicht durch
   kopierte Parallelimplementierungen.
4. Jede schreibende Aktion durch einen read-only Preflight absichern.
5. Bestehende Wix-Funktionalität nach jeder Phase regressionsprüfen.

Nach der Umsetzung:

1. relevante Unit-, UI- und Integrationstests ausführen;
2. einen kontrollierten manuellen sevDesk-Testbeleg verwenden;
3. Diff, Arbeitsbaum und geschütztes Archiv kontrollieren;
4. fertige Änderungen in `main` committen;
5. ohne Force-Push nach `origin/main` pushen.

## 23. Definition of Done

Der Umbau ist erst abgeschlossen, wenn ein manuell in sevDesk angelegter
Status-100-Entwurf in RECHNUNGEN sichtbar ist, seinen roten Entwurfsstatus
behält, seine vollständigen sevDesk-Daten und Positionen zeigt, die
Rechnungsadresse sicher als Versandfallback verwendet, alle fachlich
anwendbaren Druck-, Mail-, PDF-, PLC-, Zoll-, Nachlieferungs- und START-
Funktionen bietet und dabei garantiert keine Wix-Ordernummer, keinen
Wix-Button, kein Wix-Fulfillment und keine Wix-Zahlungsaktion vortäuscht.

Gleichzeitig müssen bestehende Wix-importierte Rechnungen ihren bisherigen
Funktionsumfang unverändert behalten.
