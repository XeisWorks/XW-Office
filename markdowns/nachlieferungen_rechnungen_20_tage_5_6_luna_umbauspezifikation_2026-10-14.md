# XW-Office – Nachlieferungen aus Rechnungen, Folgebestellungs-Trigger und 20-Tage-ASAP-Flow

Stand: 2026-10-14  
Zielmodell für die Umsetzung: Codex 5.6 Luna  
Repository: `XW-Office`

## 1. Auftrag an Codex 5.6 Luna

Implementiere den in diesem Dokument beschriebenen Nachlieferungs-Flow vollständig, inklusive Migrationen, UI, Services, Druckintegration und Tests.

Vor der Umsetzung:

1. `AGENTS.md` vollständig lesen und befolgen.
2. Mit sauberem Arbeitsbaum auf `main` wechseln.
3. `git pull --ff-only origin main` ausführen.
4. Die bestehende Lieferkorrektur-, Offene-Sendungen-, Rechnungs-, Product-Hub- und START-Drucklogik vollständig untersuchen.
5. Bestehende Benutzeränderungen und fachfremde Dateien nicht überschreiben.

Nach der Umsetzung:

1. Relevante Unit-, UI- und Integrationstests ausführen.
2. Den Arbeitsbaum und den Diff kontrollieren.
3. Die fertigen Änderungen in `main` committen.
4. Ohne Force-Push nach `origin/main` pushen.

Das geschützte Architekturarchiv
`markdowns/XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md`
darf weder bearbeitet noch umbenannt werden.

## 2. Verbindlich entschiedene Fachregeln

Die folgenden Punkte sind entschieden und dürfen bei der Implementierung nicht erneut offen interpretiert werden:

1. Die 20-Tage-Frist beginnt mit der Erstellung des Nachlieferungsfalls, also mit dessen persistentem `created_at` – nicht mit Bestätigung, ursprünglicher Bestellung oder ursprünglicher Rechnung.
2. Mehrere offene Nachlieferungen desselben Kunden werden bei gemeinsamer Auslieferung auf **einem gemeinsamen Lieferschein** zusammengeführt. Der Lieferschein nennt alle Ursprungsrechnungen und Ursprungsbestellungen.
3. Kundenmatching erfolgt primär über stabile IDs:
   - sevDesk-Kontakt-ID,
   - Wix-`contactId`,
   - normalisierte E-Mail als Fallback.
   Ein Kundenname allein darf nie automatisch matchen.
4. Nach 20 Tagen wird die Nachlieferung in den Alarm **OFFENE SENDUNGEN** in der Kopfzeile integriert. Ab dann gilt sie als so schnell wie möglich separat zu versenden.
5. Wird nach Ablauf der 20 Tage, aber vor dem tatsächlichen Lieferscheindruck eine neue Bestellung desselben Kunden erkannt, darf die Nachlieferung noch an diese Bestellung angehängt werden. Der separate ASAP-Versandfall muss dabei automatisch und idempotent zurückgezogen werden.
6. Das Erstellungs-Popup bietet ausdrücklich die Option **Sofort separat versenden**.
7. Einzelne Stimmen sind überwiegend Komponenten eines Product-Hub-Produkts und nur selten bereits eigene Rechnungspositionen. Die Komponentenauswahl muss daher Product-Hub-Daten verwenden und darf nicht von OpenAI erfunden werden.

## 3. Zielbild

Eine Nachlieferung ist fachlich ein eigener, persistenter Vorgang. Sie darf nicht nur als lose Kopie in den Einstellungen von OFFENE SENDUNGEN leben.

Technisch werden jedoch vorhandene Bausteine wiederverwendet:

- Referenzsuche nach sevDesk-Rechnung und Wix-Bestellung,
- Kunden- und Lieferadressauflösung,
- exakte Produktauflösung,
- OpenAI-Zusammenfassung,
- editierbare Produktzeilen,
- Lieferscheinrenderer,
- Druckwarteschlange,
- OFFENE-SENDUNGEN-Alarm und XW-Flow-Spiegelung,
- START-Druckreihenfolge.

Der führende Datensatz bleibt immer der Nachlieferungs-/Lieferkorrekturfall in der relationalen Datenbank.

```text
Rechnungsbutton oder Nachlieferungs-Mail
                |
                v
       vollständiger Nachlieferungsfall
       Kunde + Referenzen + Adresse + Artikel
                |
         +------+------------------+
         |                         |
         | normal                  | sofort separat
         v                         v
       WAITING             ASAP / OFFENE SENDUNGEN
         |
         +-- gleicher Kunde bestellt erneut
         |          |
         |          v
         |   atomar an neue Rechnung binden
         |          |
         |          v
         |   gemeinsamer Nachlieferungs-Lieferschein
         |   -> neue Rechnung
         |   -> ein gemeinsames Versandlabel
         |
         +-- 20 Tage erreicht
                    |
                    v
             ASAP / OFFENE SENDUNGEN
                    |
           neue Bestellung vor Druck?
              | ja            | nein
              v               v
       an Rechnung binden   separat drucken/senden
```

## 4. Vorhandener Stand, der weiterverwendet werden muss

### 4.1 Lieferkorrekturen / Customer Aftercare

Vorhanden sind unter anderem:

- `src/xw_office/models/customer_aftercare.py`
- `src/xw_office/repositories/customer_aftercare.py`
- `src/xw_office/services/customer_aftercare/service.py`
- `src/xw_office/services/customer_aftercare/trigger_service.py`
- `src/xw_office/services/customer_aftercare/inbox_service.py`
- `src/xw_office/services/customer_aftercare/ai_classifier.py`
- `src/xw_office/services/customer_aftercare/fulfillment.py`
- `src/xw_office/ui/modules/rechnungen/customer_aftercare_review_dialog.py`
- `src/xw_office/ui/modules/rechnungen/customer_aftercare_manager_dialog.py`

Bereits vorhanden:

- Status `PENDING_REVIEW`, `WAITING`, `TRIGGERED`, `RESOLVED`, `IGNORED`, `CANCELLED`;
- 20-Tage-Trigger;
- Abgleich neuer Wix-Bestellungen über `contactId` beziehungsweise E-Mail;
- KI-Vorklassifikation von Reklamationsmails;
- Zusatzrechnungslogik;
- manuelle Übergabe einer Nachsendung an OFFENE SENDUNGEN.

Die bestehende Übergabe über `OffeneSendungenService.create_manual_case()` ist derzeit nur eine Kopie. Sie muss durch eine referenzierte, synchronisierte Integration ersetzt oder so erweitert werden, dass der relationale Nachlieferungsfall die Quelle der Wahrheit bleibt.

### 4.2 OFFENE SENDUNGEN

Vorhanden sind unter anderem:

- `src/xw_office/services/sendungen/service.py`
- `src/xw_office/services/sendungen/delivery_note.py`
- `src/xw_office/ui/modules/rechnungen/offene_sendungen_dialog.py`

Wiederzuverwenden sind insbesondere:

- Erkennung von `RE-26####` und fünfstelligen Wix-Bestellnummern;
- sevDesk-/Wix-Kontextauflösung;
- exakte Rechnungspositionen und SKU;
- Lieferadressauflösung;
- strukturierte OpenAI-Ausgabe;
- editierbare Adresse, Produktzeilen und Notiz;
- Lieferscheinanzeige und -druck;
- Offen-/Erledigt-Zustand;
- bestehende Spiegelung nach XW-Flow.

Die private Geschäftslogik von OFFENE SENDUNGEN darf nicht ein zweites Mal kopiert werden. Gemeinsame Resolver sind in eigenständige Services zu extrahieren, sofern dies für die Wiederverwendung erforderlich ist.

### 4.3 START-Drucklauf

`src/xw_office/services/invoice_processing/service.py` besitzt bereits die Reihenfolge:

```text
optionaler Lieferschein -> Rechnung -> Versandlabel
```

Diese vorhandene, bestätigte Druckreihenfolge ist für Nachlieferungen zu erweitern. Es darf kein unabhängiger paralleler Druckpfad entstehen, der die Reihenfolge nicht garantiert.

## 5. Architekturentscheidung: getrennte Fachdomäne, gemeinsame Infrastruktur

Nachlieferungen und OFFENE SENDUNGEN bleiben fachlich getrennt:

- **OFFENE SENDUNG** bedeutet: jetzt beziehungsweise ASAP separat versenden.
- **NACHLIEFERUNG / WAITING** bedeutet: bei der nächsten passenden Bestellung beilegen, spätestens nach 20 Tagen separat versenden.

Gemeinsam genutzt werden:

- `ShipmentBusinessContextResolver` oder ein entsprechend klar benannter gemeinsamer Resolver;
- Lieferadressauflösung;
- Rechnungs-/Bestellpositionsauflösung;
- Product-Hub-Auflösung;
- OpenAI-Zusammenfassung;
- `DeliveryNoteService`;
- `PrintQueueService`;
- UI-Komponenten für Adresse und Produktzeilen, soweit ohne unübersichtliche Vererbung möglich.

Keine bidirektional unabhängigen Kopien desselben Falls anlegen. Ein OFFENE-SENDUNGEN-Eintrag aus einer Nachlieferung trägt stets eine stabile Referenz auf den Nachlieferungs-Dispatch beziehungsweise dessen Case-IDs.

## 6. Persistenz und Migration

Die vorhandenen Tabellen sind per neuer Alembic-Migration zu erweitern. Bestehende Daten müssen kompatibel bleiben.

### 6.1 `customer_aftercare_case`

Mindestens folgende Informationen müssen persistent und strukturiert verfügbar sein:

- Quelle des Falls: Rechnung, dedizierte Nachlieferungsmail oder erkannte Shop-Mail;
- sevDesk-Ausgangsrechnungs-ID und -nummer;
- Wix-Ausgangsbestellungs-ID und -nummer;
- sevDesk-Kontakt-ID;
- Wix-`contactId`;
- normalisierte Kunden-E-Mail;
- Kundenname als Anzeigeinformation, nicht als Matchschlüssel;
- geprüfte Lieferadresse als strukturierter Snapshot beziehungsweise JSON;
- Quelle der Lieferadresse;
- Erstellungszeitpunkt;
- `due_at = created_at + 20 Kalendertage`;
- Versandmodus `WAIT_NEXT_ORDER_OR_DEADLINE` oder `IMMEDIATE`;
- Triggergrund `NEW_ORDER`, `MAX_WAIT_EXPIRED`, `IMMEDIATE`;
- auslösende neue Rechnung und Wix-Bestellung;
- Verknüpfung zu einem Dispatch;
- Druck-/Erledigungsinformationen.

Die vorhandenen Felder sind weiterzuverwenden, sofern ihre Semantik eindeutig passt. Keine redundanten Felder allein wegen anderer Namen ergänzen.

Wichtig für bestehende E-Mail-Fälle:

- `created_at` entsteht bei der persistenten Anlage des Falls.
- Bei späterer Benutzerbestätigung ist `due_at` aus diesem ursprünglichen `created_at` zu berechnen.
- Liegt dieser Zeitpunkt bei Bestätigung bereits in der Vergangenheit, wird der Fall sofort als `MAX_WAIT_EXPIRED` fällig.

### 6.2 `customer_aftercare_item`

Produktzeilen benötigen mindestens:

- Rolle, beispielsweise `MISSING_TO_SEND`;
- exakten Anzeigenamen als Snapshot;
- SKU;
- Menge;
- Ursprung: sevDesk-Position, Wix-Position, Product-Hub-Komponente oder manuell;
- stabile Ursprungs-ID, soweit vorhanden;
- Elternprodukt/SKU bei Product-Hub-Komponenten;
- Product-Hub-Komponenten-ID beziehungsweise stabilen Komponentenschlüssel;
- Ursprungsrechnungs- und Ursprungsbestellungsreferenz;
- optional freie Zeilennotiz;
- Kennzeichnung kostenlose Nachlieferung / nicht verrechnen.

### 6.3 Dispatch/Bündelung

Für einen idempotenten gemeinsamen Lieferschein wird ein eigener persistenter Dispatch empfohlen, beispielsweise `customer_aftercare_dispatch`, mit Zuordnung der enthaltenen Cases.

Erforderliche Informationen:

- UUID;
- Status, zum Beispiel `PLANNED`, `ASAP`, `ATTACHED`, `PRINTING`, `PRINTED`, `COMPLETED`, `CANCELLED`, `FAILED`;
- Triggerart;
- Zielrechnung/Zielbestellung bei Beilage;
- Kunden-Matchschlüssel;
- enthaltene Case-IDs;
- Lieferschein-Pfad beziehungsweise Dokumentfingerprint;
- zugehörige OFFENE-SENDUNGEN-ID;
- Claim-/Druckzeitpunkte;
- Fehlertext;
- Erstellungs-/Änderungszeitpunkte.

Eine alternative Modellierung ist zulässig, wenn dieselben Eigenschaften atomar, nachvollziehbar und idempotent erfüllt werden. Lose JSON-Kopien ohne relationale Rückverknüpfung sind nicht zulässig.

## 7. Frist- und Zustandslogik

### 7.1 Normaler Modus

Bei Erstellung:

```text
shipping_mode = WAIT_NEXT_ORDER_OR_DEADLINE
due_at = created_at + 20 Kalendertage
status = WAITING, sobald der Fall bestätigt und vollständig ist
```

Vor Bestätigung darf die KI keine automatische Sendung und keinen automatischen Druck auslösen.

### 7.2 Sofort separat versenden

Bei Auswahl von **Sofort separat versenden**:

- Triggergrund `IMMEDIATE`;
- unverzügliche, idempotente Aufnahme in OFFENE SENDUNGEN;
- Aufnahme in den Kopfzeilen-Alarm;
- weiterhin vollständig editierbar;
- keine automatische Papierausgabe ohne Benutzeraktion;
- nach Druck/Erledigung Rückmeldung an den relationalen Fall.

### 7.3 Ablauf nach 20 Tagen

Nach Fristablauf:

- atomarer Übergang von `WAITING` zu fällig/ASAP;
- genau ein verknüpfter OFFENE-SENDUNGEN-Fall;
- Alarmzähler steigt genau einmal;
- vorhandene OFFENE-SENDUNGEN- und XW-Flow-Synchronisierung wird genutzt;
- wiederholte Polls erzeugen keine Dubletten.

### 7.4 Neue Bestellung nach Fristablauf, aber vor Druck

Ist eine Nachlieferung bereits als ASAP-Sendung sichtbar, aber noch nicht gedruckt beziehungsweise final beansprucht, darf eine neue passende Bestellung sie einsammeln:

1. Datenbank-Claim beziehungsweise Advisory Lock setzen.
2. Prüfen, dass noch kein Lieferschein tatsächlich gedruckt wurde.
3. ASAP-Dispatch zurückziehen beziehungsweise für OFFENE SENDUNGEN unsichtbar machen.
4. Fall an die neue Rechnung/Bestellung binden.
5. Nachlieferung vor dieser Rechnung drucken.

Ist der Druck bereits gestartet oder bestätigt, darf keine automatische Umbindung mehr erfolgen.

## 8. Kundenmatching

Ein zentraler Matcher muss sowohl Hintergrundpolling als auch synchronen START-Preflight bedienen.

Matchpriorität:

1. identische sevDesk-Kontakt-ID;
2. identische Wix-`contactId`;
3. identische normalisierte E-Mail-Adresse;
4. kein automatisches Match.

Der Kundenname darf nur angezeigt oder als manueller Suchhinweis verwendet werden.

Zu beachten:

- Ein Fall kann aus einer sevDesk-Rechnung ohne Wix-Bestellung stammen.
- Ein Wix-Fall kann später eine sevDesk-Rechnung erhalten.
- IDs sollen beim Laden des Business-Kontexts nach Möglichkeit gegenseitig ergänzt werden.
- E-Mail-Vergleich mindestens trimmen und case-insensitiv durchführen.
- Abweichende Namen oder Lieferadressen verhindern bei stabil identischer Kunden-ID kein Match, müssen aber im Popup beziehungsweise Preflight sichtbar sein.

## 9. Synchroner START-Preflight und Druckreihenfolge

Der 60-Sekunden-Hintergrundpoll reicht nicht aus. Unmittelbar vor dem physischen Druck jeder Rechnung muss der START-Flow synchron und ohne UI-Netzwerkzugriff prüfen:

1. Welche stabilen Kundenkennungen hat die aktuelle Rechnung/Bestellung?
2. Welche bestätigten, noch nicht gedruckten Nachlieferungen passen dazu?
3. Welche davon dürfen atomar für diese Rechnung beansprucht werden?
4. Gibt es bereits einen ASAP-Eintrag, der noch zurückgezogen werden kann?

Bei Treffern:

1. Alle passenden Nachlieferungen dieses Kunden bündeln.
2. Einen gemeinsamen Lieferschein erzeugen.
3. Alle Ursprungsrechnungen und Ursprungsbestellungen auf dem Lieferschein ausgeben.
4. Produkte sinnvoll zusammenführen; gleiche SKU/Komponente nur dann summieren, wenn Bezeichnung und Nachlieferungssemantik identisch sind.
5. Nachlieferungs-Lieferschein mit `wait=True` drucken.
6. Erst nach bestätigtem Lieferscheindruck die neue Rechnung drucken.
7. Danach genau ein Versandlabel für das gemeinsame Paket drucken.
8. Cases und Dispatch atomar als gedruckt/zugeordnet verbuchen.

Reihenfolge:

```text
Nachlieferungs-Lieferschein -> neue Rechnung -> ein Versandlabel
```

Fehlerverhalten:

- Schlägt der Lieferscheindruck fehl, dürfen Rechnung und Label für diesen Vorgang nicht nachfolgen.
- Ein Retry darf keinen zweiten Dispatch und keinen zweiten logischen Lieferschein erzeugen.
- Bereits bestätigte Druckschritte müssen nachvollziehbar bleiben.
- Parallel laufende START-Instanzen dürfen denselben Fall nicht doppelt beanspruchen.

## 10. Gemeinsamer Lieferschein

Der bestehende `DeliveryNoteService` ist zu erweitern beziehungsweise mit geeignetem Kontext aufzurufen.

Der gemeinsame Nachlieferungs-Lieferschein enthält mindestens:

- Überschrift `Nachlieferung` oder `Lieferschein – Nachlieferung`;
- Name und vollständige Lieferanschrift;
- Liste aller Ursprungsrechnungen;
- Liste aller Ursprungsbestellungen;
- Zielbestellung/Zielrechnung, falls beigelegt;
- alle nachzuliefernden Produkte und Komponenten;
- Mengen;
- SKU beziehungsweise Komponentenreferenz, sofern vorhanden;
- klare Kennzeichnung `Kostenlose Nachlieferung – nicht verrechnen`;
- intelligente, vom Benutzer bearbeitbare Notiz;
- keine Preise.

Die Dokumentstruktur darf keine Ursprungsreferenz verlieren, auch wenn gleiche Artikel aus mehreren Fällen zusammengefasst werden.

## 11. Rechnungsansicht: Aktion in der Spalte AKTIONEN

In `src/xw_office/ui/modules/rechnungen/view.py` sind derzeit die Tabellenaktionen Post, Zoll, Wix und Kundenmail vorhanden.

In der Tabellenspalte `AKTIONEN` gilt künftig:

- Post beibehalten;
- Zoll beibehalten;
- Wix-Link entfernen;
- Kundenmail entfernen;
- Nachlieferungsaktion mit dem vom Benutzer bereitgestellten Paket-/Rückpfeil-/Haken-Icon ergänzen.

Der Benutzerwunsch betrifft die Tabellenspalte. Die bestehenden Wix- und Kundenmail-Schaltflächen im rechten Detailbereich dürfen erhalten bleiben.

Vorgesehener Assetname:

```text
icons/nachlieferung.png
```

Das in der Anforderung bereitgestellte Bild ist zu verwenden. Falls das Bild im Ausführungskontext von Codex 5.6 Luna nicht als Datei verfügbar ist, nicht eigenmächtig ein fremdes Web-Asset herunterladen, sondern einen neutralen lokalen Qt-Fallback verwenden und die fehlende Originaldatei im Abschlussbericht nennen.

Tooltip:

```text
Nachlieferung für diese Rechnung erstellen
```

Der Klick öffnet das neue Nachlieferungs-Popup mit vollständig geladenem Rechnungskontext. Netzwerk- und Datenbankarbeit läuft im Hintergrund, nicht im UI-Thread.

## 12. Nachlieferungs-Popup

Das Popup orientiert sich optisch und funktional an OFFENE SENDUNGEN, ist aber ein eigener Dialog für die Fachdomäne Nachlieferung.

### 12.1 Kopfbereich

Anzeigen:

- Ausgangsrechnung;
- Wix-Ausgangsbestellung, falls vorhanden;
- Kunde;
- sevDesk-Kontakt-ID und/oder Wix-`contactId` in einem technischen Detailbereich;
- Quell-Badges für Rechnung, Wix, Product Hub, E-Mail und manuell;
- Erstellungszeitpunkt;
- errechnete Fälligkeit.

### 12.2 Lieferadresse

- automatisch auflösen;
- Wix-Versandadresse bevorzugen, wenn die Ausgangsbestellung eindeutig ist;
- ansonsten sevDesk-/Rechnungskontext verwenden;
- Adresse vollständig editierbar;
- Quelle anzeigen;
- ohne zustellfähige Adresse Speichern als wartender Entwurf erlauben, aber Aktivierung beziehungsweise Versand blockieren;
- manuell bearbeitete Adresse persistent speichern und nicht beim nächsten Refresh überschreiben.

### 12.3 Produktauswahl

Beim Öffnen aus einer Rechnung:

- exakte sevDesk-Rechnungspositionen laden;
- Wix-Positionen ergänzend auflösen;
- Produktnamen und SKU aus verlässlicher Quelle verwenden;
- jede Position per Checkbox auswählbar;
- Teilmenge zwischen 1 und ursprünglicher Menge auswählbar;
- bei Bedarf höhere manuelle Menge ausdrücklich zulassen, aber als manuell markieren;
- manuelle Produktzeile hinzufügen und entfernen können.

### 12.4 Product-Hub-Komponenten / einzelne Stimmen

Da einzelne Stimmen überwiegend Product-Hub-Komponenten sind:

- eine Rechnungsposition mit bekannten Komponenten aufklappbar darstellen;
- Komponenten mit exaktem Product-Hub-Namen und stabiler ID/SKU anzeigen;
- eine oder mehrere Komponenten auswählbar machen;
- Komponentenmenge editierbar machen;
- Elternprodukt und Ursprungsrechnung persistent mitführen;
- nur freigegebene beziehungsweise eindeutig zuordenbare Komponenten automatisch anbieten;
- bei fehlendem oder uneindeutigem Product-Hub-Mapping manuelle Auswahl/Eingabe ermöglichen;
- OpenAI niemals Komponenten erfinden oder als autoritative Quelle verwenden lassen.

Falls der bestehende Desktop-Read-Contract des Product Hub Komponenten noch nicht liefert, ist dieser Contract gezielt zu erweitern. Keine CSV-Datei als neue Laufzeitquelle einführen.

### 12.5 Notiz und OpenAI

Anzeigen und editierbar machen:

- intelligente Kurznotiz;
- optional interne Notiz;
- Lieferscheintext.

OpenAI erhält erst den zuvor deterministisch aufgelösten Kontext:

- Kunde;
- Ausgangsreferenzen;
- ausgewählte exakte Produkte/Komponenten;
- Mengen;
- E-Mail-Text, falls vorhanden;
- Versandmodus;
- Fälligkeitsgrund.

OpenAI darf zusammenfassen und Formulierungen vorschlagen, aber keine Adresse, Kundenidentität, SKU, Komponente, Menge oder Referenz festlegen, wenn diese nicht aus den Fachsystemen stammt.

Die strukturierte Ausgabe soll mindestens enthalten:

- kurze deutsche Zusammenfassung;
- empfohlener Lieferscheintext;
- erkannter Reklamationsgrund;
- Unsicherheiten/Warnungen.

### 12.6 Aktionen

Mindestens:

- `Speichern – auf nächste Bestellung warten`;
- `Sofort separat versenden`;
- `Lieferschein-Vorschau`;
- `Abbrechen`.

Beim Bearbeiten bestehender Fälle zusätzlich:

- Änderungen speichern;
- Versandmodus umstellen, sofern noch nicht gedruckt;
- Fall stornieren;
- erledigte/gedruckte Daten nur kontrolliert und nachvollziehbar behandeln.

## 13. E-Mail-Flow

### 13.1 Empfohlene Adresse

Verwende fachlich:

```text
nachlieferung@xeisworks.at
```

Begründung:

- `shipping@` ist eine unmittelbare Versandwarteschlange und akzeptiert derzeit jede ungelöste Mail;
- `backorder@` bedeutet eher Lieferrückstand;
- `forwarding@` ist missverständlich;
- `followup@` ist zu allgemein;
- `redelivery@` wäre möglich, ist aber im deutschsprachigen Arbeitsablauf weniger eindeutig.

### 13.2 Technische Trennung

Eine dedizierte Graph-Mailbox beziehungsweise ein dedizierter Graph-Ordner ist zu verwenden. Vorgeschlagener Secret-Key:

```text
MS_GRAPH_AFTERCARE_MAILBOX
```

Default:

```text
nachlieferung@xeisworks.at
```

Eine bloße Alias-Zustellung in die ungefilterte `shipping@`-Inbox ist nicht ausreichend, weil dort jede offene Mail sofort als OFFENE SENDUNG behandelt wird.

Die bisherige Erkennung von Reklamationsmails in `shop@` darf bestehen bleiben. Beide Quellen erzeugen denselben relationalen Nachlieferungsfall:

- `shop@`: nur erkannte Kandidaten, weiterhin manuell zu bestätigen;
- `nachlieferung@`: jede ungelöste Mail ist ein Nachlieferungskandidat, ebenfalls vor Aktivierung prüfbar.

### 13.3 Referenz- und Kontextauflösung

Vor der KI-Klassifikation beziehungsweise spätestens vor Anzeige des Popups:

1. `RE-26####` aus Betreff, Body und Thread extrahieren.
2. Fünfstellige Wix-Bestellnummer extrahieren.
3. sevDesk-Rechnung auflösen.
4. Wix-Bestellung auflösen.
5. stabile Kunden-IDs ergänzen.
6. Lieferadresse laden.
7. exakte Produkte und Product-Hub-Komponenten laden.
8. erst danach OpenAI-Zusammenfassung erzeugen.

Idempotenzschlüssel bleibt die Graph-Message-ID. Thread-ID und Ursprungsreferenzen werden zusätzlich gespeichert.

## 14. Integration in OFFENE SENDUNGEN und XW-Flow

Nachlieferungen erscheinen in OFFENE SENDUNGEN nur, wenn sie:

- explizit auf **Sofort separat versenden** gesetzt wurden oder
- ihre 20-Tage-Frist erreicht haben.

Wartende Fälle dürfen den OFFENE-SENDUNGEN-Alarm nicht erhöhen.

Ein Nachlieferungsfall in OFFENE SENDUNGEN:

- trägt ein sichtbares Badge `NACHLIEFERUNG`;
- zeigt alle Ursprungsreferenzen;
- ist wie andere Sendungen editierbar;
- nutzt dasselbe Popup beziehungsweise dieselben editierbaren Kernkomponenten, ohne Statussemantik zu verlieren;
- synchronisiert Änderungen zurück zum führenden Dispatch;
- markiert bei Erledigung die enthaltenen Nachlieferungsfälle als erledigt;
- darf bei neuer Bestellung vor Druck wieder aus OFFENE SENDUNGEN verschwinden und an die Rechnung gebunden werden.

Da OFFENE SENDUNGEN bereits nach XW-Flow gespiegelt werden, müssen fällige beziehungsweise sofortige Nachlieferungen darüber auch in XW-Flow sichtbar werden. Es ist zu prüfen, dass `source_type`, Badge, Ursprungsreferenzen, Bearbeitung und Erledigt-Status verlustfrei übertragen werden.

Für diesen Umbau sind Änderungen im Repository XW-Flow nur dann vorzunehmen, wenn der bestehende generische Sendungsvertrag die benötigten Felder nicht transportieren kann. Falls XW-Flow geändert werden muss, dort ebenfalls die jeweiligen Repository-Regeln einhalten, testen, committen und nach `origin/main` pushen.

## 15. Manager „Lieferkorrekturen“

Der vorhandene Manager bleibt erhalten, wird aber von einer überwiegend lesenden Ansicht zu einer echten Verwaltung erweitert.

Erforderlich:

- Filter `Zu prüfen`, `Wartet`, `Fällig`, `Erledigt`, `Alle` erhalten;
- Nachlieferung öffnen/bearbeiten;
- vollständige Adresse anzeigen;
- ausgewählte Produkte/Komponenten anzeigen;
- Ursprungs- und Zielreferenzen anzeigen;
- Erstellungsdatum und Fälligkeit anzeigen;
- Versandmodus anzeigen;
- Status in OFFENE SENDUNGEN anzeigen;
- Lieferschein-Vorschau;
- nachvollziehbarer Druck-/Fehlerstatus;
- keine zweite abweichende Produkt- oder Adressmaske bauen, sondern denselben Nachlieferungsdialog verwenden.

## 16. Gemeinsamer Business-Context-Resolver

Die kürzlich verbesserte Auflösung aus OFFENE SENDUNGEN ist in eine wiederverwendbare Schicht zu überführen oder über eine stabile öffentliche Schnittstelle bereitzustellen.

Der Resolver erhält beliebige Kombinationen aus:

- sevDesk-Rechnungsnummer oder -ID;
- Wix-Bestellnummer oder -ID;
- E-Mail-Text;
- Kunden-E-Mail;
- bereits bekannten IDs.

Er liefert strukturiert:

- normalisierte Referenzen;
- Rechnung und Rechnungspositionen;
- Wix-Bestellung und Positionen;
- sevDesk-Kontakt-ID;
- Wix-`contactId`;
- Kundenname und E-Mail;
- beste Lieferadresse samt Quelle;
- exakte Produktzeilen;
- Product-Hub-Auflösung und Komponenten;
- Warnungen und Konfidenz der fachlichen Zuordnung.

Priorität der Produktquellen:

1. exakte sevDesk-Rechnungsposition;
2. eindeutig zugeordnete Wix-Position;
3. Product-Hub-Komponente beziehungsweise kanonisches Produkt;
4. manuelle Eingabe;
5. KI-Text ausschließlich als unverbindlicher Hinweis.

## 17. Konfiguration

Bestehende Konfiguration:

```yaml
customer_aftercare:
  enabled: true
  b2b:
    wait_for_next_order: true
    max_wait_days: 20
```

Die Implementierung muss die vorhandenen Flags tatsächlich berücksichtigen. Derzeit vorhandene, aber nicht verwendete Flags wie `enabled`, `ai.enabled`, `min_confidence_for_prefill` und `b2b.wait_for_next_order` sind im Zuge des Umbaus konsistent zu verdrahten oder mit klarer Begründung zu entfernen. Keine wirkungslosen Konfigurationsoptionen belassen.

Sinnvolle Ergänzungen:

```yaml
customer_aftercare:
  mailbox: nachlieferung@xeisworks.at
  b2b:
    wait_for_next_order: true
    max_wait_days: 20
  shipping:
    allow_immediate: true
    attach_asap_before_print: true
```

Konfigurationsnamen dürfen an bestehende Konventionen angepasst werden.

## 18. Idempotenz, Konkurrenz und Wiederanlauf

Folgende Operationen müssen atomar beziehungsweise idempotent sein:

- Anlage aus derselben Graph-Mail;
- Anlage aus demselben Rechnungsbutton bei Doppelklick;
- Fristübergang nach 20 Tagen;
- Erzeugung des OFFENE-SENDUNGEN-Falls;
- Zusammenfassung mehrerer Cases in einen Dispatch;
- Claim durch eine neue Bestellung;
- Rückzug eines noch ungedruckten ASAP-Falls;
- Lieferscheingenerierung;
- Lieferscheindruck;
- Erledigt-Rückmeldung;
- Wiederanlauf nach App-Absturz;
- parallele START-Läufe auf mehreren PCs.

PostgreSQL-Advisory-Locks beziehungsweise vergleichbare transaktionale Sperren sind für Dispatch- und Claim-Operationen zu nutzen. Ein reiner In-Memory-Lock reicht im Mehr-PC-Betrieb nicht.

Empfohlene Idempotenzschlüssel:

- Mailfall: Graph-Message-ID;
- Rechnungsanlage: Ausgangs-sevDesk-Rechnungs-ID plus Falltyp beziehungsweise expliziter Case-Key;
- ASAP-Sendung: Dispatch-UUID;
- Beilage: Dispatch-UUID plus Zielrechnungs-ID;
- Dokument: Dispatch-UUID plus Inhaltsfingerprint.

## 19. Sicherheits- und Qualitätsregeln

- Keine Netzwerkaufrufe im Qt-UI-Thread.
- OpenAI-Ausfall darf die manuelle Erfassung nicht verhindern.
- Fehlende Adresse darf keinen Druck zulassen.
- Name allein darf keinen Kunden automatisch matchen.
- Bereits gedruckte Nachlieferung darf nicht erneut automatisch zugeordnet werden.
- Manuelle Änderungen dürfen beim Refresh nicht überschrieben werden.
- Keine automatische Rechnung, kein Label und kein Lieferschein allein aufgrund einer KI-Antwort.
- Keine stillen Steuer- oder Preisannahmen in der bestehenden Zusatzrechnungslogik.
- Keine zweite Lieferschein-PDF-Implementierung erzeugen.
- Keine neuen JSON-Schattenbestände als Quelle der Wahrheit.

## 20. Umsetzungsschritte

### Phase A – Domäne und Migration

1. Bestehendes Modell und Migration `007_customer_aftercare` analysieren.
2. Neue additive Migration erstellen.
3. Case-, Item- und Dispatch-Struktur ergänzen.
4. Repository-Methoden für Erstellung, Bearbeitung, Bündelung, Claims und Statusübergänge implementieren.
5. Fristberechnung auf `created_at + 20 Tage` korrigieren.

### Phase B – Gemeinsame Kontextauflösung

1. Referenz-, Kunden-, Adress- und Produktauflösung aus OFFENE SENDUNGEN wiederverwendbar machen.
2. sevDesk- und Wix-Kundenkennungen vervollständigen.
3. Product-Hub-Komponenten-Read-Contract ergänzen, falls nötig.
4. Quellen und Warnungen strukturiert liefern.

### Phase C – Rechnungsaktion und Popup

1. Wix- und Mail-Icons nur aus der Tabellenspalte AKTIONEN entfernen.
2. Nachlieferungsicon ergänzen.
3. Popup mit Hintergrundladen, Produktauswahl, Komponenten, Adresse, Notiz und Versandmodus implementieren.
4. Manuelle Positionen und Teilmengen ermöglichen.
5. Vorschau und Validierung implementieren.

### Phase D – Mail-Ingestion und KI

1. Dedizierte Nachlieferungs-Mailbox ergänzen.
2. Shop-Mail-Erkennung kompatibel halten.
3. Referenzen zuerst deterministisch auflösen.
4. OpenAI-Schema und Zusammenfassung auf angereicherten Kontext umstellen.
5. Manuelle Bestätigung beibehalten.

### Phase E – Trigger und OFFENE SENDUNGEN

1. Sofortmodus anbinden.
2. 20-Tage-Übergang anbinden.
3. Verknüpften statt losen Versandfall erzeugen.
4. Alarm, Offen/Erledigt und XW-Flow-Sync prüfen.
5. Rückzug vor Druck bei später Folgebestellung implementieren.

### Phase F – START-Integration

1. Synchronen Nachlieferungs-Preflight pro Rechnung ergänzen.
2. Stabile Kundenkennungen matchen.
3. Mehrere Fälle bündeln.
4. Gemeinsamen Lieferschein erzeugen.
5. Reihenfolge Lieferschein -> Rechnung -> Label erzwingen.
6. Claims, Retry und Fehlerzustände persistieren.

### Phase G – Manager und Abschluss

1. Manager auf denselben Bearbeitungsdialog umstellen.
2. Status, Referenzen, Adresse und Dispatch anzeigen.
3. Tests und Regressionen ausführen.
4. Dokumentation bei tatsächlichen Abweichungen aktualisieren.

## 21. Verbindliche Akzeptanztests

### CREATE-01 – Erstellung aus Rechnung

Gegeben ist eine konkrete sevDesk-Rechnung mit Wix-Referenz. Beim Klick auf das Nachlieferungsicon werden Kunde, Lieferadresse und exakte Rechnungspositionen geladen. Ausgewählte Positionen werden mit Ausgangsreferenzen persistent gespeichert.

### CREATE-02 – Doppelklick/Retry

Ein unbeabsichtigter Doppelklick oder Wiederanlauf erzeugt keinen doppelten Nachlieferungsfall ohne bewusste Benutzerbestätigung.

### DUE-01 – Fristursprung

Ein Fall mit `created_at = 01.10.2026 10:00` erhält `due_at = 21.10.2026 10:00`, unabhängig davon, wann er bestätigt wird.

### DUE-02 – Bereits abgelaufen bei Bestätigung

Wird ein mehr als 20 Tage alter Mailfall bestätigt, erscheint er unmittelbar und genau einmal in OFFENE SENDUNGEN.

### MATCH-01 – sevDesk-Kontakt

Eine neue Rechnung desselben sevDesk-Kontakts bindet passende Nachlieferungen, auch wenn keine Wix-Bestellung vorhanden ist.

### MATCH-02 – Wix-Kontakt

Eine neue Wix-Bestellung mit identischer `contactId` bindet passende Nachlieferungen.

### MATCH-03 – E-Mail-Fallback

Ohne stabile IDs darf eine identische normalisierte E-Mail matchen.

### MATCH-04 – Name allein

Gleicher Name ohne ID- oder E-Mail-Match löst niemals automatisch aus.

### PRODUCT-01 – Teilmenge

Von einer Rechnungsposition mit Menge 3 kann Menge 1 nachgeliefert werden.

### PRODUCT-02 – Product-Hub-Komponente

Für ein Set kann eine einzelne Product-Hub-Stimme ausgewählt und mit Elternprodukt sowie Ursprungsrechnung gespeichert werden.

### PRODUCT-03 – Manuell

Eine freie Produktzeile kann hinzugefügt, bearbeitet, gespeichert und auf dem Lieferschein ausgegeben werden.

### ADDRESS-01 – Wix-Versandadresse

Bei eindeutiger Wix-Bestellung wird die Versandadresse verwendet, nicht blind die Rechnungsadresse.

### ADDRESS-02 – Manuelle Korrektur

Eine manuell korrigierte Adresse bleibt nach Refresh und App-Neustart erhalten.

### BUNDLE-01 – Mehrere Ursprünge

Zwei offene Nachlieferungen desselben Kunden werden zu einem Lieferschein gebündelt. Beide Ursprungsrechnungen und Bestellungen bleiben sichtbar.

### PRINT-01 – Reihenfolge

Bei passender Folgebestellung lautet die physische Reihenfolge exakt:

```text
Nachlieferungs-Lieferschein -> neue Rechnung -> ein Label
```

### PRINT-02 – Lieferscheinfehler

Schlägt der Lieferscheindruck fehl, werden neue Rechnung und Label für diesen Vorgang nicht gedruckt. Der Fall bleibt retryfähig.

### ASAP-01 – Sofortmodus

`Sofort separat versenden` erhöht sofort den OFFENE-SENDUNGEN-Alarm und erzeugt genau einen verknüpften Versandfall.

### ASAP-02 – 20 Tage

Nach exakt 20 Kalendertagen erscheint ein wartender Fall genau einmal in OFFENE SENDUNGEN.

### ASAP-03 – Späte Folgebestellung vor Druck

Ein bereits sichtbarer, aber ungedruckter ASAP-Fall wird bei neuer passender Bestellung aus OFFENE SENDUNGEN zurückgezogen und vor deren Rechnung gedruckt.

### ASAP-04 – Keine Umbindung nach Druck

Ein bereits gedruckter beziehungsweise final geclaimter ASAP-Fall wird nicht mehr an eine spätere Bestellung gebunden.

### DONE-01 – Statusrückmeldung

Das Erledigen in OFFENE SENDUNGEN markiert Dispatch und enthaltene Nachlieferungsfälle konsistent als erledigt.

### MAIL-01 – Dedizierte Mailbox

Eine Mail an `nachlieferung@xeisworks.at` erzeugt genau einen prüfbaren Nachlieferungsfall, aber noch keinen Druck und kein Label.

### MAIL-02 – Referenzanreicherung

Eine Mail mit `RE-26####` oder fünfstelliger Wix-Nummer wird vor der KI-Zusammenfassung um Kunde, Lieferadresse und exakte Produkte angereichert.

### FLOW-01 – XW-Flow

Eine sofortige oder nach 20 Tagen fällige Nachlieferung ist über die bestehende OFFENE-SENDUNGEN-Synchronisierung in XW-Flow sichtbar und nach Erledigung dort wie in XW-Office konsistent erledigt.

### CONCURRENCY-01 – Zwei PCs

Zwei parallele START-Läufe können denselben Nachlieferungsfall nicht an zwei Rechnungen binden oder zweimal drucken.

## 22. Relevante Regressionstests

Mindestens ausführen und bei Bedarf erweitern:

- `tests/unit/test_customer_aftercare_service.py`
- `tests/unit/test_customer_aftercare_trigger_service.py`
- `tests/unit/test_customer_aftercare_inbox_service.py`
- `tests/unit/test_customer_aftercare_ai_classifier.py`
- `tests/unit/test_customer_aftercare_invoice_service.py`
- `tests/unit/test_offene_sendungen_service.py`
- `tests/ui/test_customer_aftercare_manager_dialog.py`
- `tests/ui/test_customer_aftercare_review_dialog.py`
- `tests/ui/test_offene_sendungen_dialog.py`
- `tests/ui/test_rechnungen_view_smoke.py`
- START-/Invoice-Processing-Tests für Lieferschein, Rechnung und Label;
- Product-Hub-Client-/Contract-Tests für Komponenten;
- Migrations- und Repository-Tests;
- XW-Flow-Bridge-Tests, falls der Vertrag erweitert wird.

Tests sind über die Projektumgebung zu starten, beispielsweise:

```powershell
.\.venv\Scripts\python.exe -m pytest ...
```

## 23. Definition of Done

Der Umbau ist erst abgeschlossen, wenn:

- eine Nachlieferung direkt aus einer Rechnung erstellt werden kann;
- Produkte, Teilmengen, Product-Hub-Komponenten und manuelle Zeilen auswählbar sind;
- Kunde, genaue Lieferadresse und Ursprungsreferenzen zuverlässig gespeichert werden;
- OpenAI ausschließlich auf angereichertem Fachkontext zusammenfasst;
- die Frist ab `created_at` läuft;
- eine passende neue Bestellung den Fall synchron und atomar bindet;
- mehrere Fälle auf einem gemeinsamen Lieferschein erscheinen;
- dieser Lieferschein vor der neuen Rechnung gedruckt wird;
- nach 20 Tagen oder im Sofortmodus OFFENE SENDUNGEN samt Alarm und XW-Flow greift;
- ein ungedruckter ASAP-Fall noch von einer neuen Bestellung eingesammelt werden kann;
- nach Druck keine Doppelzuordnung möglich ist;
- der relationale Nachlieferungsfall die Quelle der Wahrheit bleibt;
- relevante Tests grün sind;
- `main` nach `origin/main` gepusht wurde.

