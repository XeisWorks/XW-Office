# EU-OSS-Integration: Recherche und Umsetzungsbild

Stand: 2026-07-08

## Kurzfazit

EU-OSS kann in XW-Studio sinnvoll als Berechnung, Preview und XML-Export nachgeruestet
werden. Eine U30-aehnliche direkte SOAP/FileUpload-Einreichung ueber den
FinanzOnline-Webservice ist nach den aktuellen BMF/USP-Unterlagen aber nicht vorgesehen.
Der produktive Ablauf ist: XML in der App erzeugen, lokal validieren, dann im EU-OSS-Portal
via FinanzOnline unter "Erklaerung einreichen/korrigieren" hochladen/pruefen und dort
einreichen.

## Offizielle Quellenlage

- USP/BMF EU-OSS: XML-Upload ist direkt im EU-OSS bzw. Nicht-EU-OSS/eVAT unter
  "Erklaerung einreichen" / "Erklaerung hochladen"; explizit "kein Webservice von
  Finanz Online".
  https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/Umsatzsteuer-One-Stop-Shop/EU-OSS/Erklaerung-und-Zahlung-im-EU-OSS.html
- USP/BMF Upload-Anleitung ab 01.07.2021: Die oesterreichische OSS-Upload-Loesung ist
  eine Vorausfuellung zur Steuerberechnung, kein Webservice und kein FinanzOnline-
  Datenstromverfahren. Test-URL EU-OSS:
  https://fon-moss.bmf.gv.at/extern/moss/test_fileupload_oss
- FinanzOnline FileUpload-Webservice: `art` kennt U30, U13, VAT usw.; kein OSS-Code.
  Live-XSD: https://finanzonline.bmf.gv.at/fon/ws/fileupload.xsd

## Bestand in XW-Studio

- `src/xw_studio/services/finanzonline/uva_soap.py`
  - `FinanzOnlineFileUploadBackend` macht Login -> Upload -> Logout.
  - `submit_uva()` baut und validiert U30-XML und sendet `art="U30"`.
  - `submit_zm()` baut und validiert U13-XML und sendet `art="U13"`.
- `src/xw_studio/services/finanzonline/u30_xml.py`
  - U30-XML-Builder mit FASTNR und KZ-Struktur.
- `src/xw_studio/services/finanzonline/uva_payload_service.py`
  - Fremdsteuer/OSS-nahe Labels werden aus der AT-UVA herausgehalten und als Warnung
    markiert.

Damit ist die Architektur fuer Berechnung, Preview, XML-Builder und Validierung gut
wiederverwendbar. Der Transportteil darf fuer OSS aber nicht als SOAP-Upload umgesetzt
werden.

## Bestand in der Legacy-App

- `C:\Users\bernh\GitHub\sevDesk\UVA.py`
  - `EXCLUDE_EU_SALES = True`.
  - Auslaendische Umsatzsteuertexte wie "Deutsche MwSt. 7%" oder "Italienische IVA 4%"
    werden als `OSS` klassifiziert.
  - `category == "OSS"` wird bei Ausgangsbelegen aus der U30-Aggregation ausgeschlossen.
  - Bei Eingangsbelegen wird auslaendische VAT als Hinweis gefuehrt, nicht als AT-Vorsteuer.
- `C:\Users\bernh\GitHub\sevDesk\Finanzonline\EU-OSS`
  - enthaelt eine OSS-Upload-PDF und einen YAML/README-Entwurf.
  - Der YAML/README-Entwurf behauptet einen FinanzOnline SOAP/FileUpload-Upload mit
    `filetype="OSS"`. Das widerspricht den aktuellen BMF/USP-Quellen und sollte nicht
    uebernommen werden.
  - Verwertbar daraus sind nur die Feld-Stichworte `mscon`, `taxable`, `vatRate`,
    `goods`, `uidFixedEst`.

## Fachliche Abgrenzung zur U30

Die U30 ist in XW-Studio als IST-Monatsberechnung umgesetzt. EU-OSS ist anders:

- Zeitraum ist das Kalendervierteljahr.
- Laut USP sind die unter EU-OSS fallenden Umsaetze in jenes Quartal aufzunehmen, in dem
  Lieferung bzw. Dienstleistung ausgefuehrt wird. Das gilt auch bei Istbesteuerung nach
  Paragraph 17 UStG oder bei Anzahlungen.
- Fuer die Datenquelle heisst das: nicht die U30-Zahlungsselektion kopieren, sondern fuer
  OSS primaer `deliveryDate`/Leistungsdatum verwenden; Fallbacks muessen transparent
  gewarnt werden.
- Nullmeldungen sind im Portal vorgesehen; die App sollte sie anzeigen/erinnern, aber der
  Portalbutton reicht die Null-Erklaerung ein.

## Vorgeschlagenes Zielmodell

Neue Module:

- `oss_models.py`
  - `OssLine(country_code, vat_rate, taxable_amount, goods, tax_amount, source_docs)`
  - `OssQuarterResult(year, quarter, goods_lines, service_lines, corrections, warnings)`
- `oss_classifier.py`
  - gemeinsame Klassifikationsbasis mit U30, aber eigener Rueckgabetyp `OSS_CANDIDATE`.
  - erkennt Land/Steuersatz aus sevDesk `taxText`, `taxSet`, `taxRule`, Positionen und
    Lieferadresse.
- `oss_service.py`
  - laedt relevante Ausgangsbelege fuer ein Quartal.
  - filtert nur B2C-Auslandsumsatz, nicht B2B/Reverse-Charge/ZM/ig Lieferung.
  - aggregiert nach `(goods, mscon, vatRate, uidFixedEst/Abgangsland)`.
- `oss_xml.py`
  - erzeugt Portal-XML fuer EU-OSS.
  - optional `uidIossid`, `period`, `year`; optional `taxamount`.
  - Korrekturen in `Korrektur` fuer fruehere Zeitraeume.
- UI-Erweiterung im Steuer-Modul:
  - eigener Tab "EU-OSS".
  - Quartalsauswahl, Preview-Tabelle, XML speichern, Testportal oeffnen.

## Dynamische Laenderlogik

Der Plan "alle Umsatzsteuerregelungen aus sevDesk, die nicht in U30 waren" ist als
Startpunkt gut, aber nicht als alleinige Regel sicher genug. Nicht-U30 bedeutet nicht
automatisch OSS. Es braucht mindestens diese Ausschluesse:

- AT-Standardsteuer und U30-Kennzahlenfaelle
- B2B Reverse Charge / ZM-Faelle
- innergemeinschaftliche Lieferungen an Unternehmer
- Ausfuhr/Drittland
- Eingangsbelege mit auslaendischer VAT
- unklare 0%-/steuerfreie Faelle

Robuster ist:

1. U30-Klassifikation laufen lassen.
2. Alles, was U30 bewusst als `OSS`/Fremdsteuer verwirft, als OSS-Kandidat sammeln.
3. Kandidaten nur uebernehmen, wenn Verbraucherland, B2C-Indiz und Steuersatz eindeutig
   sind.
4. Neue Laender nicht ueber harte TaxText-Listen freischalten, sondern ueber ISO-Land aus
   Lieferadresse/TaxText plus EU-Laenderliste und Steuersatz.

## Testmatrix

- EU-OSS Warenlieferung DE 19%, Ausfuehrungsdatum im Quartal, Zahlung im Folgequartal:
  muss in OSS-Quartal der Lieferung landen.
- EU-OSS Dienstleistung FR 20%.
- Gleiches Land + gleicher Steuersatz + gleiche Waren/Leistungsart wird summiert.
- Gleiches Land + gleicher Steuersatz, aber Waren vs. Dienstleistung bleibt getrennt.
- B2B Reverse Charge landet nicht in OSS.
- Ausland-VAT auf Eingangsbeleg landet nicht in OSS.
- Gutschrift/Rabatt erzeugt Korrekturzeile fuer frueheren Zeitraum.
- Nullquartal wird als Nullmeldung/Portalhinweis dargestellt, nicht als SOAP-Upload.

## Umsetzungsempfehlung

Zuerst OSS-Berechnung und XML-Export bauen, dann gegen das oeffentliche Testportal pruefen.
Keine produktive "Einreichen"-Automatik implementieren, solange BMF/USP keinen OSS-Webservice
veroeffentlichen.
