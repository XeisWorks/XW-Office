# XW-Studio Bedienung: Brand gezielt und im Bulk bearbeiten

## Voraussetzungen
- Produkte sind im Tab Inventar vorhanden.
- Fuer Wix-Writeback sind `WIX_API_KEY` und `WIX_SITE_ID` konfiguriert.

## Zielauswahl (gezielt)
1. Oeffne Produkte -> Inventar (DB).
2. Nutze Suchfeld fuer SKU, Name, Kategorie oder Brand.
3. Optional: Nutze den Kategorie-Filter (`Alle Kategorien` oder konkrete Kategorie).
4. Markiere die Zielprodukte (Mehrfachauswahl ist aktiv).

## Brand im Bulk setzen
1. Klick auf `Brand fuer Auswahl setzen`.
2. Neue Brand eingeben.
3. Vorschau bestaetigen (Dry-Run-Auswertung: geaendert/uebersprungen).
4. Entscheiden, ob zusaetzlich Wix aktualisiert werden soll.
5. Falls Wix aktiv: optional bestaetigen, ob fehlende Brand in Wix automatisch angelegt werden soll.

## Ergebnisinterpretation
- Geaendert (lokal): Anzahl lokal geaenderter Produkte.
- Wix versucht: Anzahl Wix-Updateversuche.
- Wix erfolgreich / Wix Fehler: Ergebnis des Kanal-Writebacks.
- Brand aufgeloest: Brand-ID in Wix gefunden/ermittelt.
- Brand neu angelegt: Brand wurde in Wix neu erstellt.

## Typische Fehlerbilder
- Kein Wix-Produkt zugeordnet:
  - Produkt hat keine Wix-ID und konnte nicht per SKU aufgeloest werden.
- Wix-Writeback fehlgeschlagen:
  - API nicht erreichbar, Auth fehlt/ungueltig, Endpoint weist Payload ab.
  - Bei transienten Fehlern greift Retry automatisch.

## Hinweise
- Updates laufen immer zuerst lokal, danach optional in Wix.
- Wenn nur lokal gewaehlt wird, bleibt Wix unveraendert.
- `Stores/Products` Collection wird nicht direkt beschrieben; Updates laufen ueber Product-APIs.
