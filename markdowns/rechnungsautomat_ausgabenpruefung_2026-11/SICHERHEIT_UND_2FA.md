# Sicherheit, Einrichtung und 2-Faktor-Anmeldung

**Rechnungsautomat XW-Office – verbindlicher Bedienungs- und Sicherheitsleitfaden**

## 1. Schutzgüter und Bedrohungen

Zu schützen sind nicht nur Passwörter und API-Tokens, sondern auch Browsercookies,
OAuth-Refresh-Tokens, signierte Download-URLs, Rechnungsinhalte, Konto-/Mandantenzuordnung und
lokale Pfade. Ein gestohlenes Browserprofil kann eine angemeldete Sitzung übernehmen.

Die Implementierung berücksichtigt mindestens:

- versehentlichen Commit oder Sync von Secrets, Profilen, PDFs und Token-Caches;
- Mandantenvermischung oder Ablage in einem falschen Zielordner;
- manipulierte E-Mail-Anhänge, HTML mit `.pdf`-Endung und übergroße/defekte PDFs;
- Phishinglinks, offene Redirects, SSRF und Download von nicht erlaubten Hosts;
- Überschreiben vorhandener Dokumente und falsche Cloud-Erfolgsmeldungen;
- Tokens, Cookies, Mailinhalte oder signierte URLs in Logs/Exceptions;
- endlose Login-/Retry-Schleifen, Account-Sperren und Umgehung von Bot-/MFA-Schutz.

## 2. Grundprinzip: Benutzer meldet sich regulär an

Für Browserportale verlangt XW-Office standardmäßig kein Passwort. Die App öffnet ein
sichtbares, dediziertes Browserprofil; der Benutzer meldet sich wie gewohnt an und bestätigt
2FA selbst. Läuft die Sitzung ab, zeigt nur die betroffene Route **„Anmeldung erneuern“**.
Nach erfolgreichem Protected-Page-Probe wird nur dieser Job fortgesetzt.

Verboten sind Playwright-„Stealth“, CAPTCHA-Bypass, automatisierte TOTP-Erzeugung,
nachgespielte private SSO-Requests, selbst gebaute Cookie-Header und WebAuthn-Umgehungen. Wenn
ein Anbieter Automationsbrowser untersagt oder blockiert, endet die Route in
`POLICY_BLOCKED`/`MANUAL_ACTION`; E-Mail, offizielle API oder manueller Import bleiben valide
Alternativen.

## 3. Behandlung der Anmeldearten

| Verfahren | Behandlung | Grenze |
|---|---|---|
| Authenticator-Push / Google Prompt | Benutzer bestätigt am Telefon während des sichtbaren Logins | kein Abfangen/Bestätigen durch die App |
| TOTP-Code | Benutzer tippt den Code direkt in den sichtbaren Browser | Seed nie speichern oder automatisieren |
| Passkey / FIDO2 / Security Key | manueller sichtbarer Login; bei Inkompatibilität normaler Browser plus manueller Import | kein virtuelles WebAuthn-Manöver |
| SMS-/E-Mail-Code | Benutzer gibt den Code selbst ein | keine MFA-Mailbox-/SMS-Scraper |
| Recovery-Code | nur durch den Benutzer außerhalb der App verwalten | nie in UI-State, Logs, Git oder OneDrive |
| CAPTCHA / Anti-Bot | Benutzer darf eine regulär angebotene Prüfung selbst lösen | keine Umgehung; bei Portalverbot Route deaktivieren |
| Microsoft Graph OAuth | interaktiver Systembrowser mit PKCE oder verständlicher Device-Code in der UI | minimale getrennte Scopes, verschlüsselter Cache |
| API-Token | Eingabe ausschließlich im lokalen Secret-Dialog | nur erforderlicher Read-Scope, nie im Connection-YAML |

## 4. Speicherorte und Datentrennung

| Datenart | Speicher |
|---|---|
| Browser-Session/Cookies/LocalStorage | `%LOCALAPPDATA%/XeisWorks/XW-Office/invoice_collection/profiles/<provider>/<connection-hash>/` mit Nutzer-ACL |
| OAuth-Token-Cache | `%LOCALAPPDATA%/.../auth/`, mit Windows DPAPI über `msal-extensions` geschützt |
| API-Token/Passwort, falls erforderlich | Windows Credential Manager über `keyring` oder explizit geprüfter SecretStore |
| Connection-Konfiguration | lokale SQLite unter `%LOCALAPPDATA%`, nur `SecretRef`, nie Secretwert |
| Checkpoints/Läufe/Dokumentjournal | dieselbe lokale SQLite, ohne PDF-Inhalt und ohne vollständige Mailinhalte |
| temporäre Downloads | laufbezogener `%LOCALAPPDATA%`-Workspace, restriktiv, mit Cleanup/Quarantäne |
| fertige PDFs | ausgewählter OneDrive-Business-Zielordner |
| `.env` | optionales lokales Entwicklungsfallback; Klartext und nie Produktstandard |
| GitHub Secrets/Railway Variables | nur deren jeweilige Prozesse; kein lokaler Desktop-Credentialspeicher |

Anbieter, Konto und Mandant müssen Bestandteil der Secret-Service-ID sein, aber die sichtbare
E-Mail-Adresse darf nicht unnötig als Klartext im Service-Namen landen. Verwenden:
`xw-office/invoice-collection/<provider-id>/<opaque-connection-id>/<purpose>`.

`SecretRef` enthält nur Backend, Service-ID und Zweck. `repr`, Exceptions und Telemetrie dürfen
niemals den aufgelösten Wert enthalten. Clipboard-Nutzung für Tokens nicht automatisch
protokollieren und Eingabefeld standardmäßig maskieren.

## 5. Vor dem ersten Live-Login zwingend

1. Einen getesteten `local_app_data_dir()`-Pfadhelfer ergänzen. Browser-, OAuth-, Journal- und
   Tempdaten dürfen nicht über den bestehenden Repository-`state/`-Pfad laufen.
2. `.gitignore` mindestens um `.env.*` mit Ausnahme `!.env.example`, `playwright/.auth/`,
   `**/invoice_collection/profiles/`, `**/invoice_collection/storage_state*`,
   `**/invoice_collection/tmp/` und lokale Journale ergänzen. Ignore-Regeln sind nur die
   zweite Schutzschicht; die Primärablage liegt außerhalb des Repositories.
3. Keyring-/SecretStore-Abstraktion, Windows-ACL, Token-/Cookie-/URL-Redaction und lokalen
   Secret-Scan automatisiert testen.
4. Den Rechnungs-Graph-Login mit minimalen Scopes und verschlüsseltem Cache implementieren.
   Der bestehende Klartext-Cache darf nicht still kopiert werden.
5. Migration eines bestehenden Graph-Caches nur als bewussten, getesteten Prozess vorsehen:
   sichere Neuautorisierung bevorzugen, Altdatei nach Erfolg gezielt entfernen, bestehende
   Mailfunktionen nicht unterbrechen.
6. Provider-Host-Allowlist und Redirect-Regeln durch Tests absichern. Kein Live-Login, solange
   unbekannte Downloadhosts ungeprüft akzeptiert werden.

## 6. Sichere Dokumentannahme

- Maximalgröße und Downloadtimeout vor und während des Streams erzwingen.
- HTTP-Status, finalen Host nach Redirect, `Content-Type`, `%PDF-`-Signatur und Parsergebnis
  prüfen; Dateiendung allein zählt nicht.
- Verschlüsselte PDFs nicht still verwerfen: als `QUARANTINED` mit verständlicher Aktion
  behandeln. Kein Passwort im Chat anfordern.
- Parser in einer schmalen Schnittstelle kapseln; keine eingebetteten Links, JavaScript,
  Anhänge oder Launch-Actions ausführen.
- Originaldateinamen nur als untrusted Input behandeln, Pfadbestandteile/Unicode normalisieren,
  reservierte Windows-Namen und Traversal verhindern.
- Download zunächst in isolierten Workspace; Publikation ausschließlich über den Sink mit
  no-clobber-Semantik. Nie `os.replace` auf ein unbekanntes bestehendes Ziel anwenden.
- Bei Konflikt beide Identitäten dokumentieren, aber vorhandene Datei nicht überschreiben.
- Quarantäne liegt lokal außerhalb OneDrive, enthält nur tatsächlich erforderliche Artefakte
  und besitzt eine klare manuelle Lösch-/Prüfaktion.

## 7. Netzwerk- und Providergrenzen

- API-Basis- und Portalhosts stammen aus validiertem Manifest, nicht aus Benutzereingaben.
- Redirects nur zu HTTPS und erlaubten Hosts; kurzlebige, dokumentierte Download-CDNs werden
  separat allowgelistet. Private/Loopback/Link-local-Ziele bei Remote-Downloads ablehnen.
- Rechnungslinks aus E-Mails werden nicht automatisch aufgerufen. Ein späterer Link-Resolver
  wäre ein eigener Connector mit denselben Host- und Auth-Regeln.
- Explizite Connect-/Read-Timeouts, begrenzte Antwortgröße und begrenzte Retries verwenden.
- `Retry-After` respektieren; keine aggressiven Parallelabrufe oder Login-Wiederholungen.
- Rohantworten können Secrets oder personenbezogene Daten enthalten. Fehler auf sichere Codes
  und kurze redigierte Details abbilden.

## 8. Logging und Diagnose

Strukturierte Logs dürfen enthalten: `run_id`, opaque `connection_id`, Provider-ID, Route,
Fehlercode, Dauer, Zähler und Retry-Nummer. Nicht loggen: Token, Authorization-Header, Cookie,
OTP, vollständige E-Mail-Adresse, Mailtext/Betreff, Attachment-Inhalt, signierte URL,
Browser-Storage-State, voller lokaler Benutzerpfad.

Redaction geschieht vor dem Logger, nicht erst im Formatter. Exceptions externer Bibliotheken
werden in eigene sichere Fehlertypen übersetzt. Ein optionaler Diagnoseexport benötigt
Vorschau, explizite Zustimmung und einen Test, dass er keine Secrets/PDFs/Browserprofile
enthält.

## 9. Einrichtung für Benutzer ohne Konsole

**OneDrive:** In XW-Office > Ausgabenprüfung > Rechnungen abrufen > Ordner wählen einen
synchronisierten OneDrive-for-Business-Ordner auswählen. Eine lokal gespeicherte Datei wird
zunächst als **„Synchronisation ausstehend“** angezeigt.

**Microsoft-Mail:** Auf **„Postfach verbinden“** klicken und die angezeigte Microsoft-Anmeldung
im Systembrowser abschließen. Geteilte Postfachrechte nur aktivieren, wenn sie tatsächlich
benötigt werden. Benachrichtigungsmails ohne echten PDF-Anhang gelten nicht als Dokument.

**API-Provider:** Im Providerdialog ausschließlich einen minimal berechtigten Read-Token
hinterlegen und testen. Bestehende Zahlungs-/Admin-Tokens nicht ungeprüft wiederverwenden.

**Browserportale:** Auf **„Anmelden“** klicken, im sichtbaren Browser regulär anmelden und
2FA bestätigen. Bei **„Anmeldung nötig“** nur **„Anmeldung erneuern“** verwenden. Wenn der
Anbieter den Automationsbrowser blockiert, manuellen Import nutzen.

**Manueller Import:** Dateien nur über die Providerverbindung importieren, damit Mandant,
Dokumenttyp, Validierung, Hash und Deduplizierung erhalten bleiben.

## 10. Wann die Umsetzung auf eine Benutzerhandlung warten darf

Nur bei tatsächlich notwendiger Ordnerwahl, Entra-Zustimmung, sichtbarem Login/2FA/Passkey oder
Eingabe eines minimal berechtigten Tokens im lokalen geschützten Dialog. Niemals Passwörter,
API-Keys, OTPs oder Recovery-Codes im Chat anfordern. Je Blockade genau eine klare
Klickanweisung geben und nach „erledigt“ ohne weitere Freigabeschleife fortfahren.

## Technische Referenzen

- https://playwright.dev/python/docs/auth
- https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
- https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens
- https://pypi.org/project/msal-extensions/
