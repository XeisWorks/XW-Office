# Rechnungen Performance-Umbau - Analyse und Phasenplan

Stand: 2026-07-01

## Ziel

Das Untermenue `Rechnungen` soll nach App-Start und bei taeglicher Bedienung schneller und eindeutiger reagieren.

Prioritaeten:

- Nach einem Klick muss sofort sichtbar sein, dass die App reagiert hat.
- Die Rechnungsauswahl in der Liste muss sofort sichtbar umspringen.
- Detail-/Analysis-Felder duerfen danach asynchron aus Cache/API nachziehen.
- Cache-, Warmup- und START-Pfade sollen weniger doppelte Arbeit machen.
- Externe Live-Abhaengigkeiten werden nicht erweitert; Ausnahme bleiben bestehende Fulfillment-Mails.

## Ist-Ablauf nach App-Start

1. `MainWindow` oeffnet nach Aufbau direkt `ModuleKey.RECHNUNGEN`.
2. `TagesgeschaeftView` wird lazy erzeugt und baut die obere Aktionsleiste plus eingebettete `RechnungenView`.
3. `TagesgeschaeftView.showEvent()` startet Badge-Refresh fuer offene Rechnungen, Sendungen, Transfers und Mollie.
4. `RechnungenView.showEvent()` startet den ersten Rechnungs-Load, wenn ein sevDesk-Token vorhanden ist.
5. `RechnungenView._start_load()` laedt zuerst Entwuerfe (`status=100`), danach bei Bedarf offene Rechnungen (`status=200`).
6. Nach dem List-Load laufen im Hintergrund:
   - Wix-Kontext-Warmup fuer aktive Entwuerfe.
   - Hint-Prefetch fuer Rechnungsliste.
   - Open-Invoice-Uebersicht aus bereits bekannten Daten.

Guter Bestand:

- Der eingebettete `RechnungenView`-Toolbar-/Badge-Refresh wird vom Parent deaktiviert. Damit wird ein offensichtlicher Doppel-Poll bereits vermieden.
- Wix-Meta und Produktpositionen laufen ueber einen gemeinsamen Kontextloader.
- Stale-Result-Guards fuer schnellen Zeilenwechsel sind vorhanden.
- Es gibt bereits einen persistenten Wix-SQLite-Cache und einen UI-TTL-Cache.

## Ist-Ablauf bei Rechnungswechsel

Aktuell passiert in `RechnungenView._refresh_detail_for_selection()` sofort alles in einem Zug:

1. Auswahl lesen.
2. Summary-Felder im Detailpanel setzen.
3. Wix-Felder zuruecksetzen.
4. Persistent Cache fuer Wix-Meta und LineItems synchron pruefen.
5. Produktbloecke aus Cache rendern, falls vorhanden.
6. Sonst Wix-Kontextworker starten.
7. sevDesk-Detailkontext aus Service-Cache anwenden oder async laden.

Problem:

- Der Benutzer will zuerst die neue Auswahl sehen. Synchronous Cache-Lookups und Produkt-Rendering duerfen dieses visuelle Umspringen nicht blockieren.
- `clicked`/Release-basierte Auswahl fuehlt sich bei langen UI-Aktualisierungen traege an.

Ziel:

- Auswahl und Kernfelder sofort setzen.
- Cache-/Detail-Hydration per `QTimer.singleShot(0, ...)` nachziehen.
- Stale-Guard ueber Selektionssequenz beibehalten.

## Ist-Ablauf bei START

Direktklick `START`:

1. Aktive Worker werden geprueft.
2. Optional werden markierte Rechnungen eingesammelt.
3. START-Button wird deaktiviert.
4. Statusbar zeigt `Pre-Flight wird erstellt`.
5. Preflight-Worker startet.
6. Ohne `+ Noten` wird kein Dialog gezeigt, sondern direkt die Produktpruefung vorbereitet.
7. Danach startet der eigentliche Batchworker.

Problem:

- Der Button ist zwar technisch deaktiviert, aber ohne sofortiges Repaint/Textwechsel wirkt der Klick manchmal nicht bestaetigt.
- Beim normalen START erscheint kein Popup vor dem laengeren Preflight.
- Der START-Pfad laedt offene Entwuerfe mehrfach: Count/Preflight, Produktcheck, Batchlauf. Fuer `START Selected` ist das besonders vermeidbar.

Ziel:

- START-Button sofort deaktivieren, Text auf Busy-Zustand setzen und UI-Events flushen.
- Im Analysis-Panel sofort eine START-Vorbereitungszeile anzeigen.
- STOP sofort nach START-Klick aktivieren; ein Klick waehrend Preflight verhindert den folgenden Batch.
- Fuer `START Selected` die bereits selektierten Summaries/IDs weiterreichen und nicht unnoetig alle Entwuerfe laden.

## Ist-Ablauf bei Detail-Buttons

Manuelle Buttons:

- `Rechnung drucken`
- `Label drucken`
- `PLC-Label drucken`
- `Noten drucken`
- `Rechnung senden`
- Fulfillment-Chips in der Liste

Problemstellen:

- Einige Aktionen zeigen zwar ein Overlay, lassen den geklickten Button aber optisch aktiv.
- `Rechnung drucken` und `Label drucken` laden nach Erfolg aktuell die komplette erste Seite neu. Fuer reine Fulfillment-Flags ist das teurer als noetig.
- In den Result-Handlern fuer Direktdruck gibt es unerreichbaren Dialog-Code nach einem fruehen `return`.

Ziel:

- Detail-Aktionsbuttons waehrend eines laufenden Einzeljobs deaktivieren.
- UI sofort repainten.
- Erfolgreiche Fulfillment-Flags direkt in der sichtbaren Tabellenzeile patchen.
- Vollstaendigen Listen-Reload nur dort behalten, wo sich Rechnungsstatus oder Datenmenge wirklich aendern, z.B. nach START.

## Umbauphasen

### Phase 1 - Sofortiges Klick-Feedback

Status: umgesetzt

Umfang:

- START-Button: sofort Busy-Text, deaktivieren, Event-Flush.
- START-Vorbereitung sofort im Analysis-Panel anzeigen.
- Detail-Aktionsbuttons bei Druck/Mail/Fulfillment sofort deaktivieren.
- STOP sofort nach START-Klick aktivieren und Preflight-Abbruch vor dem Batch respektieren.
- Produktdruck deaktiviert den Hauptbutton ebenfalls sofort.

Risiko: gering. Keine Service-Logik, nur UI-Zustand.

### Phase 2 - Optimistischer Rechnungswechsel

Status: umgesetzt

Umfang:

- Normale linke Mausklicks auf Rechnungszeilen bereits bei MousePress selektieren.
- Summary-Felder sofort anzeigen.
- Wix-/sevDesk-Cache-Hydration per naechstem Eventloop-Tick nachziehen.
- Stale-Auswahl ueber Sequenznummer pruefen.

Risiko: mittel. Muss ExtendedSelection fuer `START Selected` respektieren.

### Phase 3 - Reloads nach Einzelaktionen reduzieren

Status: umgesetzt

Umfang:

- Fulfillment-Flag-Patches direkt in sichtbare Zeilen schreiben.
- Keine komplette erste Seite nach Einzel-Druck/Mail/Chip-Retry reloaden.
- Erfolgsrueckmeldung ueber Statusbar/Popup je nach Aktion beibehalten.

Risiko: mittel. Sichtbare Liste muss nach Patch konsistent bleiben.

### Phase 4 - START Selected weniger doppelt laden

Status: umgesetzt

Umfang:

- Selektierte Summaries fuer Produkt-Preflight verwenden.
- Service-seitig bei `invoice_ids` gezielt per ID laden statt alle offenen Entwuerfe zu laden und danach zu filtern.
- `build_inventory_requirements(invoice_ids=...)` auf denselben Zielmengen-Lader umstellen.
- Falls `fetch_invoice_by_id` keine Order-Referenz liefert, wird nur dann auf die offene Summary-Liste zurueckgegriffen.

Risiko: mittel. START-All bleibt unveraendert, START-Selected wird schlanker.

### Phase 5 - Groesserer START-All Umbau

Status: zurueckgestellt

Moegliche Folgearbeit:

- Gemeinsames Start-Preflight-Objekt mit Summaries, References und Inventory Requirements.
- Einmaliges Laden aller offenen Entwuerfe statt Count + Produktcheck + Batch-Reload.
- Abbruch-/Fehlerberichte mit Zwischenergebnissen ohne Listenreload bis Laufende.

Risiko: hoeher. Erst nach Phase 1-4 und gruener Testbasis sinnvoll.

## Verifikation

Geplante Tests:

- UI-Smoke fuer START-Busy-Zustand.
- UI-Smoke fuer deferred persistent Wix cache apply.
- UI-Smoke fuer sofortige Summary-Anzeige nach Auswahl.
- Unit-/UI-Tests fuer Wix incomplete-cache-Fallback bleiben gruen.
- Ausfuehren:
  - `tests/ui/test_rechnungen_view_smoke.py`
  - `tests/unit/test_wix_orders_client.py`
  - bei Bedarf `tests/unit/test_invoice_processing_service.py`

Gelaufen am 2026-07-01:

- `python -m py_compile src/xw_studio/ui/modules/rechnungen/view.py src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py src/xw_studio/services/invoice_processing/service.py tests/ui/test_rechnungen_view_smoke.py`
- `python -m pytest tests/ui/test_rechnungen_view_smoke.py tests/unit/test_wix_orders_client.py` -> 35 passed
- `python -m pytest tests/unit/test_invoice_processing_service.py tests/unit/test_invoice_processing_fullflow.py tests/unit/test_invoice_processing_count.py` -> 28 passed
- `python -m pytest tests/unit/test_rechnungen_product_print.py` -> 3 passed
- `python -m pytest tests/integration/test_rechnungen_rapid_switch.py` -> 5 passed
- `python -m pytest tests/ui/test_rechnungen_search.py tests/ui/test_rechnungen_download_links.py` -> 3 passed
- `python -m ruff check` auf den geaenderten Python-Dateien -> passed

## Umgesetzte Dateien

- `src/xw_studio/ui/modules/rechnungen/tagesgeschaeft_view.py`
- `src/xw_studio/ui/modules/rechnungen/view.py`
- `src/xw_studio/services/invoice_processing/service.py`
- `tests/ui/test_rechnungen_view_smoke.py`
- bestehender Wix-Incomplete-Cache-Fix in `src/xw_studio/services/wix/client.py` und `tests/unit/test_wix_orders_client.py` blieb erhalten.
