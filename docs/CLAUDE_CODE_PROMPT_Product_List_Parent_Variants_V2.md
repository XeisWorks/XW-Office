# XW Product Hub – Product List V2: Parent-Produkte mit aufklappbaren Varianten

**Zielrepo:** `XeisWorks/XW-Office`  
**Ziel:** Die Produktliste im XW Product Hub soll fachliche Produkte nur **einmal** anzeigen. Unterschiedliche verkaufbare Varianten – z. B. PHYSICAL, DIGITAL, PRINT_AT_HOME oder unterschiedliche Besetzungen – werden unter dem Parent-Produkt aufklappbar dargestellt.

## 1. Wichtige Vorgabe

Die **SKU bleibt die erste Spalte** der Haupttabelle und muss vollständig sortierbar bleiben.

Auch wenn die Hauptliste künftig Parent-Produkte darstellt, soll in der ersten Spalte eine kanonische SKU angezeigt werden:

- bevorzugt die SKU der `canonical_variant` / Default-Variante,
- ansonsten die SKU der `is_default=true`-Variante,
- ansonsten deterministisch die lexikographisch/numerisch kleinste aktive SKU.

Beispiele:

| SKU | Name | Kategorie | Marke | Varianten | Preis(e) | Status |
|---|---|---|---|---:|---|---|
| `XW-102.5` | Volksmusik #2 - Tuba in B | Zusatzstimme | XeisWorks | 2 | 5,50–9,90 € | aktiv |
| `XW-6004` | Himmelsthron | Noten | XeisWorks | 3 | 31,90–53,90 € | aktiv |

Die SKU-Spalte bleibt:

- erste Spalte,
- standardmäßig sichtbar,
- auswählbar im Spaltenmenü,
- sortierbar auf-/absteigend,
- für die Standardsortierung bevorzugt.

## 2. Fachliches Zielbild

Aktuell erscheinen identische fachliche Produkte mehrfach, wenn mehrere SKUs existieren, z. B.:

- `XW-102.5` = PHYSICAL
- `XW-102.5-D` = DIGITAL

Diese sollen künftig **eine Parent-Zeile** bilden.

### Beispiel

Hauptliste:

```text
▸ XW-102.5   Volksmusik #2 - Tuba in B   Zusatzstimme   XeisWorks   2 Varianten
```

Aufgeklappt:

```text
    PHYSICAL      XW-102.5       Netto ...   Brutto ...   Bestand ...   Wix ✓   sevdesk ✓
    DIGITAL       XW-102.5-D     Netto ...   Brutto ...   Bestand —     Wix ✓   sevdesk ✓
```

Dasselbe Konzept soll auch für Besetzungsvarianten funktionieren:

```text
▸ XW-6004   Himmelsthron   Noten   XeisWorks   3 Varianten
    Kleine Besetzung       XW-6004
    Böhmische Besetzung    XW-6218
    Musikkapelle           XW-6605
```

## 3. Bestehendes Datenmodell verwenden

Kein neues paralleles Produktmodell bauen.

Vorhandene Struktur verwenden:

- `product` = fachliches Parent-Produkt
- `product_variant` = konkrete verkaufbare SKU
- `product_price` = variantenspezifische Preise
- `product_identifier` = ISBN / ASIN / FNSKU etc.
- `channel_mapping` = Wix / sevdesk / Amazon / VLB
- `inventory_stock` = variantenspezifischer Bestand
- `tag` / `product_tag`
- `product.attributes` für bestehende Zusatzmetadaten, solange noch nicht typisiert

Die neue UI soll die bereits kuratierte Gruppierung verwenden. Keine neue Fuzzy-Gruppierung in der UI.

## 4. Hauptliste: Parent-Produkte statt Variant-Zeilen

Die API für die Produktliste soll künftig eine Parent-orientierte Darstellung liefern.

### Pro sichtbarer Hauptzeile mindestens

- `product_id`
- `display_sku`
- `name`
- `title_short`
- `category`
- `brand_name`
- `product_type`
- `status`
- `active`
- `variant_count`
- `formats`
- `ensembles`
- `scorings`
- `price_net_min`
- `price_net_max`
- `price_gross_min`
- `price_gross_max`
- `currency`
- `stock_total` bzw. sinnvoller aggregierter Bestandswert
- `tags`
- `wix_state`
- `sevdesk_state`
- `amazon_state`
- `content_status`
- `review_required`
- `updated_at`

### `display_sku`

Diese SKU ist ausschließlich die kanonische Anzeige-/Sortier-SKU des Parent-Produkts.

Sie ersetzt **nicht** die individuellen Variant-SKUs.

Regel:

1. `canonical_variant=true`, falls vorhanden
2. sonst `is_default=true`
3. sonst kleinste aktive SKU nach derselben SKU-Sortierlogik wie in der Tabelle

## 5. SKU-Sortierung

Die SKU-Sortierung darf nicht als triviale Textsortierung implementiert werden.

Beispiel gewünschte Reihenfolge:

```text
XW-101
XW-101.1
XW-101.2
XW-102
XW-102.5
XW-102.5-D
XW-4001
XW-4043
XW-4516
```

Nicht:

```text
XW-101
XW-101.1
XW-101.10
XW-101.2
...
```

Eine natürliche SKU-Sortierung implementieren, die numerische Segmente numerisch vergleicht und Suffixe deterministisch nachordnet.

Diese Sortierung soll sowohl Frontend- als auch Backend-seitig konsistent sein, falls serverseitige Sortierung eingeführt wird.

## 6. Aufklappbare Varianten

Jede Parent-Zeile erhält links einen Chevron/Pfeil:

- `▸` geschlossen
- `▾` geöffnet

Nur anzeigen, wenn `variant_count > 1`.

Bei genau einer Variante ist kein Aufklapp-Pfeil notwendig.

### Variantentabelle

Beim Aufklappen direkt unter der Parent-Zeile eine kompakte Untertabelle rendern.

Empfohlene Spalten:

| Format / Besetzung | SKU | Netto | Brutto | Bestand | Wix | sevdesk | Amazon | Aktiv |
|---|---|---:|---:|---:|---|---|---|---|

Je nach Produkttyp soll die erste Variantenspalte sinnvoll zusammengesetzt werden:

- `PHYSICAL`
- `DIGITAL`
- `PRINT_AT_HOME`
- `PLAYALONG`
- `Kleine Besetzung`
- `Böhmische Besetzung`
- `Musikkapelle`
- `5-stimmig`
- `7-stimmig`

Wenn mehrere Variantendimensionen existieren:

```text
PHYSICAL · Kleine Besetzung
DIGITAL · Kleine Besetzung
PHYSICAL · Böhmische Besetzung
```

Keine redundanten Langtitel in jeder Variant-Zeile anzeigen, wenn sie identisch zum Parent sind.

## 7. Variantenspezifische Preise

Preise gehören zur Variante, nicht pauschal zum Parent.

In der Hauptzeile:

- bei genau einem Preis: `9,90 €`
- bei mehreren unterschiedlichen Preisen: `5,50–9,90 €`
- wenn Preise fehlen: `—`

Im aufgeklappten Bereich jeweils exakt:

- `price_net`
- `vat_percent`
- `price_gross`
- Währung

Keine Preise raten oder aus falscher Variante übernehmen.

## 8. Spaltenauswahl deutlich erweitern

Aktuell sind nur wenige Spalten auswählbar.

Die neue Spaltenauswahl soll mindestens folgende Felder anbieten:

1. **SKU**
2. **Name**
3. `Kurzname`
4. `Kategorie`
5. `Marke`
6. `Typ`
7. `Varianten`
8. `Formate`
9. `Besetzung`
10. `Scoring`
11. `Instrument`
12. `Preis brutto`
13. `Preis netto`
14. `Bestand`
15. `Tags`
16. `ISBN`
17. `ASIN`
18. `Wix`
19. `sevdesk`
20. `Amazon`
21. `Content-Status`
22. `Review`
23. `Status`
24. `Aktiv`
25. `Geändert am`

### Default-Sichtbarkeit

Standardmäßig sichtbar:

- SKU
- Name
- Kategorie
- Marke
- Varianten
- Preis brutto
- Status
- Aktiv

Die SKU bleibt dabei **immer erste Spalte**, auch wenn andere Spalten ein-/ausgeblendet werden.

Wenn SKU ausgeblendet werden darf, muss beim erneuten Einblenden die SKU wieder an Position 1 erscheinen.

Bevorzugt: SKU standardmäßig sichtbar und nicht komplett entfernbar, sofern dies UX-seitig vertretbar ist.

## 9. Welche Felder gehören NICHT in die normale Spaltenauswahl?

Technische Provenance-/Debugfelder nicht in die tägliche Haupttabelle aufnehmen:

- `source_title_xlsx`
- `source_title_wix`
- `source_title_erp`
- `conflict_notes`
- `grouping_confidence`
- Raw Payloads
- interne UUIDs
- Import-Batch-IDs
- technische Hashes

Diese bleiben Detail-/Review-/Debuginformationen.

## 10. Bestehende `attributes` besser exponieren

Aktuell liegen mehrere wichtige Werte noch in `product.attributes`.

Mindestens diese Werte in der Read API typisiert verfügbar machen:

- `title_short`
- `code_short`
- `music_attributes.instrument`
- `music_attributes.ensemble`
- `music_attributes.scoring`
- `music_attributes.voice_count`
- `content_status`
- `review_required`
- `format` bzw. aggregierte `formats`

Nicht zwingend sofort neue DB-Spalten anlegen.

Es genügt zunächst, die Werte sauber aus dem bestehenden Datenmodell zu lesen und in den Pydantic-/TypeScript-Schemas typisiert zu exponieren.

## 11. Varianten und Detailseite

Ein Klick auf die Parent-Zeile öffnet weiterhin die Produktdetailseite.

Auf der Detailseite:

- Parent-Daten oben
- darunter eigener Bereich `Varianten`
- jede Variante mit SKU, Format, Besetzung, Preis, Bestand, Identifiers und Channel-Mappings

Eine Variant-Zeile in der aufgeklappten Hauptliste darf optional direkt zu dieser Variante innerhalb der Detailansicht springen.

## 12. Channel-Status

Nicht jedes Product muss Wix-fähig sein.

Insbesondere sevdesk-only Produkte wie:

- Dienstleistungen
- Versand
- Gutschriften
- Auftritte
- interne Buchungsartikel

dürfen `sync_wix=false` / `wix_publish_eligible=false` haben, ohne als Fehler markiert zu werden.

Darstellung:

- `✓` vorhanden/synchron
- `—` nicht vorgesehen
- `!` Konflikt/Fehler
- optional `○` noch nicht synchronisiert

Nicht „fehlendes Wix Mapping“ als Fehler anzeigen, wenn `wix_publish_eligible=false`.

## 13. Suchverhalten

Die Produktsuche soll sowohl Parent- als auch Variantendaten finden.

Suche nach:

- Parent-Name
- `display_sku`
- jeder Variant-SKU
- `title_short`
- `code_short`
- ISBN
- ASIN
- Tags

Beispiel:

Suche `XW-102.5-D` muss den Parent `Volksmusik #2 - Tuba in B` finden und idealerweise automatisch die passende Variante hervorheben.

## 14. Filter

Mindestens unterstützen:

- Status
- Aktiv
- Kategorie
- Marke
- Format
- Besetzung
- Tags
- Channel-Verfügbarkeit
- Review erforderlich

Später erweiterbar.

## 15. Performance

Keine N+1-Queries pro Produkt.

Für die Listen-API entweder:

- gezieltes eager loading,
- aggregierte Query,
- oder mehrere gebatchte Queries.

Kataloggröße ist aktuell überschaubar, trotzdem saubere Architektur beibehalten.

## 16. Betroffene Dateien zuerst prüfen

Vor Änderungen aktuellen Stand lesen, insbesondere:

```text
web/product-hub/src/pages/ProductListPage.tsx
web/product-hub/src/api/types.ts
web/product-hub/src/api/client.ts

src/xw_office/web/schemas/products.py
src/xw_office/web/routers/products.py
src/xw_office/services/product_hub/catalog_service.py
src/xw_office/repositories/product_hub.py
src/xw_office/models/product_hub.py
src/xw_office/services/product_hub/grouping.py

docs/product_hub/PROGRESS.md
docs/product_hub/XW_PRODUCT_HUB_DATA_MODEL.yaml
```

Nicht blind von diesen Pfaden ausgehen, falls sich der aktuelle Repo-Stand inzwischen geändert hat.

## 17. Sicherheitsregeln

- Keine Wix-Writes.
- Keine sevdesk-Writes.
- Keine Amazon-Writes.
- Keine automatische neue Gruppierung aufgrund ähnlicher Namen.
- Bestehende kuratierte Parent/Variant-Struktur verwenden.
- Keine SKU löschen.
- Keine Preise überschreiben.
- Keine Identifier zusammenführen, wenn ein Konflikt besteht.
- Kein Big-Bang-Refactoring des gesamten Product Hub.
- Bestehende Detail-/Edit-/Readiness-Funktionen müssen weiter funktionieren.

## 18. Tests

Mindestens Tests für:

### Backend

- Parent-Liste liefert pro Product nur eine Hauptzeile.
- `variant_count` stimmt.
- `display_sku` folgt der Canonical/Default-Regel.
- Preis-Min/Max korrekt.
- Channel-Aggregation korrekt.
- sevdesk-only Produkt erzeugt keinen Wix-Fehler.
- Suche nach Variant-SKU findet Parent.
- natürliche SKU-Sortierung.

### Frontend

- SKU ist erste Spalte.
- Sortierung nach SKU funktioniert auf/absteigend.
- Produkt mit 1 Variante hat keinen unnötigen Expand-Pfeil.
- Produkt mit >1 Variante ist aufklappbar.
- Varianten erscheinen mit eigener SKU und eigenem Preis.
- Spaltenauswahl enthält neue Felder.
- gespeicherte Spaltenauswahl in `localStorage` bleibt kompatibel.
- alte gespeicherte Column-Keys führen nicht zu Fehlern.
- Parent-Zeile bleibt klickbar.
- Expand-Klick darf nicht versehentlich zur Detailseite navigieren.
- Tastaturbedienung/ARIA für Expand-Button sicherstellen.

## 19. Akzeptanzbeispiele

### Beispiel A – Physical + Digital

Nicht mehr:

```text
XW-102.5     Volksmusik #2 - Tuba in B
XW-102.5-D   Volksmusik #2 - Tuba in B
```

Sondern:

```text
▾ XW-102.5   Volksmusik #2 - Tuba in B   2 Varianten

  PHYSICAL   XW-102.5
  DIGITAL    XW-102.5-D
```

### Beispiel B – mehrere Besetzungen

Nicht drei Hauptzeilen:

```text
XW-6004 Himmelsthron [Kleine Besetzung]
XW-6218 Himmelsthron [Böhmische Besetzung]
XW-6605 Himmelsthron [Musikkapelle]
```

Sondern ein Parent:

```text
▾ XW-6004   Himmelsthron   3 Varianten

  Kleine Besetzung       XW-6004
  Böhmische Besetzung    XW-6218
  Musikkapelle           XW-6605
```

Falls fachlich im bestehenden kuratierten Datenmodell bewusst unterschiedliche Parent-Produkte angelegt wurden, diese **nicht aufgrund dieses Beispiels eigenmächtig neu gruppieren**. Der Seed-/Grouping-Stand ist maßgeblich.

## 20. Definition of Done

Die Umsetzung ist fertig, wenn:

- [ ] jedes fachliche Parent-Produkt nur einmal in der Hauptliste erscheint
- [ ] SKU ist die erste sichtbare Tabellenspalte
- [ ] Sortierung nach SKU funktioniert natürlich und stabil
- [ ] Varianten sind aufklappbar
- [ ] Variant-SKUs bleiben vollständig sichtbar
- [ ] variantenspezifische Preise werden korrekt dargestellt
- [ ] Physical/Digital/Print@Home erscheinen nicht mehr als redundante Hauptzeilen
- [ ] Besetzungs-/Scoring-Varianten können ebenfalls im Expand-Bereich erscheinen
- [ ] mindestens die in §8 genannten Spalten auswählbar sind
- [ ] wichtige Attribute typisiert über die API verfügbar sind
- [ ] Suche nach Variant-SKU funktioniert
- [ ] sevdesk-only / not-for-sale Artikel werden korrekt behandelt
- [ ] keine externen Channel-Writes stattgefunden haben
- [ ] bestehende Product-Hub-Funktionen weiterhin funktionieren
- [ ] Backend- und Frontendtests ergänzt sind
- [ ] `docs/product_hub/PROGRESS.md` aktualisiert wurde

## 21. Arbeitsauftrag an Claude Code

Bitte zuerst den aktuellen Repo-Stand analysieren und dann diese Änderung in möglichst kleinen, nachvollziehbaren Schritten umsetzen.

Bevor Code geändert wird:

1. aktuelle Product-/Variant-Struktur prüfen,
2. aktuelle API-Antwort der Produktliste nachvollziehen,
3. prüfen, ob die V2-Gruppierung bereits vollständig in der Datenbank angewandt wurde,
4. keine eigene Fuzzy-Gruppierung erfinden.

Danach:

1. Backend-Read-Model für Parent-Liste erweitern,
2. typisierte Felder/API-Schemas erweitern,
3. Suche/Sortierung ergänzen,
4. Frontend-Hauptliste auf Parent-Darstellung umbauen,
5. Expandable Variant Rows implementieren,
6. Spaltenauswahl erweitern,
7. Tests ergänzen,
8. vollständige Test-/Lint-/Typecheck-Läufe durchführen,
9. `PROGRESS.md` aktualisieren.

Zum Abschluss ausgeben:

- geänderte Dateien,
- neue/angepasste API-Felder,
- Anzahl Parent-Produkte,
- Anzahl Varianten,
- Testresultate,
- bekannte Restpunkte,
- Bestätigung: **keine Wix-/sevdesk-/Amazon-Writes durchgeführt**.
