# Provisionsabrechnung MusikHeroes - Umbauskizze

Stand: 2026-07-08  
Ziel: Legacy-Punkt "Provisionsabrechnung" aus `C:\Users\bernh\GitHub\sevDesk` fachlich sauber in XW-Studio integrieren, zuerst mit der Auswahl "MusikHeroes", ohne die PySide6-App jetzt schon umzubauen.

## Kurzfazit

Die aktuelle XW-Studio-Seite `Provisionen` ist ein kleiner Tab-Prototyp fuer Artikelliste und Schnellrechner. Das Legacy-Modul ist fachlich breiter: es kombiniert Provisions-/Artikelanalyse, Kategorieauswertungen, Druckrechte, Mindestgebuehr und Beteiligungen. Fuer viele weitere Abrechnungen ist ein Tab-Layout ungeeignet, weil die Breite knapp wird und die Liste der Abrechnungsprofile wachsen wird.

Empfohlener Umbau: Die Seite `Provisionen` bleibt ein Hauptmodul, bekommt aber links eine vertikale, gruppierte Auswahl und rechts einen `QStackedWidget`-Arbeitsbereich. "MusikHeroes" wird als erstes produktives Abrechnungsprofil umgesetzt. Weitere Profile werden spaeter als Konfiguration und eigene Detailseiten ergaenzt, nicht als neue Tabs.

## Relevante Legacy-Funde

### Legacy-Einstieg

- `sevdesk_wix_fulfillment/ui/provision_kalkulation_app.py`
  - Baut zwei Spalten:
    - links `ArticleAnalysisApp`
    - rechts `KalkulationApp`
  - Das ist fuer Tk/ttkbootstrap pragmatisch, in XW-Studio aber zu breit und schwer erweiterbar.

- `sevdesk_wix_fulfillment/ui/article_analysis_app.py`
  - Enthalten sind Zeitraumwahl, Basisdatum, Kategorie-/Artikelanalyse, Suchfelder, Fortschritt, Ergebnistext, Copy-Feld, Produkt- und Rechnungslisten.
  - Die UI ist funktional, aber stark mit Datenzugriff, Caching und Speziallogik vermischt.

- `sevdesk_wix_fulfillment/services/article_analysis.py`
  - Enthalten sind die eigentlichen Analyseprofile (`ARTICLE_ANALYSIS_OPTIONS`) und die Kategoriegruppe fuer `musikheroes`.
  - "MusikHeroes" umfasst aktuell diese sevDesk-Kategorien:
    - `MusikHeroes`
    - `MusikHeroes_Noten digital`
    - `MusikHeroes_Playalongs digital`
    - `MusikHeroes_Print@Home`
  - Die Auswertung laedt jahrweise Rechnungen, Rechnungspositionen, CreditNotes, CreditNote-Positionen, Kategorien und Parts.

- `sevdesk_wix_fulfillment/ui/kalkulation_app.py`
  - Enthalten sind Kalkulation Druckrechte, Mindestgebuehr, Beteiligungen.
  - Diese Funktionen sollten in XW-Studio nicht mit der Provisionsabrechnung vermischt werden, sondern als eigene Auswahlgruppe im selben Modul erscheinen.

### Aktueller XW-Studio-Stand

- `src/xw_studio/ui/modules/calculation/view.py`
  - Nutzt derzeit `QTabWidget` mit "Artikelliste" und "Schnellrechner".
  - Fuer viele Provisionen/Kunden ist das Layout nicht skalierbar.

- `src/xw_studio/services/calculation/service.py`
  - Enthalten sind nur einfache Royalty-Helfer und persistierte Artikel aus `calculation.articles`.
  - Es gibt noch keine echte Provisionsabrechnung gegen sevDesk-Belege.

- `src/xw_studio/services/sevdesk/invoice_client.py`
  - Kann Rechnungen und einzelne Rechnungspositionen lesen.
  - Fuer die Legacy-Paritaet fehlen Bulk-Provider fuer `InvoicePos`, `CreditNote`, `CreditNotePos`, sowie ein jahrweiser Cache.

- `src/xw_studio/services/sevdesk/part_client.py`
  - Kann Parts und Part-Kategorien lesen.
  - Kann fuer Kategoriezuordnung und Profilauflosung genutzt werden.

## Analyse der `-5` im Juni

Die uebergebene Analyse sieht nach "letzter Monat" bei Stichtag im Juli 2026 aus, also nach 2026-06-01 bis 2026-06-30.

In der heutigen Legacy-Cache-Datei `C:\Users\bernh\GitHub\sevDesk\analysis_cache\analysis_data_year_2026.json` wurden fuer Juni 2026 keine passenden `CreditNote`-Belege gefunden. Die negativen Mengen entstehen aus normalen `Invoice`-Datensaetzen mit `invoiceType == "SR"`.

Konkrete Beispiele aus dem Cache:

| SKU | Ursache |
| --- | --- |
| `XW-511.09` | `RE-261880` am 2026-06-08: `+1`, `22,64` netto; `RE-261929` am 2026-06-17: `+1`, `22,64` netto; `RE-261922` am 2026-06-18 mit `invoiceType="SR"`: Menge `7`, `sumNet=-116,18`. Legacy rechnet daraus Menge `1 + 1 - 7 = -5`, aber Netto `22,64 + 22,64 + 116,18 = 161,46`. |
| `XW-521.09` | `RE-261966` am 2026-06-26: `+1`, `23,27` netto; `RE-261922` am 2026-06-18 mit `invoiceType="SR"`: Menge `4`, `sumNet=-66,39`. Legacy rechnet daraus Menge `-3`, aber Netto `89,66`. |
| `XW-561.02` | Ebenfalls ein Mischfall aus normalen Juni-Rechnungen und `RE-261923` am 2026-06-18 mit `invoiceType="SR"`. Deshalb kann die Menge auf `0` fallen, waehrend Netto positiv bleibt. |

Der fachliche Fehler liegt nicht primaer bei "vergessenen CreditNotes", sondern bei der Vorzeichenlogik fuer `SR`:

- In `article_analysis.py` ist `CANCEL_INVOICE_TYPES = {"SR"}` definiert.
- Bei Rechnungspositionen wird fuer `SR` die Menge negativ gemacht.
- Gleichzeitig haben die `SR`-Positionen im sevDesk-Payload bereits negative `sumNet`/`sumGross`.
- Die Legacy-Logik multipliziert den negativen Netto-Betrag nochmals mit `-1`, wodurch er positiv wird.

Ergebnis: negative Stueckzahl, aber positiver Umsatz. Genau dieses Muster sieht man in der Analyse.

Zusaetzlicher Legacy-Risiko-Punkt: `_credit_note_in_period()` ordnet CreditNotes zuerst dem Datum der Ursprungsrechnung zu und erst danach dem CreditNote-Datum. Das kann spaeter dazu fuehren, dass eine Gutschrift aus Juli in eine Juni-Abrechnung faellt, wenn die Ursprungsrechnung im Juni war. Fuer Provisionsabrechnung sollte das explizit steuerbar sein.

## Zielbild fuer XW-Studio

### Navigationsstruktur

Kein weiteres `QTabWidget` als Hauptnavigation. Stattdessen:

- Linke Spalte: vertikale, gruppierte Auswahl, ca. 240-280 px breit.
- Rechte Seite: `QStackedWidget` fuer die jeweils gewaehlte Arbeitsflaeche.
- Obere Zeile: kompakter Kontextkopf mit Titel, Zeitraum, Datenstand, Lade-/Exportaktionen.

Vorgeschlagene Gruppen links:

1. `Abrechnungen`
   - `MusikHeroes` (erste produktive Auswahl)
   - spaeter: `Supergroup`, `Mnozil`, `Pravecek`, `Flip`, `Albert`, `Leonhard`, `Krickl`, weitere Kunden

2. `Analysen`
   - `Freie Artikelanalyse`
   - `Freie Kategorieanalyse`
   - `Unveroeffentlichte Noten`

3. `Kalkulatoren`
   - `Druckrechte`
   - `Mindestgebuehr`
   - `Beteiligungen`

So bleibt das Modul breit nutzbar, aber die wachsende Anzahl an Abrechnungen verbraucht keine horizontale Flaeche.

### MusikHeroes-Seite

Die erste produktive Detailseite sollte nicht nur den Legacy-Text ausgeben, sondern als pruefbare Abrechnung gestaltet sein.

Oben:

- Zeitraumwahl:
  - `Letztes Jahr`
  - `Letztes Halbjahr`
  - `Letztes Quartal`
  - `Letzter Monat`
  - `Benutzerdefiniert`
- Stichtag oder Von/Bis, je nach Zeitraumtyp.
- Basisdatum:
  - `Rechnungsdatum`
  - `Zahlungsdatum`
  - spaeter optional: `Storno-/Gutschriftdatum`
- Schalter:
  - `Stornos einbeziehen`
  - `Gutschriften einbeziehen`
  - `Problemfaelle anzeigen`
- Aktionen:
  - `Neu laden`
  - `Cache verwenden`
  - `CSV/XLSX exportieren`
  - `Abrechnung kopieren`

KPI-Zeile:

- Gesamtmenge netto
- Netto gesamt
- Brutto gesamt
- Storno-/Korrekturmenge
- Anzahl Belege
- Anzahl Problemfaelle

Hauptbereich:

- Tabelle `Produktaufschluesselung`
  - SKU
  - Name
  - Verkaufte Menge
  - Storno-/Korrekturmenge
  - Netto-Menge
  - Netto Umsatz
  - Brutto Umsatz
  - Kategorien
  - Warnhinweis

- Tabelle `Kategorien`
  - Kategorie
  - Menge
  - Brutto
  - Netto
  - Anteil

- Detailbereich unten oder rechts:
  - ausgewählte SKU mit Belegen
  - Rechnungsnummer
  - Datum
  - Typ (`RE`, `SR`, CreditNote)
  - Menge roh
  - Netto roh
  - angewandtes Vorzeichen
  - Grund der Zuordnung

Problemfaelle sollten sichtbar und nicht in einem Debugtext versteckt sein. Beispiele:

- Menge negativ, Netto positiv
- Menge `0`, Netto ungleich `0`
- `SR` mit bereits negativem Betrag
- CreditNote ausserhalb des gewaehlten Zeitraums, aber Ursprungsrechnung innerhalb
- unbekannte Kategorie-ID oder Part ohne Kategorie

## Fachliche Datenlogik

### Neue Domain-Modelle

Vorschlag: Service unter `src/xw_studio/services/calculation/commission_service.py` oder eigener Namespace `src/xw_studio/services/commission/`.

Kernmodelle:

- `CommissionProfile`
  - `key`
  - `label`
  - `category_names`
  - `category_ids`
  - `sku_patterns`
  - `default_royalty_pct`
  - `include_credit_notes`
  - `include_cancellation_invoices`
  - `date_policy`

- `CommissionPeriod`
  - `start`
  - `end`
  - `basis`
  - `reference_date`

- `CommissionRunResult`
  - `profile`
  - `period`
  - `summary`
  - `product_rows`
  - `category_rows`
  - `document_rows`
  - `anomalies`
  - `source_stats`

- `ProductBreakdownRow`
  - `sku`
  - `name`
  - `sold_quantity`
  - `canceled_quantity`
  - `credited_quantity`
  - `net_quantity`
  - `net_amount`
  - `gross_amount`
  - `category_names`

- `DocumentContribution`
  - `document_id`
  - `document_number`
  - `document_type`
  - `document_date`
  - `source_kind`
  - `sku`
  - `raw_quantity`
  - `raw_net`
  - `raw_gross`
  - `signed_quantity`
  - `signed_net`
  - `signed_gross`
  - `rule`

### Profile nicht fest in UI verdrahten

MusikHeroes sollte als erstes Profil in einer Profile-Konfiguration liegen, nicht hart in der View. Start einfach:

- DB-Key: `commission.profiles`
- oder Datei: `config/commission_profiles.yaml`

Empfohlen fuer den ersten Schritt: Python-Defaultprofil im Service plus spaeter Settings-Override. So ist die erste Umsetzung robust, aber die spaetere Pflege bleibt moeglich.

MusikHeroes-Profil:

```yaml
key: musikheroes
label: MusikHeroes
category_names:
  - MusikHeroes
  - MusikHeroes_Noten digital
  - MusikHeroes_Playalongs digital
  - MusikHeroes_Print@Home
date_policy: invoice_date
include_cancellation_invoices: true
include_credit_notes: true
```

Nach dem Laden sollten Kategorie-Namen in IDs aufgeloest werden. Die eigentliche Auswertung sollte nach Kategorie-ID matchen, nicht dauerhaft nach Namen, weil Namen Tippfehler/Umbenennungen haben koennen.

### Korrekte Vorzeichenlogik

Die neue Logik sollte keine Betragsvorzeichen blind doppelt drehen.

Regelvorschlag:

1. Rohwerte aus sevDesk bleiben erhalten.
2. `signed_net` und `signed_gross` kommen primaer aus `sumNet`/`sumGross`, weil sevDesk bei `SR` bereits negative Betraege liefern kann.
3. `signed_quantity` wird fachlich bestimmt:
   - normale Rechnung: `+abs(quantity)`
   - `invoiceType == "SR"`: `-abs(quantity)`
   - CreditNote: `-abs(quantity)`
4. Wenn ein `SR` positive Betraege liefert, werden die Betraege negativ gesetzt.
5. Wenn ein `SR` bereits negative Betraege liefert, bleiben sie negativ.
6. Tabellen zeigen getrennt:
   - verkaufte Menge
   - Storno-/Gutschriftsmenge
   - Netto-Menge
   - Umsatzbetrag

Damit wuerde `XW-511.09` fachlich als `2 verkauft, 7 storniert, netto -5` erscheinen, und der Betrag waere nicht faelschlich `+161,46`. Je nach Abrechnungsregel kann die UI dann entscheiden, ob negative Netto-Umsaetze erlaubt sind oder als Warnfall separat behandelt werden.

### CreditNote-Zeitraum

Die Legacy-Funktion `_credit_note_in_period()` ist fuer Abrechnungen riskant, weil sie CreditNotes ueber die Ursprungsrechnung in einen Zeitraum ziehen kann.

Neue Regel:

- Standard fuer Provisionsabrechnung: CreditNote zaehlt nach `creditNoteDate`.
- Optionaler Modus: CreditNote zaehlt nach Ursprungsrechnung, aber nur bewusst ausgewaehlt und in der UI markiert.
- Jede CreditNote bekommt im Detail eine Spalte `Zuordnung: CreditNote-Datum` oder `Zuordnung: Ursprungsrechnung`.

## Datenzugriff und Cache

### Provider

Ein neuer Provider sollte die Legacy-Bulk-Abfragen sauber in XW-Studio kapseln:

- `list_invoices_for_year(year)`
- `list_invoice_positions(year)`
- `list_credit_notes(year)`
- `list_credit_note_positions(year)`
- `list_parts()`
- `list_part_categories()`

Der Provider kann intern `SevdeskConnection` direkt nutzen, statt die bestehende `InvoiceClient`-API zu ueberladen. Wichtig ist, dass die Rohpayloads fuer Tests und Debugging erhalten bleiben.

### Cache

Der Legacy-Cache `analysis_cache/analysis_data_year_2026.json` zeigt, dass jahrweises Caching sinnvoll ist. In XW-Studio sollte der Cache aber klar versioniert und app-intern liegen, z. B.:

- `state/commission/analysis_data_year_2026.json`
- mit `created_at`
- mit `source`
- mit `profile_version`
- mit `schema_version`

UI-Verhalten:

- Beim ersten Laden: live fetch + Cache schreiben.
- Bei erneutem Laden: Cache nutzen, aber Datenstand sichtbar zeigen.
- Button `Neu laden` erzwingt API-Abruf.

## UI-Details

### Layout-Skizze

```text
+--------------------------------------------------------------+
| Provisionen                                  [Neu laden] [...] |
+----------------------+---------------------------------------+
| Abrechnungen          | MusikHeroes                           |
|  > MusikHeroes        | Zeitraum / Basis / Optionen           |
|    Supergroup         | KPI-Zeile                             |
|    Mnozil             |---------------------------------------|
|                       | Produktaufschluesselung               |
| Analysen              |                                       |
|  Freie Artikelanalyse |---------------------------------------|
|  Freie Kategorie      | Kategorien / Problemfaelle            |
|                       |---------------------------------------|
| Kalkulatoren          | Belegdetails zur Auswahl              |
|  Druckrechte          |                                       |
|  Mindestgebuehr       |                                       |
|  Beteiligungen        |                                       |
+----------------------+---------------------------------------+
```

### Warum nicht Tabs

- Viele Provisionsprofile wachsen vertikal besser als horizontal.
- Die linke Auswahl kann gruppiert, gefiltert und spaeter mit Badges versehen werden.
- `QStackedWidget` erlaubt je Profil eigene Detailseiten, ohne dass alle Inhalte gleichzeitig sichtbar sein muessen.
- Auf kleineren Fenstern bleiben die Haupttabellen breiter.

### Optik

Stil passend zum bestehenden XW-Studio:

- ruhige Finanz-/Arbeitsoberflaeche, keine Marketing-Karten
- 6-8 px Radius maximal
- dichte Tabellen mit klaren Zahlen-Spalten
- Warnfaelle farblich sparsam:
  - neutral fuer normale Zeilen
  - gelb fuer pruefen
  - rot nur fuer harte Inkonsistenzen
- wiederverwendbare Widgets:
  - `DataTable` fuer Tabellen
  - bestehende `BackgroundWorker`-Struktur fuer API/Cache
  - bestehende QSS statt Sonderdesign pro Modul

## Umsetzungsphasen

### Phase 1: Fachservice ohne neue UI

Ziel: Provisionslogik testbar machen.

Aufgaben:

- Neues Modul fuer Commission-Domain anlegen.
- MusikHeroes-Profil als erstes Defaultprofil.
- Periodenlogik aus Legacy uebernehmen, aber isoliert testen.
- Bulk-Provider-Schnittstelle definieren.
- Cache-Lader fuer Legacy-Cache als Test-/Migrationshilfe ergaenzen.
- Vorzeichenlogik fuer `SR` und CreditNotes korrigieren.
- Ergebnisdataclasses fuer Produkt, Kategorie, Belege, Anomalien.

Tests:

- Juni-2026-Fixture mit `RE-261922`/`RE-261923`.
- Test: `SR` mit negativem `sumNet` bleibt negativ.
- Test: keine Zeile mit negativer Menge und positivem Netto ohne Warnung.
- Test: CreditNote-Datum vs. Ursprungsrechnung-Datum.
- Test: MusikHeroes-Kategorien werden ueber IDs korrekt gematcht.

### Phase 2: Neue Provisions-UI-Shell

Ziel: Tabs entfernen, Master-Detail-Struktur einfuehren.

Aufgaben:

- `CalculationView` in eine vertikale Auswahl + `QStackedWidget` umbauen.
- Bestehende Artikelliste und Schnellrechner als Eintraege unter `Kalkulatoren` weiterfuehren.
- Noch keine Legacy-Features loeschen, nur in neue Struktur ueberfuehren.
- Statuszeile und Ladezustand vereinheitlichen.

Tests:

- UI-Smoke: Modul laedt.
- Auswahl wechselt zwischen Eintraegen.
- Keine horizontale Mindestbreite durch Tabs.

### Phase 3: MusikHeroes produktiv anbinden

Ziel: erste echte Provisionsabrechnung in PySide6.

Aufgaben:

- MusikHeroes-Seite bauen.
- Zeitraum-/Basisdatum-Controls.
- Ergebnis-KPIs.
- Produkt- und Kategorie-Tabellen.
- Belegdetails und Problemfallliste.
- Copy-/Export-Funktionen.
- Cache-Datenstand sichtbar machen.

Tests:

- Fixture-basierte Service-Tests.
- UI-Smoke mit Fake-Service.
- Export-/Copy-Format stabil testen.

### Phase 4: Weitere Abrechnungen skalierbar machen

Ziel: neue Kunden/Profile ohne UI-Umbau ergaenzen.

Aufgaben:

- Profil-Registry.
- Such-/Filterfeld in linker Auswahl.
- Profil-Metadaten: Beschreibung, Satz, Abrechnungsregel, Kategorie-/SKU-Filter.
- Optional: Profil-Editor in Einstellungen.
- Wiederverwendbare Detailseite fuer einfache Kategorieprofile.
- Sonderseiten nur fuer Profile mit echter Sonderlogik.

## Migrationshinweise aus Legacy

Nicht 1:1 uebernehmen:

- UI-Textausgabe als primaeres Ergebnis.
- Vermischung von UI, API, Cache, Matching und Export.
- `max(quantity, 0.0)` beim Abzug von CreditNotes, weil dadurch echte negative Korrekturen verschwinden.
- Doppelte Vorzeichenumkehr bei `SR`.
- CreditNotes automatisch nach Ursprungsrechnung einordnen.

Uebernehmen:

- Periodenlogik als Ausgangspunkt.
- MusikHeroes-Kategoriegruppe.
- Jahrweiser Cache-Ansatz.
- Produkt-/Kategorieaufschluesselung.
- Beleglisten als Nachweis.
- Fortschrittsanzeige fuer lange API-Ladevorgaenge.

## Offene fachliche Entscheidungen

1. Sollen `SR`-Belege in Provisionsabrechnungen immer als Storno zaehlen, oder nur wenn `status`/Betrag/Menge ein Storno-Muster bestaetigen?
2. Soll eine Abrechnung negative Netto-Mengen erlauben, oder sollen solche Zeilen in "Korrekturen" ausgelagert werden?
3. Zaehlen Gutschriften nach Gutschriftdatum oder nach Datum der Ursprungsrechnung? Empfehlung: Standard Gutschriftdatum.
4. Soll MusikHeroes auf Brutto, Netto oder gemischten Kategorien abrechnen? Die Legacy-Ausgabe zeigt fuer `MusikHeroes` Netto und Brutto, fuer digitale Unterkategorien nur Brutto.
5. Soll ein Provisionssatz direkt im Profil gepflegt werden, oder bleibt die erste Version reine Verkaufs-/Umsatzanalyse?

## Empfohlener naechster Schritt

Als naechstes sollte Phase 1 umgesetzt werden: reiner Service plus Tests gegen eine kleine Fixture aus dem heutigen Legacy-Cache. Erst wenn die Juni-Abrechnung fachlich sauber reproduziert und die `SR`-Vorzeichen korrigiert sind, sollte die PySide6-UI gebaut werden.
