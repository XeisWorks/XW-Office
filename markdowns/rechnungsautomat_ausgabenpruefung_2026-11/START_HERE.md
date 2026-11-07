# Rechnungsautomat für XW-Office – START HERE
**Stand: 07.11.2026 | Konzept für Codex, noch keine implementierte Funktion.**

## Ziel
In **Finanzen > Ausgabenprüfung** einen Button **„Rechnungen abrufen“** ergänzen. Ein Dialog zeigt die aktiven Portale und einen Button **„Alle aktiven Portale abrufen“**. PDF-Gebührenrechnungen, SaaS-Belege und separat gekennzeichnete Einnahmen-/Auszahlungsnachweise sollen in **einem vom Benutzer ausgewählten OneDrive-for-Business-Ordner** landen. Keine zusätzliche SaaS-Pflicht.

## Bedienung in drei Schritten
1. **Einmalig:** Zielordner über „Ordner wählen“ festlegen, relevante Portale aktivieren, E-Mail-Zugang via Microsoft-Anmeldung freigeben, API-Tokens falls nötig sicher hinterlegen. Pro Playwright-Portal einmal auf „Anmelden“ klicken, normale Anmeldung inklusive 2FA im sichtbaren Browser abschließen.
2. **Danach:** „Alle aktiven Portale abrufen“ drücken. Die App sammelt PDF-Anhänge, ruft offizielle APIs ab und nutzt Playwright nur dort, wo kein einfacherer Weg existiert. Schon gespeicherte Rechnungen werden erkannt.
3. **Login abgelaufen:** Anbieterzeile zeigt „Anmeldung nötig“ samt **„Anmeldung erneuern“**. Ein sichtbares Browserfenster öffnet den regulären Login. Nach erfolgreich bestätigter Anmeldung wird genau dieser Abruf wiederholt; alle anderen Anbieter laufen weiter.

## Wichtige Entscheidungen
- **MVP:** Windows-PySide6, OneDrive-Business-**Sync-Verzeichnis** als Speicherziel. Pfad per QFileDialog auswählen, nicht hardcoden. Lokal gespeichert heißt noch nicht „in OneDrive-Cloud bestätigt“. Cloudstatus nur bei wirklicher Prüfung als bestätigt ausgeben. Falls kein OneDrive-Sync verfügbar: optionale Microsoft-Graph-Upload-Erweiterung mit eigener delegierter Berechtigung.
- **Priorität:** E-Mail mit PDF > offizielle Rechnungs-API > Playwright mit dediziertem Benutzerprofil > manueller Download/Import.
- **Secrets:** Windows Credential Manager / keyring, optional vorhandener verschlüsselter SecretService für passende API-Tokens. **Keine** echten Zugangsdaten, Cookies oder 2FA-Seeds im Repository, `.env.example`, Railway oder GitHub Secrets. Eine lokale `.env` ist **nicht verschlüsselt** und nur optionales Entwicklungs-Fallback.
- **2FA:** Nutzer bestätigt Passkey/Authenticator/SMS selbst. Keine Umgehung von CAPTCHA, 2FA oder Bot-Schutz; Google-Login per Automationsbrowser kann gesperrt werden.
- **SaaS:** 0 Pflicht-Abos; optional später EIN Aggregator bei nachgewiesenen Lücken. invoice-fetcher für Amazon Business erst nach einem vollständigen Vergleichslauf kündigen.
- **Keine Buchungen:** Belege sammeln, klassifizieren und kennzeichnen, aber **nicht** selbst in sevDesk buchen oder USt-Entscheidungen treffen.

## Echtes Repo: Einhängepunkte
- `src/xw_office/ui/modules/expense_review/view.py` enthält `ExpenseReviewView` mit zwei Mandanten (`xw` / `wuedara`), Ausgabentabellen, Aktualisieren-Button und Einstellungen. Der neue Button muss **zusätzlich** erscheinen, vorhandene Funktionen bleiben.
- `src/xw_office/core/worker.py` (`BackgroundWorker`) und `src/xw_office/ui/async_action.py` wiederverwenden.
- `src/xw_office/services/secrets/service.py` bietet bereits DB-verschlüsselte Secrets, `src/xw_office/services/mailing/graph_client.py` Graph-Mailzugriff; bestehende Funktionen **nicht** durch unsichere neue Implementierungen ersetzen.
- `src/xw_office/core/shared_paths.py` unterstützt vorhandene OneDrive-Pfad-Auflösung; der Produkt-Hub-Graph-Client in `services/product_hub/onedrive.py` ist **nicht** für Rechnungsschreibzugriff gedacht.
- `AGENTS.md`: saubere Arbeit auf `main`, nach Tests Commit + Push zu `origin/main`.

## Dateien und Reihenfolge
1. `START_HERE.md` – diese Einleitung.
2. `ARCHITEKTUR.md` – konkrete Implementierung, Login/2FA, OneDrive, Datensicherheit, Tests.
3. `PROVIDER_REGISTRY.yaml` – Plattformen, konservative Startmethoden und offene Prüfungen.
4. `TASK_QUEUE.yaml` – priorisierte, überprüfbare Umsetzungsschritte.
5. `CODEX_GOAL.md` – kompakter Copy-Paste-Auftrag für VS Code.

## Persönliche Schritte (nur falls nötig)
- Eigenen OneDrive-Business-Ordner auswählen.
- Portal-Login inkl. vorhandener Authenticator-App / Passkey / SMS durchführen.
- Falls erforderlich einen nur für Rechnungslesen berechtigten API-Token im geschützten Dialog einfügen.
- Zustimmung zur Microsoft-Graph-Integration nur bei Bedarf erteilen.

**Quellen:** [Playwright Auth](https://playwright.dev/python/docs/auth), [Downloads](https://playwright.dev/python/docs/downloads), [MSAL Login](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens), [Microsoft Graph Upload](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0).
