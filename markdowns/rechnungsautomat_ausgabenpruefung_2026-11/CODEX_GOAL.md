# Codex-/goal für XW-Office (VS Code)
**Bitte den Auftrag ab `/goal` kopieren:**

```text
/goal
Implementiere im Repository XeisWorks/XW-Office auf aktuellem main den neuen Rechnungsautomaten im vorhandenen Untermenü FINANZEN > AUSGABENPRÜFUNG.

Verbindliche Dateien:
markdowns/rechnungsautomat_ausgabenpruefung_2026-11/START_HERE.md
markdowns/rechnungsautomat_ausgabenpruefung_2026-11/ARCHITEKTUR.md
markdowns/rechnungsautomat_ausgabenpruefung_2026-11/SICHERHEIT_UND_2FA.md
markdowns/rechnungsautomat_ausgabenpruefung_2026-11/PROVIDER_REGISTRY.yaml
markdowns/rechnungsautomat_ausgabenpruefung_2026-11/TASK_QUEUE.yaml

Zuerst AGENTS.md und aktuellen Code/Tests lesen. Architekturvorgaben priorisieren, bestehende Ausgabenprüfung, XW-Flow, sevDesk, Graph-Mail und Produkt-Hub unverändert funktionsfähig halten. Schlanken neuen PySide6-Dialog und Service-Adapter entwickeln: Ein Klick „Alle aktiven Portale abrufen“, per Dialog wählbarer synchronisierter OneDrive-Business-Ordner, progressiver Anbieterstatus, sicherer Download, echte PDF-Validierung, SHA-256-Deduplizierung, Mandantentrennung, sichere Wiederholungen. Methodenreihenfolge: Mail-PDF > offizielle API > Playwright mit lokalem persistenten Profil > manuelle Belegübernahme. 2FA/Passkeys/Microsoft-OAuth im regulären sichtbaren Browser und mit Nutzerbestätigung; falls Login abgelaufen ist: „Anmeldung erneuern“, nach Erfolg nur diesen Adapter fortsetzen. Kein CAPTCHA-/2FA-Bypass, keine automatisierten Google-Login-Tricks. Keine unbewiesenen DOM-Selektoren oder Portal-APIs erfinden. Browserprofile, Passwörter, Cookies, OTPs nie commiten; keyring/DPAPI verwenden, .env nur optionales lokales Fallback, nicht GitHub-/Railway-Secrets für lokale Desktop-Sitzungen.

Implementiere TASK_QUEUE.yaml in Prioritätsreihenfolge und hake alle verifizierten Gates ab. Mindestens Mail-PDF-Collector, Mollie-invoices.read-Adapter und ein Playwright-Mock-/Pilotportal mit echter Download-/Nachlogin-Logik; weitere Plattformen nur nach tatsächlichen Tests aktivieren, sonst klar MANUAL_ACTION. OneDrive-Sync-Status ehrlich ausweisen, keine falsche Cloudbestätigung. Alle Tests mit Mocks, lokale Qt- und PDF-Regression, ruff, pytest, git diff --check, Secret-Scan und kurze Dokumentation. Keine automatischen Buchungen; Einnahmenbelege sauber getrennt von Ausgaben.

Arbeite eigenständig weiter und stoppe nur für zwingende persönliche Handlungen: einmalige Anmeldung, Authenticator/Passkey/2FA, OneDrive-Zielordner oder Entra-Zustimmung bzw. schmal berechtigter API-Token. Dann jeweils GENAU eine einfache Klickanweisung geben; nach meinem „erledigt“ sofort fortsetzen, kein weiteres „go on“ verlangen. Kein Geheimnis im Chat erfragen. Nutze vorhandene MCPs/CLIs soweit sinnvoll, erzwinge keinen Railway-Deploy (serverseitig derzeit instabil). Sinnvolle Zwischenschritte committen; abgeschlossenen, getesteten Stand nach AGENTS.md auf origin/main pushen, Working Tree sauber.

Am Schluss: liste getestete Provider, noch manuelle Provider, offene Auth-Schritte und OneDrive-Status, ohne ungeprüfte Livefunktion als „fertig“ auszugeben.
```

## Definition von „fertig“
- UI und Ablauf zuverlässig **lokal getestet**, ohne neue SaaS-Abos.
- Aktive Provider sind **end-to-end verifiziert**, sonst transparent als experimentell/manuell markiert.
- Abruf kann nach 2FA/Sessionablauf innerhalb des Dialogs wiederaufgenommen werden.
- Keine sensiblen Daten in Git, OneDrive-Sitzungsprofilen, Logs oder CI-Artefakten.
