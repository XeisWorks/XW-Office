# A5 verdoppeln auf A4 - Migration

Stand: 2026-07-06

## Legacy-Fundstelle

- Repository: `C:\Users\XeisWorks\GitHub\sevDesk`
- Service: `sevdesk_wix_fulfillment\notes_layout\a5_verdoppeln_auf_a4.py`
- UI: `sevdesk_wix_fulfillment\ui\notes_layout_panel.py`
- Test: `tests\test_notes_layout_a5_duplication.py`

## Uebernommene Logik

- Jede Quellseite wird auf ein neues A4-Blatt gesetzt.
- Die Seite wird zweimal platziert: obere A4-Haelfte und untere A4-Haelfte.
- Die Zielflaechen entsprechen je einer querliegenden A5-Flaeche.
- Rotationsmetadaten einzelner Quellseiten werden in einer Arbeitskopie entfernt, damit gemischte PDFs lesbar bleiben.
- Ausgabe folgt weiter dem etablierten Suffix `_A4-2x.pdf`.

## Verbesserungen in XW-Office

- Der Ablauf ist jetzt im zentralen `LayoutToolsService` gekapselt.
- Die UI liegt unter `MEDIEN > LAYOUT` als erstes Register vor `QR-Code`.
- Das Ausgabeziel ist explizit sichtbar und kann vor dem Start geaendert werden.
- Ein optionaler Sicherheitsrand je A5-Haelfte ist einstellbar.
- Die Service-Methode verhindert standardmaessig versehentliches Ueberschreiben.
- Die UI ueberschreibt nur das bewusst gewaehlte Ausgabeziel.
- Fokussierte Unit-Tests pruefen Rotation, A4-Ausgabeformat und Overwrite-Schutz.

## Recherche-Notizen

- PyMuPDF dokumentiert `Page.show_pdf_page()` fuer N-up-Platzierungen in Zielrechtecken.
- Die PyMuPDF-Basics zeigen fuer 4-up-Ausgabe denselben Ansatz: Quellseiten in berechnete Rechtecke kopieren und danach mit `garbage=3, deflate=True` speichern.
- Die Document-Doku empfiehlt fuer verlustfreie Dateigroessenreduktion `garbage=3|4`, `deflate=True` und optional `use_objstms`.
- `Document.save()` fragt beim Ueberschreiben nicht nach; der Schutz muss daher in der Anwendung passieren.
