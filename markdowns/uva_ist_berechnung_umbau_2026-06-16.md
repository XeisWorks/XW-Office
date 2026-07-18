# UVA-IST-Berechnung: Recherche, Legacy-Analyse und Umbau

Stand: 2026-06-16

## Ziel

Die monatliche Umsatzsteuerberechnung in XW-Studio soll eine einzige, nachvollziehbare
IST-Berechnung verwenden. Die Legacy-Trennung zwischen ausfuehrlicher Eigenberechnung
und alternativer sevDesk-Aggregator-Berechnung wird nicht uebernommen.

Die Berechnung bleibt bis zur separaten FinanzOnline-Umsetzung read-only gegen sevDesk.
Die spaetere FinanzOnline-Anbindung soll exakt dieselben Kennzahlen verwenden.

## Recherche-Fazit

- Bei IST-Besteuerung zaehlt fuer Ausgangsumsatzsteuer der Monat, in dem das Entgelt
  vereinnahmt wurde.
- Vorsteuer aus Eingangsrechnungen wird im IST-Setup erst bei Bezahlung beruecksichtigt.
- Die UVA stellt Umsatzsteuer und abziehbare Vorsteuer gegenueber.
- FinanzOnline erwartet fuer die Datenstromuebermittlung XML gemaess veroeffentlichten
  Strukturen; fuer UVA sind Versionen ab 01/2022 und ab 07/2026 veroeffentlicht.
- Die saubere technische Quelle in sevDesk sind Dokumente plus Zahlungsnachweise:
  `Invoice`, `CreditNote`, `Voucher`, Positionsendpunkte und verknuepfte
  `CheckAccountTransaction`-Logs.

Quellen:

- USP/BMF: Umsatzsteuervoranmeldung, Selbstberechnung und Gegenueberstellung von
  Umsatzsteuer und Vorsteuer.
- WKO: IST-Besteuerung nach vereinnahmten Entgelten und Vorsteuerabzug bei Bezahlung.
- BMF FinanzOnline: Datenstromuebermittlung und UVA-XML-Strukturen.
- sevDesk API: Dokument-, Positions-, Zahlungs- und Steuerdaten ueber REST-Endpunkte.

## Legacy-Analyse

Relevante Legacy-Dateien:

- `C:\Users\bernh\GitHub\sevDesk\UVA.py`
- `C:\Users\bernh\GitHub\sevDesk\finanzonline_uva.py`

Uebernommen werden nur belastbare Konzepte:

- Monatsperiode mit lokalem Zeitraum `[Monatsanfang, Folgemonat)`.
- Selektion ueber Zahlungsdatum bzw. verlinkte CheckAccountTransaction-Logs.
- Teilzahlungen werden anteilig auf Netto, Steuer und Brutto verteilt.
- Gutschriften werden als negative Ausgangswerte beruecksichtigt.
- OSS/Fremdsteuer wird nicht in die AT-UVA gezogen.
- Reverse-Charge- und innergemeinschaftliche Erwerbe werden mit korrespondierender
  Vorsteuer abgebildet, solange Vollabzug angenommen wird.

Nicht uebernommen:

- zweite Berechnung ueber sevDesk-Aggregator als alternative Wahrheit.
- Legacy-Caches, Konsolenpfade und monolithische Debug-Statistik.
- Status-Fallbacks, die bezahlte Dokumente ohne Zahlungsnachweis im IST-Modus in den
  Monat ziehen.

## Zielarchitektur

Ein Berechnungsweg:

1. sevDesk-Dokumente fuer den Monat und bezahlte Dokumente nach `startPayDate` laden.
2. Detail-/Payment-Logs nachladen, wenn Zahlungsdatum oder Teilzahlungsbetrag nicht
   eindeutig genug ist.
3. Dokumente ohne Zahlungsnachweis im IST-Modus ausschliessen und warnen.
4. Bei Teilzahlungen alle Dokument- und Positionswerte anteilig skalieren.
5. Gruppen je Steuerfall bilden.
6. Eine Kennzahlenstruktur fuer FinanzOnline erzeugen.
7. UI zeigt genau diese Kennzahlen und Hinweise.

## Umbauphasen

### Phase 1: Berechnung vereinheitlichen

- [x] Aggregator nicht als Berechnungsweg verwenden.
- [x] UI/Service-Texte von "Phase 1/2 Preview" auf "IST-Monatsberechnung" umstellen.
- [x] `UvaService.calculate_month()` als klare fachliche Einstiegsstelle anbieten.

### Phase 2: Teilzahlungen korrekt behandeln

- [x] Dokumentkopfsummen anteilig skalieren.
- [x] Positionssummen anteilig skalieren.
- [x] Test fuer teilbezahlte Rechnung mit Positionen ergaenzen.

### Phase 3: FinanzOnline-Anschluss vorbereiten

- [x] `build_submission_payload()` nutzt dieselbe Monatsberechnung.
- [x] Keine separate FinanzOnline-Berechnung einfuehren.
- [x] Kennzahlen bleiben als `KZ000`, `KZ011`, `KZ017`, `KZ021`, `KZ022`,
  `KZ029`, `KZ006`, `KZ057`, `KZ070`, `KZ072`, `KZ060`, `KZ065`, `KZ066`,
  `KZ090` verfuegbar.

### Phase 4: Tests und Live-Read

- [x] Unit-Tests fuer UVA-Berechnung.
- [x] UI-Smoke-Test.
- [x] Live-Lesetest ohne FinanzOnline-Sendung und ohne sevDesk-Schreibzugriff.

## Testprotokoll 16.06.2026

Automatisierte Tests:

```text
.venv\Scripts\python.exe -m pytest tests/unit/test_uva_phase1_preview.py tests/unit/test_uva_soap_mock.py -q
24 passed

.venv\Scripts\python.exe -m pytest tests/unit/test_tax_services.py tests/ui/test_main_window_smoke.py tests/unit/test_uva_phase1_preview.py tests/unit/test_uva_soap_mock.py -q
27 passed

.venv\Scripts\python.exe -m ruff check src/xw_studio/services/finanzonline src/xw_studio/ui/modules/taxes tests/unit/test_uva_phase1_preview.py tests/unit/test_uva_soap_mock.py
All checks passed

.venv\Scripts\python.exe -m mypy src/xw_studio/services/finanzonline --ignore-missing-imports
Success: no issues found
```

Live-Lesetest Mai 2026:

- Dauer: 81 Sekunden
- Berechnungsart: IST
- Zahllast: EUR 965,94
- Ausgangsseite: 131 Dokumente betrachtet, 123 selektiert
- Eingangsseite: 49 Dokumente betrachtet, 31 selektiert
- fehlender Zahlungsnachweis: 0
- Teilzahlungen: 0
- Hinweise: 30
  - Zahlungen ausserhalb Mai wurden ausgeschlossen
  - offene/Entwurfsbelege ohne Periodenzahlung wurden ausgeschlossen
- Schreibzugriffe: keine
- FinanzOnline-Sendung: keine

Kennzahlen Mai 2026:

```text
A000=12750.60
A011=651.24
A017=2347.53
A021=0.00
A022=118.83
A029=3363.40
A006=6269.60
A057=2.24
B070=118.51
B072=118.51
C060=209.22
C065=23.70
C066=2.24
D090=0.00
```

Performance-Befund:

Der sevDesk-Endpunkt `Invoice` mit `startPayDate/endPayDate` lieferte fuer Mai
11.744 Rechnungen statt nur Periodentreffer. Die neue Implementierung filtert solche
ueberbreiten Antworten sofort lokal nach Zahlungsdatum, bevor Positions- und
Payment-Log-Details nachgeladen werden.

## Betriebsregel

Eine UVA darf in XW-Studio nur auf Basis der ausgewiesenen IST-Monatsberechnung
weitergegeben werden. Wenn Warnungen zu fehlendem Zahlungsnachweis, auslaendischer VAT
oder unklassifizierten Positionen erscheinen, ist der Monat vor FinanzOnline-Uebermittlung
fachlich zu pruefen.
