# Rechnungsautomat: Ist-Stand und Abschlussplan

**Prüfstand: 14.11.2026, `main` nach `git pull --ff-only origin main`.** Diese Datei ist eine Bestandsaufnahme und ein Folgeauftrag, kein Nachweis für einen produktiven Abruf. Verbindliches Zielbild bleiben `START_HERE.md`, `ARCHITEKTUR.md` und `SICHERHEIT_UND_2FA.md` in diesem Ordner. `TASK_QUEUE.yaml` ist die bestehende Implementierungs-Queue; ihre Statuswerte wurden hier nicht pauschal auf `done` gesetzt.

## 1. Herkunft und ursprünglich gemeintes Ergebnis

Der konkrete frühere Chat war in den lokal verfügbaren Codex-Sitzungen nicht eindeutig auffindbar. Die am **07.11.2026** erstellte Planungs-Commitfolge belegt das Vorhaben im Repository: `4f5d7acb` („plan secure one-click invoice collector with 2FA and OneDrive“), danach `caf041f1` (modularisierte Planung) und die Implementierungs-Commits ab `b39041fd`. Ein Link oder Wortlaut des ursprünglichen Chats lässt sich daraus nicht ableiten.

Das Produktziel ist: In **Finanzen > Ausgabenprüfung** per Klick die **aktivierten, zum jeweiligen Konto passenden** Rechnungsquellen für einen gewählten Monat abfragen, echte PDF-Belege prüfen und ohne Überschreiben in einen vom Benutzer gewählten OneDrive-for-Business-Syncordner legen. `xw` und `wuedara` bleiben getrennt. Der aktuelle Monat sollte als Kalenderfenster in `Europe/Vienna` vorbelegt werden; am 14.11.2026 ist das **01.11. bis 30.11.2026**. Benutzer sollen den Zeitraum ändern können. Eine Rechnung für Oktober, die erst im November bereitgestellt wird, braucht eine klare Regel: standardmäßig nach **Rechnungsdatum**, falls vorhanden; bei fehlendem Datum als „Datum ungeklärt“ zur Prüfung, nicht stillschweigend als November-Rechnung. Mail-Eingangsdatum darf nicht automatisch das Rechnungsdatum ersetzen. Diese Regel ist eine Empfehlung für den Abschluss und war noch nicht durchgehend umgesetzt.

## 2. Was tatsächlich existiert

| Bereich | Befund im Code | Reifegrad |
| --- | --- | --- |
| Einstieg | `src/xw_office/ui/modules/expense_review/view.py` enthält den Button „Rechnungen abrufen“; er öffnet `invoice_collector_dialog.py`. | Vorhanden |
| Katalog | `PROVIDER_REGISTRY.yaml`: 15 Anbieter, 24 Routen (11 Mail, 2 API, 11 Browser). Alle 24 sind `planned`, keine `verified`. | Planung, keine Live-Zusage |
| Lokale Basis | Domain-Typen, Registry-Parser, Connection-Repository, SQLite-Journal, `LOCALAPPDATA`-Pfade, PDF-Validierung, Hash-/Dateinamenlogik, Secret- und Auth-Grenzen sind implementiert. | Technische Grundlage |
| Manueller Import | PDF-Auswahl im Dialog läuft durch `ManualImportConnector`, `DocumentPipeline` und `OneDriveLocalSink`; lokale Ablage meldet `SYNC_PENDING`. | Lokal getestet; echte OneDrive-Synchronisation nicht remote bestätigt |
| Abrufadapter | Graph-Mailanhänge, Mollie-API und Playwright-Session sind als injizierbare Adapter bzw. Verträge mit Fakes vorhanden. | Test-/Integrationsgrundlage, keine echte Anbieterroute nachgewiesen |
| Browser-Einrichtung | `xw-invoice-collection` bietet `doctor`, `catalog`, `login`, `login-all`, `probe`. Login öffnet eine Startseite; `probe_callback=True`, `discover_callback=[]` und `download_callback=None` sind Platzhalter. | Anmeldung/Diagnose, kein Rechnungsabruf |
| Testlauf | `python -m pytest` für drei Collector-Unitdateien und zwei UI-Dateien: **65 passed**. `python -m ruff check` für Collector-Code und zugehörige Tests: **All checks passed**. | Lokale Regression, keine Live-Abnahme |

Die optionale Abhängigkeit `invoice-collection` in `pyproject.toml` umfasst Keyring, `msal-extensions` und Playwright. Das Vorhandensein dieser Pakete beweist keine eingerichteten Konten oder erteilten Microsoft-Rechte.

## 3. Kritische Lücken zum Ein-Klick-Ziel

1. **Der Button holt noch keine Anbieterrechnungen.** `InvoiceCollectorDialog._fetch_active()` erzeugt `ConnectorFactoryRegistry()` ohne registrierte Factories. `InvoiceCollectionService.collect_active()` kann dadurch für jede gespeicherte Route nur einen Konfigurationsfehler sammeln. Der Dialog zeigt danach lediglich die Anzahl „Routen offen“ und kann irreführend „Abruf beendet“ melden. Zuerst echte, explizit registrierte Factories für **verifizierte** Routen anbinden und nicht unterstützte/planned Routen vor dem Speichern verständlich sperren.
2. **Monatsfilter ist nicht vom Button bis zum Adapter verdrahtet.** Mail-, Mollie- und Browser-Connectoren akzeptieren zwar `start`/`end`; Dialog, Service und Orchestrator übergeben keinen Zeitraum. Der Dialog bietet kein Monatsfeld. Der CLI-Login liest keine Rechnungen. Zeitraum, Zeitzone, Datumstyp und unbekannte Dokumentdaten müssen als ein Run-Vertrag end-to-end durchgereicht und getestet werden.
3. **Verbindungen sind nicht produktiv einrichtbar.** Der Dialog speichert Provider, Kontoalias und eine Route, bietet aber keine Auswahl und Pflege vorhandener Verbindungen, keine Secret-Eingabe im geschützten UI, keinen Graph-Consent-Flow, keine angezeigte Route-Capability und keine route-spezifische „Anmeldung erneuern“-Aktion. Zudem ist `RouteSettings.enabled` standardmäßig `True`, obwohl Katalogrouten `planned` sind. Bereits gespeicherte Konfigurationen müssen beim Laden gegen Katalog und Factory-Registry geprüft werden.
4. **Keine echten anbieterspezifischen Downloadregeln.** Die Browser-Engine hat keine DOM-Callbacks für reale Anbieter. Mail braucht geprüfte Absender-/Attachment-Regeln je Konto; `MailMatchPolicy` ohne Domains akzeptiert derzeit alle Absender. Der Graph-Reader liest technisch Anhänge, ist aber nicht aus dem Dialog verdrahtet. Mollie benötigt eine echte, minimal berechtigte Kontoanbindung und einen realen PDF-/Wiederholungstest. Keine fiktiven Selektoren, Links oder Berechtigungen einbauen.
5. **Fehlerisolation und Ergebnisdarstellung reichen nicht.** `CollectionOrchestrator.collect()` ruft `connector.discover()` seriell vor dem Submit auf; eine dortige Exception kann den gesamten Lauf abbrechen. Der Account-Lock wird aus dem ersten Kandidaten abgeleitet; bei leerer Liste lautet der Schlüssel `unknown`. Downloads passieren im Pool, aber Discovery nicht. Der Dialog zeigt weder Kandidatenfehler noch Provider-/Routenstatus, noch `NEEDS_LOGIN`, `POLICY_BLOCKED`, Konflikte oder einen brauchbaren Wiederaufnahmeweg. Der manuelle Import läuft direkt im UI-Thread.
6. **Journal und Wiederaufnahme sind nur teilweise umgesetzt.** `InvoiceJournal` hält Dokumentmetadaten, aber keine Runs, Routenstatus oder Checkpoints. `record_document()` ignoriert Duplikate per `INSERT OR IGNORE`; die Dokumentprovenienz über mehrere Routen wird damit nicht vollständig zusammengeführt. Es gibt keine persistierte, sichere Wiederaufnahme nach Crash und keine belegte Fallback-Steuerung gemäß Registry.
7. **OneDrive-Erfolg ist nur lokal.** `OneDriveLocalSink` schreibt in einen lokalen Ordner und meldet korrekt `SYNC_PENDING`. Remote-Synchronisation wird nicht geprüft; `CLOUD_VERIFIED` ist ohne Graph- oder anderen echten Remote-Nachweis unzulässig. Der Benutzer muss den tatsächlich synchronisierten Zielordner bestätigen. Offline-/Schreibfehler und Wiederholung müssen in der Oberfläche sichtbar sein.
8. **Sicherheits- und Release-Abnahme fehlt.** Die Queue listet T08 (echte Routen) und T09 (Releaseprüfung) als `todo`. Für keine der 24 Katalogrouten gibt es im Repository einen belegten Live-Test mit echtem Dokument, passendem Mandanten, korrektem Typ, idempotentem Wiederholungslauf und geprüftem Auth-Fehlerfall. Keine Route allein wegen grünem Mock-Test auf `verified` setzen.

**Konkreter Codebefund:** `service.py`, `factories.py`, `orchestrator.py`, `connections.py`, `journal.py`, `connectors/graph_mail.py`, `connectors/graph_reader.py`, `connectors/mollie_invoices.py`, `connectors/browser.py`, `playwright_session.py`, `invoice_collector_dialog.py`. Die genannten Risiken sind Code- und Testbefunde, keine Aussage über ungesehene lokale Benutzerkonten oder tatsächlich vorhandene Rechnungen.

## 4. Reihenfolge für den Abschluss

### A. Ehrliche, sichere Bedienung herstellen

- Baseline und aktuelle Katalog-/Factory-Matrix dokumentieren; `TASK_QUEUE.yaml` mit belegter Evidenz aktualisieren.
- Planned/nicht implementierte Routen im Dialog anzeigen, aber nicht als aktiv speicherbar oder abrufbar anbieten. Vorhandene problematische Connections migrieren oder als `CONFIGURATION_ERROR` markieren.
- `collect_active()` darf 0 erfolgreiche/0 ausgeführte Routen niemals als erfolgreichen Abruf darstellen. Ergebnis pro Connection/Route mit Fehlercode und Handlung zeigen. Exceptions vor dem Pool pro Route isolieren; Locks aus Connection-ID statt Kandidaten ableiten.
- Zielordner-Preflight und manuelle PDF-Pipeline im Worker ausführen; UI-Lifecycle, Abbruch und redigierte Fehlermeldungen testen.

### B. Monatslauf und Datenwahrheit end-to-end

- `CollectionRun` um immutable Zeitraum, Zeitzone, gewählte Connection-IDs, Ziel und Run-ID erweitern. UI vorbelegt aktuellen Kalendermonat in `Europe/Vienna`, lässt Änderung und Nachlauf früherer Monate zu.
- Filter nach dokumentiertem Rechnungsdatum/Leistungszeitraum je Route definieren. Fehlendes Datum sichtbar zur manuellen Prüfung; Mail-Eingangsdatum separat speichern. Monatsgrenzen, Jahreswechsel und später eingehende Vormonatsrechnungen testen.
- Run-/Routen-/Checkpoint-Journal, Konflikte und Provenienz ergänzen. Checkpoint nur nach erfolgreich verarbeiteter, eindeutig zuordenbarer Seite/Kandidatengruppe fortschreiben. Wiederausführung muss ohne Duplikate funktionieren.

### C. Produktive erste Routen anschließen

- Explizite Factory-Registrierung mit Capability/Preflight; SecretRef nur über lokalen Keyring; Microsoft-MSAL mit DPAPI-Cache und minimalen Mail-Rechten aus dem UI. Keine Secretwerte, Cookies oder signierten URLs in SQLite, Logs, Git oder OneDrive.
- **Zuerst einen tatsächlichen Mail-PDF-Anbieter** anhand eines echten Kontos prüfen: Absender, Attachment, Dokumenttyp, Rechnungsdatum, mehrere Seiten, Wiederholung und abgelaufene Anmeldung. Leere Match-Regeln dürfen nicht fail-open zu fremden Anhängen führen.
- **Mollie** nur mit vorhandenem `invoices.read`-Zugang live prüfen. API-Dokument und Mail-Dokument desselben Belegs müssen ohne zweite Datei als Provenienz zusammenlaufen.
- **Ein Browserpilot** erst mit echtem Portal, erlaubtem Abruf und selektorgeprüften Tests. Sichtbarer Login/2FA durch den Benutzer, danach Probe, Download und Wiederaufnahme nur dieser Route. Bei Sperre `POLICY_BLOCKED`/manuell; kein Schutz-Bypass.

### D. Anbieterabdeckung und Release

- Für alle 15 Kataloganbieter eine Tabelle führen: tatsächlich für den Benutzer relevant?, Konto/Mandant, Dokumenttyp, getesteter Mail/API/Browserweg, Route-Status, Nachweisdatum, nächster manueller Schritt. Nur relevante Konten aktivieren. Amazon-Invoice-Fetcher erst nach Paritätsnachweis ersetzen. AdSense/YouTube bleiben Einnahmennachweise.
- Jede weitere Route als eigene kleine Änderung mit Fixture-, Contract- und Live-Evidenz umsetzen. Nicht verfügbare Portale bleiben `planned`, `manual` oder `blocked_external`; der Ein-Klick-Lauf verarbeitet die **verifizierten und aktivierten** Routen und nennt fehlende Abdeckung explizit.
- Relevante Unit-/UI-/Integrationstests, Qt-Regression, Ruff, YAML-Validierung, `git diff --check` und Secret-Scan ausführen. Nur geprüfte Änderungen auf `main` committen und zu `origin/main` pushen, ohne Force-Push.

## 5. Abnahme und persönliche Schritte

**Abnahme des nutzbaren ersten Releases:** Der Monatsklick führt wenigstens eine live verifizierte, aktivierte Route aus und zeigt pro Konto neue, bereits vorhandene, ungeklärte und fehlgeschlagene Dokumente. Eine Wiederholung erzeugt keine zweite Datei. Ein Fehler oder eine nötige 2FA bei einem Konto stoppt andere Konten nicht. Das Archiv enthält nur validierte PDFs im richtig gewählten Mandanten-/Zielpfad. Lokale Speicherung heißt `SYNC_PENDING`. Die restlichen relevanten Anbieter sind in einer sichtbaren Abdeckungsmatrix mit ehrlichem Status erfasst.

**Nur der Benutzer kann bei Bedarf** den OneDrive-Business-Ordner auswählen, Microsoft-Zustimmung erteilen, sich im sichtbaren Portal mit 2FA/Passkey anmelden und einen minimal berechtigten Token im lokalen geschützten Dialog hinterlegen. Kein Passwort, OTP, Token oder Rechnungs-PDF im Chat anfordern. Ohne diese Handlungen kann Code samt Fakes fertiggestellt werden; echte Routen bleiben bis zur Live-Evidenz offen.

## 6. Kopierbares Goal für GPT-6-Luna

Dieses Goal in einer neuen Luna-Sitzung im Repository verwenden. Es setzt auf dem heutigen Code auf und verhindert, dass die vorhandene Grundlage neu gebaut oder Mock-Erfolg als produktiv bezeichnet wird.

```text
/goal
Vervollständige den Rechnungsautomaten in XeisWorks/XW-Office auf aktuellem main gemäß
markdowns/rechnungsautomat_ausgabenpruefung_2026-11/IST_STAND_UND_ABSCHLUSSPLAN_2026-11-14.md
und den dort genannten verbindlichen Architektur-/Sicherheitsdateien. Lies AGENTS.md,
prüfe zuerst Code und Tests und aktualisiere TASK_QUEUE.yaml nur mit konkreter Evidenz.

Ziel: Der Button Finanzen > Ausgabenprüfung > Rechnungen abrufen verarbeitet den auswählbaren,
mit aktuellem Kalendermonat Europe/Vienna vorbelegten Zeitraum für alle aktivierten und
tatsächlich verifizierten Verbindungen. Er speichert geprüfte PDFs ohne Überschreiben im
gewählten OneDrive-Business-Syncordner und zeigt je Route Erfolge, Duplikate, Konflikte,
Loginbedarf und Fehler. SYNC_PENDING ist kein Remote-Syncnachweis.

Arbeite den Abschlussplan A bis D in Abhängigkeitsreihenfolge ab: leere Factory und
irreführende Erfolgsanzeige beheben; planned-Routen sperren; Monatslauf durchreichen;
Discovery-Fehler isolieren, Connection-Locks und Worker-Lifecycle korrigieren; Run-/Checkpoint-
Journal und sichere Wiederaufnahme ergänzen; eine echte Mail-PDF-Route, Mollie nur bei
verfügbarem invoices.read, und höchstens einen Browserpilot anbinden und live prüfen.
Führe eine Abdeckungsmatrix für alle 15 Anbieter und die tatsächlich relevanten Konten.
Ohne echte Konto-/Dokumentevidenz bleibt eine Route planned/blocked_external/manuell.
Keine fiktiven Portalregeln, keine automatische sevDesk-Buchung, keine MFA- oder Bot-Umgehung.

Gehe bei nötigen persönlichen Schritten jeweils mit genau einer UI-Anweisung auf mich zu:
Ordnerwahl, Entra-Consent, sichtbarer Login/2FA oder Token-Eingabe im lokalen geschützten
Dialog. Frage Geheimnisse nie im Chat ab. Teste pro Phase gezielt; zum Abschluss Unit-/UI-/
Integrationstests, Ruff, YAML, diff --check und Secret-Scan. Committe und pushe getestete
Schritte gemäß AGENTS.md auf origin/main. Berichte getrennt über implementierte, per Fake
getestete und mit echtem Konto verifizierte Routen sowie offene externe Blockaden.
```
