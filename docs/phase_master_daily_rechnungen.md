# XW-Office Masterplan Daily-Business + Rechnungen

Stand: 2026-04-03
Statusquelle: Diese Datei ist die verbindliche Source of Truth fuer den Umbau- und Rollout-Status.

## Zielbild
- Altes Daily-Business ist funktional im neuen Rechnungen-Hub enthalten.
- Dringlichkeit wird konsistent als rot markiert (nie nur Farbe: immer Symbol + Tooltip/Text).
- Hinweise aus altem Daily-Business sind sichtbar: Buyer-Note, abweichende Lieferanschrift, heikles Land.
- Queue-Bereiche (Mollie, Gutscheine, Downloads, Refunds) zeigen offene Punkte sofort sichtbar.

## Umsetzungsphasen

### Phase 1 - Phase-Quelle vereinheitlichen
Status: DONE (2026-04-03)
- Eine verbindliche Masterdatei festgelegt.
- Historische Checklisten bleiben als Referenz erhalten.

### Phase 2 - Hinweisfelder im Rechnungen-Grid erweitern
Status: DONE (2026-04-03)
- Zusatsspalten eingefuehrt: Lieferabw., Heikles Land.
- Buyer-Note bleibt als Marker in Notiz-Spalte sichtbar.
- Mouseover auf Marker zeigt konkrete Buyer-Note.

### Phase 3 - Rot = Dringlichkeit (symbolisch + textlich)
Status: DONE (2026-04-03)
- Rechnungen: rote Marker fuer Notiz/Lieferabweichung/heikles Land.
- Daily-Business Queues: Mark.-Spalte mit rotem Marker bei offenen/pending/fehlenden Punkten.
- Tabs: roter Punkt vor Queue-Tabnamen bei offenen Eintraegen.

### Phase 4 - Alte Daily-Business Signale in neuen Hub uebernehmen
Status: DONE (2026-04-03, baseline)
- Rechnungen, Mollie, Gutscheine, Downloads, Refunds sind im Tab-Hub aktiv.
- Badge-Counter laufen ueber DailyBusinessService.

### Phase 5 - Qualitaetssicherung
Status: DONE (2026-04-03)
- Unit-Tests fuer Invoice-Parsing auf neue Felder erweitert.
- Bestehende Unit-Test-Suite geprueft.

## Offene Punkte (naechste Iteration)
- Feinjustierung der Kanal-Schluesselwoerter nach Realdaten aus Produktion (Live-Importer aktiv).
- Optional: zusaetzliche Symbolstufe fuer "Warnung" (nicht-dringend) einfuehren.
