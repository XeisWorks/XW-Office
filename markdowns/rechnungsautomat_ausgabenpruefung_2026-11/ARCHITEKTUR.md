# XW-Office Ausgabenprüfung: Rechnungsautomat – Zielarchitektur und Abnahmekriterien

**Stand 07.11.2026. Verbindliche Spezifikation; noch kein live verifizierter Portaladapter.**

## 1. Ausgangslage und empfohlene Korrektur

Die vorhandene Planung trifft die Sicherheits- und Produktentscheidungen grundsätzlich gut.
Für langfristige Erweiterbarkeit muss der zunächst vorgesehene Vertrag
`provider.fetch(..., sink, ...)` jedoch aufgeteilt werden: Ein Provider darf weder das
Ablageziel kennen noch selbst Deduplizierung, Dateinamen oder OneDrive-Status verwalten.
Auch Mail, API und Browser sind keine Provider, sondern alternative **Abrufrouten** einer
lokalen Provider-Verbindung.

Verbindliche Abhängigkeitsrichtung:

```text
PySide6-Dialog
    -> InvoiceCollectionService / RunOrchestrator
        -> ConnectionRepository + Journal
        -> Connector-Port -> Mail-/API-/Browser-/Import-Adapter
        -> DocumentPipeline -> Validator -> Deduplicator -> DocumentSink-Port
                                                      -> OneDriveLocalSink
```

Provider-Code hängt nur von stabilen Domain-Typen und Ports ab. UI, Orchestrator,
Dokumentpipeline und Sink enthalten keine `if provider_id == ...`-Verzweigungen.

## 2. Bestehende Funktionen und Repository-Grenzen

Vor Implementierung `AGENTS.md`, den aktuellen Code und die Tests erneut lesen. Insbesondere:

- `ExpenseReviewView` besitzt zwei Mandanten (`xw`, `wuedara`) sowie bestehende Bank-,
  Ausgaben- und Lieferantenportal-Funktionen. Ein eigener Textbutton und ein separater
  `InvoiceCollectorDialog` ergänzen die View, ohne bestehende Aktionen zu ersetzen.
- Lieferantenportale in der aktuellen Ausgabenprüfung sind URL-Zuordnungen, keine
  authentifizierten Invoice-Provider. Die beiden Konzepte bleiben getrennt.
- `BackgroundWorker`/`UiAsyncAction` werden für UI-Lifecycle und Signale wiederverwendet.
  Mehrere Providerjobs benötigen darüber einen begrenzten Orchestrator und dürfen Widgets
  niemals aus einem Workerthread ändern.
- `app_paths.state_dir()` und Logpfade zeigen derzeit ins Repository. Neue vertrauliche oder
  maschinenspezifische Daten müssen über einen neuen `local_app_data_dir()`-Pfad unter
  `%LOCALAPPDATA%/XeisWorks/XW-Office/` laufen.
- Der existierende `GraphMailClient` hat breite Standardscopes, Konsolen-Device-Flow und
  unverschlüsselten serialisierten Token-Cache. Bestehende Nutzungen nicht brechen, aber für
  den Rechnungscollector erst nach einer sicheren Auth-/Cache-Abstraktion wiederverwenden.
- Die zentrale SQLAlchemy/PostgreSQL-Datenbank ist nicht der Ort für lokale Browserprofile,
  OAuth-Caches oder Maschinen-Checkpoints. Dafür eine eigene lokale SQLite-Datenbank nutzen.
- Der Product-Hub-OneDrive-Client bleibt auf Product-Hub-Assets beschränkt.
- Die Sammlung ist ein Eingangskorb. Keine automatische sevDesk-Buchung und keine
  automatische USt-Entscheidung hinzufügen.

## 3. Zielstruktur

```text
src/xw_office/services/invoice_collection/
  domain.py                 # Enums und immutable Domain-Modelle
  ports.py                  # Connector, DocumentSink, SecretStore, Journal, Clock
  errors.py                 # typisierte, redigierbare Fehlercodes
  registry.py               # ProviderManifest laden/validieren, keine Secrets
  connections.py            # lokale Connection-Konfiguration und Migrationen
  journal.py                # SQLite-Läufe, Checkpoints, Dokumente, Konflikte
  orchestrator.py           # Queue, Account-Locks, bounded concurrency, resume/cancel
  pipeline.py               # validate -> normalize -> hash -> dedupe -> publish -> journal
  pdf_validation.py         # Limits, MIME/Magic, Parser, Metadaten
  naming.py                 # sichere, deterministische Archivpfade
  security.py               # LOCALAPPDATA, ACL, Redaction, Host-Allowlist
  auth/
    graph.py                # UI-fähiges MSAL, minimaler Scope, verschlüsselter Cache
    browser_profiles.py     # Profilpfad und exklusiver Account-Lock
    secrets.py              # SecretRef -> keyring/zugelassener Store
  connectors/
    graph_mail.py           # generischer Mail-Connector, providerbezogene Match-Regeln
    mollie_invoices.py      # erster offizieller API-Connector
    playwright_base.py      # Engine; keine providerbezogenen Selektoren
    providers/              # kleine, explizit registrierte Provideradapter
    manual_import.py        # eingebaute Route durch dieselbe Pipeline
  sinks/
    onedrive_local.py       # MVP: lokal synchronisierter Ordner
    graph_drive.py          # spätere optionale Erweiterung, nicht Teil des ersten Slice
src/xw_office/ui/modules/expense_review/invoice_collector_dialog.py
tests/unit/invoice_collection/
tests/ui/test_invoice_collector_dialog.py
tests/integration/invoice_collection/
```

Playwright und Browser-Binary als klar dokumentierte optionale Desktop-Abhängigkeit führen.
Core-, Mail-, API- und manuelle Routen müssen ohne installierten Browser importierbar bleiben.

## 4. Stabile Domain- und Port-Verträge

### 4.1 Provider-Katalog und lokale Verbindung

`ProviderManifest` ist versionskontrolliert und secretfrei:

```python
@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    label: str
    manifest_version: int
    supported_tenants: frozenset[TenantId]
    document_types: frozenset[DocumentType]
    routes: tuple[RouteManifest, ...]
```

`ProviderConnection` ist lokale Benutzereinstellung:

```python
@dataclass(frozen=True)
class ProviderConnection:
    connection_id: UUID
    provider_id: str
    tenant_id: TenantId
    account_alias: str
    enabled: bool
    route_settings: tuple[RouteSettings, ...]
```

`RouteSettings` enthält Reihenfolge, Aktivierung, nicht geheime Optionen und optional eine
`SecretRef`. Ein Secretwert darf weder im YAML-Katalog noch in QSettings/SQLite liegen.
Provider-ID und Connection-ID sind stabil; Anzeigenamen dürfen sich ändern. Unbekannte
Manifestversionen führen zu verständlichem `CONFIGURATION_ERROR`, nicht zu stiller Ignorierung.

Der statische YAML-Katalog darf **keine Python-Importpfade** ausführen. Connector-Factories
werden explizit im Code registriert. Externe, dynamisch geladene Plugins sind kein MVP-Ziel;
damit wird Registry-Manipulation nicht zur Codeausführung.

Eine geplante Route darf bereits als Produktausblick im Katalog stehen, obwohl ihre Factory
noch nicht implementiert ist; sie wird dann als „nicht verfügbar“ angezeigt und kann nicht
aktiviert werden. Für `experimental` oder `verified` sowie für jede aktivierte Route ist eine
registrierte Factory zwingend. So erzwingt der Katalog keine leeren Adapter-Stubs.

### 4.2 Connector-Port

Discovery und Download sind getrennt, damit Pagination, Checkpoints und Wiederholungen sauber
funktionieren:

```python
class InvoiceConnector(Protocol):
    route_key: str

    def capabilities(self) -> ConnectorCapabilities: ...
    def probe(self, context: FetchContext) -> RouteHealth: ...
    def discover(
        self, context: FetchContext, checkpoint: Checkpoint | None
    ) -> Iterable[DocumentReference]: ...
    def download(
        self, reference: DocumentReference, workspace: Path, cancel: CancelToken
    ) -> DownloadedArtifact: ...
    def begin_auth(self, context: AuthContext) -> AuthChallenge: ...
```

- Der Connector liefert nur Referenzen und ein Artefakt im isolierten temporären Workspace.
- Er kennt keinen Archivpfad und keinen Sink.
- `begin_auth` ist nur verfügbar, wenn die Capability dies ausweist. API-Token-Eingabe,
  Microsoft-OAuth und Browserlogin sind unterschiedliche Auth-Challenges.
- Connectoren liefern stabile externe IDs, wenn der Anbieter sie bereitstellt, und markieren
  deren Scope. Sie erfinden keine IDs aus einem Dateinamen.
- Ein Checkpoint wird erst nach erfolgreicher Pipeline-Verarbeitung aller davor liegenden
  Kandidaten fortgeschrieben. Fehlgeschlagene Kandidaten bleiben wiederholbar.

### 4.3 Dokumentpipeline und Sink-Port

```python
class DocumentSink(Protocol):
    sink_id: str

    def preflight(self, context: SinkContext) -> SinkHealth: ...
    def publish(
        self, document: ValidatedDocument, source_path: Path
    ) -> SinkReceipt: ...
    def verify(self, receipt: SinkReceipt) -> SyncStatus: ...
```

Pipeline-Reihenfolge:

1. Download in einen laufbezogenen `%LOCALAPPDATA%`-Workspace mit Größenlimit.
2. Dateisignatur, MIME, PDF-Parser, Seitenzahl und Verschlüsselungsstatus prüfen.
3. Metadaten normalisieren, aber unsichere Extraktionen als `unverified` kennzeichnen.
4. SHA-256 berechnen und gegen Journal plus vorhandene Zieldatei prüfen.
5. Deterministischen relativen Pfad erzeugen und ohne Überschreiben atomar publizieren.
6. Sink-Receipt und Dokumentjournal in einer nachvollziehbaren Reihenfolge schreiben.
7. Workspace bereinigen; bei Crash sichere Wiederaufnahme oder Quarantäne.

Der Sink entscheidet nicht über Dokumenttyp oder Mandant. Die Pipeline kennt keine
providerbezogenen APIs. `OneDriveLocalSink` meldet nach lokaler Publikation höchstens
`SYNC_PENDING`; `CLOUD_VERIFIED` darf nur ein tatsächlicher Remote-Nachweis liefern.

## 5. Datenmodell und Provenienz

Je Dokument mindestens:

- `document_id`, `run_id`, `connection_id`, `provider_id`, `route_key`, `tenant_id`
- `account_alias`, `document_type`, `external_id` plus dessen Scope
- Rechnungs-/Belegnummer, Dokumentdatum, optional Leistungszeitraum
- optional Betrag als `Decimal` und ISO-4217-Währung; niemals `float`
- Originaldateiname, deklarierter MIME-Typ, erkannter MIME-Typ, Größe, Seitenzahl
- SHA-256, relativer Archivpfad, Erfassungszeitpunkt in UTC
- `metadata_confidence`, `review_status`, `document_outcome`, `sync_status`
- redigierte Provenienz: Mail-/Attachment-ID, API-Ressourcen-ID oder Portalreferenz; keine
  signierte Download-URL, kein Cookie und kein Mailinhalt im Log

Dokumenttypen bleiben fachlich getrennt:

`fee_invoice`, `expense_invoice`, `receipt`, `credit_note`, `payout_statement`,
`income_statement`, `unknown`.

`unknown` ist zulässig und erzwingt manuelle Prüfung. Ein Dateiname mit „invoice“ ist kein
ausreichender Klassifikationsnachweis.

### Deduplizierung und Konflikte

- SHA-256 ist die maßgebliche Inhaltsidentität **innerhalb eines Mandanten und Ablageziels**.
  Ein Treffer in einem anderen Mandanten darf dessen Ablage nicht unterdrücken.
- `(connection_id, route_key, external_id)` ist eine zusätzliche Identität. Gleiche externe ID
  mit anderem Hash ist ein `CONTENT_CONFLICT` und wird nicht überschrieben.
- Gleicher Hash über Mail und API wird einmal publiziert, aber beide Provenienzen dürfen im
  Journal auf dasselbe Dokument zeigen.
- Der deterministische Dateiname enthält mindestens Provider, Kontoalias, Dokumenttyp,
  fachliches Datum und `hash8`. Bei bestehendem Ziel immer Inhalt prüfen; nie still ersetzen.
- Mehrere PCs können denselben OneDrive-Ordner sehen. Deshalb darf Deduplizierung nicht nur auf
  der lokalen SQLite-Datei beruhen. Der Sink prüft den deterministischen Zielpfad und behandelt
  eine konkurrierend entstandene identische Datei als Duplikat, abweichenden Inhalt als
  Konflikt. Gleichzeitiger produktiver Abruf auf mehreren PCs bleibt bis zu einem späteren
  verteilten Lease ausdrücklich nicht unterstützt.

## 6. Drei getrennte Zustandsautomaten

Ein einzelnes `status`-Feld wäre mehrdeutig. UI und Journal führen getrennt:

- **Konfiguration:** `DISABLED`, `NOT_CONFIGURED`, `READY`, `CONFIGURATION_ERROR`
- **Authentifizierung:** `UNKNOWN`, `AUTHENTICATED`, `CONSENT_REQUIRED`, `NEEDS_LOGIN`,
  `NEEDS_2FA`, `CREDENTIAL_INVALID`, `POLICY_BLOCKED`
- **Lauf:** `IDLE`, `QUEUED`, `RUNNING`, `WAITING_FOR_USER`, `PARTIAL`, `SUCCEEDED`,
  `FAILED`, `CANCELLED`

Dokumentergebnisse: `NEW`, `ALREADY_PRESENT`, `REJECTED`, `QUARANTINED`,
`CONTENT_CONFLICT`. Syncstatus: `LOCAL_SAVED`, `SYNC_PENDING`, `CLOUD_VERIFIED`,
`SYNC_FAILED`.

Fehler besitzen maschinenlesbare Codes: `AUTH_REQUIRED`, `RATE_LIMITED`,
`TRANSIENT_NETWORK`, `PROVIDER_CHANGED`, `UNSUPPORTED_ACCOUNT`, `INVALID_DOCUMENT`,
`DESTINATION_UNAVAILABLE`, `POLICY_BLOCKED`, `INTERNAL_ERROR`. Nur transiente Fehler und
Rate-Limits werden mit begrenztem Backoff automatisch wiederholt. Auth-, Policy-,
Konfigurations- und Provider-Changed-Fehler warten auf eine explizite Aktion.

## 7. Orchestrierung, Fallback und Abbruch

- Ein `CollectionRun` speichert immutable Zeitraum, gewählte Connection-IDs, Ziel und
  Registry-Version. Dadurch bleibt ein Lauf reproduzierbar.
- Global kleine, konfigurierbare Parallelität; pro Connection/Account genau ein aktiver Job.
  Browserprofile besitzen zusätzlich einen exklusiven Prozess-/Dateilock.
- Standardreihenfolge Mail > API > Browser > manueller Import. Fallback ist keine pauschale
  Exception-Behandlung: Beispielsweise darf `AUTH_REQUIRED` auf API nicht automatisch einen
  Browserlogin starten. Die Registry definiert erlaubte Übergänge je Fehlercode.
- Wenn eine priorisierte Route echte Dokumente geliefert hat, dürfen nachrangige Routen nur
  laufen, wenn die Connection dies zur Vollständigkeitsprüfung ausdrücklich vorsieht.
- Abbruch ist kooperativ. Bereits erfolgreich publizierte Dokumente bleiben journalisiert;
  unfertige Kandidaten werden nicht als erledigt markiert.
- Ein Fehler einer Connection stoppt keine andere. Das Gesamtergebnis kann `PARTIAL` sein.
- Login-Wiederaufnahme referenziert `run_id`, `connection_id` und `route_key` und setzt nur
  diesen Job fort.

## 8. Mail, API, Browser und manueller Import

### Mail

Der Graph-Mail-Connector ist generisch. Providerbezogene Regeln beschreiben zugelassene
Absenderdomains, optionale Empfängeraliase, Attachment-Muster und Dokumenttypen. Filter nie nur
auf Anzeigenamen oder Betreff stützen. Message-ID, Attachment-ID, tatsächlicher MIME/PDF-Inhalt,
Pagination und Zeitraum berücksichtigen. Links aus Mails werden nicht automatisch geöffnet.

Für den Collector minimalen delegierten Scope verwenden (`Mail.Read`, Shared-Mailbox-Rechte nur
bei tatsächlichem Bedarf). Interaktiver Systembrowser/PKCE oder verständlicher Device-Code in
der UI; Token-Cache mit Windows-DPAPI/`msal-extensions`. Keine Konsolenausgabe als einzige
Anmeldeoberfläche.

### Offizielle API

Je API eigener kleiner Connector auf gemeinsamer HTTP-Basis: explizite Timeouts,
Host-Allowlist, sichere Redirect-Policy, Pagination, `Retry-After`, begrenzte Retries und
redigierte Fehler. Nur dokumentierte Read-Scopes verwenden. Mollie-`invoices.read` ist der
erste Kandidat; nicht mit Zahlungs- oder Kundenrechnungs-APIs verwechseln.

### Browser

Je Connection ein persistentes Chromium-UserDataDir unter `%LOCALAPPDATA%`, niemals im Repo,
OneDrive oder Log. Geschützte Seite vor Abruf prüfen; bei Redirect/Unberechtigt `NEEDS_LOGIN`.
Login und 2FA sichtbar durch den Benutzer. Downloads mit `expect_download()` und
`save_as()` nach echten Live-/Fixture-Tests. Keine erfundenen Selektoren, privaten Endpunkte,
Cookie-Header-Nachbauten, Stealth-Modi oder CAPTCHA-/WebAuthn-Umgehung. Blockierte Anbieter
bleiben `MANUAL_ACTION`/`POLICY_BLOCKED`.

### Manueller Import

Manueller Import ist ein eingebauter Connector und kein Notbehelf außerhalb des Systems. Der
Benutzer wählt eine oder mehrere Dateien und bestätigt Provider, Connection, Mandant und
Dokumenttyp. Danach läuft exakt dieselbe Validierungs-, Deduplizierungs- und Sink-Pipeline.

## 9. OneDrive-Ziel und lokales Journal

`QFileDialog.getExistingDirectory` wählt den Zielordner. `OneDriveCommercial` darf nur einen
Vorschlag liefern. Preflight prüft Existenz, Schreibbarkeit, freien Platz und eine sichere
Testpublikation; kein stiller Fallback nach `Downloads`.

Beispiel:

```text
<Ziel>/XeisWorks/2026/11/Mollie/
<Ziel>/WuedaraMusi/2026/11/BrowserStack/
<Ziel>/XeisWorks/Ungeprueft/OpenAI/
```

Das lokale SQLite-Journal liegt unter `%LOCALAPPDATA%`, besitzt Schema-Version/Migrationen,
Foreign Keys und transaktionale Schreibvorgänge. Es enthält Provider-/Connection-Konfiguration,
Läufe, Routenstatus, Checkpoints, Dokumentidentitäten, Provenienzen, Sink-Receipts und
Konflikte – aber keine Secretwerte, PDFs, Cookies oder vollständigen Mailinhalte.

Ein späterer `GraphDriveSink` ist ein eigener Adapter mit eigener delegierter Berechtigung und
Remote-Ordneridentität. Er erweitert nicht den Product-Hub-Client und verändert keine
Connectoren.

## 10. Provider-unabhängige UI

Dialogkopf: **„Alle aktiven Verbindungen abrufen“**, **„Ordner wählen“**, **„Ordner öffnen“**,
Zeitraum, Abbrechen. Tabelle mindestens: Provider, Konto, Mandant, aktive Route,
Konfiguration, Anmeldung, letzter Lauf, neue/vorhandene/abgelehnte Dokumente, Ergebnis,
Aktionen.

Aktionen werden aus Capabilities erzeugt: Verbinden, Anmeldung erneuern, Token hinterlegen,
jetzt abrufen, Portal öffnen, manuell importieren. Keine providerbezogenen Button-Abfragen.
Fehlermeldungen zeigen sicheren Klartext plus Fehlercode, nie Rohantwort, Token, signierte URL
oder Cookie. Der initiale Wizard fragt nur fehlende Einstellungen ab.

## 11. Erweiterungsrezept für ein weiteres Portal

Ein neuer Provider gilt als sauber integriert, wenn folgende Änderungen genügen:

1. secretfreies Manifest mit stabiler ID, Dokumenttypen, Host-Allowlist und Routen ergänzen;
2. vorhandenen generischen Mail-/Import-Connector konfigurieren **oder** einen kleinen neuen
   API-/Browser-Connector samt expliziter Factory registrieren;
3. gemeinsame Connector-Contract-Suite und providerbezogene Fixturetests bestehen;
4. UI-Snapshot/Smoke-Test beweist, dass keine UI-Änderung nötig ist;
5. mit echtem Konto und Dokument testen und nur die konkrete Route auf `verified` setzen.

Falls dafür Orchestrator, Pipeline oder Sink providerbezogen geändert werden müssten, ist zuerst
zu prüfen, ob eine generische Capability im Port fehlt. Keine schnelle Sonderverzweigung.

## 12. Teststrategie und Release-Gates

### Automatische Tests

- Registry-Schema, eindeutige IDs, bekannte Factory-Keys, Host-Allowlist und Migrationen.
- Contract-Suite für **jeden** Connector: Probe, Pagination/Checkpoint, Download, Abbruch,
  redigierte Fehler, kein Archivzugriff.
- Contract-Suite für **jeden** Sink: Preflight, no-clobber, identischer Concurrent-Winner,
  Konflikt, Statuswahrheit.
- Pipeline: leere/HTML-/beschädigte/verschlüsselte/zu große PDF, Hash, Metadaten,
  Cross-Route-Duplikat, Cross-Tenant-Isolation, Crash zwischen Publish und Journal.
- Orchestrator: Partial Failure, Rate-Limit, kein falscher Fallback, Account-Lock,
  Login-Wiederaufnahme nur einer Route, kooperativer Abbruch.
- Graph-Fixtures mit Pagination und PDF-/Nicht-PDF-Anhängen; keine echten Maildaten.
- Mollie-Mock mit mehreren Seiten, 401, 429, Timeout, Duplikat und echter PDF-Bytefolge.
- lokaler Fake-Portalserver für Sessionablauf, sichtbaren Login und Download.
- UI-Regressions- und Lifecycle-Tests für beide Mandanten und zerstörte Views.

### Verbindliche Gates

1. Bestehende Ausgabenprüfung, sevDesk, XW-Flow, Graph-Mail und Product Hub bleiben grün.
2. Vor erstem Live-Login: LOCALAPPDATA-Pfade, `.gitignore`, verschlüsselter OAuth-Cache,
   SecretStore und Redaction getestet.
3. Kein stilles Überschreiben, keine tenantübergreifende Deduplizierung, keine falsche
   Cloudbestätigung.
4. Kein Secret, echtes PDF, Browserprofil oder Token-Cache in Git/Logs/Testartefakten.
5. `ruff`, relevante `pytest`-Suites, Qt-Regression, `git diff --check`, YAML-Validierung und
   Secret-Scan laufen.
6. Eine Route wird erst `verified`, wenn echtes Dokument, Dokumenttyp, Wiederholungsabruf und
   Sessionablauf bzw. Tokenfehler dokumentiert getestet wurden.
7. Fertige getestete Änderungen gemäß `AGENTS.md` auf `main` committen und zu
   `origin/main` pushen; kein Force-Push.

## 13. Bewusst nicht im ersten Release

- automatische sevDesk-Buchung oder Steuerklassifikation
- unbeaufsichtigter Scheduler/Windows-Dienst
- gleichzeitige Sammlung auf mehreren PCs in dasselbe Ziel
- dynamisch installierbare Drittanbieter-Providerpakete
- Graph-Drive-Upload und echte Remote-Syncbestätigung
- OCR als Voraussetzung für Annahme eines gültigen PDFs

Diese Punkte bleiben durch Ports und Journal nachrüstbar, ohne den ersten sicheren Desktop-Slice
unnötig zu vergrößern.

## Offizielle technische Referenzen

- https://playwright.dev/python/docs/auth
- https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
- https://playwright.dev/python/docs/downloads
- https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens
- https://pypi.org/project/msal-extensions/
- https://learn.microsoft.com/en-us/graph/api/attachment-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0
- https://docs.mollie.com/reference/list-invoices
- https://docs.mollie.com/reference/get-invoice
