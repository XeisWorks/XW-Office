# Zahlungsclearing: Analyse, Umbauphasen und Testprotokoll

Stand: 12.06.2026

## Zielbild

Das Legacy-Zahlungsclearing aus `C:\Users\bernh\GitHub\sevDesk\zahlungsabgleich.py`
wird als eigenes PySide6-Modul unter **Finanzen > Zahlungsclearing** umgesetzt.

Der Monatsablauf soll fuer mehr als 100 Zahlungen mit wenigen Aktionen funktionieren:

1. Zeitraum waehlen und Daten analysieren.
2. Eindeutige Treffer sind standardmaessig ausgewaehlt.
3. Mit **Alle auswaehlen** koennen alle buchbaren Zeilen aktiviert werden.
4. Offene oder mehrdeutige Faelle koennen einzeln geprueft und manuell einer Rechnung
   zugeordnet werden.
5. Ein bestaetigter Batch importiert fehlende Provider-Transaktionen idempotent nach
   sevDesk und bucht eindeutige Zahlungen auf Rechnungen.

Live-Schreibtests erfolgen erst nach einer separaten Zustimmung. Live-Lesezugriffe sind
fuer die Abschlusspruefung erlaubt.

## Ist-Analyse Legacy

### Datenquellen

- Stripe Charges, Refunds und Payouts
- Mollie Orders/Payments, Refunds und Settlements
- Wix Orders und Order Transactions als Bruecke zwischen Provider-ID und Bestellnummer
- sevDesk Rechnungen, Online-Konten und CheckAccountTransactions
- SEPA-Zahlungen aus bereits vorhandenen sevDesk-Transaktionen

### Matching

- Primaer: Provider-ID -> Wix Order -> Wix Bestellnummer -> sevDesk Rechnungsreferenz
- Betragstoleranz: 0,01 EUR
- SEPA: Bestell-/Rechnungsreferenz und Betrag innerhalb eines erweiterten Zeitfensters
- Bereits bezahlte Rechnungen und doppelte Referenzen werden ausgeschlossen
- Provider-Transaktionen werden ueber standardisierte Buchungstexte dedupliziert

### Positive Eigenschaften

- Cursor-Paginierung fuer Stripe, Mollie und Wix
- Erkennung bereits importierter Provider-Transaktionen
- Exaktes Referenzmatching vor einer Buchung
- Schutz vor doppelter Rechnungszuordnung
- Unterstuetzung verschiedener sevDesk-Buchhaltungssystemversionen
- Laufprotokolle, Match-Cache und getrennte spaetere Buchung

### Verbesserungsbedarf

- Der rund 1.900 Zeilen grosse Ablauf ist monolithisch und nutzt globale Konfiguration.
- Geldwerte werden ueberwiegend als `float` statt `Decimal` verarbeitet.
- Der bisherige START kann Transaktionen schreiben, obwohl die eigentliche Buchung noch
  nicht bestaetigt wurde.
- Dateibasierte Caches sind nicht fuer mehrere PCs oder parallele Laeufe ausgelegt.
- Fehler sind unstrukturierte Tupel; UI und Fachlogik sind eng gekoppelt.
- Provider-, Wix-, sevDesk- und Matchinglogik lassen sich nur schwer isoliert testen.
- Batch-Buchungen besitzen keine explizite, persistente Zustandsmaschine.
- Refunds und Payouts werden importiert, aber nicht als eigener fachlicher Fall dargestellt.

## Recherche-Ergebnis

Die neue Architektur folgt den offiziellen API-Konzepten:

- Stripe-Listen sind cursor-paginiert (`starting_after`, `has_more`) und Geldwerte werden
  in kleinsten Waehrungseinheiten geliefert.
- Mollie-Listen verwenden HAL-Links (`_links.next`) und Decimal-Strings fuer Betraege.
- Wix trennt Orders von Order Transactions; Zahlungs- und Refunddetails werden ueber die
  Transaction-Endpunkte aufgeloest.
- sevDesk CheckAccountTransactions sind die Zahlungsobjekte, die mit Rechnungen verknuepft
  werden. Schreibzugriffe werden nicht automatisch wiederholt.

Quellen:

- https://docs.stripe.com/api/charges/list
- https://docs.stripe.com/api/refunds/list
- https://docs.stripe.com/api/payouts/list
- https://docs.mollie.com/reference/v2
- https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/orders/orders/search-orders
- https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/orders/order-transactions/introduction
- https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/orders/order-transactions/list-transactions-for-multiple-orders
- https://api.sevdesk.de/

## Zielarchitektur

### Fachmodelle

- `Money`: intern `Decimal`, auf zwei Nachkommastellen normalisiert
- `ProviderTransaction`: Zahlung, Refund oder Payout mit stabiler Provider-ID
- `ClearingCandidate`: normalisierte UI- und Buchungszeile
- `ClearingAnalysis`: unveraenderliches Analyseergebnis mit Kennzahlen und Warnungen
- `BookingResult`: Ergebnis pro Zeile; Fehler in einer Zeile stoppen nicht den ganzen Batch

### Komponenten

- Provider-Gateways fuer Stripe und Mollie
- Wix-Gateway fuer Orders und Order Transactions
- sevDesk-Gateway fuer Rechnungen, Konten, Transaktionen und Buchungen
- `PaymentClearingService` als Orchestrator
- `PaymentClearingView` als eigenes PySide6-Modul

### Sicherheitsregeln

1. Analyse ist strikt read-only.
2. Schreibzugriffe erfolgen nur nach expliziter UI-Bestaetigung.
3. Vor jedem Import wird der Idempotenzschluessel erneut gegen sevDesk geprueft.
4. Vor jeder Rechnungsbuchung werden Rechnungsstatus, Betrag und Transaktionsstatus erneut
   validiert.
5. Mehrdeutige Referenzen, Betragsabweichungen und bereits bezahlte Rechnungen werden nicht
   automatisch gebucht.
6. HTTP-Schreibzugriffe werden nicht automatisch wiederholt.
7. Batch-Ergebnisse werden pro Zeile ausgewiesen.
8. Jeder Analyse- und Buchungslauf wird unter `state/clearing_runs` protokolliert.

## Umbauphasen

### Phase 1: Modelle und API-Gateways

Status: abgeschlossen

- [x] Decimal-basierte Fachmodelle
- [x] Stripe Charges, Refunds und Payouts
- [x] Mollie Payments/Orders, Refunds und Settlements
- [x] Wix Order-Suche und Transaction-Aufloesung
- [x] sevDesk Konten, Rechnungen und CheckAccountTransactions

### Phase 2: Deterministisches Matching

Status: abgeschlossen

- [x] Provider-ID zu Wix Order
- [x] Wix Bestellnummer zu sevDesk Rechnungsreferenz
- [x] Exakter Betragsvergleich
- [x] Erkennung bereits bezahlter und doppelt referenzierter Rechnungen
- [x] SEPA-Matching aus vorhandenen sevDesk-Transaktionen
- [x] Idempotenzschluessel fuer Payment, Refund und Payout
- [x] Duplicate-Key aus Typ, Provider, Provider-Ref, Wertdatum und Betrag

### Phase 3: Bestaetigte Batch-Buchung

Status: abgeschlossen

- [x] Fehlende Stripe-/Mollie-Transaktionen importieren
- [x] Zahlungen mit sevDesk-Rechnungen verknuepfen
- [x] Payouts und Refunds als getrennte Importfaelle behandeln
- [x] Refunds als eigener Pruef-/Importstatus statt generischem Importfall
- [x] Ergebnis und Fehler pro Zeile zurueckgeben
- [x] Keine automatischen Retries fuer Schreiboperationen
- [x] Persistente JSON-Historie fuer Analyse und Buchungsbatch

### Phase 4: PySide6-Modul

Status: abgeschlossen

- [x] Eigener Sidebar-Eintrag unter Finanzen
- [x] Zeitraum-Presets und freie Datumswahl
- [x] Ergebnistabelle mit Checkboxen
- [x] Alle buchbaren Zeilen auswaehlen/abwahlen
- [x] Standardauswahl fuer eindeutige Treffer
- [x] Detailansicht und Filter
- [x] Manuelle Rechnungsnummer fuer offene Faelle
- [x] Sicherheitsbestaetigung vor dem Batch
- [x] Fortschritt und Batch-Ergebnis

### Phase 5: Tests und Vergleich

Status: abgeschlossen

- [x] Unit-Tests fuer Geld, Matching, Deduplizierung und Batch-Verhalten
- [x] UI-Smoke- und Massenauswahltests
- [x] Regressionstest der bisherigen Queue-/CSV-Funktionen
- [x] Legacy-Laufdateien als Paritaetsreferenz ausgewertet
- [x] Vollstaendige lokale Testsuite ausgefuehrt
- [x] Live-Leseverbindungen ohne Schreibzugriff geprueft

## Testprotokoll

### Automatisierte Clearing-Tests

Ausgefuehrt:

```text
python -m pytest tests/unit/test_payment_clearing_service.py
                 tests/unit/test_tax_services.py
                 tests/ui/test_payment_clearing_view.py
                 tests/ui/test_main_window_smoke.py -q
```

Ergebnis: **11 bestanden**.

Abgedeckt:

- Decimal-Rundung
- Payout-Deduplizierung
- exaktes Provider/Wix/Rechnungs-Matching
- Betragsabweichung als manueller Fall
- Import und anschliessende Rechnungsbuchung
- Wiederverwendung bestehender sevDesk-Transaktionen
- bisherige Queue-/Filter-/CSV-Kompatibilitaet
- Massenauswahl nur buchbarer Zeilen
- Navigation zum neuen Sidebar-Modul

### Statische Pruefungen

```text
mypy src/xw_studio/services/clearing
     src/xw_studio/ui/modules/payment_clearing --ignore-missing-imports
ruff check <Clearing-Quellen und -Tests>
python -m compileall -q src tests
```

Ergebnis: **ohne Befund**.

### Gesamte Testsuite

Ergebnis am 12.06.2026:

- 333 bestanden
- 11 uebersprungen
- 14 fehlgeschlagen

Die 14 Fehler liegen in bereits vorhandenen, nicht vom Clearing betroffenen
Daily-Business-Paritaets- und Drucktests. Sie erwarten unter anderem absichtlich entfernte
APIs, veraenderbare Frozen-Konfiguration und nicht mehr fehlende Funktionen. Die
Clearing-Tests sind davon unabhaengig vollstaendig gruen.

### Legacy-Paritaet Maerz 2026

Legacy-Lauf `2026-04-01T17-34-29.383948+02-00`:

- 173 Zahlungen
- 150 Stripe
- 23 Mollie
- 170 Matches
- Matchcache: 148 Stripe, 22 Mollie
- 3 offene Zahlungen

Read-only Live-Analyse der neuen Implementierung:

- Mollie: 23 Zahlungen erkannt und eindeutig zu Wix aufgeloest
- alle 23 Zahlungen sind inzwischen in sevDesk als gebucht erkennbar
- 1 Mollie-Settlement als separater Importfall erkannt
- zusaetzliche heutige Zuordnung gegenueber dem Legacy-Cache: Wix Order `20232`
- keine Schreiboperation ausgefuehrt

Die Wix-Zahlungsaufloesung wurde anschliessend vom Legacy-N+1-Verfahren auf den offiziellen
Bulk-Endpunkt `payments/list-by-ids` umgestellt. Ein Live-Lesetest fuer 231 Orders und 1.099
aufgeloeste Referenzen dauerte danach 6,72 Sekunden statt rund zwei Minuten. Bei einem
Bulk-Fehler bleibt ein Einzelabruf-Fallback erhalten.

Damit stimmt der Mollie-Bestand fachlich mit dem Legacy-Lauf ueberein; die eine Differenz
ist eine nach dem Legacy-Lauf erfolgte Buchung.

### Offener Betriebsbefund

Der im Secret-Store vorhandene Stripe-Schluessel liefert aktuell HTTP 401. Deshalb konnte
der Stripe-Anteil des Live-Paritaetsvergleichs nicht erneut gelesen werden. Der neue
Workflow bricht bei einem einzelnen Provider-Ausfall nicht mehr komplett ab, sondern
zeigt die Provider-Warnung an und verarbeitet die uebrigen Quellen weiter.

### Nicht ausgefuehrt

Es wurde entsprechend der Freigabe **keine echte sevDesk-Schreiboperation** gestartet.
Der Live-Buchungstest benoetigt weiterhin eine separate ausdrueckliche Zustimmung.

### Retest 16.06.2026

Nach Ergaenzung von `STRIPE_API_KEY` wurde Stripe erneut read-only getestet. Der neue Wert
ist vorhanden, wird von Stripe aber weiterhin mit HTTP 401 fuer `/v1/charges` abgewiesen.
Der komplette Clearing-Lauf bricht dadurch nicht ab:

- Mollie/Wix/sevDesk: 24 Vorgaenge gelesen
- Status: 24 bereits gebucht
- Provider-Warnungen: 1 Stripe-HTTP-401
- Schreibzugriffe: keine

Fuer den Stripe-Anteil wird ein gueltiger Stripe Secret Key oder ein Restricted Key mit
passenden Rechten fuer Charges, Refunds, Payouts und Balance Transactions benoetigt.

### Retest 16.06.2026 nach finalem Stripe-Key und Robustheitsausbau

Nach Setzen eines funktionierenden Restricted Keys in `STRIPE_SECRET_KEY` wurden die
drei offenen Robustheitspunkte umgesetzt und read-only erneut geprueft:

- Duplicate-Key nun analog Legacy zusammengesetzt aus Art, Provider, Provider-Ref,
  Wertdatum und Betrag
- Refunds erscheinen mit eigenem Status `refund_import` bzw. `refund_review`
- Analyse- und Buchungslaeufe werden als JSON unter `state/clearing_runs` persistiert

Live-Lesetest Maerz 2026:

- Gesamt: 178 Vorgaenge
- Provider: 154 Stripe, 24 Mollie
- Art: 173 Zahlungen, 5 Payouts
- Status: 178 bereits gebucht
- Warnungen: 0
- Schreibzugriffe: keine
