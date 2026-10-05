# XW-Flow: Offene Sendungen per Android-Share und Zwischenablage

**Analyse- und Umsetzungsempfehlung für 5.6 terra**

**Stand:** 5. Oktober 2026

**Betroffene Repositories:** `XW-Flow` und `XW-Office`

## 1. Entscheidung in Kurzform

Empfohlen wird eine echte zweite Eingangsquelle für `OFFENE SENDUNGEN`:

1. XW-Flow erhält einen persistenten Datentyp `ShipmentCase` und ein Share-Ziel `Lieferung`.
2. XW-Office liest offene Fälle künftig aus zwei Quellen:
   - unverändert aus dem Postfach `shipping@xeisworks.at`,
   - zusätzlich über eine abgesicherte XW-Flow-Bridge.
3. Der zentrale mobile `+`-Button erhält:
   - `Lieferung` mit `VehicleTruckCubeRegular`,
   - `Zwischenablage` mit `ClipboardPasteRegular`.
4. Ein aus der Zwischenablage gelesener Text wird als normaler lokaler Share-Draft angelegt und anschließend im bereits vorhandenen Share-Router wahlweise als Aufgabe, `Wenn Zeit ist`, Witz, Pinnwand-Eintrag oder Lieferung gespeichert.

Die Variante „XW-Flow schickt im Hintergrund nur eine E-Mail an `shipping@...`“ ist höchstens als kurzfristiger Prototyp geeignet, nicht als Zielarchitektur. Sie würde die bestehende Ein-Quellen-Abhängigkeit nicht beseitigen und hätte unnötige Probleme bei Sendestatus, Wiederholungen, Anhängen und dem Rückkanal `Erledigt`.

## 2. Bestehender Android-Share-Flow in XW-Flow

### 2.1 Aufnahme durch die installierte PWA

Der Web-App-Manifestvertrag wird zentral in `frontend/src/pwa/shareTarget.ts` definiert:

- Action: `/share-target-v2`
- Methode: `POST`
- Encoding: `multipart/form-data`
- Felder: `title`, `text`, `url`, `media`
- akzeptierte Inhalte: Bilder, Audio, Video, PDF und Textdateien

`frontend/src/sw.ts` fängt den POST im Service Worker ab, normalisiert Android-Abweichungen beim Multipart-Format, wendet Größen- und Mengenlimits an und speichert den Inhalt zuerst lokal in IndexedDB. Danach wird zu `/share-intent?share=<localId>` umgeleitet.

Das ist die richtige Grundlage und soll nicht durch einen zweiten Share-Intake ersetzt werden. Laut Web-Share-Target-Dokumentation ist genau diese Kombination aus installiertem PWA-Share-Target, `POST`, `multipart/form-data` und Service-Worker-Verarbeitung für Dateien vorgesehen. Der Share-Handler soll außerdem offline erreichbar sein ([web.dev: OS integration](https://web.dev/learn/pwa/os-integration), [web.dev: Workbox share targets](https://web.dev/articles/workbox-share-targets)).

### 2.2 Lokaler Share-Draft

`frontend/src/offline/db.ts` besitzt bereits `ShareDraftEntry` mit:

- stabiler `localId`,
- `clientRequestId` für Idempotenz,
- Text, Titel, URL und Dateien,
- Zuständen von `editing` bis `completed` beziehungsweise `attention`,
- persistenter Completion-Receipt.

Der Draft verhindert Datenverlust, bevor ein Ziel gewählt und serverseitig bestätigt wurde. Dieses Modell eignet sich auch für Clipboard-Text und eine direkt über `+` begonnene Lieferung.

### 2.3 Zielauswahl

`frontend/src/routes/ShareIntentPage.tsx` routet derzeit zu:

- Pinnwand,
- Aufgabe,
- Wenn Zeit ist / Sammeln,
- Witz,
- Melodie,
- Marketing.

Aufgabe und `Wenn Zeit ist` erzeugen Tasks mit unterschiedlichem `planning_mode`. Witze und Pinnwände verwenden eigene APIs. Erst nach erfolgreicher Speicherung erhält der Draft eine Receipt. `Lieferung` passt deshalb fachlich als weiteres explizites Ziel in diesen Router.

### 2.4 Mobile zentrale Plus-Schaltfläche

`frontend/src/components/AppShell.tsx` zeigt derzeit acht kreisförmige Aktionen in einem radialen Drei-Reihen-Fächer. Der Fokus wird beim Öffnen in das Menü versetzt und per Tab eingeschlossen. Zwei zusätzliche, unbeschriftete Kreise würden den Fächer auf kleinen Smartphones überladen und die Zielerkennung verschlechtern.

Empfehlung: den mobilen Fächer in ein beschriftetes Action-Sheet beziehungsweise ein kompaktes 2-Spalten-Raster oberhalb der Bottom-Navigation umbauen. Die vorhandenen Aktionen bleiben erhalten. Dadurch haben auch `Lieferung` und `Zwischenablage` verständliche Labels und mindestens 44 px große Touch-Ziele. Fokusfalle, Escape-Verhalten, Backdrop und `aria-label` bleiben erhalten.

## 3. Bestehende Erkennung „Offene Sendungen“ in XW-Office

Die maßgebliche Implementierung ist `src/xw_office/services/sendungen/service.py`.

### 3.1 Aktuelle Quelle

`OffeneSendungenService.refresh_from_graph()` liest ausschließlich das konfigurierte Shared Mailbox Postfach, standardmäßig `shipping@xeisworks.at`.

Im dedizierten Postfach gilt bewusst eine sehr einfache Regel:

- jede Mail mit ID,
- deren Outlook-Follow-up-Flag nicht `complete` ist,
- ist eine offene Sendung.

Es gibt keine weitere inhaltliche Vorfilterung nach Betreff oder Absender. Erst beim Öffnen werden Body beziehungsweise Thread nachgeladen und Adresse, Produkte, Bestellnummer und Falltyp per OpenAI oder Fallback extrahiert.

### 3.2 Lokaler Cache und Sonderfälle

Die offenen Fälle liegen als JSON unter `daily_business.offene_sendungen.cases`. Daneben existieren lokale Maps für:

- erledigte IDs,
- Extraktionen,
- manuell korrigierte Felder,
- Wix-Adressen.

`create_manual_case()` zeigt bereits, dass Fälle ohne Mail grundsätzlich in denselben Label-/Lieferschein-Prozess eingeschleust werden können. Aktuell wird ihre Herkunft allerdings indirekt über `sender == "lieferkorrektur"` erkannt.

Das reicht für eine zweite externe Quelle nicht aus:

- `refresh_from_graph()` bewahrt derzeit ausschließlich diesen einen Sender-Sentinel und würde andere Nicht-Mail-Fälle verwerfen.
- `load_open_cases()` bewahrt bei einem Mailbox-Wechsel ebenfalls nur diesen Sentinel.
- `_full_case_text()` versucht für jeden Fall Graph-Zugriffe, wenn Graph konfiguriert ist.
- `mark_done()` versucht für jeden erledigten Fall einen Outlook-Flag-PATCH. Das ist für manuelle und künftige XW-Flow-Fälle fachlich falsch.

Vor dem Anschluss von XW-Flow muss die Herkunft daher ein echtes Feld werden und darf nicht länger im Absender versteckt sein.

## 4. Zielarchitektur

```text
Android Teilen ─┐
                ├─> lokaler ShareDraft ─> Share-Router ─> ShipmentCase in XW-Flow
Android Copy ───┘                                  │
                                                   │ HTTPS / Bridge-Secret
shipping@ ─> Microsoft Graph ──────────────────────┼─> OffeneSendungenService
                                                   │
                                                   └─> gemeinsamer Dialog, Label,
                                                       Lieferschein, Erledigt
```

XW-Flow ist für per Share oder Clipboard erfasste Sendungen die persistente Quelle. XW-Office bleibt das ausführende System für Prüfung, Etikett, Lieferschein und Abschluss. Der bestehende Mailweg bleibt fachlich unverändert.

### 4.1 XW-Flow-Datenmodell

Neue Tabelle `shipment_cases`:

| Feld | Zweck |
|---|---|
| `id` UUID | technische Fall-ID |
| `client_request_id` UUID, unique | Idempotenz bei Doppeltipp/Retry |
| `source_kind` | `pwa_share`, `clipboard`, `mobile_manual` |
| `title` | kurze sichtbare Bezeichnung |
| `body_text` | unveränderter geteilter beziehungsweise eingefügter Text |
| `source_url` nullable | mitgeteilter Link |
| `status` | `open`, `completed` |
| `created_at`, `updated_at` | Synchronisation und Sortierung |
| `completed_at` nullable | Abschlussnachweis |

Optional erst in einer Folgephase: referenzierte Dateien in Object Storage. Für Phase 1 muss eine Lieferung mindestens lesbaren Text, Titel oder URL enthalten. Bei einem reinen Bild-Share zeigt die UI klar `Bitte Liefertext ergänzen`; sie darf weder das Bild still verwerfen noch eine leere Sendung erzeugen.

Adress- oder Produktfelder sollen beim Capture noch nicht verpflichtend sein. Der bestehende XW-Office-Extraktionsdialog ist bereits der fachliche Prüfpunkt und kann den Rohtext verarbeiten.

### 4.2 XW-Flow-API

Benutzerroute, geschützt durch die vorhandene Session:

```http
POST /api/v1/shipment-cases
{
  "client_request_id": "uuid",
  "source_kind": "pwa_share|clipboard|mobile_manual",
  "title": "...",
  "body_text": "...",
  "source_url": "..."
}
```

Verhalten:

- gleiche `client_request_id` plus gleiche Nutzdaten: vorhandenen Fall zurückgeben,
- gleiche `client_request_id` plus abweichende Nutzdaten: `409 Conflict`,
- Rohtext oder personenbezogene Daten nie loggen,
- Antwort enthält mindestens `id`, `status`, `created_at`.

Separate Office-Bridge, nicht durch Browser-Session, sondern durch ein eigenes Secret geschützt:

```http
GET   /api/v1/office-bridge/shipment-cases?status=open&cursor=<page-cursor>
PATCH /api/v1/office-bridge/shipment-cases/{id}
{ "status": "completed" }
```

Für die Bridge ein neues Secret wie `XW_OFFICE_BRIDGE_SECRET` verwenden. Nicht `XW_FLOW_API_SECRET` wiederverwenden: Dieser Name bezeichnet in XW-Office derzeit tatsächlich den Zugriff auf die separate `wix-sevdesk-api`-Analytics-Schnittstelle. Ebenso eine neue, eindeutig benannte Basis-URL einführen, zum Beispiel `XW_FLOW_SHIPPING_API_BASE_URL`.

Die Bridge muss fail-closed sein, mit konstantzeitlichem Secret-Vergleich, begrenzter Seitengröße und ohne Nutzdaten in Access-/Fehlerlogs. Abgeschlossene Fälle sollten nach einer festgelegten Frist, empfohlen 90 Tage, inhaltlich gelöscht oder minimiert werden.

### 4.3 XW-Office-Quellenmodell

`SendungCase` erhält mindestens:

```python
source_type: Literal["graph_mail", "manual", "xw_flow_share"]
source_id: str
```

Die sichtbare/interne ID sollte namespaced sein:

- `graph:<message-id>` oder migrationsverträglich die bisherige Graph-ID,
- `manual:<id>`,
- `flow:<shipment-case-uuid>`.

Der Absender bleibt ein normales Anzeigefeld. Er darf nicht länger die Quelle codieren.

`refresh_from_graph()` wird zu einer quellenbewussten Zusammenführung:

1. lokale Nicht-Graph-Fälle laden,
2. aktuelle Graph-Fälle ersetzen,
3. alle Seiten des vollständigen Open-Snapshots aus XW-Flow über einen neuen `XwFlowShipmentClient` abrufen und per `source_id` ersetzen,
4. deduplizieren und atomar speichern,
5. bei Ausfall einer Quelle deren zuletzt erfolgreichen Cache behalten.

Wichtig: Erst nachdem alle Seiten des Open-Snapshots erfolgreich geladen wurden, darf die lokal bekannte Menge der Flow-Fälle ersetzt werden. Ein erfolgreicher leerer Abruf und ein fehlgeschlagener Abruf dürfen nicht gleich behandelt werden. Sonst verschwinden bei einem Netzwerkfehler offene Fälle aus dem Alarm.

`mark_done()` dispatcht nach Quelle:

- `graph_mail`: zuerst Outlook-Flag bestätigen lassen, dann lokal erledigt markieren,
- `xw_flow_share`: zuerst XW-Flow-Status bestätigen lassen, dann lokal erledigt markieren,
- `manual`: ausschließlich lokal erledigt markieren.

Für `done=False` gilt spiegelbildlich ein expliziter Reopen je Quelle. Der aktuelle unbeabsichtigte Graph-Zugriff für manuelle Fälle wird dabei mitbehoben.

`_full_case_text()` greift nur bei `graph_mail` auf Graph zu. Für `manual` und `xw_flow_share` ist der persistierte `body` beziehungsweise `thread_text` die Quelle.

### 4.4 Alarm und Aktualisierung

Der bestehende Alarm-Button im Untermenü `RECHNUNGEN` zählt weiterhin `OffeneSendungenService.open_count()`. Der Service liefert künftig die vereinigte, deduplizierte Menge. Dadurch braucht die UI keine Quellenkenntnis.

Graph- und XW-Flow-Abruf laufen im bestehenden Background-Worker-Pfad. Weder Badge-Refresh noch Öffnen des Dialogs darf blockierende HTTP-Aufrufe im GUI-Thread ausführen. Im Dialog kann die Quelle als kleine Kennzeichnung `Mail`, `Share` oder `Manuell` angezeigt werden; Verarbeitungsschritte bleiben identisch.

## 5. Clipboard-Text auf Android

### 5.1 Browsergrenzen

`navigator.clipboard.readText()` ist nur in einem sicheren HTTPS-Kontext verfügbar und kann mit `NotAllowedError` abgelehnt werden. Clipboard-Lesen ist eine sensible API; Browser verlangen je nach Implementierung eine aktuelle Benutzeraktion, eine Berechtigung oder einen sichtbaren Paste-Schritt ([MDN: Clipboard API](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard_API), [MDN: readText](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/readText), [W3C Clipboard API](https://www.w3.org/TR/clipboard-apis/)).

Daraus folgen zwei verbindliche UI-Regeln:

1. `readText()` muss unmittelbar im Click-Handler des Buttons `Zwischenablage` ausgeführt werden. Erst danach darf navigiert werden. Ein Aufruf nach einem Route-Wechsel kann die kurzlebige User-Aktivierung verlieren.
2. Bei nicht unterstützter API, verweigerter Berechtigung oder leerem Ergebnis erscheint ein normales Textfeld mit dem Hinweis: `Textfeld lange drücken und Einfügen wählen.` Das Feature darf nicht von einer dauerhaften Clipboard-Berechtigung abhängen.

Ein automatisches Lesen beim Öffnen des `+`-Menüs ist aus Datenschutz- und Browsergründen ausdrücklich nicht vorgesehen.

### 5.2 Wiederverwendung des Share-Routers

Neue gemeinsame Frontend-Funktion, beispielsweise `createTextShareDraft()`:

1. Text trimmen und gegen eine sinnvolle Obergrenze prüfen,
2. `ShareDraftEntry` mit neuer `localId` und `clientRequestId` anlegen,
3. `source` um `clipboard` beziehungsweise `mobile_manual` erweitern,
4. Draft in IndexedDB speichern,
5. zu `/share-intent?share=<id>` navigieren.

Der Router zeigt danach dieselben Ziele wie bei Android-Share. Damit gibt es keine separaten Implementierungen für „Clipboard als Task“, „Clipboard als Witz“ usw.

`ShareIntentPage` sollte den übernommenen Text editierbar anzeigen. Das ist zugleich die Fallback-Fläche für manuelles `Einfügen` und erlaubt, einen unverständlichen WhatsApp-Ausschnitt vor dem Speichern zu kürzen oder zu ergänzen.

### 5.3 Direkter Button `Lieferung`

Der `Lieferung`-Button im `+`-Menü erzeugt einen leeren `mobile_manual`-Draft und öffnet denselben Router mit vorausgewähltem Ziel, zum Beispiel:

```text
/share-intent?share=<id>&destination=shipment
```

Im Formular stehen Textfeld und ein sichtbarer Button `Aus Zwischenablage einfügen` bereit. Dieser Button ruft wiederum `readText()` direkt aus seinem Click-Handler auf. So funktionieren beide Wege:

- WhatsApp-Text kopieren → `+` → `Zwischenablage` → Ziel `Lieferung`,
- `+` → `Lieferung` → `Aus Zwischenablage einfügen` oder Text manuell eingeben.

## 6. Konkreter Implementierungsplan für 5.6 terra

### Phase A – Verträge und persistente XW-Flow-Quelle

1. In XW-Flow Modell, Enum, Alembic-Migration und Pydantic-Schemas für `ShipmentCase` anlegen.
2. Session-geschützte Create-Route mit Unique Constraint auf `client_request_id` implementieren.
3. Office-Bridge-Router mit eigenem Secret, Cursor/Paginierung und idempotentem Complete/Reopen implementieren.
4. Konfiguration und Deployment-Dokumentation ausschließlich um Variablennamen ergänzen; keine Secretwerte ausgeben.
5. Backend-Tests für Authentifizierung, Idempotenz, Konflikt, Paging, Complete und Reopen schreiben.

### Phase B – Gemeinsamer Share-/Clipboard-Router

1. `CaptureOutboxSource` um `clipboard` und `mobile_manual` ergänzen.
2. Gemeinsamen Helper zum Erzeugen eines Text-Drafts bauen.
3. `Destination` in `ShareIntentPage.tsx` um `shipment` ergänzen.
4. Textvorschau in ein editierbares Feld überführen und Änderungen laufend im Draft sichern.
5. Lieferung über `POST /api/v1/shipment-cases` speichern; erst nach bestätigter Antwort Receipt setzen.
6. Bei Fehlern Draft auf `attention` halten und einen klaren Retry anbieten.
7. Reine Datei-Shares für Phase 1 nicht still akzeptieren: Texteingabe verlangen und vorhandene Datei im lokalen Draft behalten.

### Phase C – Mobiles Erfassungsmenü

1. Radialen Acht-Aktionen-Fächer in ein beschriftetes mobiles Action-Sheet/2-Spalten-Raster umbauen.
2. `Lieferung` mit `VehicleTruckCubeRegular` ergänzen.
3. `Zwischenablage` mit `ClipboardPasteRegular` ergänzen.
4. Clipboard direkt im ursprünglichen Click-Handler lesen.
5. Bei `NotAllowedError`, fehlender API oder leerem Clipboard zum manuellen Paste-Textfeld weiterleiten.
6. Fokusfalle und visuelle Reihenfolge in einer einzigen Action-Definition statt in acht bis zehn einzelnen Refs pflegen.

### Phase D – XW-Office als Multi-Source-Consumer

1. Neuen Client `src/xw_office/services/sendungen/xw_flow_client.py` erstellen.
2. Separate Konfiguration und Secretregistrierung ergänzen.
3. `SendungCase` um echte Quellenfelder erweitern; alte Cache-Einträge migrationskompatibel als `graph_mail` interpretieren, den Sentinel `lieferkorrektur` als `manual`.
4. Graph-Refresh so umbauen, dass alle Nicht-Graph-Quellen erhalten bleiben.
5. XW-Flow-Refresh mit stale-on-error-Verhalten ergänzen.
6. `_full_case_text()` und `mark_done()` quellenabhängig machen.
7. Dialog optional um Quellen-Badge ergänzen, ohne den Label-/Lieferschein-Workflow zu duplizieren.
8. Badge/Alarm gegen die vereinigte Queue testen.

### Phase E – kontrollierter Rollout

1. XW-Flow Backend und Migration deployen.
2. Bridge-Secret und Basis-URL auf beiden Seiten konfigurieren.
3. Zuerst XW-Office mit leerer Flow-Quelle ausrollen.
4. Danach XW-Flow-Frontend mit `Lieferung` aktivieren.
5. Einen synthetischen Testfall per Android-Share und einen per WhatsApp-Copy erzeugen.
6. Beide in XW-Office öffnen, extrahieren, Label/Lieferschein prüfen und erledigen.
7. Kontrollieren, dass bestehende `shipping@`-Mails weiterhin unverändert erscheinen und erledigt werden.

## 7. Testmatrix und Abnahmekriterien

### Frontend

- Android teilt markierten Text an XW-Flow; `Lieferung` ist auswählbar.
- Android teilt URL plus Text; beides bleibt im Lieferfall erhalten.
- WhatsApp-Text wird kopiert; `+` → `Zwischenablage` öffnet den vorhandenen Zielrouter.
- Clipboard-Zugriff erlaubt, verweigert, nicht unterstützt und leer sind getestet.
- Manuelles Long-Press-`Einfügen` funktioniert als Fallback.
- Doppeltipp auf Speichern erzeugt wegen `client_request_id` nur einen Fall.
- Reiner Bild-Share erzeugt ohne ergänzten Text keine leere Lieferung.
- Ein fehlgeschlagener Request löscht den lokalen Draft nicht.
- Action-Sheet ist bei 320 px Breite vollständig bedienbar; Tab, Escape, Backdrop und Screenreader-Labels funktionieren.

### XW-Flow Backend

- Create ist ohne gültige User-Session nicht erreichbar.
- Office-Bridge ist ohne korrektes Bridge-Secret nicht erreichbar.
- Idempotenter Retry liefert denselben Datensatz.
- Abweichender Payload mit derselben Request-ID liefert `409`.
- Listenabfrage paginiert stabil und gibt keine abgeschlossenen Fälle als offen zurück.
- Complete und Reopen sind wiederholbar.
- Logs und Fehlermeldungen enthalten weder Clipboard-Text noch Adressdaten.

### XW-Office

- Graph-, Manual- und Flow-Fälle überleben jeden Refresh in ihrer jeweiligen Quelle.
- Ein Flow-Ausfall leert den Flow-Cache nicht.
- Ein erfolgreicher leerer Flow-Abruf entfernt beziehungsweise schließt nicht mehr offene Remote-Fälle korrekt.
- Gleichzeitiger Graph- und Flow-Refresh erzeugt keine Dubletten.
- `mark_done(graph)` patcht Outlook.
- `mark_done(flow)` patcht XW-Flow und nicht Outlook.
- `mark_done(manual)` führt keinen Netzwerkzugriff aus.
- Extraktion, Adresskorrektur, Etikett und Lieferschein funktionieren für Flow-Text identisch zum Mailtext.
- Der Alarm-Count ist die Summe der offenen, deduplizierten Fälle aller Quellen.

### Ende-zu-Ende-Abnahme

Erfüllt ist die Umsetzung erst, wenn folgender Ablauf auf dem echten Android-Gerät funktioniert:

1. Text in WhatsApp kopieren.
2. XW-Flow öffnen und zentral `+` → `Zwischenablage` wählen.
3. `Lieferung` auswählen und speichern.
4. XW-Office zeigt ohne Mailversand einen zusätzlichen Alarmfall unter `RECHNUNGEN` → `OFFENE SENDUNGEN`.
5. Der Fall lässt sich prüfen, drucken und erledigen.
6. Nach Refresh ist er weder in XW-Flow noch in XW-Office erneut offen.

## 8. Bewusst nicht empfohlen

### XW-Flow sendet für jeden Share eine Mail an `shipping@...`

Vorteil: sehr kleiner Umbau in XW-Office. Nachteile:

- weiterhin nur Mail als technische Quelle,
- Versandantwort kann bei Timeout unklar sein; blindes Retry riskiert Dubletten,
- Erledigt-Status existiert nur als Outlook-Flag,
- Share-Anhänge passen nicht zum heutigen textbasierten XW-Office-Import,
- zusätzlicher Mailverkehr und schlechtere fachliche Nachvollziehbarkeit.

Diese Variante darf nur als wegwerfbarer Spike dienen, wenn vor der eigentlichen Umsetzung die Android-Bedienung validiert werden soll.

### Automatisches Clipboard-Lesen beim Öffnen der App

Nicht umsetzen. Es widerspricht der erforderlichen sichtbaren Nutzerabsicht, ist browserabhängig und erzeugt unnötige Datenschutz- und Berechtigungsprobleme.

### Eigene Clipboard-Implementierung pro Ziel

Nicht umsetzen. Clipboard und Android-Share müssen beide denselben `ShareDraftEntry` und denselben Zielrouter verwenden. Sonst entstehen mindestens fünf unterschiedliche Fehler-, Retry- und Validierungspfade.

## 9. Leitplanken für 5.6 terra

- Beide Repositories vor jeder Phase auf `main` aktualisieren und getrennt testen/committen.
- Das geschützte Architekturarchiv in XW-Office nicht verändern.
- Keine bestehende Mailfunktion entfernen; Multi-Source ist zunächst additiv.
- Keine Produktionsinhalte oder Secretwerte in Tests, Logs oder Dokumentation aufnehmen.
- Bestehende Idempotenz- und Offline-Muster aus dem Share-Router wiederverwenden.
- UI-Erfolg erst nach serverseitig bestätigter Persistenz melden.
- Bei einer nicht erreichbaren Quelle den letzten bestätigten Zustand sichtbar behalten und einen Fehlerstatus anzeigen.
- Phase 1 textorientiert fertigstellen; Datei-/OCR-Unterstützung erst danach als eigener, testbarer Ausbau.
