# XW-Office: Architektur- und Performance-Audit RECHNUNGEN, Print-Pipeline, Produkte-Flow

Stand: 21.07.2026
Scope: `ui/modules/rechnungen/` (Hauptview, Tagesgeschaeft-View, alle 11 Dialoge), die komplette Print-Pipeline (`services/printing/*` plus alle Druck-Dialoge), der zentrale Produkte-Flow (`services/products/*`, `ui/modules/products/`)
Methode: read-only Code-Analyse (kein Laufzeit-Profiling), Abgleich gegen die in CLAUDE.md dokumentierte Soll-Architektur (Container/DI, BackgroundWorker, AppSignals, Pydantic, mypy --strict, ~800 Zeilen/Datei, "QPrinter + PyMuPDF at 600 DPI, no Acrobat")

## Gesamtbild

Das `BackgroundWorker`/`Container`/`AppSignals`-Muster aus CLAUDE.md wird in der ueberwiegenden Mehrheit der Buttons korrekt eingehalten. Kein `print()`, praktisch kein rohes Threading, keine gefundenen PyMuPDF-Speicherlecks, saubere Container-Nutzung im Produkte-Modul (`view.py` instanziiert nirgends einen Service direkt). Die Architektur traegt.

Drei Befunde sind aber kritisch, weil sie genau die Bereiche treffen, die taeglich Geld bewegen: der Notendruck (Kerngeschaeft) weicht von der dokumentierten PyMuPDF-Pipeline ab und hat keinen Sicherheitsnetz-Rueckfall; der Lagerbestand wird an zwei unabhaengigen Stellen gefuehrt, die auseinanderlaufen koennen; und Bulk-Schreiboperationen auf den Produktkatalog nutzen den vorhandenen Multi-PC-Lock nicht, obwohl "Multi-PC-Sync via PostgreSQL" explizit die Kernarchitektur ist.

**Zaehlung:** 3 kritisch, 5 hoch, 11 mittel, 10+ niedrig/Code-Qualitaet.

---

## Kritische Befunde

### K1 — Notendruck laeuft ueber PDF-XChange + stillen Acrobat-Fallback statt der dokumentierten PyMuPDF-Pipeline

`config/default.yaml:76-95` · `services/printing/pdf_backends.py:52-285`

CLAUDE.md schreibt fest: *"Printing: QPrinter + PyMuPDF at 600 DPI (no Acrobat)"*. Tatsaechlich sind die vier Standardprofile `noten_simplex`, `noten_duplex`, `brochure_mono`, `brochure_duo` — also der Notendruck, das Kerngeschaeft — auf `backend: "pdf_xchange"` gesetzt und rufen PDF-XChange per `subprocess.run([...,"/printto",...])` auf. Nur `invoice`, `label`, `plc_label` nutzen noch die QPrinter/PyMuPDF-Pipeline. Entspricht dem Commit `980a00e "use pdf xchange printto with acrobat fallback"`.

Schlaegt PDF-XChange fehl, greift `_print_with_acrobat_fallback` (Zeile 234-264) auf hartkodierte Pfade zu `Acrobat.exe`/`AcroRd32.exe` zurueck. Schlaegt auch das fehl, wirft die App eine `RuntimeError` — **es gibt keinen automatischen Rueckfall auf den dokumentierten `QtRasterBackend`**. Schwerer wiegt: der Acrobat-Fallback wartet den Prozess nicht ab (kein `.wait()`/`.communicate()`, nur `time.sleep(min(2.0,...))`) und prueft den Exit-Code nicht. Ein Lizenz-/Update-Dialog von Acrobat/Reader fuehrt zu **stillem Nicht-Drucken, das die App als Erfolg verbucht**.

Druckwege-Uebersicht:

```
(a) Rechnungsdruck  -\
(b) Reprint          |
(c) PLC-Label         >--> PrintQueueService (1 FIFO-Queue, 1 Worker-Thread) --> backend_for_job()
(d) Noten/Broschüren-/                                                              |
(e) Silent-Print (umgeht Queue) ----------------------------------------------------+
                                                                                     |
        invoice / label / plc_label  <---------------------------------------------+---> QtRasterBackend (PyMuPDF+QPrinter, 600 DPI) = dokumentierter Weg
        noten_*, brochure_* (Kerngeschäft)  <----------------------------------------+---> NativePdfCliBackend (PDF-XChange /printto)
                                                                                            |  Fehler
                                                                                            v
                                                                                     Acrobat/Reader-Fallback (kein Wait, kein Exit-Code-Check)
                                                                                            |  Fehler
                                                                                            v
                                                                                     RuntimeError -- KEIN Rückfall auf QtRasterBackend
```

### K2 — Lagerbestand wird an zwei unabhaengigen Stellen gefuehrt, die auseinanderlaufen koennen

`services/products/print_decision.py:199-201` · `services/inventory/service.py:150-172,455-463`

`PrintDecisionEngine` (Stuecke-Panel-Druckweg) liest/schreibt Bestand ueber sevDesk (`PartClient.get_part_stock`/`set_part_stock`). `InventoryService` (START-/Reprint-Workflow) fuehrt einen komplett separaten Bestand unter dem DB-Key `inventory.stock_levels`. Ein Druck ueber das eine System aktualisiert sevDesk, ein Druck ueber das andere den lokalen KV-Store — **beide Quellen koennen divergieren**, mit direkter Folge auf Ueber-/Unterdruck-Entscheidungen bei Noten.

### K3 — Bulk-Schreiboperationen auf den Produktkatalog nutzen den vorhandenen Multi-PC-Lock nicht

`services/products/field_bulk_service.py:262-273` · `brand_service.py:67-89` · `repositories/settings_kv.py:33-66`

`SettingKvRepository` bietet bereits `mutate_value_json()` mit `pg_advisory_xact_lock` fuer genau dieses Problem — verwendet u.a. in `services/ideas/store.py` und `invoice_processing/service.py:407-409`. Der Produkte-Flow schreibt Bulk-Updates (Feld-Bulk-Edit, Marken-Bulk-Update) jedoch per simplem `set_value_json()` (Read-then-Overwrite, keine Sperre). Da CLAUDE.md "Multi-PC sync via PostgreSQL on Railway" explizit als Architektur nennt: Laeuft an zwei Arbeitsplaetzen gleichzeitig ein Bulk-Update, ueberschreibt der zuletzt schreibende PC die Aenderungen des anderen vollstaendig — **ohne Fehler oder Warnung**.

---

## Modul RECHNUNGEN

Analysiert: `view.py` (4764 Zeilen), `tagesgeschaeft_view.py` (1183 Zeilen), 7 Popup-Dialoge (`open_invoice_overview.py`, `offene_ueberweisungen_dialog.py`, `offene_sendungen_dialog.py`, `special_order_dialog.py`, `digital_licenses_dialog.py`, `refund_dialog.py`, `payment_qr_dialog.py`).

### Buttons & Pipelines — Hauptview

| Aktion | Pipeline | Threading |
|---|---|---|
| Aktualisieren / Weitere laden | `InvoiceProcessingService.load_invoice_batch` | BackgroundWorker ok |
| Rechnungs-Entwurf erstellen | `DraftInvoiceService` + `build_missing_product_plan` | BackgroundWorker ok (mehrstufig) |
| Rechnung drucken / senden | `InvoiceProcessingService.print_invoice_for_invoice` / `send_invoice_mail_for_invoice` | BackgroundWorker ok |
| PLC-Label / Noten drucken | `print_dialog.run_plc_label_pdf_print` / `prepare_piece_pdf_print` | BackgroundWorker ok (Vorbereitung sync, unkritisch) |
| Fulfillment-Chips (Retry) | `InvoiceProcessingService.retry_fulfillment_step` | BackgroundWorker ok |
| "wix"-Icon -> Download-Links | `WixOrdersClient.resolve_order_dashboard_url` | **synchron im UI-Thread** |
| Produktzeile "Plan"/"Manage" | `InventoryService.save_product_print_config` | **synchron im UI-Thread (DB Read+Write)** |
| START-Workflow (Tagesgeschaeft) | `InventoryService.build_start_preflight` -> `InvoiceProcessingService.run_start_fullflow` | jede Stufe BackgroundWorker ok |

### Performance-Befunde

**[HOCH] R-H1 — Wix-Download-Link-Klick blockiert die UI**
`view.py:3489-3490` -> `services/wix/client.py:1672-1688`
`resolve_order_dashboard_url` macht bis zu 3 HTTP-Versuche gegen die Wix-API mit `time.sleep(0.25)` zwischen Fehlversuchen — synchron im UI-Thread. Ein Klick auf das "wix"-Icon kann die App fuer die volle Netzwerk-Roundtrip-Zeit einfrieren. Einziger Ausreisser unter den Zeilen-Aktionen; alle anderen (mail, delete, fulfillment-retry) laufen korrekt ueber BackgroundWorker.

**[HOCH] R-H2 — "Plan"/"Manage"-Klick macht DB-Read+Write direkt im UI-Thread**
`view.py:2422-2434, 4681-4687` -> `print_dialog.py:488-514` -> `inventory/service.py:579ff`
`save_product_print_config` ruft zuerst `list_products()` (voller Produkt-Read) und dann einen DB-Write auf — bei jedem Klick auf "Plan" oder "Manage", an zwei nahezu identischen, duplizierten Einstiegspunkten in der Datei.

**[MITTEL] R-M1 — Tabelle wird bei "Weitere laden" komplett neu aufgebaut statt inkrementell erweitert**
`view.py:1672-1680` · `ui/widgets/data_table.py:23-26,120-121,166-171`
`DataTable` bietet bereits `append_rows()` mit gezieltem `beginInsertRows`/`endInsertRows` — wird hier nicht verwendet. Stattdessen: volle Kopie aller Zeilen, Neusortierung, kompletter `beginResetModel()`/`endResetModel()`-Reset. Kostet unnoetig CPU und verliert Auswahl/Scroll-Position bei jedem "Load more".

**[MITTEL] R-M2 — Handgestrickter TTL-Cache statt vorhandenem `TtlCache`**
`view.py:926, 4076-4106`
`_wix_context_cache` reimplementiert TTL-Caching manuell (eigenes `ts`-Feld, `time.monotonic()`-Vergleich) statt `xw_office.core.cache.TtlCache` zu importieren. Keine proaktive Eviction, keine einheitliche `.invalidate()`-Semantik. `TtlCache` wird app-weit an keiner einzigen Stelle instanziiert — siehe X2.

**[MITTEL] R-M3 — Wiederholtes volles Paging der Rechnungsliste per Timer statt lokaler Zaehlung**
`view.py:939-941` (120s-Timer) · `tagesgeschaeft_view.py:328-330` (60s-Timer) -> `invoice_processing/service.py:2065-2081`
Beide Timer loesen `count_invoices` aus, das die komplette offene Rechnungsliste seitenweise ueber die sevDesk-API abzaehlt — alle 60-120s, obwohl `self._summaries` im Speicher bereits einen Grossteil der Daten haelt. Laeuft im Worker (kein UI-Freeze), aber unnoetige wiederkehrende externe API-Last.

### Konsistenz & Code-Qualitaet — Hauptview

- **Drei verschiedene Cancel-Idiome** fuer dieselbe Aufgabe koexistieren im selben Modul: `BackgroundWorker.cancel()`, `CancelToken`/`BackgroundJobManager`, und ein haendischer Bool-Flag `_start_abort_requested`. (`view.py:4385, 3936-3961` · `tagesgeschaeft_view.py:682,924,1083`)
- **Uneinheitliches Nutzer-Feedback:** mal `AppSignals.status_message`, mal blockierendes `QMessageBox.information` fuer strukturell gleiche "Job fertig"-Ereignisse. `AppSignals.show_toast` existiert exakt dafuer, wird aber nirgends im Modul genutzt. (`view.py:3225-3229, 4252-4256, 4322-4326` · `tagesgeschaeft_view.py:1045-1049`)
- **Kapselung gebrochen:** private Methode direkt aufgerufen, obwohl daneben eine oeffentliche existiert. (`tagesgeschaeft_view.py:1052`, `_reload_first_page()` statt `reload_first_page()`)
- **Dreifach kopierter Stylesheet-Block** fuer die drei Alert-Buttons, obwohl `tagesgeschaeft_view.py` fuer dieselbe Anforderung bereits sauber eine Factory `_build_alert_button()` hat. (`view.py:1016-1022, 1030-1036, 1044-1050`)
- **~83 Zeilen toter Code** nach einem `return` — alte Widget-Implementierung der Stuecke-Liste, ersetzt durch `_PieceListModel`/`_PieceDelegate`, nie entfernt. Plus 5 weitere nie aufgerufene Methoden. (`view.py:4519-4602`)
- **Live-UI-Bug durch Encoding-Korruption:** `setText(requested_ref or "â€”")` zeigt im Fehlerfall kaputten Mojibake-Text statt eines Gedankenstrichs an. (`view.py:4064`)
- **Fehlende Typhints** (Verstoss gegen mypy --strict) in 5 Delegate-Klassen bei `paint`/`sizeHint`, obwohl die neuere `_PieceDelegate` im selben File vollstaendig typisiert ist. (`view.py:193,245,257,290,312,339,392,413,466,507`)
- Magic Number `status=100` statt der vorhandenen Konstante `_DRAFT_STATUS` — an einer Stelle in `view.py`, an drei Stellen in `tagesgeschaeft_view.py` (Konstante dort gar nicht importiert). (`view.py:2098` · `tagesgeschaeft_view.py:555,704,793`)
- `_build_ui` (~377 Zeilen) und `eventFilter` (~100 Zeilen, 4 Spalten-Aktionen in einer Methode verschachtelt) sind deutlich überlange Methoden. (`view.py:980-1356, 3079-3179`)

### Popup-Dialoge

| Dialog | Zweck | Async beim Oeffnen? |
|---|---|---|
| OffeneUeberweisungenDialog | Transfer-Mails abgleichen, OpenAI-Zusammenfassung, QR-Zahlung | ja |
| OffeneSendungenDialog | Versand-Workflow, Label/Lieferschein-Druck | ja |
| SpecialOrderDialog | Wix-Payment-Links fuer Sonderauftraege | ja |
| DigitalLicensesDialog | Queue offener digitaler Lizenzen | ja (aber siehe PO-H1) |
| RefundDialog | Reine Bestaetigung, kein I/O | - |
| PaymentQrDialog | QR-PNG-Anzeige, lokale Datei | - |

**[HOCH] PO-H1 — N+1 Wix-Calls synchron im UI-Thread nach Schliessen des Lizenzen-Dialogs**
`view.py:1936-1938` -> `digital_licenses_dialog.py:92-93` -> `services/digital_licenses/service.py:74-97`
`open_count()` laeuft nach `dlg.exec()` synchron auf dem UI-Thread, macht einen sevDesk-Call und danach fuer jede offene Rechnung einen eigenen Wix-Call `is_reference_digital_only(ref)` in einer Schleife — ohne Cache, obwohl `open_invoice_overview.py:319-328` fuer denselben Zweck bereits einen Cache-Mechanismus implementiert. Bei mehreren offenen Rechnungen: spuerbares Einfrieren direkt nach Dialogschluss.

**[MITTEL] PO-M1 — Gleiches Muster, geringeres Risiko: Sendungen-/Ueberweisungen-Dialoge**
`view.py:1437-1438, 1443-1444` -> `sendungen/service.py:688` · `transfers/service.py:438`
`dlg.open_count()` laeuft ebenfalls synchron nach `exec()`, hier gegen Railway-Postgres statt externe API — geringeres, aber strukturell identisches Risiko.

**[MITTEL] PO-M2 — Kein Debounce beim Tippen im Sonderauftrag-Filter**
`special_order_dialog.py:84, 119-130`
Voller `QListWidget`-Rebuild bei jedem Tastendruck, kein `QTimer`-Debounce, kein `setUpdatesEnabled(False)` um Clear+Repopulate.

**[MITTEL] PO-M3 — Absturzrisiko: fehlende Guards gegen zerstoertes Dialog-Objekt**
`digital_licenses_dialog.py` (kein closeEvent/isValid) · `special_order_dialog.py` (kein closeEvent/isValid)
Die Ueberweisungen- und Sendungen-Dialoge schuetzen sich korrekt gegen Worker-Signale, die nach Dialogschluss ankommen (`closeEvent`-Override, `isValid()`-Checks, Sequence-Token). `DigitalLicensesDialog` und `SpecialOrderDialog` haben keinen dieser Schutzmechanismen — ein Worker-Signal kann nach Schliessen auf ein bereits zerstoertes Qt-Objekt zugreifen.

### Konsistenz & Code-Qualitaet — Popups

- **`AppSignals` wird in keinem der 7 Dialoge verwendet** — jeder rollt eigene Status-Labels/`QMessageBox`, obwohl das umgebende `view.py` es aktiv nutzt.
- **"Als erledigt markieren" 3x unterschiedlich:** mit Bestaetigung in Ueberweisungen/Lizenzen, ohne Bestaetigung in Sendungen — trotz gleicher Irreversibilitaet. (`offene_ueberweisungen_dialog.py:471-484` · `offene_sendungen_dialog.py:598-616` · `digital_licenses_dialog.py:177-187`)
- **Drei nahezu identische, aber separat kopierte "Action-Runner"** statt einer gemeinsamen Basis — mit sichtbar unterschiedlichem Verhalten (Button-Text-Swap, Fehlertitel). (`offene_ueberweisungen_dialog.py:506-528` · `offene_sendungen_dialog.py:624-648` · `digital_licenses_dialog.py:189-197`)
- **Service direkt instanziiert statt ueber Container:** `LabelPrinter(...)` statt `container.resolve(LabelPrinter)` — konkreter Verstoss gegen "UI-Widgets erzeugen Services nie selbst". (`offene_sendungen_dialog.py:494-497`)
- Dataclasses statt Pydantic-Modellen fuer Daten, die direkt aus externen APIs stammen (CLAUDE.md verlangt Pydantic fuer API-Antworten) — durchgaengiges Muster ueber alle 7 Dialoge. (`services/transfers/models.py:32,47` · `services/sendungen/service.py:40,53,61`)
- `type: ignore[arg-type]` zum Umgehen korrekter Typisierung statt sie wie in den uebrigen 5 Dialogen korrekt zu setzen. (`special_order_dialog.py:34-35` · `digital_licenses_dialog.py:189,193`)
- Keine gemeinsame Basisklasse fuer die drei strukturell fast identischen "Case-Queue"-Dialoge (Laden/Anzeigen/Fehlerbehandlung nahezu 1:1 dupliziert). (`offene_ueberweisungen_dialog.py:184-231` · `offene_sendungen_dialog.py:261-305`)

---

## Print-Pipeline (End-to-End)

Fuenf Druckwege nachverfolgt: Rechnungsdruck, Reprint, PLC-Label, Noten/Broschueren (Stuecke-Panel), Silent-Print. K1 oben betrifft direkt den wichtigsten dieser fuenf Wege (Noten).

**[HOCH] PP-H1 — PowerShell-Subprozess-Spam pro Druckkopie blockiert die einzige Print-Queue**
`services/printing/pdf_backends.py:90-134, 309-355`
`_wait_for_spooler_change` pollt bis zu 8 Sekunden lang alle 0,4s per `_windows_print_job_snapshot` — jeder Aufruf startet einen neuen `powershell.exe`-Prozess. Bei mehreren Kopien (z.B. 20 Notenexemplaren) sind das potenziell hunderte PowerShell-Starts fuer einen einzigen Auftrag. Da `PrintQueueService` nur einen Worker-Thread fuer alle Jobkinds hat (`invoice`, `label`, `product`, `music` in derselben FIFO), verzoegert das alle nachfolgenden Druckauftraege — auch zeitkritische Rechnungen.

**[MITTEL] PP-M1 — Fire-and-forget-Druckauftraege geben dem Nutzer kein Erfolgs-/Fehler-Feedback**
`core/signals.py:21-22` · `print_dialog.py:428-439` · `plc_label_dialog.py:553-571`
`AppSignals.print_job_queued`/`print_job_completed` sind definiert, werden aber app-weit nirgends emittiert oder abonniert. Die tatsaechlichen Signale von `PrintQueueService` (`job_queued/started/finished/failed`) werden ebenfalls von keiner UI-Komponente abonniert. Alle `queue.enqueue()`-Aufrufe ohne `wait=True` liefern dem Nutzer daher keinerlei Rueckmeldung, ob der Druck wirklich passiert ist.

**[MITTEL] PP-M2 — Uneinheitliche Drucker-Verfuegbarkeitspruefung vor dem Drucken**
`print_dialog.py:362-383,393,526` · `plc_label_dialog.py:545-571` · `offene_sendungen_dialog.py:494-499` · `view.py:658-665`
`print_dialog.py` prueft konsequent `evaluate_printer_status` vor jedem Druck. PLC-Label, Sendungen-Label und Custom-Label enqueuen dagegen ohne jede vorherige Verfuegbarkeitspruefung.

**[MITTEL] PP-M3 — Reine Python-Pixel-Schleife zur Farb-Klassifizierung pro Seite, ohne seitenuebergreifenden Cache**
`services/printing/pdf_renderer.py:313-355,430`
`classify_pdf_page_for_print` iteriert pixelweise in reinem Python ueber ein 72-DPI-Sample. Der `analysis_cache` gilt nur innerhalb eines einzelnen `print_pdf_with_qprinter`-Aufrufs — bei mehreren Plan-Zielen (`planned_pdf_printer.py`) wird dieselbe PDF/Seite mehrfach neu geoeffnet und analysiert. Laeuft im Queue-Thread, kein UI-Freeze, aber unnoetige CPU-Last.

**[NIEDRIG] PP-L1 — PdfPreviewDialog rendert synchron alle Seiten im Konstruktor, ist aber toter Code**
`ui/dialogs/pdf_preview_dialog.py:41-58`
Kein `BackgroundWorker` beim Rendern aller Seiten. Aktuell folgenlos, da die Klasse (ebenso wie `ProgressDialog`) im gesamten Code nirgends instanziiert wird — es existiert dadurch kein einheitlicher Fortschrittsdialog fuer Druckvorgaenge.

**[POSITIV] Kein UI-Blocking im Kern-Druckpfad, keine PyMuPDF-Speicherlecks**
Alle produktiven `wait=True`-Aufrufe sind korrekt in `BackgroundWorker`-Jobs eingebettet. Alle `fitz.open()`-Aufrufe schliessen Dokumente konsequent in `finally`-Bloecken; `Pixmap`-Objekte werden per Refcounting sauber freigegeben. `print_decision.py`/`pdf_bulk_mapper.py` sind sauber von der Druck-Ausfuehrung getrennt (reine Entscheidungslogik, kein direkter Queue-Zugriff).

---

## Zentraler Produkte-Flow

`ProductCatalogService` und `InventoryService` sind zwei getrennte In-Memory-Repraesentationen derselben DB-Quelle (ein einziges JSON-Blob pro Tabelle). Der Katalog wird bei Konstruktion einmalig geladen und muss danach manuell per `reload_from_settings()` synchronisiert werden — das ist die Wurzel mehrerer Befunde unten, zusaetzlich zum bereits genannten K3.

**[HOCH] PR-H1 — N+1 DB-Reads in der Bulk-Validierungsschleife**
`services/products/field_bulk_service.py:231-238`
Die Set-Comprehension `{row.sku ... for row in self._inventory.list_products()}` steht innerhalb des Generators einer `any(...)`-Pruefung und wird dadurch bei jeder Iteration ueber `report.items` neu ausgewertet — `list_products()` (voller DB-Roundtrip + JSON-Parse) laeuft damit einmal pro ausgewaehltem SKU statt einmal insgesamt. Bei 200 SKUs: 200 sequentielle Netzwerk-Roundtrips statt einem. Laeuft im Worker (kein UI-Freeze), streckt die Operation aber von Millisekunden auf viele Sekunden.

**[MITTEL] PR-M1 — Drei redundante volle Katalog-Reads pro Marken-Update**
`services/products/brand_service.py:56-133,224`
`apply_brand_update()` -> `apply_local_brand_update()` -> `_build_report()` lesen `list_products()` dreimal innerhalb derselben logischen Operation, ohne Zwischen-Caching.

**[MITTEL] PR-M2 — Ungecachter Wix-Call trotz bereits im Speicher gehaltener Daten**
`brand_service.py:141` vs. `field_bulk_service.py:174,193,213` · `view.py:1499`
`ProductFieldBulkService` nimmt `wix_products` als Parameter entgegen (kein Extra-Call, `view.py` uebergibt bereits geladene `self._wix_rows`). `ProductBrandService` hat kein aequivalentes Interface und erzwingt bei jedem Brand-Bulk-Update mit Wix-Sync einen frischen vollen `list_products()`-Call gegen die Wix-API.

**[MITTEL] PR-M3 — Synchroner DB-Call im UI-Thread nach Bulk-Operationen**
`view.py:1328-1339, 1359-1392`
`_on_apply_done`/`_on_legacy_import_done` sind Qt-Slots auf dem UI-Thread und rufen direkt `ProductCatalogService.reload_from_settings()` auf — ein blockierender Postgres-Roundtrip ohne weiteren Worker.

**[POSITIV] PR-P1 — Container-Nutzung und Tabellen-Virtualisierung vorbildlich**
`view.py` instanziiert an keiner Stelle einen Service direkt, sondern loest durchgaengig ueber `self._container.resolve(...)` auf (14 Fundstellen geprueft). `DataTable.set_data()` nutzt korrekt `beginResetModel`/`endResetModel`, das Qt-Model ist view-seitig virtualisiert — reines Rendering grosser Produktlisten ist nicht der Flaschenhals, das eigentliche Risiko liegt im DB-Blob-Load/Save-Muster (siehe K3, PR-H1).

### Konsistenz & Code-Qualitaet — Produkte

- **Fehlende Katalog-Invalidierung nach Bulk-Updates:** `_on_field_update_done`/`_on_brand_update_done` rufen `_load_sync_sources()`, aber nicht `ProductCatalogService.reload_from_settings()` — im Gegensatz zu `_on_apply_done`/`_on_legacy_import_done`, die das korrekt tun. Der Katalog, den `PrintDecisionEngine` fuer SKU-Aufloesung nutzt, bleibt nach einem Bulk-Feld-Edit bis zum naechsten Wix-Apply oder App-Neustart veraltet.
- **Zwei parallele Async-Muster im selben Feature-Bereich:** `bulk_field_dialog.py` nutzt den robusteren `UiAsyncAction`-Wrapper (Busy-State, Stale-Result-Unterdrueckung automatisch); `view.py` verwaltet stattdessen sieben rohe `BackgroundWorker`-Attribute mit manuellen `isRunning()`-Guards von Hand.
- `services/products/__init__.py` exportiert `ProductBrandService`, aber nicht `ProductFieldBulkService` — die kuratierte Public API ist unvollstaendig und wird von den eigentlichen Konsumenten ohnehin umgangen (direkte Submodul-Importe).
- `except Exception: pass` ohne jegliches Logging beim Katalog-Reload bzw. bei korrupten Daten — macht Debugging von Datenkorruption sehr schwer. (`view.py:1332-1337,1385-1390` · `catalog.py:259-264`)
- `field_bulk_service.py:538-620`: fuenf strukturell identische `if field_name == "...": return ProductRow(...)`-Bloecke (~80 Zeilen vermeidbare Duplizierung), liesse sich mit `dataclasses.replace(row, **{field_name: value})` drastisch verkuerzen.

---

## Uebergreifende Muster (alle drei Bereiche)

Diese Punkte tauchten unabhaengig in mindestens zwei der vier Teil-Analysen auf — das deutet auf app-weite Muster hin, nicht auf Einzelfaelle.

- **X1 — `AppSignals` wird nur teilweise genutzt.** `status_message`/`navigate_to_module` sind in den Hauptviews etabliert, aber `show_toast`, `inventory_changed`, `print_job_queued`/`print_job_completed` werden app-weit nirgends emittiert oder abonniert. Popup-Dialoge nutzen den Signal-Bus ueberhaupt nicht — jeder rollt eigenes Feedback.
- **X2 — `TtlCache` (core/cache.py) wird app-weit an keiner einzigen Stelle instanziiert**, obwohl er die dokumentierte Standardloesung ist. Stattdessen: handgestrickte Dict-Caches in `view.py` (Rechnungen), Ad-hoc-`get_cached_*` im Wix-Client, kein Cache-Reuse zwischen `open_invoice_overview.py` und `digital_licenses_dialog.py` fuer denselben Wix-Lookup.
- **X3 — Mehrfache, unterschiedliche "Cancel"- und "Action-Runner"-Idiome** fuer strukturell gleiche Aufgaben, sowohl innerhalb von `tagesgeschaeft_view.py` (3 Cancel-Muster) als auch zwischen den drei Case-Queue-Dialogen (3 separat kopierte Action-Runner).
- **X4 — Direkte Service-Instanziierung statt Container** vereinzelt trotz sonst sauberer DI-Disziplin: `LabelPrinter(...)` in `offene_sendungen_dialog.py` und `view.py` (Custom-Label).
- **X5 — Dataclasses statt Pydantic fuer API-Daten**, entgegen CLAUDE.md "All API responses: Pydantic models" — durchgaengig in `transfers`, `sendungen`, `digital_licenses`.
- **X6 — Breites `except Exception` mit `#noqa: BLE001`** ist der De-facto-Standard in allen vier Analysen, nicht die Ausnahme — technisch kein "bare except", aber im Widerspruch zum CLAUDE.md-Geist "catch specific exceptions".
- **X7 — Dateilaengen-Vorgabe (~800 Zeilen) wird von den zentralen Views massiv gerissen:**

| Datei | Zeilen | Faktor ueber Limit |
|---|---|---|
| `ui/modules/rechnungen/view.py` | 4764 | ~6x |
| `ui/modules/products/view.py` | 1863 | ~2,3x |
| `ui/modules/rechnungen/tagesgeschaeft_view.py` | 1183 | ~1,5x |

---

## Priorisierte Massnahmen

### Klein — sollte kurzfristig gemacht werden

| Massnahme | Bezug |
|---|---|
| Acrobat-Fallback: Prozess abwarten (`.wait()`), Exit-Code pruefen, bei Doppelfehler auf `QtRasterBackend` statt `RuntimeError` zurueckfallen | K1 |
| Die 4 identifizierten synchronen UI-Thread-Calls in `BackgroundWorker` verpacken (Wix-Download-Link, Plan/Manage-Save, Lizenzen-`open_count`, Katalog-Reload nach Bulk-Update) | R-H1, R-H2, PO-H1, PR-M3 |
| N+1-Schleife in `field_bulk_service.py:231-238` reparieren: Set-Comprehension vor die Schleife ziehen | PR-H1 |
| `isValid()`/`closeEvent`-Guards zu `DigitalLicensesDialog` und `SpecialOrderDialog` hinzufuegen (Absturzrisiko) | PO-M3 |
| Toten Code entfernen (83 Zeilen unreachable, 5 tote Methoden, ungenutzte `PdfPreviewDialog`/`ProgressDialog` entweder anschliessen oder loeschen), Mojibake-Bug in Zeile 4064 fixen | - |

### Mittel — naechste 1-2 Iterationen

| Massnahme | Bezug |
|---|---|
| Bulk-Writes (Feld-/Marken-Update) auf `mutate_value_json()` mit Advisory-Lock umstellen | K3 |
| PDF-XChange-Spooler-Polling ersetzen (kein `powershell.exe` pro Snapshot — z.B. Win32-API oder deutlich selteneres Polling) | PP-H1 |
| `append_rows()` fuer "Weitere laden" statt vollem Tabellen-Reset verwenden | R-M1 |
| `PrintQueueService.job_*`-Signale (oder die bereits definierten `AppSignals.print_job_*`) tatsaechlich an die UI anschliessen, damit Fire-and-forget-Drucke Feedback geben | PP-M1 |
| Ad-hoc-Caches durch `TtlCache` ersetzen; Wix-Produktliste zwischen Brand- und Field-Bulk-Service teilen | X2, PR-M2 |
| Gemeinsame Basisklasse/Mixin fuer die drei Case-Queue-Dialoge (Laden, Action-Runner, Close-Guards) | X3 |

### Gross — bewusst planen

| Massnahme | Bezug |
|---|---|
| Entscheiden: Notendruck zurueck auf `QtRasterBackend`/PyMuPDF (CLAUDE.md einhalten) oder CLAUDE.md bewusst aktualisieren, falls PDF-XChange eine begruendete Entscheidung war (z.B. Vektorqualitaet) — aber dann mit echtem Sicherheitsnetz | K1 |
| Die zwei getrennten Bestandssysteme (sevDesk-Stock vs. lokaler KV-Store) auf eine einzige Quelle konsolidieren | K2 |
| `rechnungen/view.py` (4764 Zeilen) und `products/view.py` (1863 Zeilen) aufteilen — z.B. Delegates in eigene Module, Tabs/Panels in eigene Widget-Klassen | X7 |
