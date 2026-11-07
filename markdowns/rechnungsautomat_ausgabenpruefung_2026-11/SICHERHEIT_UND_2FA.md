# Sicherheit, Einrichtung und 2-Faktor-Anmeldung
**Rechnungsautomat XW-Office – Bedienungs-/Sicherheitsleitfaden für Anfänger und Codex**

## Prinzip: Einfach anmelden, keine Zugangsdaten verteilen
**Für Playwright-Portale keine Benutzerpasswörter automatisch verlangen!** Die App soll ein sichtbares Browserfenster öffnen, in dem du dich wie gewohnt anmeldest. Danach speichert der Browser seine Sitzung in einem **eigenen, lokalen, nicht synchronisierten Profil**. Wenn die Sitzung abläuft, zeigt XW-Office exakt einen Button **„Anmeldung erneuern“**. Authenticator-, Passkey- oder SMS-Prüfung machst du selbst. Nach bestätigtem Login prüft die App die Rechnungsseite und setzt nur den unterbrochenen Abruf fort.

Der ursprüngliche Portal-Login darf NICHT mit einem Playwright-„Stealth“-Modus, CAPTCHA-Bypass, nachgespielten SSO-Requests oder privaten Endpunkten umgangen werden. Ein Anbieter kann den Automationsbrowser blockieren; dann **nicht endlos versuchen**, sondern offiziell per API, Mail oder manuellen Import arbeiten.

## 2FA je Typ
| Verfahren | Empfohlene Behandlung | Wichtige Grenzen |
|---|---|---|
| Authenticator-Push / Microsoft Authenticator / Google Prompt | Benutzer bestätigt normale Benachrichtigung auf dem Smartphone im sichtbaren Login | Keine Push-Abfanglogik; bei timeout neuer Login-Button |
| TOTP (6-stelliger Code) | Benutzer öffnet eigene Authenticator-App und tippt Code in Browser | **TOTP-Seed nicht in App/env/GitHub hinterlegen**; nicht automatisieren |
| Passkey / FIDO2 / Security Key | Anmeldung manuell im sichtbaren Browser; prüfen, ob Playwright-Context mit dem Gerät/Schlüssel funktioniert | Wenn WebAuthn scheitert, normalen Browser und manuelle Belegübernahme |
| SMS-Code / E-Mail-Code | Benutzer gibt Code selbst ein | Keine SMS-Mailbox-Scraper für MFA; keine Speicherung |
| Recovery-Code | **Nur vom Benutzer selbst** außerhalb des Programms sicher aufbewahren und bei Notfall verwenden | Nie in Logs, UI-State, GitHub, Railway, OneDrive, Screenshots |
| CAPTCHA / Anti-Bot | Mensch löst rechtmäßig angebotene Prüfung selbst, falls möglich | Nicht umgehen; bei Portalverbot Adapter deaktivieren |
| Microsoft-Graph-OAuth | **MSAL interaktiver Systembrowser + PKCE** oder Device Code; Token aus verschlüsseltem Cache | Separate Rechte `Mail.Read` und ggf. `Files.ReadWrite`, nicht Full-Admin |
| Google OAuth / Login | Wenn offiziell verfügbar OAuth in Systembrowser/Google-Mail, sonst manueller Export | Google kann programmatisch gesteuerte Browseranmeldung verweigern |

## Wo welche Daten sicher liegen
| Datenart | Richtiger Speicher |
|---|---|
| **Browser-Session** inkl. Cookies/LocalStorage | Dediziertes persistentes UserDataDir in **%LOCALAPPDATA%**, eingeschränkte Nutzer-ACL, weder Git noch OneDrive |
| Portal-Passwort, falls zwingend erforderlich | Windows Credential Manager via Python `keyring`, konto-/providerspezifisch; ansonsten gar nicht speichern |
| Graph-OAuth-Refresh-Token | Verschlüsselter MSAL-Cache (`msal-extensions` nutzt Windows DPAPI), **nicht** neue Klartext-JSON-Dateien |
| API-Token (z. B. Mollie invoices.read) | Keyring oder vorhandener `SecretService`, wenn lokale Nutzerrechte und DB-Verschlüsselung geprüft |
| Zielpfad/Anbieteraktivierung/letzter Sync | QSettings oder lokale SQLite ohne Secrets |
| PDF-Dokumente | Vom Nutzer gewählter OneDrive-Business-Zielordner, ohne Klartext-Login-Daten |
| `.env` | Nur optionales **lokales Entwicklungsfallback**, per `.gitignore` ausgeschlossen. Ist **Klartext**, kein Vault |
| GitHub Actions Secrets | **Nur CI-Jobs**, nicht automatisch für lokalen XW-Office-Start verfügbar |
| Railway Variables | **Nur Railway-Prozesse**, nicht für Windows-Browser-Sitzungen |

### Vor dem ersten Live-Login zwingend
1. `.gitignore` ergänzen um `.env.*` mit `!.env.example`, `playwright/.auth/`, `**/invoice_collection/profiles/`, `**/invoice_collection/storage_state*`, `**/invoice_collection/tmp/`. Vorhandene `.env`-Regel erhalten.
2. Browserprofile nach `%LOCALAPPDATA%/XeisWorks/XW-Office/invoice_collection/profiles/<provider>/<account-hash>/` verlagern; App legt nur Nutzerzugriff fest, schützt die Daten vor beiläufigem Commit, behandelt sie als Account-Credentials.
3. Token-/Cookie-/Passwort-Redaction und CI-/lokalen Secret-Scan nachweisen; Tests kontrollieren, dass im Git-Status keine Sitzung oder ein `.env` auftaucht.
4. Bereits vorhandene Klartext-MSAl-Caches im Repository-`state` **nicht einfach in neue Featuretests kopieren**; ggf. gesondert sicher migrieren und nach erfolgreicher Neuautorisierung sicher bereinigen. Bestehende Mail-Funktionen dürfen dabei nicht ausfallen.

## Für dich: Einrichtung ohne Konsole
**OneDrive:** In XW-Office > Ausgabenprüfung > „Rechnungen abrufen“ > „Ordner wählen“ den gewünschten synchronisierten OneDrive-for-Business-Ordner anklicken und bestätigen. Wenn Windows meldet, dass OneDrive nicht angemeldet/synchronisiert ist, diese Anmeldung regulär in der OneDrive-App durchführen. Ein lokal gespeichertes PDF ist zunächst **„Synchronisation ausstehend“**.

**Microsoft-Mail:** Im gleichen Dialog auf „Postfach verbinden“ klicken; die bestehende Microsoft-Anmeldung über Systembrowser (empfohlen) oder einen verständlich dargestellten Device-Code öffnen. Die App fragt nur die minimal erforderlichen Rechte an. Bei geteiltem Postfach dessen berechtigten Account verwenden. Bei erfolgreicher Authentifizierung die echten Rechnungs-PDF-Anhänge lesen; bloße Benachrichtigungsmails mit Link sind noch keine PDF-Rechnungen.

**Mollie:** Entweder PDF-Dateianhänge im Mollie-Dashboard für Rechnungs-E-Mails aktivieren oder – wenn API gebraucht – unter „Developers/Entwickler > API keys“ einen **Advanced Access Token nur mit `invoices.read`** erstellen, im geschützten XW-Office-Dialog einfügen und dort testen. Der bestehende Zahlungs-Schlüssel hat andere Berechtigungen, nicht ungeprüft wiederverwenden. Quelle: https://help.mollie.com/hc/de/articles/360010774314-Was-ist-ein-Advanced-Access-Token sowie https://docs.mollie.com/reference/list-invoices.

**Stripe/GitHub/Railway/andere Browserportale:** Einmal im sichtbaren Portalbrowser anmelden und 2FA bestätigen; danach „Anmeldung testen“, dann „Rechnungen abrufen“. Wenn „Anmeldung nötig“ erscheint: genau auf „Anmeldung erneuern“ klicken, nicht mehrfach Login-Daten eingeben. Dokumenttypen (eigene Gebührenrechnung vs Kundenrechnung) explizit prüfen.

**Google:** Login über automatisierten Browser kann durch Google abgelehnt werden. Offiziellen E-Mail-/Export-/Google-Payments-Weg bevorzugen; manueller Belegimport ist ein korrekter Fallback und wird in der UI als solcher angezeigt. Quelle: https://support.google.com/accounts/answer/7675428.

## Was Codex stoppen darf
Nur eine tatsächliche Nutzerhandlung: Browser-Login/2FA/Passkey, Ordnerwahl, Zustimmung zu Microsoft-Berechtigung, erforderlichen Token im lokalen sicheren Einstellungsdialog einfügen. **Niemals** Passwörter, API-Keys, OTPs oder Recovery-Codes im Chat verlangen. Nach „erledigt“ ohne neues „go on“ weiterarbeiten.

## Technische Referenzen
- Playwright Sessiondaten sind hochsensibel: https://playwright.dev/python/docs/auth
- Persistenter Context und nur eine Browserinstanz pro UserDataDir: https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
- Microsoft PublicClientApplication: https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens
- Geschützter Cache/DPAPI: https://pypi.org/project/msal-extensions/
