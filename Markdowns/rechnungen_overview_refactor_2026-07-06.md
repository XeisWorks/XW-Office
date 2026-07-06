# RECHNUNGEN Overview-Refactor - 2026-07-06

## Anlass

Die Box `OFFENE RECHNUNGEN` zeigte vor dem vollstaendigen Wix-Laden falsche
Werte fuer physische Rechnungen, digital-only Rechnungen und Kaeufernotizen.
Ausserdem lag die komplette Klassifikationslogik direkt in `RechnungenView`,
obwohl sie fachlich kein Widget-Code ist.

## Umgesetzter Umbau

- Neue Hilfslogik in `ui/modules/rechnungen/open_invoice_overview.py`.
- `RechnungenView` berechnet nur noch den sofort sichtbaren Snapshot und startet
  bei fehlender Wix-Klassifikation einen Worker.
- Wix-Kaeufernotizen aus `resolve_invoice_list_hints()` zaehlen jetzt in
  `Mit Kaeufernotiz`.
- PLC-Hinweise werden konsistent aus sevDesk- und Wix-Notiztexten erkannt.
- Bereits bekannte physisch/digital-Klassifikationen werden aus dem UI-Cache
  wiederverwendet und nicht erneut ueber Wix abgefragt.
- Der persistente Wix-Order-Cache wird fuer die sofortige Summary genutzt:
  digital-only Klassifikation, Kaeufernotizen und Line-Items koennen ohne
  Netzaufruf erscheinen.
- Unter der Open-Invoice-Summary gibt es jetzt eine rechnungsuebergreifende
  Printprodukt-Liste mit Produkttitel, Beschreibung und Gesamtstueckzahl.
- Der Overview-Worker verarbeitet offene Wix-Refs parallel und startet einen
  vorgemerkten neuen Durchlauf, falls waehrenddessen die Rechnungsliste wechselt.
- Zeilenauswahl in der Tabelle oeffnet das Detailpanel sofort, ohne doppelte
  Detail-Hydration bei normalem Selektionswechsel.

## Zielbild

`RechnungenView` sollte mittelfristig nur noch UI-Zustand und Signalverdrahtung
halten. Fachliche Ableitungen sollen in kleine, testbare Helfer oder Services:

- Open-Invoice-Overview: erledigt.
- Wix-Detailkontext fuer Kunden-, Versand- und Produktdaten: naechster Kandidat.
- Fulfillment-Aktionsstatus und Tabellenpatches: naechster Kandidat.
- START-Preflight und Summary-Anzeige: mittelfristig eigener Controller.

## Noch sinnvoller Folgeschritt

Den bestehenden Wix-Kontextfluss vereinheitlichen:

1. Ein Resolver liefert pro Wix-Referenz Meta, Line-Items, HintFlags und
   digital-only Status.
2. Detailpanel, Tabellen-Hinweise, Open-Overview und START-Preflight nutzen
   denselben Resolver.
3. Der Resolver prueft zuerst Session-Cache, dann persistenten Wix-Cache, dann
   erst Wix API.
4. Die View bekommt nur noch fertige, flache ViewModels.

Das reduziert doppelte API-Pfade und macht die Performance bei groesseren
Rechnungslisten berechenbarer.
