# XW Product Hub – Master Seed

Stand: 2026-09-17

## Dateien
- `XW_Product_Hub_Master_Seed_2026-09-17.csv`: 972 Master-Zeilen, eine Zeile pro SKU.
- `XW_Product_Hub_Review_Conflicts_2026-09-17.csv`: 408 Zeilen mit Review-/Konfliktbedarf.

## Source-of-Truth-Regel
Höchste Priorität haben ausschließlich die Blätter `XeisWorks` und `MusikHeroes`
aus `Produktpalette(1).xlsx`. Wix, ERP/sevdesk-Export und Amazon-Bericht ergänzen
fehlende Informationen und dienen zur Konfliktprüfung.

## Modellierungsentscheidungen
- `ensemble`: nur
  - Kleine Besetzung
  - Böhmische Besetzung
  - Musikkapelle
  - Blasmusik Supergroup
  - Sinfonisches Blasorchester
- `scoring`: Satz-/Stimmigkeitsmodell, z. B.
  `Register-4er`, `Junior-4tett`, `Section-4tett`, `4-stimmig`, `5-stimmig`,
  `6-stimmig`, `7-stimmig`, `8-stimmig`.
- `voice_count`: numerische Ergänzung zu `scoring`.
- Deutschsprachige Stimmung: `B` / `Es`.
- MusikHeroes-Codes: `CKH`, `OW`, `T&G`, `WU`, `BJ`, `UUU`, `ET`.
- `format`: `PHYSICAL`, `PRINT_AT_HOME`, `DIGITAL`, `PLAYALONG`.
- `vat_percent`: durchgehend 10.00.
- Preise: explizite XLSX-Preisangaben haben Vorrang. Danach ERP/sevdesk netto,
  danach Wix brutto. Brutto/Netto werden mit 10 % USt. gegengerechnet.

## Titelkonvention
- `title_full`: menschenlesbar; Besetzung/Scoring in eckigen Klammern.
- `title_short`: kompakte Anzeige.
- `code_short`: kompakter technischer Anzeigename; nicht als Primärschlüssel verwenden.
- SKU bleibt der eindeutige technische Artikel-Identifier.

Beispiele:
- `Christkindl-Hits #1 - 2. Stimme in B (hoch)`
- `CKH#1 2B-h`
- `CKH#1_2B-h`
- `Himmelsthron [Kleine Besetzung]`
- `Himmelsthron [Kl.Bes.]`
- `HIMMELSTHRON_KB`

## Amazon
Der hochgeladene Kategorie-Angebotsbericht enthält keine FNSKU-Spalte und keine
FNSKU-Werte. Deshalb bleibt `fnsku` leer und `fnsku_status=MISSING_IN_REPORT`.

Für Amazon-Buchprodukte mit ISBN-13 wird zusätzlich ISBN-10 berechnet und als
unverifizierter ASIN-Kandidat eingetragen:
- `asin_source=DERIVED_FROM_ISBN13_BOOK`
- `asin_verified=false`

Nur ein im Bericht ausdrücklich als `ASIN` ausgewiesener Wert wird mit
`asin_source=AMAZON_REPORT` und `asin_verified=true` markiert.

## Content
Vorhandene Amazon-/Wix-Beschreibungen werden übernommen und normalisiert.
Fehlende Inhalte wurden neutral erzeugt:
- `content_status=SOURCE`: vorhandener Quelltext
- `content_status=AUTO_DRAFT`: automatisch erzeugter Entwurf

AUTO_DRAFT sollte vor Push zu Wix/Amazon redaktionell freigegeben werden.

## Datenstatus
- live: 501
- review: 227
- draft: 244
- ACTIVE: 501
- RESERVED: 244
- EXTERNAL_ONLY: 226
- XLSX_BLANK_EXTERNAL_ACTIVE: 1

## Formate
- PHYSICAL: 753
- DIGITAL: 118
- PRINT_AT_HOME: 57
- PLAYALONG: 44

## Content
- AUTO_DRAFT: 660
- SOURCE: 312

## Wichtigste Review-Flags
- NOT_IN_XLSX_SOT: 226
- TITLE_DRIFT: 138
- PRICE_DRIFT_WIX: 31
- FNSKU_NOT_IN_REPORT: 23
- PRICE_DRIFT_ERP: 7
- DUPLICATE_WIX_SKU: 2
- DUPLICATE_ERP_SKU: 1
- XLSX_BLANK_BUT_EXTERNAL_ACTIVE: 1
- AMAZON_SELLER_SKU_DIFFERS: 1
