# Umbau-Skizze: Umsatzsteuervoranmeldung in XW-Studio

Stand: 2026-04-19

## 1. Ausgangslage

Ziel ist die saubere Integration der österreichischen Umsatzsteuervoranmeldung (UVA / U30) in XW-Studio auf Basis der Legacy-Logik aus `sevDesk/UVA.py`, aber **nicht als 1:1-Port**, sondern fachlich bereinigt, modularisiert und auf die XW-Studio-Architektur angepasst.

Vom Auftraggeber bestätigt:

- **IST-Versteuerung** ist maßgeblich.
- Gewünscht ist **Berechnung + Vorschau + FinanzOnline-Übermittlung**.
- Führende Datenquelle soll zunächst die **SevDesk-API live** sein.
- Relevante Sonderfälle:
  - EU-B2B-Leistungen / Reverse Charge
  - innergemeinschaftliche Lieferungen
  - OSS-Verkäufe an Privatkunden
  - Drittland / Ausfuhr
- Es gibt **bereits eingereichte UVA-Monate** für den fachlichen Soll-Ist-Abgleich.

---

## 2. Ergebnis der Legacy-Analyse

## 2.1 Was an der Altlogik fachlich plausibel ist

Die Legacy-Datei enthält bereits einige gute und für Österreich passende Grundannahmen:

1. **IST-Versteuerung wird zahlungsbasiert gerechnet**
   - Ausgänge werden nach Zahlungsdatum selektiert.
   - Teilzahlungen werden aliquot berücksichtigt.
   - Das passt zur IST-Versteuerung.

2. **Vorsteuer bei IST-Versteuerung wird ebenfalls zahlungsnah behandelt**
   - Das ist für den hier angenommenen österreichischen Fall stimmig.

3. **Ausländische Umsatzsteuer auf Eingangsbelegen wird nicht blind in KZ 060 gezogen**
   - Das ist wichtig und fachlich richtig.
   - Ausländische VAT gehört grundsätzlich **nicht** in die österreichische UVA, sondern ggf. in ein ausländisches Vorsteuererstattungsverfahren.

4. **OSS-/Fremdsteuersätze werden überwiegend nicht in die Inlands-UVA eingemischt**
   - Das ist als Grundrichtung richtig.

5. Die vorhandenen Legacy-Tests für den Monatslauf sind derzeit stabil:
   - **28 Tests bestanden** beim gezielten Testlauf der UVA-Unit-Tests.

## 2.2 Fachliche Korrekturen und Schwachstellen

Die Legacy-Logik ist **für viele Standardfälle brauchbar**, aber **nicht vollständig sauber genug**, um sie unverändert in XW-Studio zu übernehmen.

### A. EU-B2B-Leistungen und innergemeinschaftliche Lieferungen bleiben in der österreichischen UVA sichtbar

Aktueller fachlicher Zielentscheid:

- **EU-B2B-Leistungen / Reverse Charge** sollen in der österreichischen UVA berücksichtigt werden.
- **Innergemeinschaftliche Lieferungen** sollen ebenfalls in der UVA berücksichtigt werden.
- **Nur B2C-Auslandsleistungen** sollen nicht in die österreichische UVA laufen.

**Folge für den Umbau:**
Die Legacy-Logik darf diese B2B-Fälle weiterhin in der UVA führen, muss aber sauber zwischen:

- **B2B / UVA-relevant**
- **B2C / nicht UVA-relevant**

unterscheiden.

### B. Innergemeinschaftlicher Erwerb und Reverse Charge bleiben in Phase 1 bewusst pauschal bei 20 %

Für die jetzt beauftragte Phase 1 gilt ausdrücklich:

- **Reverse Charge weiterhin pauschal 20 %**
- **innergemeinschaftlicher Erwerb weiterhin pauschal 20 %**

Das ist eine pragmatische Zielvorgabe für die erste Integrationsstufe und wird daher so umgesetzt.

### C. Feldbezeichnungen in der Legacy-Datei sind teils irreführend

Einige Legacy-Labels nennen Werte „NETTO“, obwohl im Ergebnis eigentlich **Steuerbeträge** gemeint sind.
Das betrifft insbesondere die Darstellung rund um:

- KZ 057
- KZ 065
- KZ 066

Die interne Logik ist dort teilweise brauchbar, die **Benennung/Dokumentation aber fachlich missverständlich**.

### D. Teilweiser oder ausgeschlossener Vorsteuerabzug ist nicht sauber modelliert

Die Altlogik geht praktisch von einem voll abzugsfähigen Standardfall aus.
Für XW-Studio sollte das fachlich vorbereitet werden, auch wenn die erste Version zunächst auf den Vollabzug optimiert ist.

### E. Die Legacy-Datei ist architektonisch nicht übernehmbar

`UVA.py` ist als monolithische Sammeldatei zu groß und enthält:

- Berechnung
- API-Zugriffe
- Caching
- Konsolenausgabe
- Klassifikation
- Transportlogik

alles in einem Modul.

Das widerspricht der Zielarchitektur von XW-Studio.

---

## 3. Recherche-Fazit zur fachlichen Zielberechnung

Die Zielberechnung für XW-Studio soll sich an folgendem fachlichen Verhalten orientieren:

| Fall | Behandlung in XW-Studio | UVA-Relevanz |
| --- | --- | --- |
| Österreichische Ausgangsrechnungen 20/10/13 % | nach Zahlung im Zeitraum berücksichtigen | ja |
| Inländisches Reverse Charge (Ausgangsseite) | getrennt erfassen | ja |
| EU-B2B-Leistung / Reverse Charge | in der österreichischen UVA mitführen | ja |
| Innergemeinschaftliche Lieferung von Waren | getrennt erfassen | ja |
| Ausfuhr / Drittland | getrennt erfassen | ja |
| OSS-Umsätze an Privatkunden in anderen EU-Ländern | aus der AT-UVA ausschließen, separat kennzeichnen | nein |
| Eingangsrechnung mit ausländischer ausgewiesener VAT | nicht in KZ 060 übernehmen | nein |
| Reverse-Charge-Eingangsleistung | pauschal mit 20 % führen und korrespondierende Vorsteuer berücksichtigen | ja |
| Innergemeinschaftlicher Erwerb | pauschal mit 20 % führen | ja |

---

## 4. Empfohlenes Zielmodell in XW-Studio

Die bereits vorhandenen Platzhalter in XW-Studio sind sinnvoll und sollen ausgebaut werden:

- `src/xw_studio/services/finanzonline/uva_service.py`
- `src/xw_studio/services/finanzonline/uva_soap.py`
- `src/xw_studio/services/finanzonline/client.py`
- `src/xw_studio/ui/modules/taxes/view.py`
- `src/xw_studio/bootstrap.py`

### Neue fachliche Zielstruktur

#### 4.1 `uva_rules.py`
Enthält ausschließlich steuerliche Klassifikation:

- Tax-Text-Mappings
- Erkennung von AT / EU / OSS / Drittland
- satzabhängige Zuordnung
- Abgrenzung:
  - inländischer RC
  - EU-B2B-Leistung
  - ig Lieferung
  - ig Erwerb
  - ausländische VAT

#### 4.2 `uva_models.py`
Pydantic-Modelle für:

- UVA-Periode
- Dokumentklassifikation
- Summenfelder / Kennzahlen
- Preview-Payload
- Übermittlungsresultat

#### 4.3 `uva_payload_service.py`
Baut aus SevDesk-Daten den fachlich sauberen UVA-Entwurf:

- lädt Belege und Rechnungen
- bestimmt Zahlungsrelevanz im Zeitraum
- klassifiziert Steuerfälle
- bildet die Kennzahlen
- erzeugt eine nachvollziehbare Preview inkl. Warnungen

#### 4.4 `uva_submission_service.py`
Kapselt die FinanzOnline-Übermittlung:

- SOAP-Aufruf
- Request/Response-Mapping
- Fehlerbehandlung
- Protokollierung
- sichere Rückmeldung an UI

#### 4.5 `uva_validation_service.py`
Vergleicht XW-Studio-Berechnung mit bereits eingereichten Monaten:

- Monats-Snapshot laden
- Soll/Ist-Differenzen anzeigen
- Abweichungen pro Kennzahl dokumentieren

---

## 5. Konkrete fachliche Regeln für Version 1

## 5.1 Standard-Ausgangsumsätze

- Nur **im Zeitraum bezahlte** Umsätze zählen.
- Teilzahlungen werden aliquot auf Netto und Steuer umgelegt.
- Standardsteuersätze:
  - 20 %
  - 10 %
  - 13 %

## 5.2 EU-B2B-Leistungen

- in die österreichische UVA aufnehmen
- in Phase 1 als B2B-/Reverse-Charge-Fall sichtbar halten
- nur B2C-Auslandsleistungen ausschließen

## 5.3 Innergemeinschaftliche Lieferungen

- nur dann UVA-relevant, wenn es sich wirklich um **Warenlieferungen** handelt
- in der technischen Logik darf „EU“ **nicht automatisch** als „ig Lieferung“ interpretiert werden

## 5.4 OSS

- alle OSS-Umsätze strikt aus der AT-UVA ausschließen
- in der Preview mit eigener Summenzeile ausweisen
- dadurch bleibt die österreichische UVA sauber

## 5.5 Eingangsbelege mit ausländischer Steuer

- keine Verbuchung in KZ 060
- stattdessen Warnhinweis / Auslands-VAT-Info

## 5.6 Reverse Charge / ig Erwerb

- in Phase 1 bewusst mit **20 % pauschal** rechnen
- korrespondierende Vorsteuer nur ziehen, wenn Vorsteuerabzug zulässig ist
- spätere Verfeinerung bleibt optional für Phase 2+

---

## 6. Präziser Umbauplan für XW-Studio

## Phase 1 – Legacy sauber zerlegen

**Ziel:** nur die belastbaren Regeln übernehmen, nicht den Monolithen.

Arbeiten:

1. Relevante Berechnungslogik aus `sevDesk/UVA.py` fachlich extrahieren.
2. Alles trennen in:
   - Klassifikation
   - Periodenselektion
   - Aggregation
   - Submission
3. Alle Alt-Caches und Konsolenhilfen **nicht** direkt übernehmen.

**Ergebnis:** klar testbare Fachlogik.

## Phase 2 – neue UVA-Domain in XW-Studio aufbauen

Neue Module:

- `src/xw_studio/services/finanzonline/uva_rules.py`
- `src/xw_studio/services/finanzonline/uva_models.py`
- `src/xw_studio/services/finanzonline/uva_payload_service.py`
- optional `src/xw_studio/services/finanzonline/uva_validation_service.py`

**Ergebnis:** modulares, typisiertes UVA-Fundament.

## Phase 3 – bestehende Services erweitern

### `uva_service.py`
Erweitern um:

- `build_preview(year, month)`
- `calculate_month(year, month)`
- `validate_against_reference(...)`
- `submit_uva(payload)`

### `client.py`
Belassen als Einstiegspunkt für FinanzOnline, aber:

- bessere Fehlertexte
- saubere Credentials-Prüfung
- klare Unterscheidung zwischen Mock- und Live-Modus

### `uva_soap.py`
Ausbauen für:

- robustes SOAP-Mapping
- Zeitüberschreitungen / Faults
- übermittelte Referenz-ID
- Response-Audit-Log

## Phase 4 – UI in `taxes/view.py` real machen

Die aktuelle Oberfläche ist nur ein Platzhalter.
Sie soll erweitert werden um:

1. Monats-/Jahresauswahl
2. echte Preview mit Kennzahlen
3. Warnbereich für Sonderfälle
4. Button „UVA prüfen“
5. Button „UVA senden“
6. Ergebnisdialog mit Referenz / Status / Fehlermeldung

**Wichtig:**
Das Senden bleibt asynchron über `BackgroundWorker`.

## Phase 5 – Validierung gegen echte Monate

Da bereits echte Einreichungsmonate vorhanden sind, wird die Berechnung **nicht nur technisch**, sondern fachlich gegen die Realität geprüft.

Vorgehen:

1. 2–3 bereits eingereichte Monate auswählen
2. XW-Studio-Berechnung dagegen laufen lassen
3. Abweichung je Kennzahl dokumentieren
4. Fachregeln nachschärfen
5. erst danach Live-Übermittlung freischalten

---

## 7. Minimale Testmatrix für die Implementierung

Pflichttests:

1. Standardrechnung 20 % voll bezahlt
2. Standardrechnung 10 % teilbezahlt
3. Gutschrift negativ im gleichen Monat
4. ausländische VAT auf Eingangsbeleg → **nicht** in KZ 060
5. OSS-Rechnung → **nicht** in AT-UVA
6. EU-B2B-Leistung → **nicht** in AT-UVA
7. ig Lieferung Ware → richtige Kennzahl
8. Reverse-Charge-Eingang → Steuer + Vorsteuer korrekt
9. ig Erwerb 20 %
10. ig Erwerb reduzierter Satz
11. Drittland/Ausfuhr
12. Monatsabgleich gegen echten Referenzmonat

---

## 8. Akzeptanzkriterien

Die Integration gilt erst dann als fachlich bereit, wenn alle folgenden Punkte erfüllt sind:

- die Kennzahlen werden aus echten SevDesk-Daten nachvollziehbar erzeugt
- die Preview zeigt alle Summen und Warnungen transparent an
- EU-B2B-Leistungen, OSS und ausländische VAT werden **nicht falsch** in die AT-UVA gezogen
- Reverse Charge und ig Erwerbe sind **satzabhängig** modelliert
- mindestens 2 Referenzmonate stimmen fachlich mit der historischen UVA ausreichend überein
- SOAP-Übermittlung liefert reproduzierbare Rückmeldungen und Fehlertexte

---

## 9. Empfohlene Umsetzung in Priorität

### Priorität 1
- fachlich saubere Berechnung und Preview
- korrekte Sonderfall-Abgrenzung
- Referenzmonats-Abgleich

### Priorität 2
- Live-FinanzOnline-Senden
- Audit-Protokoll und bessere Fehlerrückmeldung

### Priorität 3
- Komfortfunktionen
  - Monatsvorschläge
  - Export / PDF / Archivierung
  - automatische Validierung historischer Perioden

---

## 10. Klare Empfehlung

**Die Legacy-Datei ist ein guter fachlicher Startpunkt, aber kein geeigneter Direkt-Port.**

Für XW-Studio sollte umgesetzt werden:

- **fachlich korrigierte** UVA-Logik
- **modularisierte Services** statt Monolith
- **echte Preview vor Versand**
- **Validierung gegen bereits eingereichte Monate**
- erst danach **Live-FinanzOnline-Übermittlung**

Damit ist die Integration belastbar, nachvollziehbar und wartbar.
