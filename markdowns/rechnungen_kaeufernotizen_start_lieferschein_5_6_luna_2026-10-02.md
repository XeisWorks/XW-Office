# Rechnungen: Käufernotizen, START-Review und kundenfähiger Lieferschein

**Zielversion:** Codex 5.6 Luna  
**Status:** verbindlicher Umsetzungsplan  
**Datum:** 2026-10-02  
**Gültigkeit:** Modul `RECHNUNGEN`, insbesondere START und die rechte Analyseansicht

## 1. Ergebnis und fachliche Entscheidung

Käufernotizen dürfen vor einer Rechnungs- und Versandverarbeitung nicht mehr
unbemerkt bleiben. Ein START-Lauf erhält deshalb einen verpflichtenden
Notiz-Review, wenn im exakten Laufumfang mindestens eine Käufernotiz vorliegt.

Für physische Bestellungen kann die bearbeitende Person pro Notiz einen
**kundenfähigen Lieferschein** vormerken. Dieser wird im Stil des bestehenden
Dialogs **OFFENE SENDUNGEN** aufgebaut: Empfängeradresse, Produkte,
Käufernotiz und eine bearbeitbare Kurznotiz. Im START-Lauf wird er in der
festen Reihenfolge gedruckt:

```text
Lieferschein -> Rechnung -> Versandlabel -> Fulfillment/Mail
```

Ein fehlgeschlagener Lieferscheindruck blockiert den Druck dieser Rechnung;
es darf kein unvollständiger Papierstapel entstehen.

Für digitale-only Bestellungen wird nie ein Papier-Lieferschein oder
Versandlabel erzeugt. Die Käufernotiz muss dennoch ausdrücklich geprüft und
mit einer digitalen bzw. keiner Papieraktion quittiert werden.

## 2. Nachgewiesener Ist-Zustand

Die Untersuchung von Wix-Order `21427` am 2026-10-02 ergab:

| Aspekt | Befund |
| --- | --- |
| Wix-Order | vorhanden, `buyerNote` enthält die vollständige Käufernotiz |
| sevDesk-Rechnung | `RE-262433`, Status `200`, `buyer_note` ist leer |
| START-Historie | die Wix-Notiz wurde im Lauf um 07:47 Uhr korrekt als Run-Snapshot gespeichert |
| Sichtbarkeit | nach einem weiteren START-Lauf liegt sie in `RUN −2`; in der selektierten Rechnungsdetailansicht fehlt sie |

Die Daten wurden somit nicht verloren. Die gegenwärtige Anzeige ist aber
nicht betriebssicher:

1. Die Übersichtsblöcke werten nur sichtbare Entwürfe mit Status `100` aus.
2. Die Detailansicht einer selektierten Rechnung zeigt nur
   `InvoiceSummary.buyer_note` aus sevDesk. Eine separat geladene Wix-Notiz
   wird dort nicht nachgetragen.
3. Die Run-Historie ist nicht auf den konkreten START-Umfang fokussiert und
   Käufernotizen liegen optisch zwischen anderen Analyseblöcken.
4. Der bisherige Resolver bevorzugt in einem Pfad eine bereits vorhandene
   sevDesk-Notiz und kann dadurch eine zusätzliche Wix-Notiz unterdrücken.

Das bestehende Panel `KÄUFER-NOTIZEN` bleibt als Übersicht erhalten, ist aber
kein Ersatz für einen bewussten START-Entscheidungspunkt.

## 3. Quellenvertrag: B2C und B2B nicht vermischen

Eine Käufernotiz wird als fachlicher Datensatz mit Herkunft geführt, nicht
als anonymer String. Mindestens diese Quellen werden unabhängig gesammelt:

| Quelle | Technischer Wert | Verwendung |
| --- | --- | --- |
| sevDesk-Rechnung | `InvoiceSummary.buyer_note` / API-Feld `buyerNote` | vorhandene Rechnungsnotiz |
| Wix-Bestellung | `buyerNote`, kompatibel zusätzlich `buyerNotes` | Bestellnotiz aus dem Shop |
| künftige B2B-Sonderquelle | dedizierter Adapter je bestätigtem Feld/Endpoint | nur nach einer realen B2B-Belegprobe aktivieren |

Die aktuell geprüften B2B-Beispiele `21402` und `21427` liefern beide ihre
Notiz über Wix `buyerNote`; sevDesk ist dort leer. Daraus darf jedoch keine
globale B2C/B2B-Annahme abgeleitet werden. Die Implementierung muss daher pro
Quelle arbeiten und die Herkunft in UI, Review, Snapshot und Tests erhalten.

### 3.1 Neues Kernmodell

Ein neues, serialisierbares Modell `BuyerNoteCase` ersetzt die lose
`BuyerNote`-Darstellung im START-Pfad:

```text
invoice_id, invoice_number, order_reference, customer_name
source: sevdesk_invoice | wix_order | b2b_adapter
source_label
note_verbatim
physical_delivery: bool | unknown
address_lines
products
note_fingerprint
```

Mehrere Quellen derselben Bestellung bleiben getrennt sichtbar. Identische
Texte dürfen nur als visuelle Duplikatgruppe zusammengefasst werden; die
Herkunftskennzeichnung bleibt erhalten. Die Originalnotiz wird unverändert
gespeichert und auf dem Lieferschein ausgegeben. Gekürzte oder von OpenAI
interpretierte Texte sind dafür kein Ersatz.

### 3.2 Auflösung und Fehlerverhalten

Die Auflösung erfolgt in einem Worker für **genau die Rechnungen des
angeforderten START-Laufs** (`ALL` oder `SELECTED`):

1. sevDesk-Zusammenfassung lesen.
2. vorhandene Wix-Cache-Daten verwenden.
3. bei Cache-Miss die Wix-Bestellung einmalig abrufen und den Cache auffüllen.
4. alle Quellen in `BuyerNoteCase` überführen.
5. Lieferart, Produktzeilen und Adresse in denselben Kontext aufnehmen.

Eine nicht verfügbare Quelle wird als `unavailable` im Review angezeigt und
blockiert keine Bestellung ohne Notiz. Gibt es dagegen eine Notiz, aber keine
sichere Lieferart, Adresse oder Produktdaten, darf ein Lieferschein nicht
automatisch gedruckt werden. Die Person muss den Datensatz bearbeiten oder
die Rechnung für diesen START überspringen.

Protokolle enthalten nur Referenz, Quelle, Textlänge und Fingerprint – nie
den vollständigen Käufernotiztext.

## 4. Käufernotiz in der Rechnungsansicht

Die rechte Detailansicht wird so erweitert, dass sie auch bei Status `200`
und nach einer Suche die tatsächlich aufgelösten Käufernotizen zeigt.

* Die Detailkarte heißt `KÄUFERNOTIZEN` und zeigt Quelle, Wix-Referenz und
  Originaltext.
* Beim Laden der Wix-Details wird die Karte aktualisiert; ein leeres
  sevDesk-Feld versteckt keine vorhandene Wix-Notiz mehr.
* Der Analyseblock erhält eine deutlich sichtbare Warnfarbe und den Titel
  `KÄUFERNOTIZEN – PRÜFUNG ERFORDERLICH (n)`, wenn offene Entwürfe betroffen
  sind.
* Die Run-Historie trägt Umfang und Zeit bei sich. Sie darf nicht als aktuelle
  offene Arbeit missverstanden werden; `AKTUELL`, `LAST RUN` und ältere Runs
  bleiben klar getrennt.

## 5. START-Notizreview

### 5.1 Position im Ablauf

Der neue Review wird nach der B2B-Kreditprüfung und vor Produkt- bzw.
Druck-Preflight angezeigt. Damit löst weder Inventar- noch Drucklogik
Seiteneffekte aus, bevor Käufernotizen bewusst entschieden wurden.

```text
START / START SELECTED
  -> Rechnungsumfang ermitteln
  -> B2B-Kreditprüfung
  -> Käufernotizen, Lieferart, Adresse und Produkte auflösen
  -> verpflichtender Käufernotiz-Review
  -> bestehender Produkt-/Bestands-Preflight
  -> START-Ausführung
```

Für Läufe ohne Notizen entsteht kein zusätzlicher Dialog.

### 5.2 Dialoggestaltung

`BuyerNoteReviewDialog` orientiert sich an **OFFENE SENDUNGEN**: links die
Fälle, rechts die bearbeitbare Detailkarte. Er arbeitet ausschließlich auf
dem bereits ermittelten START-Umfang.

Pro Fall zeigt die Karte:

* Rechnung, Wix-Order, Kunde und Quellen-Badge;
* Originalnotiz, unverändert und deutlich hervorgehoben;
* Lieferart `physisch`, `digital-only` oder `unklar`;
* abgerufene Versandadresse mit Editiermöglichkeit;
* Produktzeilen für den Lieferschein;
* Lieferschein-Vorschau sowie die zu erwartende Druckreihenfolge.

Verbindliche Fallaktionen:

| Aktion | Bedeutung |
| --- | --- |
| `Gelesen – normal verarbeiten` | Notiz ist geprüft; physischer Standardlauf bleibt unverändert |
| `Lieferschein vormerken` | kundenfähigen Lieferschein mit bearbeitbarem Zusatztext erzeugen und vor Rechnung drucken |
| `Rechnung in diesem Lauf überspringen` | keine Finalisierung, kein Druck, kein Fulfillment für diese Rechnung |
| `Digitale Aktion bestätigt` | nur bei digital-only; keine Papierausgabe |

Zusätzliche Hilfsaktionen ohne Abschlusswirkung:

* `Wix-Bestellung öffnen`
* `sevDesk-Rechnung öffnen`
* `Notiz kopieren`
* `Lieferschein-Vorschau`
* `Adresse neu laden`

`START fortsetzen` bleibt deaktiviert, bis jeder Fall eine zulässige Aktion
hat. `Abbrechen` hat keine Seiteneffekte. Eine gewählte Aktion wird mit
Fingerprint und Zeit in den START-Snapshot aufgenommen; eine geänderte Notiz
oder Bestellung erzwingt beim nächsten START erneut eine Prüfung.

OpenAI bleibt optional: Es kann wie bei OFFENE SENDUNGEN eine Kurzfassung als
Vorschlag erzeugen, aber nie den Originaltext überschreiben, nie eine
Lieferart entscheiden und nie ohne Vorschau einen Lieferschein drucken.

## 6. Kundenfähiger Lieferschein

### 6.1 Wiederverwendung statt zweitem PDF-System

Der bestehende PDF-Stil von `OffeneSendungenService` wird wiederverwendet,
aber von dessen mailgebundenem `SendungCase` entkoppelt. Dafür entsteht ein
gemeinsamer, fachlich neutraler `DeliveryNoteService` bzw. ein gemeinsamer
Renderer mit einem Eingabemodell:

```text
DeliveryNoteContext(
  invoice_number, order_reference, customer_name,
  address_lines, products, buyer_note_verbatim, manual_note
)
```

Der Dialog OFFENE SENDUNGEN nutzt danach denselben Renderer weiter. Das
verhindert zwei optisch und fachlich auseinanderlaufende Lieferschein-PDFs.

Der Lieferschein enthält mindestens:

* Überschrift `Lieferschein` und Rechnungs-/Bestellreferenz;
* Empfängeradresse;
* Produktzeilen mit Menge;
* Käufernotiz als klar markierten Abschnitt;
* optionalen, im Review bearbeiteten Zusatztext;
* Erstellzeitpunkt.

### 6.2 Adresse

Adress-Fetching ist sinnvoll und wird umgesetzt. Die Reihenfolge lautet:

1. im Review manuell bestätigte Adresse;
2. aktuelle Wix-Versandadresse;
3. sevDesk-Versand-/Rechnungsadresse als Fallback.

Die gewählte Adresse wird im Review sichtbar, kann zeilenweise bearbeitet
werden und wird in den Start-Snapshot übernommen. Eine physische Lieferung
ohne zustellfähige Adresse blockiert `Lieferschein vormerken` und verlangt
eine Korrektur oder `Überspringen`.

### 6.3 Versandlabel

Ein zusätzlicher Labeldruck aus dem Review wäre nicht sinnvoll: Der normale
START-Lauf druckt für physische Bestellungen bereits genau ein Label. Ein
zweiter Dialogdruck würde Duplikate erzeugen und die Sortierreihenfolge
gefährden.

Stattdessen nutzt der START die im Review bestätigte Adresse für die
bestehende Labelphase. Die verbindliche physische Reihenfolge ist damit:

```text
optional Lieferschein -> Rechnung -> genau ein Label
```

Ein manueller Label-Nachdruck bleibt ausschließlich die vorhandene
Einzelaktion bzw. ein Fehler-/Retry-Pfad nach dem Lauf. Digital-only Fälle
überspringen Lieferschein und Label vollständig.

### 6.4 Druckgarantien

* Lieferschein und Rechnung verwenden dieselbe `PrintQueueService`-Reihenfolge.
* Der Lieferscheindruck wird vor dem Rechnungsdruck bestätigt (`wait=True`
  beziehungsweise vorhandene Spooler-Bestätigung).
* Fehler im Lieferschein oder fehlende PDF-/Adressdaten markieren nur die
  betroffene Rechnung als fehlgeschlagen; Rechnung, Label, Fulfillment und
  Mail dieser Bestellung unterbleiben.
* Der verbleibende START-Lauf folgt der vorhandenen STOP- und
  Fehlerbehandlung.

## 7. Notwendige Codeänderungen

| Bereich | Änderung |
| --- | --- |
| `open_invoice_overview.py` | quellenfähige Notizmodelle und deterministische Sammlung statt String-Fallback |
| `invoice_processing/service.py` | Start-spezifische Auflösung, Kontext-Fingerprint, Delivery-Note-Phase vor `invoice_print`, Ergebnisfelder |
| `tagesgeschaeft_view.py` | Worker-Payload erweitern, `BuyerNoteReviewDialog` vor Produkt-Preflight, übersprungene IDs an START weiterreichen |
| `view.py` | Wix-Notizen in Detailkarte nachladen, Warnzustand und exakte Run-Snapshots anzeigen |
| `services/sendungen/service.py` | PDF-Renderer in gemeinsamen Delivery-Note-Service auslagern, bestehende Offene-Sendungen-API kompatibel halten |
| `services/printing/*` | vorhandene Warteschlange und Bestätigungsweg verwenden, keine zweite Druckabstraktion |
| Persistenz | Schema der START-Historie auf v3 mit Notizquelle, Reviewaktion, Adress-/Kontextfingerprint und Lieferscheinstatus erweitern |

Bestehende Daten der Snapshot-Schemata v1 und v2 müssen lesbar bleiben. Neue
Felder erhalten sichere Standardwerte.

## 8. Testplan und Abnahmekriterien

### 8.1 Unit-Tests

* Wix- und sevDesk-Notiz derselben Order bleiben mit Herkunft sichtbar.
* Nichtleere sevDesk-Notiz unterdrückt keine Wix-Notiz.
* B2B- und B2C-Belegfixtures verwenden jeweils die bestätigte reale Quelle.
* Kontextresolver nutzt Adresse gemäß Priorität und verweigert unzustellbare
  physische Fälle.
* Digital-only erzeugt keinen Delivery-Note- oder Labelauftrag.
* Lieferschein-Fehler verhindert Rechnung, Label, Fulfillment und Mail nur
  für die betroffene Bestellung.
* Erfolgsreihenfolge ist `delivery_note_print`, `invoice_print`,
  `label_print`.
* v1/v2-Snapshots werden weiterhin geladen; v3 speichert Quellen und
  Reviewaktionen.

### 8.2 UI-Tests

* Ausgewählte Rechnung mit leerer sevDesk-Notiz und Wix-Notiz zeigt die
  Detailkarte nach der Wix-Hydrierung.
* Der START-Dialog erscheint nur für Notizen im ausgewählten Laufumfang.
* `START fortsetzen` ist bis zur Entscheidung jedes Falls deaktiviert.
* `Lieferschein vormerken` zeigt Adresse, Produkte und Vorschau.
* `Überspringen` entfernt genau diese Rechnung aus dem späteren START-Call.
* Keine doppelte Labelauslösung aus Review und START.
* Run-Historie macht ältere Käufernotizen auffindbar und kennzeichnet sie
  korrekt als historischen Lauf.

### 8.3 Manuelle Abnahme

1. B2B-Fall mit Käufernotiz und physischem Produkt.
2. B2C-Fall mit Käufernotiz und physischem Produkt.
3. Käufernotiz wie Order `21427`: Lieferschein enthält Originalnotiz,
   korrekte Adresse, Produkte; Druckreihenfolge ist Lieferschein, Rechnung,
   Label.
4. Digital-only mit Käufernotiz: Review nötig, keine Papierausgabe.
5. Fehlende Adresse und fehlgeschlagener Lieferscheindruck stoppen nur die
   betroffene Rechnung sicher.
6. START SELECTED enthält keine Notiz aus nicht markierten Rechnungen.

## 9. Lieferreihenfolge für 5.6 Luna

1. Datenmodell, Quellenadapter und Resolver mit Tests.
2. Detailkarten-Fix für Wix-Notizen und verbesserte Run-Historie.
3. Gemeinsamen kundenfähigen Lieferschein-Renderer aus OFFENE SENDUNGEN
   herauslösen und bestehende Dialogtests absichern.
4. START-Reviewdialog samt verpflichteten Aktionen und Persistenz einbauen.
5. Delivery-Note-Phase und adressgebundene bestehende Labelphase in den
   START-Workflow integrieren.
6. Vollständige Unit-, UI- und manuelle Druckreihenfolge-Abnahme.

## 10. Nicht-Ziele

* Kein automatisches Auslegen jeder Käufernotiz als Lieferscheinauftrag.
* Kein automatischer OpenAI-Text als kundenwirksamer Inhalt.
* Kein zweites Versandlabel für reguläre physische START-Bestellungen.
* Keine Änderung des unveränderlichen Content-Studio-Archivs.
