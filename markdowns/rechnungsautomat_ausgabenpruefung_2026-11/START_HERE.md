# Rechnungsautomat für XW-Office – START HERE

**Stand: 14.11.2026 | Lokale Foundation und Adapter-Fakes getestet; keine live verifizierte Rechnungsroute.**

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

1. **Lokales Setup:** Zielordner wählen. Der Zeitraum ist mit dem aktuellen Kalendermonat in
   `Europe/Vienna` vorbelegt. Verbindungsangaben für eine noch nicht verifizierte Route lassen
   sich lokal als deaktivierter Entwurf speichern; aktivieren lässt sie sich erst, wenn die
   konkrete Route im Katalog als `verified` steht. Der Graph-Mailbox-Probe testet Zugriff,
   verifiziert aber keine Rechnungsroute.
2. **Monatslauf:** **„Alle aktiven Verbindungen abrufen“** verarbeitet nur aktivierte, aktuell
   verifizierte Routen. Unabhängige Verbindungen laufen begrenzt parallel; pro Konto läuft
   höchstens ein Job. Ohne Live-verifizierte Route bleibt **„PDF manuell hinzufügen“** der
   nutzbare Weg durch dieselbe PDF-Prüfung und Ablage.
3. **Anmeldung:** Graph kann für den Mailbox-Probe eine sichtbare Microsoft-Anmeldung öffnen.
   Der Dialog bietet noch keine allgemeine Aktion **„Anmeldung erneuern“** oder eine
   routebezogene Wiederaufnahme nach einem Authfehler. Authfehler werden im Ergebnis angezeigt;
   das ist ein offener T04-Punkt.

## Verbindliche Produktentscheidungen

- **Desktop-MVP:** Windows/PySide6. Standardziel ist ein bewusst ausgewählter, beschreibbarer
  OneDrive-Business-Syncordner. Lokal gespeichert bedeutet `SYNC_PENDING`, nicht
  `CLOUD_VERIFIED`.
- **Route und Fallback:** Katalogstatus, Factory-Prüfung und Verbindungsaktivierung sind
  fail-closed. Konfigurierbare Priorität und Capability-gesteuerte Auth-/Retry-Aktionen sind
  Zielarchitektur, aber im Dialog noch nicht vollständig umgesetzt.
- **Keine Provider-Sonderlogik in UI/Orchestrator:** Manifest und Connector-Factories sind
  explizit und die gemeinsame Pipeline ist providerunabhängig. Der aktuelle Dialog ist noch ein
  erster Slice; Capability-gesteuerte Aktionen bleiben offen.
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

## Echtes Repository: aktueller Stand

Implementiert und lokal getestet sind der manuelle PDF-Slice, der providerunabhängige
Monatsdialog und Orchestrator, Graph-Mailbox-Zugriff/Anhangsreader, Mollie-API-Adapter,
Playwright-Fake-Portal, PDF-Prüfung, lokales No-Clobber-Publishing, Journal mit Resume und
Provenienz sowie Verbindungsbearbeitung mit stabiler Connection-ID. Der Dialog kann den Zielordner und eine vorhandene mandantenspezifische `_needs_review`-Prüfablage öffnen. Für unbekannte oder mehrdeutige Rechnungsdaten bleibt die inhaltliche Prüfung manuell; lokale Ablage wird weiter als `SYNC_PENDING` markiert.

Relevante Implementierungsstellen:

- `src/xw_office/ui/modules/expense_review/view.py` und
  `src/xw_office/ui/modules/expense_review/invoice_collector_dialog.py`: Einstieg, lokales
  Setup, Zeitraum, Verbindungsverwaltung, Graph-Probe, manueller Import und Ergebnisanzeige.
- `src/xw_office/services/invoice_collection/`: Domain, Registry, Factories, Connectoren,
  PDF-Pipeline, Sink, Journal, Secret- und Authgrenzen, Orchestrator.
- `src/xw_office/core/app_paths.py`: separate Pfade für Invoice-Collection-Zustand unter
  `%LOCALAPPDATA%`; das zentrale PostgreSQL wird nicht als lokaler Auth-/Browserzustand benutzt.
- `markdowns/rechnungsautomat_ausgabenpruefung_2026-11/IST_STAND_UND_ABSCHLUSSPLAN_2026-11-14.md`:
  detaillierte Befunde, offene Punkte, externe Blocker und letzte Testevidenz.
- `markdowns/rechnungsautomat_ausgabenpruefung_2026-11/TASK_QUEUE.yaml`: verbindliche
  Aufgabenstatus und Abnahmeevidenz.

Keine echte Anbieterroute oder OneDrive-Remote-Synchronisation ist nachgewiesen. Die lokal
gespeicherten externen IDs liegen seit Journal-Schema 4 nicht mehr im Klartext im aktiven
Datensatz; SQLite garantiert dadurch keine physische Bereinigung alter Datenseiten oder Backups.

## Dateien und Reihenfolge

1. `START_HERE.md` – Zielbild und Entscheidungen.
2. `ARCHITEKTUR.md` – Ports/Adapter, Datenmodell, Zustände, Pipeline und Abnahmekriterien.
3. `SICHERHEIT_UND_2FA.md` – Bedrohungsmodell, sichere Ablage und Benutzerhandlungen.
4. `PROVIDER_REGISTRY.yaml` – versionierter Provider-Katalog mit Routen und Reifegraden.
5. `TASK_QUEUE.yaml` – inkrementelle Umsetzung mit vertikalem ersten Slice.
6. `GPT6_LUNA_FORTSETZUNGS_GOAL_2026-11-14.md` – aktueller, kopierbarer Folgeauftrag für GPT-6-Luna.

## Persönliche Schritte – nur wenn die Implementierung sie tatsächlich benötigt

- OneDrive-Business-Zielordner auswählen.
- Für den ersten Mail-Pilot Provider, Rechnungs-Mailbox und bestätigte Absenderdomains lokal
  klären und nur im Dialog eintragen; keine dieser Angaben im Chat posten.
- Danach Graph-Mailbox-Test und sichtbaren Microsoft-Login/Consent im lokalen UI abschließen.
- Echten Rechnungsbeleg und Wiederholung lokal prüfen; ein erfolgreicher Mailbox-Probe allein
  reicht nicht zur Route-Verifikation.
- Ein API-Credential nur bei einer offiziellen API-Route über das maskierte Eingabefeld
  hinterlegen; der Wert liegt im Windows Credential Manager, SQLite hält nur die Referenz.
  Mollies [List-invoices-API](https://docs.mollie.com/reference/list-invoices) erfordert einen
  Advanced Access Token oder OAuth-Zugriff mit `invoices.read`; ein normaler Profil-API-Key ist
  dort nicht als Zugriffsart dokumentiert.
- Browser-Login einschließlich Authenticator/Passkey/SMS nur für einen konkret unterstützten
  und erlaubten Portalpilot im sichtbaren Browser durchführen; ein solcher Anbieterpilot ist
  noch nicht verifiziert.
- Microsoft-Graph-Zustimmung für die konkret angezeigten minimalen Rechte erteilen.

**Technische Referenzen:** [Playwright Auth](https://playwright.dev/python/docs/auth),
[Playwright Downloads](https://playwright.dev/python/docs/downloads),
[MSAL Token](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens),
[Graph Upload](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0).
