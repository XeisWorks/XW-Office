# Fortsetzungs-Goal fuer GPT-6-Luna

**Stand:** 15.11.2026 (Fehlerredaktion, sichere ACLs, PDF-Bereinigung, exakte Mail-Absenderfilter, eigener/Shared-Mailbox-Modus, katalogautoritative Connector-Auswahl, SecretService-Graph-Wiring und Vollsuite 2.449/7 dokumentiert)
**Repository:** `XeisWorks/XW-Office`, Branch `main`
**Ausgangslage:** Die technische MVP-Grundlage ist weitgehend implementiert und lokal getestet. Der erste echte Rechnungsabruf ist noch nicht verifiziert. Der Graph-Collector liest Client-ID und Tenant-ID über den vorhandenen `SecretService`; der Benutzer muss weiterhin das Postfach, in dem Lieferantenbelege eingehen, und die bestätigten Absenderdomain(en) klären. Die vom Benutzer genannten Steuer-Mail-Adressen sind im Repo Versandabsender/-empfänger und ersetzen diese Werte nicht.

Fuer Bestandsaufnahme, Codebefunde und Provideruebersicht siehe:

- [IST_STAND_UND_ABSCHLUSSPLAN_2026-11-14.md](IST_STAND_UND_ABSCHLUSSPLAN_2026-11-14.md)
- [TASK_QUEUE.yaml](TASK_QUEUE.yaml)
- [PROVIDER_ABDECKUNG_2026-11-14.md](PROVIDER_ABDECKUNG_2026-11-14.md)

## Kopierbarer Auftrag

```text
/goal
Setze den Rechnungsautomaten in XeisWorks/XW-Office vom aktuellen Stand auf `main` aus
fort. Lies zuerst AGENTS.md sowie:

- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/IST_STAND_UND_ABSCHLUSSPLAN_2026-11-14.md
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/TASK_QUEUE.yaml
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/ARCHITEKTUR.md
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/SICHERHEIT_UND_2FA.md

Verwende aktuelle `main`, aktualisiere sie gemaess AGENTS.md mit
`git pull --ff-only origin main` und pruefe den Arbeitsbaum, bevor du Aenderungen machst.
Baue nicht neu, was im Ist-Stand bereits implementiert und mit konkreter Evidenz belegt ist.

Ziel: Der Monatslauf unter Finanzen > Ausgabenpruefung verarbeitet aktivierte und tatsaechlich
verifizierte Anbieterwege, validiert PDFs und legt sie ohne Ueberschreiben im vom Benutzer
gewaehlten OneDrive-Business-Syncordner ab. Die Oberflaeche zeigt Teilerfolge, Duplikate,
Quarantaene, Review-Bedarf und Fehler pro Route. Lokale Ablage bleibt `SYNC_PENDING`; behaupte
keine Cloud-Synchronisation ohne echten Remote-Nachweis.

Arbeite die Queue nach Abhaengigkeiten ab und konzentriere dich auf den noch offenen Umfang:

1. Pruefe T01-T09 gegen den aktuellen Code und die Queue. Aktualisiere Status/Evidenz nur,
   wenn sie durch vorhandenen Code, erfolgreiche Pruefungen oder echte Live-Evidenz gedeckt ist.
2. Der Graph-Downloadpfad hat seit Commit `1de41866` begrenztes Streaming fuer rohe und
   JSON/Base64-Anhaenge, eine berechnete Base64-Obergrenze und eine 64-KiB-Grenze fuer
   JSON-Metadaten. `Content-Length` ist nur ein Vorabhinweis. Graph-Nachrichtenseiten werden
   inkrementell iteriert, vorab auf `hasAttachments eq true` eingeschraenkt, und wiederholte
   `nextLink`s enden mit einem typisierten Routenfehler.
   Erhalte diese Regeln und pruefe die Implementierung samt Tests, bevor du den Task als
   erledigt betrachtest; erfinde keine zweite Downloadstrategie.
3. Pruefe die Dialog-, Journal-, Wiederaufnahme- und Fehlerpfade auf noch fehlende MVP-
   Bedienhandlungen. Implementiere nur konkret belegte, providerunabhaengige Luecken.
   Der Laufverlauf zeigt sichere Run-/Routenstatus und uebernimmt einen frueheren Zeitraum;
   Resume erfolgt nur bei identischem Kontext. Diese Funktion nicht erneut bauen.
   Checkpoints zeigen erfolgreiche Kandidatenzahlen. Nicht allein aufgrund einer Quellen-ID
   Downloads ueberspringen: Resume muss erneut laden und pruefen, bis ein Connector eine
   getestete Inhaltsrevision oder einen Integritaetsdigest bereitstellt.
   Insbesondere keine erfundenen Mail-Absenderregeln, Portal-Selektoren, API-Rechte oder
   Rechnungsdaten. Temp-Downloadpfade nutzen `workspace_download_path()` fuer Graph, Browser,
   Mollie und manuellen Import; diese Funktion begrenzt bereinigte Anbieterdateinamen auf den
   Workspace und prueft Traversal/Geraetedateien. Pruefe diese bestehende Loesung, statt sie
   erneut zu bauen. Der OneDrive-Sink nutzt ebenfalls eindeutige temporaere Dateien pro
   Publish und entfernt Teildateien nach Fallback-Schreibfehlern; parallele identische sowie
   divergierende Zielinhalte sind gezielt getestet. Der Mollie-PDF-Download ist ebenso auf 25 MiB
   begrenzt und gestreamt. Pruefe diese vorhandenen Schutzmassnahmen gegen Code und Tests, statt
   sie neu zu bauen. Der Browseradapter hat generische Fake-Portal-Tests, aber keine echten
   Anbieter-Callbacks. Das Journal verwendet Schema 5: neue Dokumente speichern keine rohen
   `external_id`-Werte in `documents`; vorhandene Schema-1-bis-3-Werte werden in gehashte
   Provenienz migriert und aus der aktiven Spalte entfernt. Schema 5 speichert Kontoalias,
   Belegart und Datum fuer Review-Aufloesung; `InvoiceReviewService` prueft die PDF-Hashidentitaet,
   publiziert no-clobber, aktualisiert danach das Journal und entfernt zuletzt die Review-Kopie.
   Erhalte die Hash-basierte Konflikterkennung und fuehre keinen Klartext-Fallback wieder ein.
   Ein Discovery-Fehler `AUTH_REQUIRED` wird pro Route und fuer den Gesamtlauf als
   `WAITING_FOR_USER` dargestellt, wenn alle aktiven Routen auf Benutzerauthentifizierung
   warten; Regressionstest `test_collection_service_marks_run_waiting_when_every_route_needs_auth`.
   Der Dialog listet gespeicherte Providerverbindungen, aktualisiert Einstellungen mit stabiler
   Connection-ID und verhindert die Reaktivierung nicht verifizierter Routen. Angaben zu
   unverifizierten Routen koennen als deaktivierte Entwuerfe lokal gespeichert werden. Fuer
   `official_api` gibt es eine maskierte Eingabe, die das Credential ausschliesslich ueber
   `SecretStore`/Windows Credential Manager sichert; die Mollie-Factory liest diesen SecretRef
   und bekommt den gewaehlten Zeitraum. Erhalte diese Guardrails. Eine routebezogene Retry-Aktion
   fuer Auth-, Netzwerk-, Rate-Limit- und temporaere Zielordnerfehler ist umgesetzt; Policy-,
   Konfigurations-, Dokument- und Inhaltskonflikte duerfen nicht erneut eingeplant werden.
   Graph-Auth-Erneuerung nutzt silent-first den DPAPI-Cache und fällt bei Bedarf auf den
   sichtbaren MSAL-Login zurück; Mailbox-Probe oder routebezogener Retry lösen dies aus.
   Dieses Verhalten ist mit einem Fake-App-Test belegt. Provider-
   Portale werden fuer `portal_hosts` bereits als HTTPS-Menue angeboten; Hostvalidierung und
   manuelle Login-/Download-Klarstellung nicht entfernen und keine Portalautomation ohne
   Live-Verifikation erfinden.
   Der allgemeine `BackgroundWorker` protokolliert Ausnahme-Text. Monatsabruf, Graph-Mailbox-
   Probe und manueller PDF-Import redigieren fatale Fehler vor Worker-Logging und UI-Ausgabe.
   Diese Grenzen sind umgesetzt und getestet; neue Workergrenzen duerfen keine rohen
   Providerfehler, Tokens, signierten URLs oder Exception-Chains protokollieren.
   Graph-Mailbox-Probe und Postfachtyp-Auswahl folgen der Katalog-Auth-Capability
   `microsoft_graph_mail`; geschuetzte Credential-Eingabe folgt `api_token`. Erhalte diese
   Capability-Steuerung. Routebezogene Wiederholung und interaktive Auth-Erneuerung sind
   umgesetzt; erhalte die Retry-Filterung.
4. Der Live-Mailpilot ist extern blockiert: Anbieter, Rechnungs-Mailbox und bestaetigte
   Absenderdomain(s) sind noch nicht geklaert. Frage nie nach diesen Werten oder Geheimnissen
   im Chat. Wenn der Benutzer soweit ist, gib genau eine lokale UI-Anweisung: in Finanzen >
   Ausgabenpruefung > Rechnungen abrufen Anbieter/Verbindung mit Mailbox und bestaetigten
   Absenderdomain(s) konfigurieren, "Graph-Mailbox testen" waehlen und sichtbaren Microsoft-
   Login/Consent abschliessen. Fuehre keinen Liveversuch mit geratenen Werten aus.
   Der optionale exakte Absenderadressfilter ist umgesetzt; Domain und exakte Adresse muessen
   gemeinsam passen. Keine Adressen vorbefuellen. Das UI bietet „Eigenes Postfach“ und
   „Freigegebenes Postfach“; nur die explizite Shared-Auswahl fordert `Mail.Read.Shared` an.
   Microsoft dokumentiert den delegierten Scope fuer eigenes und freigegebenes Mail, nur fuer
   Arbeits-/Schulkonten: https://learn.microsoft.com/en-us/graph/permissions-reference#mailreadshared .
   Consent bleibt sichtbar und muss vom Benutzer abgeschlossen werden.
5. Nach dem lokalen Probe: Zugriffsergebnis allein ist keine Rechnungsrouten-Verifikation.
   Mit echtem Anbieterbeleg muessen Absender, Anhang, Dokumenttyp, Rechnungsdatum, Mandant,
   Wiederholung ohne zweite Datei und Auth-Fehlerverhalten separat nachgewiesen werden.
   Bis dahin bleibt T08 `blocked_external`; unbewiesene Routen bleiben `planned`/manuell.
6. Mollie nur live pruefen, wenn ein rechtmaessig verfuegbarer Advanced Access Token oder ein
   OAuth-Credential mit `invoices.read` besteht. Ein normaler Profil-API-Key ist fuer den
   `/v2/invoices`-Endpunkt nicht als Zugriffsart dokumentiert. Mollies
   Business-Operations-Invoices-API hat keinen Sandbox-Modus, daher nur mit echtem
   Produktionskonto und bewusstem Benutzerauftrag pruefen.
   Maximal einen echten Browserpilot starten, nur mit erlaubter sichtbarer Anmeldung. Keine
   CAPTCHA-, MFA-, Bot- oder Google-Login-Umgehung.
7. Nach jeder Codeaenderung passende Tests ausfuehren. Vor Abschluss volle relevante
   Repository-Suite, Ruff, MyPy, Provider-/Queue-YAML, `git diff --check` und Secret-Scan
   ausfuehren. Keine Zugangsdaten, Postfaecher, Tokens, PDFs, Browserprofile oder OAuth-Caches
   ins Repository, in Logs oder Commits aufnehmen.
8. Aktualisiere Ist-Stand, Queue, Providerabdeckung und diese Goal-Datei mit dem tatsaechlichen
   Ergebnis. Committe getestete Aenderungen und pushe sie gemaess AGENTS.md nach `origin/main`;
   kein Force-Push. Beende mit sauberem Arbeitsbaum.

Berichte getrennt ueber (a) implementiert, (b) mit lokalen Fakes getestet und (c) mit echtem
Konto verifiziert. Nenne Testevidenz und konkrete externe Blocker. Behaupte nicht, dass der
urspruengliche Chat gefunden wurde: lokaler Verlauf lieferte keinen eindeutigen Treffer; die
Repo-Planungs-/Commit-Historie bestaetigt das Vorhaben.
```

## Baseline und Queue-Status 15.11.2026

T00 wurde am pre-feature Stand `caf041f1` reproduzierbar abgeschlossen: 73 Baseline-Tests fuer Ausgabenpruefung, Worker, SecretService und Graph-Mail-Aufrufstellen bestanden. Commit `b39041fd` ist der erste Collector-Code. T01-T07 sind nach lokaler Acceptance-Evidenz abgeschlossen. T04 deckt Auth-Erneuerung beim expliziten Probe-/Retry-Klick ab. T05 unterstuetzt auswählbar eigenes oder freigegebenes Postfach, mit Scope-Wahl, Consent und Auth-Verhalten durch Fakes geprueft. Exakte optionale Absenderadressen werden zusaetzlich zur bestaetigten Domain geprueft; bei Pipelinefehlern wird kein Checkpoint geschrieben. T08 bleibt extern blockiert, weil der Benutzer Mailboxtyp, Mailbox und Absenderdomain noch klaeren muss. T09 bleibt wegen historischer PDF-Gitobjekte offen.

Auth-Erneuerung, Mailmatcher, Shared-Mailbox-Modus und Checkpoint-Fehlerverhalten bestehen mit 103 gezielten Connector-/Dialog-/Foundationtests sowie **2446 passed, 7 skipped** in der Vollsuite. Ruff, gezieltes MyPy, Queue-/Provider-YAML, Diff-Check und Diff-Secret-Musterpruefung sind bestanden. Es sind keine realen Postfach- oder Absenderdaten eingetragen. `Mail.Read` bleibt Standard; `Mail.Read.Shared` wird nur nach ausdruecklicher Auswahl des Shared-Mailbox-Typs und mit sichtbarem Consent angefordert.

## Sicherheitsnachtrag 15.11.2026

Die lokale Collector-Datenstruktur unter `%LOCALAPPDATA%` wird auf Windows rekursiv mit `icacls` eingeschraenkt (aktueller Benutzer, SYSTEM, Administratoren), und Initialisierung bricht bei ACL-Fehlern fail-closed ab. Der ACL-Test sowie eine isolierte Windows-Tempverzeichnispruefung sind bestanden. Alle 17 zuvor getrackten PDFs sind aus dem aktuellen Git-Index entfernt und durch repo-weites `*.pdf` in `.gitignore` fuer kuenftige Commits ausgeschlossen. Lokale Kopien bleiben zur Vermeidung von Datenverlust vorhanden und ignoriert. Payment-QR- und PLC-Zollformular-Tests erzeugen synthetische PDFs zur Laufzeit; Vollsuite: 2.443 passed, 7 skipped. `git ls-files -- *.pdf` ist leer. Alte Git-Objekte enthalten die entfernten Dateien weiterhin; `AGENTS.md` verbietet Force-Push und History-Rewrite. T09 bleibt offen, bis die historische Blob-Aufbewahrung bewertet ist; historische Remote-Objekte sind nicht geloescht.

## Aktueller persoenlicher Schritt

Der Benutzer muss zuerst Anbieter, zugehoerige Rechnungs-Mailbox und bestaetigte
Absenderdomain(s) feststellen. Er soll diese Werte ausschliesslich im lokalen Dialog eingeben.
Bis dahin gibt es keinen sinnvollen Live-Graph-Probe und keine echte Mailroute, die als
verifiziert gelten kann. Der lokale Entwicklungs- und Sicherheitsfortschritt kann unabhaengig
davon fortgesetzt werden.
