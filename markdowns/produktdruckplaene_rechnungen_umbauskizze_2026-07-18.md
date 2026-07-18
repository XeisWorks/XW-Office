# Produkt-Druckplaene in PRODUKTE und RECHNUNGEN

Stand: 2026-07-18

## Umsetzungsstand 2026-07-18

Erledigt:

- `PRINT-PRODUKTE OFFEN` zeigt echte Produktzeilen mit Print-/Settings-Aktion.
- `PRINT-PRODUKTE OFFEN` filtert auf die bestehende HINWEISE-Print-Flag-Logik.
- Ausgewaehlte Rechnungsprodukte zeigen Druckaktionen nur noch fuer geflaggte Print-Produkte.
- Ausgewaehlte Rechnungsprodukte zeigen jetzt exklusiv entweder `Druck` oder `Plan`.
- Im PRODUKTE-Modul gibt es pro lokalem Produkt eine eigene Spalte `Druck` fuer die Druckplan-Pflege.
- Das alte JSON-Freitextfeld `inventory.print_plans` ist im normalen Produkt-Workflow ausgeblendet.
- Legacy-Profil-IDs werden beim Import auf die aktuellen Profil-IDs gemappt.
- Die Produktdruckprofile `noten_simplex`, `noten_duplex`, `brochure_mono` und `brochure_duo` sind in `config/default.yaml` auf PDF-XChange Native gesetzt.
- Der Druckplan-Dialog zeigt PDF-Status/Seitenzahl, PDF-/Ordner-Buttons, echte Profilnamen, Drucker, Backend und Live-Zusammenfassung.
- Das alte Pilotprofil `noten_native_pilot` wurde entfernt; `Noten A4 Simplex` ist nur noch einmal vorhanden.
- Nach Speichern eines offenen Print-Produkts wird die offene Produktliste neu gerendert, damit Settings direkt zu Print wechseln kann.

Noch als spaetere Haertung offen:

- Ein eigener Resolver-DTO fuer `ready/missing/invalid` wuerde die UI-Entscheidung weiter zentralisieren; aktuell wird die bestehende Produktkatalog-/PieceBlock-Logik wiederverwendet.
- Silent-Print kann weiterhin nur Jobannahme, nicht physisch fertig gedrucktes Papier bestaetigen.

## Bestaetigte Entscheidungen

- Die Druckplaene werden zentral am Produkt gepflegt und von dort in allen Rechnungs-Flows verwendet.
- Im Untermenue PRODUKTE bleibt pro Produkt immer eine Wartungsaktion sichtbar, auch wenn bereits ein gueltiger Druckplan existiert.
- Im Untermenue RECHNUNGEN ist der Produkt-Button strikt zustandsabhaengig: gueltiger Plan = Direktdruck, kein/ungueltiger Plan = Zahnrad fuer Einrichtung.
- Titel-spezifische Legacy-Druckplaene bleiben erhalten. Die Aufloesung ist: SKU + konkreter Rechnungs-/Produkt-Titel zuerst, SKU-Default als Fallback.
- PDF-XChange Native wird fuer hochwertige Produktdrucke als Ziel-Backend gesetzt. Rechnungsdruck und PLC-/Label-Druck bleiben getrennt, solange dort kein Qualitaetsproblem besteht.
- Absolute PDF-Pfade unter `C:\Users\...` duerfen erhalten bleiben. Es wird ausschliesslich auf dem aktuellen PC gedruckt; Portabilitaet ueber mehrere PCs ist fuer diese Funktion kein Ziel.
- Nach erfolgreicher Annahme des Druckjobs darf der bestehende Bestand-/sevDesk-Update-Flow weiterlaufen. Bei Druckfehlern darf kein Bestand erhoeht werden.
- Die Print-Flag-Quelle bleibt die bestehende HINWEISE-Logik aus `rechnungen.sku_flags`.

## Ist-Befund PySide6

Relevante Dateien:

- `src/xw_studio/ui/modules/products/view.py`
- `src/xw_studio/ui/modules/rechnungen/view.py`
- `src/xw_studio/ui/modules/rechnungen/print_dialog.py`
- `src/xw_studio/ui/modules/rechnungen/open_invoice_overview.py`
- `src/xw_studio/services/inventory/service.py`
- `src/xw_studio/services/products/catalog.py`
- `src/xw_studio/services/products/print_decision.py`
- `src/xw_studio/services/printing/planned_pdf_printer.py`
- `src/xw_studio/services/printing/pdf_backends.py`
- `config/default.yaml`

Vorarbeit ist bereits vorhanden:

- `ProductRow` kennt schon `print_file_path`, `print_profile_id`, `print_plan` und `title_print_configs`.
- `InventoryService.save_product_print_config(...)` speichert Default-Konfigurationen und Titel-Overrides.
- `ProductCatalogService.resolve_print_config(sku, title)` kann Titel-spezifische Plaene aufloesen.
- `ProductPrintConfigDialog` existiert bereits als Basisdialog mit PDF-Pfad, Seitenbereichen und Profilauswahl.
- `planned_pdf_printer` kann geplante PDF-Jobs ausfuehren.
- `pdf_backends.py` enthaelt bereits einen PDF-XChange-Backend-Pfad.
- Legacy-Importcode fuer `../sevDesk/data/inventory_store.json` ist vorhanden.

Aktuelle Luecken:

- Im PRODUKTE-Modul gibt es noch keinen klaren Button direkt am zentralen Produkt fuer Druckplan-Wartung.
- Das vorhandene Freitextfeld `inventory.print_plans` ist fachlich getrennt vom echten Produktdruckplan und sollte nicht mehr als Fuehrungssystem verwendet werden.
- In RECHNUNGEN werden Druck-/Plan-Controls derzeit faktisch fuer alle nicht-digitalen Produkte gezeigt; das muss auf die HINWEISE-Print-Flag-Logik eingeschraenkt werden.
- Der Delegate zeigt aktuell Druck und Plan gleichzeitig. Ziel ist ein eindeutiger Toggle: Druck oder Zahnrad.
- `PRINT-PRODUKTE OFFEN` ist aktuell HTML im `QTextBrowser` und kann keine pro Produkt Aktionen tragen.
- Legacy-Profil-IDs werden importiert, aber nicht sauber auf die aktuellen Profil-IDs gemappt.
- Die Produktionsprofile fuer Produktdruck stehen noch nicht durchgaengig auf PDF-XChange Native.

## Legacy-Befund

Wichtige Legacy-Quellen:

- `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\inventory\ui_print_dialog.py`
- `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\ui\print_selection_dialog.py`
- `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\analysis_panel.py`
- `C:\Users\XeisWorks\GitHub\sevDesk\sevdesk_wix_fulfillment\ui\app.py`
- `C:\Users\XeisWorks\GitHub\sevDesk\data\inventory_store.json`

Der Legacy-Dialog hatte fachlich die richtigen Bausteine:

- Kopfbereich mit SKU, Produktname und Menge.
- PDF-Pfadauswahl.
- Abgeleiteter PDF-Titel.
- Druckplan-Tabelle mit Seitenbereich und Profil.
- Hilfe fuer `END`/`ENDE`.
- Live-Zusammenfassung inklusive Profil und Drucker.
- Buttons zum Hinzufuegen und Entfernen von Planzeilen.
- Modusabhaengige Aktionen: Speichern, Drucken, Speichern & Drucken, Abbrechen.
- Validierung auf existierende PDF und Ziel-Drucker.
- Speicherung pro Produkt und pro konkretem Titel.

Legacy-Datenlage aus `inventory_store.json`:

- 504 Produktdatensaetze.
- 164 Datensaetze mit mindestens einem PDF-Pfad.
- 38 Default-PDFs mit Druckplan.
- 31 Produkte mit Titel-spezifischen Konfigurationen.
- 42 Titel-Konfigurationen insgesamt.
- 41 Titel-PDFs mit Druckplan.
- Profilreferenzen: `noten_a4_duplex` 60, `canon_brochure_duo` 15, `canon_brochure_mono` 14, `noten_a4_simplex` 5.

## Zielbild Datenmodell

Das fuehrende Modell bleibt produktzentriert:

```text
ProductRow
  sku
  name
  print_file_path          absoluter PDF-Pfad, optional
  print_plan               Liste aus Seitenbereich + Profil-ID
  print_profile_id         nur noch Legacy-/Fallback-Feld, mittelfristig abloesen
  title_print_configs      Dict[title] -> Pfad + Plan
```

Empfohlene neue interne DTOs:

```text
ProductPrintConfig
  sku
  title optional
  pdf_path
  plan_steps
  source = default | title_override

PrintPlanStep
  page_range
  profile_id
```

Ein gemeinsamer Resolver entscheidet an einer Stelle:

- Gibt es fuer `(sku, title)` einen Titel-Override?
- Falls nein, gibt es einen SKU-Default?
- Existiert die PDF-Datei?
- Ist der Plan nicht leer?
- Sind alle Profil-IDs in `PrintingConfig` vorhanden?
- Ist der PDF-XChange-Pfad fuer Native-Profile verfuegbar?

Ergebnis:

```text
ready      -> Direktdruckbutton
missing    -> Zahnrad
invalid    -> Zahnrad mit Tooltip/Fehlerstatus
```

## Absolute Pfade

Da nur am aktuellen PC gedruckt wird, wird kein Root-Alias-System erzwungen. Der gespeicherte Pfad darf vollstaendig absolut bleiben, z. B.:

```text
C:\Users\XeisWorks\OneDrive - XeisWorks\02 XeisWorks\05 Noten\...
```

Trotzdem sollte der Dialog validieren:

- Datei existiert.
- Datei ist PDF.
- Datei kann geoeffnet werden.
- Seitenzahl kann gelesen werden.
- Plan referenziert keine Seiten ausserhalb des Dokuments.

Optional sinnvoll, aber nicht zwingend fuer Phase 1:

- Anzeige "Datei gefunden" / "Datei fehlt".
- Button "Pfad im Explorer oeffnen".
- Button "PDF oeffnen".
- Warnung bei OneDrive-Platzhalterdatei, falls Windows die Datei noch nicht lokal verfuegbar hat.

## Profil-Mapping Legacy -> PySide6

Beim Import muessen Legacy-Profil-IDs eindeutig uebersetzt werden:

| Legacy-ID | Neue ID |
| --- | --- |
| `noten_a4_simplex` | `noten_simplex` |
| `noten_a4_duplex` | `noten_duplex` |
| `canon_brochure_mono` | `brochure_mono` |
| `canon_brochure_duo` | `brochure_duo` |

Importregeln:

- Import ist idempotent.
- Bestehende manuelle PySide6-Konfigurationen werden nicht still ueberschrieben.
- Fuer Konflikte wird ein Importbericht erzeugt.
- Titel-Overrides bleiben erhalten.
- Absolute Pfade werden unveraendert uebernommen.
- Unbekannte Profil-IDs werden nicht geraten, sondern als invalid markiert.

## PDF-XChange Native

Produktdruckprofile sollen auf Native umgestellt werden:

- `noten_simplex`
- `noten_duplex`
- `brochure_mono`
- `brochure_duo`

`config/default.yaml` sollte fuer diese Profile `backend: pdf_xchange` verwenden. Dabei muss pro Profil weiterhin klar bleiben:

- Ziel-Drucker.
- Simplex/Duplex-Einstellung.
- Farbe/Mono, sofern vom Backend steuerbar.
- Seitenbereich je Planzeile.
- Anzahl Kopien aus Rechnungs-/Uebersichtsmenge.

Wichtiger technischer Punkt: "erfolgreich" bedeutet bei Silent-Print nur, dass PDF-XChange den Job angenommen hat. Ob Papier physisch fertig gedruckt wurde, kann die App nicht sicher wissen. Der Bestand darf deshalb nach erfolgreicher Jobannahme aktualisiert werden, aber Fehler beim Starten/Annehmen des Jobs blockieren den Bestand-Update.

## Neuer Druckplan-Dialog

Der vorhandene `ProductPrintConfigDialog` wird erweitert statt neu erfunden.

Aufbau:

- Kopf: SKU, Produktname, optional Rechnungs-/Stuecktitel.
- Statuszeile: Default-Plan oder Titel-Override.
- PDF-Feld: absoluter Pfad, Datei-waehlen, PDF-oeffnen, Explorer-oeffnen.
- PDF-Status: gefunden/fehlt, Seitenzahl, Dateiname.
- Plan-Tabelle: Reihenfolge, Seitenbereich, Profil, Profil-Drucker, Backend.
- Zeilenaktionen: hinzufuegen, entfernen, optional nach oben/unten.
- Live-Zusammenfassung: "1-2 -> Noten Duplex -> PDF-XChange -> Drucker X".
- Validierung direkt im Dialog.
- Buttons: Speichern, Abbrechen; im Rechnungs-Kontext optional "Speichern & Drucken".

Verbesserungen gegenueber Legacy:

- Profile werden als sprechende Namen angezeigt, gespeichert wird nur die stabile Profil-ID.
- Ungueltige Profile bleiben sichtbar, damit importierte Plaene reparierbar sind.
- Der Dialog zeigt sofort, warum kein Direktdruckbutton sichtbar ist.
- Titel-Overrides koennen bewusst als Titel-Plan gespeichert oder auf SKU-Default zurueckgesetzt werden.

## PRODUKTE-Integration

Im zentralen Produktbereich wird pro Produkt eine Wartungsaktion eingebaut:

- Zahnrad/Button "Druckplan" immer sichtbar.
- Optional zusaetzlicher Print-Testbutton, wenn der Plan gueltig ist.
- Statusindikator: kein Plan, Plan OK, Plan ungueltig, Titel-Overrides vorhanden.

Die Pflege muss gegen `InventoryService.save_product_print_config(...)` laufen, nicht gegen das alte JSON-Freitextfeld. Das Freitextfeld `inventory.print_plans` sollte ausgeblendet oder als veraltet markiert werden, damit es nicht zwei Fuehrungssysteme gibt.

## RECHNUNGEN: Ausgewaehlte Rechnung

In der Produktliste einer ausgewaehlten Rechnung gilt:

- Nur Produkte mit HINWEISE-Print-Flag erhalten Druck-/Plan-Aktion.
- Digitale Produkte bleiben ohne Produktdruckaktion.
- Wenn `resolve_print_config(sku, title)` ready ist: Printbutton.
- Wenn nicht ready: Zahnrad.
- Printbutton fuehrt ohne Rueckfrage exakt den aufgeloesten Plan aus.
- Zahnrad oeffnet den Druckplan-Dialog fuer SKU + Titel-Kontext.
- Nach Speichern wird die Zeile sofort neu bewertet und der Button wechselt auf Print, sofern ready.

Zu beheben:

- `flagged` im Piece-Model darf nicht mehr aus "nicht digital" kommen, sondern aus der HINWEISE-Print-Flag-Logik.
- Der Delegate soll nur einen Aktionsbutton malen.
- Alter nicht erreichbarer Widget-Code im Rechnungen-View sollte entfernt oder klar deaktiviert werden, damit spaetere Aenderungen nicht an der falschen UI landen.

## RECHNUNGEN: PRINT-PRODUKTE OFFEN

Der Bereich unter dem Summary-Feld wird von HTML auf ein aktionsfaehiges Widget umgebaut:

- Nur offene Produkte mit HINWEISE-Print-Flag werden gelistet.
- Aggregation bleibt ueber offene Rechnungen erhalten.
- Pro Zeile: SKU, Titel/Name, offene Menge, Planstatus, Print/Zahnrad.
- Printbutton druckt ohne Rueckfrage die aggregierte offene Menge mit dem zentral aufgeloesten Plan.
- Zahnrad oeffnet denselben Dialog wie oben.

Technisch bietet sich ein `QAbstractTableModel`/Delegate oder eine kompakte `QListWidget`/Row-Widget-Loesung an. Da bereits ein Delegate fuer Rechnungsprodukte existiert, ist ein Model/Delegate langfristig konsistenter.

## Druckausfuehrung

Der Druckjob sollte vor dem Start als unveraenderlicher Snapshot gebaut werden:

- SKU.
- Titel.
- PDF-Pfad.
- Planzeilen mit aufgeloesten Profilen.
- Menge/Kopien.
- Quelle: Rechnung oder offene Uebersicht.

Danach:

- Validierung.
- Queue-Aufnahme.
- PDF-XChange Native Ausfuehrung je Planzeile.
- Fehler sichtbar an UI melden.
- Bestand-/sevDesk-Update nur nach erfolgreicher Jobannahme.

## Tests

Pflichttests:

- Legacy-Profil-Mapping.
- Import erhaelt Titel-Overrides.
- Absolute Pfade bleiben unveraendert.
- Resolver liefert ready/missing/invalid korrekt.
- HINWEISE-Print-Flag filtert exakt die sichtbaren Produktaktionen.
- RECHNUNGEN zeigt Print oder Zahnrad, nie beides.
- Direktdruck oeffnet keinen Dialog.
- Zahnrad-Speichern schaltet die Zeile unmittelbar auf Print.
- Offene Print-Produkte listen nur geflaggte SKUs.
- Fehlerhafter Druckjob aktualisiert keinen Bestand.
- PDF-XChange Backend wird fuer Produktprofile verwendet.

Sinnvolle Smoke-Tests:

- `pytest tests/unit/test_rechnungen_product_print.py`
- `pytest tests/unit/test_planned_pdf_printer.py`
- Neue Tests fuer `ProductPrintConfigResolver`.
- Neuer Test fuer `_ProductAccumulator`/Open-Overview-Filter.

## Umsetzung in Phasen

Phase 1: Daten- und Resolver-Schicht

- Gemeinsamen Resolver fuer Produktdruckplaene einfuehren.
- Legacy-Profil-Mapping in Importpfad ergaenzen.
- Validierung fuer absolute PDF-Pfade und Planzeilen zentralisieren.
- Tests fuer Mapping, Resolver und Import.

Phase 2: Dialog verbessern

- `ProductPrintConfigDialog` um Legacy-Komfortfunktionen erweitern.
- Titel-Override explizit anzeigen und speicherbar machen.
- Live-Zusammenfassung und Profil-/Backend-/Druckeranzeige einbauen.
- Dialog aus PRODUKTE und RECHNUNGEN gemeinsam verwenden.

Phase 3: PRODUKTE anbinden

- Pro Produkt Druckplan-Wartungsbutton einbauen.
- Statusindikator anzeigen.
- Veraltetes JSON-Freitextfeld aus dem normalen Workflow nehmen.
- Nach Speichern Produktkatalog neu laden oder gezielt aktualisieren.

Phase 4: RECHNUNGEN ausgewaehlte Rechnung

- Print-Flag-Bug beheben.
- Delegate auf exklusiven Print/Zahnrad-Button umbauen.
- Direktdruck auf Resolver-Snapshot umstellen.
- Bestand-/sevDesk-Update nur nach erfolgreicher Jobannahme.

Phase 5: PRINT-PRODUKTE OFFEN

- `QTextBrowser` durch aktionsfaehige Liste ersetzen.
- Aggregation auf HINWEISE-Print-Flag begrenzen.
- Pro Zeile denselben Resolver und dieselben Buttons verwenden.
- Aggregierte Menge ohne Rueckfrage drucken.

Phase 6: PDF-XChange produktiv setzen

- Produktprofile in `config/default.yaml` auf `backend: pdf_xchange` stellen.
- Pilotprofil entfernen oder als Diagnoseprofil belassen.
- Testdruck je Profil durchfuehren.
- Fehlertexte fuer fehlendes PDF-XChange klar anzeigen.

## Akzeptanzkriterien

- Ein Druckplan wird genau einmal am Produkt gepflegt und ueberall verwendet.
- Legacy-Defaultplaene und Titelplaene sind nach Import verfuegbar.
- In PRODUKTE ist die Wartung direkt am Produkt erreichbar.
- In RECHNUNGEN erscheinen Produktdruckaktionen nur fuer HINWEISE-Print-Produkte.
- Bei vorhandener gueltiger Konfiguration druckt der Button ohne Rueckfrage.
- Bei fehlender/ungueltiger Konfiguration erscheint statt Print ein Zahnrad.
- `PRINT-PRODUKTE OFFEN` zeigt nur geflaggte offene Produkte.
- Produktdruck laeuft ueber PDF-XChange Native.
- Absolute Pfade bleiben erhalten.
- Tests decken Resolver, Import, UI-Entscheidung und Druckfehlerpfade ab.

## Offene technische Risiken

- Silent-Print kann physische Fertigstellung nicht bestaetigen, nur Jobannahme.
- PDF-XChange-Kommandozeilenoptionen muessen je Druckerprofil praktisch verifiziert werden.
- OneDrive-Dateien muessen lokal verfuegbar sein, wenn absolute Pfade auf OneDrive zeigen.
- Bestehende Legacy-Daten koennen alte Profilnamen oder nicht mehr existierende PDFs enthalten; diese Plaene muessen reparierbar sichtbar bleiben.
