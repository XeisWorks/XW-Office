# Rechnungsautomat: Ist-Stand und Abschlussplan

**Pruefstand: 14.11.2026, Branch `main`.** Diese Datei ist eine Bestandsaufnahme und ein Folgeauftrag, kein Nachweis fuer einen produktiven Rechnungsabruf. Verbindliches Zielbild bleiben `START_HERE.md`, `ARCHITEKTUR.md` und `SICHERHEIT_UND_2FA.md` in diesem Ordner. `TASK_QUEUE.yaml` ist die bestehende Implementierungs-Queue; ihre Statuswerte wurden hier nicht pauschal auf `done` gesetzt. Juengere Implementierungsschritte sind Cross-Route-Deduplizierung `0c5274c7`, sichere Quellenanzeige `2d152f3c`, Quarantaene-Status `f13de57a`, Playwright-Lifecycle/Fehlerklassifikation `dbcac683`, begrenztes Graph-Anhangsstreaming `1de41866`, bereinigte Temp-Downloadnamen und inkrementelle Graph-Pagination.

**Aktueller persoenlicher Blocker:** Der Benutzer hat am 14.11.2026 bestaetigt, dass Anbieter-Mailbox und bestaetigte Absenderdomain(s) erst geklaert werden muessen. Bis dahin kein Graph-Live-Probe und keine echte Mailrouten-Verifikation; T08 bleibt `blocked_external`. Fuer die naechste Umsetzung mit GPT-6-Luna ist der auf den heutigen Code zugeschnittene Auftrag in [GPT6_LUNA_FORTSETZUNGS_GOAL_2026-11-14.md](GPT6_LUNA_FORTSETZUNGS_GOAL_2026-11-14.md) massgeblich. Der unten stehende fruehere Initialauftrag ist nur Historie und soll nicht erneut zum kompletten Neuaufbau fuehren.

## Fortschreibung: externe Rechnungs-IDs im Journal

Beim Abschlussaudit wurde festgestellt, dass `documents.external_id` neue externe Rechnungs-IDs trotz bereits vorhandener Hash-Provenienz zusaetzlich im Klartext speicherte. Das Journal nutzt jetzt Schema 4: neue Dokumentzeilen schreiben dort keine externe ID mehr; `has_external_id()` arbeitet ueber den SHA-256-Fingerprint in `document_provenance`. Die Migration uebernimmt vorhandene Schema-1-bis-3-Klartextwerte in gehashte Provenienz und leert anschliessend die Spalte, sodass die Inhaltskonflikterkennung erhalten bleibt. Abgedeckt durch Tests fuer neue Klartextfreiheit, Hash-Lookup/Konflikterkennung und Schema-3-Migration. Der gezielte Foundation-Lauf besteht mit **37 passed**. Eine SQLite-Migration garantiert keine physische Loeschung alter Datenseiten oder Sicherungskopien; sie entfernt den Wert aus dem aktiven Datenbankschema und dem aktuellen Datensatz.

Die volle Repository-Suite nach der Migration besteht mit **2.414 passed, 7 skipped, 0 failed** (eine externe Starlette/httpx-Deprecation-Warnung). Repo-weites Ruff, Collector-MyPy (30 Dateien), Provider-/Queue-YAML, `git diff --check` und der hinzugefuegte Diff-Secret-Mustercheck bestehen.

## Fortschreibung: begrenzter Graph-Anhangsdownload

Die Nachrichtenabfrage verwendet ausserdem `hasAttachments eq true`, damit Graph Nachrichten ohne nicht-inline Anhaenge vor dem Expand herausfiltert. Microsoft dokumentiert OData-Queryparameter fuer [List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0); `hasAttachments` ist laut [Message-Ressource](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0) bei Inline-only-Nachrichten `false`, die der Connector ohnehin nicht als Rechnungsanhaenge verarbeitet.

Der Graph-Reader liest rohe Anhangsantworten und JSON-`contentBytes` jetzt ueber `httpx.Client.stream()`. Der Empfang ist auf maximal 25 MiB fuer rohe PDF-Bytes begrenzt; JSON-Antworten haben eine berechnete Base64-Obergrenze plus 64 KiB JSON-Metadaten. `Content-Length` loest nur eine fruehe Ablehnung aus; die laufende Bytezaehlung bleibt die Grenze. Fehler schliessen die Antwort und schreiben keine teilweise Zieldatei. Nachrichten-Seiten werden inkrementell geliefert, statt die gesamte Mailboxliste im Speicher zu halten; jeder `nextLink` wird vor dem Aufruf auf den erlaubten Graph-Host geprueft und wiederholte Seitenlinks werden erkannt, um Endlosschleifen zu verhindern. Die vollstaendige Repository-Suite nach Graph-Streaming, Temp-Dateinamen-Haertung, inkrementeller Pagination und Loop-Schutz besteht mit **2.407 bestanden, 7 uebersprungen, 0 fehlgeschlagen**; Repo-weites Ruff, Collector-MyPy (30 Dateien), Provider-/Queue-YAML, `git diff --check` und Secret-Musterpruefung sind ebenfalls sauber.

## Fortschreibung: sichere temporäre Downloadnamen

Ein Anbieter kann den Dateinamen eines Anhangs oder API-Dokuments kontrollieren. Graph-Mail, Browser-, Mollie- und manueller Import schreiben deshalb ueber `workspace_download_path()` in einen bereinigten Dateinamen im jeweiligen Temp-Workspace. Die Aufloesung des Zielpfads wird gegen den Workspace geprueft; Pfadtrenner, Traversalnamen und Windows-Geraetedateien koennen so nicht aus dem Workspace ausbrechen. Traversal- und `CON.pdf`/`LPT1.txt`-Faelle sind gezielt abgedeckt; die vollstaendige Repository-Regression besteht mit **2.406 bestanden, 7 uebersprungen, 0 fehlgeschlagen**.

## Fortschreibung: paralleles No-Clobber-Publishing

Der OneDrive-Sink verwendete zuvor einen Tempnamen aus Dateiname und Prozess-ID; parallele Laeufe im selben Prozess konnten dieselbe Tempdatei teilen. Er nutzt jetzt pro Publish eine exklusiv angelegte, eindeutige Tempdatei. Beim Kopierfallback wird eine von diesem Lauf angelegte Teildatei bei Fehlern entfernt, die Zielpruefsumme verifiziert und ein Rennen um denselben Zielpfad hashbasiert als Duplikat oder Konflikt bewertet. Vier gezielte Tests decken erfolgreichen Fallback, Schreibfehler mit Cleanup sowie parallele identische und divergierende Inhalte ab. Die vollstaendige Repository-Suite besteht nach diesem Fix mit **2.411 bestanden, 7 uebersprungen, 0 fehlgeschlagen**; der Lauf zeigt eine externe Starlette/httpx-Deprecation-Warnung.

## Fortschreibung: begrenzter Mollie-PDF-Abruf

Der Mollie-PDF-Download liest den HTTP-Body jetzt gestreamt mit einem konfigurierbaren Limit (standardmaessig 25 MiB); `Content-Length` ist nur eine fruehe Ablehnung, die Bytezaehlung begrenzt den tatsaechlichen Empfang. Der Response wird auch bei Groessen- und Lesefehlern geschlossen; die Zieldatei wird erst nach vollstaendigem Empfang geschrieben. Der bestehende Rate-Limit-/Timeout-Retry gilt auch fuer den Stream, und nicht erlaubte Hosts werden vor dem Request blockiert. Connector-Tests fuer Oversize/Response-Close, Retry und Hostallowlist bestehen. Die vollstaendige Repository-Suite besteht nach Graph-/OneDrive-Haertung und Mollie-Streaming mit **2.413 bestanden, 7 uebersprungen, 0 fehlgeschlagen**.

## 1. Herkunft und ursprünglich gemeintes Ergebnis

Der konkrete frühere Chat war in den lokal verfügbaren Codex-Sitzungen nicht eindeutig auffindbar. Die am **07.11.2026** erstellte Planungs-Commitfolge belegt das Vorhaben im Repository: `4f5d7acb` („plan secure one-click invoice collector with 2FA and OneDrive“), danach `caf041f1` (modularisierte Planung) und die Implementierungs-Commits ab `b39041fd`. Ein Link oder Wortlaut des ursprünglichen Chats lässt sich daraus nicht ableiten.

Das Produktziel ist: In **Finanzen > Ausgabenprüfung** per Klick die **aktivierten, zum jeweiligen Konto passenden** Rechnungsquellen für einen gewählten Monat abfragen, echte PDF-Belege prüfen und ohne Überschreiben in einen vom Benutzer gewählten OneDrive-for-Business-Syncordner legen. `xw` und `wuedara` bleiben getrennt. Der aktuelle Monat sollte als Kalenderfenster in `Europe/Vienna` vorbelegt werden; am 14.11.2026 ist das **01.11. bis 30.11.2026**. Benutzer sollen den Zeitraum ändern können. Eine Rechnung für Oktober, die erst im November bereitgestellt wird, braucht eine klare Regel: standardmäßig nach **Rechnungsdatum**, falls vorhanden; bei fehlendem Datum als „Datum ungeklärt“ zur Prüfung, nicht stillschweigend als November-Rechnung. Mail-Eingangsdatum darf nicht automatisch das Rechnungsdatum ersetzen. Diese Regel ist inzwischen konservativ in der Pipeline umgesetzt und muss mit echten Anbieterbelegen live validiert werden.

## 2. Was tatsächlich existiert

| Bereich | Befund im Code | Reifegrad |
| --- | --- | --- |
| Einstieg | `src/xw_office/ui/modules/expense_review/view.py` enthält den Button „Rechnungen abrufen“; er öffnet `invoice_collector_dialog.py`. | Vorhanden |
| Katalog | `PROVIDER_REGISTRY.yaml`: 18 Anbieter und 26 Routen; Details in `PROVIDER_ABDECKUNG_2026-11-14.md`. Die automatisierten Rechnungsrouten sind nicht live verifiziert. | Planung, keine Live-Zusage |
| Monatslauf | Der Dialog bietet Start-/Enddatum und vorbelegt den aktuellen Kalendermonat in `Europe/Vienna`; der Zeitraum wird bis zu den Factory-Connectors durchgereicht. | Lokal verdrahtet; Datumssemantik ist je Route noch nicht durchgehend verifiziert |
| Lokale Basis | Domain-Typen, Registry-Parser, Connection-Repository, SQLite-Journal, `LOCALAPPDATA`-Pfade, PDF-Validierung, Hash-/Dateinamenlogik, Secret- und Auth-Grenzen sind implementiert. Verschluesselte PDFs werden lokal quarantinisiert und als `QUARANTINED` gemeldet. | Technische Grundlage |
| Manueller Import | PDF-Auswahl im abbrechbaren Worker l?uft durch `ManualImportConnector`, `DocumentPipeline` und `OneDriveLocalSink`. Der gew?hlte Rechnungszeitraum wird gepr?ft; au?erhalb liegende Belege werden als ?bersprungen ausgewiesen. Lokale Ablage meldet `SYNC_PENDING`. | Lokal getestet; echte OneDrive-Synchronisation nicht remote best?tigt |
| Abrufadapter | Graph-Mail ist in der Desktop-App mit expliziter Factory verdrahtet; Mailbox- und Absenderdomain-Konfiguration wird gepr?ft. Die optionale Graph-/Browser-Laufzeit ist installiert; der normale Doppler-Start liefert `MS_GRAPH_CLIENT_ID` und `MS_GRAPH_TENANT_ID`. | Technisch vorbereitet; keine Rechnungsroute live verifiziert |
| Graph-Mailbox-Probe | Der Dialog öffnet einen sichtbaren MSAL-Systembrowser-Login mit `Mail.Read`; der Probe fragt höchstens eine Nachrichten-ID ab, keine Texte oder Anhänge. Token-Cache ist lokal unter `LOCALAPPDATA` und nach Tenant/Mailbox getrennt. | Zugriffstest vorhanden; bestätigt weder Anbieterregel noch Rechnungsabruf |
| Browser-Einrichtung | `xw-invoice-collection` bietet `doctor`, `catalog`, `login`, `login-all`, `probe`. Login öffnet eine Startseite; `probe_callback=True`, `discover_callback=[]` und `download_callback=None` sind Platzhalter. | Anmeldung/Diagnose, kein Rechnungsabruf |
| Testlauf | Vollstaendige Repository-Suite nach Browser-Lifecycle- und Callback-Fehlerbehandlung: **2.402 bestanden, 7 uebersprungen**, 0 fehlgeschlagen. Repo-weites Ruff, Provider-/Queue-YAML, `git diff --check`, Secret-Musterpruefung und Collector-MyPy (30 Dateien) bestanden. | Lokale Regression, keine Live-Abnahme |

Die optionale Abhängigkeit `invoice-collection` in `pyproject.toml` umfasst Keyring, `msal-extensions` und Playwright. Das Vorhandensein dieser Pakete beweist keine eingerichteten Konten oder erteilten Microsoft-Rechte.

## 3. Kritische Lücken zum Ein-Klick-Ziel

1. **Keine Rechnungsroute ist produktiv freigeschaltet.** Die UI und der Service blockieren Katalogrouten, deren Maturity nicht `verified` ist. Das ist korrekt fail-closed. Der Graph-Mailbox-Probe testet nur Zugriff; er lädt keine Anhänge und setzt keine Route auf `verified`. Es fehlt ein echter, geprüfter Mail-PDF-Livepilot samt Wiederholungslauf.
2. **Datumsbehandlung ist jetzt fail-closed, aber noch nicht live validiert.** Graph filtert nicht mehr nach Mail-Eingangsdatum. Die Pipeline akzeptiert ein Connector-Rechnungsdatum oder genau ein explizit beschriftetes Datum aus den ersten drei PDF-Textseiten. Fehlendes oder mehrdeutiges Datum wird in `xw/_needs_review/...` abgelegt und im Ergebnis als `NEEDS_REVIEW` markiert. Ein erkanntes Datum außerhalb des gewählten Zeitraums wird verworfen und als `OUT_OF_PERIOD` gezählt; es landet nicht im aktuellen Monatsordner. OCR und anbieterspezifische Labels sind nicht abgedeckt; die Trefferqualität muss an echten Belegen geprüft werden.
3. **Verbindungsverwaltung ist nur ein erster Einrichtungsschritt.** Der Dialog erfasst Provider, Mandant, Kontoalias, Mailbox und bestätigte Senderdomains und bietet einen Graph-Zugriffstest. Planned-Routen lassen sich absichtlich nicht aktiv speichern. Auswahl/Pflege mehrerer gespeicherter Verbindungen, Route-Capabilities und gezielte Erneuerung der Anmeldung fehlen weiterhin.
4. **Keine echten anbieterspezifischen Downloadregeln.** Die Browser-Engine hat keine DOM-Callbacks für reale Anbieter. Für Mail müssen Absender, Anhang, Dokumenttyp und Rechnungsdatum anhand eines echten Anbieterkontos geprüft werden. Mollie benötigt ein echtes `invoices.read`-Konto und einen PDF-/Wiederholungstest. Keine fiktiven Selektoren, Links oder Berechtigungen einbauen.
5. **Ergebnisdarstellung ist erweitert, UI-Aktionen fehlen.** Discovery-Fehler werden pro Route abgefangen; Download-Locks verwenden Connection-IDs; Connectoren werden am Laufende geschlossen. Die Ergebnistabelle zeigt Provider/Konto, Route, Mandant, Dateiname, Ergebnis und pro Beleg sichere Quellenlabels (Provider/Route, ohne externe IDs). Verschluesselte PDFs werden als `QUARANTINED` gemeldet und lokal zur manuellen Pruefung erhalten. Leere Discovery wird von erfolgreicher Verarbeitung unterschieden. Anmeldung erneuern, Konfliktpruefung und Review-Aufloesung haben noch keine eigenen Aktionen.
6. **Laufjournal und sichere Wiederholung sind jetzt teilweise umgesetzt.** SQLite haelt Run-ID, Status, Zeitraum, Connection-Konfigurationsfingerprints, Zielordnerfingerprint, Routenstatus und gehashte Kandidaten-Checkpoints. Nach Abbruch/Crash startet ein Klick mit identischem Kontext denselben Lauf erneut; Verarbeitung laeuft bewusst idempotent erneut durch PDF-Pruefung und No-Clobber-Deduplizierung. Der tatsaechliche Checkpoint wird noch nicht als Connector-Paginierungs-Cursor verwendet. Dokumente werden dem Run zugeordnet. Gleicher Hash im selben Mandanten wird routenuebergreifend nur einmal publiziert; zusaetzliche Quellen werden mit gehashten Quell-/External-IDs als Provenienz gespeichert. Ein sichtbarer Wiederaufnahmedialog fehlt.
7. **OneDrive-Erfolg ist nur lokal.** `OneDriveLocalSink` schreibt in einen lokalen Ordner und meldet korrekt `SYNC_PENDING`. Remote-Synchronisation wird nicht geprüft; `CLOUD_VERIFIED` ist ohne Graph- oder anderen echten Remote-Nachweis unzulässig. Der Benutzer muss den tatsächlich synchronisierten Zielordner bestätigen. Offline-/Schreibfehler und Wiederholung müssen in der Oberfläche sichtbar sein.
8. **Sicherheits- und Release-Abnahme fehlt.** Für keine der 26 Katalogrouten gibt es im Repository einen belegten Live-Test mit echtem Dokument, passendem Mandanten, korrektem Typ, Rechnungsdatum, idempotentem Wiederholungslauf und geprüftem Auth-Fehlerfall. Keine Route allein wegen grünem Fake-Test oder erfolgreichem Mailbox-Probe auf `verified` setzen.

**Konkreter Codebefund:** `service.py`, `factories.py`, `orchestrator.py`, `connections.py`, `journal.py`, `connectors/graph_mail.py`, `connectors/graph_reader.py`, `connectors/mollie_invoices.py`, `connectors/browser.py`, `playwright_session.py`, `invoice_collector_dialog.py`. Die genannten Risiken sind Code- und Testbefunde, keine Aussage über ungesehene lokale Benutzerkonten oder tatsächlich vorhandene Rechnungen.

## 4. Reihenfolge für den Abschluss

### A. Ehrliche, sichere Bedienung herstellen

- Baseline und aktuelle Katalog-/Factory-Matrix dokumentieren; `TASK_QUEUE.yaml` mit belegter Evidenz aktualisieren.
- Bereits vorhanden: planned-Routen werden angezeigt und k?nnen nicht aktiviert werden; gespeicherte Routen werden beim Abruf erneut gegen Katalog-Maturity gepr?ft. Fehlende Katalogrouten und besch?digte gespeicherte Verbindungszeilen erscheinen als `CONFIGURATION_ERROR`; g?ltige Verbindungen laufen weiter. Belegt durch `test_collection_isolates_invalid_saved_connection_and_keeps_valid_accounts_running`.
- Bereits vorhanden: 0 erfolgreiche Dokumente werden nicht als erfolgreicher Abruf ausgegeben; Setup-/Discovery-Exceptions sind pro Route isoliert, Locks verwenden Connection-IDs; Ergebnisse erscheinen je Route/Kandidat. Noch offen: konkrete Handlung für Auth-, Konflikt- und Policyfehler.
- Vorhanden: PDF-Import und Sink-Preflight laufen im abbrechbaren Worker; UI-Resultate werden nur im Hauptthread aktualisiert. Die vollstaendige Repository-Suite mit Qt-Regression besteht (2.394 passed, 7 skipped). Offen: Review-Aufloesung und konkrete UI-Handlungen fuer Auth-, Konflikt- und Policyfehler.

### B. Monatslauf und Datenwahrheit end-to-end

- Bereits vorhanden: Zeitraumwahl mit aktuellem Kalendermonat in `Europe/Vienna` und Durchreichung bis zum Connector. Das Run-Ergebnis enthält Run-ID, Zeitraum und Connection-IDs; Journal speichert Ziel-Fingerprint statt eines lokalen Zielpfads. Offen: dokumentierte Zeitzonen-/Datumskonvention je Connector.
- Vorhanden: beschriftete Rechnungsdaten werden konservativ geparst; Graph-Eingangszeit bleibt separate Provenienz. Unbekannte/mehrdeutige Daten landen zur Prüfung außerhalb des Monatsarchivs; erkannte off-period Dokumente werden gezählt und übersprungen. Offen: echte Anbieter-PDFs, OCR-freie Abdeckung der relevanten Vorlagen und Prüfung/Zuordnung aus der Review-Ablage.
- Vorhanden: Run-ID, unveränderlicher Zeitraum/Connection-IDs im Ergebnis, sichere Fingerprints ohne gespeicherte Zielpfade oder Mailboxwerte, Routenstatus, gehashte Checkpoints und automatisches Resume desselben unvollständigen Laufs bei identischem Kontext. Wiederholung durch Pipeline/Deduplizierung ist idempotent.
- Cross-Route-Deduplizierung und Quellenanzeige sind umgesetzt: gleicher Hash im selben Mandanten/Sink wird nur einmal publiziert; weitere Quellen werden gehasht im Journal gespeichert und im Ergebnis ausschliesslich als Provider/Route gezeigt. Offen: Checkpoint als Cursor bei paginierten Connectors verwenden, sichtbare Resume-Aktion/Statusliste ergaenzen und Crash-/Teilfehlerpfade weiter pruefen.

### C. Produktive erste Routen anschließen

- Vorhanden: explizite Graph-Mail-Factory, lokaler MSAL-Cache, interaktiver Systembrowser-Flow und minimales `Mail.Read`; die optionale Laufzeitabhängigkeit `msal-extensions` muss auf dem Zielsystem installiert sein. Offen: echte Route-Capabilities/Preflight und Livebeleg.
- **Zuerst einen tatsächlichen Mail-PDF-Anbieter** anhand eines echten Kontos prüfen: Absender, Attachment, Dokumenttyp, Rechnungsdatum, mehrere Seiten, Wiederholung und abgelaufene Anmeldung. Leere Match-Regeln dürfen nicht fail-open zu fremden Anhängen führen.
- **Mollie** nur mit vorhandenem `invoices.read`-Zugang live prüfen. API-Dokument und Mail-Dokument desselben Belegs müssen ohne zweite Datei als Provenienz zusammenlaufen.
- **Ein Browserpilot** erst mit echtem Portal, erlaubtem Abruf und selektorgeprüften Tests. Sichtbarer Login/2FA durch den Benutzer, danach Probe, Download und Wiederaufnahme nur dieser Route. Bei Sperre `POLICY_BLOCKED`/manuell; kein Schutz-Bypass.

### D. Anbieterabdeckung und Release

- Für alle 18 Kataloganbieter eine Tabelle führen: tatsächlich für den Benutzer relevant?, Konto/Mandant, Dokumenttyp, getesteter Mail/API/Browserweg, Route-Status, Nachweisdatum, nächster manueller Schritt. Nur relevante Konten aktivieren. Amazon-Invoice-Fetcher erst nach Paritätsnachweis ersetzen. AdSense/YouTube bleiben Einnahmennachweise.
- Jede weitere Route als eigene kleine Änderung mit Fixture-, Contract- und Live-Evidenz umsetzen. Nicht verfügbare Portale bleiben `planned`, `manual` oder `blocked_external`; der Ein-Klick-Lauf verarbeitet die **verifizierten und aktivierten** Routen und nennt fehlende Abdeckung explizit.
- Relevante Unit-/UI-/Integrationstests, Qt-Regression, Ruff, YAML-Validierung, `git diff --check` und Secret-Scan ausführen. Nur geprüfte Änderungen auf `main` committen und zu `origin/main` pushen, ohne Force-Push.

## 5. Abnahme und persönliche Schritte

**Abnahme des nutzbaren ersten Releases:** Der Monatsklick führt wenigstens eine live verifizierte, aktivierte Route aus und zeigt pro Konto neue, bereits vorhandene, ungeklärte und fehlgeschlagene Dokumente. Eine Wiederholung erzeugt keine zweite Datei. Ein Fehler oder eine nötige 2FA bei einem Konto stoppt andere Konten nicht. Das Archiv enthält nur validierte PDFs im richtig gewählten Mandanten-/Zielpfad. Lokale Speicherung heißt `SYNC_PENDING`. Die restlichen relevanten Anbieter sind in einer sichtbaren Abdeckungsmatrix mit ehrlichem Status erfasst.

**Persoenlicher Live-Schritt noch offen:** Du musst fuer den ersten Mail-Pilot den Anbieter, das zugehoerige Rechnungs-Postfach und bestaetigte Absenderdomain(s) lokal klaeren und in der UI eingeben; danach dort den Graph-Mailbox-Test und den sichtbaren Microsoft-Login/Consent ausfuehren. Diese Werte nicht im Chat posten. Zielordnerwahl, API-Token oder weitere Logins werden erst angefragt, wenn die konkrete Route sie benoetigt.

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
Führe eine Abdeckungsmatrix für alle 18 Anbieter und die tatsächlich relevanten Konten.
Ohne echte Konto-/Dokumentevidenz bleibt eine Route planned/blocked_external/manuell.
Keine fiktiven Portalregeln, keine automatische sevDesk-Buchung, keine MFA- oder Bot-Umgehung.

Gehe bei nötigen persönlichen Schritten jeweils mit genau einer UI-Anweisung auf mich zu:
Ordnerwahl, Entra-Consent, sichtbarer Login/2FA oder Token-Eingabe im lokalen geschützten
Dialog. Frage Geheimnisse nie im Chat ab. Teste pro Phase gezielt; zum Abschluss Unit-/UI-/
Integrationstests, Ruff, YAML, diff --check und Secret-Scan. Committe und pushe getestete
Schritte gemäß AGENTS.md auf origin/main. Berichte getrennt über implementierte, per Fake
getestete und mit echtem Konto verifizierte Routen sowie offene externe Blockaden.
```
