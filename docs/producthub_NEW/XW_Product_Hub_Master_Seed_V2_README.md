# XW Product Hub – Master Seed V2

Stand: 2026-09-17

## Source of Truth
Für widersprüchliche Produktidentität, Artikelnummern und Bezeichnungen gelten ausschließlich
die Tabellenblätter `XeisWorks` und `MusikHeroes` aus `Produktpalette(2).xlsx` als höchste Priorität.

## Dateien
- `XW_Product_Hub_Master_Seed_V2_2026-09-17.csv`: 915 eindeutige kanonische SKU-Zeilen
- `XW_Product_Hub_SKU_Aliases_V2_2026-09-17.csv`: 87 Legacy-SKU-Aliase
- `XW_Product_Hub_Channel_Cleanup_V2_2026-09-17.csv`: 91 geplante Channel-Bereinigungen
- `XW_Product_Hub_Review_Conflicts_V2_2026-09-17.csv`: 24 verbleibende echte Review-Fälle

## V2-Regeln

### SKU
- Alle dreistelligen `XW-4xx` werden kanonisch vierstellig: `XW-4xx -> XW-40xx`.
- Suffixe bleiben erhalten, z. B. `XW-424.3 -> XW-4024.3`.
- Alte Nummern werden NICHT vergessen, sondern als `sku_alias` geführt.
- Beispiel: `XW-443 -> XW-4043`; Titel/Identität folgen dem XLSX-SOT (`Zadok The Priest`).

### Marken
- `XW-1...`, `XW-2...`, `XW-3...` -> `XeisWorks`
- `XW-40...` -> `Blechhaufn`
- `XW-45...` -> `Mnozil Brass`

### Zusatzstimmen
- Bei `XW-1xx.*` und `XW-2xx.*` ist `category_primary=Zusatzstimme`.
- `Zusatzstimme`, `ZST`, `ZS` stehen NIE in `title_full`, `title_short` oder `code_short`.
- Beispiel: `XW-102.5` und `XW-102.5-D` heißen beide `Volksmusik #2 - Tuba in B`.

### Titel
- `Volksmusik - Band N` wird immer `Volksmusik #N`.
- Das Wort `Band` kommt in den drei Titelfeldern nicht vor.
- B/Es werden deutschsprachig verwendet.
- Physisch/Digital/Print@Home desselben fachlichen Produkts haben exakt dieselben drei Titel.
- Format ist ausschließlich ein Variantenattribut.

### Varianten und Gruppierung
- `product_group_id` fasst fachlich identische Produkte zusammen.
- `parent_sku` zeigt auf die bevorzugte kanonische Variante.
- `canonical_variant` und `variant_role` machen Format-, Besetzungs-, Scoring- und Legacy-Varianten explizit.
- Besetzung bleibt separat von `scoring`.
- Zwei Arrangements von `Erinnerungen an Brennberg` bleiben als eigene Varianten erhalten.

### Channels
- `EXTERNAL_ONLY` bedeutet bewusst: operativer/sevdesk-interner Artikel, nicht automatisch ein Wix-Verkaufsprodukt.
- `sync_wix`, `sync_sevdesk`, `sync_amazon` und `wix_publish_eligible` sind explizite Channel-Hinweise.
- Fehlende Wix-Präsenz bei Dienstleistung/Versand/Abrechnung ist kein Konflikt.
- Externe Writes bleiben beim Import deaktiviert; Cleanup wird separat ausgeführt.

## Statistiken
- Zeilen: 915
- Legacy-Aliase: 87
- Review-Fälle: 24
- Channel-Cleanup-Einträge: 91

### Record state
- ACTIVE: 600
- RESERVED: 251
- EXTERNAL_ONLY: 46
- REVIEW: 18

### Status
- live: 640
- draft: 251
- review: 24

### SOT-Status
- EXACT: 466
- RESERVED: 251
- DERIVED: 94
- EXTERNAL: 73
- DERIVED_TITLE_MATCH: 31

## Kontrollierte Sonderentscheidungen
- `XW-562.12`: Titel fachlich auf `Umpa Umpa Umtata #2 - Playalongs in C` korrigiert.
- `XW-511.16`: bleibt reserviert; das sevdesk-Horn-Playalong gehört zu `XW-511.17`.
- `XW-4024.2` / `XW-4024.3`: zwei Arrangements; `.3` = `[Blechhaufn-Version]`.
- `XW-6012`: SOT = `BH-Polka [Kleine Besetzung]`; Wix-Bier-Polka-Doppelbelegung ist Channel-Cleanup.
- `XW-4516`: SOT = `Mnoschil`; doppelte Wix-Abbildung wird als Cleanup behandelt.

## Harte Validierungen vor Import
- keine doppelten `sku`
- kein dreistelliges `XW-4xx` mehr
- keine Wörter `Zusatzstimme`, `ZST`, `ZS` oder `Band` in `title_full`, `title_short`, `code_short`
- Markenregeln für XW-1/2/3/40/45 erfüllt
- alle XW-1xx.* und XW-2xx.* in Kategorie `Zusatzstimme`
- Formatvarianten mit vorhandener Basis-SKU haben identische Titel
