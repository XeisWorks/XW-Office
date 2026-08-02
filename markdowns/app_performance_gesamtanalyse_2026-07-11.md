# XW-Office: Gesamtanalyse Klick- und Navigationsperformance

Stand: 11.07.2026  
Scope: alle Eintraege der Sidebar, das Untermenue `RECHNUNGEN`, zugehoerige Dialoge, gemeinsame UI-Widgets und Background-Infrastruktur

## Umsetzungsstand vom 11.07.2026

Die erste große Umbauphase wurde direkt auf Basis dieser Analyse umgesetzt.

Umgesetzt:

- `BackgroundWorker.cancel()` unterdrueckt Resultate und Fehler bereits ersetzter Jobs sicher.
- `UiAsyncAction` vereinheitlicht sofortigen Busytext, Doppelklickschutz, Generation-Guard, Fehlerbehandlung, Finished-Restore und Laufzeitlogging.
- Der DI-Container ist fuer paralleles erstmaliges Aufloesen von Services mit einem reentranten Lock abgesichert.
- Alle Module einschließlich `Rechnungen` zeigen beim ersten Navigieren sofort eine Ladeshell.
- `TagesgeschaeftView` zeigt zuerst Aktionsleiste und Rechnungen-Ladezustand; die große `RechnungenView` wird erst in der folgenden Eventloop-Runde aufgebaut.
- Die synchrone Rechnungs-Draft-Vorschau laeuft im Worker und ist gegen geaenderte Ordernummern/stale Results geschuetzt.
- Reentrante `QApplication.processEvents()`-Aufrufe wurden aus den Rechnungsaktionspfaden entfernt.
- Produktfeld-Vorschau und -Anwendung, Brand-Preview/Writeback, Druckplan-I/O sowie sevDesk-Produktanlage laufen asynchron.
- Offene Sendungen: Label, Lieferschein-Erzeugung/-Druck und Outlook-Erledigung laufen asynchron.
- Offene Ueberweisungen: Zusammenfassung, QR-Erzeugung, Verschieben und Outlook-Erledigung laufen asynchron.
- Zahlungsclearing ordnet manuelle Rechnungen im Worker zu.
- Settings laden Queue-/Preflightdaten und Mailvorlagen asynchron und speichern Queue-Daten, Tokens, PLC-Secrets und Mailvorlagen im Hintergrund.
- Secrets werden in einem einzelnen DB-Roundtrip gecacht und beim App-Start im Background-Warmup vorgeladen.
- Marketing und Notensatz zeigen sofort ihre Shell, halten ein Memory-Model und laden/persistieren Railway-Daten im Hintergrund.
- XW-Copilot laedt Config, Templates und Audit gemeinsam asynchron; Speichern, Dry-Run, History-Loeschen und Schemaexport blockieren den GUI-Thread nicht mehr.
- Gutscheine und Mollie verwenden einen kurzen TTL und behalten beim Refresh die bisherigen Daten sichtbar.
- Provisionen und Steuern snapshotten alle Qt-Eingabewerte vor Workerstart; OSS besitzt Doppelklickschutz und schreibt XML im Worker.
- Layout liest große PDFs erst im Worker und verhindert konkurrierende Werkzeugjobs.
- CRM und Statistik verhindern doppelte Loads; CRM restauriert den Scanbutton auch im Fehlerfall.

Verifikation dieser Phase:

- 474 relevante UI-/Unit-Tests bestanden.
- 29 gezielte Rechnungen-/MainWindow-Tests bestanden.
- 14 zentral geaenderte Module bestehen `mypy --strict` ohne Fehler.
- Alle geaenderten Dateien bestehen `ruff check`.
- Der ungefilterte Altbestand erreicht 519 bestandene Tests; 18 bekannte Legacy-/Paritaetstests sind bereits vor diesem Umbau fachlich veraltet und erwarten alte APIs bzw. explizit noch nicht implementierte Funktionen.

## Umsetzungsstand zweite Umbauphase vom 11.07.2026

Fokus dieser Phase: grosse item-basierte Tabellen in Hauptmodulen abbauen, damit Result-Handler nicht mehr hunderte oder tausende `QTableWidgetItem`-Objekte im GUI-Thread erzeugen und Spalten nach jedem Load neu vermessen.

Umgesetzt:

- `SimpleTableModel` besitzt eine eigene Sortierrolle. Sichtbare Werte koennen formatiert bleiben, waehrend Sortierung auf numerischen oder zeitlichen Rohwerten laeuft.
- `DataTable` nutzt diese Sortierrolle appweit automatisch.
- `CRM` verwendet fuer Kontaktliste und Duplikat-Tabelle `DataTable` statt `QTableWidget`.
- CRM-Duplikatauswahl basiert auf dem Row-Payload statt auf sichtbaren Tabellenindizes. Das bleibt korrekt, wenn die Tabelle sortiert oder gefiltert ist.
- `Statistik` verwendet fuer die Monatstabelle `DataTable` statt `QTableWidget`; Rechnungsanzahl und Umsatz sortieren ueber Rohwerte.
- `Statistik` raeumt die Workerreferenz im Finished-Pfad auf, sodass Folge-Refreshs nicht von einer alten Referenz blockiert werden.
- `XW-Copilot` verwendet fuer den Verlauf `DataTable` statt `QTableWidget`; Laden und Loeschen sind jeweils ein Model-Reset statt zeilenweiser Item-Aufbau.
- Ein gezielter UI-Test prueft, dass `DataTable` formatierte Werte ueber explizite Rohwerte sortiert.

Verifikation dieser Phase:

- `python -m compileall -q` fuer die geaenderten UI-Dateien bestanden.
- `python -m ruff check` fuer alle geaenderten Dateien bestanden.
- `python -m mypy --strict --follow-imports=skip` fuer die geaenderten UI-Dateien bestanden.
- `PYTHONPATH=src python -m pytest tests/ui -q` bestanden: 50 Tests.

## Umsetzungsstand dritte Umbauphase vom 11.07.2026

Fokus dieser Phase: zentraler JobManager mit Queue-Limits, "latest request wins" und kooperativer Cancellation bis in lange Service-Schleifen.

Umgesetzt:

- `BackgroundJobManager` verwaltet jetzt pro Queue mehrere aktive Jobs mit konfigurierbaren Limits.
- Neue Standard-Queues: `ui-critical-network`, `network-background`, `database`, `cpu`, `printing`, `export`.
- `submit_callable()` startet Jobs mit `CancelToken`, Owner-Bezug, Result-/Error-/Finished-Callbacks, Prioritaet und Replace-Policy.
- `replace="cancel_previous"` cancelt wartende und laufende Jobs mit gleichem Key und unterdrueckt stale Resultate ueber `BackgroundWorker.cancel()`.
- `cancel_owner()` und `cancel_key()` erlauben View-Lebenszeit- und Auswahlwechsel-Cancellation.
- Der Rechnungs-Wix-Detailrequest laeuft jetzt ueber `ui-critical-network` und bricht vorherige Detailrequests ab.
- Wix-Warmup laeuft ueber `network-background`, nicht mehr ueber einen verschachtelten `ThreadPoolExecutor`.
- Sichtbare Wix-Detailrequests brechen konkurrierende Warmup-Jobs ab, damit Benutzeraktionen Vorrang haben.
- Wix-Warmup prueft den Cancel-Token zwischen Order-Summary, Line-Items, Piece-Mapping und Hint-Aufloesung.
- Wix-Order-Service-Methoden `resolve_order_summary()` und `fetch_order_line_items()` akzeptieren optional einen Cancel-Token und pruefen ihn in der Order-Aufloesung und beim Line-Item-Parsing.
- Wix-Produkt-Paging und Wix-Retry-Backoff akzeptieren optional einen Cancel-Token.
- sevDesk-GET-Retry akzeptiert optional `cancel_token` und kann Backoff-Schlaf in kleinen Intervallen abbrechen.
- Neue Unit-Tests pruefen Queue-Limits und `cancel_previous` gegen stale Resultate.

Verifikation dieser Phase:

- `python -m compileall -q` fuer die geaenderten Dateien bestanden.
- `python -m ruff check` fuer alle geaenderten Dateien bestanden.
- `python -m mypy --strict --follow-imports=skip` fuer `BackgroundJobManager` und dessen neue Tests bestanden.
- `PYTHONPATH=src python -m pytest tests/unit/test_background_job_manager.py tests/unit/test_worker_cancellation.py tests/ui/test_rechnungen_view_smoke.py -q` bestanden: 31 Tests.

## Umsetzungsstand vierte Umbauphase vom 11.07.2026

Fokus dieser Phase: Rechnungs-Produktdetails im rechten Detailpanel auf Model/View umstellen, damit Rechnungswechsel mit vielen Wix-Positionen keine dynamischen QWidget-Baeume mehr erzeugt.

Umgesetzt:

- Neues `_PieceListModel` fuer `PieceBlock`-Zeilen, Print-Flag, Menge, Detailtexte, Bestandstext und Aktivzustand.
- Neuer `_PieceDelegate` malt Produktzeilen, Mengensteuerung, Druck- und Plan-Aktion ohne pro Zeile `QWidget`, `QLabel`, `QSpinBox` oder `QToolButton` zu erzeugen.
- Die Produktsektion in `RechnungenView` verwendet jetzt `QListView + QAbstractListModel + QStyledItemDelegate`.
- `_on_stuecke_loaded()` dedupliziert weiter wie bisher, befuellt aber nur noch das Model und zeigt die ListView.
- Sammeldruck liest Mengen aus dem Model statt aus `QSpinBox`-Instanzen.
- Einzelproduktdruck und Druckplanpflege laufen ueber Delegate-Events zur bestehenden Druck-/Planlogik.
- Enable/Disable bei laufendem Druck aktualisiert den Modelzustand und repaintet die ListView.
- Neuer UI-Test prueft 100 Produktpositionen: 100 Modelzeilen, aber nur noch konstantes Produktlayout (`Hint + QListView`).

Verifikation dieser Phase:

- `python -m compileall -q` fuer `rechnungen/view.py` und den Rechnungen-Smoke-Test bestanden.
- `python -m ruff check` fuer `rechnungen/view.py` und den Rechnungen-Smoke-Test bestanden.
- `PYTHONPATH=src python -m pytest tests/ui/test_rechnungen_view_smoke.py -q` bestanden: 29 Tests.

## Abschlussphase vom 11.07.2026

Fokus dieser Phase: die nach Phase 4 noch dokumentierten Restpunkte schliessen und die Umsetzung gegen die urspruengliche Skizze abgleichen.

Umgesetzt:

- `offene_sendungen_dialog.py` verwendet fuer die bearbeitbare Produktliste ein eigenes `QAbstractTableModel + QTableView` statt `QTableWidget`.
- `reprint_dialog.py` verwendet fuer beide Vorschautabellen `DataTable` statt `QTableWidget`.
- `print_dialog.py` verwendet fuer den Produkt-Druckplan `QTableView + _PrintPlanModel + _PrintProfileDelegate` statt `QTableWidget` mit Cell-Widgets.
- `open_invoice_overview.py` enthaelt keinen lokalen `ThreadPoolExecutor` mehr; die Berechnung laeuft seriell im bereits gestarteten Worker und konkurriert nicht mehr mit UI-kritischen Netzwerkjobs.
- `InvoiceProcessingService` enthaelt keine lokalen `ThreadPoolExecutor`-Bloecke mehr; START-Postprocessing, Inventar-Preflight und Wix-Prefetch laufen seriell innerhalb ihres Background-Jobs.
- `EventLoopWatchdog` misst Eventloop-Gaps mit 16-ms-Timer, loggt Gaps ab 50 ms bzw. 250 ms und stellt einen Snapshot fuer Debug/Tests bereit.
- `MainWindow` startet den Watchdog automatisch und bietet `performance_snapshot()` als leichte Debugschnittstelle.

Abschluss-Audit der Skizze:

- P0-Freezes aus Click-Handlern und Navigationspfaden sind in den analysierten Hauptmodulen entfernt oder hinter Worker/Loading-Zustaende gelegt.
- Rechnungswechsel zeigt Stammdaten sofort, laedt Wix-/Detail-/Produktdaten asynchron und ignoriert stale Resultate.
- Grosse Haupttabellen in CRM, Statistik und XW-Copilot sind auf Model/View migriert.
- Rechnungs-Produktdetails sind auf ListModel/Delegate migriert.
- Zentrales Jobmanagement mit Queue-Limits, latest-wins und Cancellation ist vorhanden und fuer Rechnungs-Wix-Pfade angebunden.
- Lokale unkontrollierte ThreadPools aus den dokumentierten Rechnungs-Hotspots wurden entfernt.
- Eventloop-Gaps werden runtime-seitig sichtbar gemacht.

Verifikation dieser Abschlussphase:

- `python -m compileall -q` fuer die geaenderten Abschlussdateien bestanden.
- `python -m ruff check` fuer die geaenderten Abschlussdateien bestanden.
- `PYTHONPATH=src python -m pytest tests/ui tests/unit/test_background_job_manager.py tests/unit/test_worker_cancellation.py tests/unit/test_printing_parity_e2e.py -q` bestanden: 66 Tests.
- Voller Regressionslauf: 547 bestanden, 11 uebersprungen, 18 bekannte Altbestand-/Parity-Fehler ausserhalb dieses Performance-Umbaus.
- `rg` findet in `offene_sendungen_dialog.py`, `reprint_dialog.py`, `print_dialog.py`, `open_invoice_overview.py` und `invoice_processing/service.py` keine `QTableWidget`-, `setCellWidget`-, `ThreadPoolExecutor`- oder `as_completed`-Treffer mehr.

Noch bewusst offen:

- Produktiv-Benchmark mit echten API-Latenzen und echten Datenmengen. Die technische Instrumentierung ist vorhanden, aber belastbare Zielwert-Bestaetigung braucht eine Messung auf dem Produktivsystem.
- Weitere stale-while-revalidate-Snapshots koennen nach realer Messung fuer selten genutzte Nebenmodule ergaenzt werden; in den wichtigsten Rechnungs-/Queue-/Refresh-Pfaden ist das Muster bereits umgesetzt.

## Zielbild

Die App soll auf jede Benutzeraktion sofort sichtbar reagieren. Langsame Datenbank-, Netzwerk-, Datei-, PDF-, Druck- und Analysearbeit darf den Qt-GUI-Thread nicht blockieren. Bereits vorhandene Daten bleiben sichtbar, waehrend eine aktuellere Version im Hintergrund geladen wird.

Verbindliche Zielwerte:

| Messpunkt | Ziel |
|---|---:|
| Klick bis optische Rueckmeldung | unter 100 ms, hartes Maximum 200 ms |
| Wechsel auf eine bereits erzeugte Seite | unter 50 ms |
| Erster sichtbarer Frame einer neuen Seite | unter 150 ms |
| Rechnungswechsel: neue Stammdaten sichtbar | unter 50 ms |
| Rechnungswechsel: gecachte Zusatzdaten sichtbar | unter 150 ms |
| Einzelner GUI-Thread-Arbeitsblock | normalerweise unter 16 ms, Maximum 50 ms |
| Suche/Filter nach Debounce | unter 50 ms im GUI-Thread |
| Abbruch/Neuauswahl bis alte Resultate ignoriert werden | sofort |

Wichtig: "asynchron" bedeutet in diesem Dokument echte Ausfuehrung ausserhalb des GUI-Threads. `QTimer.singleShot(0, ...)` verschiebt Arbeit nur auf den naechsten Eventloop-Durchlauf; sie wird dadurch nicht parallel und kann die Oberflaeche weiterhin einfrieren.

## Vorgehen und Belastbarkeit der Analyse

Diese Analyse ist eine statische Codeanalyse des aktuellen Repository-Stands. Sie umfasst Click-Handler, Konstruktoren, `showEvent`, Worker-Result-Handler, Tabellenaufbau, Cachezugriffe und Serviceaufrufe. Sie ist noch keine Laufzeitmessung gegen die produktiven APIs. Deshalb werden Messinstrumentierung und reproduzierbare Performance-Tests als Phase 0 gefordert.

Als technische Referenz wurden die offiziellen Qt-/PySide6-Dokumente verwendet:

- [Qt Threads and QObjects](https://doc.qt.io/qtforpython-6/overviews/qtdoc-threads-qobject.html): GUI-Arbeit muss im GUI-Thread bleiben; Ergebnisse aus Threads sollen ueber queued Signals zurueckgegeben werden.
- [Qt Concurrent Run](https://doc.qt.io/qtforpython-6/overviews/qtconcurrentrun.html): Threadpool-Ausfuehrung und nicht-blockierende Ergebnisbeobachtung; `result()` darf im GUI-Thread nicht zum Warten verwendet werden.
- [Qt Model/View Programming](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-model-view-programming.html): fuer nicht-triviale Datenmengen wird Model/View statt item-basierter Convenience-Widgets empfohlen.
- [QTimer](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTimer.html): Zero-Timer verteilen Arbeit lediglich ueber Eventloop-Runden; eine dauerhaft beschaeftigte Zero-Timer-Kette kann die UI ebenfalls unruhig machen.

## Kurzfazit

Die App besitzt bereits viele sinnvolle `BackgroundWorker`, Lazy-Imports, debouncte Suche, Model/View-Tabellen und mehrere Stale-Result-Guards. Besonders `Rechnungen` ist deutlich weiter als die meisten anderen Module.

Die groessten verbleibenden Hebel sind:

1. Die Seitenerzeugung ist nur optisch, nicht technisch asynchron. `MainWindow._build_page_async()` ruft den Factory-Konstruktor nach einem Zero-Timer weiterhin im GUI-Thread auf. `Rechnungen` wird sogar explizit vollstaendig synchron erzeugt.
2. Mehrere Module erledigen DB-, API-, Datei- oder Druckarbeit noch direkt im Click-Handler.
3. Teure Result-Aufbereitung laeuft haeufig im GUI-Thread: Listen zusammenfuehren, sortieren, filtern, grosse Payloads bauen, `QTableWidget` zeilenweise befuellen oder dynamische Widgetbaeume neu erzeugen.
4. Die Worker sind lokal pro View organisiert. Es fehlen appweite Prioritaeten, begrenzte Parallelitaet, echte Cancellation, Owner-Lebenszeit, einheitliche Busy-Zustaende und standardisierte "latest request wins"-Semantik.
5. Viele Views leeren beim Laden die Anzeige. Das wirkt langsamer als `stale-while-revalidate`: alte Daten sofort anzeigen, dezenten Ladehinweis setzen und nur das frische Ergebnis einblenden.
6. Einige Worker-Funktionen greifen aus dem Hintergrundthread auf Qt-Widgets zu. Eingabewerte muessen vor Worker-Start im GUI-Thread als unveraenderlicher Snapshot gelesen werden.

## Prioritaetsmatrix

| Prio | Bereich | Befund | Erwarteter Effekt |
|---|---|---|---|
| P0 | Navigation | View-Konstruktoren laufen im GUI-Thread; `Rechnungen` ist Sonderfall ohne Placeholder | erster Frame jedes Moduls sofort |
| P0 | Rechnungen | synchrone Restarbeit bei Cache-Hydration, Dialogaktionen, Draft-Vorschau und dynamischem Detailaufbau | Rechnungswechsel und Aktionen merkbar schneller |
| P0 | Produkte | Bulk-Feld/Brand, sevDesk-Anlage und Druckplaene teilweise synchron | keine langen Freezes nach Produktaktionen |
| P0 | Einstellungen/XW-Copilot/Ideen | zahlreiche Railway-/DB-Zugriffe direkt im UI-Thread | Navigation und Speichern blockieren nicht |
| P0 | Rechnungsdialoge | Druck, PDF, Outlook, Attachment und Statusupdates teilweise synchron | Dialogbuttons reagieren sofort |
| P1 | Tabellen | grosse Resultate werden im UI-Thread transformiert oder per `QTableWidget` aufgebaut | weniger Eventloop-Luecken |
| P1 | Worker-System | lokale QThreads ohne globale Limits/Cancellation/Owner | weniger Konkurrenz und veraltete Resultate |
| P1 | Cache | fehlendes stale-while-revalidate in mehreren Modulen | Inhalte wirken sofort vorhanden |
| P1 | Thread-Sicherheit | Widgetwerte werden teils innerhalb von Worker-Jobs gelesen | stabile, korrekte Hintergrundarbeit |
| P2 | Messung | kein durchgaengiges Click-to-feedback-/Eventloop-Monitoring | Performance bleibt dauerhaft kontrollierbar |

## Querschnittsbefunde

### 1. Navigation: aktuelles Lazy Loading blockiert weiterhin

Fundstellen: `src/xw_office/ui/main_window.py:193-238`.

`_navigate_to()` zeigt fuer die meisten Module zuerst einen Placeholder. Danach ruft `_build_page_async()` ueber `QTimer.singleShot(0, materialize)` die Factory auf. Der Placeholder kann dadurch zwar einen Frame erhalten, aber Import, Konstruktor, Tab-Aufbau, Service-Aufloesung und initiale DB-Lesevorgaenge laufen anschliessend vollstaendig im GUI-Thread.

`Rechnungen` ist in `main_window.py:195-200` ein Sonderfall: `TagesgeschaeftView` wird direkt im Click-Handler materialisiert. Wegen der sehr grossen eingebetteten `RechnungenView` ist dies der wichtigste Navigationsblocker.

Empfohlener Umbau:

- Jede Seite bekommt eine sehr leichte, sofort erzeugbare Shell: Titel, Toolbar, leere Model/View-Tabelle, lokaler Ladehinweis.
- Schwere Python-Imports koennen vorab im Idle-Warmup erfolgen. QWidget-Konstruktion bleibt im GUI-Thread, muss aber in kleine, budgetierte Schritte zerlegt werden.
- Keine Seite darf im Konstruktor Netzwerk/DB ansprechen. Sie startet erst nach erstem Paint einen Worker.
- Komplexe Tabs werden erst beim ersten `currentChanged` gebaut, nicht alle im Hauptkonstruktor.
- `Rechnungen` verliert den Sonderfall und zeigt sofort eine Rechnungen-Shell. Tabelle und Detailpanel werden als leichte Widgets angelegt; die Datenhydration beginnt danach.
- Optional nach dem ersten Home-Paint: die zwei am haeufigsten verwendeten Shells (`Rechnungen`, `Produkte`) in Idle-Slices vorbauen.

### 2. Einheitlicher Action-/Loading-Zustand

Heute existieren Statuslabels, deaktivierte Buttons und `ProgressOverlay`, aber nicht nach einem einheitlichen Vertrag.

Jede langsame Aktion soll atomar folgende Schritte ausfuehren:

1. Im Click-Handler sofort Buttontext/Icon aendern, z. B. `Wird geladen...`.
2. Nur die betroffene Aktion deaktivieren; Navigation und nicht betroffene Bereiche aktiv lassen.
3. Bestehende Daten nicht leeren. Daneben `Aktualisiere...` oder einen Skeleton-Zustand anzeigen.
4. Eingabewerte im GUI-Thread snapshotten.
5. Job mit `owner`, `key`, `priority`, `generation` und Cancel-Token starten.
6. Resultat nur anwenden, wenn Owner lebt und Generation/Selection noch aktuell ist.
7. In einem garantiert ausgefuehrten Finished-Pfad Button, Text und Workerreferenz restaurieren.

Ein seitenweites, mausblockierendes Overlay ist nur fuer atomare Transaktionen sinnvoll, bei denen weitere Eingaben unzulaessig sind. Fuer Listen-Refresh oder Detail-Hydration sollte ein lokaler Inline-Loader verwendet werden.

### 3. Background-Infrastruktur

Fundstellen: `src/xw_office/core/worker.py`, `src/xw_office/services/background_jobs/service.py`.

Positiv:

- Exceptions und Ergebnisse werden per Signal an den GUI-Thread geliefert.
- `BackgroundJobManager` kann Jobs priorisieren und per Key zusammenfassen.
- `Rechnungen` nutzt bereits eine Side-Job-Queue.

Offen:

- Jeder `BackgroundWorker` erzeugt einen eigenen `QThread`; es gibt kein appweites Parallelitaetslimit.
- `BackgroundJobManager` verwaltet genau einen aktiven Worker je Queue, aber keine Cancellation laufender Jobs, keinen Owner und keine Timeout-/Metrikdaten.
- Coalescing entfernt nur wartende Jobs. Ein bereits laufender veralteter Request arbeitet weiter.
- Viele Views haben nur ein generisches `_worker`-Feld. Neue Aktionen koennen die Referenz ueberschreiben, obwohl ein vorheriger Worker noch laeuft.
- `closeEvent()` wartet beim Startup-Worker bis zu zwei Sekunden im GUI-Thread (`main_window.py:332-335`).

Ziel-API fuer einen erweiterten `UiJobManager`:

```python
jobs.submit(
    key="invoice-detail:4711",
    owner=self,
    queue="ui-critical-network",
    priority=10,
    replace="cancel_previous",
    fn=lambda cancel, progress: service.load(...),
    on_result=self._apply_if_current,
)
```

Queues und Limits:

| Queue | Parallelitaet | Beispiele |
|---|---:|---|
| `ui-critical-network` | 3 | sichtbare Rechnung, sichtbarer Dialog, manuelle Aktualisierung |
| `network-background` | 2 | Warmup, Badges, Prefetch |
| `database` | 2-4 | Settings, Ideen, Audit-Listen |
| `cpu` | `max(1, cpu_count-1)` | PDF, Matching, Tabellen-Payloads |
| `printing` | 1 | Druckqueue, Bestandsfortschreibung |
| `export` | 1-2 | CSV/XLSX/XML/PDF schreiben |

Services und Clients muessen ausdruecklich thread-safe sein oder pro Worker eine Session erhalten. Besonders verschachtelte `ThreadPoolExecutor` in bereits laufenden QThreads sind nur mit belegter Client-/Cache-Thread-Sicherheit zu behalten.

### 4. Tabellen und Result-Handler

`DataTable` und `SimpleTableModel` sind eine gute Grundlage. Sie vermeiden cell-by-cell Widgets und besitzen bereits Proxy-Sortierung. Dennoch werden Payloads oft vollstaendig im GUI-Thread neu gebaut und das Model komplett zurueckgesetzt.

Verbesserungen:

- Filtern mit einem spezialisierten `QSortFilterProxyModel` statt jedes Mal neue Listen und Dict-Payloads zu bauen.
- Result-Worker liefert bereits darstellungsfertige, unveraenderliche Row-DTOs.
- Bei grossen Resultaten `beginResetModel/endResetModel` nur einmal; bei Paging `beginInsertRows` verwenden.
- Einzelne Status-/Checkbox-Aenderungen mit `dataChanged`, nicht per kompletter Tabellenauffrischung.
- `QTableWidget` in CRM, Statistik, XW-Copilot und einigen Dialogen durch `QTableView + QAbstractTableModel` ersetzen.
- `resizeColumnToContents()` nicht nach jedem grossen Load; nur Stichprobe/erste sichtbare Zeilen messen oder feste/interaktive Breiten verwenden.
- Dynamische QWidget-Baeume pro Tabellen-/Produktzeile vermeiden; Delegates malen Buttons/Chips ohne tausende QObject-Instanzen.

### 5. Cache-Strategie

Ein einheitliches `stale-while-revalidate`-Muster sollte fuer alle lesenden Module gelten:

- Memory-Cache fuer die aktuelle App-Sitzung.
- Optional persistenter Cache mit Zeitstempel fuer teure API-Daten.
- Beim Oeffnen sofort letzten Stand anzeigen und `Stand HH:MM - aktualisiere...` melden.
- Worker aktualisiert im Hintergrund und ersetzt nur bei neuerer Generation.
- Manueller Refresh setzt `force=True`, leert aber nicht vorher die sichtbaren Daten.
- Fehler behaelt alte Daten sichtbar und zeigt `Aktualisierung fehlgeschlagen` statt einer leeren Ansicht.

## Analyse nach Untermenue

### Start

Status: leichtgewichtig; Dashboard-Karten navigieren ueber Signale.

Verbesserungen:

- Card-Pressed-Zustand sofort rendern und Ziel-Shell vor dem schweren Materialisieren aktivieren.
- Idle-Warmup erst nach erstem Paint starten und bei Benutzeraktion pausieren.
- Startup-Preload fuer Rechnungen ist sinnvoll, soll aber ueber die Low-Priority-Queue laufen und nie mit einem sichtbaren Rechnungsrequest konkurrieren.
- Druckerstatus-Snapshot sofort verwenden, Live-Refresh wie bereits vorhanden im Hintergrund behalten.

### Rechnungen / Tagesgeschaeft

Positive Basis:

- Listen-, Detail-, Wix-, Mail-, Druck- und START-Pfade nutzen ueberwiegend Worker.
- Auswahl zeigt Summary-Daten sofort und verschiebt Hydration auf den naechsten Eventloop-Tick (`rechnungen/view.py:3112-3160`).
- Selection-/Sequence-Pruefungen verhindern viele veraltete Ergebnisse.
- Wix-Kontext und Rechnungsdetails besitzen Cachepfade.
- Side-Jobs werden priorisiert; Warmup startet verzoegert.

P0-Befunde und Umbauten:

1. **Sofortige Modulshell**  
   `MainWindow` baut `TagesgeschaeftView` weiterhin synchron. `RechnungenView` umfasst mehr als 4.000 Zeilen und erzeugt viele Gruppen, Delegates und Detailwidgets. Shell zuerst anzeigen; Detailgruppen und seltene Aktionen erst bei Bedarf bauen.

2. **Kein `QApplication.processEvents()` zur Klickbestaetigung**  
   Fundstellen u. a. `rechnungen/view.py:2633-2635` und `4070-4073`. Das kann reentrante Click-/Selection-Handler ausloesen. Stattdessen UI-Zustand setzen und eigentlichen Start mit `QTimer.singleShot(0, start_job)` planen. Die Arbeit selbst bleibt im Worker.

3. **Cache-Hydration wirklich billig halten**  
   `_apply_cached_wix_context()` liest den persistenten Wix-Cache im GUI-Thread (`3360-3392`). Auch nach einem Zero-Timer kann SQLite-/Datei-/Lock-Wartezeit den Rechnungswechsel blockieren. Nur Memory-Cache synchron; persistenten Cache in den `ui-critical-network`-Job integrieren.

4. **Detail-Widgetbaum nicht bei jeder Auswahl neu aufbauen**  
   `_on_stuecke_loaded()` loescht und erzeugt fuer jede Position mehrere Widgets (`3930-4053`). Das wird bei vielen Positionen spuerbar. Ein `QAbstractListModel` mit Delegate oder wiederverwendete Row-Widgets einsetzen. Zunaechst maximal sichtbare Positionen rendern und Rest per "weitere anzeigen" nachladen.

5. **Uebersichtsvorlauf reduzieren**  
   `_refresh_open_invoice_overview()` erstellt schon im GUI-Thread eine Voruebersicht und kann Cachezugriffe pro Rechnung ausfuehren (`1828-1871`). Im GUI-Thread nur Counts aus vorhandenen Summaryfeldern setzen; alle Cache-/Produktklassifikationen in einem Worker berechnen.

6. **Sichtbare Rechnung unterbricht Warmup**  
   Aktuell wartet der sichtbare Wix-Kontext unter Umstaenden auf einen laufenden Warmup-Worker und merkt nur den letzten `queued_ref`. Der JobManager soll laufende Low-Priority-Netzrequests kooperativ abbrechen oder sichtbare Detailrequests in einer getrennten, hoeher priorisierten Queue ausfuehren.

7. **Keine verschachtelte unkontrollierte Parallelitaet**  
   Wix-Warmup startet in einem `BackgroundWorker` noch einen `ThreadPoolExecutor` (`2071-2129`). Parallelitaet zentral begrenzen; Client und persistenten Cache auf Thread-Sicherheit pruefen. Sichtbare Requests brauchen reservierte Kapazitaet.

8. **Erstload mit alten Daten**  
   `_start_load()` zeigt ein blockierendes Overlay (`1288-1340`). Beim Refresh letzte Tabellenzeilen sichtbar lassen, Toolbar lokal auf `Aktualisiere...` setzen und nur beim allerersten Start einen Skeleton verwenden.

9. **Result-Aufbereitung auslagern**  
   `_apply_load_result_data()` liest Hint-Caches, kombiniert/sortiert Listen, baut Suchindex und setzt Layout (`1415 ff.`). Sortierung, Merge und Search-Index im Worker vorbereiten. Im GUI-Thread nur Model-Swap, Auswahlwiederherstellung und Labels.

10. **Suche coalescen**  
    Jeder debouncte Suchtext kann einen neuen Worker starten (`1234-1256`). Sequence-Guards verhindern falsche Anzeige, sparen aber keine Arbeit. Pro Suche `replace=cancel_previous`; leeres Suchfeld soll laufenden Request abbrechen/ignorieren.

11. **Draft-Vorschau asynchron**  
    `_run_draft_preview()` ruft `DraftInvoiceService.preview_wix_order_number()` direkt im modalen Dialog auf (`3871-3912`). Preview-Button sofort auf Busy, Worker starten, Eingabe waehrenddessen optional editierbar lassen, Ergebnis nur fuer unveraenderte Ordernummer anwenden.

12. **Product-Preflight gesammelt statt serieller Modaldialoge**  
    `_run_product_preflight_dialogs()` zeigt je Issue einen Dialog. Eine einzige Tabelle mit allen Problemen, vorgeschlagenen Aktionen und einem finalen Anwenden-Button spart Interaktionen und wiederholten Widgetaufbau.

Weitere Rechnungsaktionen:

- Status-/Fulfillment-Patches weiterhin direkt in der sichtbaren Zeile anwenden; keinen Komplett-Reload nach Einzelaktionen.
- PDF-/Druckvorbereitung vollstaendig in den Printing-Job verschieben. Dateiauswahl darf modal sein, PDF-Oeffnen/Rendern nicht.
- Erfolgsfeedback bevorzugt als Toast/Statusbar; modale `QMessageBox.information` verlaengert den subjektiven Workflow.
- Jeder Detailjob erhaelt Invoice-ID plus Selection-Generation. Das vorhandene Muster soll fuer alle Aktionsresultate gelten.

### Rechnungen: Offene Sendungen

Positiv: Listen- und Detailload laufen im Worker, Detailresultate besitzen Sequence-Guards und sichtbares Ladefeedback.

P0:

- `_print_label()` speichert, baut Drucker und druckt synchron (`offene_sendungen_dialog.py:410-428`). In Printing-Queue verschieben; Button sofort `Drucke...`.
- `_create_delivery_note()`, `_show_delivery_note()` und `_print_delivery_note()` erzeugen PDF und drucken synchron (`430-463`). PDF-Job im Hintergrund, danach GUI-seitig Datei oeffnen.
- `_mark_done()` schreibt manuelle Felder und Outlook-Status synchron (`465-480`). Im Worker ausfuehren, Zeile optimistisch als `wird erledigt...` markieren.
- `_save_current_manual_fields()` ist potenziell DB-gebunden und darf nicht unbemerkt im Click-Handler laufen.
- Beim schnellen Fallwechsel werden mehrere Detailworker parallel weitergefuehrt. Sequence-Guard ist korrekt, aber alte Jobs sollten cancelbar sein und die Netzkapazitaet freigeben.

### Rechnungen: Offene Ueberweisungen

Positiv: initialer Listenload und Attachment-/Zahlungsdetail sind asynchron und selection-sicher.

P0:

- `_summarize_selected()` ist synchron (`offene_ueberweisungen_dialog.py:382-387`), obwohl Zusammenfassung/API teuer sein kann.
- `_show_invoice()` listet und laedt Attachments sowie schreibt die Tempdatei synchron (`389-410`). Worker + lokaler Loader.
- `_generate_qr()` speichert und generiert synchron (`412-428`). Generierung/DB-Schreiben in Job.
- `_defer()` und `_mark_done()` schreiben DB/Outlook synchron (`430-469`). Worker, Busy-Zustand, optimistischer Zeilenstatus.
- `open_count()` in beiden Dialogen darf beim Schliessen keinen Remote-/DB-Roundtrip im GUI-Thread machen; Count aus aktuellem Model oder Memory-Cache liefern.

### Gutscheine

Positiv: Queue-Load erfolgt im Worker, Suche ist debounced, Tabelle verwendet Model/View.

Verbesserungen:

- `showEvent()` startet bei jedem Zuruecknavigieren sofort einen Reload. Letzte Rows sofort anzeigen, nur nach TTL oder manuellem Refresh aktualisieren.
- Refresh-Button sofort auf `Aktualisiere...`; Countlabel um `Stand HH:MM` ergaenzen.
- Workerreferenz in `finished` auf `None` setzen und Fehlerzustand ebenfalls sauber abschliessen.
- Bei grosser Queue nicht nur Spalte 0 filtern; Proxy ueber relevante Spalten einsetzen, ohne Row-Dicts neu zu bauen.

### Mollie Authorized

Die View ist technisch nahezu identisch zu Gutscheine und bereits workerbasiert. Dieselben Massnahmen gelten: vorhandene Rows beim Refresh sichtbar lassen, TTL statt Reload bei jedem `showEvent`, sichtbarer Zeitstempel, sauberer Finished-State und mehrspaltiger Proxyfilter. Der Mollie-Count im Rechnungen-Header soll denselben Cache verwenden, damit Badge und geoeffnete Liste nicht kurz hintereinander dieselbe Quelle abfragen.

### Produkte

Positive Basis: Netzwerkloads und grundlegende Speicheroperationen verwenden Worker; Tabellen sind bereits Model/View mit Delegates.

P0:

1. `_run_bulk_field_dialog()` ruft `apply_field_update()` synchron auf (`products/view.py:1191-1243`). Bei Wix-Sync bedeutet das potenziell viele Netzwerkaufrufe. Dialog schliessen, betroffene SKUs im Model auf `wird aktualisiert` setzen und Bulkjob starten.
2. `_bulk_set_inventory_brand()` ruft Preview und `apply_brand_update()` synchron auf (`1335-1409`). Preview kann aus bereits geladenen Daten lokal erzeugt werden; DB-/Wix-Anwendung gehoert in Worker mit Fortschritt `x/y`.
3. `_create_selected_wix_product_in_sevdesk()` baut Plan, legt sevDesk-Part an und speichert lokal synchron (`1248-1333`). Alle Remote-/DB-Teile asynchron; Dialogdaten vorher oder in einem Preflightjob laden.
4. `_load_print_plans()` und `_save_print_plans()` greifen synchron auf Settings/DB zu (`1153-1170`). Worker plus Busylabel.
5. Resulthandler `_on_apply_done()` und `_on_legacy_import_done()` rufen `ProductCatalogService.reload_from_settings()` synchron auf. Reload in denselben Worker aufnehmen.

P1:

- Die drei Syncquellen werden innerhalb eines Workers seriell geladen (`766-792`). Lokale DB, Wix und sevDesk koennen mit begrenzter Parallelitaet getrennt geladen werden. Teilresultate sofort anzeigen; Gesamtvergleich aktualisieren, sobald Quellen eintreffen.
- `_build_sync_rows()` und `_populate_sync_table()` laufen fuer alle SKUs im GUI-Thread (`835-943`). In Worker vorbereiten oder ein echtes Sync-Model verwenden, das die drei Maps direkt liest.
- Filter bauen bei jedem Wechsel die komplette Payload neu (`989-1010`). Proxyfilter verwenden.
- Wix->Lokal-Merge wird vor Workerstart vollstaendig im GUI-Thread erstellt (`1015-1069`). Fuer grosse Kataloge Merge in CPU/DB-Job verschieben.
- Der Konstruktor startet sofort einen kompletten Live-Abgleich. Besser: letzten Snapshot anzeigen; frische Quellen in Hintergrundjobs laden. Initial nur den sichtbaren Tab bauen.

### CRM

Positiv: Livekontaktload, Duplikatscan und Merge laufen in Workern.

Verbesserungen:

- Kontakt- und Duplikattabellen sind `QTableWidget` und werden zeilenweise im GUI-Thread befuellt. Auf Models migrieren.
- `_load_contacts()` hat keinen Running-/Generation-Guard. Doppelte Requests verhindern oder ersetzen.
- Bei Scanfehler wird `_scan_btn` durch den Lambda-Errorpfad nicht garantiert wieder aktiviert. Einheitlicher `finished`-Handler.
- Merge-Ergebnis befuellt die komplette Tabelle und startet sofort einen weiteren Scan im GUI-Callback. Model patchen; Rescan als Low-Priority-CPU-Job erst nach dem Paint.
- `resizeColumnToContents()` nach Vollbefuellung vermeiden.
- Alte Kontakte sofort anzeigen und Live-Refresh im Hintergrund markieren.

### Steuern

Positive Basis: UVA, U13, OSS, Clearing, Ausgaben und Exporte nutzen weitgehend Worker; UVA besitzt Fortschrittsanzeige.

P0/P1:

- Worker-Jobs lesen teils Qt-Widgets erst im Hintergrund, z. B. `year.value()`, `month.value()`, Checkboxen oder Textfelder. Alle Werte vor `BackgroundWorker`-Erzeugung snapshotten. Qt-Widgets duerfen nur im GUI-Thread gelesen/geschrieben werden.
- OSS Preview/Export prueft keinen bereits laufenden `_oss_worker`, deaktiviert Buttons nicht und setzt die Referenz nach Ende nicht zurueck (`taxes/view.py:522-578`). Dadurch koennen Jobs ueberlappen und die Referenz ueberschreiben.
- XML wird im Resulthandler synchron geschrieben (`558-567`). Den Zielpfad vorher waehlen und Schreiben im Exportjob erledigen.
- Clearing-/Ausgaben-CSV wird vor der Dateiauswahl im GUI-Thread gerendert (`715-738`, `810-833`). Filter und Serialisierung in Worker.
- Filter sollten ProxyModels nutzen, wenn die Datenmenge waechst.
- Fuer alle Tabs einen einheitlichen lokalen Progress-/Busybereich statt nur modaler Fehlerdialoge verwenden.

### Zahlungsclearing

Positive Basis: Analyse, Monatsreset und Buchen sind Workerjobs mit Fortschritt. Tabelle verwendet `DataTable`.

P0/P1:

- `_assign_invoice()` ruft `PaymentClearingService.assign_invoice()` synchron auf (`payment_clearing/view.py:259-291`). Falls sevDesk/API beteiligt ist, als Worker ausfuehren.
- Checkboxklick und `Alle auswaehlen` bauen die komplette Kandidatenliste und Tabelle neu. Nur betroffene Modelzeilen mit `dataChanged` patchen; fuer Alle-Auswahl einen Model-Batch verwenden.
- Worker-Error zeigt Dialog, aber ein persistenter nicht-modaler Fehlerstatus ist schneller bedienbar.
- Resultaufbereitung grosser Booking-Batches in Worker vorstrukturieren; GUI patcht nur geaenderte IDs.
- Analyseergebnis cachen und bei erneutem Seitenwechsel sofort anzeigen.

### Statistik

Positiv: der teure Summaryload ist asynchron und ein Loadertext ist sichtbar.

Verbesserungen:

- `_load()` braucht einen Running-/Generation-Guard; der Button wird zwar deaktiviert, programmgesteuerte Doppelstarts bleiben moeglich.
- Monatstabelle von `QTableWidget` auf Model/View umstellen.
- `resizeColumnToContents()` nach jedem Load entfernen.
- Letzten Summary-Snapshot sofort anzeigen und `Aktualisiere...` setzen.
- KPI-Karten nicht ueber `findChild` pro Update suchen; direkte Labelreferenzen halten.

### Provisionen

Positive Basis: Profilberechnung, Artikelload und CSV/XLSX-Export sind Workerjobs; grosse Haupttabellen nutzen `DataTable`.

P0/P1:

- `CommissionView._run_musikheroes()` liest Checkboxen innerhalb der Workerfunktion (`calculation/view.py:368-375`). Werte vorher snapshotten.
- Neu-laden-/Cache-/Exportbuttons benoetigen einheitliche Busytexte und Disabled-State; aktuell zeigt vor allem ein Statuslabel den Lauf.
- Mehrere Tabellen werden im Resulthandler direkt hintereinander komplett ersetzt. Darstellungs-Payload im Worker erzeugen und GUI-Updates auf Eventloop-Slices verteilen, falls Messung ueber 50 ms zeigt.
- Artikelload setzt keinen sichtbaren Busy-/Running-Guard am Refreshbutton.
- Kleine Sofortberechnung (`_run_calc`) soll synchron bleiben; Threading waere hier teurer als die Operation.
- Export-Fertigmeldung bevorzugt als Toast; modaler Dialog nur fuer Fehler oder explizite Bestaetigung.

### Layout

Positive Basis: PDF-Duplizierung, QR-Erzeugung, Leerseitenverarbeitung und Covererzeugung laufen ueber Worker.

P0/P1:

- Alle Werkzeuge teilen ein einziges `_worker`-Feld und nur A5 deaktiviert konsequent seinen Startbutton. Gleichzeitige QR-/Cover-/Blank-Aktionen koennen Referenzen ueberschreiben. Pro Aktion eigener Job-Key oder zentraler Manager.
- `_pick_blank_source()` liest die gesamte PDF synchron in den Speicher (`layout/view.py:307-316`). Nur Pfad merken; Datei im Worker lesen.
- QR-/Blank-/Coverbuttons sofort deaktivieren und wieder aktivieren; Status `Wartet/Verarbeitet/Speichert` anzeigen.
- Ergebnisdatei im Worker schreiben. Dateidialog im GUI-Thread ist korrekt, das eigentliche Schreiben nicht zwingend.
- Keine unnoetigen Worker fuer ISBN-Pruefung: die kleine lokale Berechnung soll synchron bleiben.

### WuedaraMusi

Aktuell sind die Aktionen fast ausschliesslich lokale, kleine UI-Aenderungen; hier bringt Threading keinen Vorteil.

Verbesserungen fuer die spaetere Persistenz:

- Sobald Archiv/Workflow an DB oder Dateisystem angebunden wird: optimistisches UI, debounced Autosave oder Save-Worker.
- Stueckliste als Model halten, nicht bei jeder Persistenz komplett neu laden.
- Ladefeedback erst einfuehren, wenn reale I/O existiert; fuer reine In-Memory-Aktionen waere es visuell stoerend.

### Reisekosten

Fundstelle: `travel_costs/view.py:24-78`.

Der Modulimport, die Suche nach Bridge-Symbolen und die externe Widgetfactory laufen beim Aufbau synchron im GUI-Thread. Ein unbekanntes Submodul kann beliebig lange importieren oder im Konstruktor I/O ausfuehren.

Umbau:

- Bridge-Verfuegbarkeit/Import im Startup-Idle oder Worker pruefen.
- Danach im GUI-Thread nur das QWidget erzeugen; Vertrag dokumentieren: Widgetkonstruktor darf kein I/O ausfuehren.
- Shell zeigt sofort `Reisekosten-Modul wird vorbereitet...`.
- Fehlversuche pro Sitzung cachen, statt bei jedem neuen Viewaufbau alle Kandidaten erneut zu importieren.

### Marketing

Marketing verwendet wie Notensatz den DB-/JSON-gestuetzten `IdeasStore`. Damit gelten dieselben P0-Befunde: Konstruktorload, Speichern, Loeschen und erneutes Lesen bei jeder Auswahl koennen den GUI-Thread blockieren. Die View soll ein sofort sichtbares Memory-Model erhalten und Persistenzjobs optimistisch im Hintergrund ausfuehren.

### Notensatz

Notensatz verwendet denselben `IdeasStore`; die Performancebefunde sind identisch.

P0:

- `IdeasStore` ist Railway-/DB-gestuetzt. Konstruktor-Migration, `list_ideas`, `add_idea` und `replace_all` koennen DB-I/O ausfuehren. Die Views rufen diese Methoden direkt im Konstruktor, beim Speichern, Loeschen, Selektieren und Refresh auf.
- Bei jeder Auswahl wird die komplette Liste erneut aus dem Store gelesen.

Umbau:

- Einmaliger asynchroner Load in ein ViewModel/Memory-Model.
- Auswahl liest nur aus dem Memory-Model.
- Speichern/Loeschen aktualisiert das Model optimistisch und persistiert im DB-Job.
- Bei Fehler Rollback oder klarer `nicht synchronisiert`-Status am Eintrag.
- Gemeinsames `IdeasListModel` fuer beide Module; keine wiederholte Vollbefuellung von `QListWidget`.

### XW-Copilot

P0:

- Der Konstruktor laedt Konfiguration, Templates und Auditverlauf synchron aus dem Service (`xw_copilot/view.py:39-60`). Dadurch kann bereits die Navigation blockieren.
- Laden/Speichern von Config und Templates, Dry-Run, Audit laden/loeschen und Schemaexport laufen direkt im GUI-Thread.
- Ingress-Start/-Stop kann Socket-/Thread-Shutdown enthalten und sollte nicht ungemessen im Click-Handler laufen.
- Verlauf wird per `QTableWidget` zeilenweise aufgebaut; jeder Ingressrequest laedt den kompletten Verlauf neu.

Umbau:

- Sofort Tabshell anzeigen, dann Config/Templates/History als getrennte Jobs laden.
- History nur beim ersten Oeffnen des Tabs laden; neue Ingress-Eintraege direkt ins Model einfuegen.
- Alle DB-Schreibvorgaenge als Worker mit Busy-/Dirty-State.
- Dry-Run lokal synchron lassen, wenn Messung unter 16 ms; sobald er DB/API nutzt, Worker.
- Verlauf auf `QAbstractTableModel`, Paging und z. B. letzte 100 Eintraege begrenzen.
- Schemaziel zuerst waehlen, Export im Worker schreiben.

### Einstellungen

Die Settings-View ist mit mehr als 1.100 Zeilen schwer und baut viele Bereiche eager. Bereits beim Aufbau werden Secrets und Settings aus Services gelesen. Spaeter erfolgen zahlreiche Railway-/DB- und Secret-Schreibvorgaenge synchron.

P0:

- View in leichte Tabs/Sections teilen und Inhalte erst beim ersten Oeffnen bauen.
- Alle benoetigten Werte in einem Settings-Snapshot-Worker laden; danach Formfelder in einem GUI-Update setzen.
- `_load_queue_settings()` fuehrt viele einzelne Repository-Reads seriell im GUI-Thread aus (`settings/view.py:656-690`). Repository-Batchread in einem DB-Job.
- `_save_queue_settings()` fuehrt viele einzelne Writes seriell im GUI-Thread aus. Transaktionaler Batchwrite im Worker; Button sofort `Speichere...`.
- Fulfillment-Vorlage laden/speichern ist DB-I/O und gehoert in Worker.
- PLC-Secrets und Tokens werden in Schleifen synchron gespeichert (`921-1008`, `1010-1045`). `SecretService.save_many()` mit einer DB-Transaktion im Worker.
- ClickUp ist bereits asynchron; der Listen-ID-Persistenzaufruf im Resulthandler sollte in denselben Job bzw. einen kurzen DB-Job.
- DB-Test schliesst die erzeugte Engine nach dem Ping sauber; Finished-State muss Button/Workerreferenz restaurieren.

P1:

- HTML-Vorschau debouncen, falls sie an jede Texteingabe gekoppelt wird; lange Templates koennen `QTextDocument.setHtml()` blockieren.
- Nur Dirty-Felder speichern, nicht jedes Secret neu verschluesseln/persistieren.
- Settings-Cache nach erfolgreichem Save gezielt invalidieren und betroffene AppSignals senden.

## Konkrete Zielarchitektur fuer schnelle Klicks

### UI-Aktionscontroller

Ein kleiner Helper verhindert, dass jede View Busy-/Error-/Finished-Logik neu erfindet:

```python
action = UiAsyncAction(
    owner=self,
    button=self._refresh_btn,
    idle_text="Aktualisieren",
    busy_text="Aktualisiere...",
    status_label=self._status,
    keep_content=True,
)
action.run(job_key="crm-refresh", fn=load_contacts, on_result=self._model.replace)
```

Er muss garantieren:

- sofortiger visueller Busy-State;
- nur ein Job pro Action-Key;
- `finally`-aehnliche Wiederherstellung bei Result, Error und Cancellation;
- Owner-Lebenszeitpruefung;
- optionaler Retry und Toast;
- Click-to-feedback- und Worker-Laufzeitmessung.

### Immutable Request Snapshots

Vor Workerstart werden alle Qt-Werte gelesen:

```python
request = CommissionRequest(
    profile_key=self._active_profile_key,
    period=period,
    include_cancellations=self._include_cancellations.isChecked(),
    include_credit_notes=self._include_credit_notes.isChecked(),
)
worker = BackgroundWorker(lambda: service.run(request))
```

Kein Worker darf `QLineEdit.text()`, `QSpinBox.value()`, `QCheckBox.isChecked()` oder andere QWidget-Methoden aufrufen.

### Latest-wins fuer Navigation und Auswahl

Jede asynchrone Detailansicht verwendet:

- monoton steigende Generation;
- fachlichen Key, z. B. Invoice-ID;
- Cancel-Token fuer alten Job;
- Resultcheck auf Generation, Key, aktuelle Sichtbarkeit und Owner.

`Rechnungen`, Offene Sendungen und Offene Ueberweisungen besitzen Teile davon bereits. Das Muster wird zentralisiert und auf Suche, Produkte, Settings und XW-Copilot uebertragen.

## Umsetzungsphasen

### Phase 0: Messen und Regressionen sichtbar machen

1. `PerfProbe` fuer `click -> busy state`, Queuewait, Workerzeit, Result-Apply und Gesamtzeit.
2. Eventloop-Watchdog mit 16-ms-Timer; Gaps ueber 50/100/250 ms loggen.
3. Strukturierte Logs mit `module`, `action`, `key`, `cache_hit`, `generation`.
4. Debugseite unter Einstellungen: langsamste 20 Aktionen, aktive Jobs, Cache-Hit-Rate.
5. Baseline fuer jede Sidebarseite und zehn haeufigste Rechnungsaktionen erfassen.

### Phase 1: P0-Freezes entfernen

1. Rechnungen-Shell statt synchroner Vollmaterialisierung.
2. Produkte Bulk-Feld, Brand und sevDesk-Anlage asynchron.
3. Offene-Sendungen-/Ueberweisungen-Aktionen asynchron.
4. Settings-Snapshot/Batchsave asynchron.
5. Marketing/Notensatz und XW-Copilot von synchronem DB-I/O befreien.
6. Alle Widgetzugriffe aus Workerfunktionen entfernen.
7. `QApplication.processEvents()` aus Aktionspfaden entfernen.

### Phase 2: Tabellen und Detailaufbau

1. CRM, Statistik, Copilot-History auf Models.
2. Rechnungs-Produktdetails auf ListModel/Delegate.
3. Produkte-Syncvergleich im Worker/Model statt Dict-Neuaufbau.
4. Clearing-Checkboxen per Modelpatch.
5. Result-Apply-Budget messen und grosse Updates chunked anwenden.

### Phase 3: Zentraler JobManager

1. Prioritaetsqueues und globale Limits.
2. Owner, Cancellation, latest-wins und Timeout.
3. Warmup-Pause bei sichtbaren Aktionen.
4. Einheitliche `UiAsyncAction`-Busy-/Errorlogik.
5. Sauberer App-Shutdown ohne GUI-Thread-`wait()`.

### Phase 4: Stale-while-revalidate und Prefetch

1. Modul-Snapshots fuer Gutscheine, CRM, Statistik, Clearing, Produkte.
2. Persistenter Rechnungslisten-Snapshot fuer sofortige Tabelle beim Start.
3. Sichtbare/benachbarte Rechnungen priorisieren; historische Rows erst bei Auswahl.
4. Cache-TTLs und gezielte Invalidierung nach Schreibaktionen.

## Testplan

### UI-Reaktionszeit

- Parametrisierter Test fuer jede Sidebarseite: nach Click ist innerhalb einer Eventloop-Runde Shell/Placeholder sichtbar.
- Slow-Fake-Service mit 1 s Wartezeit: GUI-Timer muss waehrenddessen weiterlaufen.
- Jeder lange Button zeigt innerhalb von 100 ms Busytext oder lokalen Loader.
- Doppelklick startet keinen doppelten fachlichen Job.

### Rechnungswechsel

- 20 schnelle Zeilenwechsel: Stammdaten folgen jedem MousePress sofort.
- Nur das Resultat der letzten Invoice-ID darf Detail/Wix/Produkte aktualisieren.
- Alter Warmup darf sichtbaren Detailjob nicht laenger als ein kleines Queuebudget verzoegern.
- Persistenter Cachezugriff mit kuenstlicher 500-ms-Latenz darf den GUI-Thread nicht blockieren.
- 100 Produktpositionen duerfen keinen Eventloop-Gap ueber 50 ms erzeugen.

### Tabellen

- 1.000/10.000 Rows fuer Produkte, CRM und Copilot-History.
- Model-Reset/Filter/Sort messen; GUI-Apply unter 50 ms oder chunked.
- Einzelne Checkbox-/Statusaenderung darf keinen Full-Reset ausloesen.

### Fehler und Cancellation

- Errorpfad reaktiviert jeden Button und entfernt Busytext.
- Navigation weg waehrend Worker: kein Zugriff auf geloeschtes Widget.
- Abgebrochener/veralteter Job darf kein Resultat anwenden.
- App schliesst ohne blockierendes `wait()` und ohne `QThread destroyed while running`.

### Thread-Sicherheit

- Testdouble fuer Widgets, das Zugriff ausserhalb des GUI-Threads erkennt.
- Services mit gemeinsamem HTTP-/SQLite-Client unter parallelen Jobs testen.
- Keine modalen Dialoge aus Workerthreads; alle UI-Signale queued zum Owner.

## Definition of Done

Eine Performance-Aenderung gilt erst als fertig, wenn:

- der Click-Handler vor der langsamen Arbeit sichtbares Feedback setzt;
- kein Netzwerk-, DB-, Datei-, PDF- oder Druckaufruf im GUI-Thread verbleibt;
- der Worker keine Qt-Widgets liest oder veraendert;
- der Resulthandler gemessen unter dem GUI-Budget bleibt oder gechunkt ist;
- Stale-Result-/Owner-Guard vorhanden ist;
- Fehler und Cancellation den UI-Zustand garantiert restaurieren;
- mindestens ein Slow-Fake-UI-Test beweist, dass der Eventloop weiterlaeuft;
- Cache- und Refreshverhalten dokumentiert sind.

## Empfohlene erste Tickets

1. **PERF-001:** Performance-Probe und Eventloop-Watchdog.
2. **PERF-002:** `UiJobManager` um Owner, latest-wins, Cancellation und Metriken erweitern.
3. **PERF-003:** `UiAsyncAction` fuer einheitlichen Button-/Loading-Zustand.
4. **PERF-004:** Rechnungen-Shell und Entfernung des synchronen MainWindow-Sonderfalls.
5. **PERF-005:** Persistent-Wix-Cache und Draft-Preview aus dem Rechnungs-GUI-Thread.
6. **PERF-006:** Offene Sendungen/Ueberweisungen: alle Aktionsbuttons auf Worker.
7. **PERF-007:** Produkte Bulk-Feld/Brand/sevDesk-Anlage/Druckplaene asynchron.
8. **PERF-008:** Settings Snapshot + transaktionaler Batchsave.
9. **PERF-009:** Marketing/Notensatz Memory-Model mit asynchroner Persistenz.
10. **PERF-010:** XW-Copilot initiale Loads und Writes asynchron, History-Model.
11. **PERF-011:** CRM/Statistik `QTableWidget` ersetzen.
12. **PERF-012:** Rechnungs-Produktdetails auf Model/Delegate.

## Schlussbewertung

Die vorhandene Worker-Vorarbeit ist eine gute Basis. Fuer eine wirklich reaktionsschnelle App muss der Fokus jetzt von "Serviceaufruf ist in irgendeinem Thread" auf die gesamte wahrgenommene Aktionskette wechseln:

`MousePress -> sofortiger sichtbarer Zustand -> priorisierter/cancelbarer Job -> kleines selection-sicheres Result-Apply -> nicht-modales Feedback`.

Den groessten sofortigen Gewinn liefern der Rechnungen-Shell-Umbau, die Entfernung der synchronen Produkt-/Settings-/Copilot- und Rechnungsdialog-I/O sowie ein zentrales latest-wins-Jobmanagement. Danach werden Model/View-Migration und stale-while-revalidate die App auch bei grossen Datenmengen dauerhaft fluessig halten.
