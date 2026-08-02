# UVA und ZM/U13 in PySide6: Gesamtanalyse, Live-Tests und Umbauplan

Stand: 12.07.2026
Ziel: ein fachlich sauberes, schnelles und Ã¼bersichtliches Modul `Steuern > UVA / ZM` in XW-Office
Status dieses Dokuments: Analyse, Umsetzungsplan und laufende Umbaudokumentation. Die Vorgaben vom 12.07.2026 sind eingearbeitet: ZM/U13 bleibt eine Soll-Berechnung rein nach Rechnungsdatum bzw. Gutschriftdatum; `status >= 100` bleibt bewusst die Mandantenregel.

## 1. Management Summary

Die UVA ist nach der zuletzt korrigierten Behandlung von `creditDebit=D`-Belegen fÃ¼r 06/2026 betragsmÃ¤ÃŸig sehr nahe am Golden Master:

| Ergebnis | PySide6 live | Golden Master | Differenz |
|---|---:|---:|---:|
| UVA-Zahllast 06/2026 | 1.910,30 EUR | 1.910,22 EUR | +0,08 EUR |

Die groÃŸen Kennzahlen A022, A029 und A006 sowie B070/B072 und C065 stimmen exakt. Abweichungen bestehen noch bei A017, A057/C066 und C060. A057/C066 neutralisieren sich bei voller Gegenbuchung in der Zahllast; C060 erklÃ¤rt die verbleibenden 0,08 EUR.

Fachlich ist die Berechnung trotzdem noch nicht allgemein abgabesicher. Sie basiert auf Text-/TaxSet-Heuristiken, einer vereinfachten Kennzahlenmatrix, einem Best-Effort-Zahlungsabgleich und nicht versionierten U30-Regeln. Die gute Ãœbereinstimmung eines Monats darf daher nicht mit allgemeiner Korrektheit gleichgesetzt werden.

Die ZM/U13 liefert fÃ¼r 06/2026 vier UID-Zeilen Ã¼ber insgesamt 2.399 EUR. Ihre Grundstruktur â€“ Sollprinzip nach Rechnungsdatum, Gruppierung je UID und GeschÃ¤ftsart, ganzzahlige kaufmÃ¤nnische Rundung und U13-XML â€“ ist die fachliche Zielrichtung fÃ¼r XW-Office. Die Mandantenregel lautet ausdrÃ¼cklich: `status >= 100` bleibt zulÃ¤ssig.

- eine komplette Rechnung erhielt bisher genau eine GeschÃ¤ftsart;
- der Nettobetrag kommt aus der Dokumentgesamtsumme statt aus ZM-relevanten Positionen;
- 96 Contact-Einzelabfragen erzeugen einen deutlichen N+1-Effekt;
- UID-PrÃ¼fung kontrolliert nur das Format/PrÃ¼fziffernmodell, nicht den qualifizierten Status zum Lieferzeitpunkt.

Performance ist aktuell der grÃ¶ÃŸte Bedienungsmangel:

- kalte UVA: 123â€“124 Sekunden, 907 API-Aufrufe;
- warme UVA in derselben Serviceinstanz: 10 Sekunden, 20 API-Aufrufe;
- ZM zusÃ¤tzlich: 12,3 Sekunden, 98 API-Aufrufe;
- ein erster kombinierter UVA+ZM-Lauf liegt damit bei ungefÃ¤hr 135 Sekunden.

Das Zielbild ist ein gemeinsamer Monats-Snapshot: Dokumente, Positionen, Zahlungen, Kontakte und Steuermetadaten werden einmal geladen, persistent gehasht und anschlieÃŸend von UVA und ZM gemeinsam verwendet. Zielwerte: kalter kombinierter Lauf unter 20 Sekunden, warmer Lauf unter 2 Sekunden, typischerweise weniger als 50 API-Aufrufe.

## 2. Analysierter Ist-Zustand

### 2.1 Komponenten

UVA:

- `src/xw_office/services/finanzonline/uva_preview.py`
  - sevDesk-Kandidaten, Zahlungsmetadaten, Positionen und Steuergruppen
- `src/xw_office/services/finanzonline/uva_selection.py`
  - IST-Auswahl und Teilzahlungsquoten
- `src/xw_office/services/finanzonline/uva_payload_service.py`
  - Ãœberleitung der Gruppen auf U30-Kennzahlen und Zahllast
- `src/xw_office/services/finanzonline/uva_models.py`
  - derzeit nur ein Teil der U30-Kennzahlen
- `src/xw_office/services/finanzonline/u30_xml.py`
  - XML und XSD-Validierung

ZM:

- `src/xw_office/services/finanzonline/zm_service.py`
  - Rechnungsauswahl, UID-PrÃ¼fung, Art, Gruppierung und Rundung
- `src/xw_office/services/finanzonline/u13_xml.py`
  - U13-XML und XSD-Validierung
- `src/xw_office/services/finanzonline/uva_service.py`
  - gekoppelte Berechnung und Abgabe: zuerst U30, anschlieÃŸend U13

UI:

- `src/xw_office/ui/modules/taxes/view.py`
  - gemeinsamer UVA-Berechnen-Button, UVA- und ZM-Textfelder, Fortschritt und kombinierte Abgabe

### 2.2 Positiver Bestand

- Vorschau und U30-Payload nutzen denselben `UvaPayloadService`.
- GeldbetrÃ¤ge werden mit `Decimal` und expliziter Rundung verarbeitet.
- Fremdsteuer-/OSS-nahe Gruppen werden sichtbar aus der AT-UVA ausgeschlossen.
- ErlÃ¶sseitige `creditDebit=D`-Belege werden inzwischen berÃ¼cksichtigt.
- Gutschriften werden auf der Ausgangsseite negativ verarbeitet.
- ZM gruppiert getrennt nach UID und Art (`delivery`, `service`, `dreieck`).
- U13 verwendet `SOLEI=J` bzw. `DREIECK=J` entsprechend der BMF-Struktur.
- U30 und U13 werden vor FileUpload gegen XSD validiert.
- Eine fehlerhafte UID blockiert derzeit die ZM-Abgabe.
- UI-Jobs laufen auÃŸerhalb des GUI-Threads.

## 3. Live-Test 06/2026

Testbedingungen:

- echter sevDesk-Datenbestand;
- reine Lese- und BerechnungslÃ¤ufe;
- keine Ãœbermittlung an FinanzOnline;
- identische Periode 06/2026;
- Messung auf dem aktuellen Entwicklungsrechner und Netzwerk;
- Zeiten sind Momentaufnahmen, aber die Request-Verteilung ist strukturell aussagekrÃ¤ftig.

### 3.1 UVA-Ergebnis

| KZ | PySide6 live | Golden Master | Delta |
|---|---:|---:|---:|
| A017 | 3.668,46 | 3.534,30 | +134,16 |
| A022 | 3.349,56 | 3.349,56 | 0,00 |
| A029 | 4.585,57 | 4.585,57 | 0,00 |
| A006 | 9.216,97 | 9.216,97 | 0,00 |
| A057 | 17,53 | 12,12 | +5,41 |
| B070 | 592,02 | 592,02 | 0,00 |
| B072 | 592,02 | 592,02 | 0,00 |
| C060 | 416,38 | 416,46 | -0,08 |
| C065 | 118,40 | 118,40 | 0,00 |
| C066 | 17,53 | 12,12 | +5,41 |
| D090 | 0,00 | 0,00 | 0,00 |
| **Zahllast** | **1.910,30** | **1.910,22** | **+0,08** |

Die bestÃ¤tigte Mandantenregel von 20 % fÃ¼r KZ 065 sowie KZ 057/066 bleibt Vorgabe. Der Unterschied A057/C066 ist eine Auswahl-/Basendifferenz, keine Aufforderung zur Ã„nderung des Satzes.

Mehrmonatsvergleich nach Speicherung der Golden Master fuer 04/2026 bis 06/2026:

| Monat | PySide6 live | Golden Master | Delta | Datenqualitaet |
|---|---:|---:|---:|---|
| 04/2026 | 267,60 | 267,60 | 0,00 | innerhalb Toleranz |
| 05/2026 | 997,31 | 1.000,57 | -3,26 | blockiert |
| 06/2026 | 1.910,30 | 1.910,22 | +0,08 | pruefen, innerhalb Toleranz |

Konsequenz im Code: Monate mit Golden-Master-Abweichung ausserhalb 0,10 EUR werden nicht als abgabebereit behandelt und nicht an FinanzOnline uebermittelt.

### 3.2 ZM-Ergebnis

- betrachtete Rechnungen und Gutschriften: 140
- als ZM-relevant klassifiziert: 15
- gÃ¼ltige UID-/Art-Zeilen: 4
- Gesamtsumme nach Rundung: 2.399 EUR
- ungÃ¼ltige UID: 0
- eine auf 0 EUR gerundete Zeile wurde verworfen
- alle vier ausgegebenen Zeilen waren `delivery`

Gemeldete UID-Summen:

| UID | Art | Betrag | Rechnungen |
|---|---|---:|---:|
| DE216810359 | Lieferung | 538 | 2 |
| DE252010133 | Lieferung | 282 | 1 |
| DE330576993 | Lieferung | 285 | 1 |
| DE815104731 | Lieferung | 1.294 | 9 |

Diese Zahlen sind ein technischer Live-Befund, noch kein steuerlich bestÃ¤tigter Golden Master.

### 3.3 Performanceprofil

Kalter UVA-Lauf:

| Endpoint-Gruppe | Requests | kumulierte Wartezeit |
|---|---:|---:|
| Invoice | 578 | 80,98 s |
| InvoicePos | 149 | 18,78 s |
| Voucher | 117 | 14,99 s |
| VoucherPos | 57 | 7,25 s |
| CreditNote | 4 | 0,48 s |
| TaxSet | 2 | 0,14 s |
| **Gesamt** | **907** | **ca. 123,0 s** |

ZM nach UVA:

| Endpoint-Gruppe | zusÃ¤tzliche Requests |
|---|---:|
| Invoice | 1 |
| CreditNote | 1 |
| Contact | 96 |
| **Gesamt** | **98** |

ZM-Laufzeit: 12,35 Sekunden.

Warm-Cache-Test derselben UVA-Serviceinstanz:

| Lauf | Zeit | neue Requests | Zahllast |
|---|---:|---:|---:|
| kalt | 124,39 s | 907 | 1.910,30 EUR |
| warm | 10,05 s | 20 | 1.910,30 EUR |

Nach der ersten Umsetzungsstufe vom 12.07.2026:

| Lauf | Zeit | Datenquelle | Zahllast | ZM |
|---|---:|---|---:|---:|
| kalt | 136,24 s | sevDesk live + Snapshot schreiben | 1.910,30 EUR | 4 Zeilen / 2.399 EUR |
| warm | 0,00 s | App-Monatscache | 1.910,30 EUR | 4 Zeilen / 2.399 EUR |
| App-Neustart | 0,002 s | persistenter Monats-Snapshot | 1.910,30 EUR | 4 Zeilen / 2.399 EUR |

Interpretation:

- Die In-Memory-Caches funktionieren fÃ¼r Positionen und Zahlungsdetails.
- Der neue App-Monatscache verhindert erneute Live-Abfragen nach einer Vorschau und wird auch fÃ¼r den U30-/U13-Sendepfad genutzt.
- Der persistente Monats-Snapshot Ã¼berlebt einen App-Neustart und ist Ã¼ber einen SHA-256-Hash referenzierbar.
- Der erste Benutzerlauf bleibt unvertretbar langsam und benÃ¶tigt weiterhin den persistenten Snapshot/inkrementellen Loader.
- Der kalte Live-Lauf bleibt langsam, weil der zugrunde liegende sevDesk-Loader noch viele Dokument-/Positions-/Zahlungsabfragen ausfÃ¼hrt.
- Listen-/Overlay-Abfragen werden innerhalb derselben Serviceinstanz nicht mehr erneut ausgefÃ¼hrt, sobald der Monatscache gefÃ¼llt ist.
- UVA und ZM teilen Kontakte und Dokumentlisten nicht.

## 4. Fachliche Leitplanken aus PrimÃ¤rquellen

### 4.1 UVA

- Die UVA ist eine Selbstberechnung fÃ¼r den Voranmeldungszeitraum; die Vorauszahlung ist grundsÃ¤tzlich am 15. des zweitfolgenden Monats fÃ¤llig. Quelle: RIS, Â§ 21 UStG.
  https://ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004873&Paragraf=21
- Bei Istbesteuerung entsteht die Ausgangssteuerschuld grundsÃ¤tzlich im Monat der Bezahlung; Anzahlungen sind eingeschlossen. Quelle: USP/BMF.
  https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/entstehen-der-steuerschuld-und-pflichten/zeitpunkt-des-entstehens-der-steuerschuld.html
- FÃ¼r bestimmte Istbesteuerer ist auch der Vorsteuerabzug an die Zahlung geknÃ¼pft. Quelle: USP/BMF.
  https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/vorsteuerabzug.html
- MaÃŸgeblich sind die U30- und U30a-Versionen des jeweiligen Jahres. Quelle: BMF Formularservice.
  https://service.bmf.gv.at/service/anwend/formulare/show_mast.asp?s=U30
- Ab 07/2026 Ã¤ndern sich Dokument-/PrÃ¼fregeln und Kennzahlen. Die Regelengine muss deshalb periodenversioniert sein. Quelle: BMF.
  https://www.bmf.gv.at/dam/jcr%3A922a2cf9-e758-40c4-a671-1674044cced1/BMF_Dokumentenversion_UVA%20ab_07_2026.pdf

### 4.2 ZM/U13

- ZM-pflichtig sind innergemeinschaftliche Warenlieferungen sowie bestimmte im Ã¼brigen Gemeinschaftsgebiet steuerpflichtige sonstige Leistungen, fÃ¼r die der EmpfÃ¤nger nach Art. 196 MwSt-RL die Steuer schuldet. Quelle: RIS, Art. 21 UStG-Binnenmarkt.
  https://ris.bka.gv.at/NormDokument.wxe?Abfrage=Bundesnormen&Artikel=21&Gesetzesnummer=10004929
- FÃ¼r Warenlieferungen gilt grundsÃ¤tzlich der Meldezeitraum der Rechnung, spÃ¤testens der Monat nach AusfÃ¼hrung. FÃ¼r sonstige Leistungen nennt Art. 21 Abs. 7 den Zeitraum der LeistungsausfÃ¼hrung. FÃ¼r XW-Office gilt abweichend die bestÃ¤tigte Mandantenregel: ZM/U13 wird rein nach Rechnungsdatum bzw. Gutschriftdatum bestimmt, weil das der gewÃ¼nschten Soll-Auswertung und dem Legacy-Verhalten entspricht. Quelle fÃ¼r die allgemeine Rechtslage: RIS, Art. 21 Abs. 7.
- Dienstleistungen an Nichtunternehmer ohne UID sowie Leistungen auÃŸerhalb der B2B-Grundregel gehÃ¶ren nicht in die ZM. Quelle: USP/BMF.
  https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/grenzueberschreitende-dienstleistungen.html
- Die Steuerfreiheit innergemeinschaftlicher Lieferungen hÃ¤ngt auch an einer vollstÃ¤ndigen/richtigen ZM bzw. ordnungsgemÃ¤ÃŸer Berichtigung. Quelle: USP/BMF.
  https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/ausfuhr-innergemeinschaftliche-lieferung.html
- BMF U13 verlangt UID_MS, SUM_BGL und gegebenenfalls `DREIECK=J` oder `SOLEI=J`; SUM_BGL ist die Summe je Erwerber und Art. Quelle: BMF, Allgemeines ZM, Stand 14.01.2025.
  https://www.bmf.gv.at/dam/jcr%3A9a7faa0a-2da5-466b-b01f-0658ff04289f/BMF_Allgemeines_Zusammenfassende_Meldung.pdf
- U13a beschreibt auch Korrekturen; eine Berichtigung muss auf die ursprÃ¼ngliche Meldung und WÃ¤hrung abgestimmt sein. Quelle: BMF U13a.
  https://formulare.bmf.gv.at/service/formulare/inter-steuern/pdfd/9999/u13a.pdf

## 5. Fachliche UVA-Befunde und Empfehlungen

### P0 â€“ Berechnung und Abgabe benÃ¶tigen einen vollstÃ¤ndigen Snapshot

Der aktuelle Lauf fragt live und dokumentweise ab. Ein Teilausfall kann zu unvollstÃ¤ndigen Gruppen fÃ¼hren, ohne dass ein formaler VollstÃ¤ndigkeitsstatus existiert.

Empfehlung:

- `UvaSourceSnapshot` mit Dokumenten, Positionen, Zahlungsereignissen, TaxSets, Abrufstatus und Hash;
- `complete`, `partial`, `failed` als explizite ZustÃ¤nde;
- nur `complete + validated` darf versendet werden;
- Vorschau und XML referenzieren dieselbe Snapshot-ID.

### P0 â€“ Zahlungsereignisse statt Best-Effort-Datumsfelder

`paidDate`, Status-Overlays und zwei Payment-Endpunkte werden gemischt. Das funktioniert fÃ¼r 06/2026 weitgehend, ist aber schwer beweisbar.

Empfehlung:

- kanonisches `PaymentLedger` je Dokument;
- Transaktions-ID, Buchungsdatum, Betrag, WÃ¤hrung, Quelle und Confidence;
- Teilzahlungen und RÃ¼ckzahlungen als einzelne Ereignisse;
- `paidDate` nur als dokumentierter Fallback;
- keine Auswahl allein nach Rechnungs-/Belegdatum im IST-Modus.

### P0 â€“ Typisierte Steuerfakten statt Textheuristik

Die Klassifikation nutzt Steuertexte, LÃ¤nderwÃ¶rter, TaxRule-/TaxSet-IDs und Steuersatzinferenz. Das ist nÃ¼tzlich zur Migration, aber zu fragil fÃ¼r eine Abgabe.

Empfehlung:

- versionierte TaxMapping-Tabelle;
- Richtung, Jurisdiktion, GeschÃ¤ftsart, AT-UVA-Relevanz, OSS-Relevanz, Satz und Zielkennzahl;
- unbekannte Kombination blockiert statt still `0 %` zu werden;
- Textheuristik nur als Vorschlag in einer Mapping-PrÃ¼fansicht.

### P0 â€“ Periodenversionierte U30-Regelengine

`UvaKennzahlen` enthÃ¤lt nur einen Ausschnitt; A000 und Zahllast werden hart codiert. Das bildet kÃ¼nftige und seltene FÃ¤lle nicht vollstÃ¤ndig ab.

Empfehlung:

- `U30_01_2022` fÃ¼r 06/2026 und `U30_07_2026` fÃ¼r Perioden ab 07/2026;
- amtliche Formeln und PlausibilitÃ¤tsprÃ¼fungen als ausfÃ¼hrbare Regeln;
- vollstÃ¤ndiges Modell aller im Mandanten mÃ¶glichen Kennzahlen;
- bestÃ¤tigte 20-%-Mandantenregel fÃ¼r 057/066/065 explizit testen;
- kein Versand bei verletzter BMF-PrÃ¼fbeziehung.

### P1 â€“ Restabweichungen 06/2026 auflÃ¶sen

Vor Produktivfreigabe sind positionsgenau zu erklÃ¤ren:

- A017: +134,16 EUR gegenÃ¼ber Golden Master;
- RC-Basis: PySide6 87,66 EUR gegenÃ¼ber Soll 60,62 EUR;
- C060: -0,08 EUR.

Erforderlicher Diff-Bericht:

- Dokument-ID und Nummer;
- Zahlungsdatum und Monatsanteil;
- Position, TaxSet/TaxRule, Netto und Steuer;
- Zielkennzahl;
- Beitrag Live versus Golden Master.

### P1 â€“ KZ-Semantik und UI-Bezeichnungen

Einige Texte bezeichnen SteuerbetrÃ¤ge als `[NETTO]`, insbesondere KZ 057/065/066. Die UI sollte strikt zwischen Bemessungsgrundlage und Steuerbetrag unterscheiden und die amtliche Semantik je Kennzahl anzeigen.

## 6. Fachliche ZM/U13-Befunde und Empfehlungen

### Mandantenregel â€“ Status >= 100 bleibt

`_is_final_status()` akzeptiert jede numerische Statuszahl ab 100. Das bleibt fÃ¼r diesen Mandanten bewusst so, weil die Legacy-nahe Soll-Auswertung genau diese Statusgrenze verwendet.

Empfehlung:

- Statusregel als Mandantenregel dokumentieren und testen;
- keine Umstellung auf eine strengere Finalstatusmatrix ohne neue fachliche Freigabe;
- Storno-/Korrekturverhalten separat sichtbar machen, ohne `status >= 100` pauschal zu ersetzen.

### Mandantenregel â€“ ZM-Periode nach Rechnungsdatum

Aktuell wird fÃ¼r Lieferung, sonstige Leistung und DreiecksgeschÃ¤ft das Rechnungsdatum verwendet. Das bleibt die Zielregel.

Empfehlung:

- Rechnung: `invoiceDate`;
- Gutschrift: `creditNoteDate`;
- UI und Preview nennen dauerhaft `Berechnungsart: Soll (Rechnungsdatum)`;
- keine artabhÃ¤ngige Periodenlogik implementieren, solange diese Mandantenregel gilt;
- Gutschrift/Korrektur weiterhin mit Referenz auf ursprÃ¼ngliche Art und UID prÃ¼fen.

### P0 â€“ Positionsebene statt Gesamtrechnung

`pick_net()` Ã¼bernimmt `sumNet` der gesamten Rechnung. Bei gemischten Rechnungen kann dadurch ein nicht ZM-pflichtiger Anteil mitgemeldet werden. Eine Rechnung kann derzeit nur eine Art besitzen.

Empfehlung:

- Positionen laden und je Position klassifizieren;
- mehrere Arten pro Rechnung zulassen;
- Versand, Rabatt und Rundungspositionen sachgerecht verteilen;
- Summe der ZM-Fakten gegen Rechnungsnetto plausibilisieren;
- nur relevante Bemessungsgrundlagen je UID und Art aggregieren.

### P0 â€“ UID-Nachweis

`python-stdnum` prÃ¼ft Format/PrÃ¼fziffer. Das belegt nicht, dass die UID zum Leistungszeitpunkt gÃ¼ltig und dem Kunden zugeordnet war.

Empfehlung:

- qualifizierte UID-BestÃ¤tigung/VIES-Ergebnis mit Zeitstempel speichern;
- Firmenname/Adresse und UID-Abweichungen anzeigen;
- Cache mit fachlich definierter GÃ¼ltigkeit;
- Netzfehler nicht als â€žUID ungÃ¼ltigâ€œ behandeln;
- Offline-FormatprÃ¼fung und Online-Status getrennt modellieren.

### P1 â€“ Rundung, Null- und Negativzeilen

Die Rundung erst nach Aggregation je UID und Art auf ganze Euro ist grundsÃ¤tzlich plausibel und entspricht der U13-Struktur. Zu spezifizieren sind:

- negative Gesamtsumme nach Gutschrift;
- auf 0 gerundete, aber fachlich relevante Korrektur;
- getrennte Berichtigungsmeldung versus laufende Meldung;
- WÃ¤hrung und Umrechnungskurs;
- Reproduzierbarkeit des Rundungsschritts.

### P1 â€“ Abstimmung UVA â†” ZM

UVA und ZM haben bewusst unterschiedliche Periodenlogiken; dennoch mÃ¼ssen kontrollierbare Beziehungen bestehen.

Empfehlung:

- A017-Fakten gegen ZM-Lieferungsfakten abstimmen;
- A021/sonstige Leistungen gegen `SOLEI` abstimmen;
- Differenzen nach Zahlungs-/Rechnungs-/Leistungsperiode erklÃ¤ren;
- kein pauschaler Gleichheitszwang;
- eigene Abstimmliste â€žnur UVAâ€œ, â€žnur ZMâ€œ, â€žbeide, andere Periodeâ€œ.

## 7. Performance-Umbau

### 7.1 Hauptursachen

1. Pro Kandidat bis zu zwei Zahlungsabfragen.
2. Pro ausgewÃ¤hltem Dokument eine Positionsabfrage.
3. ZM fragt Kontakte einzeln nach.
4. UVA und ZM laden Ã¼berlappende Rechnungen unabhÃ¤ngig.
5. Caches sind nur instanzlokal und nicht persistent.
6. Ein erneuter Listenlauf findet auch im Warmfall statt.
7. API-Aufrufe sind weitgehend seriell; unkontrollierte ParallelitÃ¤t wÃ¤re wegen Rate Limits aber ebenfalls falsch.

### 7.2 Empfohlene Datenpipeline

```text
Monat wÃ¤hlen
  -> Snapshot-Metadaten prÃ¼fen
  -> geÃ¤nderte Dokumente seit letztem Sync laden
  -> Positionen/Zahlungen/Kontakte begrenzt parallel nachladen
  -> Snapshot atomar speichern und hashen
  -> UVA-Fakten berechnen
  -> ZM-Fakten berechnen
  -> Kreuzabstimmung
  -> UI aus lokalem Resultat rendern
```

### 7.3 Konkrete MaÃŸnahmen

- persistenter SQLite/PostgreSQL-Cache oder Repository im bestehenden DB-Schema;
- Cache-Key aus Ressource, ID und `update`-Marker;
- negative Cache-EintrÃ¤ge mit kurzer TTL;
- gemeinsame Contact-Map fÃ¼r ZM;
- gemeinsame Invoice-/CreditNote-Liste fÃ¼r UVA und ZM;
- Positionen nur bei geÃ¤ndertem Dokument neu laden;
- Zahlungslogs inkrementell Ã¼ber Update-/Buchungszeitraum synchronisieren;
- maximal 4â€“6 parallele GETs mit zentralem Rate-Limiter;
- Request-Deduplizierung (â€žsingle flightâ€œ) bei identischen gleichzeitigen GETs;
- Snapshot-Berechnung lokal und ohne Netzwerk wiederholbar;
- â€žDaten aktualisierenâ€œ getrennt von â€žBerechnung neu anzeigenâ€œ.

### 7.4 Performance-Ziele

| Szenario | Ist | Ziel |
|---|---:|---:|
| UVA kalt | 123â€“124 s / 907 Requests | < 20 s / < 50 Requests |
| UVA warm | 10 s / 20 Requests | < 2 s / 0â€“5 Requests |
| ZM | 12,3 s / 98 Requests | < 2 s warm; < 5 s kalt |
| UVA + ZM erster Lauf | ca. 135 s | < 20 s |
| lokale Neuberechnung aus Snapshot | nicht vorhanden | < 0,5 s |

Die Ziele mÃ¼ssen mit realem Rate Limit validiert werden. Weniger Requests ist wichtiger als aggressive Parallelisierung.

## 8. Ziel-UI

### 8.1 Struktur

Empfohlen wird ein gemeinsamer Steuerarbeitsbereich mit drei Ansichten:

1. `UVA / U30`
2. `ZM / U13`
3. `Abstimmung & DatenqualitÃ¤t`

Kopfbereich fÃ¼r alle Ansichten:

- Periode;
- Snapshot-Zeit und Datenstatus;
- Button `Daten aktualisieren`;
- Button `Lokal neu berechnen`;
- Statuschip `unvollstÃ¤ndig`, `prÃ¼fen`, `abgabebereit`;
- Laufzeit und Requestzahl des letzten Updates.

### 8.2 UVA-Ansicht

- groÃŸe Zahllast/Gutschrift;
- Kennzahlentabelle mit Betrag, Typ (Basis/Steuer), Delta zum Golden Master/Vormonat;
- Klick auf Kennzahl Ã¶ffnet Beleg-/PositionsbeitrÃ¤ge;
- Warnungen gruppiert nach blockierend, Betragseinfluss und Information;
- OSS/Fremdsteuer separat, nicht nur als Textwarnung;
- Golden Master als Vergleich, niemals als ErgebnisÃ¼berschreibung.

### 8.3 ZM-Ansicht

- UID, Kunde, Art, ungerundete Summe, Meldebetrag und Beleganzahl;
- aufklappbare Rechnungen/Positionen;
- UID-Formatstatus und qualifizierter BestÃ¤tigungsstatus getrennt;
- Leistungs-/Rechnungsdatum und verwendete Periodenregel sichtbar;
- Korrektur-/Gutschriftkennzeichnung;
- U13-XML-Vorschau und XSD-Status.

### 8.4 Abstimmungsansicht

- A017 gegen ZM-Lieferungen;
- A021/RC-Leistungen gegen SOLEI;
- GrÃ¼nde fÃ¼r Periodendifferenzen;
- unbekannte TaxSets;
- Zahlungen ohne Dokument;
- Dokumente ohne Positionen;
- Kontakte ohne gÃ¼ltige UID;
- Export als CSV/JSON fÃ¼r Steuerberatung.

## 9. Umsetzungsphasen

### Phase 0 â€“ Golden Masters und Rohsnapshot

- umgesetzt: 04/2026, 05/2026 und 06/2026 sind als unveraenderbare Referenzdaten in `config/uva_reference_values.json` gespeichert;
- umgesetzt: Golden-Master-Werte werden nur verglichen, nie als Rechenergebnis verwendet;
- umgesetzt: Golden-Master-Deltas erscheinen im Payload/UI;
- umgesetzt: Zahllast-Abweichung ausserhalb 0,10 EUR blockiert die Abgabe;
- mindestens einen bestÃ¤tigten U13-Monat erfassen;
- pseudonymisierte Rohsnapshots erzeugen;
- positionsgenauen Diff-Report erstellen.

### Phase 1 â€“ gemeinsamer persistenter Snapshot

- Umgesetzt als erste konservative Stufe: `UvaService` hÃ¤lt pro App-Instanz einen Monatscache fÃ¼r die vollstÃ¤ndige UVA/ZM-Berechnung.
- Anzeige und spÃ¤terer U30-Submission-Payload verwenden dadurch dieselben berechneten Kennzahlen, wenn zuvor berechnet wurde.
- Die UI zeigt an, ob der Lauf live geladen oder aus dem Monatscache gelesen wurde.
- Die UI hat zusÃ¤tzlich `Neu aus sevDesk laden`, um den Monatscache bewusst zu erneuern.
- Umgesetzt: `TaxMonthlySnapshotStore` speichert vollstÃ¤ndige Monatsberechnungen persistent in `state/xw_office_cache.sqlite`.
- Umgesetzt: gespeicherte Snapshots enthalten einen stabilen SHA-256-Hash und werden nach App-Neustart in ca. 0,002 Sekunden geladen.
- Umgesetzt: Snapshot-Schema-Version verhindert, dass alte Snapshots ohne neue Referenz-/Datenqualitaetslogik verwendet werden.
- Noch offen: inkrementeller Rohdatenloader statt vollstÃ¤ndigem kaltem sevDesk-Neulauf.

- Dokument-, Positions-, Zahlungs-, Contact- und TaxSet-Modelle;
- inkrementeller Loader;
- VollstÃ¤ndigkeitsreport und Hash;
- lokale Wiederholbarkeit.

### Phase 2 â€“ UVA-Fakten und Regelversionen

- PaymentLedger;
- TaxFacts;
- umgesetzt: U30-Regelversion `U30_01_2022` bis 06/2026;
- umgesetzt: U30-Regelversion `U30_07_2026` ab 07/2026 als explizite Payload-/UI-Metadaten;
- BMF-PlausibilitÃ¤tsprÃ¼fungen.

### Phase 3 â€“ ZM-Fakten

- Statusregel bleibt Mandantenregel `status >= 100`;
- Meldezeitraum bleibt Mandantenregel Rechnungsdatum/Gutschriftdatum;
- umgesetzt: Positionsklassifikation wird bei headerseitig ZM-relevanten Belegen nachgeladen;
- umgesetzt: mehrere ZM-Arten pro Rechnung werden aus plausiblen Positionen aggregiert;
- umgesetzt: wenn Positionssumme und Dokumentnetto nicht plausibel zusammenpassen, verwendet ZM konservativ das Dokumentnetto und gibt einen Hinweis aus;
- UID-Nachweis;
- Gutschriften und Berichtigungen;
- U13-Golden Master.

### Phase 4 â€“ Kreuzabstimmung und UI

- UVA-/ZM-Abstimmdienst;
- umgesetzt: kompakte UVAâ†”ZM-Abstimmung im bestehenden UVA-Textbereich;
- umgesetzt: DatenqualitÃ¤tsstatus `abgabebereit`, `pruefen`, `blockiert`;
- umgesetzt: Snapshot-Quelle und Hash in der UI;
- umgesetzt: `submit_month()` laedt/berechnet zuerst den Monats-Payload und blockiert Uploads bei blockierender Datenqualitaet;
- umgesetzt: Golden-Master-Abweichungen ausserhalb Toleranz setzen Datenqualitaet auf `blockiert`;
- offen: eigene dreiteilige UI mit Drill-down-Tabellen;
- umgesetzt: U30-/U13-Versand verwendet den geprueften Monats-Payload/Snapshot statt einen zweiten unabhaengigen Rechenweg.

### Phase 5 â€“ Performance und Parallelbetrieb

- Requestbudget messen;
- umgesetzt: Cold-/Warm-/App-Neustart-Benchmarks;
- mindestens drei Monate gegen Altberechnung und Einreichungen;
- Fehler- und Rate-Limit-Tests;
- erst danach alten Rechenpfad entfernen.

## 10. Testmatrix

UVA:

- vollstÃ¤ndige/mehrfache Teilzahlung;
- Zahlung am Monatsrand und Zeitzone;
- RÃ¼ckzahlung, Storno und Gutschrift;
- `creditDebit=C` versus `D`;
- gemischte 10/13/20-%-Positionen;
- Export, ICS, ICA, RC und OSS;
- auslÃ¤ndische Vorsteuer;
- unbekanntes TaxSet;
- U30-Versionswechsel 06/2026 â†’ 07/2026;
- XSD und BMF-PrÃ¼fregeln.

ZM:

- Status `>= 100` als Mandantenregel;
- Rechnung mit abweichendem Leistungsdatum bleibt nach Rechnungsdatum;
- gemischte Lieferung und Service in einer Rechnung;
- DreiecksgeschÃ¤ft;
- Gutschrift im selben/spÃ¤teren Zeitraum;
- ungÃ¼ltige, inaktive und nicht erreichbare UID-PrÃ¼fung;
- negative und auf null gerundete Zeile;
- mehrere Arten je UID;
- Berichtigung einer frÃ¼heren ZM.

Performance/Resilienz:

- kalter/warm persistenter Cache;
- App-Neustart;
- HTTP 429/500 und Retry-After;
- Timeout einzelner Position/Kontakt/Zahlung;
- Pagination-Limit;
- DatenÃ¤nderung wÃ¤hrend Snapshot-Erfassung;
- paralleler Doppelklick;
- Abbruch und Wiederaufnahme.

## 11. Definition of Done

- UVA 06/2026 bleibt ohne Override innerhalb von 0,10 EUR zum bestÃ¤tigten Golden Master; die 0,08 EUR sind positionsgenau erklÃ¤rt oder korrigiert.
- A017 und RC-Abweichungen sind fachlich dokumentiert.
- Mindestens drei UVA-Monate stimmen mit eingereichten Werten Ã¼berein.
- Mindestens ein U13-Monat ist gegen eine bestÃ¤tigte Meldung geprÃ¼ft.
- ZM verwendet die bestÃ¤tigte Soll-Regel nach Rechnungsdatum/Gutschriftdatum und `status >= 100`.
- Gemischte ZM-Rechnungen werden positionsbezogen verarbeitet, sobald Positionsdaten im Snapshot vorhanden sind.
- Vorschau, XML und Versand verwenden denselben Monats-Payload/Snapshot.
- UnvollstÃ¤ndige Daten und unbekannte Mappings blockieren die Abgabe.
- kombinierter kalter Lauf < 20 Sekunden, warmer Lauf < 2 Sekunden.
- UI zeigt BetrÃ¤ge, DatenqualitÃ¤t, Drill-down und UVAâ†”ZM-Abstimmung Ã¼bersichtlich.

## 12. Priorisierte Empfehlung

Nicht zuerst die UI umgestalten. Der hÃ¶chste Nutzen entsteht in dieser Reihenfolge:

1. gemeinsamer persistenter Monats-Snapshot;
2. positionsgenauer Diff fÃ¼r die verbleibenden UVA-Abweichungen;
3. ZM-Statusregel und Rechnungsdatum-Regel als Mandantenlogik absichern;
4. ZM-Positionsebene vollstÃ¤ndig aus dem gemeinsamen Snapshot speisen;
5. periodenversionierte U30-Regeln;
6. gemeinsame Abstimmungs- und Drill-down-UI.

Damit werden fachliche Sicherheit und Geschwindigkeit gleichzeitig verbessert: Der Snapshot beseitigt die N+1-Abfragen, schafft Reproduzierbarkeit und liefert zugleich die Grundlage fÃ¼r verstÃ¤ndliche Belegnachweise in der OberflÃ¤che.

## 13. Nachanalyse 04/2026 und 05/2026: belegte C060-Ursache

Die Live-Beleganalyse hat die jeweilige C060-Abweichung vollstaendig und centgenau
erklaert. sevDesk liefert bei einzelnen Eingangsbelegen ein `payDate`, das vor dem
eigentlichen `voucherDate` liegt. Dadurch wurden zukuenftig datierte Belege in einer
frueheren UVA als Vorsteuer beruecksichtigt:

- 04/2026: zwei erst im Mai datierte Belege mit 47,15 EUR und 4,67 EUR Vorsteuer;
  Summe 51,82 EUR, exakt die C060-Abweichung.
- 05/2026: drei erst im Juni datierte Belege mit 99,83 EUR, 1,75 EUR und 27,62 EUR
  Vorsteuer; Summe 129,20 EUR, exakt die C060-Abweichung.

Umgesetzt ist eine Plausibilitaetssperre nur fuer Eingangsbelege: Liegt das
Belegdatum nach dem UVA-Monat, wird der Beleg trotz eines frueheren Zahlungsdatums
nicht beruecksichtigt und als Warnung ausgewiesen. Bereits vor dem UVA-Monat
datierte und im UVA-Monat bezahlte Belege bleiben entsprechend der IST-Logik
enthalten. Die noch offene Umsatzabweichung 05/2026 von 32,55 EUR ist nicht
eindeutig belegt und wurde deshalb nicht durch eine Sonderregel korrigiert.
