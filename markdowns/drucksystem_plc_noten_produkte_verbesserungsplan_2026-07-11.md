# Intensivanalyse und Verbesserungsplan: PLC-Etiketten, Noten- und Produktdruck

Stand: 11. Juli 2026

Update 2026-07-29: Der PDF-XChange-Produktdruck ist auf echter Hardware abgenommen. Testlauf QA-01 bis QA-04
(`noten_simplex`, `noten_duplex`, `brochure_mono`, `brochure_duo`) wurde ueber den produktiven
`print_pdf_by_plan()`-/PDF-XChange-Pfad an die Windows-Spooler uebergeben. Nutzerkontrolle auf Papier:
Simplex und Duplex funktionieren, Schaerfe und Zentrierung sind absolut ok. Der PDF-XChange-Pilot fuer
Noten-/Produktdruck ist damit fachlich abgeschlossen; PDF-XChange bleibt der Zielpfad.

## Ziel und Kurzfazit

Rechnungsdruck und Brother-Adressetikettendruck bleiben unverändert, weil sie laut Praxis zuverlässig funktionieren. Für die beiden offenen Qualitätsprobleme und die fehlende UI-Parität ist eine gezielte Trennung der Backends sinnvoll:

1. **PLC-Etiketten:** den bestehenden internen Pfad zunächst behalten, aber A5-Seitenlayout, Zielrechteck und Skalierung deterministisch machen. Die derzeitige Ausgabe zeichnet ein A5-PDF unskaliert ab Papierursprung, ohne das A5-Layout am `QPrinter` zu setzen. Druckertreiberzustand und tatsächlich gemeldete Auflösung können dadurch sporadisch zu Beschnitt, falscher Skalierung oder Versatz führen.
2. **Noten/Printing Products:** nicht länger standardmäßig als Bitmap mit heuristischer Bildkorrektur drucken. Die Beispiel-PDFs enthalten hochwertige Vektornotation; der aktuelle Renderer rastert jede Seite und verändert erkannte Notenseiten zusätzlich. Empfohlen wird ein **austauschbares PDF-Backend** mit einem nativen, stillen PDF-Drucker als bevorzugtem Produkt-Backend. Als pragmatischer Pilot ist PDF-XChange Editor CLI am stärksten; Acrobat bleibt optionaler Referenz-/Fallback-Pfad, nicht der Standard.
3. **Dialoge und Druckpläne:** einen einzigen wiederverwendbaren `ProductPrintDialog`/Controller schaffen. Analysis Panel, Hauptmenü **PRODUKTE**, START-Automatik und Nachdruck müssen denselben Resolver, dieselbe Validierung und dieselbe Job-Erzeugung benutzen.
4. **Analysis Panel:** neben **jedem physischen Printing Product** in der Produkt-Zusammenfassung einen Druckbutton plus Mengenwahl und Plan-Button anzeigen, nicht nur bei aktuell `flagged` Produkten.

Vor einer endgültigen Backend-Entscheidung ist ein realer A/B-Test auf den vorhandenen Canon-/A5-Druckerqueues notwendig. Softwaretests können Druckertreiber, Gerätemargen, Duplex-/Broschüren-Finishing und sichtbare Schattenqualität nicht abschließend simulieren.

## Umsetzungsstand 2026-07-11

Erledigt im Code:

- Phase 1/2 teilweise umgesetzt: `PdfPrintJob`, Druckprofile, Queue, Planresolver und Renderer kennen jetzt `page_size`, `orientation`, `scale_mode` und `alignment`.
- PLC-Webservice-/Archivdruck erzeugt jetzt explizit A5 Portrait, `printable_origin`, `fit`, `center`; das Profil `plc_label` traegt dieselben Defaults.
- Analysis Panel zeigt Produkt-Druck/Plan nicht mehr nur fuer markierte SKUs, sondern fuer alle nicht-digitalen Positionen.
- Manueller Produktdruck aus dem Analysis Panel wartet auf die Queue-Bestaetigung, bevor Bestand/sevDesk aktualisiert wird.
- Menue **Produkte** hat eine Aktion `Auswahl drucken`, die denselben `run_piece_pdf_print()`-/`ProductPrintConfigDialog`-/`print_pdf_by_plan()`-Pfad nutzt.
- Ergaenzte Tests sichern Planfelder, PLC-A5-Jobdaten und Fit/Center-Zielrechteck ab.

Noch offen:

- PDF-XChange-/Native-Backend-Pilot fuer hochwertigen Notendruck: abgeschlossen am 2026-07-29; Simplex/Duplex, Schaerfe und Zentrierung auf Papier abgenommen.
- Hardware-Abnahme PLC: zehn Drucke nach wechselnden A4/A5-Jobs auf dem echten `Paketmarke A5`-Drucker.
- Entscheidung, ob der Produktdruck im Menue **Produkte** Lagerbestand erhoehen soll. Aktuell startet er bewusst nur den Druck, weil dort kein Rechnungs-/Produktionskontext vorhanden ist.

## Untersuchte Bereiche

- `src/xw_studio/services/printing/pdf_renderer.py`
- `src/xw_studio/services/printing/print_queue.py`
- `src/xw_studio/services/printing/print_jobs.py`
- `src/xw_studio/services/printing/planned_pdf_printer.py`
- `src/xw_studio/services/printing/invoice_printer.py`
- `src/xw_studio/services/printing/label_printer.py`
- `src/xw_studio/ui/modules/rechnungen/print_dialog.py`
- `src/xw_studio/ui/modules/rechnungen/plc_label_dialog.py`
- `src/xw_studio/ui/modules/rechnungen/view.py`
- `src/xw_studio/ui/modules/products/view.py`
- `src/xw_studio/services/inventory/service.py`
- `src/xw_studio/services/products/print_decision.py`
- `config/default.yaml` und die druckbezogenen Unit-/UI-Tests
- sieben Noten-/Produkt-PDFs in `docs/` sowie `resources/api_specs/plc/PLC-Test-Label.pdf`
- Legacy-Hinweise und bestehende Umbaupläne im Repository

Relevanter Testlauf am 11. Juli 2026: **34 Tests bestanden** (`test_print_jobs`, `test_planned_pdf_printer`, `test_print_queue`, `test_no_external_pdf_printing`, `test_printing_parity_e2e`, `test_rechnungen_product_print`, `test_plc_label_archive`). Diese Tests bestätigen die programmatische Verdrahtung, aber nicht Layout- oder Druckqualität auf realer Hardware.

## Ist-Architektur

| Anwendungsfall | UI/Service | Backend | Ergebnis |
|---|---|---|---|
| Rechnung | Rechnungen/`InvoicePrinter` | PyMuPDF-Rasterbild → `QPainter` → `QPrinter` | laut Praxis gut; A4 wird explizit gesetzt |
| Adresslabel | Shipping Panel/`LabelPrinter` | Brother `.lbx` über b-PAC COM | laut Praxis gut; eigener nativer Labelpfad |
| PLC-Label | `PlcLabelPrintDialog` | archiviertes A5-PDF → allgemeiner PyMuPDF/QPrinter-Pfad | A5 wird am Druckjob nicht explizit gesetzt; sporadischer Beschnitt/Versatz plausibel |
| Manueller Notendruck | Rechnungsdialog | allgemeiner PyMuPDF/QPrinter-Pfad | 600-dpi-Bitmap plus automatische Seitenklassifikation |
| Produkt-Druckplan | `print_pdf_by_plan` | je Planzeile ein `PdfPrintJob`, danach allgemeiner Renderer | Planauflösung zentral, Ausführung bitmapbasiert |
| START-Produktdruck | `InventoryService` | `print_pdf_by_plan(..., wait=True)` | gleicher Planresolver, aber kein gemeinsamer UI-Dialog |
| Hauptmenü PRODUKTE | `ProductsView` | kein gleichwertiger manueller Druckdialog | Anforderung derzeit nicht erfüllt |

## Befunde: PLC-Etikett

### PDF und gewünschtes Medium

Das Referenzlabel ist exakt A5: 419,53 × 595,28 pt bzw. 148 × 210 mm, Hochformat. Auch der PLC-Webservice fordert bewusst `paper_layout_id="A5"` an. Das ist korrekt.

### Wahrscheinlichste technische Ursache

`PlcLabelPrintDialog._queue_webservice_label()` erstellt nur einen `PdfPrintJob` mit `job_kind="label"`. Es übergibt weder Seitenformat noch Orientierung, Skalierungsmodus oder explizite Profilparameter. Im Renderer werden Seitenformat und Hochformat ausschließlich für `job_kind="invoice"` auf A4 gesetzt. Für PLC gilt daher:

- `QPrinter` übernimmt die zuletzt im Windows-Queue-/Treiberzustand gespeicherten Einstellungen.
- Standard-Placement ist `paper_origin`; dadurch wird `setFullPage(True)` gesetzt.
- Die Seite wird bei `(0, 0)` **ohne Skalierung und ohne Zentrierung** gezeichnet.
- Nicht bedruckbare Hardware-Ränder werden in diesem Modus nicht kompensiert.
- Bildgröße wird aus der PDF-Größe und der vom Treiber gemeldeten DPI berechnet; Drucker- und Painter-Koordinaten müssen exakt dieselbe effektive DPI verwenden.
- Ist die Queue zeitweise auf A4, „Fit“, eine andere Orientierung oder eine vendor-spezifische Skalierung eingestellt, kann der A5-Inhalt abgeschnitten, verschoben oder nochmals skaliert werden.

Qt weist ausdrücklich darauf hin, dass bei Full-Page-Ausgabe der Ursprung zwar am Papierrand liegt, physisch aber nicht die gesamte Seite bedruckbar sein muss und die Anwendung die Margen selbst berücksichtigen muss. Das passt exakt zum beobachteten Beschnitt ([Qt `QPrinter`](https://doc.qt.io/qtforpython-6/PySide6/QtPrintSupport/QPrinter.html)).

### Weitere Schwachstellen

- Das Profil `plc_label` in `default.yaml` enthält derzeit nur Druckername und Label. A5, Hochformat, Skalierungsregel und Offset sind nicht deklarativ festgelegt.
- Ein Secret `PLC_LABEL_PRINTER` überschreibt das Profil vollständig; damit gehen künftig auch Profilattribute verloren, sofern weiterhin nur ein String aufgelöst wird.
- Die manuelle Funktion `run_plc_label_pdf_print()` zeigt zwar einen Windows-Dialog, überträgt danach aber nur Druckername und Seitenbereich in einen neuen Job. Im Dialog gewählte Kopien, Layout-/Treiberparameter oder Auflösung werden nicht vollständig als Job-Snapshot erhalten.
- `QPrinter.isValid()` und die vom Treiber akzeptierte Seitengröße werden vor dem Druck nicht hart validiert.
- Die vorhandenen Metric-Logs laufen nur auf Debug-Level und werden nicht als strukturierte Diagnose pro Job persistiert.
- Die Queue wertet erfolgreiches `QPainter.end()` als Dispatch-Erfolg; ein Spooler-/Gerätefehler nach Übergabe ist damit nicht sicher erkannt.

### Zielkorrektur PLC

1. `PdfPrintJob` um explizite Layoutsemantik erweitern: `page_size`, `orientation`, `scaling_mode`, `alignment`, optional `margins_mm`.
2. Eigenes Profil `plc_label` verbindlich konfigurieren:
   - A5, Portrait
   - bevorzugt `fit_to_printable_area` mit Seitenverhältnis und Zentrierung; alternativ `actual_size_centered`, falls der Paketmarkendrucker randlos A5 kann
   - keinerlei Treiber-„Fit to page“-Doppelskalierung
   - kalibrierbare X/Y-Offsets nur nach einem Messdruck
3. Vor `painter.begin()` A5 und Orientierung setzen; danach tatsächlich akzeptierte `pageLayout()`-Werte lesen und bei grober Abweichung abbrechen statt falsch zu drucken.
4. Zielrechteck rechnerisch bestimmen:
   - PDF-Seitenverhältnis beibehalten
   - Scale = `min(paint_width/pdf_width, paint_height/pdf_height)`
   - niemals unbeabsichtigt hochskalieren, wenn „Actual size“ gewählt ist
   - mittig in `paintRectPixels()` platzieren
5. PLC-Archivdruck und Erstdruck exakt denselben Job-Builder verwenden.
6. Einen A5-Kalibrierbogen mit 5-mm-Rahmen, Mittelkreuz, Eckmarken und Millimeterskala bereitstellen.
7. Jobdiagnose speichern: PDF-Maß, angefordertes/akzeptiertes Papier, paint/full rect, DPI, Scale, Zielrect, Queue und Treiberversion.

## Befunde: Noten und Printing Products

### Was die Beispiel-PDFs zeigen

Alle untersuchten Produkt-PDFs sind A4. Die Dokumente sind heterogen:

- Cover-/Vorsatzseiten enthalten Rasterbilder, Farbe, Schatten oder Transparenz.
- Notenseiten bestehen überwiegend aus Vektoren, Text/Glyphen und sehr vielen Zeichenoperationen.
- Einzelne Leerseiten sind Bestandteil der Druck-/Duplexplanung.
- Die Dateien stammen aus verschiedenen Generationen (u. a. Finale/Quartz, altes Ghostscript und neu zusammengesetzte PDFs).

Beispiele: `Abendlied` enthält auf Notenseiten über 6.000 Vektorzeichnungen, `Brinpolka` teils über 16.000. Diese Inhalte sind für nativen PDF-/Vektordruck sehr gut geeignet und sollten nicht unnötig in ein einziges Rasterbild umgewandelt werden.

### Warum Schatten und Grafik derzeit leiden

Der aktuelle Pfad rendert jede vollständige Seite über PyMuPDF in `QImage` und zeichnet anschließend nur dieses Bitmap auf den Drucker. Für Musik-/Produktjobs wird zusätzlich bei 72 dpi analysiert:

- erkannte Notation → Graustufen + `adaptive_music`
- „mixed“/„graphic“ → RGB ohne Enhancement

Die Klassifikation hängt von globalen Pixelquoten ab. Kleine farbige Elemente, Schatten, Anti-Aliasing, alte eingebettete Grafiken oder fast leere Cover können dadurch anders behandelt werden als beabsichtigt. Die Graustufenfunktion clippt dunkle Werte und verändert Mitteltöne nichtlinear. Das kann Noten kräftiger machen, zerstört aber feine Schattenverläufe und kann Kantencharakter bzw. Tonwerte verändern.

Weitere Qualitäts-/Komplexitätsnachteile:

- Vektoren, Fonts und Transparenz werden vor dem Windows-Treiber gerastert.
- 600 dpi A4 RGB benötigt ungefähr 100 MB Rohdaten pro Seite; große Jobs erzeugen hohen Speicher-/Spooldruck.
- Die Seitenklassifikation läuft pixelweise in Python auf einer 72-dpi-Probe und erhöht Komplexität und Laufzeit.
- Es existiert kein ICC-/Farbmanagementkonzept und kein klarer Rendering Intent.
- „600 dpi“ ist nicht automatisch identisch mit der nativen Geräteauflösung oder dem besten Canon-Qualitätsmodus.
- Planprofile in `default.yaml` definieren aktuell nicht explizit DPI, Farbe, Placement oder Backend; sie verlassen sich stark auf persistente Windows-Queue-Voreinstellungen.

### Bewertung möglicher Backends

#### A. PDF-XChange Editor CLI – empfohlener Pilot

Die offizielle CLI unterstützt stillen Druck, exakten Druckernamen und Seitenbereiche (`/print`, `showui=no`, `printer=...`, `pages=...`). Damit kann die bestehende Planlogik abgebildet werden, ohne für jeden Job ein sichtbares Fenster zu öffnen. Installation kann ohne Änderung der PDF-Dateizuordnung erfolgen ([CLI-Dokumentation](https://help.pdf-xchange.com/pdfxe10/command-line-options_ed.html), [Deployment ohne Dateizuordnungsänderung](https://help.pdf-xchange.com/sysadmin/making-the-editor-the-default-.html)).

Vorteile:

- ausgereifter PDF-Druckpfad mit hoher Chance auf Acrobat-nahe Vektor-/Transparenzqualität
- stiller Kommandozeilendruck ohne das bekannte Acrobat-Fokusflackern
- Drucker und Seitenbereich pro Planjob steuerbar
- Anwendung bleibt unabhängig: Backend-Prozess wird gekapselt und überwacht

Risiken/zu verifizieren:

- Die CLI-Dokumentation sagt, dass ohne `default=yes` zuletzt verwendete Druckparameter gelten; das muss durch dedizierte Windows-Queues/gespeicherte Profile deterministisch gemacht werden.
- CLI-Rückkehr bedeutet nicht zwingend, dass das physische Blatt erfolgreich ausgegeben wurde.
- Lizenz und zulässiger geschäftlicher Einsatz der konkret verwendeten Funktionen müssen vor Rollout schriftlich geprüft werden. Die Herstellerseite unterscheidet freie und lizenzpflichtige Funktionen ([Produkt/Downloads](https://www.pdf-xchange.com/product/downloads)).
- Exakte Optionen für Skalierung, Duplex, Broschüre und Papierzufuhr müssen in einem Hardware-Pilot mit den vorhandenen Queue-Profilen geprüft werden.

#### B. Acrobat Reader/Acrobat – Referenz und optionaler Fallback

Die bekannte Ausgabequalität ist der Maßstab. Der frühere Shell-/Fensterpfad ist wegen Fokusflackern ungeeignet. Ein erneuter Acrobat-Einsatz wäre nur sinnvoll, wenn ein nachweislich versteckter, serialisierter Prozesspfad stabil funktioniert. Da Adobes Reader-CLI für robuste Automation nur begrenzt dokumentiert/steuerbar ist, sollte er nicht wieder zum Kernbackend werden. Acrobat bleibt aber ideal für Golden-Master-Vergleichsdrucke.

#### C. Ghostscript `mswinpr2` – technischer Fallback, nicht erste Wahl

Ghostscript kann direkt und ohne Druckdialog auf eine benannte Windows-Queue drucken; `-dNoCancel` blendet den Fortschrittsdialog aus. Es nutzt Windows-Druckertreiber, rastert aber für `mswinpr2` auf eine DIB. Die offizielle Dokumentation warnt zudem, dass Papierformat-/Orientierungsanforderungen vom Treiber ignoriert werden können und nennt begrenzte Steuerbarkeit der Auflösung ([Ghostscript Windows printer device](https://ghostscript.readthedocs.io/en/latest/Devices.html)).

Damit löst Ghostscript zwar UI-Flackern und kann gute Rasterqualität liefern, erhält aber nicht den entscheidenden Vektorvorteil. Die Lizenz ist ebenfalls kritisch: AGPL oder kommerzielle Artifex-Lizenz, insbesondere bei Distribution einer proprietären Anwendung ([Ghostscript FAQ/Lizenz](https://ghostscript.com/faq/index.html)).

#### D. Qt PDF / anderer Python-Renderer – keine grundlegende Verbesserung

`QPdfDocument` stellt Laden und `render()` bereit, aber keinen nativen „PDF unverändert an Windows-Drucker“-Pfad ([Qt `QPdfDocument`](https://doc.qt.io/qtforpython-6/PySide6/QtPdf/QPdfDocument.html)). Ein Wechsel von PyMuPDF zu Qt PDF oder PDFium mit anschließendem `QImage` tauscht primär den Rasterizer, nicht das Architekturproblem. Das kann Schattenfehler reduzieren, beseitigt aber weder Rasterisierung noch hohe Speicherlast.

#### E. MuPDF `mutool`

`mutool draw` kann Raster- und einige Vektorformate erzeugen, bietet aber laut offizieller Dokumentation keinen direkten Windows-Printer-Dispatch als gleichwertige, einfache Lösung ([MuPDF `mutool draw`](https://mupdf.readthedocs.io/en/1.25.0/mutool-draw.html)). PyMuPDF nutzt bereits die MuPDF-Renderingbasis; ein Wechsel hierhin verspricht daher wenig Qualitätsgewinn.

#### F. Kommerzielles eingebettetes PDF-SDK

PDF-XChange Core/Editor SDK, Apryse, Foxit SDK oder vergleichbare Engines wären langfristig die sauberste voll integrierte Lösung, falls CLI-Prozesse unerwünscht sind. Vorteile sind programmatische Jobkontrolle, professionelles PDF-Rendering und Support; Nachteile sind Lizenzkosten, Bindung und deutlich größere Integration. Erst evaluieren, wenn der PDF-XChange-CLI-Pilot Qualitäts- oder Automationsanforderungen nicht erfüllt.

### Empfohlenes Zielbild

Ein `PdfPrintBackend`-Interface mit mindestens zwei Implementierungen:

- `NativePdfCliBackend` für `job_kind in {music, product}`
- `QtRasterBackend` für Rechnung und als kontrollierter Fallback

Optional später `GhostscriptBackend` oder ein SDK-Backend. Backendwahl gehört in das Druckprofil, nicht in UI-Code oder Seitenerkennung.

Beispielkonfiguration:

```yaml
printing:
  default_pdf_backend: qt_raster
  print_profiles:
    - id: noten_simplex
      printer_name: "Noten A4 Simplex"
      backend: pdfxchange_cli
      paper_size: A4
      scaling_mode: actual_size
      color_mode: auto
    - id: brochure_mono
      printer_name: "Canon Broschüre Mono"
      backend: pdfxchange_cli
      paper_size: A4
      scaling_mode: actual_size
    - id: plc_label
      printer_name: "Paketmarke A5"
      backend: qt_raster
      paper_size: A5
      orientation: portrait
      scaling_mode: fit_printable
      alignment: center
```

Die bisherigen `render_color_mode`-/`black_enhancement`-Optionen bleiben ausschließlich für das Raster-Fallback. Für Native-PDF-Profile ist keine Cover-/Notenerkennung mehr nötig.

## Druckpläne: Konsistenzanalyse

### Was bereits sauber ist

- `resolve_plan_targets()` ist der zentrale Resolver für Seitenbereiche und Profil-IDs.
- `print_pdf_by_plan()` erzeugt pro Planzeile einen konkreten Job.
- START-Automatik und manueller Rechnungs-Produktdruck verwenden beide diesen Resolver.
- Seitenbereiche unterstützen `Alle Seiten`, einzelne Seiten, Listen und Bereiche einschließlich `START`/`END`.
- Die Queue serialisiert Jobs und räumt temporäre Dateien auf.

### Offene Inkonsistenzen und Risiken

- Der Konfigurationsdialog liegt im Rechnungs-UI-Modul und ist daher kein neutral wiederverwendbarer Produktdialog.
- Das Hauptmenü PRODUKTE bietet denselben manuellen Dialog/Druckweg nicht an.
- Analysis Panel konfiguriert/druckt `PieceBlock`; ProductsView arbeitet mit `ProductRow`. Ein gemeinsames ViewModel fehlt.
- `print_profile_id` wird beim Speichern aus der ersten Planzeile abgeleitet und parallel zum gesamten `print_plan` gespeichert. Zwei Sources of Truth können auseinanderlaufen.
- Planzeilen werden zwar syntaktisch gelesen, aber nicht gegen Überlappungen, Lücken, ungültige Reihenfolge oder ungewollte Mehrfachdrucke validiert.
- Mehrere Planjobs werden separat gequeued. Wenn Job 2 fehlschlägt, ist Job 1 bereits gedruckt; es gibt keinen Plan-/Batchstatus und keinen sicheren Resume-Punkt.
- Im asynchronen manuellen Pfad kehrt `print_pdf_by_plan(wait=False)` nach Queueing zurück. Danach wird Bestand als gedruckt gebucht, obwohl der physische/Backend-Druck noch fehlschlagen kann. Das ist ein fachlicher Fehler.
- Der START-Pfad nutzt `wait=True` und ist diesbezüglich robuster, blockiert aber pro Job bis zum internen Dispatch-Ergebnis.
- Ein `QPrintDialog`-Job verliert Teile der im Dialog gewählten Einstellungen, weil anschließend ein neuer `QPrinter` nur aus Jobfeldern rekonstruiert wird.
- Druckprofile tragen keine stabile Version. Änderungen während eines laufenden Plans sind nicht auditierbar.
- „Erfolgreich“ bedeutet Backend-/Spool-Dispatch, nicht physisch gedruckt; diese Zustände sollten getrennt benannt werden.

## UI-Analyse und gewünschte Erweiterung

### Analysis Panel / Zusammenfassung

Der aktuelle `_PieceDelegate` zeichnet Mengensteuerung, „Druck“ und „Plan“ nur, wenn `flagged=True`. Damit fehlt der gewünschte Druckbutton neben jedem Produkt. Außerdem liegt unter `_on_stuecke_loaded()` noch ein älterer Widget-Aufbau, der wegen eines unmittelbar vorherigen `return` vollständig unerreichbar ist und entfernt werden sollte.

Ziel:

- Für jedes **physische** Printing Product eine Produktzeile mit `−`, Menge, `+`, **Druck** und **Plan**.
- Digitale Produkte: kein Druckbutton bzw. klar deaktiviert mit Erklärung.
- Unbekannte/nicht konfigurierte Produkte: Druckbutton darf den gemeinsamen Konfigurationsdialog öffnen, statt still zu fehlen.
- `flagged` steuert Empfehlung/Defaultauswahl und Warnfarbe, nicht die grundsätzliche Verfügbarkeit des manuellen Drucks.
- Einzel-Druck zeigt vor Ausführung den aufgelösten Plan: PDF, Seiten, Queue, Kopien, Backend, Papier, Duplex-/Broschürenhinweis.
- Nach Queueing Status pro Produkt: „wartet“, „an Backend übergeben“, „fehlgeschlagen“; Bestand erst nach bestätigtem Backend-Erfolg aktualisieren.

### Hauptmenü PRODUKTE

Aktuell gibt es keinen gleichwertigen Produktdruck-Einstieg. Nachzurüsten sind:

- Druckaktion für selektierte Produktzeile(n)
- exakt derselbe gemeinsame Dialog/Controller wie im Analysis Panel
- gleiche PDF-Pfad-/Profil-/Planpflege
- gleiche Vorprüfung, Planvorschau, Backendwahl, Queue und Ergebnisbehandlung
- optional Mehrfachauswahl nur dann, wenn Menge und Plan pro Produkt eindeutig dargestellt werden

Der Dialog darf nicht aus `ui.modules.rechnungen` importiert werden müssen. Vorschlag:

- `ui/dialogs/product_print_dialog.py`
- `services/printing/product_print_controller.py`
- `services/printing/product_print_request.py`

Adapter wandeln `PieceBlock` und `ProductRow` in dasselbe `ProductPrintRequest`-ViewModel um.

## Umsetzungsphasen

### Phase 0 – Messbarer Baseline-Test

- Für drei repräsentative PDFs Golden Samples definieren: reines Notenblatt, Cover mit Schatten, gemischtes/älteres PDF.
- Je PDF identische Seiten mit Acrobat, aktuellem Qt-Rasterpfad und PDF-XChange CLI drucken.
- Mit Lupe/Scan vergleichen: Notenlinien, kleine Glyphen, diagonale Kanten, Schattenverlauf, Vollton, Passer, Seitenposition.
- PLC-A5-Test zehnmal nach wechselnden vorherigen A4-/A5-Jobs ausgeben, um den intermittierenden Treiberzustand reproduzierbar zu machen.
- Windows-Queue-Einstellungen und genaue Druckermodelle/Treiberversionen protokollieren.

### Phase 1 – Jobmodell und Diagnose härten

- `PdfPrintJob` um Backend-, Papier-, Orientierung-, Scale- und Alignmentfelder erweitern.
- Profilauflösung liefert vollständigen unveränderlichen Job-Snapshot.
- `QPrinter.isValid()`, akzeptiertes Layout und Zielrechteck validieren.
- strukturierte `PrintJobDiagnostic`-Logs sowie Batch-/Plan-ID ergänzen.
- Status `queued`, `backend_started`, `backend_dispatched`, `failed` unterscheiden.

### Phase 2 – PLC deterministisch machen

- A5/Portrait explizit setzen.
- `fit_printable` und `actual_size_centered` implementieren.
- PLC-Erst-/Archiv-/manuellen Druck auf denselben Builder umstellen.
- Kalibrierseite und 10× Zustandswechsel-Test ergänzen.
- Erst danach optionale X/Y-Kalibrierung am realen Gerät festlegen.

### Phase 3 – Native-PDF-Backend pilotieren

- PDF-XChange-Pfad erkennen und Version protokollieren.
- Argumentliste ohne Shell erstellen; Dateipfade/Queue-Namen sicher quoten.
- Timeout, Prozess-Exitcode, stdout/stderr und Abbruch behandeln.
- Seitenbereich pro Planzeile abbilden.
- Dedizierte Windows-Queues für Simplex, Duplex und Broschüre beibehalten; deren Treibereinstellungen sind weiterhin maßgeblich.
- Bei fehlendem Backend klarer Preflight-Fehler oder bewusst konfigurierter Qt-Fallback – kein stiller Qualitätswechsel.
- Heuristische Seitenklassifikation für Native-PDF-Jobs vollständig umgehen.

### Phase 4 – Gemeinsamer Produktdruckdialog

- Dialog und Controller aus Rechnungen-Modul herauslösen.
- Planeditor um Backend/Papier/validierte Profilanzeige und Vorschau erweitern.
- Analysis Panel auf gemeinsamen Controller umstellen.
- Hauptmenü PRODUKTE mit identischer Aktion nachrüsten.
- Unerreichbaren Legacy-Widgetcode entfernen.

### Phase 5 – Bestand und Batchsicherheit

- Bestand erst nach erfolgreichem Job-/Planabschluss buchen.
- Plan als Batch behandeln; Teilerfolg anzeigen und gezielten Resume erlauben.
- Idempotency-Key aus Produkt, PDF-Hash, Planversion, Menge und Auslöser bilden.
- UI bei laufendem Job nicht global unnötig sperren; nur kollidierende Produktaktionen blockieren.

### Phase 6 – Rollout

- Feature Flag pro Profil (`qt_raster`/`pdfxchange_cli`).
- Zuerst ein Noten-Simplex-Profil, dann Duplex, zuletzt Broschüre.
- Zwei Wochen Diagnose-/Fehlerdaten sammeln.
- Qt-Rasterfallback erst entfernen, wenn alle Dokumentklassen und Druckpläne freigegeben sind.

## Erforderliche Tests und Abnahmekriterien

### Automatisiert

- Profil → vollständiger Job-Snapshot inklusive Backend und A5/A4.
- PLC-Job erzwingt A5 Portrait unabhängig vom vorherigen Queuezustand.
- Fit-/Center-Berechnung für unterschiedliche Hardwaremargen und DPI.
- Kein Zielrechteck überschreitet `paintRect` bei `fit_printable`.
- Native Produktjobs rufen keine Seitenklassifikation/Graustufenverstärkung auf.
- Planbereiche werden korrekt und ohne ungewollte Doppelungen aufgelöst.
- Plan-Teilfehler aktualisiert Bestand nicht als Gesamterfolg.
- Analysis-Delegate bietet Druck für jedes physische Produkt, unabhängig von `flagged`.
- Digitale Produkte bleiben nicht druckbar.
- ProductsView und Analysis Panel erzeugen für dasselbe Produkt identische Requests/Jobs.
- Fehlendes externes Backend erzeugt sichtbaren Preflight-Fehler.
- Pfade mit Leerzeichen/Umlauten und Druckernamen mit Sonderzeichen.

### Hardware-Abnahme PLC

- zehn aufeinanderfolgende A5-Labels identische Position ±0,5 mm
- je fünf A5-Labels nach zuvor gedrucktem A4-Rechnungs- und Notenjob
- kein Barcode/QR-Code oder Rand abgeschnitten
- Barcode-Scanquote 100 %
- kein zusätzlicher „Fit“-Effekt im Treiber

### Hardware-Abnahme Noten

Status 2026-07-29: QA-01 bis QA-04 gedruckt und durch Nutzer auf Papier geprueft. Simplex/Duplex funktionieren; Schaerfe und Zentrierung sind absolut ok.

- kleine Notenköpfe, Linien und Fonts mindestens gleichwertig mit Acrobat-Referenz
- Cover-Schatten ohne harte Stufen, Clipping oder ungewollte Graukonvertierung
- leere Duplex-/Trennseiten bleiben exakt erhalten
- Simplex-, Duplex-, Broschüre-Mono- und Broschüre-Duo-Pläne korrekt
- kein sichtbares Fenster, Fokusraub oder Bildschirmflackern
- Jobs mit 20+ Seiten ohne übermäßigen RAM-/Spooleranstieg

## Priorisierung

1. **P0:** PLC-A5-Layout explizit und zentriert; Diagnosewerte persistieren.
2. **P0:** Bestandsbuchung erst nach tatsächlichem Backend-Ergebnis.
3. **P1:** PDF-XChange-CLI-A/B-Pilot mit den drei Golden Samples.
4. **P1:** gemeinsamer Produktdruck-Controller/Dialog und Druckbutton bei jedem physischen Analysis-Produkt.
5. **P1:** gleicher Dialog im Hauptmenü PRODUKTE.
6. **P2:** Batch-/Resume-/Idempotency-Härtung und Entfernung des unerreichbaren UI-Codes.
7. **P2:** kommerzielles SDK nur evaluieren, falls CLI-Pilot nicht genügt.

## Offene Fragen vor der Umsetzung

1. Welches exakte Druckermodell und welcher Treiber stehen hinter **„Paketmarke A5“**? Ist A5 tatsächlich eingelegt und randlos bedruckbar, oder müssen Hardware-Ränder berücksichtigt werden?
2. Tritt der PLC-Fehler eher nach einem vorherigen A4-Job, nach einem Neustart oder nur bei bestimmten PLC-Labels auf? Ein fehlerhaftes und ein korrekt gedrucktes Blatt/Foto plus zugehöriger Log wäre sehr wertvoll.
3. Welche exakten Canon-Modelle/Treiber stehen hinter den vier Notenqueues? Werden Broschüre/Duplex ausschließlich über gespeicherte Windows-Queue-Voreinstellungen gesteuert?
4. Darf auf allen Druckstationen ein zusätzlicher PDF-Viewer wie PDF-XChange Editor installiert und für geschäftlichen Einsatz lizenziert werden?
5. Soll der Druckbutton im Analysis Panel wirklich bei **jedem physischen Produkt** erscheinen, auch wenn es nicht als „muss gedruckt werden“ markiert ist? Dieser Plan nimmt das an.
6. Soll ein Klick sofort drucken oder zunächst immer eine kompakte Planvorschau/Bestätigung zeigen? Für manuelle Einzeldrucke empfiehlt dieser Plan die Vorschau, für START-Automatik weiterhin stillen Druck nach Preflight.
7. Sollen Bestände auch bei manuellen Drucken aus dem Hauptmenü PRODUKTE erhöht werden? Falls ja, muss die fachliche Bedeutung (Produktion vs. bloßer Test-/Ersatzdruck) im Dialog auswählbar sein.

## Nicht empfohlen

- bloßes Erhöhen von 600 auf 1200 dpi: vervierfacht ungefähr Pixel-/Speicherlast und behebt weder Vektorverlust noch Klassifikationsfehler.
- weitere Verfeinerung der Cover-/Noten-Heuristik als Hauptstrategie: sie bleibt dokumentabhängig und unnötig, sobald native PDF-Ausgabe verfügbar ist.
- direktes Raw-Spooling der PDF-Datei ohne bestätigte PDF-Unterstützung des konkreten Druckers/Windows-Treibers.
- erneuter Shell-`printto`-Pfad über Dateizuordnungen: nicht deterministisch und anfällig für Fenster/Fokusprobleme.
- stiller automatischer Fallback von Native-PDF zu Rasterdruck: kann unbemerkt Qualitätsunterschiede produzieren.
