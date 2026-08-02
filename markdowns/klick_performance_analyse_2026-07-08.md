# Klick-Performance-Analyse XW-Office

Datum: 2026-07-08  
Scope: Klickverhalten, Modulwechsel, Untermenues, Rechnungen/Tagesgeschaeft, Tabellen, Background-Work, weitere Performance-Umbauten.

## Kurzfazit

Die App ist nicht deshalb traege, weil jeder Klick direkt im UI-Thread Netzwerkarbeit macht. Viele kritische Services laufen bereits in `BackgroundWorker`. Die gefuehlte Traegheit entsteht vor allem durch diese Muster:

1. Nach Klicks startet oft sofort ein langer Worker ohne klare Zwischenzustaende fuer jeden Teilprozess.
2. Einige teure Initialisierungen passieren noch synchron im UI-Thread, vor allem Modulmaterialisierung, Druckererkennung und grosse Widget-Baeume.
3. Tabellen werden in mehreren Modulen mit vielen `QTableWidgetItem` oder Model-Resets komplett neu aufgebaut.
4. Rechnungen triggert nach dem sichtbaren Laden mehrere Nebenprozesse: Open-Overview, Hint-Prefetch, Wix-Warmup, Badge-Refresh.
5. Echte Logs zeigen lange externe Phasen: Wix-Warmup ca. 19-20 s pro 6er-Batch, START gesamt ca. 300 s fuer 11 Rechnungen, Wix-Fulfillment ca. 16-18 s pro Rechnung und Mail ca. 7-11 s pro Rechnung.

Die wichtigste Zielarchitektur: Klicks duerfen nur UI-Zustand aendern und Jobs in eine zentrale Background-Schicht einreihen. Alle Netzwerk-, Druck-, Analyse-, Tabellen- und Warmup-Aufgaben muessen entkoppelt, begrenzt parallelisiert, abbrechbar bzw. ersetzbar und progressfaehig sein.

## Umbauphasen

### Phase 1 - Sofort wirksame Rechnungen-Fixes

Status: umgesetzt

- Nach Entwuerfen werden nicht mehr nur `Bezahlt (1000)`, sondern die neuesten Nicht-Entwuerfe geladen.
- Gesamtliste wird nach Aktualitaet zentral absteigend sortiert, auch nach gestuftem Nachladen.
- PLC-Archivlookup wurde ueber Index + View-Cache beschleunigt.
- Rechnungen-Page wird beim Navigieren deterministisch/materialisiert geladen, ohne Placeholder-Race.

### Phase 2 - Klickpfad Rechnungen entlasten

Status: umgesetzt

- Wix-Warmup wurde von aggressivem Voll-Listen-Warmup auf kleine, sichtungsnahe Batches reduziert.
- Warmup startet verzoegert und konkurriert dadurch weniger mit den ersten Zeilenklicks.
- Solange direkte Detailloads laufen (`invoice detail`, `selected wix context`), werden keine weiteren Warmup-Batches gestartet.
- Druckererkennung fuer `MainWindow` und `RechnungenView` laeuft jetzt ueber einen Kurzzeit-Cache und im Rechnungen-View erst nach dem ersten Paint.

### Phase 3 - Nächste Rechnungen-Optimierungen

Status: teilweise umgesetzt

- Selektionsnahe Prefetch-Strategie weiter schaerfen: aktuelle Zeile, Nachbarzeilen, dann erst Rest.
  Status: umgesetzt
- Open-Overview vollstaendig in Worker/Queue mit Revision-Gating verlagern.
  Status: teilweise umgesetzt
- Hints nicht mehr listenweit anschieben, sondern priorisiert nach sichtbaren/selektierten Zeilen.
  Status: umgesetzt
- Logging um echte Phasen erweitern: `draft-load`, `recent-non-draft-load`, `selected-detail-load`, `warmup`.
  Status: umgesetzt

### Phase 4 - Strukturumbauten ausserhalb Rechnungen

Status: teilweise umgesetzt

- Printer-Status in dedizierten Service ueberfuehren.
  Status: umgesetzt
- Generischen Background-Job-Manager mit Prioritaeten/Coalescing einfuehren.
  Status: umgesetzt (aktuell fuer Rechnungen-Nebenjobs)
- Tabellen in Produkte/Clearing/Kalkulation auf Model/View vereinheitlichen.
  Status: teilweise umgesetzt
- Exporte und weitere Dateioperationen konsequent aus dem UI-Thread ziehen.
  Status: teilweise umgesetzt

## Bereits umgesetzte Einzelmaßnahmen

- `recent non-draft invoices` statt nur `status=1000` nach Entwurfsphase
- zentrale Sortierung `invoiceDate desc, id desc`
- begrenztes Wix-Warmup: kleine Batchgroesse, geringere Parallelitaet, verzoegerter Start
- Pause des Warmups waehrend selektionskritischer Detailloads
- Prefetch-Priorisierung nach selektierter Zeile, Nachbarzeilen und sichtbaren Rows
- Open-Overview wird hinter selektionskritischen Detail-Loads zurueckgestellt statt parallel loszulaufen
- Rechnungen-Logging mit expliziten Phasenlabels: `draft-load`, `recent-non-draft-load`, `selected-detail-load`, `selected-wix-context`, `open-overview`
- gecachte Druckererkennung mit TTL
- verzogerter Rechnungen-Druckercheck erst nach erstem Paint
- zentraler `PrinterStatusService` fuer Snapshot + Hintergrundrefresh
- generischer `BackgroundJobManager` mit Prioritaet und Coalescing, derzeit fuer `open-overview`, `hint-prefetch` und `wix-warmup`
- Badge-/Count-Refresh fuer Rechnungen/Tagesgeschaeft ueber denselben Job-Manager koordiniert
- Export-Worker fuer Provisionen CSV/XLSX sowie Steuern CSV umgesetzt; Dateiauswahl bleibt im UI-Thread, Datei-Erzeugung/-Schreiben laeuft im Worker
- `PaymentClearingView` von `QTableWidget` auf `DataTable`/Model-View migriert
- `CalculationView` Ergebnis-Tabellen und Legacy-Artikelliste von `QTableWidget` auf `DataTable`/Model-View migriert
- `ProductsView` Inventar-, Wix- und Sync-Tabellen von `QTableWidget` auf `DataTable`/Model-View migriert; Sync-Status, Konflikte und sevDesk-Aktion jetzt delegate-basiert ohne Zeilen-Widgets

## Durchgefuehrte Live-Tests

### Testumgebung

- Windows, PowerShell, Repo `.venv`
- `QT_QPA_PLATFORM=offscreen`
- `PYTHONPATH=src`
- PySide6/pytest-qt UI-Tests mit Fake-Services fuer reproduzierbare Klickpfade
- Lokale Logs aus `logs/xw_office.log`
- Keine externen API-Aktionen im Testlauf ausgeloest, um keine echten sevDesk/Wix/Graph-Seiteneffekte zu erzeugen.

### pytest-qt Lauf

Befehl:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_rechnungen_view_smoke.py tests/ui/test_payment_clearing_view.py tests/ui/test_rechnungen_search.py -q --durations=20
```

Ergebnis:

- 28 Tests bestanden.
- 1 Test fehlgeschlagen: `test_main_window_can_open_payment_clearing`.
- Ursache: `PaymentClearing` wird inzwischen lazy/asynchron erst als Placeholder registriert. Der Test erwartet noch sofort die finale `PaymentClearingView`.
- Relevanz: Der Fehlschlag spricht fuer eine bereits eingefuehrte Performance-Optimierung, aber die Tests muessen die neue Lazy-Loading-Semantik abwarten.

Langsamste UI-Testdauer:

| Test | Dauer |
|---|---:|
| `test_main_window_rechnungen_warms_drafts_but_defers_open_invoice_contexts` | 1,33 s |
| `test_search_suggestions_performance_large_dataset` | 0,04 s |
| typische Rechnungen-Klicktests | 0,01-0,04 s |

### Synthetische Qt-Live-Messung mit Fake-Services

Messwerte:

| Pfad | Dauer |
|---|---:|
| `MainWindow` konstruieren | 13,6 ms |
| Navigation `PaymentClearing` Placeholder | 80,6 ms |
| Navigation `Rechnungen` erste Materialisierung | 37,9 ms |
| Rechnungen Erstladung bis `open_loaded` mit Fake-Service | 10,0 ms |
| Auswahl Zeile 0 | 22,2 ms |
| Auswahl Zeile 1 | 20,7 ms |
| `DataTable.set_data` 100 Zeilen | 22,5 ms |
| `DataTable.set_data` 1.000 Zeilen | 41,2 ms |
| `DataTable.set_data` 5.000 Zeilen | 148,0 ms |
| `Rechnungen._apply_load_result_data` 50 Zeilen | 22,3 ms |
| `Rechnungen._apply_load_result_data` 250 Zeilen | 33,8 ms |
| `Rechnungen._apply_load_result_data` 1.000 Zeilen | 76,6 ms |
| `DataTable.set_data` 10.000 Zeilen | 364,0 ms |
| maximaler Eventloop-Gap bei 10.000 Zeilen | 273,2 ms |

Interpretation:

- Der reine Klickpfad ist bei kleinen Fake-Daten nicht das Problem.
- Die UI blockiert messbar, sobald grosse Tabellen oder umfangreiche Resultate synchron in Widgets geschrieben werden.
- 273 ms Eventloop-Gap ist noch keine "mehrere Sekunden"-Traegheit, aber bei realem Rechner, Icons, Delegates, Netzantworten, Printer-Discovery und mehreren Folgejobs kann daraus gefuehltes Haengen werden.

### QTableWidget-Messung

Messwerte:

| Pfad | Dauer |
|---|---:|
| `QTableWidget insertRow` 100 x 10 | 21,6 ms |
| `QTableWidget insertRow` 1.000 x 10 | 36,0 ms |
| `QTableWidget insertRow` 5.000 x 10 | 113,9 ms |
| `QTableWidget setRowCount` 1.000 x 10 | 37,3 ms |
| `QTableWidget setRowCount` 5.000 x 10 | 108,1 ms |
| `QTableWidget insertRow` 10.000 x 10 | 325,4 ms |
| maximaler Eventloop-Gap bei 10.000 x 10 | 226,9 ms |

Interpretation:

- `QTableWidget` ist fuer sehr grosse Tabellen ein strukturelles Risiko.
- Das Problem ist weniger `insertRow` vs. `setRowCount`, sondern die Item-basierte Architektur.
- Fuer Produkte, Zahlungsclearing und Provisionen sollte langfristig `QAbstractTableModel`/`QTableView` wie bei `DataTable` verwendet werden.

## Reale Log-Auswertung

Relevante Ausschnitte aus `logs/xw_office.log`:

| Ereignis | Beobachtung |
|---|---:|
| Rechnungen Draft-Load, 0 Zeilen | ca. 1.680-1.767 ms |
| Rechnungen Open-Load, 50 Zeilen | einmal 7.706 ms, spaeter 1.931 ms |
| Wix-Warmup 6 Referenzen | ca. 19.107-20.431 ms pro Batch |
| START Wix-Prefetch 11 Referenzen | 4.152 ms |
| START `product_mapping` | meist ca. 2.5-3.0 s pro Rechnung |
| START `payment` | meist ca. 5.2-6.7 s pro Rechnung |
| START `invoice_print` | ca. 1.2-2.1 s pro Rechnung |
| START `label_print` | ca. 2.1-3.1 s pro Rechnung |
| START `wix_fulfillment` | ca. 16.5-18.2 s pro Rechnung |
| START `mail` | ca. 7.0-10.8 s pro Rechnung |
| START Post-Processing 11 Tasks, 5 Worker | 90.047 ms |
| START gesamt 11 Rechnungen | 300.562 ms |

Interpretation:

- "Jeder Klick dauert Sekunden" ist in der echten Nutzung sehr wahrscheinlich nicht nur UI-Thread-Blockade, sondern eine Kombination aus Klick startet Prozess, Prozess laeuft lange, UI vermittelt nicht sauber, was gerade passiert.
- Wix-Fulfillment und Mail sind die groessten echten Zeitfresser.
- Rechnungslisten-Ladezeiten von 1,7-7,7 s muessen als Hintergrunddatenstand behandelt werden. Der Klick selbst sollte nach <200 ms sichtbar reagieren.
- Der Wix-Warmup ist zwar im Worker, laeuft aber lange und konkurriert mental mit Interaktion. Er braucht klarere Priorisierung, Drosselung und Status.

## Kritische Codepfade

### MainWindow und Modulwechsel

Datei: `src/xw_office/ui/main_window.py`

- `MainWindow.__init__` baut Sidebar, Home, Statusbar und ruft `_apply_printer_status()` synchron.
- `_apply_printer_status()` ruft `discover_printers()` synchron.
- `_navigate_to()` behandelt `Rechnungen` als Sonderfall und materialisiert dieses Modul synchron, waehrend andere Module einen Placeholder bekommen.
- `_build_page_async()` nutzt `QTimer.singleShot(0, materialize)`, baut aber die View trotzdem im UI-Thread.

Risiko:

- Druckererkennung kann unter Windows langsam sein.
- Der erste Rechnungen-Klick kann durch Widget-Aufbau, Druckercheck im Rechnungen-View und sofortige Initial-Loads schwer wirken.
- `QTimer.singleShot(0)` ist kein echter Background-Thread. Es verschiebt nur auf den naechsten Eventloop-Tick.

### Rechnungen/Tagesgeschaeft

Dateien:

- `src/xw_office/ui/modules/rechnungen/tagesgeschaeft_view.py`
- `src/xw_office/ui/modules/rechnungen/view.py`

Bereits gut:

- Rechnungslisten werden ueber `BackgroundWorker` geladen.
- Detaildaten werden zuerst sofort aus Summary angezeigt und danach hydratisiert.
- Wix-Kontexte werden im Hintergrund gebatched.
- START-Preflight und START-Ausfuehrung laufen in Workern.

Risiken:

- `TagesgeschaeftView._build_ui()` erstellt sofort eine komplette `RechnungenView`.
- `RechnungenView.__init__()` ruft `_initialize_printer_status()` synchron.
- `RechnungenView.showEvent()` startet direkt Reload, Badge/Mollie-Refresh und weitere Nebenprozesse.
- `_apply_load_result_data()` macht Sortierung, Tabellenreset, Suchindex, Tabellenlayout, Open-Overview-Scheduling und Detailrefresh im UI-Thread.
- `_refresh_open_invoice_overview()` fuehrt eine synchrone Sofortuebersicht aus und startet danach Background-Detailarbeit.
- `QApplication.processEvents()` wird in Start-/Print-Pfaden genutzt. Das kaschiert Blockaden, kann aber Reentrancy-Probleme verursachen.
- `_run_product_preflight_dialogs()` oeffnet potenziell mehrere Dialoge seriell. Wenn viele Produktprobleme auftauchen, fuehlt sich START zerhackt an.
- `_set_start_running()` ruft `QApplication.processEvents()`. Besser: Status setzen, dann mit `QTimer.singleShot(0, start_worker)` starten.

### Produkte

Datei: `src/xw_office/ui/modules/products/view.py`

Risiken:

- `ProductsView.__init__()` startet direkt `_load_sync_sources(refresh_sevdesk_cache=True)`.
- Der erste Modulaufruf startet lokale Produkte, Wix und sevDesk zusammen.
- `_populate_inv`, `_populate_wix`, `_populate_sync_table` bauen `QTableWidget` komplett neu.
- Filter rufen erneut komplette Populate-Funktionen auf.
- Sync-Tabelle erzeugt pro Zeile teilweise Widgets/Buttons, was bei vielen SKUs teuer wird.

Empfehlung:

- Erstes Anzeigen nur Shell + "Daten laden" bzw. gecachte letzte Ansicht.
- Wix/sevDesk Sync getrennt starten und im Hintergrund aktualisieren.
- Tabellen auf `QAbstractTableModel` migrieren.

### Zahlungsclearing

Datei: `src/xw_office/ui/modules/payment_clearing/view.py`

Bereits gut:

- Analyse, Reset und Buchung laufen in `BackgroundWorker`.

Risiken:

- `_refresh_table()` baut `QTableWidget` komplett neu.
- Suche/Filter ruft `_refresh_table()` bei jeder Suchaenderung.
- `Alle buchbaren auswaehlen` ersetzt die komplette Kandidatenliste und baut die Tabelle neu.

Empfehlung:

- Model/View mit Proxy-Filter verwenden.
- Checkbox-Status im Model aendern, nicht ganze Tabelle neu schreiben.
- Suchfilter debounce bzw. `QSortFilterProxyModel`.

### Provisionen/Kalkulation

Datei: `src/xw_office/ui/modules/calculation/view.py`

Bereits gut:

- Abrechnung laeuft in Worker.

Risiken:

- Nach Worker-Ergebnis werden mehrere `QTableWidget` komplett neu befuellt.
- Export CSV/XLSX laeuft synchron im UI-Thread.
- `CalculationView.__init__()` ruft `_load_articles()` direkt.

Empfehlung:

- Export in Worker.
- Tabellen auf Models migrieren oder chunked population.
- Artikelliste erst laden, wenn Tab sichtbar ist.

## Priorisierte Optimierungen

### P0: Sofort sichtbares Klick-Feedback erzwingen

Ziel: Jeder Klick zeigt innerhalb von 100-200 ms eine sichtbare Reaktion.

Umsetzung:

- Einheitlicher `run_user_action()` Helper fuer Buttons:
  - Button sofort disabled oder pressed/loading state.
  - Statusbar-Text sofort setzen.
  - Optional kleines Inline-Spinner/ProgressOverlay.
  - Eigentliche Arbeit mit `QTimer.singleShot(0, start_worker)` starten.
- Kein Klickhandler darf direkt schwere Arbeit starten, bevor die UI den neuen Zustand zeichnen konnte.
- `QApplication.processEvents()` schrittweise entfernen und durch geplante Eventloop-Uebergabe ersetzen.

Kandidaten:

- `TagesgeschaeftView._set_start_running`
- `RechnungenView._on_product_print_clicked`
- `RechnungenView._on_send_invoice_clicked`
- `RechnungenView._on_print_clicked`
- `ProductsView._load_sync_sources`
- `PaymentClearingView._analyze`

### P0: Rechnungen nicht mehr synchron materialisieren

Problem:

- `MainWindow._navigate_to()` baut `Rechnungen` als Sonderfall sofort.
- `TagesgeschaeftView` baut wiederum sofort `RechnungenView`.

Umbau:

- Rechnungen wie alle anderen Module zuerst als Placeholder anzeigen.
- `TagesgeschaeftView` in Shell und Inhalt trennen:
  - Shell: Actionbar sofort sichtbar.
  - Inhalt: `RechnungenView` per `QTimer.singleShot(0)` oder besser als "deferred UI build" in kleinen Schritten.
- Druckerstatus und erste Datenladung nicht im Konstruktor, sondern nach erstem Paint starten.

DoD:

- Klick auf "Rechnungen" zeigt innerhalb <200 ms Actionbar/Placeholder.
- Volle Tabelle darf spaeter kommen.
- Kein synchroner Printer-Discovery-Call im View-Konstruktor.

### P0: Druckererkennung zentral cachen und asynchron aktualisieren

Problem:

- `MainWindow._apply_printer_status()` und `RechnungenView._initialize_printer_status()` koennen beide `discover_printers()` ausloesen.

Umbau:

- Neuer `PrinterStatusService`:
  - Ein zentraler Cache.
  - Hintergrundrefresh beim App-Start.
  - TTL z.B. 30-60 s.
  - Signal `printer_status_changed`.
- Views lesen nur den letzten bekannten Zustand und abonnieren Updates.

Erwartung:

- Keine Windows-Druckerabfrage mehr auf Modul-Klick.
- Druckstatus kann nachtraeglich von "wird geprueft" auf gruen/gelb/rot wechseln.

### P0: Rechnungslisten-Ladepipeline entkoppeln

Aktuell:

- Drafts laden.
- Wenn keine Drafts, Open-Load automatisch.
- Danach Suchindex, Open-Overview, Hints, Wix-Warmup.

Umbau:

- Listenanzeige in Stufen:
  1. Sofort: alte gecachte Tabelle oder leere Skeleton-Tabelle.
  2. Worker: neue erste Seite.
  3. UI: nur sichtbare Zeilen anwenden.
  4. Danach: Nebenjobs mit niedriger Prioritaet.
- Nebenjobs in JobQueue priorisieren:
  - Prio 0: aktuell selektierte Zeile.
  - Prio 1: sichtbare Zeilen.
  - Prio 2: Badge/Open-Overview.
  - Prio 3: Warmup restlicher Liste.
- Wenn der User klickt/selektiert, Warmup pausieren oder repriorisieren.

Konkrete Kandidaten:

- `_schedule_post_load_prefetch`
- `_warm_wix_context_for_summaries`
- `_start_next_wix_warm_batch`
- `_prioritize_hint_prefetch_for_summary`
- `_start_open_invoice_overview`

### P0: Wix-Warmup drosseln und in persistenten Background-Client auslagern

Logbefund:

- 24 Referenzen wurden in 6er-Batches gewaermt.
- Jeder 6er-Batch dauerte ca. 19-20 s.

Problem:

- Der Worker blockiert zwar nicht direkt die UI, aber er laeuft lange, erzeugt API-Last und konkurriert mit selektionsnahen Wix-Abfragen.

Umbau:

- Neuer `WixContextBackgroundClient`:
  - Eigene Queue mit Prioritaeten.
  - Request-Coalescing pro Order-Ref.
  - Cancel/Drop von Low-Priority-Jobs bei Modulwechsel.
  - Rate-Limit und Backoff.
  - Persistent Cache zuerst lesen, Netzwerk nur wenn stale.
  - Separate Methoden fuer Summary, LineItems, Fulfillment, PaymentDetails.
- Warmup nur fuer sichtbare Zeilen plus 2-3 naechste Zeilen.
- Keine 24 Referenzen direkt nach erstem Load.

### P0: START-Workflow als echte Pipeline mit Background-Orchestrator

Logbefund:

- 11 Rechnungen: 300.562 ms gesamt.
- Post-Processing: 90.047 ms.
- Wix-Fulfillment: ca. 16-18 s pro Rechnung.
- Mail: ca. 7-11 s pro Rechnung.

Umbau:

- `StartWorkflowRunner` als service-seitiger Orchestrator:
  - Phasenstatus pro Rechnung.
  - Persistenter Laufstatus in `state/` oder DB.
  - UI bekommt nur Events.
  - STOP setzt Cancel-Token, nicht nur Flag im View.
  - Retry pro Phase.
  - Fortschrittstabelle statt modaler Summary am Ende.
- Phasen parallelisieren, wo sicher:
  - Vorab: Wix Order + Payment Details fuer alle Zielrechnungen.
  - Pro Rechnung: product_mapping/finalize/payment weiter kontrolliert seriell, wenn sevDesk das braucht.
  - Nachgelagert: Wix-Fulfillment und Mail in getrennte Queues mit begrenzter Parallelitaet.
- Druckjobs nicht als "Warten bis fertig" im START behandeln, sondern als PrintQueue-Status referenzieren.

UX:

- START-Klick zeigt sofort eine Laufansicht.
- Der User kann weiter navigieren.
- Einzelne Phasen zeigen "wartet", "laeuft", "ok", "retry", "fehler".

### P1: Tabellenarchitektur vereinheitlichen

Problem:

- `QTableWidget` wird in Produkte, Zahlungsclearing und Provisionen stark genutzt.
- Komplettes Neuaufbauen blockiert die Eventloop bei grossen Datenmengen.

Umbau:

- Gemeinsames `TableModelBase(QAbstractTableModel)`:
  - rows als typed dataclasses/Pydantic/Plain objects.
  - `data()` formatiert on demand.
  - `QSortFilterProxyModel` fuer Suche/Filter.
  - `dataChanged` fuer einzelne Felder.
  - Keine QWidget-Buttons pro Tabellenzeile, sondern Delegates.
- `DataTable` erweitern:
  - optional stable row id.
  - batch insert/update.
  - selected row preservation.
  - built-in proxy filter ueber mehrere Spalten.

Kandidaten:

- `PaymentClearingView._refresh_table`
- `ProductsView._populate_sync_table`
- `ProductsView._populate_inv`
- `ProductsView._populate_wix`
- `CalculationView._populate_product_table`
- `CalculationView._populate_doc_table`

### P1: Chunked UI-Updates fuer grosse Resultate

Wenn Model-Migration nicht sofort moeglich ist:

- Tabellenupdates in Chunks von 100-250 Zeilen per `QTimer.singleShot(0, next_chunk)`.
- `setUpdatesEnabled(False)` nur innerhalb eines kleinen Chunks, nicht fuer tausende Zeilen am Stueck.
- Status: "250/3.200 Zeilen angezeigt".
- User kann schon filtern/abbrechen, bevor alle Zeilen materialisiert sind.

### P1: Badge- und Count-Strategie aendern

Problem:

- `TagesgeschaeftView._refresh_badges()` ruft `invoice_service.count_invoices(status=100)`.
- `count_invoices()` paginiert ueber API-Seiten.
- Badge-Refresh laeuft im Worker, kann aber API-Last und spaete Statusupdates erzeugen.

Umbau:

- Badge-Zahlen nicht live vollstaendig zaehlen, sondern:
  - aus letzter Liste ableiten.
  - stale Cache anzeigen.
  - im Hintergrund mit TTL aktualisieren.
  - Max-Anzeige z.B. `200+`, statt alles zu paginieren.
- Bei START oder Reload gezielt invalidieren.

### P1: Open-Overview vollstaendig in Worker verlagern

Problem:

- `_refresh_open_invoice_overview()` macht einen Sofortteil synchron und startet danach Worker.
- Es gibt Status-Verwechslungspotenzial: In Rechnungen werden `_DRAFT_STATUS=100` und `_OPEN_STATUS=1000` verwendet, aber Open-Overview nutzt `status_code == 100`.

Umbau:

- Vollstaendige Overview-Berechnung in Worker.
- UI setzt sofort "wird aktualisiert".
- Ergebnis wird nur angewendet, wenn List-Revision noch passt.
- Status-Namensgebung klaeren:
  - `DRAFT_STATUS = 100`
  - `OPEN_STATUS = 1000`
  - Overview explizit "Entwuerfe/offene Tagesgeschaeftsrechnungen" nennen, wenn 100 korrekt ist.

### P1: Export- und Dateioperationen aus dem UI-Thread

Kandidaten:

- `CalculationView._export_commission_xlsx`
- `CalculationView._export_commission_csv`
- PDF-/Druckvorbereitung, falls noch synchron in Dialogen.
- Produkt-Druckplaene laden/speichern.

Umbau:

- Nach Dateiauswahl Worker starten.
- Fortschritt/Fehler im Statusbereich.
- Kein modaler Erfolg, wenn nicht noetig; lieber Toast/Statusbar.

### P1: Dialoge vorladen oder nicht-modal machen

Problem:

- Modale Dialoge sind nicht per se langsam, aber bei mehreren seriellen Produktproblemen fuehlt es sich zaeh an.

Umbau:

- Produkt-Preflight als eine Sammelansicht statt N Dialoge.
- Dialog-UI erst anzeigen, Daten parallel vorbereiten.
- Fuer wiederkehrende Dialoge leichte ViewModels cachen.

Kandidaten:

- `_run_product_preflight_dialogs`
- `ProductPreflightDialog`
- `ReprintPreviewDialog`
- `OffeneSendungenDialog`

### P2: Background-Job-System statt einzelner Worker-Felder

Problem:

- Viele Views halten einzelne Felder: `_worker`, `_wix_context_worker`, `_hint_worker`, `_badge_worker`, usw.
- Das macht Priorisierung, Cancel, Konkurrenz und globale Lastkontrolle schwer.

Umbau:

- Neuer `BackgroundJobManager`:
  - Named queues: `ui-critical`, `network`, `warmup`, `printing`, `export`.
  - Prioritaet.
  - Max parallel pro Queue.
  - Coalescing key, z.B. `wix-context:20945`.
  - Cancel token.
  - Result delivery nur an noch lebende Widgets.
  - zentrale Metriken.
- `BackgroundWorker` bleibt intern nutzbar, aber Views starten Jobs ueber den Manager.

### P2: HTTP-Clients persistent halten

Problem:

- Mehrere Services erzeugen haeufig neue `httpx.Client` Instanzen.
- Verbindungsaufbau/TLS kostet Zeit.

Umbau:

- Pro API ein langlebiger Client im Container:
  - sevDesk
  - Wix
  - Graph/Mail
  - Mollie/Stripe, falls relevant
- Sauberer Shutdown.
- Gemeinsames Timeout/Retry/RateLimit.

### P2: Lokale Read-Through-Caches ausbauen

Kandidaten:

- Wix Order Summary
- Wix Line Items
- sevDesk Invoice Detail
- sevDesk Parts
- Fulfillment Flags
- Payment Account IDs
- Printer Status

Regeln:

- Cache-Key mit API-Scope/Account.
- TTL nach Datenart.
- "stale-while-revalidate": UI nutzt alte Daten sofort, Worker aktualisiert im Hintergrund.
- Manuelles "Aktualisieren" invalidiert gezielt.

### P2: Performance-Metriken in der App sichtbar machen

Schon vorhanden:

- Logs fuer Rechnungen load, Wix warmup, START-Phasen.

Ausbauen:

- `PerfProbe` Helper:
  - `ui_click_to_feedback_ms`
  - `worker_queue_wait_ms`
  - `worker_run_ms`
  - `ui_apply_result_ms`
  - `eventloop_gap_ms`
- Debug-Overlay oder "Performance" in Einstellungen:
  - letzte 20 Klicks
  - langsamste Worker
  - aktive Jobs
  - Cache hit/miss

Damit ist kuenftig sofort sichtbar, ob ein Klick selbst blockiert oder ob ein Background-Prozess nur lange dauert.

## Konkreter Umsetzungsplan

### Phase 1: Klick-Feedback und offensichtliche Blocker

1. `PrinterStatusService` bauen und synchrone Druckererkennung aus Konstruktoren entfernen.
2. `Rechnungen` in `MainWindow._navigate_to()` nicht mehr synchron materialisieren.
3. `TagesgeschaeftView` in Shell + deferred `RechnungenView` splitten.
4. `QApplication.processEvents()` in START/Print-Pfaden durch `QTimer.singleShot(0, ...)` ersetzen.
5. Test `test_main_window_can_open_payment_clearing` an Lazy Loading anpassen.

Erwarteter Effekt:

- Modul- und Buttonklicks reagieren sichtbar schneller.
- Weniger UI-Freeze bei Start/Navigation.

### Phase 2: Rechnungen-Background-Pipeline

1. `WixContextBackgroundClient` mit Prioritaeten und Coalescing.
2. Warmup nur fuer sichtbare/nahe Zeilen.
3. Open-Overview komplett in Worker.
4. Badge-Counts mit TTL/stale cache.
5. START-Orchestrator mit persistentem Status und Fortschrittstabelle.

Erwarteter Effekt:

- Selektionswechsel und Untermenues bleiben fluessig, auch wenn Wix langsam ist.
- START wirkt nicht wie eingefrorene App, sondern wie ein langer kontrollierter Job.

### Phase 3: Tabellenmigration

1. Zahlungsclearing auf `QAbstractTableModel`.
2. Produkte Sync auf `QAbstractTableModel` plus Delegates statt Zeilenbuttons.
3. Provisionen-Tabellen auf Models oder chunked population.
4. Multi-Spalten-Filter via ProxyModel.

Erwarteter Effekt:

- Weniger Eventloop-Gaps bei grossen Resultaten.
- Suche/Filter wird deutlich billiger.

### Phase 4: API- und Cache-Schicht

1. Langlebige HTTP-Clients im Container.
2. Einheitliches Retry/Timeout/RateLimit.
3. Read-through-Caches mit stale-while-revalidate.
4. JobManager-Metriken und Debug-Ansicht.

Erwarteter Effekt:

- Weniger externe Latenz pro Aktion.
- Weniger doppelte API-Aufrufe.
- Ursachen fuer langsame Klicks werden sichtbar.

## Akzeptanzkriterien

Performance-SLOs:

- Klick auf Button: sichtbares Feedback <200 ms.
- Modulwechsel: Placeholder/Shell <200 ms, erster Inhalt <500 ms wenn gecacht.
- Rechnungen erste sichtbare Tabelle: alte gecachte Daten sofort, frische Daten im Hintergrund.
- Selektionswechsel in Rechnungen: Summary-Details <100 ms, Wix/Products spaeter.
- Tabellen-Apply im UI-Thread: <50 ms fuer normale Resultate; alles groessere chunked oder Model-basiert.
- Kein synchrones Netzwerk, kein synchroner Druckercheck, kein Export und keine grosse Tabellenpopulation direkt im Klickhandler.

Tests:

- UI-Test fuer Klick-Feedback:
  - Button klickt.
  - Button/Status aendert sich sofort.
  - Workerstart darf danach passieren.
- UI-Test fuer Lazy-Modulwechsel:
  - Placeholder sofort sichtbar.
  - finale View wird abgewartet.
- Eventloop-Gap-Test:
  - QTimer alle 10 ms.
  - grosse Tabellenaktion darf definierten Max-Gap nicht ueberschreiten oder muss chunked sein.
- Rechnungen-Test:
  - Auswahlwechsel darf Detail-Summary sofort setzen.
  - Wix-Warmup darf selektionsnahe Detailabfrage nicht blockieren.
- START-Test:
  - Fortschritt pro Phase kommt als Signal.
  - STOP setzt Cancel-Token.

## Wichtigste Einzelbefunde fuer die Umsetzung

1. Die echten Verzogerungen liegen stark bei externen Phasen: Wix-Fulfillment, Mail, Payment, Wix-Warmup.
2. Die UI muss diese Arbeit als langen Hintergrundprozess darstellen, nicht als "Klick wartet".
3. `QTimer.singleShot(0)` macht UI-Arbeit nicht parallel. Fuer echte Entlastung braucht es Worker/JobManager oder chunked UI-Aufbau.
4. `QTableWidget` wird bei grossen Daten ein wiederkehrendes Problem bleiben.
5. Rechnungen hat schon gute Ansatze, aber zu viele Folgejobs nach dem ersten Load.
6. Der groesste Hebel ist eine zentrale Background-Schicht mit Prioritaeten, Cancel und Coalescing.

