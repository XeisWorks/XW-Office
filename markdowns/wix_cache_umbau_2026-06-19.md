# Wix-/sevDesk-Caching Umbau

## Ziel

Die Rechnungsansicht soll Zeilenauswahl und Analysis-Panel sofort reagieren lassen. Wix-Daten werden lokal persistent gecacht, weil Bestell-Stammdaten fuer diesen Workflow stabil genug sind. sevDesk-Daten bleiben vorsichtiger behandelt, weil Rechnungen im sevDesk-UI geaendert werden koennen.

## Phase 1: Lokaler Wix-Order-Cache

- SQLite-Datei unter `state/xw_office_cache.sqlite`.
- Speicherung der rohen Wix-Order pro Site/Account/Reference.
- Abgeleitete Daten wie Adresse, Summary, Digitalstatus und Line-Items werden aus derselben Order berechnet.
- Negative Lookups werden nur kurz gecacht, damit frisch synchronisierte Orders nicht blockiert werden.

## Phase 2: Wix-Client Read-Through

- `WixOrdersClient.resolve_order()` nutzt zuerst den lokalen Cache.
- Bei Cache-Miss wird Wix abgefragt und das Ergebnis persistiert.
- Mutable Fulfillment-Endpunkte fragen weiterhin live ab; nur die Order-ID/Line-Items duerfen aus dem Cache kommen.

## Phase 3: START und Analysis Panel

- START-Prefetch profitiert automatisch vom persistierten Cache.
- Das Analysis Panel nutzt vorhandene In-Memory-Daten weiter, bekommt aber nach Neustart ebenfalls schnelle Wix-Daten.
- Doppelte Resolve-Aufrufe werden reduziert, weil Summary/Adresse/Digital/Line-Items aus demselben Snapshot kommen.

## Phase 4: sevDesk nur defensiv

- Kein dauerhafter sevDesk-Rechnungscache in dieser Phase.
- Bestehende Detail-/PDF-Caches bleiben In-Memory.
- Spaeter sinnvoll: kurze TTLs fuer Rechnungsliste/Details und gezielte Invalidierung nach App-Aktionen.

## Phase 5: Wartung

- Cache kann spaeter im Settings-Bereich sichtbar gemacht werden: Groesse, Anzahl Orders, Cache leeren.
- Retention optional: z.B. Orders aelter als 180 Tage entfernen.
