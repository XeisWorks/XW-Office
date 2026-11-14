# Fortsetzungs-Goal fuer GPT-6-Luna

**Stand:** 14.11.2026 (Fehlerredaktion, kataloggesteuerte Portale, Tool-Recherche und Vollsuite 2.428/7 ergaenzt)
**Repository:** `XeisWorks/XW-Office`, Branch `main`
**Ausgangslage:** Die technische MVP-Grundlage ist weitgehend implementiert und lokal getestet. Der erste echte Rechnungsabruf ist noch nicht verifiziert. Der Benutzer hat bestaetigt, dass Anbieter-Mailbox und Absenderdomain(s) noch geklaert werden muessen.

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
   Insbesondere keine erfundenen Mail-Absenderregeln, Portal-Selektoren, API-Rechte oder
   Rechnungsdaten. Temp-Downloadpfade nutzen `workspace_download_path()` fuer Graph, Browser,
   Mollie und manuellen Import; diese Funktion begrenzt bereinigte Anbieterdateinamen auf den
   Workspace und prueft Traversal/Geraetedateien. Pruefe diese bestehende Loesung, statt sie
   erneut zu bauen. Der OneDrive-Sink nutzt ebenfalls eindeutige temporaere Dateien pro
   Publish und entfernt Teildateien nach Fallback-Schreibfehlern; parallele identische sowie
   divergierende Zielinhalte sind gezielt getestet. Der Mollie-PDF-Download ist ebenso auf 25 MiB
   begrenzt und gestreamt. Pruefe diese vorhandenen Schutzmassnahmen gegen Code und Tests, statt
   sie neu zu bauen. Der Browseradapter hat generische Fake-Portal-Tests, aber keine echten
   Anbieter-Callbacks. Das Journal verwendet Schema 4: neue Dokumente speichern keine rohen
   `external_id`-Werte in `documents`; vorhandene Schema-1-bis-3-Werte werden in gehashte
   Provenienz migriert und aus der aktiven Spalte entfernt. Erhalte die Hash-basierte
   Konflikterkennung und fuehre keinen Klartext-Fallback wieder ein.
   Der Dialog listet gespeicherte Providerverbindungen, aktualisiert Einstellungen mit stabiler
   Connection-ID und verhindert die Reaktivierung nicht verifizierter Routen. Angaben zu
   unverifizierten Routen koennen als deaktivierte Entwuerfe lokal gespeichert werden. Fuer
   `official_api` gibt es eine maskierte Eingabe, die das Credential ausschliesslich ueber
   `SecretStore`/Windows Credential Manager sichert; die Mollie-Factory liest diesen SecretRef
   und bekommt den gewaehlten Zeitraum. Erhalte diese Guardrails; vollstaendige
   capability-basierte Auth-/Retryaktionen bleiben ein gesonderter offener T04-Punkt. Provider-
   Portale werden fuer `portal_hosts` bereits als HTTPS-Menue angeboten; Hostvalidierung und
   manuelle Login-/Download-Klarstellung nicht entfernen und keine Portalautomation ohne
   Live-Verifikation erfinden.
   Der allgemeine `BackgroundWorker` protokolliert Ausnahme-Text. Monatsabruf, Graph-Mailbox-
   Probe und manueller PDF-Import redigieren fatale Fehler vor Worker-Logging und UI-Ausgabe.
   Diese Grenzen sind umgesetzt und getestet; neue Workergrenzen duerfen keine rohen
   Providerfehler, Tokens, signierten URLs oder Exception-Chains protokollieren.
   Der Graph-Mailbox-Probe-Button ist nur fuer Routen mit Katalogmethode `mail` aktiv; erhalte
   diese methodenbasierte UI-Sperre. Weitere capability-basierte Auth-/Retry-/Portalaktionen
   sind noch nicht vollstaendig umgesetzt.
4. Der Live-Mailpilot ist extern blockiert: Anbieter, Rechnungs-Mailbox und bestaetigte
   Absenderdomain(s) sind noch nicht geklaert. Frage nie nach diesen Werten oder Geheimnissen
   im Chat. Wenn der Benutzer soweit ist, gib genau eine lokale UI-Anweisung: in Finanzen >
   Ausgabenpruefung > Rechnungen abrufen Anbieter/Verbindung mit Mailbox und bestaetigten
   Absenderdomain(s) konfigurieren, "Graph-Mailbox testen" waehlen und sichtbaren Microsoft-
   Login/Consent abschliessen. Fuehre keinen Liveversuch mit geratenen Werten aus.
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

## Aktueller persoenlicher Schritt

Der Benutzer muss zuerst Anbieter, zugehoerige Rechnungs-Mailbox und bestaetigte
Absenderdomain(s) feststellen. Er soll diese Werte ausschliesslich im lokalen Dialog eingeben.
Bis dahin gibt es keinen sinnvollen Live-Graph-Probe und keine echte Mailroute, die als
verifiziert gelten kann. Der lokale Entwicklungs- und Sicherheitsfortschritt kann unabhaengig
davon fortgesetzt werden.
