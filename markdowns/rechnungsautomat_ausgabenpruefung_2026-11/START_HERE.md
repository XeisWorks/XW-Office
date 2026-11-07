# Rechnungsautomat für XW-Office – START HERE

**Stand: 07.11.2026 | Architektur und Foundation-MVP implementiert; keine live verifizierten Portalrouten.**

## Ziel

In **Finanzen > Ausgabenprüfung** kommt ein zusätzlicher Button **„Rechnungen abrufen“**.
Der Dialog sammelt Belege aus aktivierten Verbindungen und legt sie in einem vom Benutzer
gewählten OneDrive-for-Business-Syncordner ab. Gebührenrechnungen, SaaS-Belege,
Gutschriften und separat gekennzeichnete Einnahmen-/Auszahlungsnachweise durchlaufen dieselbe
sichere Dokumentpipeline. Es entsteht keine zusätzliche SaaS-Pflicht und keine automatische
sevDesk-Buchung.

## Leitentscheidung: Portal, Abrufweg und Ablage trennen

Ein Anbieter ist nicht gleichbedeutend mit einer technischen Abrufmethode. Ein Portal kann
heute E-Mail-Anhänge liefern, später eine API anbieten und bei einzelnen Kontotypen weiterhin
einen manuellen Import benötigen. Deshalb besteht die Lösung aus austauschbaren Bausteinen:

```text
Provider-Katalog -> lokale Verbindung -> Abrufroute -> Dokumentpipeline -> Ablageziel
Mollie             XW/Mollie AT        API            prüfen/deduplizieren OneDrive-Sync
BrowserStack       XW/BrowserStack     Mail           prüfen/deduplizieren OneDrive-Sync
Neues Portal       Mandant/Konto       neuer Adapter  unverändert          unverändert
```

- **Provider-Katalog:** versionskontrollierte, secretfreie Beschreibung eines Anbieters.
- **Verbindung (Connection):** lokale Zuordnung von Provider, Kontoalias, Mandant und
  aktivierten Abrufrouten; enthält nur Secret-Referenzen, nie Secret-Werte.
- **Abrufroute (Connector):** Mail, offizielle API, Browser oder manueller Import. Sie liefert
  Dokumentkandidaten und schreibt keine Dateien ins Archiv.
- **Dokumentpipeline:** validiert PDF, normalisiert Metadaten, berechnet SHA-256, dedupliziert
  und publiziert erst dann.
- **Ablageziel (Sink):** anfangs lokaler OneDrive-Syncordner, später optional Graph-Upload.

Damit erfordert ein neues Portal normalerweise nur Manifest, Connector/Route und dessen
Contract-Tests – keine Änderung an Dialog, Orchestrator, PDF-Pipeline oder OneDrive-Code.

## Bedienung in drei Schritten

1. **Einmalig:** Zielordner wählen, Provider-Verbindungen einem Mandanten (`xw` oder
   `wuedara`) zuordnen und benötigte Routen aktivieren. Microsoft-Zustimmung, schmal
   berechtigte API-Tokens und sichtbare Portal-Logins werden nur bei Bedarf angefordert.
2. **Danach:** **„Alle aktiven Verbindungen abrufen“** startet einen Lauf. Unabhängige
   Verbindungen laufen begrenzt parallel; pro Konto läuft höchstens ein Job. Jeder Kandidat
   durchläuft dieselbe sichere, idempotente Pipeline.
3. **Login abgelaufen:** Nur die betroffene Route zeigt **„Anmeldung erneuern“**. Der Benutzer
   meldet sich im sichtbaren Browser inklusive 2FA an. Danach wird diese Route fortgesetzt;
   andere Verbindungen bleiben unbeeinträchtigt.

## Verbindliche Produktentscheidungen

- **Desktop-MVP:** Windows/PySide6. Standardziel ist ein bewusst ausgewählter, beschreibbarer
  OneDrive-Business-Syncordner. Lokal gespeichert bedeutet `SYNC_PENDING`, nicht
  `CLOUD_VERIFIED`.
- **Priorität je Verbindung:** verifizierter Mail-PDF-Weg > offizielle API > Playwright mit
  dediziertem Benutzerprofil > manueller Import. Die Reihenfolge ist konfigurierbar; ein
  Fallback startet nur bei einem passenden, klassifizierten Fehler.
- **Keine Provider-Sonderlogik in UI/Orchestrator:** Anzeige und Aktionen werden aus
  Capabilities und Status abgeleitet. Provider-spezifische DOM-, API- und Mailregeln bleiben
  im jeweiligen Connector.
- **Secrets:** Windows Credential Manager/keyring oder geprüfter verschlüsselter Speicher.
  Keine echten Tokens, Cookies, Passwörter, 2FA-Seeds, PDFs oder Browserprofile in Git,
  OneDrive-Sitzungsordnern, Logs oder Testartefakten.
- **2FA und Bot-Schutz:** Der Benutzer bestätigt Passkey/Authenticator/SMS selbst. Kein
  CAPTCHA-, MFA- oder Anti-Bot-Bypass. Ein blockierter Browserweg endet nachvollziehbar in
  `MANUAL_ACTION`.
- **Keine Buchungen oder Steuerentscheidungen:** Die Funktion sammelt, klassifiziert und
  kennzeichnet Dokumente. Fachliche Freigabe und Buchung bleiben getrennte Schritte.
- **Ehrlicher Reifegrad:** `planned`, `experimental`, `verified` und `disabled` gelten je
  Abrufroute. Nur mit echtem Dokument plus idempotentem Wiederholungstest darf eine Route
  `verified` werden.

## Echtes Repository: Einhängepunkte

Der aktuelle Stand enthält bereits den manuellen vertikalen Slice, den providerunabhängigen
Dialog/Orchestrator sowie getestete Graph-Mail-, Mollie- und Playwright-Adaptergrenzen. Reale
Providerkonten, Portal-DOMs und Cloud-Remoteprüfung bleiben bewusst ungeprüft, bis die jeweilige
Verbindung lokal autorisiert und mit einem echten Dokument wiederholt getestet wurde.

- `src/xw_office/ui/modules/expense_review/view.py`: zusätzlicher Button; bestehende zwei
  Mandanten, Tabellen, Aktualisierung, Lieferantenportale und Einstellungen bleiben erhalten.
- `src/xw_office/core/worker.py` und `src/xw_office/ui/async_action.py`: vorhandene
  Thread-/Lifecycle-Muster wiederverwenden; für mehrere Jobs einen kleinen, begrenzten
  Orchestrator darüber setzen.
- `src/xw_office/core/app_paths.py`: derzeit liegen `state/` und Logs im Repository. Für
  Browserprofile, Token-Cache, lokale Registry-Konfiguration und Journal ist deshalb vor dem
  ersten Live-Login ein neuer `%LOCALAPPDATA%`-Pfadhelfer erforderlich.
- `src/xw_office/services/secrets/service.py`: vorhandenen SecretService nicht ungeprüft für
  persönliche Portal-Logins zweckentfremden; Secret-Referenzen und Speicherart explizit
  modellieren.
- `src/xw_office/services/mailing/graph_client.py`: bestehender Client nutzt aktuell breite
  Mail-Rechte, Device-Code-Ausgabe auf der Konsole und einen Klartext-JSON-Cache unter
  `state/`. Nicht direkt als sichere MVP-Lösung übernehmen; zuerst UI-fähige Authentifizierung,
  minimale Scopes und verschlüsselten Cache schaffen, ohne bestehende Mailfunktionen zu
  beschädigen.
- `src/xw_office/core/database.py`: zentrale PostgreSQL-Datenbank nicht für lokale
  Browser-/Tokenzustände verwenden. Das Invoice-Journal ist eine eigene lokale SQLite-Datei
  unter `%LOCALAPPDATA%` mit Migrationen.
- `src/xw_office/core/shared_paths.py`: darf einen OneDrive-Pfad vorschlagen, ersetzt aber nie
  die bewusste Ordnerwahl. Der Product-Hub-OneDrive-Client bleibt unverändert.
- `AGENTS.md`: auf aktuellem `main` arbeiten; getestete Änderungen committen und nach
  `origin/main` pushen.

## Dateien und Reihenfolge

1. `START_HERE.md` – Zielbild und Entscheidungen.
2. `ARCHITEKTUR.md` – Ports/Adapter, Datenmodell, Zustände, Pipeline und Abnahmekriterien.
3. `SICHERHEIT_UND_2FA.md` – Bedrohungsmodell, sichere Ablage und Benutzerhandlungen.
4. `PROVIDER_REGISTRY.yaml` – versionierter Provider-Katalog mit Routen und Reifegraden.
5. `TASK_QUEUE.yaml` – inkrementelle Umsetzung mit vertikalem ersten Slice.
6. `CODEX_GOAL.md` – kompakter Folgeauftrag.

## Persönliche Schritte – nur wenn die Implementierung sie tatsächlich benötigt

- OneDrive-Business-Zielordner auswählen.
- Portal-Login einschließlich Authenticator/Passkey/SMS im sichtbaren Browser durchführen.
- Einen minimal berechtigten API-Token im lokalen geschützten Dialog hinterlegen.
- Microsoft-Graph-Zustimmung für die konkret angezeigten Rechte erteilen.

**Technische Referenzen:** [Playwright Auth](https://playwright.dev/python/docs/auth),
[Playwright Downloads](https://playwright.dev/python/docs/downloads),
[MSAL Token](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens),
[Graph Upload](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0).
