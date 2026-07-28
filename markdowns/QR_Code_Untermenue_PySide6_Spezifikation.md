# Technische Spezifikation: QR-Code-Untermenü für die XeisWorks-PySide6-App

**Status:** Umsetzungsentwurf für AI-Extensions in VS Code  
**Quelldatei:** `QR-Codes Online.xlsx`  
**Schwerpunkt:** Register **„Ganze Skala“** sowie die Varianten **„Gesamtspielchen“**, **„Ungerade Zahlen“**, **„Gerade Zahlen“** und **„Jede 4.Zahl“**  
**Zielplattform:** Windows / PySide6  
**Festgelegte Benutzerentscheidungen:**

- Pro Erzeugungslauf wird **genau eine Variante** ausgewählt.
- QR-Einstellungen werden **global** gespeichert.
- Ausgabeformat ist in der ersten Version ausschließlich **PNG**.
- Standardgröße: **1000 × 1000 Pixel**.
- Ein Mittellogo ist standardmäßig aktiviert.
- Standardpfad des Mittellogos:

```text
C:\Users\XeisWorks\OneDrive - XeisWorks\02 XeisWorks\16 QR Codes\musikheroes_qr.png
```

---

## 1. Ziel des Moduls

Die bestehende Excel-Arbeitsmappe dient derzeit als manuelle Daten- und Formellogik zur Erzeugung von IDs, URLs und Bulk-Import-Zeilen für einen externen QR-Code-Prozess. Diese Logik soll vollständig in die bestehende PySide6-App übernommen werden.

Das neue Modul soll:

1. die bisher in Excel eingegebenen Daten über PySide6-Felder erfassen,
2. die Excel-Formellogik reproduzierbar und testbar abbilden,
3. aus den erzeugten URLs lokal und offline PNG-QR-Codes erstellen,
4. standardmäßig das MusikHeroes-Logo in der Mitte platzieren,
5. alle Dateien gesammelt in einen gewählten Ausgabeordner schreiben,
6. vor der Erzeugung eine vollständige Vorschau der IDs, URLs und Dateinamen anzeigen,
7. die globalen QR-Grafikeinstellungen dauerhaft speichern,
8. die bestehende App-Architektur respektieren und keine parallelen Settings-, Logging- oder Worker-Systeme aufbauen.

Ein externer Online-QR-Dienst oder eine kostenpflichtige API ist **nicht erforderlich**.

---

## 2. Empfohlene Menüstruktur

Die AI-Extension muss zuerst die bestehende Menüstruktur der App untersuchen. Die folgenden Namen sind als Zielbild zu verstehen und an bestehende Konventionen anzupassen.

```text
Werkzeuge
└── QR-Codes
    ├── QR-Code-Serie erzeugen …
    ├── QR-Code-Einstellungen …
    ├── Letzten Ausgabeordner öffnen
    └── Letztes Erzeugungsprotokoll anzeigen
```

Alternativ, wenn die App bereits ein eigenes Hauptmenü für Produktionswerkzeuge besitzt:

```text
Produktion
└── QR-Codes
    ├── Serie erzeugen …
    └── Einstellungen …
```

### 2.1 Menüaktionen

| Aktion | Verhalten |
|---|---|
| QR-Code-Serie erzeugen | Öffnet den Hauptdialog mit Variantenauswahl, Eingaben, Vorschau und Erzeugung. |
| QR-Code-Einstellungen | Öffnet einen kleinen globalen Einstellungsdialog. |
| Letzten Ausgabeordner öffnen | Öffnet den zuletzt verwendeten Ordner über `QDesktopServices.openUrl()`. Deaktiviert, wenn kein gültiger Ordner gespeichert ist. |
| Letztes Erzeugungsprotokoll anzeigen | Zeigt das zuletzt gespeicherte Manifest bzw. Protokoll an. Optional für MVP, empfohlen für Phase 2. |

---

## 3. Analyse der Excel-Arbeitsmappe

Die Arbeitsmappe enthält sieben sichtbare Register:

1. `Ganze Skala`
2. `Gesamtspielchen`
3. `JMLA`
4. `WIX-CMS`
5. `Ungerade Zahlen`
6. `Gerade Zahlen`
7. `Jede 4.Zahl`

Für das angeforderte QR-Untermenü sind primär die Register 1, 2, 5, 6 und 7 relevant. `JMLA` und `WIX-CMS` enthalten eigenständige, umfangreichere Datenmodelle und sollten nicht unbemerkt in den MVP hineingezogen werden. Die Architektur soll aber später weitere tabellenbasierte Presets aufnehmen können.

---

## 4. Register „Ganze Skala“ – exakte Ist-Logik

### 4.1 Relevante Eingabezellen

| Excel-Zelle | Bedeutung | Aktueller Wert | App-Feld |
|---|---|---|---|
| `A5` | sichtbares Kürzel / Serienkennung | `UUU#2` | `series_code` |
| `B5` | Instrument-Kürzel | `pos` | `instrument_slug` |
| `C5` | URL-Präfix | `https://www.xeisworks.at/mh-oa/uuu2/pos/` | berechnet, aber editierbar |
| `F5:F115` | laufende Nummern | `01` bis `111` | Start, Ende, Schritt, Mindestbreite |
| `G5` | Trennzeichen für Bulk-Import | `,` | `manifest_separator` |
| `K5:K9` | Instrument-Vorschläge | `trp`, `pos`, `ftb`, `btb`, `hrn` | editierbare ComboBox |

Die Datenvalidierung in `B5` verweist auf `K5:K10`. `K10` ist leer. In der App soll die leere Auswahl **nicht** als Instrument vorgeschlagen werden.

### 4.2 Excel-Formeln

**URL-Präfix:**

```excel
="https://www.xeisworks.at/mh-oa/uuu2/"&B5&"/"
```

**Logische ID:**

```excel
=$A$5&"-"&UPPER($B$5)&"/"&F5
```

**Ziel-URL:**

```excel
=$C$5&F5
```

**Bulk-Import-Zeile:**

```excel
=D5&$G$5&E5
```

### 4.3 Ergebnis mit aktuellen Daten

Erster Datensatz:

```text
ID:       UUU#2-POS/01
URL:      https://www.xeisworks.at/mh-oa/uuu2/pos/01
Bulk:     UUU#2-POS/01,https://www.xeisworks.at/mh-oa/uuu2/pos/01
```

Letzter Datensatz:

```text
ID:       UUU#2-POS/111
URL:      https://www.xeisworks.at/mh-oa/uuu2/pos/111
Bulk:     UUU#2-POS/111,https://www.xeisworks.at/mh-oa/uuu2/pos/111
```

Die Variante erzeugt aktuell **111 Datensätze**.

### 4.4 Nummernformat

Die Werte `01` bis `09` sind in Excel als Text mit führender Null gespeichert. Ab `10` werden normale Zahlen verwendet. Die App darf daher nicht starr auf zwei Zeichen kürzen. Die korrekte Regel lautet:

```python
formatted_number = str(number).zfill(2)
```

Beispiele:

```text
1   -> 01
9   -> 09
10  -> 10
99  -> 99
100 -> 100
111 -> 111
```

Die Einstellung sollte intern `minimum_number_width = 2` heißen, nicht `number_length = 2`.

---

## 5. Kritische Besonderheiten und Excel-Risiken

### 5.1 Kürzel und URL-Slug sind nicht gekoppelt

`A5` enthält `UUU#2`, während die Formel in `C5` den URL-Bestandteil `uuu2` hart codiert. Eine Änderung von `A5` ändert den URL-Pfad nicht automatisch.

Die App muss daher zwei getrennte Werte führen:

```text
Sichtbares Kürzel: UUU#2
URL-Projekt-Slug:  uuu2
```

Empfohlene Felder:

- `series_code`: `UUU#2`
- `project_slug`: `uuu2`
- `instrument_slug`: `pos`
- `base_domain`: `https://www.xeisworks.at`
- `base_path_template`: `/mh-oa/{project_slug}/{instrument_slug}/`

Die URL darf aus diesen Feldern automatisch zusammengesetzt werden. Zusätzlich soll ein Schalter **„URL-Präfix manuell bearbeiten“** vorgesehen werden, um Sonderfälle abzubilden.

### 5.2 Logische ID ist kein gültiger Windows-Dateiname

Die logische ID enthält `/`:

```text
UUU#2-POS/01
```

Der Schrägstrich ist unter Windows als Dateinamenzeichen unzulässig. Deshalb müssen drei Werte getrennt werden:

```text
logical_id:     UUU#2-POS/01
payload_url:    https://www.xeisworks.at/mh-oa/uuu2/pos/01
output_filename: UUU#2-POS_01.png
```

Die logische ID darf nicht verändert werden. Nur der Dateiname wird sicher bereinigt.

### 5.3 Einige Formeln sind in der XLSX-Datei als Shared Formulas gespeichert

Nicht jede sichtbare Ergebniszelle enthält eine eigenständige Formelzeichenfolge. Viele Zellen enthalten zwischengespeicherte Ergebnisse einer gemeinsam geführten Excel-Formel. Die PySide6-App darf daher nicht versuchen, die XLSX-Datei im laufenden Betrieb als Formelmotor zu verwenden. Die Logik soll nativ in Python implementiert werden.

### 5.4 „Neues Schema“ in Zeile 2

Im Register steht zusätzlich:

```text
https://www.xeisworks.at/mh-oa/uuu1/trp/02
```

Dieser Eintrag ist nicht mit der Haupttabelle verbunden. Er wird als Beispiel-/Notizzelle behandelt und nicht als aktive Datenquelle übernommen.

---

## 6. Analyse der Variantenregister

Wichtig: Die Registerbezeichnungen und die tatsächlich erzeugten Sequenzen sind teilweise nicht semantisch deckungsgleich. Die erste App-Version soll das **exakte Excel-Ist-Verhalten** bewahren und in der Oberfläche deutlich als „Excel-Logik“ kennzeichnen. Es darf keine stillschweigende Korrektur erfolgen.

### 6.1 Variante „Ganze Skala“

| Eigenschaft | Excel-Istwert |
|---|---|
| Modus | numerischer Bereich |
| Start | 1 |
| Ende | 111 |
| Schritt | 1 |
| Mindestbreite | 2 |
| ID-Muster | `{series_code}-{instrument_upper}/{number}` |
| URL-Muster | `{base_url}{number}` |
| Aktuelles Kürzel | `UUU#2` |
| Aktuelles Instrument | `pos` |
| Aktuelle URL-Basis | `https://www.xeisworks.at/mh-oa/uuu2/pos/` |
| Anzahl | 111 |

### 6.2 Variante „Gesamtspielchen“

Diese Variante ist keine mathematische Zahlenfolge, sondern eine explizite Instrumenttabelle mit zwölf Zeilen.

**Basis-URL:**

```text
https://www.xeisworks.at/dl-gesspiel/
```

**Excel-Tabelle:**

| Nr. | Anzeigename | Slug | URL |
|---:|---|---|---|
| 01 | Euphonium | `euph` | `https://www.xeisworks.at/dl-gesspiel/euph` |
| 02 | Begleitinstrumente | `begl` | `https://www.xeisworks.at/dl-gesspiel/begl` |
| 03 | Diatonische Harmonika | `harm` | `https://www.xeisworks.at/dl-gesspiel/harm` |
| 04 | B-Tuba | `btuba` | `https://www.xeisworks.at/dl-gesspiel/btuba` |
| 05 | Flöte+Oboe+Violine | `in-c` | `https://www.xeisworks.at/dl-gesspiel/in-c` |
| 06 | Saxophon | `sax` | `https://www.xeisworks.at/dl-gesspiel/sax` |
| 07 | Klarinette | `klar` | `https://www.xeisworks.at/dl-gesspiel/klar` |
| 08 | Tenorhorn | `ten` | `https://www.xeisworks.at/dl-gesspiel/ten` |
| 09 | F-Tuba | `ftuba` | `https://www.xeisworks.at/dl-gesspiel/ftuba` |
| 10 | Horn | `horn` | `https://www.xeisworks.at/dl-gesspiel/horn` |
| 11 | Posaune | `pos` | `https://www.xeisworks.at/dl-gesspiel/pos` |
| 12 | Trompete + Flügelhorn | `trp` | `https://www.xeisworks.at/dl-gesspiel/trp` |

Bulk-Zeile, Beispiel:

```text
01 Euphonium,https://www.xeisworks.at/dl-gesspiel/euph
```

Diese Variante benötigt in der App eine editierbare Tabelle und keine Start-/Endfelder.

### 6.3 Variante „Ungerade Zahlen“ – Excel-Logik

Trotz des Registernamens werden in der sichtbaren Ausgabetabelle die fortlaufenden Werte `01` bis `25` erzeugt.

| Eigenschaft | Excel-Istwert |
|---|---|
| Start | 1 |
| Ende | 25 |
| Schritt | 1 |
| Nummernsuffix | `d` |
| ID-Suffix | `-LOESUNG` |
| URL-Basis | `https://www.xeisworks.at/loes-wu1-pos/` |
| Beispiel-ID | `01d-LOESUNG` |
| Beispiel-URL | `https://www.xeisworks.at/loes-wu1-pos/01d` |
| Anzahl | 25 |

UI-Name für die erste Version:

```text
Ungerade Zahlen (Excel-Logik: 01–25)
```

### 6.4 Variante „Gerade Zahlen“ – Excel-Logik

Trotz des Registernamens werden die ungeraden Werte `01, 03, 05, …, 25` erzeugt.

| Eigenschaft | Excel-Istwert |
|---|---|
| Start | 1 |
| Ende | 25 |
| Schritt | 2 |
| tatsächliche Folge | `01, 03, 05, …, 25` |
| Nummernsuffix | `d` |
| ID-Suffix | `-CHECK` |
| URL-Basis | `https://www.xeisworks.at/wu1-check-trp/` |
| Beispiel-ID | `01d-CHECK` |
| Beispiel-URL | `https://www.xeisworks.at/wu1-check-trp/01d` |
| Anzahl | 13 |

UI-Name für die erste Version:

```text
Gerade Zahlen (Excel-Logik: 01, 03, …, 25)
```

### 6.5 Variante „Jede 4.Zahl“

| Eigenschaft | Excel-Istwert |
|---|---|
| Start | 4 |
| Ende | 24 |
| Schritt | 4 |
| Folge | `04, 08, 12, 16, 20, 24` |
| Nummernsuffix | `d` |
| ID-Suffix | `-CLIP` |
| URL-Basis | `https://www.xeisworks.at/wu1-clips-trp/` |
| Beispiel-ID | `04d-CLIP` |
| Beispiel-URL | `https://www.xeisworks.at/wu1-clips-trp/04d` |
| Anzahl | 6 |

---

## 7. Abgrenzung zu „JMLA“ und „WIX-CMS“

### 7.1 JMLA

Das Register `JMLA` enthält mehrere tabellenbasierte Gruppen, unter anderem:

- Übersicht Gold,
- Junior C,
- Junior B,
- Bronze C,
- Bronze B,
- Silber #-lastig,
- Silber b-lastig.

Es bildet URLs wie folgt:

```text
https://www.xeisworks.at/jmla/{instrument}/{stufe}/{tonart-slug}
```

Beispiel:

```text
https://www.xeisworks.at/jmla/fl/gold
```

### 7.2 WIX-CMS

Das Register `WIX-CMS` transformiert JMLA-Daten in mehrere Wix-CMS-Felder. Es ist keine reine QR-Code-Liste, sondern eine CMS-Datenaufbereitung mit IDs, Anzeigenamen, Instrument, Stufe, Slug und Pfadangaben.

### 7.3 Architekturfolge

JMLA und WIX-CMS werden nicht im MVP implementiert. Die Preset-Architektur muss aber einen späteren `TABLE_ROWS`-Modus unterstützen, damit JMLA ohne Komplettumbau ergänzt werden kann.

---

## 8. Recherche: geeignete kostenlose QR-Code-Bibliotheken

### 8.1 Kandidat A: `qrcode` + Pillow – Empfehlung

**Empfohlene Version:** `qrcode 8.2`  
**Lizenz:** BSD  
**Status:** Production/Stable  
**Python:** ab Python 3.9  
**PNG- und Pillow-Unterstützung:** direkt vorhanden  
**Mittellogo:** über `StyledPilImage` möglich; für dieses Projekt wird dennoch kontrolliertes manuelles Compositing mit Pillow empfohlen.

Vorteile:

- sehr einfache Python-API,
- gut für PySide6-Desktop-Apps geeignet,
- keine externe API und keine Internetverbindung notwendig,
- hohe Fehlerkorrektur `ERROR_CORRECT_H`,
- Pillow-Integration für Logo, Transparenz, Größenanpassung und exakte PNG-Ausgabe,
- ausreichend für statische URL-QR-Codes,
- BSD-Lizenz.

Nachteile:

- stark stilisierte Codes sind laut Projektdokumentation nicht mit jedem Reader garantiert kompatibel,
- exakte 1000 × 1000 Pixel und eine definierte Logogröße sollten nicht blind dem Standard-Renderer überlassen werden.

**Entscheidung:** Hauptgenerator.

Installation:

```bash
pip install "qrcode[pil]==8.2"
```

Für `pyproject.toml`:

```toml
dependencies = [
    "qrcode[pil]==8.2",
]
```

### 8.2 Kandidat B: Segno

**Aktuelle geprüfte Version:** `1.6.6`  
**Lizenz:** BSD  
**Eigenschaften:** reines Python, keine Pflichtabhängigkeiten, ISO/IEC-18004-orientiert, viele Ausgabeformate.

Vorteile:

- sehr standardorientiert,
- viele Tests,
- PNG ohne externe Bildbibliothek möglich,
- gute Option, wenn später SVG, EPS oder PDF benötigt werden.

Nachteile für dieses Projekt:

- das Mittellogo erfordert ein zusätzliches Pillow-/Artistic-Compositing,
- für ausschließlich PNG plus zentrales Logo bietet `qrcode + Pillow` den direkteren Weg.

**Entscheidung:** dokumentierte Alternative, nicht primäre Implementierung.

### 8.3 Kandidat C: ZXing-C++ Python Bindings

**Aktuelle geprüfte Version:** `3.1.0` vom 7. Juli 2026  
**Lizenz:** Apache-2.0  
**Funktion:** Lesen und Schreiben von Barcodes einschließlich QR-Code.

Vorteile:

- sehr gute Rücklese-/Validierungsbibliothek,
- kann nach der Erzeugung prüfen, ob der fertige QR-Code inklusive Logo wieder exakt zur URL dekodiert werden kann,
- aktuelle Windows-Wheels verfügbar.

Nachteile:

- native C++-Binärabhängigkeit,
- erhöht Paket- und Deployment-Komplexität,
- für die reine Generierung mit Logo nicht so komfortabel wie `qrcode + Pillow`.

**Entscheidung:** optionale Qualitätsprüfung bzw. Testabhängigkeit.

Optional:

```bash
pip install zxing-cpp==3.1.0
```

### 8.4 Warum kein Online-QR-Maker verwendet werden soll

Ein Online-Dienst wäre für diesen Workflow schlechter:

- zusätzliche Netzabhängigkeit,
- mögliche Limits für Bulk-Erzeugung,
- Datenschutz- und Verfügbarkeitsrisiko,
- unklare Langzeitbedingungen,
- schwieriger automatisiert zu testen,
- unnötig, da nur statische URLs kodiert werden.

---

## 9. Verbindliche technische Entscheidung

### 9.1 Laufzeitabhängigkeiten

```text
qrcode 8.2
Pillow (über qrcode[pil])
PySide6 (bereits in der App)
```

### 9.2 Optionale Test-/QA-Abhängigkeit

```text
zxing-cpp 3.1.0
```

### 9.3 QR-Grundeinstellungen

```yaml
error_correction: H
border_modules: 4
module_style: square
foreground_color: "#000000"
background_color: "#FFFFFF"
output_format: png
output_width_px: 1000
output_height_px: 1000
logo_enabled: true
logo_max_width_percent: 18
logo_backplate_width_percent: 22
```

Keine runden Module, Farbverläufe oder dekorativen Finder Patterns im MVP. Lesbarkeit hat Vorrang.

---

## 10. Hauptdialog – UI-Konzept

Empfohlener Klassenname:

```python
QrCodeBatchDialog
```

Empfohlene Dialoggröße:

```text
ca. 1050 × 720 Pixel, frei skalierbar
```

### 10.1 Layout

```text
┌──────────────────────────────────────────────────────────────┐
│ Variante: [Ganze Skala ▼]          [Globale Einstellungen]  │
├───────────────────────────┬──────────────────────────────────┤
│ Eingaben                  │ Vorschau                         │
│                           │                                  │
│ Kürzel                     │ Tabelle:                         │
│ URL-Projekt-Slug           │ Nr. | ID | URL | Dateiname      │
│ Instrument                 │                                  │
│ Domain                     │                                  │
│ URL-Präfix                 │                                  │
│ Start / Ende / Schritt     │                                  │
│ Nummernbreite              │                                  │
│ Ausgabeordner              │                                  │
│ Logo                       │                                  │
├───────────────────────────┴──────────────────────────────────┤
│ 111 QR-Codes werden erzeugt.   [Abbrechen] [QR-Codes erzeugen]│
└──────────────────────────────────────────────────────────────┘
```

### 10.2 Variantenauswahl

`QComboBox` mit genau einer aktiven Variante:

```text
Ganze Skala
Gesamtspielchen
Ungerade Zahlen (Excel-Logik: 01–25)
Gerade Zahlen (Excel-Logik: 01, 03, …, 25)
Jede 4. Zahl
```

Die Auswahl steuert ein `QStackedWidget`:

- Seite A: numerische Serien,
- Seite B: tabellenbasierte Serie „Gesamtspielchen“.

### 10.3 Vorschautabelle

Empfohlen: `QTableView` mit eigenem `QAbstractTableModel`, nicht `QTableWidget`, wenn die bestehende App bereits Model/View verwendet.

Spalten:

1. laufender Index,
2. Nummer/Schlüssel,
3. logische ID,
4. Ziel-URL,
5. PNG-Dateiname,
6. Status/Warnung.

Funktionen:

- vollständige Live-Aktualisierung nach jeder Eingabe,
- Zeilen mit Fehlern rot bzw. mit Warnsymbol,
- URL per Doppelklick kopierbar,
- erste und letzte Zeile automatisch sichtbar,
- Anzeige der Gesamtanzahl.

---

## 11. Eingabefelder der Variante „Ganze Skala“

Die aktuellen Excel-Daten sollen nicht nur als grauer `placeholderText`, sondern als **echte Erststart-Standardwerte** verwendet werden. Nur so erzeugt ein unveränderter Dialog tatsächlich das Excel-Ergebnis.

| Feld | Widget | Erststartwert | Validierung |
|---|---|---|---|
| Kürzel | `QLineEdit` | `UUU#2` | nicht leer |
| URL-Projekt-Slug | `QLineEdit` | `uuu2` | URL-segmenttauglich |
| Instrument | editierbare `QComboBox` | `pos` | nicht leer, Kleinbuchstaben empfohlen |
| Instrumentvorschläge | Combo-Einträge | `trp`, `pos`, `ftb`, `btb`, `hrn` | keine leere Zeile |
| Domain | `QLineEdit` | `https://www.xeisworks.at` | gültige HTTPS-URL |
| Pfadvorlage | `QLineEdit` | `/mh-oa/{project_slug}/{instrument_slug}/` | muss unterstützte Platzhalter enthalten |
| URL-Präfix | `QLineEdit` | berechnet | standardmäßig read-only |
| manuelle URL | `QCheckBox` | aus | bei Aktivierung URL-Präfix editierbar |
| Start | `QSpinBox` | `1` | >= 0 |
| Ende | `QSpinBox` | `111` | >= Start |
| Schritt | `QSpinBox` | `1` | >= 1 |
| Mindestbreite | `QSpinBox` | `2` | 1–8 |
| ID-Muster | `QLineEdit` | `{series_code}-{instrument_upper}/{number}` | nur erlaubte Platzhalter |
| Trennzeichen | `QLineEdit` | `,` | maximal 1–3 Zeichen |
| Ausgabeordner | Pfadfeld + Button | zuletzt verwendet | vorhanden/schreibbar |

### 11.1 URL-Vorschau

Unter dem URL-Präfix:

```text
Beispiel: https://www.xeisworks.at/mh-oa/uuu2/pos/01
```

### 11.2 ID-Vorschau

```text
Beispiel: UUU#2-POS/01
Dateiname: UUU#2-POS_01.png
```

---

## 12. Eingaben der Variante „Gesamtspielchen“

### 12.1 Allgemeine Felder

| Feld | Erststartwert |
|---|---|
| Basis-Domain | `https://www.xeisworks.at` |
| Basispfad | `/dl-gesspiel/` |
| Trennzeichen | `,` |
| Ausgabeordner | zuletzt verwendet |

### 12.2 Editierbare Zeilentabelle

Spalten:

1. Aktiv,
2. Nummer,
3. Anzeigename,
4. URL-Slug,
5. logische ID/Bezeichnung,
6. URL,
7. Dateiname.

Buttons:

- Zeile hinzufügen,
- Zeile duplizieren,
- Zeile löschen,
- Reihenfolge nach oben/unten,
- Excel-Standard wiederherstellen.

Die zwölf Excel-Zeilen werden als Preset geladen. Änderungen gelten zunächst nur für den aktuellen Lauf. Optional kann später ein benutzerdefiniertes Preset gespeichert werden.

---

## 13. Numerische Varianten – generische Serienlogik

Alle numerischen Varianten sollen dieselbe Engine verwenden.

### 13.1 Datenmodell

```python
@dataclass(frozen=True)
class NumericSequenceSpec:
    start: int
    end: int
    step: int
    minimum_width: int = 2
    number_suffix: str = ""
```

### 13.2 Generator

```python
def generate_numbers(spec: NumericSequenceSpec) -> list[str]:
    if spec.step <= 0:
        raise ValueError("step must be greater than zero")
    if spec.end < spec.start:
        raise ValueError("end must not be smaller than start")

    return [
        f"{number:0{spec.minimum_width}d}{spec.number_suffix}"
        for number in range(spec.start, spec.end + 1, spec.step)
    ]
```

### 13.3 Presetwerte

```python
WHOLE_SCALE = NumericSequenceSpec(1, 111, 1, 2, "")
ODD_REGISTER_LEGACY = NumericSequenceSpec(1, 25, 1, 2, "d")
EVEN_REGISTER_LEGACY = NumericSequenceSpec(1, 25, 2, 2, "d")
EVERY_FOURTH = NumericSequenceSpec(4, 24, 4, 2, "d")
```

Die internen Konstantennamen dürfen nicht behaupten, dass die tatsächliche Zahlenfolge gerade ist. Daher wird für das Excel-Register „Gerade Zahlen“ intern bewusst `EVEN_REGISTER_LEGACY` oder besser `GERADE_ZAHLEN_EXCEL_PRESET` verwendet und der tatsächliche `step=2, start=1` in Tests festgeschrieben.

---

## 14. Preset-Datenmodell

Empfohlen:

```python
class QrVariantType(StrEnum):
    WHOLE_SCALE = "whole_scale"
    GESAMTSPIELCHEN = "gesamtspielchen"
    UNGERADE_EXCEL = "ungerade_excel"
    GERADE_EXCEL = "gerade_excel"
    EVERY_FOURTH = "every_fourth"
```

```python
@dataclass(frozen=True)
class QrVariantPreset:
    key: QrVariantType
    display_name: str
    generation_mode: Literal["numeric", "table"]
    sequence: NumericSequenceSpec | None
    base_domain: str
    base_path: str
    id_template: str
    default_series_code: str = ""
    default_project_slug: str = ""
    default_instrument_slug: str = ""
    id_suffix: str = ""
```

### 14.1 Presetdefinitionen

```python
PRESETS = {
    QrVariantType.WHOLE_SCALE: QrVariantPreset(
        key=QrVariantType.WHOLE_SCALE,
        display_name="Ganze Skala",
        generation_mode="numeric",
        sequence=NumericSequenceSpec(1, 111, 1, 2),
        base_domain="https://www.xeisworks.at",
        base_path="/mh-oa/{project_slug}/{instrument_slug}/",
        id_template="{series_code}-{instrument_upper}/{number}",
        default_series_code="UUU#2",
        default_project_slug="uuu2",
        default_instrument_slug="pos",
    ),
    # weitere Presets analog
}
```

Presets sind unveränderliche Programmstandards. Benutzereingaben werden in einen separaten `QrBatchRequest` kopiert.

---

## 15. Laufzeit-Datenmodelle

```python
@dataclass(frozen=True)
class QrRecord:
    ordinal: int
    source_key: str
    logical_id: str
    payload_url: str
    output_filename: str
```

```python
@dataclass(frozen=True)
class QrRenderSettings:
    width_px: int = 1000
    height_px: int = 1000
    output_format: str = "png"
    error_correction: str = "H"
    border_modules: int = 4
    foreground_color: str = "#000000"
    background_color: str = "#FFFFFF"
    logo_enabled: bool = True
    logo_path: Path | None = None
    logo_max_width_percent: float = 18.0
    logo_backplate_width_percent: float = 22.0
```

```python
@dataclass(frozen=True)
class QrBatchRequest:
    variant: QrVariantType
    records: tuple[QrRecord, ...]
    output_directory: Path
    render_settings: QrRenderSettings
    collision_policy: Literal["abort", "overwrite", "rename"] = "abort"
```

```python
@dataclass(frozen=True)
class QrGenerationResult:
    record: QrRecord
    output_path: Path | None
    success: bool
    decoded_payload: str | None
    error_message: str | None
```

---

## 16. Dateinamenbereinigung

### 16.1 Regeln

Unter Windows unzulässige Zeichen:

```text
< > : " / \ | ? *
```

Zusätzlich:

- abschließende Punkte entfernen,
- abschließende Leerzeichen entfernen,
- reservierte Namen berücksichtigen: `CON`, `PRN`, `AUX`, `NUL`, `COM1` … `COM9`, `LPT1` … `LPT9`,
- Dateiname darf nach Bereinigung nicht leer sein,
- Erweiterung `.png` nur einmal anhängen.

### 16.2 Empfohlene Funktion

```python
WINDOWS_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_windows_filename(value: str, replacement: str = "_") -> str:
    cleaned = WINDOWS_INVALID_FILENAME_CHARS.sub(replacement, value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"_+", "_", cleaned)

    if not cleaned:
        raise ValueError("The filename is empty after sanitizing")

    stem_upper = cleaned.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update({f"COM{i}" for i in range(1, 10)})
    reserved.update({f"LPT{i}" for i in range(1, 10)})
    if stem_upper in reserved:
        cleaned = f"_{cleaned}"

    return cleaned
```

Beispiel:

```text
UUU#2-POS/01 -> UUU#2-POS_01.png
```

---

## 17. Globale QR-Einstellungen

Empfohlene Klasse:

```python
QrSettingsRepository
```

### 17.1 Speichertechnik

`QSettings` verwenden. Vor der Implementierung muss geprüft werden, ob die App bereits eine zentrale QSettings-Instanz oder einen Settings-Service besitzt. Dieser ist wiederzuverwenden.

Keine neue Organisation/Application-ID erfinden, wenn bereits vorhanden.

### 17.2 Schlüsselnamespace

```text
qr_codes/render/width_px
qr_codes/render/height_px
qr_codes/render/output_format
qr_codes/render/error_correction
qr_codes/render/border_modules
qr_codes/render/foreground_color
qr_codes/render/background_color
qr_codes/logo/enabled
qr_codes/logo/path
qr_codes/logo/max_width_percent
qr_codes/logo/backplate_width_percent
qr_codes/output/last_directory
qr_codes/output/collision_policy
qr_codes/quality/verify_after_generation
```

### 17.3 Erststartwerte

```yaml
qr_codes:
  render:
    width_px: 1000
    height_px: 1000
    output_format: png
    error_correction: H
    border_modules: 4
    foreground_color: "#000000"
    background_color: "#FFFFFF"
  logo:
    enabled: true
    path: "C:\\Users\\XeisWorks\\OneDrive - XeisWorks\\02 XeisWorks\\16 QR Codes\\musikheroes_qr.png"
    max_width_percent: 18.0
    backplate_width_percent: 22.0
  output:
    collision_policy: abort
  quality:
    verify_after_generation: false
```

### 17.4 Einstellungsdialog

Felder:

- Breite in Pixeln,
- Höhe in Pixeln,
- Ausgabeformat: `PNG` – in Version 1 einziger Eintrag,
- Logo verwenden,
- Logo-Pfad + Dateiauswahl,
- Logo-Vorschau,
- erweiterbar: Logobreite in Prozent,
- hohe Fehlerkorrektur: fest auf H oder als read-only Info,
- QR-Rand: standardmäßig vier Module,
- Rückleseprüfung nach Erzeugung: optional.

Buttons:

```text
[Auf Standard zurücksetzen] [Abbrechen] [Speichern]
```

---

## 18. Logo-Verarbeitung

### 18.1 Anforderungen

- PNG, JPG und WebP dürfen als Eingabelogo akzeptiert werden.
- Transparenz muss erhalten bleiben.
- Seitenverhältnis darf nicht verändert werden.
- Das Logo muss mittig stehen.
- Das Logo darf nicht bis zu den Finder Patterns oder zum ruhigen Rand reichen.
- Hinter dem Logo wird eine weiße, quadratische oder leicht abgerundete Fläche eingefügt.
- Die QR-Datei bleibt immer PNG.

### 18.2 Standardgrößen

Empfehlung:

```text
Logo-Inhalt: maximal 18 % der gerenderten QR-Symbolbreite
weiße Hintergrundfläche: 22 % der QR-Symbolbreite
```

Die 30-%-Fehlerkorrektur von Level H bedeutet nicht, dass gefahrlos 30 % der sichtbaren Fläche abgedeckt werden dürfen. Fehlerkorrektur bezieht sich auf Codewörter und nicht auf eine beliebige zusammenhängende Fläche. Deshalb wird konservativ dimensioniert.

### 18.3 Fehlender Logo-Pfad

Wenn `logo_enabled = true` und die Datei fehlt oder nicht lesbar ist:

1. Vorabprüfung schlägt fehl.
2. Der Dialog zeigt eine verständliche Meldung.
3. Buttons:

```text
[Logo auswählen] [Ohne Logo erzeugen] [Abbrechen]
```

„Ohne Logo erzeugen“ gilt nur für den aktuellen Lauf und ändert die globale Einstellung nicht automatisch.

---

## 19. Exakte 1000 × 1000-Pixel-Ausgabe

QR-Codes bestehen aus diskreten Modulen. Ein QR-Code darf nicht mit bilinearer oder bikubischer Interpolation auf 1000 Pixel verzerrt werden.

### 19.1 Empfohlener Algorithmus

1. QR-Matrix mit automatischer Version und Fehlerkorrektur H erzeugen.
2. Vier Module Quiet Zone integrieren.
3. Anzahl der Matrixmodule bestimmen.
4. Ganzzahlige Modulgröße berechnen:

```python
module_px = min(width_px, height_px) // module_count
```

5. Tatsächliche Symbolgröße:

```python
symbol_size = module_count * module_px
```

6. Symbol auf einer exakt 1000 × 1000 Pixel großen weißen Fläche zentrieren.
7. Module ohne Antialiasing als schwarze Rechtecke zeichnen.
8. Logo-Backplate und Logo mittig darüberlegen.
9. PNG speichern.

### 19.2 Beispiel mit aktueller erster URL

Für:

```text
https://www.xeisworks.at/mh-oa/uuu2/pos/01
```

ergab ein technischer Prototyp:

```text
Matrix inklusive Rand: 45 × 45 Module
Modulgröße:            22 Pixel
QR-Symbol:             990 × 990 Pixel
Endbild:                1000 × 1000 Pixel
Außenrest:              5 Pixel je Seite
Rücklesetest:           erfolgreich
```

Dieser Ansatz garantiert ein exakt 1000 × 1000 Pixel großes Bild ohne unscharfe Modulgrenzen.

---

## 20. QR-Renderer-Service

Empfohlene Datei:

```text
services/qr_code_renderer.py
```

### 20.1 Schnittstelle

```python
class QrCodeRenderer(Protocol):
    def render(
        self,
        payload: str,
        settings: QrRenderSettings,
    ) -> Image.Image:
        ...
```

### 20.2 Konkrete Implementierung

```python
class PillowQrCodeRenderer:
    def render(self, payload: str, settings: QrRenderSettings) -> Image.Image:
        self._validate_payload(payload)
        self._validate_settings(settings)

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=1,
            border=settings.border_modules,
        )
        qr.add_data(payload)
        qr.make(fit=True)

        matrix = qr.get_matrix()
        image = self._render_matrix_exact_size(matrix, settings)

        if settings.logo_enabled:
            image = self._composite_logo(image, settings)

        return image
```

### 20.3 Wichtige Vorgaben

- Keine Wiederverwendung eines QRCode-Objekts über mehrere Datensätze, außer es wird zuverlässig `clear()` aufgerufen.
- Pro Datensatz deterministisches Ergebnis.
- Keine Netzwerkaufrufe.
- Keine temporären Dateien für das Logo nötig.
- Eingabelogo möglichst einmal pro Batch laden und zwischenspeichern.

---

## 21. Batch-Erzeugung und UI-Responsivität

Bei 111 PNG-Dateien darf die UI nicht blockieren.

### 21.1 Worker-Strategie

Bevorzugt:

- bestehendes Worker-/Task-System der App wiederverwenden,
- andernfalls `QThreadPool` + `QRunnable` oder ein dedizierter `QThread`.

### 21.2 Signale

```python
progress_changed(current: int, total: int, logical_id: str)
record_finished(result: QrGenerationResult)
batch_finished(summary: QrBatchSummary)
batch_failed(message: str)
cancelled()
```

### 21.3 Fortschrittsdialog

```text
QR-Codes werden erzeugt …
47 von 111
UUU#2-POS/47
[██████████████░░░░░░░░░░]
[Abbrechen]
```

Abbrechen:

- beendet nach dem aktuell gerenderten Datensatz,
- löscht bereits erzeugte Dateien nicht automatisch,
- Abschlussmeldung listet Teilresultat,
- optionaler Button „bereits erzeugte Dateien löschen“.

---

## 22. Ausgabeordner und Kollisionsverhalten

### 22.1 Empfohlener Ausgabeordner

Der Benutzer wählt den Ordner pro Lauf. Der letzte Ordner wird global gespeichert.

Optionaler Vorschlagsname für einen automatisch erzeugten Unterordner:

```text
QR_UUU#2_POS_2026-07-28_163000
```

Die AI-Extension soll nicht ohne Benutzerentscheidung automatisch in den Logo-Ordner schreiben.

### 22.2 Vorabprüfung

Vor dem Start:

- Ausgabeordner existiert oder kann angelegt werden,
- Schreibtest durchführen,
- alle endgültigen Dateipfade berechnen,
- doppelte Dateinamen innerhalb des Batches erkennen,
- vorhandene Dateien erkennen.

### 22.3 Kollisionsoptionen

```text
Abbrechen und nichts erzeugen        – Standard
Vorhandene Dateien überschreiben
Automatisch neue Dateinamen vergeben – z. B. _2, _3
```

Die Auswahl kann global gespeichert werden, muss aber vor jedem Batch in einer Zusammenfassung sichtbar sein.

---

## 23. Manifest und Protokoll

Obwohl in Version 1 nur PNG als Bildformat verlangt ist, sollte zusätzlich ein maschinenlesbares Manifest erzeugt werden. Dies ersetzt funktional die Excel-Spalte `QR_Code BULK-IMPORT` und erleichtert Nachvollziehbarkeit.

Empfohlene Datei:

```text
qr_manifest.csv
```

Spalten:

```text
ordinal;source_key;logical_id;payload_url;output_filename;status;error
```

Für österreichische Excel-Installationen ist Semikolon als CSV-Trenner oft praktischer. Die QR-ID/URL-Bulkzeile mit Komma kann zusätzlich in einer Spalte `legacy_bulk_line` erhalten bleiben.

Alternativ oder zusätzlich:

```text
qr_manifest.json
```

Das Manifest ist eine Phase-2-Funktion, aber die Datenmodelle sollen bereits darauf vorbereitet sein.

---

## 24. Eingabevalidierung

### 24.1 URL

- Schema muss `https` sein; `http` nur nach ausdrücklicher Warnung.
- Host muss vorhanden sein.
- keine Zeilenumbrüche,
- keine unbeabsichtigten Leerzeichen,
- Pfadsegmente korrekt URL-encoden, jedoch vorhandene `/` nicht als `%2F` kodieren.

### 24.2 Kürzel und Slugs

- `series_code`: beliebiger sichtbarer Text, aber keine Steuerzeichen,
- `project_slug`: `[a-z0-9-]+`, optional Unterstrich falls tatsächlich benötigt,
- `instrument_slug`: `[a-z0-9-]+`,
- Anzeigenamen dürfen Umlaute und Leerzeichen enthalten.

### 24.3 Zahlenbereich

- `end >= start`,
- `step >= 1`,
- resultierende Anzahl > 0,
- Warnung ab z. B. 1000 Datensätzen,
- harte Sicherheitsgrenze optional 10.000 Datensätze.

### 24.4 Templates

Erlaubte Platzhalter:

```text
{series_code}
{project_slug}
{instrument_slug}
{instrument_upper}
{number}
{number_raw}
{number_suffix}
{id_suffix}
{name}
{slug}
{ordinal}
```

Unbekannte Platzhalter führen zu einem Validierungsfehler, nicht zu einem Python-Traceback.

### 24.5 Logo

- Datei existiert,
- lesbares Bildformat,
- Breite und Höhe > 0,
- keine extrem große Bilddatei ohne Warnung,
- beim Laden `Image.verify()` bzw. kontrolliertes Öffnen verwenden.

---

## 25. Fehlerbehandlung

Benutzerfreundliche Fehlertypen:

```python
class QrModuleError(Exception): ...
class QrConfigurationError(QrModuleError): ...
class QrPresetError(QrModuleError): ...
class QrRenderError(QrModuleError): ...
class QrOutputError(QrModuleError): ...
class QrVerificationError(QrModuleError): ...
```

Keine rohen Tracebacks im Dialog. Traceback ins bestehende App-Log schreiben.

Beispielmeldung:

```text
Der QR-Code „UUU#2-POS/37“ konnte nicht gespeichert werden.

Datei:
C:\...\UUU#2-POS_37.png

Grund:
Der Ausgabeordner ist schreibgeschützt.
```

Batchverhalten:

- Standard: Fehler bei einem Datensatz protokollieren und mit nächstem fortfahren,
- bei strukturellem Fehler wie ungültigem Ausgabeordner: Batch vollständig abbrechen,
- Abschlussübersicht: erfolgreich / fehlgeschlagen / übersprungen.

---

## 26. Qualitätsprüfung durch Rücklesen

### 26.1 Option A – ohne zusätzliche Laufzeitabhängigkeit

- Unit- und Integrationstests verwenden lokal verfügbaren Decoder.
- Produktions-App zeigt keine automatische Verifikation.

### 26.2 Option B – optionale ZXing-C++-Prüfung

Nach dem Speichern:

1. PNG mit ZXing-C++ öffnen,
2. QR-Code dekodieren,
3. dekodierten Inhalt mit `payload_url` vergleichen,
4. bei Abweichung Datei als fehlgeschlagen markieren.

Empfehlung:

- in Entwicklung und CI aktiv,
- in Produktion als globale Option,
- nicht zwingend für MVP, um Deployment einfach zu halten.

### 26.3 Stichprobenmodus

Für große Batches optional:

```text
erste Datei
mittlere Datei
letzte Datei
plus 5 zufällige Dateien
```

Für die hohe Sicherheit des Logos ist eine Prüfung jeder Datei besser, aber langsamer.

---

## 27. Vorgeschlagene Projektstruktur

Die tatsächlichen Pfade müssen an das Repository angepasst werden.

```text
src/
└── app/
    ├── qr_codes/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── presets.py
    │   ├── sequence_generator.py
    │   ├── record_builder.py
    │   ├── filename_sanitizer.py
    │   ├── qr_code_renderer.py
    │   ├── batch_generator.py
    │   ├── verifier.py
    │   ├── settings_repository.py
    │   ├── manifest_writer.py
    │   └── ui/
    │       ├── qr_batch_dialog.py
    │       ├── qr_settings_dialog.py
    │       ├── qr_preview_model.py
    │       ├── gesamtspielchen_table_model.py
    │       └── qr_progress_dialog.py
    └── ...

tests/
└── qr_codes/
    ├── test_presets.py
    ├── test_sequence_generator.py
    ├── test_record_builder.py
    ├── test_filename_sanitizer.py
    ├── test_qr_code_renderer.py
    ├── test_settings_repository.py
    ├── test_batch_generator.py
    └── test_excel_compatibility.py
```

Falls das Repository bereits eine Feature-/Module-Struktur besitzt, soll die AI-Extension diese übernehmen.

---

## 28. Record Builder

Der Record Builder wandelt Benutzerfelder und Preset in konkrete Datensätze um. Er enthält keine UI-Logik und erzeugt keine Bilder.

```python
class QrRecordBuilder:
    def build_numeric_records(
        self,
        preset: QrVariantPreset,
        form: NumericQrFormData,
    ) -> tuple[QrRecord, ...]:
        ...

    def build_table_records(
        self,
        preset: QrVariantPreset,
        rows: Sequence[TableQrRow],
    ) -> tuple[QrRecord, ...]:
        ...
```

### 28.1 Ganze-Skala-Beispiel

```python
number = "01"
logical_id = "UUU#2-POS/01"
payload_url = "https://www.xeisworks.at/mh-oa/uuu2/pos/01"
output_filename = "UUU#2-POS_01.png"
```

### 28.2 Keine Stringverkettung im UI-Code

Die Dialogklasse darf nicht selbst URLs mit `+` oder f-Strings zusammenbauen. Das ist ausschließlich Aufgabe von `QrRecordBuilder` und Template-Funktionen.

---

## 29. Live-Vorschau und Debouncing

Bei jeder Eingabeänderung wird die Vorschau aktualisiert. Um unnötige Neuberechnung zu vermeiden:

- `QTimer` als Debounce, ca. 150–250 ms,
- bei tabellenbasierten Varianten sofortige Aktualisierung der betroffenen Zeile,
- keine QR-Bilder für alle 111 Vorschauzeilen rendern,
- nur Textdaten live berechnen.

Optional wird für die aktuell markierte Zeile rechts unten ein kleines QR-Vorschaubild erzeugt, z. B. 260 × 260 Pixel. Dieses Vorschaubild darf aus Performancegründen verzögert erzeugt werden.

---

## 30. Persistenz der Formulardaten

Der Benutzer hat globale QR-Grafikeinstellungen verlangt. Die inhaltlichen Serienfelder sollten vorsichtig behandelt werden.

Empfehlung:

- globale Grafiksettings dauerhaft speichern,
- letzter Ausgabeordner dauerhaft speichern,
- letzte Variante optional speichern,
- zuletzt eingegebene Serienwerte optional unter `qr_codes/forms/{variant}/...` speichern,
- Button **„Excel-Standardwerte laden“** bereitstellen.

Wichtig: Preset-Defaults dürfen nicht durch letzte Benutzereingaben überschrieben werden. Es muss jederzeit möglich sein, den dokumentierten Excel-Zustand wiederherzustellen.

---

## 31. Unit-Tests – zwingende Excel-Kompatibilität

### 31.1 Ganze Skala

```python
def test_whole_scale_matches_excel_defaults():
    records = build_whole_scale_default_records()

    assert len(records) == 111
    assert records[0].logical_id == "UUU#2-POS/01"
    assert records[0].payload_url == "https://www.xeisworks.at/mh-oa/uuu2/pos/01"
    assert records[0].output_filename == "UUU#2-POS_01.png"

    assert records[-1].logical_id == "UUU#2-POS/111"
    assert records[-1].payload_url == "https://www.xeisworks.at/mh-oa/uuu2/pos/111"
```

### 31.2 Gesamtspielchen

```python
assert len(records) == 12
assert records[0].logical_id == "01 Euphonium"
assert records[0].payload_url == "https://www.xeisworks.at/dl-gesspiel/euph"
assert records[-1].logical_id == "12 Trompete + Flügelhorn"
assert records[-1].payload_url == "https://www.xeisworks.at/dl-gesspiel/trp"
```

### 31.3 Ungerade Zahlen – Excel-Logik

```python
assert len(records) == 25
assert records[0].logical_id == "01d-LOESUNG"
assert records[-1].logical_id == "25d-LOESUNG"
```

### 31.4 Gerade Zahlen – Excel-Logik

```python
expected = [f"{n:02d}d-CHECK" for n in range(1, 26, 2)]
assert [r.logical_id for r in records] == expected
assert len(records) == 13
```

### 31.5 Jede 4. Zahl

```python
expected = ["04d-CLIP", "08d-CLIP", "12d-CLIP", "16d-CLIP", "20d-CLIP", "24d-CLIP"]
assert [r.logical_id for r in records] == expected
```

---

## 32. Renderer-Tests

Zwingende Tests:

1. Ausgabe ist exakt `1000 × 1000` Pixel.
2. Ausgabeformat ist PNG.
3. QR-Code ohne Logo ist dekodierbar.
4. QR-Code mit Standard-Logoproportion ist dekodierbar.
5. Transparente Logos funktionieren.
6. Hochformat- und Querformatlogos behalten Seitenverhältnis.
7. Quiet Zone bleibt weiß.
8. Keine Interpolation an QR-Modulen.
9. URL mit `#`, `?`, `&`, Umlauten im Pfad bzw. URL-Encoding wird korrekt kodiert.
10. Fehlendes Logo erzeugt eine kontrollierte Fehlermeldung.

Optionaler Golden-Master-Test:

- Hash nicht auf das gesamte PNG festnageln, da Kompression variieren kann.
- Stattdessen Matrix, Bildgröße, Eckpixel, Logo-Box und Dekodierergebnis prüfen.

---

## 33. UI-Tests

Mindestens:

- Menüaktion öffnet Dialog,
- genau eine Variante auswählbar,
- Wechsel der Variante tauscht Felder korrekt,
- Standardwerte von Ganze Skala sind korrekt,
- Vorschau zeigt 111 Zeilen,
- falscher URL-Slug blockiert Erzeugung,
- fehlender Ausgabeordner blockiert Erzeugung,
- Einstellungen werden gespeichert und erneut geladen,
- Reset stellt 1000 × 1000, PNG und Standardlogo wieder her,
- Abbruch eines Batches friert UI nicht ein.

---

## 34. Implementierungsphasen für die VS-Code-AI-Extension

### Phase 0 – Repository verstehen

Die AI-Extension muss vor Codeänderungen:

1. App-Einstiegspunkt finden.
2. bestehende Menüerstellung finden.
3. vorhandene Dialog- und Widget-Konventionen analysieren.
4. bestehendes Settings-System finden.
5. Logging-System finden.
6. vorhandene Worker-/Thread-Klassen finden.
7. Dependency-Management bestimmen: `requirements.txt`, Poetry, uv oder anderes.
8. Testframework und Teststruktur bestimmen.
9. bestehende Pfad-/Dateidialog-Helfer suchen.
10. keine neue Parallelarchitektur erstellen.

Ergebnis dieser Phase als kurze technische Notiz im PR/Commit dokumentieren.

### Phase 1 – Domänenlogik ohne UI

Implementieren:

- Datenmodelle,
- Presets,
- Zahlenfolgegenerator,
- Record Builder,
- Dateinamenbereinigung,
- Tests für exakte Excel-Kompatibilität.

Definition of Done:

- alle fünf angeforderten Varianten liefern exakt die dokumentierten Datensätze,
- keine PySide6-Abhängigkeit in der Domänenlogik.

### Phase 2 – Renderer

Implementieren:

- `qrcode 8.2 + Pillow`,
- Fehlerkorrektur H,
- exakte Pixelgröße,
- Mittellogo,
- weiße Logo-Backplate,
- PNG-Speicherung,
- Renderer-Tests.

Definition of Done:

- erste Ganze-Skala-URL kann mit Logo in 1000 × 1000 erzeugt und zurückgelesen werden.

### Phase 3 – Settings

Implementieren:

- globales Settings Repository,
- Standardwerte,
- Einstellungsdialog,
- Logo-Dateiauswahl und Vorschau,
- Reset auf Standard.

### Phase 4 – Hauptdialog und Vorschau

Implementieren:

- Variantenauswahl,
- `QStackedWidget`,
- Felder für numerische Varianten,
- editierbare Gesamtspielchen-Tabelle,
- Live-Vorschau,
- Validierungsstatus,
- Ausgabeordnerauswahl.

### Phase 5 – Batch-Worker

Implementieren:

- Hintergrundausführung,
- Fortschritt,
- Abbruch,
- Kollisionsprüfung,
- Abschlussübersicht,
- optional Manifest.

### Phase 6 – Menüintegration

Implementieren:

- Untermenü,
- Aktionen,
- Icons nur aus bestehendem Icon-System,
- zuletzt verwendeten Ausgabeordner öffnen.

### Phase 7 – Qualität und Dokumentation

- vollständige Tests,
- manuelle Scanner-Stichprobe mit mehreren Smartphones,
- README-/Benutzerhilfe,
- Dependency-Lizenzen dokumentieren,
- keine ungenutzten Excel-Laufzeitabhängigkeiten.

---

## 35. Konkreter Arbeitsauftrag für Codex/Copilot/Claude Code

Der folgende Block kann als Startauftrag verwendet werden:

```text
Implementiere in der bestehenden PySide6-App ein neues Untermenü „QR-Codes“ gemäß der Datei
QR_Code_Untermenue_PySide6_Spezifikation.md.

Arbeite in klar getrennten Phasen:
1. Analysiere zuerst die vorhandene App-Architektur, Menüstruktur, Settings, Logging,
   Threading und Tests. Verwende bestehende Muster und baue keine parallelen Systeme.
2. Implementiere zunächst ausschließlich die UI-unabhängige Domänenlogik und Tests.
3. Reproduziere die Excel-Defaults exakt, einschließlich der historisch widersprüchlichen
   Sequenzen der Register „Ungerade Zahlen“ und „Gerade Zahlen“. Korrigiere oder benenne
   diese nicht stillschweigend um.
4. Verwende qrcode[pil] 8.2 und Pillow. Erzeuge QR-Codes vollständig offline mit
   ERROR_CORRECT_H, vier Modulen Quiet Zone, quadratischen Modulen und einem standardmäßig
   aktivierten Mittellogo.
5. Die PNG-Ausgabe muss exakt 1000 × 1000 Pixel groß sein, ohne geglättetes Skalieren der
   QR-Module. Rendere mit ganzzahliger Modulgröße auf eine exakte Ziel-Canvas.
6. Trenne logical_id, payload_url und output_filename. Bereinige nur Dateinamen für Windows.
7. Verwende QSettings beziehungsweise den vorhandenen Settings-Service für globale
   Grafiksettings.
8. Erzeuge einen responsiven Batch-Workflow mit Fortschritt und Abbruch.
9. Liefere Tests, die erste/letzte Datensätze und Anzahl aller fünf Varianten exakt prüfen.
10. Zeige mir nach jeder Phase die geänderten Dateien, Tests und noch offenen Punkte.

Ändere keine fachfremden Teile der App. Erstelle keine Online-API-Abhängigkeit.
```

---

## 36. Abnahmekriterien

Die Funktion ist abnahmefähig, wenn:

- [ ] Das QR-Untermenü ist in der bestehenden App sichtbar.
- [ ] Pro Lauf ist genau eine Variante aktiv.
- [ ] Ganze Skala lädt beim Erststart `UUU#2`, `uuu2`, `pos`, Start 1, Ende 111.
- [ ] Die Vorschau erzeugt exakt 111 Zeilen.
- [ ] Erste URL ist `https://www.xeisworks.at/mh-oa/uuu2/pos/01`.
- [ ] Letzte URL ist `https://www.xeisworks.at/mh-oa/uuu2/pos/111`.
- [ ] Logische IDs behalten `/`; PNG-Dateinamen ersetzen `/` sicher.
- [ ] Gesamtspielchen enthält die zwölf Excel-Instrumente.
- [ ] Die beiden widersprüchlich benannten Excel-Varianten werden exakt reproduziert und klar gekennzeichnet.
- [ ] Jede-4.-Zahl erzeugt genau sechs Datensätze.
- [ ] PNG-Dateien sind exakt 1000 × 1000 Pixel.
- [ ] Standardlogo ist aktiv und der Pfad ist änderbar.
- [ ] Fehlendes Logo wird kontrolliert behandelt.
- [ ] QR-Codes verwenden Fehlerkorrektur H und vier Module Rand.
- [ ] Batch-Erzeugung blockiert die UI nicht.
- [ ] Fortschritt und Abbruch funktionieren.
- [ ] Vorhandene Dateien werden vorab erkannt.
- [ ] Globale Einstellungen bleiben nach App-Neustart erhalten.
- [ ] Alle Excel-Kompatibilitätstests bestehen.
- [ ] Mindestens erste, mittlere und letzte Datei sind mit einem echten Scanner lesbar.

---

## 37. Bewusste Nicht-Ziele des MVP

Nicht Teil der ersten Version:

- dynamische/trackbare QR-Codes,
- externer URL-Shortener,
- Online-QR-API,
- SVG-, PDF- oder EPS-Ausgabe,
- frei gestaltete QR-Eyes oder Farbverläufe,
- vollständige JMLA-/WIX-CMS-Integration,
- Cloud-Synchronisierung von Presets,
- automatische Veröffentlichung auf Wix,
- direkte Druckbogenmontage.

Diese Funktionen dürfen die Architektur nicht verhindern, sollen aber nicht den MVP verzögern.

---

## 38. Empfohlene spätere Erweiterungen

1. Benutzerdefinierte Presets speichern.
2. JMLA als tabellenbasiertes Preset integrieren.
3. CSV/Excel-Import beliebiger ID-/URL-Paare.
4. QR-Bögen für A4/A3 erzeugen.
5. SVG-Ausgabe für professionellen Druck.
6. direkte Wix-CMS-Verknüpfung.
7. automatische URL-Erreichbarkeitsprüfung vor der Erzeugung.
8. Scan-Verifikation jeder PNG-Datei.
9. ZIP-Paket aus Batch und Manifest.
10. Historie früherer Erzeugungsläufe.

---

## 39. Quellen der Bibliotheksrecherche

- Python `qrcode` auf PyPI:  
  https://pypi.org/project/qrcode/
- `python-qrcode` GitHub-Repository und Dokumentation:  
  https://github.com/lincolnloop/python-qrcode
- Segno auf PyPI:  
  https://pypi.org/project/segno/
- Segno-Dokumentation zur Erzeugung und Fehlerkorrektur:  
  https://segno.readthedocs.io/en/latest/make.html
- ZXing-C++ Python Bindings auf PyPI:  
  https://pypi.org/project/zxing-cpp/
- ZXing-C++ GitHub-Repository:  
  https://github.com/zxing-cpp/zxing-cpp
- DENSO WAVE QR-Code-Informationsseite:  
  https://www.qrcode.com/en/

---

## 40. Schlussentscheidung

Für die bestehende PySide6-App ist folgende Kombination die beste Lösung:

```text
Generator:          qrcode 8.2
Bildverarbeitung:   Pillow
Fehlerkorrektur:    H
Mittellogo:         manuell kontrolliertes Pillow-Compositing
Ausgabe:             PNG, exakt 1000 × 1000 Pixel
Settings:            bestehender App-Settings-Service bzw. QSettings
Qualitätsprüfung:    optional ZXing-C++
```

Die Excel-Datei soll nach der Integration nicht mehr für die tägliche QR-Erzeugung benötigt werden. Sie bleibt Referenz für Presetwerte und Kompatibilitätstests.
