# UVA 06/2026: Testlauf, Fehleranalyse und Umbauplan

Stand: 12.07.2026  
Scope: `Steuern > UVA` in XW-Office (PySide6) gegen das Legacy-Modul in `C:\Users\bernh\GitHub\sevDesk`  
Wichtig: Es wurden ausschließlich Berechnungen gegen sevDesk ausgeführt. Es wurde nichts an FinanzOnline gesendet.

## 1. Kurzfazit

Der in XW-Office angezeigte Betrag von **42,18 EUR ist klar falsch**. Der Legacy-Wert von **1.910,22 EUR liegt nach Anwenderabgleich sehr nahe am echten Ergebnis** und ist deshalb der maßgebliche Referenzkorridor. XW unterschätzt die Zahllast um **1.868,04 EUR**.

Die Differenz ist rechnerisch nahezu vollständig erklärt: XW verliert gegenüber Legacy die Bemessungsgrundlagen **A022 = 3.349,56 EUR** und **A006 = 9.216,97 EUR**. Daraus fehlen **669,91 EUR Umsatzsteuer zu 20 %** und **1.198,21 EUR Umsatzsteuer zu 13 %**, zusammen **1.868,12 EUR**. Die C060-Abweichung von 0,08 EUR reduziert das Gesamtdelta auf exakt **1.868,04 EUR**. Die primäre Fehlerstelle liegt daher in Auswahl, Positionsaggregation oder Klassifikation der Ausgangsumsätze – nicht in KZ 057/065.

Trotzdem ist die XW-Berechnung noch nicht abgabesicher:

1. Der Datenbeschaffungsweg ist nicht vollständig identisch mit einer strikten IST-Zahlungszuordnung.
2. Teilzahlungen werden teilweise nur als Dokumentquote, nicht als Summe konkreter Zahlungsereignisse behandelt.
3. Steuerarten werden über Textfragmente, feste TaxSet-IDs und Steuersatz-Inferenz klassifiziert.
4. Die mandantenspezifisch bestätigte 20-%-Behandlung für KZ 057/066 und KZ 065 ist beizubehalten.
5. KZ 070/072 werden derzeit identisch befüllt; das ist fachlich und nach den BMF-Prüfregeln nicht allgemein korrekt.
6. Die Zahllast wird aus wenigen Kennzahlen hart codiert rekonstruiert, statt aus einer versionierten U30-Regelmatrix.
7. Es fehlt ein persistierter Monats-Snapshot mit Beleg- und Zahlungs-Audit, über den sich jeder Cent erklären lässt.

Empfehlung: Die Legacy-Berechnung für 06/2026 als Referenz verwenden und zuerst Ergebnisparität herstellen. Verbesserungen wie die Trennung von AT-UVA und OSS dürfen nur bleiben, wenn sie anhand konkreter Rechnungen nachweislich keine österreichisch UVA-pflichtigen 20-%-/13-%-Umsätze entfernen.

## 2. Reproduzierter Testlauf 06/2026

### 2.1 XW-Office

Ausgeführt wurde derselbe Service, den die PySide6-Oberfläche über `UvaService.calculate_month(2026, 6)` verwendet:

- `SevdeskUvaPreviewProvider`
- `UvaDocumentSelector`
- `UvaPreviewService`
- `UvaPayloadService`

Laufzeit des beobachteten Live-Laufs: ca. 135 Sekunden.

| Kennzahl | XW-Office |
|---|---:|
| A000 | 8.481,41 |
| A011 | 227,38 |
| A017 | 3.668,46 |
| A021 | 0,00 |
| A022 | 0,00 |
| A029 | 4.585,57 |
| A006 | 0,00 |
| A057 | 17,53 |
| B070 | 592,02 |
| B072 | 592,02 |
| C060 | 416,38 |
| C065 | 118,40 |
| C066 | 17,53 |
| **Zahllast** | **42,18** |

Auswahlstatistik:

| Bereich | betrachtet | gewählt | Teilzahlungen | Zahlung außerhalb | fehlender Zahlungsnachweis |
|---|---:|---:|---:|---:|---:|
| Ausgang | 149 | 138 | 0 | 5 | 6 |
| Eingang | 54 | 39 | 4 | 9 | 0 |

Bemerkenswerte Ausgangsgruppen:

- 10 % AT: netto 4.585,57 EUR / USt 458,21 EUR
- innergemeinschaftliche Lieferung: 3.668,46 EUR
- Ausfuhrlieferung: 227,38 EUR
- aus AT-UVA ausgeschlossen: deutsche 7 %, italienische 4 %, tschechische und niederländische Steuergruppen

Bemerkenswerte Eingangsgruppen:

- inländische Vorsteuer: 416,38 EUR
- innergemeinschaftlicher Erwerb: 592,02 EUR
- Reverse Charge: 87,66 EUR

### 2.2 Legacy-Modul

Ausgeführt wurden `PeriodRange.for_month(6, 2026)` und `UVAService.run(period)` aus `C:\Users\bernh\GitHub\sevDesk\UVA.py` im standardmäßigen `strict_cash_mode=True`.

Der erste Lauf lieferte wegen TLS-Fehlern eine **Null-UVA**, obwohl sämtliche API-Abfragen fehlgeschlagen waren. Das Modul protokollierte Netzwerkfehler, brach die Berechnung aber nicht zuverlässig ab. Für einen gültigen Vergleich wurde ausschließlich für den lokalen, lesenden Testlauf die TLS-Verifikation der Legacy-`requests.Session` an die funktionierende Umgebung angepasst. Diese Umgehung darf nicht als Produktivfix übernommen werden.

Laufzeit des gültigen Live-Laufs: ca. 249 Sekunden.

| Kennzahl | Legacy theoretisch | Delta XW minus Legacy |
|---|---:|---:|
| A000 | 21.183,64 | -12.702,23 |
| A011 | 227,38 | 0,00 |
| A017 | 3.656,56 | +11,90 |
| A021 | 147,60 | -147,60 |
| A022 | 3.349,56 | -3.349,56 |
| A029 | 4.585,57 | 0,00 |
| A006 | 9.216,97 | -9.216,97 |
| A057 | 18,02 | -0,49 |
| B070 | 592,02 | 0,00 |
| B072 | 592,02 | 0,00 |
| C060 | 416,46 | -0,08 |
| C065 | 118,40 | 0,00 |
| C066 | 18,02 | -0,49 |
| **Zahllast (theoretisch)** | **1.910,22** | **-1.868,04** |

Legacy-Audit:

- 138 Rechnungen, 0 Gutschriften, 42 Belege
- `LinkedPayments Quelle: fast_path`
- 65 offene/Entwurfsrechnungen ignoriert
- 3 stornierte Rechnungen ohne Monatszahlung ignoriert
- 11 Cancel-Checks per API
- 11.632 Dokumentkandidaten mit Zahlung außerhalb des Zeitraums ausgeschlossen
- **theoretische Zahllast 1.910,22 EUR**
- zusätzlicher `getTax`-Diagnosewert 41,75 EUR, der laut Anwender **nicht** den echten UVA-Zielwert repräsentiert
- XW gegen maßgeblichen Legacy-Referenzwert: **-1.868,04 EUR**

Der `getTax`-Diagnosewert ist für diesen Vergleich ungeeignet. Er bildet nicht dieselbe vollständige Kennzahlenlogik wie das theoretische Legacy-Ergebnis ab und darf weder Sollwert noch Optimierungsziel sein.

## 3. Was aus XW-Office beibehalten werden soll

### 3.1 AT-UVA und ausländische B2C-/OSS-Steuer trennen

XW schließt im Testmonat deutsche, italienische, tschechische und niederländische Steuergruppen aus der AT-UVA aus und meldet dies als Warnung. Das erklärt den größten Teil des Unterschieds zu den Legacy-Kennzahlen A006 und A022. Diese Trennung ist fachlich sinnvoll: Für Auslandsgeschäfte gilt grundsätzlich das Recht am steuerlichen Leistungsort; OSS-Umsätze gehören in die OSS-Erklärung und nicht allein wegen eines erkannten Prozentsatzes in österreichische Steuersatz-Kennzahlen.

Beibehalten, aber verbessern:

- nicht über sprachabhängige Marker wie `DEUTSCHE`, `IVA`, `BTW` entscheiden;
- stattdessen explizite TaxSet-/TaxRule-Konfiguration mit `jurisdiction`, `scheme`, `transaction_type` und `uva_code` verwenden;
- unbekannte Zuordnungen als **blockierenden Prüfpunkt**, nicht nur als Hinweis behandeln.

### 3.2 Eine Berechnung für Vorschau und Versand

`UvaService.calculate_month()` und `build_submission_payload()` greifen auf denselben Payload-Service zurück. Dieses Prinzip verhindert, dass UI und U30-Sendung verschiedene Rechenwege nutzen. Es muss erhalten bleiben; künftig sollen beide einen unveränderlichen `UvaCalculationResult` referenzieren.

### 3.3 Decimal und explizite Rundung

XW rechnet mit `Decimal` und `ROUND_HALF_UP`. Das ist besser als ein Float-basierter Endwert. Zu ändern ist der Rundungszeitpunkt: Beträge müssen auf der fachlich definierten Ebene gerundet werden (Zahlungsanteil/Steuerzeile/Kennzahl), nicht durch mehrfaches Quantisieren während Klassifikation und Aggregation.

### 3.4 Transparente Warnungen und getrennte ZM

Die gruppierten Warnungen und die sichtbare Trennung der ZM sind brauchbare UX-Verbesserungen. Warnungen müssen künftig Schweregrade, Dokumentreferenzen, Betragseinfluss und einen Status `offen/bestätigt/behoben` besitzen.

## 4. Fehler- und Risikohypothesen

### P0: XW-Auswahl ist nicht strikt zahlungsereignisbasiert

`SevdeskUvaPreviewProvider` lädt Dokumente sowohl nach Dokumentdatum als auch nach Zahlungsdatum und über Status-Overlays. Erst danach versucht `UvaDocumentSelector`, Zahlungsnachweise auszuwerten. Dieser Best-Effort-Weg kann einen Beleg zwar korrekt ausschließen, garantiert aber nicht, dass alle Zahlungen des Monats gefunden werden.

Besonders kritisch:

- API-Felder wie `paidDate` bilden bei mehreren Zahlungen oft nur einen Zustand oder ein Datum ab;
- der vollständige Monatsbetrag muss aus konkreten CheckAccount-Transaktionen/Logs bzw. belastbaren Payment-Links stammen;
- XW meldete bei Ausgangsrechnungen keine Teilzahlung, Legacy besitzt dagegen eine wesentlich ausführlichere Zahlungs-Map;
- Dokumente werden auch nach Dokumentdatum in die Kandidatenmenge gezogen, was die Semantik schwer prüfbar macht.

Umbau: Zahlungsereignisse zuerst laden, danach Dokumente über stabile IDs zuordnen. Kein Dokument darf allein aufgrund seines Rechnungs-/Belegdatums in eine IST-UVA gelangen.

### P0: Keine harte Vollständigkeits- und Fehlergrenze

Das Legacy-Modul demonstriert den gefährlichen Fehlerfall: Totalausfall der API kann als formal erfolgreiche Null-UVA erscheinen. XW wirft HTTP-Fehler im Regelfall sauberer, besitzt aber ebenfalls keinen fachlichen `completeness_status` für einen Monats-Snapshot.

Umbau: Berechnung nur `filing_ready=True`, wenn alle Pflichtquellen vollständig sind. API-Fehler, Pagination-Limit, abgebrochene Detailabfragen, unbekannte Steuercodes oder nicht zuordenbare Zahlungen blockieren die Abgabe.

### P0: Text- und Prozent-Inferenz entscheidet über Kennzahlen

In `uva_preview.py` werden Steuergruppen aus `taxText`, Textmarkern, TaxRule-/TaxSet-IDs und notfalls aus `vat/net` inferiert. Ein unbekannter Text kann so als Prozentsatz interpretiert werden. Legacy zeigt, wie gefährlich das ist: fremde 13-/20-%-Sätze landen in A006/A022.

Umbau: versionierte `TaxMapping`-Tabelle, beispielsweise:

| Feld | Beispiel |
|---|---|
| sevdesk_tax_set_id | `27267` |
| sevdesk_tax_rule_id | `3` |
| direction | purchase/sale |
| jurisdiction | AT/DE/IT/... |
| scheme | domestic/ICS/ICA/RC/OSS/export |
| tax_rate | 20.00 |
| base_u30_code | 070/072/... |
| tax_u30_code | 057/... |
| input_u30_code | 060/065/066/... |
| valid_from / valid_to | fachliche Versionierung |

Nicht zugeordnete Kombinationen dürfen nicht still zu `0 %` oder einem gerundeten Satz werden.

### Bestätigte Mandantenregel: 20 % für Erwerbsteuer und Reverse Charge

Für diesen Mandanten ist die dauerhafte 20-%-Berechnung für KZ 065 sowie KZ 057/066 ausdrücklich bestätigt. Sie ist **kein Fehlerkandidat für 06/2026** und darf beim Umbau nicht verändert werden. B070/B072/C065 sind in beiden Läufen identisch; Unterschiede in A057/C066 heben sich bei voller Gegenbuchung in der Zahllast auf.

Die BMF-Prüfungen verlangen eine konsistente Beziehung zwischen KZ 070/071 und den nach Steuersätzen gegliederten Erwerbskennzahlen; ab 07/2026 kommen weitere Kennzahlen hinzu. Für 06/2026 gilt noch die vorherige U30-Version. Eine einfache Gleichsetzung von 070 und 072 ist kein tragfähiges Modell.

Umbau:

- `acquisition_base_total` getrennt von steuersatzbezogenen Erwerbsbasen führen;
- tatsächlichen österreichischen Erwerbsteuersatz aus gemapptem Sachverhalt bestimmen;
- C065 mit der bestätigten 20-%-Mandantenregel berechnen;
- BMF-Prüfregeln je Formularversion als ausführbare Validierung abbilden.

### P0: Fehlende 20-%- und 13-%-Ausgangsumsätze

Dies ist die zentrale Fehlerhypothese. XW selektiert ebenso wie Legacy 138 Ausgangsrechnungen, bildet aber A022 und A006 mit null. Legacy enthält genau die fehlenden Basen 3.349,56 EUR zu 20 % und 9.216,97 EUR zu 13 %.

Vorrangig zu prüfen sind XWs Positionsaggregation, Dokument- versus Positions-Steuertext, Fremdsteuer-/OSS-Marker, Feldprioritäten für Netto/Steuer sowie die Overlay-Zusammenführung. Akzeptanz: Die **12.566,53 EUR fehlende Basis** muss vollständig auf konkrete Dokumentpositionen verteilt werden.

### P1: C060-Differenz von 0,08 EUR

XW weist 416,38 EUR, Legacy 416,46 EUR aus. Diese kleine Differenz ist für die Zahllast relevant und kann aus folgenden Ursachen stammen:

- 39 ausgewählte XW-Belege gegenüber 42 Legacy-Belegen;
- vier anteilig skalierte XW-Belege;
- unterschiedliche Zahlungsanteile oder Zahlungsdaten;
- Positionssumme versus Dokument-`sumTax`;
- Rundung pro Position, Dokument oder Zahlung;
- fehlender/anders behandelter negativer Beleg.

Ohne gemeinsamen Rohdaten-Snapshot lässt sich die Differenz nicht belastbar einem Beleg zuordnen. Der Umbau muss vor der Regeländerung einen `document_diff_report` erzeugen.

### P1: A017-Differenz von 11,90 EUR

XW: 3.668,46 EUR, Legacy: 3.656,56 EUR. Da beide Läufe 138 Ausgangsrechnungen wählen, liegt wahrscheinlich eine Klassifikations-, Positions-, Storno- oder Zahlungsquotendifferenz innerhalb der gleichen Dokumentanzahl vor. Auch steuerfreie innergemeinschaftliche Lieferungen müssen als Geschäftsvorfall und nicht bloß anhand eines Labels erkannt werden; die ZM-Abstimmung ist ein zusätzlicher Kontrollpunkt, ersetzt aber nicht die UVA-Prüfung.

### P1: A000-Semantik und Summenformel

XW bildet A000 durch Addition ausgewählter Unterkennzahlen. Das ist nur korrekt, wenn die U30-Version und die Bedeutung aller enthaltenen/abzuziehenden Kennzahlen exakt berücksichtigt werden. Die ab 07/2026 veröffentlichte BMF-Dokumentversion zeigt ausdrücklich geänderte Summen-/Prüfbeziehungen. Daher darf A000 nicht als zeitlos fest codierte Addition implementiert sein.

### P2: N+1-Abfragen und nicht reproduzierbarer Live-Zustand

XW lud im Test Positionen, TaxSets und Zahlungsinformationen dokumentweise; der Lauf dauerte ca. 135 Sekunden. Legacy dauerte trotz Caches ca. 249 Sekunden. Während eines solchen Laufs kann sich der sevDesk-Datenbestand ändern. Ein erneuter Lauf ist dann nicht beweisbar identisch.

Umbau: Rohdaten einmal mit `snapshot_id`, Abrufzeit, Query, Seitenzahl, Objektzahl und Hash speichern. Die Berechnung arbeitet danach ausschließlich auf diesem Snapshot.

## 5. Steuerliche Leitplanken aus der Online-Recherche

Maßgebliche Primär-/Behördenquellen (Abruf 12.07.2026):

1. USP/BMF, Zeitpunkt der Steuerschuld: Bei Istbesteuerung entsteht die Steuerschuld mit Ablauf des Monats der Bezahlung; Anzahlungen sind ebenfalls relevant.  
   https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/entstehen-der-steuerschuld-und-pflichten/zeitpunkt-des-entstehens-der-steuerschuld.html
2. USP/BMF, Vorsteuerabzug: Für bestimmte Istbesteuerer bis 2 Mio. EUR ist zusätzlich die geleistete Zahlung Voraussetzung für den Vorsteuerabzug.  
   https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/vorsteuerabzug.html
3. BMF, U30 2026 und U30a-Ausfüllhilfe: maßgebliche Formularversion für 2026.  
   https://service.bmf.gv.at/service/anwend/formulare/show_det.asp?MIdVal=47086&STyp=&Typ=SD&s=unternehmer
4. USP/BMF, innergemeinschaftlicher Erwerb: Erwerbsteuer grundsätzlich in Österreich; bei voller Berechtigung korrespondierender Vorsteuerabzug in derselben UVA.  
   https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/innergemeinschaftlicher-erwerb.html
5. USP/BMF, Steuersätze und Befreiungen: 20 % Normalsteuersatz; 10 % und 13 % sind Ausnahmen; Ausfuhr- und innergemeinschaftliche Lieferungen sind echte Befreiungen.  
   https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/steuersaetze-und-steuerbefreiungen-der-umsatzsteuer.html
6. BMF, Dokumentversion UVA ab 07/2026: neue KZ 124/125 und geänderte Prüfbeziehungen; belegt die Notwendigkeit einer periodengesteuerten Formularversion.  
   https://www.bmf.gv.at/dam/jcr%3A922a2cf9-e758-40c4-a671-1674044cced1/BMF_Dokumentenversion_UVA%20ab_07_2026.pdf
7. BMF, Prüfungen UVA ab 07/2026: unter anderem Abhängigkeiten KZ 065 zu Erwerbskennzahlen sowie KZ 066 zu KZ 057.  
   https://www.bmf.gv.at/dam/jcr%3A4180aed7-d33e-4949-b0ca-5999aaa185c6/BMF_Pruefungen_UVA_ab_07_2026.pdf

Hinweis: Die steuerliche Endfreigabe der Mapping-Tabelle und Sonderfälle sollte durch Steuerberatung erfolgen. Der technische Umbau muss diese Freigabe als versionierte Konfiguration abbilden, nicht als verstreute Textregeln im Code.

## 6. Zielarchitektur

```text
sevDesk API
   |
   v
UvaSnapshotCollector -----> immutable Raw Snapshot + completeness report
   |
   v
PaymentLedgerBuilder -----> payment events / allocations / refund events
   |
   v
TaxFactBuilder -----------> typed taxable facts (no U30 codes yet)
   |
   v
U30RuleEngine(period) ----> kennzahlen + formula trace + validation result
   |                              |
   +--> UI preview/audit          +--> exact same filing payload
```

### 6.1 Neue Modelle

`UvaSourceSnapshot`

- Snapshot-ID, Erstellzeit, Zeitraum, API-Basis/Version
- Rohobjekte für Invoice, CreditNote, Voucher, Positions, TaxSet/TaxRule
- Zahlungsereignisse und Zuordnungsquellen
- Pagination-/Fehler-/Vollständigkeitsprotokoll
- Hash über kanonisches JSON

`PaymentAllocation`

- Dokumenttyp und ID
- Zahlungsereignis-ID und Buchungsdatum in Europe/Vienna
- Bruttozahlungsbetrag, Währung und Umrechnung
- Anteil am Dokument; Behandlung Über-/Unterzahlung
- Quelle und Confidence (`transaction`, `log`, `paidDate_fallback`, manuell)
- Storno/Rückzahlung als eigenes negatives Ereignis

`TaxFact`

- Dokument-/Positionsreferenz
- Richtung sale/purchase
- Sachverhalt domestic/ICS/ICA/export/RC/OSS/non-taxable
- Jurisdiktion und Leistungs-/Lieferort
- Nettobasis, Steuerbetrag, Steuersatz
- realisierter Anteil im UVA-Monat
- Mapping-ID und Mapping-Version
- mögliche U30-Zielkennzahlen

`UvaCalculationResult`

- Formularversion (`U30_01_2022` für 06/2026; passende Version nach amtlicher Matrix verifizieren)
- Kennzahlen mit Centwerten
- Zahllast/Gutschrift
- pro Kennzahl eine Liste beitragender TaxFacts
- ausgeführte Formeln und Rundungsschritte
- Validation-Issues mit severity
- `filing_ready`
- Snapshot-Hash

### 6.2 Dateischnitt

Vorgeschlagen unter `src/xw_office/services/finanzonline/uva/`:

- `models.py`
- `snapshot_collector.py`
- `payment_ledger.py`
- `tax_mapping.py`
- `tax_fact_builder.py`
- `rules/base.py`
- `rules/u30_01_2022.py`
- `rules/u30_07_2026.py`
- `validator.py`
- `audit_renderer.py`
- `service.py`

Die bestehenden `uva_preview.py`, `uva_selection.py` und `uva_payload_service.py` bleiben während der Migration als Legacy-XW-Adapter bestehen und werden nach bestandenem Parallelbetrieb entfernt.

## 7. Umsetzungsphasen

### Phase 0: Referenzlauf einfrieren

1. Read-only Debug-Export für 06/2026 ergänzen.
2. Alle Rohdokumente, Positionen, Steuermetadaten und Zahlungen in einen redigierbaren Snapshot schreiben.
3. Geheimnisse und personenbezogene Freitexte aus Test-Fixtures entfernen; IDs stabil pseudonymisieren.
4. XW-alt und Legacy auf exakt diesem Snapshot ausführen.
5. Differenzbericht pro Dokument, TaxFact und Kennzahl erzeugen.

Akzeptanz:

- Wiederholte Läufe auf demselben Snapshot sind byte-identisch.
- Die 0,08-EUR-Differenz in C060, 11,90 EUR in A017 und 2,45 EUR RC-Basis sind einzelnen Fakten zugeordnet.
- Kein API-Fehler kann als leere erfolgreiche UVA erscheinen.

### Phase 1: Payment Ledger

1. Legacy-Logik für CheckAccount-Transaktionen/Logs fachlich extrahieren, nicht kopieren.
2. Zahlungen, Teilzahlungen, Rückzahlungen und Gutschriften als Ereignisse modellieren.
3. `paidDate` nur als konfigurierten Fallback mit sichtbarer Confidence verwenden.
4. Monatsgrenze in `Europe/Vienna` testen.
5. Summe der Allokationen gegen Dokumentbrutto und offene Beträge plausibilisieren.

Akzeptanz:

- Jeder in 06/2026 berücksichtigte Cent besitzt ein Zahlungsereignis oder eine ausdrücklich bestätigte Ausnahme.
- 138 Ausgangsdokumente und die Abweichung 39/42 Eingangsbelege werden im Diff-Report erklärt.
- Teilzahlungen werden nach realem Monatszahlungsbetrag skaliert.

### Phase 2: Steuer-Mapping und TaxFacts

1. Alle im Snapshot vorkommenden TaxSet-/TaxRule-Kombinationen inventarisieren.
2. Fachlich freigegebene Mapping-Matrix erstellen.
3. OSS-/Fremdsteuer explizit trennen.
4. ICS, ICA, Export und RC als verschiedene Sachverhalte modellieren.
5. Text-/Prozent-Inferenz nur noch als Diagnosevorschlag, niemals als Filing-Entscheidung verwenden.

Akzeptanz:

- Keine unbekannte Kombination in einem filing-ready Ergebnis.
- Legacy-Fehlklassifikation ausländischer 13-/20-%-Umsätze ist als Regressionstest fixiert.
- A017-Differenz ist fachlich entschieden und dokumentiert.

### Phase 3: Versionierte U30-Regelengine

1. Amtliche U30-/U30a-Definitionen und Prüfregeln für bis 06/2026 implementieren.
2. Separate Regelversion ab 07/2026 implementieren.
3. A000, Erwerbsteuer, RC-Steuer, Vorsteuern und Zahllast aus deklarativen Formeln bilden.
4. KZ 070/071/072 usw. korrekt nach Basis und Satz trennen.
5. KZ 057/066 und KZ 065 mit der bestätigten 20-%-Mandantenregel erzeugen.
6. BMF-Prüfbeziehungen lokal ausführen, bevor XML erzeugt wird.

Akzeptanz:

- Zeitraum 06/2026 wählt automatisch die alte Formularversion; 07/2026 die neue.
- KZ 066 > KZ 057 ist unmöglich bzw. blockierend.
- Erwerbskennzahlen erfüllen die für die Periode geltenden BMF-Prüfungen.
- Zahllast ist vollständig aus protokollierten Formeln reproduzierbar.

### Phase 4: PySide6-UI und Abgabeschutz

1. Ergebnisstatus `Unvollständig`, `Prüfung nötig`, `Abgabebereit` anzeigen.
2. Kennzahl anklickbar machen; darunter beitragende Belege/Zahlungen anzeigen.
3. Warnungen nach Betragseinfluss sortieren.
4. Snapshot-Zeit und Hash anzeigen; Button `Daten neu laden` erzeugt bewusst einen neuen Lauf.
5. `UVA senden` nur für genau den geprüften Snapshot aktivieren.
6. ZM bleibt eigenständig; Komfortablauf UVA+ZM darf keine Fehler vermischen.

Akzeptanz:

- Ein unbekanntes TaxMapping oder unvollständiger API-Abruf deaktiviert den Sendebutton.
- Vorschau und gesendetes XML tragen denselben Snapshot-Hash und dieselben Kennzahlen.
- Der Benutzer kann die Differenz zum Vormonat und zu einem Referenzlauf nachvollziehen.

### Phase 5: Parallelbetrieb und Freigabe

1. Mindestens drei bereits fachlich bekannte Monate plus Grenzfälle berechnen.
2. XW-alt, Legacy theoretisch, Legacy `getTax`, neue Engine und tatsächlich eingereichte UVA nebeneinanderstellen.
3. Differenzen nicht pauschal tolerieren; jede Differenz klassifizieren: Bug alt, bewusste Verbesserung, Stammdatenfehler, Timing, Rundung, steuerliche Entscheidung.
4. Steuerliche Freigabe der Mapping- und U30-Regelversion dokumentieren.
5. Erst danach alten XW-Rechenweg entfernen.

## 8. Teststrategie

### Unit-Tests

- Zahlung am Monatsletzten/Monatsersten inklusive Zeitzone
- mehrere Teilzahlungen in verschiedenen Monaten
- Rückzahlung und Gutschrift
- Storno mit/ohne Monatszahlung
- inländische 20/10/13-%-Positionen
- gemischte Steuersätze in einem Dokument
- EU-B2B-Lieferung versus EU-B2C/OSS
- innergemeinschaftlicher Erwerb mit der bestätigten 20-%-Mandantenregel
- Reverse Charge mit der bestätigten 20-%-Mandantenregel und Gegenbuchung in KZ 066
- Ausfuhrlieferung
- ausländische Vorsteuer
- unbekanntes TaxSet blockiert
- Rundung auf Position, Zahlungsanteil und Kennzahl
- Formularwechsel 06/2026 -> 07/2026

### Golden-Master-Tests

- pseudonymisierter Snapshot 06/2026
- erwartete Dokumentauswahl
- erwartete TaxFacts
- erwartete Kennzahlen und Zahllast
- erwartete Warnungen und `filing_ready`
- erwarteter U30-XML-Payload

### Fehler-/Resilienztests

- TLS-/Netzfehler
- HTTP 429/500
- Pagination abgebrochen
- einzelne Position nicht abrufbar
- TaxSet-Endpunkt nicht verfügbar
- Zahlung ohne Dokumentzuordnung
- Änderung des sevDesk-Bestands während der Erfassung

In allen unvollständigen Fällen muss der Lauf fehlschlagen oder als nicht abgabebereit enden; eine Null-UVA ist kein zulässiger Fallback.

## 9. Konkrete fachliche Klärungen vor Implementierung

1. Ist die Organisation für 06/2026 tatsächlich Istbesteuerer und gilt die Zahlungsvoraussetzung auch für den Vorsteuerabzug? Die Anwendung nimmt beides derzeit an.
2. Welcher eingereichte FinanzOnline-U30-Wert oder Steuerberater-Abschluss ist der verbindliche Golden Master für 06/2026?
3. Welche sevDesk-TaxSets repräsentieren ICS, ICA, RC, OSS und Exporte tatsächlich im Mandanten?
4. Gibt es eingeschränkten Vorsteuerabzug oder ausschließlich volle Abzugsberechtigung?
5. Welche 42 Legacy-Eingangsbelege stehen den 39 XW-Belegen gegenüber?
6. Welcher Beleg erklärt 0,08 EUR C060, welcher Vorgang 11,90 EUR A017 und welcher 2,45 EUR RC-Basis?
7. Sind die sechs XW-Ausgangsrechnungen ohne Zahlungsnachweis tatsächlich unbezahlt, oder fehlt nur der API-Zahlungslink?

## 10. Definition of Done

- Für 06/2026 existiert ein unveränderlicher, vollständiger und gehashter Daten-Snapshot.
- Jede Kennzahl lässt sich bis zu Position und Zahlungsereignis aufklappen.
- Die Differenzen 0,08 EUR, 11,90 EUR und 2,45 EUR sind abschließend erklärt.
- Ausländische B2C-/OSS-Umsätze bleiben aus der AT-UVA ausgeschlossen.
- ICS/ICA/RC werden nachvollziehbar klassifiziert; die bestätigte 20-%-Regel für KZ 065 und 057/066 bleibt erhalten.
- U30-Regeln sind periodenversioniert und gegen amtliche Prüfungen validiert.
- Vorschau, XML und Versand verwenden dasselbe Resultat.
- Unvollständige Daten oder unbekannte Mappings blockieren den Versand.
- Der Wert für 06/2026 ist gegen einen tatsächlich eingereichten bzw. steuerlich freigegebenen Referenzwert bestätigt.

## 11. Priorisierte Entscheidung

Der nächste sinnvolle Implementierungsschritt ist **Phase 0 mit Legacy 1.910,22 EUR als Referenzkorridor**. Zuerst werden die in XW fehlenden Basen A022 = 3.349,56 EUR und A006 = 9.216,97 EUR positionsgenau rekonstruiert. Die Untersuchung beginnt bei Positionsaggregation und Fremdsteuer-/OSS-Klassifikation, weil die Anzahl der gewählten Ausgangsrechnungen bereits übereinstimmt. KZ 065 und KZ 057/066 werden dabei nicht umgebaut.
