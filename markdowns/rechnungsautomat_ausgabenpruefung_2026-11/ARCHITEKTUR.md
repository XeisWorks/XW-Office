# XW-Office Ausgabenprüfung: Rechnungsautomat – Architektur und Abnahmekriterien
**Stand 07.11.2026. Spezifikation – keine bereits produktiv geprüften Portaladapter.**

## 1. Unveränderte Basis
Vor Codeänderungen `AGENTS.md`, `src/xw_office/ui/modules/expense_review/view.py`, `src/xw_office/services/expenses/`, `src/xw_office/core/worker.py`, `src/xw_office/ui/async_action.py`, `src/xw_office/services/mailing/graph_client.py`, `src/xw_office/services/secrets/service.py`, `src/xw_office/core/shared_paths.py`, Tests und Konfiguration lesen. Live-Version erneut gegen Plan vergleichen.
`ExpenseReviewView` hat einen `QTabBar` für XeisWorks (`xw`) und WüdaraMusi (`wuedara`) und bestehende Bank-/Ausgaben-/Lieferantenportal-Logik. **Keine** bestehende Schaltfläche überschreiben; eigener Textbutton „Rechnungen abrufen“ + separater `InvoiceCollectorDialog`, damit `view.py` nicht weiter anwächst. Bestehende Lieferantenportale sind **URL-Zuordnungen**, keine automatisch authentifizierten Provider. Die neue Sammlung ist ein Eingangskorb und **keine automatische sevDesk-Buchung**; vorhandene XW-Flow-Bridge nicht doppeln.

## 2. Fertige Oberfläche
Dialog (Deutsch, mit Tastatur und klaren Fehlermeldungen):
- Kopf: „Alle aktiven Portale abrufen“ (primär), „Ordner wählen“, „Ordner öffnen“, Monat (Vormonat) / letzte 90 Tage / Zeitraum.
- Pfad und Status: „OneDrive-Ordner erkannt“, „Lokale Datei gespeichert; Sync noch nicht bestätigt“, „Ordner nicht beschreibbar“. Ein einfacher Initial-Wizard fordert nur tatsächlich fehlende Einstellungen an.
- Tabelle: **Portal, Mandant, Methode, Anmeldung, letzter Abruf, neue Belege, vorhandene Belege, Ergebnis, Aktion**. Pro Portal „Anmelden“, „Anmeldung erneuern“, „Jetzt abrufen“, „Portal öffnen“, „PDF manuell hinzufügen“.
- Fortschritt und Fehler pro Portal; Zustände `NOT_CONFIGURED`, `READY`, `NEEDS_LOGIN`, `NEEDS_2FA`, `BLOCKED`, `MANUAL_ACTION`, `ERROR` und Ergebnisse `NEW`, `ALREADY_PRESENT`, `NO_NEW_DOCUMENTS`. Login-Probleme anderer Portale dürfen Sammelabruf nicht stoppen.
- Zuordnung zu `xw` oder `wuedara` **explizit**, kein Übernehmen fremder Mandantendaten. Periodenauswahl entspricht Dokumentzeitraum, nicht zwingend Zahlungsdatum.

## 3. Servicelayer / Adapter-Vertrag
```text
src/xw_office/services/invoice_collection/
  models.py                 # InvoiceDocument, ProviderStatus, FetchResult
  provider_base.py          # ABC/Protocol: capabilities, probe_auth, fetch, open_login
  registry.py               # Konfiguration + Validierung, keine Zugangsdaten
  orchestrator.py           # Queue, Restart einzelner Provider, Signal-Progress
  state_repository.py       # lokale SQLite/geeignete DB nur Metadaten
  security.py               # keyring, Profilpfade, Maskierung/ACL
  playwright_runner.py      # headful Login, persistent_context, PDF-Download
  mail_collector.py         # Graph Mail.Read / PDF-Attachments
  mollie_invoices.py        # offizielle invoices.read API
  onedrive_sink.py          # synchronisierter Windows-Ordner, später Graph optional
  pdf_validation.py         # PDF-Inhalt, SHA256, Deduplikation
  providers/                # nur schrittweise verifizierte Adapter
src/xw_office/ui/modules/expense_review/invoice_collector_dialog.py
tests/unit/test_invoice_collection_*.py
tests/ui/test_invoice_collection_*.py
tests/integration/test_invoice_collection_*.py
```
Provider-Interface: `capabilities` (mail/api/browser/manual), `probe_auth(account) -> AuthStatus`, `fetch(period, account, sink, progress, cancel_event) -> FetchResult`, optional `open_login(account)`. Datenschema je PDF: provider_id, Mandant, account_alias, Dokumenttyp, externe ID, Rechnungsnr., Dokumentdatum, Leistungszeitraum, Betrag/Währung (optional), Quelle, SHA256, relativer Archivpfad, Syncstatus und Prüfstatus. `document_type` strikt getrennt in `fee_invoice`, `expense_invoice`, `receipt`, `credit_note`, `payout_statement`, `income_statement`. Kein automatisches Buchen aufgrund „Rechnung“ im Dateinamen.

### Worker, Browser und echte PDF-Dateien
- Bereits vorhandenen `BackgroundWorker` bzw. `UiAsyncAction` benutzen. Qt-Widgets nur über Qt-Signale im Hauptthread aktualisieren. Kooperativer Abbruch, Zeitlimits, begrenzte Wiederholungen, keine doppelten Starts. Abgebrochene Download-Transaktionen beim nächsten Lauf sicher wiederaufnehmen.
- Je Account ein **eigenes persistentes Chromium-UserDataDir**, nur ein laufender Context pro Verzeichnis, lokal außerhalb des Repos. Playwright-Sessions können ablaufen. Beim Sammelabruf zunächst geschützte Rechnungsseite prüfen; wenn Redirect/Unberechtigt `NEEDS_LOGIN` setzen. Beim Klick „Anmeldung erneuern“ sichtbaren Browser im selben separaten Profil öffnen; Nutzer authentifiziert sich und bestätigt 2FA selbst, danach geschützten Abruf nachprüfen und betroffenen Provider fortsetzen.
- Kein automatisiertes Erraten von Passwörtern, kein erzwungenes TOTP-Seed, kein CAPTCHA- oder Anti-Bot-Bypass, keine selbst gescripteten WebAuthn-Zugriffe. Browser-Profile, Cookies, LocalStorage können einen Account übernehmen: niemals im Repo, Log oder OneDrive speichern.
- Downloads über Playwright `with page.expect_download(): ...; download.save_as(temp_file)` **nach echtem DOM-Test**, nicht über erfundene CSS-Selektoren, veraltete URL-Routen oder `requests` mit zusammengebastelten Cookie-Headern. Bei PDF im neuen Tab dokumentiert sichere Alternative entwickeln. Nur registrierte offizielle Hostnames. Retry bei transienten Fehlern, kein aggressives Scraping.
- Bei Google können automatisierte Browser-Anmeldungen ausdrücklich blockiert werden: Google-Payments/AdSense über offizielle Konten, E-Mail, Exporte und nötigenfalls **manuellen Import** lösen. Nie behaupten, Google-Login mit Playwright sei zuverlässig.
- Für einfache Fälle **Mail vor Browser**: vorhandener `GraphMailClient` kann Anhänge abrufen; sein bisheriger MSAL-Device-Code-Flow schreibt aber Aufforderungen an die Konsole und verwendet einen JSON-Cache unter `state/`. Keine versteckte Konsole/Blockade in neuer UI und keine unverschlüsselte neue MSAL-Tokenablage: entweder sicher UI-tauglich erweitern und regressionsprüfen oder eigenen Graph-Collector mit MSAL + `msal-extensions` (Windows DPAPI) implementieren. Ein reiner Read-Adapter benötigt `Mail.Read` (für Shared Mailbox Rechte prüfen).
- PDF-Mailfilter nicht allein nach Absenderanzeige/Betreff, sondern Senderdomain, Message-ID, Attachment-ID, MIME/PDF-Inhalt und Alias prüfen. Rechnungslinks aus Mails nicht unkontrolliert ausführen (Phishing-Risiko). Graph Pagination und mehrmonatige Rücksuche beachten.

## 4. OneDrive for Business: minimaler Aufwand, echte Statuswerte
**Standard:** `QFileDialog.getExistingDirectory` wählt beschreibbaren **lokal synchronisierten OneDrive-Business-Ordner**. `OneDriveCommercial` kann Default vorschlagen; immer Auswahl/Bestätigung durch Nutzer. Nutzerpfad pro PC persistieren, keine Festverdrahtung an fremde Benutzerprofile. Test-Datei/Schreibrecht prüfen, niemals still in `C:\\Users\\...\\Downloads` ausweichen. Optional manuelle Kontrolle durch Explorer und Graph-Fernprüfung.

Beispielstruktur: `<gewählter Ordner>/XeisWorks/2026/11/Stripe/` bzw. `.../WuedaraMusi/2026/11/Mollie/`; unklare Rechnungsmonate: `Ungeprueft/`. Dateiname `YYYY-MM__anbieter__kontoalias__dokumenttyp__belegnr-oder-hash8.pdf` (sanitisiert, eindeutige Kollisionbehandlung). Ein Download landet erst in lokalem temporären Verzeichnis, PDF-Header/Parse und maximale Größe prüfen, SHA256 bilden und **atomar** in Ziel verschieben. In SQLite Dateiidentität + Provider + Konto + externe ID/Belegnummer sichern; existierendes gleiches Dokument niemals überschreiben. Mehrfachabruf muss idempotent sein. Metadaten erst nach erfolgreichem Save als „gespeichert“ schreiben.

**Wichtig:** Lokales Ablegen im OneDrive-Verzeichnis = `SYNC_PENDING`, **nicht** `CLOUD_VERIFIED`. Optional bei vorhandenen Graph-Rechten Remote-Präsenz/Hash prüfen; nie vorab „hochgeladen“ melden. Für rechnerunabhängigen Upload später **eigene** Graph-Integration mit delegiertem `Files.ReadWrite` und `PUT /drives/{drive-id}/items/{parent-id}:/{filename}:/content` (bis 250 MB), vorher gewählten Drive/Ordner verifizieren; auf Konflikte nicht überschreiben. Der vorhandene `OneDriveAssetClient` dient ausschließlich Product-Hub-Assets und darf nicht um Rechnungs-Schreibrechte erweitert werden. Bei offline OneDrive: in dauerhafter Retry-Queue behalten.

## 5. Sicherheit und Konfiguration
- Lokale Portal-Passwörter nach Möglichkeit **überhaupt nicht speichern**; sichtbarer Login plus Browser-Sitzung ist die normale UX. Falls explizit notwendig: **Windows Credential Manager** per Python `keyring`, getrennte Credential-Namen pro Provider/Account. Keine Passwort-Prompts in Chat/CI.
- `.env` ist Klartext und nur für optionale Entwicklungs-Tokens, nicht Standard; existierendes `SecretService` kann bereits bestimmte Tokens Fernet-verschlüsselt in DB verwalten, sollte aber nicht automatisch für persönliche Browser-Logins genutzt werden. Für neue Nur-Lesen-Mollie-Rechnungsrechte ein separates **Advanced Access Token `invoices.read`** verwenden; nicht blind `MOLLIE_ACCESS_TOKEN` mit Zahlungsrechten wiederverwenden.
- `GitHub Secrets` sind für GitHub Actions, `Railway Variables` für auf Railway laufende Prozesse – nicht als lokaler Credentialspeicher. Kein Playwright-Railway-Deploy als Voraussetzung (Railway-Deployment aktuell instabil).
- Browserprofile unter `%LOCALAPPDATA%/XeisWorks/XW-Office/invoice_collection/profiles/<provider>/<konto-hash>/` mit Windows-Benutzer-ACL, nicht in Git/OneDrive. MSAL-Cache durch DPAPI/`msal-extensions`. Logs maskieren Tokens, Cookies, E-Mail-Inhalte, Download-URLs mit Signatur, sensitive Pfade. `.gitignore` vor Live-Login um `.env.*` (Ausnahme `!.env.example`), `playwright/.auth/`, `**/invoice_collection/profiles/`, `**/invoice_collection/storage_state*`, `**/invoice_collection/tmp/` erweitern.
- Dokumente vor Prüf-/Buchhaltungsfreigabe nie automatisch als SevDesk-Beleg ausgeben; Belegtypen/USt-Klassifikation fachlich trennen.

## 6. Release-Gates
1. UI bleibt responsive, vorhandene Ausgabenprüfung funktioniert weiterhin, pro Mandant keine Datenvermischung.
2. Mock-Mail-PDF, Mock-Mollie-Rechnung, lokaler Mock-Playwright-Download funktionieren End-to-End ohne reale Credentials.
3. Session abgelaufen -> `NEEDS_LOGIN`; sichtbarer Login/2FA und Wiederaufnahme einzelner Jobs getestet. Login kann auch auf `MANUAL_ACTION` enden, wenn Anbieter Automationsbrowser blockiert.
4. Beschädigte HTML-`.pdf`, Leerdatei, Duplikat, Downloads über Monatsgrenzen, Ausfall OneDrive-Sync, Crash/Retry, Fehler eines einzigen Providers und Kontotrennung getestet.
5. Kein stilles Überschreiben, keine Secrets im Commit oder Log. `ruff`, `pytest`, Qt-Regression und `git diff --check` laufen. Live-Portaladapter **erst nach echten Tests auf `verified` setzen**.
6. Getestete Fortschritte committen, nach Repo-Regel `AGENTS.md` in `origin/main` integrieren, keine Railway-Deploy-Abhängigkeit.

## Offizielle Referenzen
- https://playwright.dev/python/docs/auth
- https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
- https://playwright.dev/python/docs/downloads
- https://support.google.com/accounts/answer/7675428
- https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens
- https://pypi.org/project/msal-extensions/
- https://learn.microsoft.com/en-us/graph/api/attachment-get?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0
- https://docs.mollie.com/reference/list-invoices
- https://docs.mollie.com/reference/get-invoice
