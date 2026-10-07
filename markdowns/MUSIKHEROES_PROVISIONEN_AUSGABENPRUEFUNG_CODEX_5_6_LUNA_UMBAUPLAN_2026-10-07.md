# MusikHeroes-Provisionen und Ausgabenprüfung — Umbauplan für Codex 5.6 Luna

**Stand:** 2026-10-07  
**Primärrepo:** `XeisWorks/XW-Office`  
**Analysiertes Legacy-Repo:** `XeisWorks/sevDesk` (nur lesend)  
**Baseline XW-Office:** `5b29369d36d3b1f40eef716d52ef3b2f651e84d9`  
**Zielplattform:** PySide6  
**Architekturstatus:** fachliche Entscheidungen bestätigt; Umsetzung noch offen

## 0. Zweck und Arbeitsauftrag

Dieses Dokument ist der operative Umbauplan für Codex 5.6 Luna. Es verbindet drei Vorhaben, die fachlich dieselben sevDesk-Bank- und Belegverknüpfungen benötigen:

1. die korrekte und kompakte MusikHeroes-Provisionsabrechnung;
2. einen zentralen Finanzbereich **Ausgabenprüfung**;
3. die spätere Integration von **Fehlende Belege**.

Die Umsetzung erfolgt in kleinen, getesteten Paketen. Luna darf nicht den gesamten Umbau in einem Lauf durchführen. Pro Lauf ist genau das im jeweiligen Paket beschriebene Ergebnis umzusetzen und zu prüfen.

Dieses Dokument verändert nicht das geschützte Architekturarchiv `markdowns/XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md`.

## 1. Verbindliche fachliche Entscheidungen

### 1.1 Provisionslogik

Für jede SKU und analog für Kategorie- und Gesamtsummen gilt:

- **Menge:** verkaufte Menge aus normalen Rechnungen minus Menge aus Stornorechnungen.
- **Netto:** Nettoerlös aus normalen Rechnungen minus Netto aus der dem Storno zugeordneten Gutschrift.
- **Brutto:** Bruttoerlös aus normalen Rechnungen minus Brutto aus der zugeordneten Gutschrift.
- Eine Gutschrift ist kein zusätzlicher Retourenfall, sondern der finanzielle Teil genau eines Stornovorgangs.
- Die Stornorechnung reduziert die Menge, aber nicht zusätzlich den Betrag.
- Die Gutschrift reduziert den Betrag, aber nicht zusätzlich die Menge.
- Ein Storno-Gutschrift-Paar darf in keiner Summe doppelt wirken.

Damit lautet das fachliche Modell für ein Produkt:

```text
Menge = Summe(RE-Mengen) - Summe(SR-Mengen aus eindeutigen Korrekturpaaren)
Netto = Summe(RE-Netto)  - Summe(GU-Netto aus denselben eindeutigen Korrekturpaaren)
Brutto = Summe(RE-Brutto) - Summe(GU-Brutto aus denselben eindeutigen Korrekturpaaren)
```

`RE` bezeichnet normale Rechnungen, `SR` Stornorechnungen und `GU` Gutschriften.

Diese Logik gilt identisch für:

- die sichtbare Produktliste;
- die Kategorietabelle;
- die Kopieransicht;
- CSV;
- XLSX;
- Kopf-/Gesamtsummen.

Es darf nicht je Export ein eigener Rechenweg entstehen. Alle Darstellungen konsumieren dasselbe unveränderliche Ergebnisobjekt.

### 1.2 Ein Korrekturvorgang statt zweier negativer Buchungen

XW-Office führt intern ein `CorrectionPair` ein. Dieses verbindet:

- die Stornorechnung als Mengenbeleg;
- die Gutschrift als Betragsbeleg;
- die betroffene Ursprungsrechnung;
- die auf SKU-Ebene zugeordneten Positionen.

Die vorhandene lokale sevDesk-OpenAPI-Dokumentation bestätigt getrennte Mechanismen für das Erzeugen einer Stornorechnung (`Invoice/{invoiceId}/cancelInvoice`) und einer Gutschrift (`CreditNote/Factory/createFromInvoice`), dokumentiert im gelesenen Response-Modell aber kein hinreichend belastbares gemeinsames Relationsfeld. Deshalb ist vor der eigentlichen Rechenänderung ein read-only Datenspiegelungs-Spike gegen echte MusikHeroes-Fälle Pflicht.

Reihenfolge für die Zuordnung:

1. explizite sevDesk-Objektrelationen aus realen API-Payloads;
2. gemeinsame Ursprungsrechnungs-ID;
3. eindeutige Belegreferenzen und Belegnummern;
4. als reine Prüfheuristik: Kontakt, SKU-Positionen, Beträge und enger Datumsabstand.

Nur Stufen 1 bis 3 dürfen automatisch final zuordnen. Eine Heuristik darf einen Kandidaten vorschlagen, aber niemals still eine provisionswirksame Paarung erzeugen.

### 1.3 Zeitraumregel für Korrekturpaare

Empfohlene und für die Umsetzung zu testende Regel:

- Normale Verkäufe gehören nach `invoiceDate` in den Zeitraum.
- Ein vollständiges Korrekturpaar gehört als Einheit nach `creditNoteDate` in den Zeitraum.
- Die SR-Menge und der GU-Betrag wirken dadurch im selben Abrechnungsmonat, selbst wenn die Dokumente an unterschiedlichen Tagen oder über eine Monatsgrenze hinweg erstellt wurden.
- Eine allein im Zeitraum liegende SR darf nicht vorab die Menge reduzieren, wenn die zugehörige GU noch fehlt.
- Eine allein gefundene GU darf nicht als zweite oder ungesicherte Korrektur gebucht werden.

Der Datenspiegelungs-Spike muss diese Regel an mindestens drei echten Paaren bestätigen, darunter nach Möglichkeit ein Paar über eine Monatsgrenze. Falls sevDesk die fachliche Beziehung anders abbildet, stoppt Luna Paket P1 nach Dokumentation der Payloads und passt die Regel nicht stillschweigend an.

### 1.4 Verhalten bei unvollständiger oder mehrdeutiger Zuordnung

- Ein unvollständiges oder mehrdeutiges Paar wird als **Problemfall** angezeigt.
- Es erhält bis zur Klärung keine provisionswirksame Korrektur.
- Kopieren, CSV und XLSX bleiben für eine Vorschau möglich, müssen aber deutlich `NICHT FINAL – ungeklärte Korrekturen` ausweisen.
- Ein finaler Abrechnungsabschluss darf bei ungeklärten Korrekturen nicht möglich sein.
- Keine Fuzzy-Heuristik darf einen Problemfall automatisch verschwinden lassen.

### 1.5 Darstellung und Formatierung

Die Provisionsansicht behält oben zwei Spalten:

- links: Kategorie, Zeitraum, Kategorietabelle und Kopierfunktion;
- rechts: Produkte mit `SKU`, `Name`, `Menge`, `Netto`;
- darunter über die volle Breite: aufklappbarer Bereich **Ausgaben MusikHeroes**.

Belege bleiben aufklappbar und sind initial geschlossen. Der Ausgabenbereich ist informativ und verändert die Provision nicht.

Verbindliche Formatierung:

- Mengen sind ganze Zahlen ohne Dezimalstellen, beispielsweise `360` oder `360 Stk.`;
- Geld in UI und kopiertem Text: `€ 6.262,99`;
- Null: `€ 0,00`;
- negative Beträge: `−€ 55,00`;
- CSV enthält locale-sichere numerische Werte plus Währungsspalte oder eine klar dokumentierte deutsche Darstellung;
- XLSX enthält echte Zahlenzellen mit Zahlenformat `€ #.##0,00`, keine als Text gespeicherten Geldbeträge.

Der kopierte Text folgt diesem Schema:

```text
Kategorie: MusikHeroes
Zeitraum: 01.08.2026 - 31.08.2026

MusikHeroes: 360 Stk., € 6.650,08 brutto, € 6.262,99 netto
MusikHeroes_Noten digital: 23 Stk., € 110,00 brutto, € 103,77 netto
...

Produkte:
SKU	Name	Menge	Netto
XW-511.01	Ohrwürmer #1 TRP	48 Stk.	€ 845,69
...
```

## 2. Zielbild für die Ausgabenprüfung

### 2.1 Platzierung in der Anwendung

Unter **FINANZEN** entsteht ein eigener Sidebar-Eintrag **Ausgabenprüfung**. Das ist fachlich sauberer als ein Ausbau des bisherigen Tabs `Steuern > Ausgaben`, weil Bankabgleich, Belegstatus und Profilzuordnung nicht nur Steuerfunktionen sind.

Die neue Seite besitzt drei interne Bereiche:

1. **Kontobewegungen** — globaler Ausgaben-Check;
2. **Fehlende Belege** — zunächst nur ausgehende Zahlungen;
3. **Regeln & Zuordnungen** — IBAN-/Empfängerregeln, Lieferantenlinks und Legacy-Importstatus.

Nach erfolgreicher Migration wird `Steuern > Ausgaben` entfernt oder für eine Übergangsversion als klarer Verweis auf den neuen Bereich belassen. `Steuern` bleibt für UVA/OSS zuständig.

### 2.2 Eingebettete MusikHeroes-Sicht

Unterhalb der beiden Provisionsspalten wird dieselbe Pipeline als profilgefilterte Projektion eingebettet:

- Zeitraum entspricht der Provisionsabrechnung;
- Konto ist ausschließlich **XeisWorks**;
- zunächst nur ausgehende Zahlungen;
- Spalten: Status/Flag, Datum, Empfänger, Zahlungsreferenz oder Verwendungszweck, Betrag, Belegstatus, sevDesk-Link, Lieferantenlink;
- der Bereich ist standardmäßig aufgeklappt, darf aber eingeklappt werden;
- sein Inhalt ist rein informativ und wird nicht von der Provision abgezogen.

Der UI-Begriff lautet **Ausgaben MusikHeroes**, nicht `Sonderausgaben`, um eine Verwechslung mit dem steuerlichen Begriff zu vermeiden.

### 2.3 Bank-Abrufstand

Sichtbar anzuzeigen sind:

- Name des sevDesk-Kontos: `XeisWorks`;
- sevDesk-`lastSync` des Kontos;
- Datum der neuesten geladenen Kontobewegung;
- Zeitpunkt des letzten erfolgreichen XW-Office-Abrufs;
- Vollständigkeitsstatus des Abrufs.

Wenn eine Seite, eine Dokumentverknüpfung oder ein Teilabruf fehlschlägt, darf die UI keinen vollständigen Stand vortäuschen. Sie zeigt **Abruf unvollständig** mit Wiederholen-Aktion.

### 2.4 Links

Für eine Kontobewegung können zwei getrennte Links angezeigt werden:

- **Beleg in sevDesk:** wenn eine konkrete Invoice, ein Voucher oder eine CreditNote verknüpft ist;
- **Lieferantenportal:** hinterlegte Website des Empfängers, vor allem wenn noch kein Beleg verknüpft ist.

Beide Schaltflächen dürfen gleichzeitig sichtbar sein. Ein zentraler `SevdeskDocumentUrlResolver` erzeugt URLs nach Ressourcentyp; UI-Module dürfen keine eigenen URL-Muster zusammensetzen. Lieferanten-URLs werden nur für `https` akzeptiert, normalisiert und erst nach explizitem Klick geöffnet.

## 3. Gemeinsame Pipeline

```text
sevDesk CheckAccount "XeisWorks"
        |
        v
SevdeskBankProvider + paginierter Abruf
        |
        v
normalisierte BankTransaction-Snapshots
        |
        +--> DocumentLinkResolver --> Invoice/Voucher/CreditNote-Links
        |
        +--> ReviewEngine --> offen / ignoriert / verschoben / erledigt
        |
        +--> ProfileMatcher --> candidate / included / excluded
        |                         für musikheroes und spätere Profile
        v
Read Models
        +--> FINANZEN > Ausgabenprüfung
        +--> Provisionen > MusikHeroes > Ausgaben MusikHeroes
        +--> Fehlende Belege
```

Alle drei Oberflächen greifen auf dieselben gespeicherten Transaktionen, Links und Regeln zu. Es darf keine zweite MusikHeroes-spezifische Bankabruf-Implementierung geben.

### 3.1 Normalisiertes Transaktionsmodell

Mindestens folgende Felder werden typisiert übernommen:

- sevDesk-Transaktions-ID und Konto-ID;
- `valueDate` und `entryDate`;
- Betrag als `Decimal` und Währung;
- Richtung `outgoing` oder `incoming`;
- Empfänger/Zahler;
- IBAN bzw. Kontonummer;
- Zahlungsreferenz;
- Verwendungszweck;
- sevDesk-Status;
- sevDesk-`create`/`update`;
- Abrufzeitpunkt und Importlauf.

Für die sichtbare Referenz gilt: Zahlungsreferenz verwenden, wenn befüllt, sonst Verwendungszweck. Die Originalfelder bleiben getrennt gespeichert.

Die Richtung wird von Beginn an modelliert. Phase 1 zeigt ausschließlich `outgoing`; `incoming` bleibt durch ein deaktiviertes Feature-Flag und ohne sichtbaren UI-Schalter vorbereitet.

### 3.2 Globaler Prüfstatus und Profilzuordnung trennen

Ein Datensatz benötigt zwei voneinander unabhängige Dimensionen:

- globaler Prüfstatus, beispielsweise `open`, `linked`, `missing_receipt`, `ignored`, `shifted`, `resolved`;
- profilbezogene Zuordnung, beispielsweise `candidate`, `included`, `excluded` für `musikheroes`.

Ein global ignorierter Eintrag ist nicht automatisch aus allen fachlichen Profilen gelöscht. Umgekehrt bedeutet ein MusikHeroes-Flag nicht, dass der Beleg global erledigt ist.

### 3.3 Intelligentes Flaggen

Beim manuellen Flag **MusikHeroes zuordnen** geschieht atomar:

1. die konkrete Transaktion erhält `included` für Profil `musikheroes`;
2. die normalisierte IBAN wird als exakte Kandidatenregel gespeichert, sofern vorhanden;
3. der normalisierte Empfänger wird als transparente Fallback-Regel gespeichert;
4. zukünftige Treffer werden nur als `candidate` vorgeschlagen, nicht ungefragt final aufgenommen;
5. die UI zeigt, welche Regel ausgelöst hat.

Priorität:

1. exakte IBAN;
2. exakter normalisierter Empfänger;
3. manuell gepflegte Aliasregel;
4. keine automatische Fuzzy-Zuordnung.

IBANs werden in der UI maskiert; vollständig gespeichert werden sie nur in der lokalen XW-Office-Datenbank. API-Token und vollständige IBANs dürfen nicht in Logs erscheinen.

Das Schema verwendet einen generischen `profile_key` aus den Provisionsprofilen. Dadurch können später weitere Bereiche in **PROVISIONEN** eigene Flags verwenden, ohne neue Tabellen zu benötigen.

## 4. Persistenzziel

Die aktuelle Migration `006_expense_check.py` enthält nur Ignore- und Verschiebelogik; `expenses.open_items` liegt weiterhin in `SettingKV`. Dieser Zwischenstand wird nicht erweitert. Eine neue additive Alembic-Migration nach dem beim Implementierungsstart aktuellen Head legt normalisierte Tabellen an.

Vorgeschlagene Tabellen:

### `expense_import_run`

- Konto-ID und Kontoname;
- angefragter Zeitraum;
- `last_sync_at`, `started_at`, `finished_at`;
- Status `running|complete|partial|failed`;
- Seiten-, Transaktions-, Link- und Fehlerzähler;
- Fehlermeldung ohne Secrets.

### `expense_transaction_snapshot`

- eindeutige Kombination aus sevDesk-Konto-ID und Transaktions-ID;
- beide Datumsfelder, Betrag `Numeric`, Währung und Richtung;
- Empfänger, normalisierter Empfänger, IBAN, Referenz und Verwendungszweck;
- sevDesk-Status, Quell-Updatezeit und letzter Abruf;
- optional konservierter Rohdatenausschnitt für Diagnose, ohne Token.

### `expense_document_link`

- Transaktion;
- `resource_type` (`Invoice`, `Voucher`, `CreditNote`);
- externe Dokument-ID und Belegnummer;
- Auflösungsquelle und Zeitpunkt;
- eindeutiger zusammengesetzter Schlüssel gegen Duplikate.

### `expense_review_decision`

- Transaktion;
- globaler Status, Notiz und optionaler Zielmonat;
- Quelle, Zeitstempel und Versionsfeld für konkurrierende Änderungen.

### `expense_profile_assignment`

- Transaktion und `profile_key`;
- Status `candidate|included|excluded`;
- Quelle `manual|rule|legacy_import`;
- auslösende Regel, Zeitstempel und Versionsfeld.

### `expense_match_rule`

- Gültigkeitsbereich `global` oder ein `profile_key`;
- Aktion, Feld (`iban|payee|purpose`), normalisierter Wert;
- Priorität, aktiv/inaktiv, Quelle und Auditfelder;
- IBAN-Regeln sind exakt; unscharfe Schwellenwerte gehören nicht in Phase 1.

### `expense_supplier_link`

- optionaler `profile_key`;
- normalisierter Empfänger und optional IBAN;
- Bezeichnung und validierte HTTPS-URL;
- Quelle und Auditfelder.

Bestehende `expense_ignore_rule`- und `expense_shift_entry`-Daten werden kontrolliert migriert oder über Adapter gelesen, bis die Migration bestätigt ist. Alte Tabellen und `SettingKV` werden erst in einem eigenen Cleanup-Paket entfernt.

## 5. sevDesk-Abruf und Belegauflösung

### 5.1 Kontoauswahl

- Konto ausschließlich über den exakten Namen `XeisWorks` suchen.
- Kein stiller Fallback auf das erste Konto.
- Kein Treffer oder mehrere Treffer sind ein sichtbarer Konfigurationsfehler.
- Konto-ID darf gecacht werden, muss bei 404/Deaktivierung neu aufgelöst werden.

### 5.2 Abruf

- Bestehende `SevdeskConnection` für Authentifizierung, Rate-Limit und Retry wiederverwenden.
- CheckAccount- und Transaktionsabruf aus vorhandenen Clearing-/sevDesk-Bausteinen in einen gemeinsam nutzbaren Provider extrahieren, nicht private Klassen kopieren.
- Pagination vollständig abarbeiten.
- DB-Upserts idempotent anhand externer IDs durchführen.
- Netzwerkzugriffe in einem abbrechbaren Background-Worker ausführen; die PySide6-UI darf nicht blockieren.
- `Decimal` statt `float`, Zeitzone `Europe/Vienna` für Anzeige und zeitzonenfähige Persistenz.

### 5.3 Verknüpfte Dokumente

Die Legacy-App ermittelt verknüpfte Transaktionen durch Dokumentlisten und `Resource/{id}/getCheckAccountTransactions`. Das ist fachlich nützlich, kann aber bei vielen Belegen zu sehr vielen Requests führen.

Die neue Pipeline soll:

1. relevante Invoice-, Voucher- und CreditNote-Dokumente paginiert laden;
2. verfügbare eingebettete Relationen bzw. Sammelendpunkte bevorzugen;
3. nur fehlende Verknüpfungen per Resource-Aufruf ergänzen;
4. Antworten pro Dokument-ID cachen;
5. die vorhandene globale Rate-Limit-/Retry-Logik verwenden;
6. einen Lauf als `partial` markieren, sobald irgendein Teil nicht vollständig geprüft wurde.

Der Transaktionsstatus allein genügt nicht als Belegnachweis. Nur eine konkrete gespeicherte Dokumentverknüpfung zählt als `linked`.

### 5.4 Fehlende Belege

Phase 1:

- nur ausgehende Transaktionen (`amount < 0`);
- Konto `XeisWorks`;
- keine konkrete Invoice-/Voucher-/CreditNote-Verknüpfung;
- nicht global ignoriert oder bewusst in einen anderen Monat verschoben;
- vollständiger Linkscan erforderlich.

Wenn der Linkscan unvollständig ist, darf die Pipeline einen Vorgang nicht endgültig als **Beleg fehlt** klassifizieren. Er bleibt **Prüfung unvollständig**.

Die Domain-API akzeptiert bereits eine Richtung; eingehende Transaktionen werden gespeichert und testbar verarbeitet, aber noch nicht in der UI angeboten.

## 6. Analyse des Ist-Zustands

### 6.1 XW-Office

Relevante Befunde:

- `src/xw_office/services/commission/service.py` summiert aktuell `signed_quantity` und `signed_net` über Rechnungen, Stornos und Gutschriften. Dadurch können Menge und Geld durch SR und GU doppelt reduziert werden.
- `ProductBreakdownRow` besitzt bereits getrennte Werte für verkauft, storniert, gutgeschrieben und netto; das Ergebnisobjekt muss zu einer expliziten Korrekturpaar-Logik weiterentwickelt werden.
- Die Gutschrift wird derzeit anhand `creditNoteDate` in den Zeitraum aufgenommen.
- `src/xw_office/services/expenses/service.py` liest offene Posten noch aus `SettingKV["expenses.open_items"]`; das ist keine sevDesk-Bankpipeline.
- `src/xw_office/models/expense_check.py` und Migration 006 decken Ignore-/Shift-Daten ab, aber keine normalisierten Banktransaktionen oder Dokumentlinks.
- `src/xw_office/ui/modules/taxes/view.py` zeigt den bisherigen einfachen Ausgaben-Tab unter **Steuern**.
- `src/xw_office/services/clearing/gateways.py` und `src/xw_office/services/sevdesk/invoice_client.py` enthalten wiederverwendbare Teile für CheckAccount/Transaktionen.
- sevDesk-Deep-Links werden derzeit an mehreren Stellen unterschiedlich gebaut; sie müssen zentralisiert werden.

### 6.2 Legacy-App `XeisWorks/sevDesk`

Übernehmenswerte Funktionen:

- Ausgaben-Check und Fehlende Belege als zwei getrennte Arbeitsansichten;
- negative Banktransaktionen als Ausgangsbasis;
- Aktionen zum Ignorieren, Verschieben, Flaggen und Öffnen der Quelle;
- Lieferantenportal-Links anhand Empfänger/Verwendungszweck;
- Auflösung verknüpfter Dokumente über sevDesk-Ressourcen.

Bewusst nicht 1:1 übernehmen:

- lokale JSON-Dateien als dauerhafte Wahrheit;
- vermischte Anzeige von Empfänger und Verwendungszweck;
- global wirkende Flags ohne Provisionsprofil;
- Fuzzy-Matching als automatische Entscheidung;
- pro Dokument ungebremste Einzelrequests;
- unklare Cache-Aktualität;
- UI-nahe Geschäftslogik.

## 7. Legacy-Migration

Ein idempotentes Importwerkzeug wird vorgesehen, zum Beispiel:

```text
python scripts/import_legacy_expense_check.py \
  --source C:\Users\XeisWorks\GitHub\sevDesk \
  --dry-run
```

Erst nach Prüfung des Berichts erfolgt ein zweiter Lauf mit `--apply`.

Zuordnung:

- Legacy-Flags aus `cache.json`: als `musikheroes`-Kandidatenregeln mit Quelle `legacy_import`, niemals sofort `included`;
- `missing_receipt_links.json`: in `expense_supplier_link`;
- Ignore-Daten: in globale Ignore-Regeln;
- Shift-Daten: in globale Prüfentscheidungen mit Zielmonat;
- gecachte Legacy-Transaktionen: nicht als Wahrheit importieren, sondern frisch aus sevDesk laden.

Der Import speichert Quelldatei, SHA-256, Laufzeit und Ergebniszahlen, damit ein wiederholter Lauf keine Duplikate erzeugt. Nicht eindeutig zuordenbare Einträge landen in einem Prüfbericht. Das Legacy-Repo wird weder verändert noch bereinigt.

## 8. UI-Spezifikation

### 8.1 FINANZEN > Ausgabenprüfung

Kopfbereich:

- Von/Bis oder Zeitraum-Preset;
- Konto `XeisWorks` als nicht frei wechselbare Anzeige;
- Abrufstand und Vollständigkeitsbadge;
- `Neu laden`, `Cache verwenden`, `Export`.

Kontobewegungstabelle:

- Datum;
- Empfänger;
- Zahlungsreferenz/Verwendungszweck;
- Betrag;
- Belegstatus;
- Profilflags;
- Aktionen.

Kontext-/Zeilenaktionen:

- MusikHeroes einschließen;
- MusikHeroes ausschließen;
- Kandidat bestätigen oder verwerfen;
- einmal ignorieren;
- Empfänger/IBAN dauerhaft ignorieren;
- in Folgemonat verschieben;
- sevDesk-Beleg öffnen;
- Lieferantenportal öffnen;
- Entscheidung rückgängig machen.

Jede dauerhafte Regeländerung zeigt vor dem Speichern die normalisierte Regel und ihre zukünftige Wirkung. `Einmal ignorieren` wird an die konkrete Transaktions-ID gebunden und darf nicht wie in der Legacy-Logik unbeabsichtigt dauerhaft wirken.

### 8.2 Regeln & Zuordnungen

- getrennte Listen für globale Ignore-Regeln, Profilregeln und Lieferantenlinks;
- Suchfeld, Aktiv/Deaktiviert, Quelle und letzter Treffer;
- keine Anzeige vollständiger IBANs;
- bearbeitbare Lieferanten-URL mit HTTPS-Prüfung;
- Legacy-Importbericht und ungeklärte Einträge.

### 8.3 Provisionen > MusikHeroes

Der eingebettete Bereich nutzt ein kompaktes Read Model und enthält keine eigene Regelengine. Manuelle MusikHeroes-Aktionen schreiben in dieselben Tabellen wie die zentrale Ausgabenprüfung. Änderungen erscheinen nach Refresh in beiden Ansichten identisch.

## 9. Umsetzungspakete für Codex 5.6 Luna

### P0 — Realdaten-Spike Storno/Gutschrift

**Ziel:** belastbare sevDesk-Beziehung und Zeitraumregel bestätigen.

- read-only drei oder mehr bekannte MusikHeroes-Korrekturfälle abrufen;
- Rohfelder strukturell dokumentieren, personenbezogene Inhalte im Testfixture anonymisieren;
- Ursprungsrechnung, SR und GU samt Positionen gegenüberstellen;
- mindestens einen Cross-Period-Fall prüfen oder dessen Fehlen dokumentieren;
- Ergebnis in einer kurzen ergänzenden Markdown-Datei und anonymisierten Fixtures festhalten;
- keine Produktionslogik ändern.

**DoD:** Ein automatisierbarer Relationsweg ist belegt. Andernfalls ist ein sichtbarer manueller Pairing-Workflow spezifiziert, bevor P1 beginnt.

### P1 — Provisionskorrekturen vereinheitlichen

- `CorrectionPair` und Pairing-Service einführen;
- RE-Menge/RE-Betrag, SR-Menge und GU-Betrag getrennt aggregieren;
- unvollständige/mehrdeutige Paare als Problemfälle ausgeben;
- ein zentrales Ergebnisobjekt für UI, Copy, CSV und XLSX verwenden;
- Ganzzahl- und Euroformat zentralisieren;
- Finalitätsstatus in Exporte aufnehmen.

**DoD:** Kein Testfall kann SR-Netto plus GU-Netto oder SR-Menge plus GU-Menge doppelt abziehen.

### P2 — Gemeinsames Expense-Domainmodell und Migration

- neue Modelle/Enums/Repositories;
- additive Alembic-Migration nach aktuellem Head, nicht hart eine Nummer annehmen;
- globale Review- und profilbezogene Assignment-Zustände trennen;
- Feature-Flags für neuen Bereich und versteckte Einnahmenrichtung;
- Repository- und Migrationstests.

### P3 — sevDesk-Bankprovider und Abrufstand

- gemeinsamen CheckAccount-/Transaction-Provider extrahieren;
- exakte Auswahl `XeisWorks`;
- Pagination, idempotente Upserts, `lastSync` und Importläufe;
- Background-Worker, Abbruch und Fehlerstatus;
- noch keine Regelautomatik.

### P4 — Dokumentlinks und Fehlende-Belege-Engine

- Invoice/Voucher/CreditNote-Verknüpfungen zentral auflösen;
- `SevdeskDocumentUrlResolver`;
- vollständige/partielle Scansemantik;
- outgoing-only Projektion, Domain bereits richtungsfähig;
- API-Fixtures für Pagination, Retry und Teilfehler.

### P5 — Regeln, MusikHeroes-Flags und Lieferantenlinks

- manuelles Include/Exclude;
- IBAN- und Empfänger-Kandidatenregeln;
- Priorität und Herkunft sichtbar;
- Lieferantenportalverwaltung;
- Audit-/Optimistic-Locking-Verhalten testen.

### P6 — Legacy-Importer

- Dry-run und Apply;
- Checksum-/Importledger;
- Flags als MusikHeroes-Kandidaten, nicht automatische Includes;
- Links, Ignore und Shift übernehmen;
- Importbericht und Wiederholbarkeit testen.

### P7 — Neuer Bereich FINANZEN > Ausgabenprüfung

- neuer `ModuleKey`, Sidebar, Main-Window-Factory und Home-Kachel;
- Kontobewegungen, Fehlende Belege, Regeln & Zuordnungen;
- Status-/Link-/Flag-Aktionen;
- Tabellenzustände Loading/Empty/Error/Partial;
- ausgehende Zahlungen sichtbar, Einnahmen verborgen.

### P8 — MusikHeroes-Einbettung

- vollbreiter Bereich unter den zwei Provisionsspalten;
- identisches Read Model, Zeitraum und Konto;
- informative Summen ohne Einfluss auf Provision;
- beide Links und Flag-Aktionen;
- UI-Regressionstests für Collapse/Resize/Refresh.

### P9 — Umschaltung und Cleanup

- alten `Steuern > Ausgaben`-Tab entfernen oder Übergangsverweis löschen;
- `expenses.open_items` nur nach bestätigter Migration aus dem aktiven Pfad entfernen;
- obsolete Doppelimplementierungen beseitigen;
- Benutzer-/Betriebsdokumentation aktualisieren;
- Feature-Flag nach erfolgreichem Parallelbetrieb umlegen.

## 10. Testmatrix

### Provisionen

- RE ohne Korrektur;
- RE + SR + zugehörige GU: Menge genau einmal reduziert, Betrag genau einmal reduziert;
- mehrere Teilpositionen und mehrere SKUs;
- identische Beträge bei verschiedenen Kunden dürfen nicht falsch gepaart werden;
- SR und GU in verschiedenen Monaten;
- fehlende GU, fehlende SR, mehrere mögliche Partner;
- Kategorie- und Gesamtsumme entsprechen der Summe der Produktzeilen;
- UI, Clipboard, CSV und XLSX stammen aus demselben Ergebnis;
- Mengen ganzzahlig, Geld `€ 0,00`, XLSX-Zellen numerisch.

### Bankpipeline

- Konto `XeisWorks` genau einmal, gar nicht und mehrfach gefunden;
- paginierte Transaktionen ohne Lücken/Duplikate;
- negative Ausgabe, positive Einnahme, Nullbetrag und Fremdwährung;
- `lastSync` fehlt oder ist veraltet;
- wiederholter Import ist idempotent;
- Teilfehler erzeugt `partial`, nicht `complete`.

### Regeln

- manuelles Flag bindet aktuelle Transaktion als `included`;
- exakte IBAN erzeugt bei neuer Transaktion nur `candidate`;
- Empfänger-Fallback ist nachvollziehbar;
- falscher Kandidat kann dauerhaft ausgeschlossen werden;
- globale Ignore-Regel und Profilflag bleiben unabhängig;
- vollständige IBAN erscheint nicht in Logs oder UI.

### Dokumente und Links

- Invoice-, Voucher- und CreditNote-Link;
- mehrere Dokumente an einer Transaktion;
- kein Dokument plus Lieferantenportal;
- beide Links gleichzeitig;
- ungültige oder nicht-HTTPS Lieferanten-URL;
- unvollständiger Linkscan erzeugt keinen falschen Missing-Receipt-Fall.

### Legacy-Import

- Dry-run schreibt nichts;
- Apply ist wiederholbar;
- doppelte und mehrdeutige Regeln landen im Bericht;
- Flags werden Kandidaten, nicht automatische MusikHeroes-Ausgaben;
- Legacy-Dateien bleiben unverändert.

## 11. Abnahmekriterien

Der Umbau ist erst abgeschlossen, wenn:

1. ein Korrekturpaar Menge und Geld jeweils genau einmal reduziert;
2. ungeklärte Paare sichtbar sind und keine finale Abrechnung erlauben;
3. alle Darstellungen dieselben Mengen und Summen liefern;
4. Mengen ganzzahlig und Eurobeträge sauber formatiert sind;
5. Belege initial geschlossen bleiben;
6. MusikHeroes-Ausgaben informativ unter der Provisionsansicht erscheinen;
7. die zentrale Ausgabenprüfung denselben Datenbestand und dieselben Links nutzt;
8. manuelle MusikHeroes-Flags die IBAN-Regel speichern und neue Treffer als Kandidaten anzeigen;
9. sevDesk-Beleglink und Lieferantenlink getrennt funktionieren;
10. der Abrufstand von `XeisWorks` sichtbar und ehrlich vollständig/partiell markiert ist;
11. Fehlende Belege zunächst nur ausgehende Zahlungen zeigt;
12. die Domain spätere Einnahmen und weitere Provisionsprofile ohne Schemaneubau unterstützt;
13. Legacy-Flags und Lieferantenlinks idempotent migriert und überprüfbar sind;
14. keine lokale JSON-Datei mehr die operative Wahrheit für neue Funktionen ist.

## 12. Luna-Arbeitsregeln

Vor jedem Paket:

1. auf `main` wechseln;
2. sauberen Arbeitsbaum prüfen;
3. `git pull --ff-only origin main` ausführen;
4. aktuellen Alembic-Head und relevante Tests feststellen;
5. dieses Dokument und die tatsächlich betroffenen Dateien neu lesen.

Während eines Pakets:

- Scope des Pakets einhalten;
- vorhandene sevDesk-Verbindung, Rate-Limits und Fehlerbehandlung wiederverwenden;
- keine Live-Schreiboperation gegen sevDesk für Analyse oder Tests;
- externe Payloads in anonymisierte Fixtures überführen;
- Geld nur als `Decimal`/`Numeric` behandeln;
- Geschäftslogik aus PySide6-Widgets heraushalten;
- keine fremden Änderungen im Arbeitsbaum überschreiben;
- das geschützte Architekturarchiv nicht verändern.

Nach jedem Paket mindestens:

```text
python -m pytest <gezielte Tests>
python -m ruff check <geänderte Python-Pfade>
python -m mypy <geänderte Python-Pfade, soweit im Projekt unterstützt>
git diff --check
```

Anschließend vollständige relevante Suite ausführen, Änderungen committen, in `main` integrieren und ohne Force-Push zu `origin/main` pushen. Bekannte Altfehler sind klar von neu verursachten Fehlern zu trennen.

## 13. Bewusste Nicht-Ziele

- Ausgaben automatisch von Provisionen abziehen;
- Einnahmen bereits in der UI anzeigen;
- automatische Buchungen oder Belegzuordnungen in sevDesk schreiben;
- Fuzzy-Treffer ohne Bestätigung final zuordnen;
- mehrere Bankkonten auswählbar machen;
- das Legacy-Repo weiterentwickeln;
- die gesamte Finanzarchitektur in einem Big-Bang ersetzen.
