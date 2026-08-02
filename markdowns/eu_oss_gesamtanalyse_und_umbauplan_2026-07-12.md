# EU-OSS Gesamtanalyse und Umbauplan (Q1/Q2 2026)

Stand: 12.07.2026  
Status: Analyse, Planung und Teilumsetzung der Berechnungslogik

## 1. Ziel und Abgrenzung

Geprueft wurde der PySide6-Pfad von sevDesk bis zum EU-OSS-XML:

1. Quartals- und Belegauswahl;
2. Laden der Rechnungen, Gutschriften und Positionen;
3. Erkennung von EU-B2C-OSS-Umsaetzen;
4. Land-, Steuersatz- und Waren/Leistungs-Klassifikation;
5. Aggregation von Netto und Umsatzsteuer;
6. Vorschau;
7. XML-Erzeugung und lokale Validierung;
8. UI-Ablauf fuer Vorschau, Speichern und Portalaufruf;
9. Laufzeit und Wiederholbarkeit.

Die vom Anwender bestaetigten Werte wurden in
`config/oss_reference_values.json` als unveraenderbare Referenz gespeichert.
Sie sind reine Vergleichsdaten und duerfen weder Live-Werte ersetzen noch
Abweichungen automatisch korrigieren.

## 2. Golden Master

### Q1/2026

| Land/Satz | Netto | Steuer | Brutto |
|---|---:|---:|---:|
| DE 7 % | 5.175,91 | 373,16 | 5.549,07 |
| IT 4 % | 491,77 | 19,73 | 511,50 |
| NL 9 % | 97,80 | 8,80 | 106,60 |
| LU 3 % | 240,26 | 7,24 | 247,50 |
| SE 6 % | 20,83 | 3,97 | 24,80 |
| EE 9 % | 90,90 | 8,10 | 99,00 |
| ES 10 % | 5,00 | 0,50 | 5,50 |

### Q2/2026

| Land/Satz | Netto | Steuer | Brutto |
|---|---:|---:|---:|
| DE 7 % | 4.036,26 | 286,04 | 4.322,30 |
| IT 4 % | 599,95 | 24,05 | 624,00 |
| NL 9 % | 269,97 | 24,33 | 294,30 |
| FR 5,5 % | 147,49 | 8,11 | 155,60 |
| CZ, Bezeichnung 0 % | 34,80 | 0,00 | 34,80 |

Der fruehere CZ-Referenzkonflikt wurde am 12.07.2026 durch Anwenderkorrektur in
sevDesk aufgeloest. `RE-261935` ist jetzt ein echter 0-%-Fall: 34,80 EUR netto,
0,00 EUR Steuer, 34,80 EUR brutto. Die Referenzdatei wurde entsprechend
angepasst; sie bleibt Vergleichsdatenbestand und kein Berechnungs-Override.

## 3. Live-Ergebnisse

### Q1/2026

Kalter Live-Lauf: 138,339 Sekunden, 919 geladene Dokumente, 791 ausgeschlossen.

| Land/Satz | Live Netto | Soll Netto | Delta Netto | Live Steuer | Soll Steuer | Delta Steuer |
|---|---:|---:|---:|---:|---:|---:|
| DE 7 % | 5.102,93 | 5.175,91 | -72,98 | 368,04 | 373,16 | -5,12 |
| IT 4 % | 481,19 | 491,77 | -10,58 | 19,31 | 19,73 | -0,42 |
| NL 9 % | 97,80 | 97,80 | 0,00 | 8,80 | 8,80 | 0,00 |
| LU 3 % | 209,39 | 240,26 | -30,87 | 6,31 | 7,24 | -0,93 |
| SE 6 % | 20,83 | 20,83 | 0,00 | 3,97 | 3,97 | 0,00 |
| EE 9 % | fehlt | 90,90 | -90,90 | fehlt | 8,10 | -8,10 |
| ES 10 % | fehlt | 5,00 | -5,00 | fehlt | 0,50 | -0,50 |

### Q2/2026

Kalter Live-Lauf: 69,179 Sekunden, 760 geladene Dokumente, 658 ausgeschlossen.

| Land/Satz | Live Netto | Soll Netto | Delta Netto | Live Steuer | Soll Steuer | Delta Steuer |
|---|---:|---:|---:|---:|---:|---:|
| DE 7 % | 3.999,01 | 4.036,26 | -37,25 | 284,39 | 286,04 | -1,65 |
| IT 4 % | 599,95 | 599,95 | 0,00 | 24,05 | 24,05 | 0,00 |
| NL 9 % | 269,97 | 269,97 | 0,00 | 24,33 | 24,33 | 0,00 |
| FR 5,5 % | 147,49 | 147,49 | 0,00 | 8,11 | 8,11 | 0,00 |
| CZ / Konflikt 0 % | fehlt | 32,26 | -32,26 | fehlt | 2,54 | -2,54 |

Nach Umsetzung der Regelmatrix und nach der sevDesk-Korrektur des CZ-Falls:

Kalter Live-Lauf mit Projekt-venv und nativer Windows-TLS-Kette nach
Parallelisierung der Positionsabrufe: 16,775 Sekunden, 760 geladene Dokumente,
657 ausgeschlossen.

| Land/Satz | Live Netto | Soll Netto | Delta Netto | Live Steuer | Soll Steuer | Delta Steuer |
|---|---:|---:|---:|---:|---:|---:|
| CZ 0 % | 34,80 | 34,80 | 0,00 | 0,00 | 0,00 | 0,00 |
| DE 7 % | 4.004,51 | 4.036,26 | -31,75 | 284,79 | 286,04 | -1,25 |
| IT 4 % | 599,95 | 599,95 | 0,00 | 24,05 | 24,05 | 0,00 |
| NL 9 % | 269,97 | 269,97 | 0,00 | 24,33 | 24,33 | 0,00 |
| FR 5,5 % | 147,49 | 147,49 | 0,00 | 8,11 | 8,11 | 0,00 |

Ein Hinweis bleibt: Bei `RE-261669` wurde der Dokumentkopf genutzt, weil die
Positionssumme nicht zum Belegkopf passt. Das ist jetzt sichtbar und nicht mehr
still.

Der aktuelle Export erzeugt fuer Q1 fuenf und fuer Q2 vier XML-Zeilen. Die
lokale Funktion `validate_oss_xml()` akzeptiert beide Dateien. Diese Aussage
bedeutet nur, dass das XML wohlgeformt ist und die drei lokal geprueften
Kopffelder enthaelt; sie beweist keine Portal- oder XSD-Konformitaet.

## 4. Belegte Ursachen

### 4.1 Dokument-/Positionskonflikte

Die Berechnung verwendet Positionen, sobald `xw_positions` vorhanden ist. Der
Dokumentkopf wird dann nicht zur Summenabstimmung herangezogen. Historische oder
unvollstaendige Positionen koennen deshalb einen korrekten Dokumentkopf
ueberschreiben.

Belegte beziehungsweise gepruefte Beispiele:

- `RE-261440`: Dokumentkopf LU 3 %, netto 30,87 EUR, Steuer 0,93 EUR, brutto
  31,80 EUR. Nach erneutem Live-Drill-down stimmen die zwei Positionen
  inzwischen exakt mit dem Kopf ueberein; daraus folgt kein klarer Fix mehr.
- `RE-261181`: Dokumentkopf IT 4 %, netto 10,58 EUR, Steuer 0,42 EUR, brutto
  11,00 EUR. Nach erneutem Live-Drill-down stimmen die zwei Positionen
  inzwischen exakt mit dem Kopf ueberein; daraus folgt kein klarer Fix mehr.
- `RE-261935`: Dokumentkopf/Brutto 34,80 EUR und TaxSet CZ; geladene Positionen
  liefern nach Anwenderkorrektur 34,80 EUR netto und 0,00 EUR Steuer. Die neue
  Regelmatrix uebernimmt diesen echten 0-%-Fall.

### 4.2 Steuersatz aus Text hat unbedingten Vorrang

`_resolve_rate()` uebernimmt zuerst jeden Prozentsatz aus `taxText`. Ein
Textwert 0 % verhindert damit die Ableitung aus Netto/Steuer. Gleichzeitig
verwirft die Aggregation alle Saetze `<= 0`. Bei widerspruechlichen Daten gibt
es keinen strukturierten Fehlerstatus und keine Abgabesperre.

Umsetzung 12.07.2026: Dieses Verhalten wurde durch eine versionierte
sevDesk-Regelmatrix ersetzt. Bekannte OSS-Regeln werden positiv zugeordnet;
bekannte Nicht-OSS-Regeln werden explizit ausgeschlossen; unbekannte
auslaendische USt-Regeln werden mit Belegnummer gemeldet und nicht still
uebernommen. Echte 0-%-Regeln sind erlaubt, aber 0 % plus positiver
Steuerbetrag wird blockierend gemeldet.

### 4.3 Historische TaxSet-/TaxText-Luecken

Der OSS-Provider besitzt im Gegensatz zur UVA keinen TaxSet-Text-Cache und
keinen Lookup fuer leere historische `taxText`-Felder. Mehrere Q1-Dokumente
weisen am Dokumentkopf leere Texte oder fehlende TaxSet-Metadaten auf. Das ist
ein plausibler Mechanismus fuer nicht erkannte Zeilen, ist fuer DE/EE/ES aber
noch nicht positionsgenau vollstaendig bewiesen. Deshalb darf daraus vor dem
Drill-down kein pauschaler Laufzeit-Fallback entstehen.

Umsetzung 12.07.2026: Wenn der sevDesk-Regeltext fehlt oder nur `0` lautet,
darf die Berechnung nur dann ueber Land/Satz ableiten, wenn die Kombination in
der versionierten OSS-Regelmatrix bekannt ist. Diese Ableitung erzeugt einen
Hinweis. Damit werden historische Luecken verarbeitet, ohne neue unbekannte
Regeln zu erraten.

### 4.4 Datumsabgrenzung ist nicht die Ursache

Ein kontrollierter Gegenlauf mit Rechnungsdatum statt Leistungsdatum ergab in
Q1 und Q2 exakt dieselben Aggregate. Die aktuellen Abweichungen duerfen daher
nicht durch einen Datumswechsel "korrigiert" werden.

### 4.5 sevDesk-USt-Regelmatrix

Die Filterung erfolgt jetzt in drei Stufen:

1. Exakte/normalisierte sevDesk-Regelbezeichnung aus
   `config/oss_tax_rules.json`;
2. kontrollierter Fallback ueber EU-Verbrauchsland und bekannten Satz aus
   derselben Matrix, nur bei fehlendem Regeltext;
3. Warnung und Ausschluss bei unbekannter auslaendischer Regel.

Die aktuell hinterlegten positiven OSS-Regeln sind:

| Land | Regel | Satz |
|---|---|---:|
| BE | Belgische TVA 6% | 6 % |
| ES | Spanische IVA 10% | 10 % |
| EE | Estnische KM 9% | 9 % |
| FI | Finnische ALV 14% | 14 % |
| DK | Daenische MOMS 25% | 25 % |
| SI | Slowenische DDV 9,5 % | 9,5 % |
| CZ | Tschechische DPH 0% (seit 2024) | 0 % |
| NL | Niederlaendische BTW 21% | 21 % |
| SE | Schwedische MOMS 6% | 6 % |
| LT | Litauische PVM 9% | 9 % |
| LU | Luxemburgische TVA 3% | 3 % |
| FR | Franzoesische TVA 5,5% | 5,5 % |
| DE | Deutsche MwSt. 19% | 19 % |
| DE | Deutsche MwSt. 7% | 7 % |
| NL | Niederlaendische BTW 9% | 9 % |
| IT | Italienische IVA 4% | 4 % |

Dokumentierte Ausschluesse:

- Steuerfreie innergemeinschaftl. Lieferung (EU);
- Steuerfreie Ausfuhrlieferung (§ 7 UStG 1994).

Wenn kuenftig eine zusaetzliche USt-Regel auftaucht, ist die beste
Vorgehensweise: TaxSet/TaxRule in sevDesk identifizieren, Land/Satz fachlich
gegen die aktuelle OSS-/VAT-Rate pruefen, die Regel in
`config/oss_tax_rules.json` ergaenzen und erst danach in der Berechnung
zulassen. Kein automatisches Raten anhand eines beliebigen fremden Textmarkers.

## 5. Fachlicher Sollzustand

EU-OSS erfasst grundsaetzlich die dafuer qualifizierten grenzueberschreitenden
B2C-Umsaetze und ordnet sie dem Mitgliedstaat des Verbrauchs zu. Erklaerung und
Zahlung erfolgen im Mitgliedstaat der Identifizierung. Die EU-OSS-Erklaerung
ist quartalsweise einzureichen; die Aufzeichnungen muessen die Steuerberechnung
nachvollziehbar tragen.

Fuer XW-Office bedeutet das:

- nur belegte EU-B2C-OSS-Umsaetze aufnehmen;
- AT, Export, innergemeinschaftliche B2B-Lieferung und Reverse Charge trennen;
- Verbrauchsland, Leistungsart, Bemessungsgrundlage, Satz und Steuer je Position
  revisionssicher festhalten;
- Gutschriften/Korrekturen mit Bezugsquartal und Referenzbeleg modellieren;
- keine Zeile aus widerspruechlichen Kopf-/Positionsdaten erzeugen;
- Golden Master vergleichen, niemals als Berechnungswert einsetzen.

Offizielle Grundlagen:

- [USP: Umsatzsteuer One-Stop-Shop](https://www.usp.gv.at/steuern-finanzen/umsatzsteuer/Umsatzsteuer-One-Stop-Shop.html)
- [USP: Erklaerung und Zahlung im EU-OSS](https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/Umsatzsteuer-One-Stop-Shop/EU-OSS/Erklaerung-und-Zahlung-im-EU-OSS.html)
- [EU-Kommission: OSS](https://vat-one-stop-shop.ec.europa.eu/index_en)
- [EU-Kommission: VAT rates](https://taxation-customs.ec.europa.eu/taxation/vat/vat-directive/vat-rates_en)
- [USP/BMF: Testanwendung fuer XML-Dateiupload](https://www.usp.gv.at/dam/jcr%3A2275a2bb-93cd-4ae1-be77-4fe37dda3d0a/Instructions%20for%20the%20test%20application.pdf)

## 6. XML-/Import-Audit

### Istzustand

Das XML wird frei mit `xml.etree.ElementTree` als `OSSReturn` aufgebaut:

- `ossId`, `year`, `quarter`;
- je Zeile `countryCode`, `goods`, `taxable`, `vatRate`, `taxAmount`;
- optional `uidFixedEst`.

Die lokale Validierung prueft nur:

- XML ist parsebar;
- Root-Tag ist `OSSReturn`;
- `ossId`, `year`, `quarter` sind vorhanden.

Nicht geprueft werden:

- offizielles und versionsrichtiges XSD;
- Namespace und vorgeschriebene Elementreihenfolge;
- Datentypen, Laengen und Wertevorrat;
- korrekte OSS-ID;
- Land/Satz-Kombination;
- Rundungs- und Vorzeichenregeln;
- Korrekturzeitraeume und feste Niederlassungen;
- Summenabstimmung;
- Nullmeldung;
- Portalantwort und Fehlercodes.

Die UI belegt das OSS-ID-Feld fallweise mit `hersteller_id`, sofern diese mit
`ATU` beginnt. Hersteller-ID, UID und OSS-Registrierungskennung duerfen nicht
ohne explizite fachliche Zuordnung vermischt werden.

### Erforderlicher Sollzustand

1. Offizielle, versionierte XML-Spezifikation und XSD als Konfigurations-/Asset-
   Abhaengigkeit hinterlegen.
2. XML ausschliesslich aus einem freigegebenen Quartalssnapshot erzeugen.
3. Vor Export Schema-, Wertevorrats-, Summen- und Fachvalidierung ausfuehren.
4. Konflikte wie CZ 0 % plus positiver Steuer als blockierend behandeln.
5. Eine echte OSS-ID-Konfiguration mit Formatpruefung einfuehren.
6. Exportdatei plus Snapshot-Hash, Regelversion und Validierungsbericht
   revisionssicher protokollieren.
7. Testdateien automatisiert gegen die offizielle Testanwendung pruefen; ein
   Portalupload bleibt ein expliziter manueller/autoriserter Schritt.

## 7. Performance-Audit

Der Provider laedt zuerst Quartalslisten und ruft danach fuer jedes Dokument
`InvoicePos` beziehungsweise `CreditNotePos` einzeln auf. Das erzeugt ein
N+1-Muster. Der In-Memory-Positionscache gilt nur fuer die aktuelle Instanz.
`build_xml_export()` berechnet das Quartal erneut, statt die sichtbare Vorschau
zu exportieren.

Gemessen:

- Q1 kalt: 138,339 Sekunden;
- Q2 kalt nach Q1 in derselben Instanz: 69,179 Sekunden;
- Diagnose-Vollabrufe: etwa 76 bis 156 Sekunden je Quartal;
- lokale Aggregation und XML-Erzeugung sind dagegen vernachlaessigbar.

Nach Umsetzung der begrenzten Parallelisierung fuer Positionsabrufe:

- Q1 kalt: 21,063 Sekunden bei 919 geladenen Dokumenten;
- Q2 kalt: 16,775 Sekunden bei 760 geladenen Dokumenten;
- Q2 liegt damit unter dem Zielwert von 20 Sekunden, Q1 knapp darueber;
- die Aggregationswerte blieben gegenueber dem seriellen Lauf stabil.

Nach Umsetzung des persistenten Quartalssnapshots:

- Q1 Refresh aus sevDesk: 20,906 Sekunden, Warmstart aus SQLite: 0,001 Sekunden;
- Q2 Refresh aus sevDesk: 16,537 Sekunden, Warmstart aus SQLite: 0,001 Sekunden;
- Vorschau und Export koennen denselben Snapshot-Hash verwenden.

Zielwerte:

- erster Quartals-Snapshot unter 20 Sekunden, soweit die API dies erlaubt;
- persistenter Warmstart unter 2 Sekunden;
- Vorschau zu XML ohne erneuten sevDesk-Vollabruf;
- exakt ein Snapshot-Hash fuer Vorschau, Vergleich und Export.

## 8. Umbauphasen

### Umsetzungsstand 12.07.2026

Abgeschlossen:

- Phase 0 teilweise: OSS-Referenzen werden ueber `load_oss_references()`
  unveraenderbar geladen und ueber `compare_oss_reference()` gegen
  Live-Ergebnisse verglichen;
- Phase 2 teilweise: bei unvollstaendigen oder abweichenden Positionen darf ein
  eindeutig klassifizierter Dokumentkopf als Fallback verwendet werden; der
  Fallback wird als Hinweis ausgegeben;
- Phase 3 teilweise: versionierte sevDesk-USt-Regelmatrix,
  bekannte 0-%-Regeln, unbekannte Regelwarnungen und kontrollierter
  Land/Satz-Fallback sind umgesetzt;
- Phase 5 teilweise: Positionsabrufe laufen begrenzt parallel
  (`max_position_workers=6`), der In-Memory-Positionscache ist fuer parallele
  Zugriffe abgesichert;
- Phase 5 erweitert: `OssQuarterSnapshotStore` speichert fertige
  Quartalsergebnisse persistent in `state/xw_office_cache.sqlite`; Warmstarts
  laufen ohne sevDesk-API-Zugriff;
- Phase 6 teilweise: XML-Export wurde von internem `OSSReturn` auf die
  BMF/USP-Portalstruktur `Erklaerungen/Erklaerung` mit `mscon`, `taxable`,
  `vatRate` und optionaler `goods`-/`uidFixedEst`-Angabe umgestellt; lokale
  XSD- und Duplikatvalidierung sind aktiv;
- Phase 7 teilweise: EU-OSS-UI zeigt Snapshot-Quelle/Hash, eine
  Soll-Ist-nahe Ergebnis-Tabelle und Drill-down auf die Belegnummern je
  Land/Satz/Art; Export nutzt den sichtbaren Snapshot, wenn Quartal/Jahr
  uebereinstimmen;
- Regressionstests fuer bekannte Regeln, 0-%-CZ, 0-%-Konflikt,
  Dokumentkopf-Fallback, unbekannte auslaendische Regeln, Referenzvergleich,
  parallele Positionsabrufe, persistenten Snapshot und XML-Validierung.

Noch offen:

- vollstaendiges positionsgenaues Auditmodell mit Ausschlussliste;
- Q1-Refresh liegt mit rund 21 Sekunden noch knapp ueber dem 20-Sekunden-Ziel;
- Portal-Testupload gegen die BMF-Testanwendung wurde fuer Q2/2026 erfolgreich
  durchgefuehrt. Ergebnis: `Datei wurde erfolgreich hochgeladen`.
- Das BMF-Testportal lehnt `vatRate 0,00` mit der Meldung
  `Das XML-File enthaelt den Steuersatz von 0,0%. Dies ist nicht erlaubt.` ab.
  Deshalb bleiben 0-%-Zeilen in der Berechnung sichtbar, werden aber nicht in
  das Portal-XML uebernommen; der Export meldet diesen Ausschluss explizit.
- UI-Drill-down fuer Referenzvergleich und Ausschlussliste;
- positionsgenauer Drill-down fuer die verbleibenden Q1/Q2-Deltas.

### Phase 0: Referenz- und Sicherheitsnetz

- unveraenderbare Q1-/Q2-Referenzen laden und schema-validieren;
- Vergleich pro Land, Satz und Leistungsart sowie Quartalssummen;
- Toleranz standardmaessig 0,01 EUR je gemeldeter Zeile;
- fehlende/unerwartete Zeilen und Kopf-/Positionskonflikte blockieren Export;
- Golden Master niemals in Live-Aggregate kopieren.

### Phase 1: Auditierbares Quartalsmodell

- `OssDocumentFact`, `OssPositionFact`, `OssClassificationDecision` und
  `OssQuarterSnapshot` einfuehren;
- Rohwert, normalisierter Wert, Datenquelle und Entscheidung je Feld speichern;
- Ausschlussgruende als Codes statt nur Zaehler erfassen;
- Drill-down von Aggregate zu Beleg und Position bereitstellen.

### Phase 2: Kopf-/Positionsabstimmung

- Positionssumme gegen Dokumentnetto, Steuer und Brutto abstimmen;
- Cent-Toleranz und Rundungsstrategie deklarativ festlegen;
- fehlende Positionssteuer nicht automatisch aus einem widerspruechlichen
  Textsatz erzeugen;
- bei belastbarer Dokumentsteuer und unvollstaendigen Positionen eine explizite,
  getestete Dokument-Fallback-Strategie verwenden;
- gemischte Saetze ohne belastbare Positionen blockieren.

### Phase 3: Klassifikation

- Land primaer aus Lieferadresse/Verbrauchsort, TaxText nur als kontrollierten
  Fallback verwenden;
- TaxSet-IDs zentral und versioniert auf Land/Satz/OSS-Art abbilden;
- leere historische TaxTexts ueber TaxSet-Metadaten anreichern;
- B2C/B2B, UID, Export, ICS, RC und AT explizit entscheiden;
- Waren/Leistungen positionsbezogen statt pauschal je Dokument bestimmen;
- reale Nullsaetze von Datenkonflikten trennen.

### Phase 4: Korrekturen und Gutschriften

- Bezugsrechnung, urspruengliches Quartal und Korrekturquartal speichern;
- Gutschriften nicht nur mit negativem Vorzeichen in das aktuelle Quartal werfen;
- Portalregeln fuer Berichtigungen versionsbezogen abbilden;
- fehlende Referenz als blockierenden Datenqualitaetsfehler behandeln.

### Phase 5: Persistenter Snapshot und Geschwindigkeit

- Quartals-Rohdaten einmal laden und persistent speichern;
- Positionen kontrolliert parallel/batchweise laden, Rate Limits beachten;
- inkrementelle Aktualisierung anhand Aenderungszeitpunkt;
- Vorschau, Referenzvergleich und XML aus demselben Snapshot;
- explizite Aktion "Neu aus sevDesk laden";
- Cache-Schema und Regelversion in den Hash aufnehmen.

### Phase 6: Offizieller XML-Exporter

- offizielles Schema/Namespace und Dokumentversion implementieren;
- Decimal-Werte ohne Float-Konvertierung ausgeben;
- feste Elementreihenfolge und Wertevorrat;
- XSD plus fachliche Cross-Checks;
- Dateiname, Encoding und Portalgrenzen testen;
- maschinenlesbarer Validierungsbericht;
- Export bei Abweichung oder Warnung mit Abgaberisiko sperren.

### Phase 7: UI

- Quartalsstatus: live/cached, Snapshot-Zeit, Hash, Regel-/XML-Version;
- Soll/Ist/Delta-Tabelle je Land/Satz/Art;
- Drill-down und Ausschlussliste;
- Datenqualitaet getrennt in blockierend und Hinweis;
- OSS-ID separat konfigurieren;
- erst freigegebenen Snapshot exportieren;
- keine automatische oder versteckte Portaluebermittlung.

## 9. Testplan

### Golden Master

- Q1/2026 und Q2/2026 unveraendert laden;
- jede Zeile und Quartalssumme vergleichen;
- absichtliche Mutation der Referenz im Speicher verhindern;
- fehlende, zusaetzliche und falsche Art/Satz-Zeilen erkennen.

### Berechnung

- `RE-261440`, `RE-261181` und `RE-261935` als Regressionen;
- Kopf=Positionen, Rundungsdifferenz, fehlende Positionen, gemischte Saetze;
- leeres TaxText mit/ohne TaxSet;
- Land aus Lieferadresse versus TaxText-Konflikt;
- echte 0-%-Zeile und unmoegliche 0-%-plus-Steuer-Zeile;
- Rechnung/Gutschrift und periodenfremde Korrektur;
- B2B/UID, AT, Export, ICS und Reverse Charge;
- Waren und Leistungen in einem Dokument;
- Quartalsgrenzen und Zeitzonen.

### XML

- Golden-Master-Snapshot zu erwarteter XML-Fixture;
- offizielles XSD positiv/negativ;
- Namespace, Reihenfolge, Dezimalformat, Vorzeichen und Maximalwerte;
- ungueltige OSS-ID;
- Nullquartal;
- feste Niederlassung;
- Portal-Testupload mit archivierter Antwort;
- Vorschau-Hash entspricht Export-Hash.

### Performance und Resilienz

- kalter und warmer Lauf Q1/Q2;
- App-Neustart mit persistentem Snapshot;
- 429, Retry-After, 500, Timeout und Teilfehler;
- Pagination ueber 1.000 Dokumente;
- abgebrochener Positionsabruf darf keinen freigegebenen Snapshot erzeugen;
- Doppelklick/Parallelstart wird dedupliziert.

## 10. Prioritaet und Definition of Done

Prioritaet:

1. Referenzvergleich und blockierende Datenqualitaet;
2. Kopf-/Positionsabstimmung;
3. positionsgenauer Diff fuer DE/EE/ES und alle unerwarteten Zeilen;
4. offizielles XML-Schema und OSS-ID;
5. persistenter Quartalssnapshot;
6. Drill-down-UI;
7. autorisierter Portal-Testupload.

Fertig ist der Umbau erst, wenn:

- Q1 und Q2 ohne Override innerhalb der festgelegten Cent-Toleranz liegen oder
  jede verbleibende Differenz explizit fachlich bestaetigt ist;
- kein Kopf-/Positionskonflikt unbemerkt exportiert wird;
- Vorschau und XML denselben Snapshot verwenden;
- das XML gegen die offizielle Spezifikation und Testanwendung bestanden hat;
- OSS-ID und Hersteller-ID getrennt sind;
- kalter/warm persistenter Lauf die Zielwerte erreicht;
- ein Export nur bei vollstaendiger, reproduzierbarer Datenqualitaet moeglich ist.

## 11. Offene, nicht zu erratende Punkte

- Welche Einzelbelege erklaeren die restlichen DE-Deltas Q1/Q2 sowie EE und ES?
- Sind alle Umsaetze Waren, oder existieren OSS-Dienstleistungen/feste
  Niederlassungen?
- Welche konkrete OSS-Registrierungskennung ist fuer den Portalimport zu nutzen?
- Welche offizielle XML-Version akzeptiert das Portal fuer Q1/Q2 2026?

Diese Punkte muessen durch Drill-down, Portalunterlagen oder fachliche
Bestaetigung geklaert werden. Sie duerfen nicht durch pauschale Sonderregeln
oder Golden-Master-Overrides kaschiert werden.
