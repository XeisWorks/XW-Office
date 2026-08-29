# XW-Office – Performance Deep Dive / Codex-Umsetzungsplan

**Repository:** `XeisWorks/XW-Office`  
**Analysierter Stand:** `main`, HEAD zum Analysezeitpunkt: `5267e25af9347547b85de603f9a9ada967579e18`  
**Fokus:** `RECHNUNGEN`, Rechnungswechsel, PLC-Popup, `PRINT PRODUKTE OFFEN`  
**Methode:** statische Codeanalyse der relevanten UI-, Service-, Cache-, Wix-, sevDesk- und PLC-Pfade.  
**Wichtig:** Die Ursachen sind im Code klar erkennbar; reale P50/P95-Zeiten wurden nicht auf dem Produktiv-PC gemessen. Phase 0 ergänzt deshalb gezielte Telemetrie, bevor/parallel zu den Änderungen.

---

## Executive Summary

Ja – es gibt **deutliche, grundsätzliche Performance-Hebel**.

Das Problem ist nicht primär „zu wenig Caching“. XW-Office cached bereits an vielen Stellen sinnvoll. Das größere Problem ist:

> **Auf einem UI-Ereignis hängen noch zu viele voneinander unabhängige Arbeiten, darunter N+1-Netzwerkzugriffe, sequenzielle Cold-Cache-Auflösungen und synchrone Datei/PDF-Prüfungen.**

Die fünf wichtigsten Ursachen:

1. **P0 – sevDesk-Lagerstand als N+1-Netzwerkproblem beim Rechnungswechsel**  
   `PrintDecisionEngine.get_piece_blocks()` baut die Stückeliste auf und fragt für jedes physische Produkt einzeln `PartClient.get_part_stock()` ab. Bei unbekannten Produkten kann zusätzlich `find_part_by_sku()` ins Netz gehen. Ein Wix-Cache-Hit verhindert diese sevDesk-Aufrufe nicht.

2. **P0 – `PRINT PRODUKTE OFFEN` wird Rechnung für Rechnung sequenziell aufgelöst**  
   Bis zu 50 offene Rechnungen werden vollständig nacheinander analysiert. Cache-Misses können Wix-Aufrufe erzeugen. Das Ergebnis wird erst nach Abschluss des gesamten Laufs vollständig geliefert.

3. **P0/P1 – Wix Cold Path ist unnötig teuer**  
   Order-Suchen erzeugen wiederholt neue `httpx.Client`-Instanzen. Eine Order kann mit mehreren Suchvarianten gesucht werden. Danach wird die Order **vor dem finalen Cache-Schreiben** noch um Produktkategorien angereichert, was pro unbekanntem Produkt weitere Wix-Produktaufrufe auslösen kann. Parallel laufende Jobs können denselben Ref gleichzeitig auflösen, weil ein „single-flight“/in-flight dedupe fehlt.

4. **P1 – Rechnungswechsel besitzt Head-of-Line-Blocking bei sevDesk-Details**  
   Es gibt effektiv einen seriellen `_invoice_detail_worker`. Wird während eines laufenden Requests eine andere Rechnung gewählt, muss der alte blockierende Netzwerkrequest zuerst fertig werden, bevor die aktuelle Auswahl drankommt.

5. **P1 – PLC-Klick kann synchron Dateisystem/PDF-Arbeit auf dem Qt-Main-Thread ausführen**  
   Archiv-Lookups und bei bestehenden Zoll-PDFs `ensure_customs_a5_print_file()` laufen vor Anzeige des Popups/Dialogs. Das kann Glob/Stat/PyMuPDF-Arbeit enthalten. Auf langsamen/gesyncten Pfaden ist das direkt als UI-Lag sichtbar.

### Erwartete Wirkung

Wenn nur Phase 1–3 sauber umgesetzt werden, sollte sich der Bereich `RECHNUNGEN` **spürbar bis deutlich** schneller anfühlen:

- warm/cached Rechnungswechsel: nahezu sofortige UI-Reaktion;
- Stückeliste ohne eine sevDesk-Abfrage pro Position;
- aktuelle Auswahl wird nicht mehr von einem alten Detailrequest blockiert;
- `PRINT PRODUKTE OFFEN` zeigt Cache-Ergebnisse sofort und lädt nur unbekannte Orders nach;
- Wix Cold Cache profitiert von Connection Reuse, Single-Flight und früherem Raw-Order-Caching;
- PLC-Popup öffnet ohne Dateisystem-/PDF-Scan im Click-Handler.

---

# Befund im Detail

## 1. P0 – Größter Hebel beim Rechnungswechsel: Lagerstand-N+1

### Aktueller Pfad

Beim Auswählen einer Rechnung wird der Wix-Kontext geladen. Nach Order-Summary und Wix-Line-Items wird ausgeführt:

```python
engine: PrintDecisionEngine = self._container.resolve(PrintDecisionEngine)
pieces = engine.get_piece_blocks(wix_items, invoice_ref=ref)
```

`PrintDecisionEngine._build_block()` ruft bei einem physischen Produkt mit sevDesk-Part-ID:

```python
on_hand = self._fetch_stock_safe(product.sevdesk_part_id)
```

und darin:

```python
self._part_client.get_part_stock(sevdesk_part_id)
```

`PartClient.get_part_stock()` führt einen HTTP-GET zu `/Part/{part_id}/getStock` aus; bei Fehler sogar noch einen zweiten Fallback-GET.

### Warum das trotz Caching langsam bleibt

Der Wix-Order-Cache kann 100 % treffen und der Rechnungswechsel kann trotzdem mehrere externe HTTP-Aufrufe benötigen:

- 1 physisches Produkt = bis zu 1 sevDesk-Stockrequest;
- 6 physische Positionen = bis zu 6 Requests;
- unbekannte SKU = eventuell zusätzlich `find_part_by_sku()`.

Das ist klassisches **N+1 I/O**.

### Zielarchitektur

Ein `StockSnapshotService` bzw. eine Cache-Schicht vor `PartClient`:

- hält `part_id -> stock` und optional `sku -> part` im RAM;
- TTL z. B. 30–60 Sekunden;
- **stale-while-revalidate**: UI liest sofort den letzten Snapshot;
- Snapshot wird im Hintergrund in einem Bulk-Lauf aktualisiert;
- bevorzugt `PartClient.list_parts(refresh_cache=True)` / eine paginierte Part-Liste statt Einzelrequest pro Position;
- nach `set_part_stock()` wird der Cache gezielt aktualisiert oder invalidiert;
- ein manueller Refresh bleibt möglich.

### Wichtige Designregel

`PrintDecisionEngine.get_piece_blocks()` darf für die reine Darstellung einer Rechnung **keinen synchronen Einzel-Netzwerkzugriff pro Produkt** mehr benötigen.

### Erwarteter Impact

**Sehr hoch**, speziell bei Rechnungswechseln mit mehreren physischen Produkten.

---

## 2. P0 – `PRINT PRODUKTE OFFEN`: serieller Fan-out über bis zu 50 Rechnungen

`resolve_open_invoice_overview()` iteriert die offenen Rechnungen sequenziell.

Pro Rechnung können u. a. entstehen:

- `resolve_invoice_list_hints(ref)`;
- Digital/Physical-Ermittlung;
- Line-Item-Auflösung;
- bei Cache-Miss Wix-Auflösung.

Die View lädt automatisch bis zu 50 offene Rechnungen. Ein kompletter Cold-/Partial-Cold-Lauf wird damit zu einer seriellen Kette.

### Zusätzliche Schwäche

Die UI hat zwar eine schnelle cache-basierte Voransicht, aber die vollständigen Print-Produkte werden erst nach Abschluss der vollständigen Analyse konsistent geliefert. Der User wartet daher sichtbar auf den „langen Schwanz“.

### Zielarchitektur

`OpenInvoiceOverviewResolver` als zweistufige Pipeline:

#### Stufe A – sofort, cache-only

- vorhandene persistente Wix-Order-Snapshots auswerten;
- Produkte sofort aggregieren;
- Digital/Physical/Hints aus **einem** normalisierten OrderSnapshot ableiten;
- `unknown_refs` sammeln;
- UI innerhalb eines Event-Loop-Turns aktualisieren.

#### Stufe B – nur Unknowns nachladen

- ausschließlich `unknown_refs` extern auflösen;
- Single-Flight pro Ref verwenden;
- bounded parallelism, z. B. 3–4 gleichzeitige Order-Auflösungen;
- Resultate in kleinen Batches zurückmelden;
- UI progressiv aktualisieren;
- keine 50 bereits bekannten Orders erneut durch die volle Resolver-Kette schicken.

### Keine Doppelableitungen

Aus einem gecachten Wix-Orderobjekt sollten gemeinsam erzeugt werden:

- order summary;
- shipping/PLC context;
- line items;
- digital_only;
- buyer note;
- hint flags;
- print-product aggregate inputs.

Nicht dieselbe Order nacheinander über mehrere öffentliche Methoden wieder „auflösen“.

### Erwarteter Impact

**Sehr hoch** für `PRINT PRODUKTE OFFEN`, besonders nach App-Start oder bei neuen Orders.

---

## 3. P0/P1 – Wix Cold Path: Connection Reuse + Raw Cache + Single-Flight

### 3.1 Neuer HTTP-Client pro Request

`WixOrdersClient._get_order_by_id()` und `_search_order_by_field()` verwenden jeweils:

```python
with httpx.Client(timeout=_TIMEOUT) as client:
```

Damit wird der Client/Pool wiederholt neu aufgebaut.

`WixProductDetailsClient` macht dasselbe an mehreren Stellen.

### Änderung

Einen langlebigen, zentral verwalteten Wix-HTTP-Client pro App-/Service-Lifecycle verwenden:

- Keep-Alive/Connection Pool;
- gemeinsame Timeouts;
- gemeinsame Retry-Policy;
- sauberer `close()` beim App-Shutdown;
- testbar durch injizierbaren Transport/Client.

### 3.2 Raw Order wird zu spät gecacht

Nach erfolgreicher Order-Suche wird aktuell zuerst:

```python
_order_with_enriched_line_item_categories(...)
```

ausgeführt und erst danach das Ergebnis gecacht.

Die Kategorieanreicherung kann pro Produkt `WixProductDetailsClient.get_product()` und ggf. eine Category-Query auslösen.

Damit wartet die zentrale Order-Auflösung auf **sekundäre Metadaten**, die für Adresse, PLC, Digitalstatus und die meisten UI-Anzeigen nicht kritisch sind.

### Änderung

1. gefundene Order **sofort raw persistieren**;
2. UI-kritische Normalisierung cache-only durchführen;
3. fehlende Kategorie-Metadaten separat/lazy nachladen;
4. angereicherten Snapshot danach überschreiben.

So können andere Jobs denselben OrderSnapshot bereits verwenden, während optionale Produktmetadaten noch laufen.

### 3.3 Single-Flight fehlt

Cache schützt nur **nach** erfolgreichem Schreiben.

Wenn z. B. gleichzeitig laufen:

- selected Wix context;
- open overview;
- warmup;
- PLC context;
- hint prefetch,

können mehrere Jobs denselben Ref sehen, bevor der erste Request abgeschlossen ist.

### Änderung

Pro `order_ref` eine in-flight Registry:

```text
ref -> Future/Event/Promise
```

- erster Caller startet die externe Auflösung;
- weitere Caller hängen sich an dieselbe laufende Auflösung;
- Resultat/Fehler wird geteilt;
- Registry wird anschließend gelöscht;
- Cancellation eines einzelnen Consumers darf die gemeinsame Order-Auflösung nicht für alle abbrechen.

### Erwarteter Impact

**Hoch bei Cold Cache**, mittel bei warmem Cache.

---

## 4. P1 – Rechnungsdetail: Latest Selection muss sofort starten

Aktuell existiert nur ein aktiver `_invoice_detail_worker`.

Wird Rechnung B gewählt, während Rechnung A noch geladen wird, wird B lediglich vorgemerkt. A kann wegen blockierendem HTTP nicht wirklich abgebrochen werden. B startet erst danach.

### Änderung

Den Detail-Load über `BackgroundJobManager` abwickeln:

- Queue `ui-critical-network`;
- Request-Sequence/Generation beibehalten;
- stale Resultate verwerfen;
- **neue Auswahl darf sofort starten**, auch wenn ein alter Request noch ausläuft;
- bounded concurrency, z. B. 2 für Invoice-Detail;
- nicht unbegrenzt parallelisieren.

Optional danach:

- selected row + 1–2 Nachbarzeilen im Idle-Warmup vorladen;
- kurzer Detail-TTL bzw. Sessioncache weiterverwenden.

### Erwarteter Impact

**Sehr hoch beim schnellen Durchklicken** mehrerer Rechnungen.

---

## 5. P1 – PLC-Popup: im Click-Handler kein Filesystem/PyMuPDF

### Aktuelles Risiko

`_update_plc_controls()` prüft synchron das PLC-Archiv.

Beim Öffnen des PLC-Popups können zusätzlich synchron erfolgen:

- Label-Archiv-Lookup;
- Customs-Archiv-Glob/Stat;
- `ensure_customs_a5_print_file()`;
- Öffnen/Prüfen von PDFs mit PyMuPDF;
- ggf. Erzeugen einer neuen A5-Druckfassung.

### Gute Nachricht

Der eigentliche `PlcLabelPrintDialog` lädt seinen Wix-Kontext bereits sauber per `QTimer.singleShot(0, ...)` + BackgroundWorker. Dieser Teil ist grundsätzlich richtig.

### Änderung

- PLC-Archivindex einmal im Hintergrund aufbauen;
- Label- und Customs-Index gemeinsam O(1)-lesbar halten;
- Index beim Speichern eines PLC-Dokuments inkrementell aktualisieren;
- Main Thread darf nur Snapshot-Lookups machen;
- `ensure_customs_a5_print_file()` nicht vor Anzeige des Dialogs ausführen;
- A5-Derivat bereits beim Archivieren/Empfang erzeugen (passiert nach neuem PLC-Send bereits weitgehend) oder beim Reprint asynchron nachholen;
- beim Click zunächst Dialog/Popup sofort anzeigen.

### Erwarteter Impact

**Hoch**, wenn PLC-Archiv auf langsamem Laufwerk/Sync-Ordner liegt oder viele Dateien enthält.

---

## 6. P2 – Abgeleitete Settings statt immer wieder JSON/DB

`InvoiceProcessingService` lädt SKU-Flags und Länderregeln wiederholt aus dem Settings-Repository und parsed JSON.

Das ist kein Hauptproblem, aber in 50er-Schleifen unnötig.

### Änderung

Kleine immutable/compiled Settings-Snapshots:

- SKU exact/prefix/suffix;
- allowed/sensitive countries;
- ggf. weitere Hint-Regeln.

Invalidierung nur bei Settings-Änderung.

### Erwarteter Impact

**Klein bis mittel**, aber billig und sauber.

---

# Empfohlene Bauphasen

## Phase 0 – Messbarkeit und Regression Guardrails

**Ziel:** Änderungen messbar machen, ohne Produktivlogik umzubauen.

Implementieren:

- Action spans:
  - `invoice_select_to_immediate_paint_ms`
  - `invoice_select_to_detail_ms`
  - `invoice_select_to_wix_context_ms`
  - `invoice_select_to_piece_blocks_ms`
  - `plc_click_to_dialog_visible_ms`
  - `open_overview_first_cached_ms`
  - `open_overview_complete_ms`
- Counters:
  - Wix cache hit/miss;
  - Wix upstream calls pro Ref;
  - sevDesk stock upstream calls pro Rechnungswechsel;
  - single-flight joined/started;
  - PLC archive full scan count;
  - Event-loop stalls > 50/100/250 ms.
- Fake-latency Tests für UI-Orchestrierung.

**Exit-Kriterium:** Vorher/Nachher kann reproduzierbar verglichen werden.

---

## Phase 1 – Rechnungswechsel entkoppeln

**Priorität: höchste**

### 1A StockSnapshot / N+1 eliminieren

- `PartClient` oder neuer `StockSnapshotService`;
- TTL/Stale-while-revalidate;
- `PrintDecisionEngine` ausschließlich Snapshot-Lookup im UI-Kontext;
- gezielte Invalidation nach Stock-Write.

### 1B Detail latest-wins

- `_invoice_detail_worker`-Serialisierung entfernen;
- `BackgroundJobManager` + seq guard;
- concurrency=2;
- stale response ignorieren.

### 1C Keine Main-Thread-Archivarbeit beim Row Select

- `_update_plc_controls()` darf keine ungebremste Archiv-Rescan-Arbeit triggern;
- nur Cache/Index-Snapshot.

**Exit-Kriterien:**

- warm selection zeigt sofort den neuen Row-Kontext;
- bei 5 schnellen Klicks beginnt die letzte Detailanforderung ohne auf die erste zu warten;
- bei Wix-Cache-Hit: **0 sevDesk-Stock-HTTP-Requests pro Position**;
- keine PLC-Glob/PDF-Prüfung auf dem Qt-Main-Thread.

---

## Phase 2 – Wix I/O-Schicht optimieren

### 2A langlebige Clients

- shared/injected `httpx.Client`;
- Connection pooling;
- Lifecycle/close;
- Testtransport injizierbar.

### 2B Raw-order-first caching

- raw Order sofort persistieren;
- category enrichment vom kritischen Pfad entkoppeln.

### 2C single-flight per order ref

- kein doppeltes Cold-Resolve derselben Order durch konkurrierende Jobs.

### 2D Produktmetadaten ebenfalls poolen/bündeln

- ProductDetails-Client denselben HTTP-Transport nutzen;
- fehlende Kategorieinfos lazy/batch nachladen;
- bestehende 7-Tage-Metacaches weiterverwenden.

**Exit-Kriterien:**

- pro Cold-Ref maximal **eine** gleichzeitige Order-Auflösung;
- Cache-Hit erzeugt 0 Wix-HTTP-Requests;
- ein gefundener Raw-Snapshot ist verfügbar, bevor optionale Produktkategorien fertig sind;
- keine Neuerzeugung eines HTTP-Clients pro Wix-Request.

---

## Phase 3 – `PRINT PRODUKTE OFFEN` neu aufbauen

### 3A Cache-only first

- alle bekannten OrderSnapshots lokal auswerten;
- Produktliste sofort anzeigen;
- unknown refs separat sammeln.

### 3B Unknown-only + bounded parallelism

- nur Missing Refs extern laden;
- max. 3–4 gleichzeitig;
- Single-Flight verwenden.

### 3C Progressive Resultate

- nach jedem Batch oder jeder fertiggestellten Order die Aggregate ergänzen;
- UI nicht bis zur letzten von 50 Orders blockieren.

### 3D Derived OrderAnalysis

Optional, aber empfohlen:

```python
OrderAnalysisSnapshot(
    ref,
    digital_only,
    buyer_note,
    shipping,
    line_items,
    hint_flags,
    analyzed_at,
)
```

Aus dem persistierten Wix-Rawsnapshot ableiten und ebenfalls cachebar halten.

**Exit-Kriterien:**

- bei vollständig warmem Cache: `PRINT PRODUKTE OFFEN` ohne Netzwerk;
- erste sinnvolle Produktanzeige < 150 ms als Ziel auf normalem Büro-PC;
- Cold/Partial-Cold: progressive Anzeige;
- niemals 50 bekannte Rechnungen seriell durch einen Remote-fähigen Resolver schicken.

---

## Phase 4 – PLC Fast Path

- gemeinsamer Label/Customs-Archivindex;
- Background-Initialisierung;
- inkrementelles Update nach Save;
- `ensure_customs_a5_print_file()` aus Click-Handler entfernen;
- Reprint-Derivat asynchron bei Bedarf erzeugen.

**Exit-Kriterien:**

- PLC-Dialogshell < 100 ms sichtbar als Ziel;
- kein `glob`, kein großes Archiv-Scan, kein PyMuPDF-Open/Render vor Dialoganzeige;
- bestehende Labels/Zollformulare bleiben funktional identisch.

---

## Phase 5 – Konsolidierung

Erst nach gemessener Verbesserung:

- `rechnungen/view.py` in Controller/Resolver/Widgets zerlegen;
- Settings-Regeln compiled cachen;
- duplicate cache layers dokumentieren;
- Cache Ownership definieren:
  - Wix raw order: persistent order cache;
  - order analysis: derived cache;
  - selected UI context: short/session presentation cache;
  - stock: short-lived snapshot;
  - PLC archive: filesystem index snapshot.
- keine „noch einen Cache daneben“-Lösung ohne definierte Source-of-Truth/Invalidierung.

**Wichtig:** Das Aufteilen der 244-KB-`view.py` ist Wartbarkeitsarbeit und **nicht** als alleinige Performance-Lösung zu verkaufen.

---

# Prioritätenliste

| Rang | Maßnahme | Impact | Risiko | Confidence |
|---|---|---:|---:|---:|
| 1 | sevDesk Stock-N+1 durch StockSnapshot ersetzen | sehr hoch | niedrig–mittel | sehr hoch |
| 2 | Open Overview cache-first / unknown-only / progressiv | sehr hoch | mittel | sehr hoch |
| 3 | Wix shared HTTP pool + raw-first cache + single-flight | hoch–sehr hoch | mittel | sehr hoch |
| 4 | Invoice detail latest-wins statt serieller Worker | hoch | niedrig–mittel | sehr hoch |
| 5 | PLC Archiv/PDF I/O vom Main Thread entfernen | hoch bei PLC-Lag | niedrig–mittel | sehr hoch |
| 6 | Settings-/Hint-Regeln compiled cachen | klein–mittel | niedrig | hoch |
| 7 | `rechnungen/view.py` modularisieren | indirekt | mittel | hoch |

---

# Konkrete Codex-Dateien / Hotspots

## Hauptdateien

- `src/xw_office/ui/modules/rechnungen/view.py`
- `src/xw_office/ui/modules/rechnungen/open_invoice_overview.py`
- `src/xw_office/ui/modules/rechnungen/plc_label_dialog.py`
- `src/xw_office/services/products/print_decision.py`
- `src/xw_office/services/sevdesk/part_client.py`
- `src/xw_office/services/wix/client.py`
- `src/xw_office/services/wix/product_details_client.py`
- `src/xw_office/services/wix/order_cache.py`
- `src/xw_office/services/invoice_processing/service.py`
- `src/xw_office/services/plc/label_archive.py`
- `src/xw_office/services/plc/customs_document.py`
- `src/xw_office/services/background_jobs/service.py`
- `src/xw_office/ui/performance.py`

## Neue Dateien – Vorschlag

- `src/xw_office/services/sevdesk/stock_snapshot.py`
- optional `src/xw_office/services/wix/order_context.py`
- optional `src/xw_office/services/performance/metrics.py`

Nicht zwangsläufig neue Dateien anlegen, wenn Codex eine kleinere, sauber testbare Änderung in bestehender Struktur bevorzugt.

---

# Technische Leitplanken für Codex

1. **Keine Änderung der fachlichen Logik** nur um Performance zu gewinnen.
2. **Keine unbegrenzte Parallelisierung.**
3. UI-kritische Requests haben Vorrang vor Warmup/Overview.
4. Blocking I/O niemals auf Qt-Main-Thread.
5. `cancel()` bei Netzwerkjobs nicht als echten Abbruch betrachten; stale-results per generation/seq verwerfen.
6. Single-Flight verhindert Duplicate Work.
7. Cache-Invaliderung explizit definieren.
8. Bestandsdaten dürfen kurz stale sein, wenn die UI das erlaubt; Stock-Write muss Snapshot sofort aktualisieren.
9. Persistenter Wix-Raw-Cache bleibt Source of Truth für Wix-Snapshots.
10. Kategorie-/Produktmetadaten dürfen die zentrale Order-Auflösung nicht blockieren.
11. Neue Performance-Optimierung muss mit Tests gegen Request-Anzahl abgesichert werden.
12. Keine willkürliche Erhöhung der Threadzahl als „Fix“.

---

# Empfohlene Tests

## Stock

- `get_piece_blocks()` mit 10 Positionen und warmem StockSnapshot -> 0 HTTP calls;
- bei leerem Snapshot -> genau 1 Background-Bulk-Refresh, nicht 10 Einzelrequests;
- `set_part_stock()` aktualisiert/invaldiert Snapshot;
- stale snapshot liefert sofort Wert und refresh läuft im Hintergrund.

## Wix

- 3 gleichzeitige `resolve_order("12345")` -> genau 1 upstream order search;
- cache hit -> 0 upstream;
- raw order wird gespeichert, auch wenn category enrichment langsam/fehlerhaft ist;
- mehrere Requests verwenden denselben Client/Transport;
- Product category failure darf Order Summary/PLC nicht verzögern oder zerstören.

## Rechnungswechsel

Mit Fake-Netzwerk:
- Rechnung A: 2 s Detailrequest;
- 100 ms später Rechnung B anklicken;
- B muss sofort einen Request starten dürfen;
- Antwort A darf UI B niemals überschreiben.

## Open Overview

- 50 Orders, davon 45 cached / 5 missing:
  - genau 5 Remote Resolves;
  - nicht 50;
- Warm cache -> 0 Remote;
- Batch-Resultate aktualisieren Produkte progressiv;
- dedupe gleicher Ref.

## PLC

- Klick auf PLC bei 2.000 Archivdateien:
  - kein synchroner Full-Glob im Click-Handler;
  - kein `fitz.open()` vor Dialogsichtbarkeit;
- fehlendes A5-Derivat wird asynchron erstellt;
- vorhandenes Derivat wird ohne Regeneration genutzt.

---

# Zielwerte

Diese Werte sind **Performance Budgets**, keine Behauptung über die heutige Laufzeit.

| Aktion | Ziel |
|---|---:|
| UI-Reaktion auf Rechnungswahl / Skeleton | < 50 ms |
| Warm cached Rechnungsdetail | < 150 ms |
| Start der neuesten Auswahl trotz altem Request | < 50 ms |
| PLC Dialogshell sichtbar | < 100 ms |
| `PRINT PRODUKTE OFFEN` warm: erste vollständige lokale Aggregation | < 150–300 ms |
| Cache-hit Wix calls | 0 |
| Stock HTTP calls pro warmem Rechnungswechsel | 0 |
| Gleichzeitige Wix Resolve Calls pro Ref | max. 1 |
| Main-thread PLC glob/PDF parse | 0 |

Für Cold-Cache-Netzwerkzeiten keine unrealistischen absoluten Grenzen erzwingen; stattdessen Request-Anzahl, Parallelitätsgrenze und Time-to-first-result messen.

---

# Was ich ausdrücklich NICHT als Hauptlösung empfehle

- noch mehr TTL-Caches blind hinzufügen;
- `QThreadPool`/BackgroundWorker-Zahl einfach erhöhen;
- alle 50 offenen Rechnungen parallel losschicken;
- `rechnungen/view.py` nur aufteilen und Performancegewinn erwarten;
- persistente Wix-Caches kürzer machen;
- Stockwerte bei jedem Row-Select „zur Sicherheit“ live neu verifizieren.

---

# Codex-Auftrag

Implementiere die Performance-Optimierung **phasenweise**.

Nach jeder Phase:

1. Tests ausführen;
2. Request-Counter/Timing vergleichen;
3. keine fachliche Regression;
4. Commit mit Phase-ID;
5. erst danach nächste Phase.

Reihenfolge:

```text
P0 Measurement
→ P1 StockSnapshot + latest-selection
→ P2 Wix transport/raw-cache/single-flight
→ P3 Open Overview
→ P4 PLC Fast Path
→ P5 Cleanup
```

Wenn eine geplante Optimierung aufgrund der realen APIs/Tests keinen messbaren Nutzen bringt, **nicht erzwingen**. Dokumentieren und überspringen.

---

# Fazit

Die Performanceprobleme sind **nicht eingebildet und nicht durch „ein bisschen mehr Cache“ zu lösen**.

Die Architektur cached viele Daten bereits, aber auf dem kritischen UI-Pfad werden noch:

- einzelne Live-Bestandsrequests pro Produkt,
- mehrere sequenzielle Order-Auflösungen,
- optionale Produktmetadaten vor dem Raw-Cache,
- alte blockierende Requests,
- und PLC-Datei/PDF-Arbeit

ausgeführt.

Der größte unmittelbare Gewinn dürfte aus der Kombination entstehen:

> **StockSnapshot + latest-wins UI requests + Wix single-flight/raw-first + unknown-only Open Overview.**

Diese Änderungen greifen direkt an der Anzahl externer Roundtrips und am Head-of-Line-Blocking an und haben daher deutlich mehr Potenzial als weitere Mikro-Caches.
