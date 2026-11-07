# Codex-Goal für XW-Office

**Diesen Auftrag erst im nächsten Umsetzungsschritt verwenden.**

```text
/goal
Implementiere im Repository XeisWorks/XW-Office auf aktuellem main den Rechnungsautomaten
unter FINANZEN > AUSGABENPRÜFUNG. Verbindliche Spezifikation:

- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/START_HERE.md
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/ARCHITEKTUR.md
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/SICHERHEIT_UND_2FA.md
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/PROVIDER_REGISTRY.yaml
- markdowns/rechnungsautomat_ausgabenpruefung_2026-11/TASK_QUEUE.yaml

Arbeite TASK_QUEUE.yaml in Abhängigkeitsreihenfolge ab. Lies vor jeder Phase AGENTS.md,
aktuellen Code und relevante Tests. Setze einen Task nur mit konkreter Test-/Prüfevidenz auf
done. Halte bestehende Ausgabenprüfung, beide Mandanten, sevDesk, XW-Flow, Graph-Mail und
Product Hub funktionsfähig.

Architektur ist verbindlich: Provider-Katalog, lokale ProviderConnection, Abrufroute,
Dokumentpipeline und DocumentSink bleiben getrennt. Connectoren entdecken/laden Kandidaten,
schreiben aber nie ins Archiv. UI, Orchestrator, Pipeline und Sinks enthalten keine
provider_id-Sonderfälle. Neue Provider werden über secretfreies Manifest, explizit registrierte
Connector-Factory und gemeinsame Contract-Tests ergänzt. Keine ausführbaren Importpfade aus
YAML laden.

Beginne nach Baseline und Sicherheitsbasis mit dem manuellen vertikalen Slice:
LOCALAPPDATA-Zustand, lokales SQLite-Journal, sichere PDF-Prüfung, tenantbezogene
SHA-256-Deduplizierung, no-clobber OneDriveLocalSink und manueller Import. Danach den
providerunabhängigen PySide6-Dialog und begrenzten Orchestrator bauen. Anschließend unabhängig:
(1) sichere Microsoft-Graph-Mailanhänge, (2) Mollie invoices.read mit Mock-API und
(3) Playwright-Engine mit lokalem Fake-Portal, sichtbarem Login und route-spezifischem Resume.

Methodenpriorität je Verbindung: verifizierte Mail-PDFs > offizielle API > Playwright >
manueller Import. Fallback nur für explizit erlaubte Fehlercodes. Keine unbewiesenen
DOM-Selektoren, Absenderregeln, Portal-URLs oder APIs erfinden. Kein CAPTCHA-/MFA-/Bot-Bypass,
kein Stealth, keine automatisierten Google-Login-Tricks. Browserprofile, OAuth-Caches,
Passwörter, Cookies, OTPs, signierte URLs, echte PDFs und Secretwerte nie committen, nach
OneDrive synchronisieren oder loggen. Neue maschinenspezifische Daten liegen unter
%LOCALAPPDATA%, nicht im Repository-state/. Secretwerte nur über SecretRef und keyring bzw.
explizit geprüften Store auflösen.

OneDrive-Syncstatus ehrlich behandeln: lokales Speichern ergibt SYNC_PENDING, niemals ohne
Remoteprüfung CLOUD_VERIFIED. Keine Datei still überschreiben. Gleiches external_id mit
anderem Hash ist CONTENT_CONFLICT. Deduplizierung ist mandanten- und zielbezogen; ein Treffer
bei xw darf wuedara nicht unterdrücken. Manueller Import nutzt dieselbe Pipeline.

Stoppe nur für eine zwingende persönliche Handlung: OneDrive-Ordnerwahl, Entra-Zustimmung,
sichtbarer Portal-Login/2FA/Passkey oder Eingabe eines minimal berechtigten Tokens im lokalen
geschützten Dialog. Dann genau eine einfache Klickanweisung geben. Niemals ein Geheimnis im
Chat erfragen; nach „erledigt“ direkt fortsetzen.

MVP bedeutet nicht, alle Registry-Provider zu automatisieren. Unverifizierte Routen bleiben
planned oder manual. Für verified sind echtes Dokument, korrekter Dokumenttyp, erfolgreicher
Download, idempotenter Wiederholungslauf, Auth-Fehlerfall und sichere Logs nachzuweisen.
Provider in kleinen unabhängigen Wellen ergänzen; ein blockiertes Portal darf andere nicht
blockieren. Keine automatische sevDesk-Buchung und keine Steuerklassifikation.

Führe pro Phase passende Contract-, Unit-, UI- und Integrationstests aus; am Ende mindestens
ruff, relevante pytest-Suites, Qt-Regression, YAML-Validierung, git diff --check und
Secret-Scan. Committe sinnvolle getestete Schritte und pushe den fertigen integrierten Stand
gemäß AGENTS.md auf origin/main. Kein Force-Push; Working Tree am Ende sauber.

Abschlussbericht: getestete und live verifizierte Routen getrennt auflisten, manuelle/geplante
Provider, externe Auth-Schritte, OneDrive-Status, bekannte Grenzen und Testevidenz nennen. Nie
eine Mock- oder ungeprüfte Livefunktion als fertig ausgeben.
```

## Definition von „fertig“ für den MVP

- Der manuelle vertikale Slice und die drei technischen Routen Mail, Mollie-API und
  Playwright-Fake-Portal sind lokal reproduzierbar getestet.
- Dialog und Orchestrator sind providerunabhängig; ein Fixture-Provider benötigt keine
  UI-/Orchestratoränderung.
- Session-/Tokenablauf kann gezielt wiederaufgenommen werden, ohne andere Jobs zu stoppen.
- Keine sensitiven Daten in Git, OneDrive-Sitzungsordnern, Logs oder CI-Artefakten.
- Live-Reifegrade bleiben ehrlich; weitere Provider sind unabhängiger Folgeumfang.
