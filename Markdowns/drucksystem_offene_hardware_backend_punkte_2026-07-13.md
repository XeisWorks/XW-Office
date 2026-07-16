# Offene Drucksystem-Punkte fuer Umsetzung auf einem zweiten PC

Stand: 13. Juli 2026

Ausgangslage: Der Code-Stand `11a41ad Improve product and PLC print handling` hat die lokalen Softwarephasen bereits umgesetzt:

- PLC-Jobs enthalten explizit A5 Portrait, `printable_origin`, `fit`, `center`.
- Druckprofile, Queue, Planresolver und Renderer kennen `page_size`, `orientation`, `scale_mode` und `alignment`.
- Analysis Panel und Menue Produkte nutzen denselben Produktdruckpfad.
- Analysis-Produktdruck wartet auf Queue-Bestaetigung, bevor Bestand/sevDesk aktualisiert wird.

## Umsetzungsstand 16. Juli 2026

Die in den Abschnitten 3 und 4 beschriebenen Software-Umbauten sind umgesetzt:

- `PdfPrintBackend` trennt die Druckqueue vom konkreten PDF-Renderer.
- `QtRasterBackend` bleibt der sichere Standard fuer Rechnung, PLC und alle nicht umgestellten Profile.
- `NativePdfCliBackend` unterstuetzt PDF-XChange Editor pro Druckprofil mit Seitenauswahl,
  mehreren Kopien, Silent-Aufruf und klarer Fehlerweitergabe.
- Bei einem Fehler des nativen Backends gibt es bewusst keinen stillen Qt-Raster-Fallback.
- PDF-XChange wird erst aktiviert, wenn ein Profil `backend: "pdf_xchange"` und einen
  existierenden `native_pdf_exe` enthaelt. Auf dem Entwicklungs-PC ist PDF-XChange derzeit
  nicht installiert; `config/default.yaml` enthaelt daher nur ein auskommentiertes Beispiel.
- Die Hersteller-Syntax wurde gegen die
  [PDF-XChange Editor CLI-Dokumentation](https://help.pdf-xchange.com/pdfxe10/command-line-options_ed.html)
  geprueft. Verwendet wird `/print:default=yes;showui=no;printer="..."`.
- Im Menue **Produkte** bleibt `Auswahl drucken` ein reiner Druck. Die separate Aktion
  `Drucken + Bestand` setzt die empfohlene Variante 3 um: Sie wartet auf die Queue-Bestaetigung
  und erhoeht danach zuerst den sevDesk-Bestand und anschliessend den lokalen Bestandssnapshot.
  Druckfehler veraendern keinen Bestand; Bestandsfehler werden getrennt gemeldet.

Automatisch geprueft wurden Backend-Auswahl, PDF-XChange-Prozessargumente, Seitensyntax,
Mehrfachkopien, fehlende EXE, Fehler-Exitcodes, fehlender Raster-Fallback sowie die lokale
Bestandssynchronisierung. Offen bleiben ausschliesslich die physischen Tests aus Abschnitt 2
und der Golden-Sample-Vergleich aus Abschnitt 3.

Diese Datei beschreibt nur die Punkte, die auf dem Ziel-PC mit echten Druckern, installierten PDF-Viewern und realen Druckertreibern abgeschlossen werden muessen.

## 1. Ziel-PC vorbereiten

### Repository und Branch

1. Repository auf dem Ziel-PC aktualisieren:

   ```powershell
   git fetch origin
   git checkout agent/performance-responsiveness-final
   git pull --ff-only
   ```

2. Sicherstellen, dass mindestens Commit `11a41ad` enthalten ist:

   ```powershell
   git log --oneline -5
   ```

3. Lokale Abhaengigkeiten wie gewohnt installieren/aktualisieren:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Kurzer Smoke-Test ohne Hardwaredruck:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/unit/test_print_jobs.py tests/unit/test_planned_pdf_printer.py tests/unit/test_print_queue.py tests/unit/test_rechnungen_product_print.py tests/unit/test_plc_label_archive.py -q
   ```

### Erwartete Windows-Druckerqueues

Die Namen muessen exakt zu `config/default.yaml` passen oder dort fuer den Ziel-PC angepasst werden:

- `Rechnungen`
- `Noten A4 Simplex`
- `Noten A4 Duplex`
- `Canon Broschuere Mono`
- `Canon Broschuere Duo`
- `Brother QL-800`
- `Paketmarke A5`

Wichtig fuer PLC:

- Der Queue-Name `Paketmarke A5` muss auf den echten A5/Paketmarken-Drucker zeigen.
- In den Windows-Druckereinstellungen sollte A5 als Standardpapier hinterlegt sein.
- Borderless/Randlos darf nur verwendet werden, wenn der Treiber das sauber unterstuetzt. Sonst lieber normaler bedruckbarer Bereich; der Code passt das PDF jetzt in `paintRect` ein.

## 2. PLC-Hardwareabnahme

### Ziel

Pruefen, ob der intermittierende Versatz/Beschnitt durch die neuen expliziten A5-/Fit-/Center-Daten behoben ist.

### Testmaterial

Geeignet sind:

- ein echtes archiviertes PLC-Label aus `state/plc_labels/`
- alternativ `resources/api_specs/plc/PLC-Test-Label.pdf`

### Testablauf

1. XW-Studio starten.
2. Zuerst einen normalen A4-Druckjob ausloesen, zum Beispiel Rechnung oder beliebiges A4-PDF.
3. Direkt danach ein PLC-Label drucken.
4. Danach erneut einen anderen A4-Druckjob ausloesen.
5. Wieder ein PLC-Label drucken.
6. Diesen Wechsel mindestens zehnmal wiederholen:

   ```text
   A4 -> PLC -> A4 -> PLC -> A4 -> PLC ...
   ```

7. Jeden PLC-Ausdruck kurz bewerten:

   ```text
   Lauf | vorheriger Job | Ergebnis | Bemerkung
   1    | A4 Rechnung    | OK/Fehler | ...
   2    | A4 Noten       | OK/Fehler | ...
   ```

### Akzeptanzkriterien

Der PLC-Pfad gilt als abgenommen, wenn:

- alle zehn Labels vollstaendig sichtbar sind;
- keine Barcode-/Textbereiche abgeschnitten sind;
- der Inhalt auf A5 optisch mittig und gleich skaliert bleibt;
- ein vorheriger A4-Job keinen Einfluss mehr auf das Label-Layout hat.

### Wenn PLC weiterhin verschoben oder abgeschnitten ist

Dann zuerst die Treiberdaten pruefen:

- Ist `Paketmarke A5` wirklich der richtige Queue-Name?
- Steht der Windows-Queue auf A5 Portrait?
- Hat der Treiber eine Option wie "An Seite anpassen", "Skalierung", "Randlos", "Druckbereich maximieren"? Diese Optionen testweise neutralisieren.
- Gibt es einen physischen nicht bedruckbaren Rand, der groesser als erwartet ist?

Danach mit kleinen Profilkorrekturen arbeiten, nicht im Code:

```yaml
printing:
  print_profiles:
    - id: "plc_label"
      printer_name: "Paketmarke A5"
      page_size: "A5"
      orientation: "portrait"
      placement_mode: "printable_origin"
      scale_mode: "fit"
      alignment: "center"
      x_offset_mm: 0.0
      y_offset_mm: 0.0
```

Nur wenn konstant derselbe Versatz sichtbar ist:

- `x_offset_mm` in 0.5-mm-Schritten korrigieren.
- `y_offset_mm` in 0.5-mm-Schritten korrigieren.
- Nach jeder Aenderung wieder mindestens drei Drucke nach vorherigem A4-Job testen.

## 3. Hochqualitativer Noten-/Produktdruck: Backend-Pilot

### Ziel

Vergleichen, ob ein nativer PDF-Druckpfad die Schatten, Cover und Vektornotation sichtbar besser druckt als der interne PyMuPDF/QPrinter-Rasterpfad.

### Warum dieser Punkt offen ist

Der aktuelle interne Pfad rastert jede PDF-Seite. Das ist robust und automatisierbar, aber fuer hochwertige Produkt-PDFs nicht ideal:

- Vektornotation wird zu Bitmap.
- Cover/Grafiken mit Schatten koennen flacher oder haerter wirken.
- Die automatische Seitenklassifikation kann nie so gut sein wie ein nativer PDF-Renderer mit Druckertreiberintegration.

### Empfohlener Pilot: PDF-XChange Editor CLI

Auf dem Ziel-PC installieren:

- PDF-XChange Editor
- geschäftlich passende Lizenz klaeren, falls der Pilot produktiv genutzt wird

Zu pruefen:

- Pfad zur EXE, typischerweise etwa:

  ```text
  C:\Program Files\Tracker Software\PDF Editor\PDFXEdit.exe
  ```

- CLI-Druck mit einem Test-PDF:

  ```powershell
  & "C:\Program Files\Tracker Software\PDF Editor\PDFXEdit.exe" /print:printer="Noten A4 Simplex" "C:\Pfad\zur\Testdatei.pdf"
  ```

Die genaue Syntax bitte am Ziel-PC mit der installierten Version validieren, weil Viewer-Versionen CLI-Details aendern koennen.

### Golden-Sample-Test

Aus `docs/` drei PDF-Typen auswaehlen:

- ein reines Noten-/Notation-PDF
- ein Cover/Grafik-PDF mit Schatten
- ein gemischtes Produkt-PDF mit Cover plus Notenseiten

Fuer jedes PDF drei Ausdrucke erzeugen:

1. aktueller XW-Studio interner Druckpfad
2. PDF-XChange CLI
3. falls installiert: Acrobat als Referenz

Bewertung je Sample:

```text
PDF | Pfad | Notenlinien | Textschaerfe | Schatten/Cover | Graustufen | Duplex/Broschuere | Gesamt
... | intern | 1-5 | 1-5 | 1-5 | 1-5 | OK/Fehler | ...
... | PDF-XChange | 1-5 | 1-5 | 1-5 | 1-5 | OK/Fehler | ...
... | Acrobat | 1-5 | 1-5 | 1-5 | 1-5 | OK/Fehler | ...
```

Akzeptanz fuer PDF-XChange:

- Notenlinien mindestens so scharf wie Acrobat oder deutlich besser als intern.
- Schatten/Cover sichtbar sauberer als intern.
- Kein Bildschirmflackern wie beim alten Acrobat-Pfad.
- Silent/automatisierter Druck ohne stoerende Dialoge.
- Druckerprofile wie Simplex/Duplex/Broschuere bleiben stabil.

### Wenn PDF-XChange gut ist

Dann naechste Implementierungsphase:

- `PdfPrintBackend`-Interface einfuehren.
- `QtRasterBackend` als bestehenden Default behalten.
- `NativePdfCliBackend` fuer Produkt-/Notendruck ergaenzen.
- Backend pro PrintProfile konfigurierbar machen, z.B.:

  ```yaml
  print_profiles:
    - id: "noten_simplex"
      printer_name: "Noten A4 Simplex"
      backend: "pdf_xchange"
      native_pdf_exe: "C:/Program Files/Tracker Software/PDF Editor/PDFXEdit.exe"
  ```

- Fallback-Regel definieren:
  - Produktdruck soll bei Native-Backend-Fehler nicht still auf schlechtere Rasterqualitaet fallen, sondern klar melden.
  - Rechnungsdruck bleibt intern, weil er aktuell gut funktioniert.
  - PLC bleibt intern A5-fit, solange Hardwareabnahme gut ist.

### Wenn PDF-XChange nicht gut genug ist

Weitere Optionen:

- Acrobat nur als optionaler Referenz-/Fallback-Pfad, falls Flackern loesbar ist.
- Kommerzielles PDF-SDK pruefen, wenn CLI-Prozesse nicht stabil genug sind.
- Ghostscript nur als technischer Fallback; wegen Rasterpfad, Treiberlimitationen und Lizenzthemen nicht erste Wahl.

## 4. Produktdruck im Menue Produkte: Lagerbestand-Entscheidung

### Aktueller Stand

Die neue Aktion `Auswahl drucken` im Menue **Produkte** startet bewusst nur den Druck. Sie erhoeht den Lagerbestand nicht automatisch.

Grund: Im Produkte-Menue fehlt der Rechnungs-/Produktionskontext. Ein Klick kann ein Testdruck, Nachdruck, Muster oder echte Lagerproduktion sein.

### Zu klaerende Fachentscheidung

Es gibt drei sinnvolle Varianten:

1. **Nur drucken, Bestand nicht anfassen**  
   Sicherster aktueller Zustand. Kein Risiko, versehentlich Lager zu erhoehen.

2. **Dialog mit Modusauswahl**  
   Vor dem Druck:

   ```text
   [ ] Bestand nach erfolgreichem Druck erhoehen
   Anzahl: ...
   Grund: Produktion / Testdruck / Nachdruck / Muster
   ```

   Bestand wird nur bei aktivem Haken nach bestaetigtem Druck erhoeht.

3. **Separater Produktionsbutton**  
   `Auswahl drucken` bleibt reiner Druck. Ein zweiter Button `Produktion buchen` oder `Drucken + Bestand` macht die Lagerbuchung explizit.

Empfehlung: Variante 3, weil sie Fehlklicks reduziert und fachlich klarer ist.

### Umsetzung, falls Lagerbuchung gewuenscht ist

Technisch sollte die Lagererhoehung erst nach bestaetigtem Druck erfolgen:

- Produktdruck mit `wait=True` starten.
- Danach `sevDesk`-/Inventarbestand um die produzierte Menge erhoehen.
- Fehlerfall: keine Bestandsaenderung.
- UI-Meldung muss unterscheiden:
  - Druck erfolgreich, Bestand gebucht.
  - Druck erfolgreich, Bestand nicht gebucht.
  - Druck fehlgeschlagen, Bestand nicht gebucht.

## 5. Abschlusskriterien fuer den zweiten PC

Die offenen Punkte gelten als abgeschlossen, wenn:

- PLC-A5 nach wechselnden A4-Jobs mindestens zehnmal stabil korrekt druckt.
- Fuer Produkt-/Notendruck ein Backend-Vergleich mit mindestens drei Golden Samples dokumentiert ist.
- Eine Entscheidung vorliegt, ob PDF-XChange/Acrobat/native SDK eingebaut wird.
- Eine Entscheidung vorliegt, ob Produktdruck im Menue Produkte Lagerbestand buchen darf.
- Alle finalen Entscheidungen in dieser MD oder einer Folge-MD dokumentiert sind.

