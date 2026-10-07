# Bar- und Privatausgaben in XW-Office und XW-Flow

## Umbauskizze für Codex 5.6 Luna

Stand: 7. Oktober 2026

Betroffene Repositories:

- `C:\Users\bernh\GitHub\XW-Office`
- `C:\Users\bernh\GitHub\XW-Flow`

Diese Skizze ergänzt die bestehende mandantenfähige **Ausgabenprüfung**. Sie setzt voraus, dass in
XW-Office bereits die beiden obersten Bereiche **XeisWorks** und **WüdaraMusi** sowie darunter die
Reiter **Kontobewegungen**, **Fehlende Belege** und **Einstellungen** vorhanden sind.

---

## 1. Ziel und klare Empfehlung

Ausgaben, die nicht auf dem jeweiligen sevDesk-Standardkonto auftauchen, sollen unmittelbar beim
Entstehen erfasst werden können. Typische Beispiele:

- bar aus eigener Tasche bezahlt;
- mit privater Kreditkarte bezahlt;
- vom privaten Konto bezahlt;
- aus einer betrieblichen Barkasse bezahlt;
- Rechnung oder Kassenzettel zuerst nur als Foto, Screenshot, PDF, Text oder Android-Share
  vorhanden.

Die Funktion soll **keine zweite Buchhaltung** und auch keine automatische sevDesk-Buchung sein.
Sie ist ein gemeinsamer Eingangskorb mit anschließendem Prüf- und Erledigungsablauf.

### Architekturentscheidung

**XW-Flow wird die führende Datenquelle für manuell erfasste Ausgaben.** XW-Office liest und
bearbeitet diese Datensätze über eine authentifizierte Bridge.

Das ist sinnvoller als eine Speicherung in beiden Datenbanken:

1. XW-Flow besitzt bereits den mobilen `+`-Einstieg, den Android-Web-Share-Target, eine
   offlinefähige Share-Draft-Ablage und Uploads in privaten Objektspeicher.
2. XW-Office besitzt bereits einen abgesicherten Bridge-Client zu XW-Flow für offene Sendungen.
3. Ein gemeinsamer Datensatz verhindert Dubletten, Synchronisationskonflikte und abweichende
   Bearbeitungsstände.
4. Anhänge bleiben in XW-Flows privatem R2-Objektspeicher. XW-Office erhält nur kurzlebige,
   signierte Ansichts-URLs und speichert diese URLs niemals dauerhaft.

```text
XW-Flow mobile + / Android SHARE / Zwischenablage
                         |
                         v
              Expense Capture in XW-Flow
                + private R2-Anhänge
                         |
          X-XW-Office-Secret geschützte Bridge
                         |
                         v
 XW-Office > Ausgabenprüfung > XeisWorks oder WüdaraMusi
                         |
                prüfen / ergänzen / erledigen
```

Nicht umsetzen:

- keine direkten Schreibzugriffe einer Anwendung in die Datenbank der anderen;
- keine Kopie derselben Ausgabe in beiden Datenbanken;
- keine dauerhaften öffentlichen Beleg-URLs;
- keine automatische sevDesk-Buchung direkt nach einer mobilen Erfassung;
- keine automatische Einbeziehung ungeprüfter Vorgänge in UVA, Provisionen oder andere
  Auswertungen.

---

## 2. Fachliches Zielbild

### 2.1 Neue Tabelle in XW-Office

Im Reiter **Kontobewegungen** wird unterhalb der bestehenden sevDesk-Kontobewegungen in beiden
Mandantenbereichen eine zweite, klar getrennte Tabelle eingefügt:

> **Zusätzliche Ausgaben – bar oder privat bezahlt**

Sie darf nicht mit den Bankbewegungen zu einer einzigen Tabelle verschmolzen werden. Bankbewegung
und manuell erfasste Ausgabe haben unterschiedliche Quellen und einen unterschiedlichen
Lebenszyklus. Die optische Trennung verhindert, dass eine private Ausgabe versehentlich als bereits
vom Betriebskonto bezahlt verstanden wird.

Der Tabellenkopf enthält:

- links Titel und Anzahl offener Vorgänge;
- rechts einen großen, randlosen `+`-Icon-Button **Neue Ausgabe**;
- einen randlosen Aktualisieren-Icon-Button;
- optional einen Filter `Offen | Alle`.

Empfohlene Spalten:

| Spalte | Inhalt |
|---|---|
| Datum | Ausgaben-/Belegdatum, nicht Erfassungszeitpunkt |
| Empfänger | Händler, Lieferant oder Zahlungsempfänger |
| Zweck | kurze fachliche Beschreibung |
| Betrag | positiver Bruttobetrag, leicht rot getönt |
| USt. | `20 %`, `10 %`, `13 %`, `0 %`, `gemischt` oder `unbekannt` |
| Zahlungsart | privat bar, private Karte, privates Konto, Betriebskasse, sonstige |
| Kategorie | dieselben runden Kategorie-Buttons wie in der Ausgabenprüfung |
| Beleg | Büroklammer/Bild-Icon mit Anzahl, fehlender Beleg deutlich markiert |
| Prüfung | unvollständig, offen, geprüft, gebucht oder verworfen |
| Rückzahlung | offen, zurückgezahlt oder nicht erforderlich |
| Quelle | Mobil, Android Share, Zwischenablage oder Desktop |

Die Tabelle verwendet dieselbe Spaltenbreiten-Persistenz wie die vorhandenen Tabellen. Der initiale
Auto-Fit richtet jede Spalte nach Überschrift und aktuell längstem sichtbaren Wert aus; danach bleibt
jede Spalte per Maus veränderbar. Ein Refresh darf manuelle Breiten nicht überschreiben.

### 2.2 Desktop-Dialog über `+`

Der Dialog **Neue zusätzliche Ausgabe** bietet:

- Mandant, durch den geöffneten obersten Tab vorbelegt und normalerweise nicht umzuschalten;
- Kategorie, mit dem zuletzt verwendeten Wert für diesen Mandanten vorbelegt;
- Bruttobetrag und Währung (`EUR` als Standard);
- Ausgaben-/Belegdatum (`heute` als Standard);
- USt.-Behandlung;
- Zahlungsart;
- Empfänger;
- Zweck;
- optionale Notiz;
- Belegstatus `Beleg vorhanden`, `Beleg kommt später`, `kein Beleg erhältlich`;
- Dateiauswahl für Bild/PDF/Text;
- Aktion **Bild aus Zwischenablage einfügen**, wenn die Qt-Zwischenablage ein Bild enthält.

Der Dialog darf beim Netzfehler seine Eingaben nicht verlieren. Er bleibt geöffnet und zeigt einen
verständlichen Retry-Hinweis. In Phase 1 wird **kein zweiter lokaler XW-Office-Outbox-Datensatz**
angelegt, weil dadurch wieder zwei Datenquellen entstehen würden.

### 2.3 Bearbeiten und Erledigen

Doppelklick auf eine Tabellenzeile oder ein Bearbeiten-Icon öffnet denselben Dialog. Dort können
Angaben ergänzt, Belege geöffnet und weitere Anhänge hochgeladen werden.

Die Bearbeitung braucht getrennte Zustände:

#### Buchhalterischer Zustand

- `incomplete` – als Erinnerung gerettet, Pflichtangaben fehlen;
- `open` – vollständig erfasst, noch nicht geprüft;
- `reviewed` – fachlich geprüft;
- `booked` – in der Buchhaltung berücksichtigt bzw. mit sevDesk verknüpft;
- `dismissed` – bewusst verworfen, mit optionalem Grund.

#### Rückzahlungszustand

- `not_required` – zum Beispiel aus Betriebskasse bezahlt;
- `open` – privat ausgelegt und noch nicht erstattet;
- `reimbursed` – privat ausgelegter Betrag wurde erstattet.

Diese beiden Zustände dürfen nicht zu einem einzigen Status zusammengelegt werden. Eine Ausgabe
kann bereits gebucht, aber noch nicht privat zurückgezahlt sein.

Die Standardansicht `Offen` zeigt einen Datensatz so lange, wie mindestens eine der folgenden
Bedingungen gilt:

- buchhalterischer Zustand ist `incomplete`, `open` oder `reviewed`;
- Rückzahlungszustand ist `open`.

Zusätzlich zeigt XW-Office oberhalb der Tabelle einen Hinweis, wenn noch private Rückzahlungen aus
älteren, aktuell nicht ausgewählten Zeiträumen offen sind. Dadurch verschwinden Altfälle nicht nur
wegen der Monatsauswahl.

---

## 3. Mobile Erfassung in XW-Flow

### 3.1 Einstieg über den mobilen `+`-Button

Im Erfassungsmenü kommt die Aktion **Neue Ausgabe** mit einem Dollar-/Geld-Icon hinzu. Vor der
Implementierung prüfen, welches passende Fluent-Icon in der installierten Version von
`@fluentui/react-icons` tatsächlich exportiert wird, etwa `MoneyRegular` oder
`WalletCreditCardRegular`.

Das aktuelle radiale Menü enthält bereits viele Aktionen. Ein elfter frei positionierter Kreis wird
auf kleinen Displays unübersichtlich. Empfehlung:

- den zentralen `+`-Button beibehalten;
- die Aktionen auf schmalen Displays in eine zugängliche 3-spaltige Capture-Palette bzw. ein
  Bottom-Sheet überführen;
- auf ausreichend breiten Displays kann die bestehende Darstellung bleiben, sofern alle Aktionen
  ohne Überlappung erreichbar sind;
- Fokusreihenfolge, Escape/Zurück, Focus-Trap, `aria-label` und Touch-Zielgröße mit anpassen.

Keinesfalls nur einen weiteren absolut positionierten Button hinzufügen, ohne die Darstellung auf
typischen Android-Breiten zu testen.

### 3.2 Android SHARE

Der bestehende Android/PWA-Share-Target bleibt unverändert der einzige Eingang für geteilte Inhalte.
In `ShareIntentPage` wird **Ausgabe** als weiteres Ziel ergänzt.

Beispiele:

- Kassenzettel fotografieren und aus der Galerie mit XW-Flow teilen;
- PDF-Rechnung aus einer Mail-App teilen;
- Screenshot aus einer Banking- oder Händler-App teilen;
- markierten Text oder eine URL teilen;
- Text über die vorhandene Zwischenablage-Aktion übernehmen und danach `Ausgabe` wählen.

Die vorhandene Share-Draft samt Dateien wird in ein Ausgabenformular übernommen. Erst das
bestätigte Formular erzeugt den serverseitigen Ausgabendatensatz. Ein roher Share darf nicht sofort
als vollständige Ausgabe gespeichert werden.

### 3.3 Mobiles Formular: schnell, aber nicht steuerlich überladen

Für eine **vollständige Ausgabe** sind erforderlich:

1. Mandant;
2. Kategorie;
3. Bruttobetrag größer null;
4. Ausgaben-/Belegdatum;
5. Zahlungsart;
6. mindestens eines von `Empfänger` oder `Zweck`.

Optional bzw. nachpflegbar:

- USt.-Satz, standardmäßig `unbekannt` statt einer riskanten Annahme;
- das jeweils zweite Feld von Empfänger/Zweck;
- Notiz;
- Beleg/Anhänge;
- Rechnungsnummer;
- sevDesk-Verknüpfung, ausschließlich später in XW-Office.

Für Situationen, in denen nur schnell ein Foto oder Text gerettet werden kann, gibt es zusätzlich
**Als Erinnerung speichern**. Dafür reichen Mandant, Kategorie und mindestens ein Inhalt aus
Text/URL/Anhang/Empfänger. Der serverseitige Zustand wird `incomplete`; XW-Office zeigt deutlich
`Angaben fehlen`. Solch ein Datensatz kann weder als geprüft noch als gebucht markiert werden, bevor
die Pflichtfelder ergänzt sind.

Der zuletzt verwendete Mandant, die Kategorie und die Zahlungsart dürfen lokal als UX-Vorgabe
gemerkt werden. Der Server validiert trotzdem jeden Wert gegen die aktiven Kategorien.

### 3.4 USt.-Modell

V1 bietet:

- unbekannt;
- 0 %;
- 10 %;
- 13 %;
- 20 %;
- gemischt.

Der Geldbetrag wird immer als `Decimal`/`Numeric`, nie als Gleitkommazahl, gespeichert. Bei einem
einzelnen Satz dürfen Netto- und Steueranteil nur als Hilfswerte berechnet werden. `gemischt` bleibt
in V1 ohne automatische Aufteilung und muss bei der Prüfung behandelt werden. Eine spätere
`ExpenseTaxLine`-Tabelle kann mehrere Steuersätze abbilden, ohne das Grundmodell zu ändern.

---

## 4. Datenhoheit und Datenmodell in XW-Flow

### 4.1 `ExpenseCapture`

Neue SQLAlchemy-Tabelle, beispielhaft `expense_captures`:

| Feld | Typ/Regel |
|---|---|
| `id` | UUID Primary Key |
| `client_request_id` | UUID, unique, für idempotente Wiederholungen |
| `tenant_key` | String, zunächst `xw` oder `wuedara` |
| `category_key` | String, gegen aktiven Kategorie-Spiegel validiert |
| `category_label_snapshot` | String, damit historische Anzeigen stabil bleiben |
| `source_kind` | `mobile_manual`, `pwa_share`, `clipboard`, `desktop_manual` |
| `expense_date` | Date, fachliches Beleg-/Ausgabendatum, nullable nur bei `incomplete` |
| `gross_amount` | Numeric(12,2), positiv, nullable nur bei `incomplete` |
| `currency` | ISO-Code, V1 nur `EUR` |
| `tax_mode` | `unknown`, `single_rate`, `mixed` |
| `tax_rate_bps` | nullable Integer; 2000 entspricht 20 % |
| `recipient` | normalisierter String, nullable |
| `purpose` | Text, nullable |
| `note` | Text, nullable |
| `invoice_number` | String, nullable |
| `payment_source` | siehe Enum unten |
| `receipt_state` | `attached`, `later`, `unavailable` |
| `accounting_status` | `incomplete`, `open`, `reviewed`, `booked`, `dismissed` |
| `reimbursement_status` | `not_required`, `open`, `reimbursed` |
| `sevdesk_document_id` | nullable String; nur echte ID, keine Dashboard-URL |
| `dismissed_reason` | nullable Text |
| `reviewed_at`, `booked_at`, `reimbursed_at`, `dismissed_at` | nullable UTC-Zeitpunkte |
| `version` | Integer für optimistische konkurrierende Updates |
| `created_at`, `updated_at` | UTC-Zeitpunkte |

`payment_source`:

- `private_cash`;
- `private_card`;
- `private_account`;
- `business_cash`;
- `other`.

Bei `private_cash`, `private_card` und `private_account` wird
`reimbursement_status=open` vorbelegt. Bei `business_cash` wird
`reimbursement_status=not_required` vorbelegt. Der Benutzer darf dies bewusst ändern.

### 4.2 Anhänge

Neue Tabellen nach den vorhandenen Upload-Session-Mustern:

- `expense_capture_attachments`;
- `expense_capture_upload_sessions`.

Ein Anhang speichert nur Metadaten und private Object-Keys:

- Parent-ID;
- Originaldateiname;
- MIME-Type;
- Größe;
- SHA-256;
- Object-Key;
- optional Thumbnail-Object-Key;
- Sortierung;
- Uploadstatus;
- Zeitpunkte.

R2-Pfade erhalten einen eigenen Präfix, beispielsweise
`expense-captures/<jahr>/<monat>/<expense-id>/...`. Vorhandene Größen-, MIME-, Magic-Byte-,
SHA-256- und Finalize-Prüfungen wiederverwenden. Keine Base64-Dateien in PostgreSQL und keine
Objekt-Keys an den Browser oder XW-Office als direkt verwendbare URL ausgeben.

### 4.3 Kategorie-Spiegel

Die Kategorien werden heute in XW-Office gepflegt. Diese Datenhoheit bleibt bestehen. XW-Flow
erhält nur einen validierbaren Spiegel:

`expense_category_mirrors` mit mindestens:

- `tenant_key`;
- `category_key`;
- `label`;
- `initials`;
- `color`;
- `enabled`;
- `source_version` oder `source_updated_at`;
- `updated_at`.

XW-Office sendet nach dem Speichern der Einstellungen und beim ersten Laden der Ausgabenprüfung
einen idempotenten Snapshot an XW-Flow. Ein leerer oder ungültiger Snapshot darf bestehende
Kategorien nicht deaktivieren. Beim initialen Rollout werden sichere Standardwerte bereitgestellt,
damit die mobile Erfassung nicht vom ersten Desktop-Start abhängt; danach überschreibt der
XW-Office-Snapshot diese Vorgaben.

Kategorieänderungen verändern nicht rückwirkend den historischen Snapshot-Text einer Ausgabe.
Deaktivierte Kategorien bleiben für alte Datensätze darstellbar, sind bei Neuanlagen aber nicht mehr
auswählbar.

---

## 5. API-Verträge in XW-Flow

### 5.1 Benutzer-authentifizierte Endpunkte

Unter dem bestehenden Session-Schutz:

```text
GET    /api/v1/expense-categories?tenant_key=xw
POST   /api/v1/expense-captures
GET    /api/v1/expense-captures/{id}
PATCH  /api/v1/expense-captures/{id}
POST   /api/v1/expense-captures/{id}/attachment-sessions
POST   /api/v1/expense-captures/{id}/attachment-sessions/{session_id}/finalize
POST   /api/v1/expense-captures/{id}/attachments/{attachment_id}/view-url
```

`POST /expense-captures` ist über `client_request_id` idempotent:

- gleiche ID und identischer normalisierter Payload: vorhandenen Datensatz mit HTTP 200 liefern;
- gleiche ID und anderer Payload: HTTP 409;
- erstmalige Anlage: HTTP 201.

Die Anhänge werden erst nach erfolgreichem Finalize als `attached` gezählt. Ein fehlgeschlagener
Upload lässt Share-Draft und Formular retryfähig erhalten.

### 5.2 Maschinen-Bridge für XW-Office

Mit derselben Header-Authentifizierung `X-XW-Office-Secret` wie bei Sendungen:

```text
GET    /api/v1/office-bridge/expense-captures
POST   /api/v1/office-bridge/expense-captures
GET    /api/v1/office-bridge/expense-captures/{id}
PATCH  /api/v1/office-bridge/expense-captures/{id}
POST   /api/v1/office-bridge/expense-captures/{id}/attachment-sessions
POST   /api/v1/office-bridge/expense-captures/{id}/attachment-sessions/{session_id}/finalize
POST   /api/v1/office-bridge/expense-captures/{id}/attachments/{attachment_id}/view-url
PUT    /api/v1/office-bridge/expense-categories/snapshot
```

Der List-Endpunkt unterstützt mindestens:

- `tenant_key`;
- `date_from` und `date_to`;
- `active_only`;
- `updated_since`;
- Cursor und `limit`.

Keine stille feste 500-Zeilen-Grenze ohne Cursor. XW-Office darf initial den ausgewählten Zeitraum
plus alle offenen Rückzahlungen abrufen und danach mit `updated_since` inkrementell aktualisieren.

PATCH verlangt die zuletzt gelesene `version`. Bei Versionskonflikt HTTP 409 und den aktuellen
Datensatz zurückgeben, damit kein Update des jeweils anderen Clients verloren geht.

Der View-URL-Endpunkt liefert nur eine kurzlebige signierte GET-URL mit Ablaufzeit. XW-Office öffnet
sie direkt und persistiert sie nicht.

### 5.3 Bestehende Konfiguration weiterverwenden

Kein neues Bridge-Secret einführen. `XW_OFFICE_BRIDGE_SECRET` bleibt die gemeinsame
Maschinen-Authentifizierung.

Der Name `XW_FLOW_SHIPPING_API_BASE_URL` ist für eine allgemeine Bridge inzwischen zu eng.
Kompatible Umstellung:

1. neue allgemeine Konfiguration `flow_bridge_api` und Variable
   `XW_FLOW_BRIDGE_API_BASE_URL` einführen;
2. solange die neue Variable fehlt, auf `XW_FLOW_SHIPPING_API_BASE_URL` zurückfallen;
3. den vorhandenen Sendungsclient auf dieselbe allgemeine Konfiguration umstellen;
4. keine Secret-Werte loggen oder in Dokumentation/Testdaten schreiben.

---

## 6. Umsetzung in XW-Flow

### Phase F1 – Backend-Grundmodell und Migration

Neue bzw. anzupassende Bereiche:

- `backend/app/models/expense_capture.py`;
- `backend/app/models/expense_capture_attachment.py` oder ein gemeinsam gehaltenes Modellmodul;
- `backend/app/models/__init__.py`;
- `backend/app/schemas/expense_capture.py`;
- neue Alembic-Migration auf dem **tatsächlichen aktuellen Head**;
- `backend/app/main.py`.

Vor Erstellen der Migration mit Alembic `heads` prüfen. Das Repository hatte bereits verzweigte und
zusammengeführte Historie; niemals einen Down-Revision-Wert aus dieser Skizze raten.

Constraints und Indizes:

- Unique auf `client_request_id`;
- Index auf `(tenant_key, accounting_status, expense_date)`;
- Index auf `(tenant_key, reimbursement_status)`;
- Unique auf `(tenant_key, category_key)` im Kategorie-Spiegel;
- Foreign Keys mit bewusstem Löschverhalten;
- Check-Constraints für positiven Betrag, erlaubte Zustände und gültigen USt.-Satz.

### Phase F2 – Service, Uploads und API

Empfohlene Dateien:

- `backend/app/services/expense_capture_service.py`;
- `backend/app/services/expense_capture_upload_service.py`;
- `backend/app/api/expense_captures.py`;
- `backend/app/schemas/expense_capture.py`;
- `backend/app/main.py`.

Vorhandene Muster gezielt wiederverwenden:

- Idempotenz und Bridge-Authentifizierung aus `backend/app/api/shipments.py`;
- presigned Upload/Finalize/View-URL aus den Capture-, WüMu- oder Playbook-Media-Services;
- private Objektspeicherung aus `backend/app/integrations/object_storage`.

Bridge- und User-Router dürfen dieselben Servicefunktionen nutzen, aber unterschiedliche
Authentifizierungsabhängigkeiten behalten. Zustandsübergänge gehören in den Service, nicht nur in
die UI.

### Phase F3 – Web-/Mobile-Formular

Empfohlene Dateien:

- neuer API-Client/Types unter `frontend/src/api/`;
- neue Route/Komponente `frontend/src/routes/ExpenseCapturePage.tsx`;
- `frontend/src/App.tsx`;
- `frontend/src/routes/ShareIntentPage.tsx`;
- bei Bedarf kleine, isolierte Komponenten unter `frontend/src/components/expenses/`.

`ShareIntentPage` erweitert seinen `Destination`-Typ, Labels, Farbe und Zielauswahl um `expense`.
Für `destination=expense` wird nicht direkt committed, sondern das Formular mit der vorhandenen
Share-Draft-ID geöffnet. Nach erfolgreicher Anlage und Attachment-Finalisierung wird erst dann die
bestehende Completion-Receipt geschrieben und die Draft gelöscht.

### Phase F4 – Mobile Capture-Menü

Anpassen:

- `frontend/src/components/AppShell.tsx`;
- zugehörige Styles und `AppShell.test.tsx`.

Die neue Aktion erzeugt wie `openShipmentCapture()` eine leere `ShareDraftEntry` mit
`source='mobile_manual'` und öffnet:

```text
/share-intent?share=<local-id>&destination=expense
```

Alternativ darf sie direkt die Expense-Route mit Share-ID öffnen, solange Android-Share,
Zwischenablage und manuelle Erfassung denselben Formular- und Commit-Code verwenden.

### Phase F5 – XW-Flow-Tests

Mindestens:

- Backend-API-Test für vollständige und unvollständige Anlage;
- Idempotenz 201/200/409;
- Bridge ohne/falsches Secret 401, korrektes Secret erfolgreich;
- tenant- und statusgefilterte, cursorbasierte Liste;
- optimistischer Versionskonflikt;
- Zustandsübergänge und Pflichtfelder;
- private Zahlung erzeugt offene Rückzahlung, Betriebskasse nicht;
- Kategorie-Snapshot inklusive Schutz gegen leeren Snapshot;
- Upload-Session, MIME/Magic/Größe/SHA-256 und Finalize;
- View-URL nur authentifiziert und kurzlebig;
- Share-Ziel `expense` mit Bild, PDF, Text und URL;
- Retry behält Draft und Anhänge;
- `AppShell`-Tastatur-, Fokus- und kleine Viewport-Tests.

Qualitätsläufe aus dem XW-Flow-Repository:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest tests/test_expense_captures_api.py -q
.\.venv\Scripts\python.exe -m pytest tests -q

cd ..\frontend
npm run test
npm run lint
npm run build
```

Vor **jedem Commit in XW-Flow** außerdem gemäß dessen `AGENTS.md`/`SECURITY.md` den Gitleaks-Scan
mit `--redact` ausführen. Niemals Environment-Dumps oder Secret-Werte ausgeben.

---

## 7. Umsetzung in XW-Office

### Phase O1 – allgemeine XW-Flow-Bridge

Anpassen bzw. ergänzen:

- `src/xw_office/core/config.py`;
- `config/default.yaml`;
- vorhandenen `src/xw_office/services/sendungen/xw_flow_client.py` auf allgemeine Bridge-Config
  umstellen;
- neuen Client beispielsweise unter
  `src/xw_office/services/expenses/xw_flow_expense_client.py` anlegen;
- Dependency Injection in `src/xw_office/bootstrap.py` ergänzen.

Der Client besitzt typisierte DTOs, Timeouts, verständliche Fehlertexte und folgende Methoden:

- `fetch_expenses(...)`;
- `create_expense(...)`;
- `update_expense(...)`;
- `create_attachment_session(...)`;
- `finalize_attachment_session(...)`;
- `create_attachment_view_url(...)`;
- `sync_category_snapshot(...)`.

HTTP und Upload laufen niemals im Qt-GUI-Thread. Verwende die vorhandenen Worker-/Job-Muster.

### Phase O2 – Tabelle und Dialog

Die bestehende Datei
`src/xw_office/ui/modules/expense_review/view.py` ist bereits groß. Die neue Funktion nicht komplett
dort einbetten. Empfohlene Aufteilung:

- `src/xw_office/ui/modules/expense_review/manual_expenses_table.py`;
- `src/xw_office/ui/modules/expense_review/manual_expense_dialog.py`;
- optional `src/xw_office/ui/modules/expense_review/manual_expense_model.py`;
- `view.py` nur für Einbindung, Tenant-/Zeitraumwechsel und gemeinsame Signale.

Verhalten:

- XeisWorks-Tab lädt nur `tenant_key=xw`;
- WüdaraMusi-Tab lädt nur `tenant_key=wuedara`;
- der `+`-Dialog erhält den Mandanten aus dem sichtbaren Tab;
- Zeitraumwechsel filtert normale Datensätze nach `expense_date`;
- offene Rückzahlungen außerhalb des Zeitraums werden nur als Hinweis/Anzahl ergänzt;
- Kategorie-Klick speichert wie bei Bankbewegungen lazy im Hintergrund;
- keine gelbe Zeilenmarkierung und keine blockierende UI;
- fehlgeschlagene Lazy-Änderung setzt den alten Zustand zurück und zeigt kopierbaren Fehlertext;
- alle Tabellen- und Dialogtexte bleiben auswähl- und kopierbar;
- Beleg-Icon öffnet einen kurz zuvor abgerufenen View-Link;
- mehrere Anhänge öffnen eine kleine auswählbare Liste/Vorschau.

### Phase O3 – Kategorien synchronisieren

Die bereits mandantenspezifisch gepflegten Kategorien bleiben maßgeblich. Snapshot senden:

- nach erfolgreichem Speichern einer Kategorieänderung;
- beim ersten Öffnen der Ausgabenprüfung pro Anwendungslauf;
- optional nach Bridge-Reconnect, wenn der letzte Sync gescheitert ist.

Fehler beim Kategorie-Sync dürfen die vorhandene Ausgabenprüfung nicht unbenutzbar machen. Die UI
zeigt einen kompakten Hinweis; ein späterer Retry ist möglich. Keine Endlosschleife und kein Sync bei
jedem Paint-/Tabellenereignis.

### Phase O4 – XW-Office-Tests

Neue Tests mindestens für:

- Client-DTO-Parsing und Query-Parameter;
- Bridge-Konfiguration samt altem Variablen-Fallback;
- Secret fehlt, HTTP 401/409/5xx und Timeout;
- Tenant-Isolation in beiden obersten Tabs;
- `+` übernimmt korrekten Mandanten;
- Pflichtfelder und Statusvorbelegungen;
- Lazy-Kategorieänderung, Rollback bei Fehler;
- Filter `Offen | Alle`;
- Hinweis auf alte offene Rückzahlungen;
- Belegöffnung fordert immer frischen View-Link an;
- Spaltenbreiten werden initial angepasst und danach persistiert;
- Worker sorgt dafür, dass HTTP/Upload nicht im GUI-Thread läuft;
- Texte in Tabelle und Dialog sind auswähl-/kopierbar.

Beispielhafte Qualitätsläufe:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_expense_review_view.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_xw_flow_expense_client.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check src tests
```

Mypy mindestens gezielt auf neue typisierte Service-/DTO-Dateien anwenden; bekannte Altfehler in
großen UI-Modulen nicht durch pauschale Ignores verstecken.

---

## 8. Schutz vor Doppelzählung

Die neue Tabelle ist zunächst ein Erfassungs- und Prüfbereich. Daraus folgt:

1. Ein Datensatz wird nicht automatisch in bestehende Summen der sevDesk-Bankbewegungen addiert.
2. `reviewed` bedeutet noch nicht zwingend `booked`.
3. Erst `booked` bzw. eine echte sevDesk-Verknüpfung signalisiert buchhalterische Berücksichtigung.
4. Eine spätere Rückzahlung vom Betriebskonto ist keine zweite Betriebsausgabe. Sie ist die
   Begleichung der privaten Auslage.
5. Falls später dieselbe Zahlung doch auf einem importierten Konto erscheint, nur einen
   **möglichen Treffer** vorschlagen; nie automatisch löschen oder zusammenführen.

Für eine spätere Matching-Phase kann XW-Flow am Datensatz eine externe
`settlement_bank_transaction_id` bzw. XW-Office-Referenz speichern. Kandidaten dürfen anhand von
Betrag, Datum, Empfänger und normalisiertem Zweck vorgeschlagen werden. Die Verknüpfung bleibt eine
bewusste Benutzeraktion.

### Nicht Bestandteil von V1

- automatisches Erzeugen oder Hochladen eines sevDesk-Belegs;
- automatische Kontierung;
- automatischer Abzug bei MusikHeroes-Provisionen;
- automatische UVA-/EÜR-Einbeziehung;
- OCR als Pflichtbestandteil;
- automatisches Erkennen gemischter Steuersätze;
- automatische Rückzahlungsüberweisung.

Diese Grenzen sind Absicht: Zuerst muss das Vergessen der Ausgabe zuverlässig verhindert werden.
Automatische Buchungswirkung folgt erst, wenn der Prüfworkflow stabil ist.

---

## 9. Performance- und Offline-Verhalten

- XW-Office lädt die zusätzliche Tabelle unabhängig vom aufwendigeren sevDesk-Lauf. Ein Fehler der
  Bridge darf die Bankbewegungen nicht ausblenden.
- Der erste Abruf ist auf sichtbaren Zeitraum plus offene Rückzahlungen begrenzt.
- Weitere Aktualisierungen verwenden `updated_since` und Cursor.
- Anhänge werden nicht vorab heruntergeladen; nur Thumbnail/Dateimetadaten und bei Klick eine
  signierte URL.
- Der Refresh-Button aktualisiert nur die zusätzliche Tabelle, nicht automatisch den kompletten
  sevDesk-Monatslauf.
- Ein kleiner In-Memory-Cache pro Tenant/Zeitraum darf für die laufende XW-Office-Sitzung verwendet
  werden. Nach einer Mutation wird der betroffene Datensatz gezielt ersetzt.
- XW-Flows Android-Share bleibt in Dexie erhalten, bis Datensatz **und** Anhänge serverseitig
  finalisiert wurden.
- Keine langen Netzwerkoperationen im Qt-GUI-Thread.

---

## 10. Sicherheits- und Datenschutzanforderungen

- Bridge nur über HTTPS und `X-XW-Office-Secret`;
- konstante Secret-Prüfung wie im vorhandenen Sendungsrouter;
- keine Secrets, Authorization-Header oder signierten URLs in Logs;
- Objekt-Keys nicht als öffentliche Links behandeln;
- presigned GET/PUT mit kurzer Gültigkeit;
- Uploadgröße, Dateianzahl, MIME-Type, Magic Bytes und SHA-256 validieren;
- Dateinamen normalisieren, aber Originalname separat für die Anzeige erhalten;
- alle Zustandsänderungen serverseitig validieren;
- kein Hard-Delete aus der normalen UI: `dismissed` ist nachvollziehbar und reversibel;
- sensible Beleginhalte nicht in Test-Fixtures übernehmen; nur synthetische Daten verwenden.

---

## 11. Empfohlene Umsetzungsreihenfolge für Luna

Die Arbeit soll in kleinen, jeweils grünen Schritten erfolgen. Beide Repositories haben getrennte
Commits und getrennte Tests.

1. In **XW-Flow** auf `main` wechseln, Arbeitsbaum prüfen und `git pull --ff-only origin main`.
2. Aktuellen Alembic-Head prüfen; Datenmodell, Migration und Backend-Tests bauen.
3. User-API, Office-Bridge, Uploads und deren Tests bauen.
4. Expense-Formular und Android-Share-Ziel bauen.
5. Capture-Menü responsiv ergänzen und Frontend-Tests/Build ausführen.
6. Gitleaks gemäß XW-Flow-Regeln mit `--redact` ausführen, committen und nach `origin/main` pushen.
7. XW-Flow-Backend/Frontend samt Migration deployen und Health/API mit synthetischen Daten prüfen.
8. In **XW-Office** auf `main` wechseln, sauberen Arbeitsbaum prüfen und
   `git pull --ff-only origin main`.
9. Allgemeine Bridge-Konfiguration und Expense-Client samt Tests bauen.
10. Tabelle, Dialog, Worker und Kategorie-Sync bauen.
11. Gezielte und vollständige Tests sowie Ruff ausführen.
12. Fertige Änderungen in XW-Office `main` committen und zu `origin/main` pushen.

XW-Office erst aktiv gegen die neuen Endpunkte schalten, nachdem der XW-Flow-Backend-Rollout die
Migration und Bridge bereitstellt. Bis dahin muss fehlende Bridge-Konfiguration als ruhiger
`nicht konfiguriert`-Zustand erscheinen und darf die bestehende Ausgabenprüfung nicht beschädigen.

Das geschützte Architekturarchiv
`markdowns/XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md` bleibt unberührt.

---

## 12. Abnahmekriterien

Die Erweiterung ist fertig, wenn alle folgenden Punkte erfüllt sind:

1. Im XeisWorks- und WüdaraMusi-Tab steht unter den Kontobewegungen jeweils die neue Tabelle.
2. Eine Desktop-Ausgabe wird im richtigen Mandanten angelegt und erscheint nach Refresh erneut.
3. Eine mobile Ausgabe kann über das Dollar-Icon vollständig erfasst werden.
4. Ein Bild/PDF/Text kann über Android SHARE als Ausgabe übernommen werden.
5. Bei Zeitdruck kann eine unvollständige Erinnerung gespeichert werden; sie ist unübersehbar offen.
6. Kategorien kommen aus dem XW-Office-gepflegten, mandantenspezifischen Bestand.
7. Anhänge bleiben privat und öffnen in XW-Office nur über kurzlebige Links.
8. Private Auslagen bleiben bis zur separaten Rückzahlungsbestätigung sichtbar.
9. Buchungs- und Rückzahlungszustand sind unabhängig voneinander.
10. Wiederholte Requests erzeugen keine Dubletten.
11. Keine ungeprüfte manuelle Ausgabe verändert sevDesk, UVA oder Provisionen.
12. Bridge-Ausfall, Offline-Share und Uploadfehler verlieren keine bereits eingegebenen Daten.
13. Tabellen bleiben bei Netzaktivität bedienbar; Spaltenbreiten und kopierbare Texte funktionieren.
14. Tenant-Filter verhindern zuverlässig, dass XeisWorks- und WüdaraMusi-Vorgänge vermischt werden.

---

## 13. Fachliche Vorgaben, die vor einer späteren Buchungsautomatik bestätigt werden sollten

Für V1 gelten ohne weitere Rückfrage diese empfohlenen Annahmen:

- private Zahlung bedeutet standardmäßig `Rückzahlung offen`;
- Zahlung aus Betriebskasse bedeutet `Rückzahlung nicht erforderlich`;
- USt. ist mobil standardmäßig `unbekannt`;
- unvollständige Erinnerungen sind erlaubt, aber nicht als geprüft/buchbar markierbar;
- manuelle Ausgaben bleiben zunächst außerhalb automatischer Steuer- und Provisionssummen.

Vor einer späteren Phase mit echter Buchungswirkung sind drei Entscheidungen nötig:

1. Soll XW-Office eine privat ausgelegte Ausgabe nur dokumentieren oder auch eine explizite
   Rückzahlungswarteschlange/Überweisung vorbereiten?
2. Ab welchem Zustand darf eine zusätzliche Ausgabe in steuerliche Auswertungen einfließen:
   `reviewed`, `booked` oder ausschließlich nach sevDesk-Verknüpfung?
3. Sollen gemischte Steuersätze künftig im Dialog in mehrere Betragszeilen zerlegt werden?

Diese Fragen blockieren V1 nicht. Das vorgeschlagene Modell hält alle drei späteren Wege offen.
