# XeisWorks Office

PySide6 desktop application for XeisWorks music publishing business management.

## Features

- **Rechnungen:** Invoice processing, printing, fulfillment
- **Produkte:** Inventory management, Wix/sevDesk sync, print plans
- **Druckcenter:** Separater Desktop-Start fuer Produktdruck ohne Bestellung; eigene Druckartikel
  ohne SKU und ohne externe Synchronisation
- **CRM:** Customer management, deduplication, merge
- **Steuern:** UVA, payment clearing, expense auditing
- **Statistik:** Revenue analytics, charts, export
- **Layout:** PDF tools, cover creation, QR codes, watermarks
- **Provisionen:** Royalty calculations, article analysis
- **Reisekosten:** Travel cost management (embedded)
- **Marketing:** Content planning, social media (scaffold)
- **Notensatz:** Music notation tools (scaffold)

### Ausgabenpruefung

Fuer XeisWorks und WuedaraMusi sind Kontobewegungen und Belegpruefung in einer gemeinsamen
Ansicht integriert. Im Bereich **XeisWorks** bietet der Kategoriefilter alle konfigurierten
Kategorien sowie **Ohne Kategorie**.
**Nur fehlende Belege anzeigen** zeigt ausschliesslich gepruefte Kontobewegungen mit
Lieferantenportal (Website-Icon), aber ohne verknuepften sevDesk-Beleg; wie in der bisherigen
Belegansicht werden dabei auch Eingaenge beruecksichtigt. Ohne diesen Filter bleiben die
ausgehenden Zahlungen sichtbar. **Nur offene Zuordnungen anzeigen** blendet bereits
kategorisierte Kontobewegungen in XeisWorks aus und ist mit beiden anderen Filtern kombinierbar.
Rechts neben den Checkboxen steht die Gesamtzahl der ausgehenden Zahlungen im Zeitraum.
Unvollstaendige Belegscans werden im Status ausgewiesen.

Im Bereich **WuedaraMusi** gibt es keine Kategorie-Spalten, keinen Kategoriefilter und
keine Checkbox fuer offene Zuordnungen. Auch die Kategorie-Einstellungen und die
Kategorieauswahl beim Erfassen einer zusaetzlichen Ausgabe entfallen dort.
Vorhandene Kategorien werden nicht geloescht; die Ausgaben-Bridge erhaelt fuer neue
WuedaraMusi-Ausgaben intern die feste WM-Zuordnung, ohne Auswahl durch den Benutzer.
XeisWorks behaelt seine Kategorien und Filter beim Mandantenwechsel.

Unter **WuedaraMusi > Zusaetzliche Ausgaben** erscheinen neben den dort erfassten Ausgaben
auch die in XeisWorks mit **WM** kategorisierten ausgehenden Kontobewegungen und manuellen
Ausgaben des gewaehlten WuedaraMusi-Zeitraums. Die Spalte **Herkunft** unterscheidet
XeisWorks-Konto, XeisWorks-manuell und WuedaraMusi-manuell. Die Darstellung liest die
Originaldaten, ohne neue Ausgaben oder Kopien in einem anderen Mandanten anzulegen.
Die Bankausgaben stammen aus dem gemeinsamen PostgreSQL-Cache, manuelle Ausgaben aus
der XW-Flow-Bridge. Bankausgaben bleiben auch ohne konfigurierte manuelle Bridge sichtbar.
Ein anderer Zeitraum oder eine geaenderte WM-Zuordnung wird beim naechsten Laden/Cache-Abgleich
beruecksichtigt. Aenderungen an den Kategorien erfolgen ausschliesslich in XeisWorks;
sevDesk-Links, Lieferantenportale und manuelle Anhaenge oeffnen weiterhin die Originalbelege.
Ausgaben werden in der zusaetzlichen Tabelle als positive Ausgabenbetraege dargestellt.

Rechtsbuendig in derselben Zeile wie Filter und Checkboxen stehen drei rahmenlose Aktionen:
**Plus** fuer eine zusaetzliche
Ausgabe, **Aktualisieren** fuer Kontobewegungen, Belegverknuepfungen und zusaetzliche Ausgaben sowie das
**Zahnrad** fuer Lieferantenportale und Zweckbereinigung des aktuellen Mandanten sowie
in XeisWorks fuer Kategorien und Zuordnungsregeln. **Neu laden** und das Aktualisierungsicon stossen dieselbe
inkrementelle Pruefung an; ein separater Vollscan-Textbutton ist nicht mehr vorhanden.
Ein Doppelklick auf **Zweck / Referenz** oeffnet die empfaengerbezogene Zweckbereinigung.
Die Felder im Dialog passen ihre Breite an vorhandenen und eingegebenen Text an;
die verfuegbare Bildschirmbreite begrenzt die Vergroesserung.
Die Tabelle fuer zusaetzliche Ausgaben zeigt maximal zwei Zeilen; weitere Eintraege sind
per Scrollbar erreichbar. Der restliche Platz gehoert der Haupttabelle.

Beim Oeffnen sowie nach einem Mandanten- oder Zeitraumwechsel werden zuerst die gespeicherten
Kontobewegungen und Belegverknuepfungen angezeigt. Danach wird im Hintergrund synchronisiert,
ohne die sichtbare Tabelle zu leeren. Solange die Ansicht sichtbar ist, wird der gemeinsame
Cache jede Minute erneut gelesen. Erfolgreich synchronisierte Zeitraeume gelten fuenf Minuten
als frisch; manuelles Aktualisieren umgeht diese Frischefrist.

Snapshots, Verknuepfungen, Beleg-Fingerprints und Frischezeitpunkte liegen in PostgreSQL und
sind damit auf allen PCs mit derselben Datenbank verfuegbar, getrennt nach Mandant.
Die vorhandene PostgreSQL-Advisory-Sperre serialisiert Synchronisierungen pro Mandant,
auch bei ueberlappenden Zeitraeumen. Wartende PCs pruefen nach Freigabe erneut die Frische;
ein inzwischen abgeschlossener identischer Scan wird nicht wiederholt. Fehler oder Teilscans
setzen keinen neuen Frischezeitpunkt; vorhandene Daten bleiben bei Fehlern sichtbar.

Der Abgleich liest weiterhin die sevDesk-Beleglisten, da deren Datumsfilter bisher nicht
zuverlaessig waren. Nur neue oder geaenderte relevante Belege benoetigen anschliessend
Einzelabfragen ihrer Bankverknuepfungen. Bei neu importierten Bankbewegungen werden auch
bereits bekannte relevante Belege erneut zugeordnet. Es handelt sich um einen gemeinsamen
Datenbank-Cache, nicht um einen lokalen Offline-Cache.

## Content Studio Web (Phase 1)

The repository also contains the separately deployable web foundation for the future mobile
Content Studio. It does not replace the PySide6 desktop application or its printing workflows.

```bash
# Configure at least the temporary Phase-1 API protection
set XW_CONTENT_BOOTSTRAP_TOKEN=replace-with-a-long-random-value

# Start on http://127.0.0.1:8000
python -m xw_office.web
```

Public routes:

- `/` – data-free landing page
- `/health` – Railway health check

The versioned `/api/v1/content/*` routes require the bootstrap bearer token. This token is an
interim deployment safeguard, not the later user login. Railway deployment settings are in
`railway.toml`; `requirements-web.txt` deliberately keeps desktop and printing packages out of
the server image, and `Dockerfile.web` makes that image reproducible without desktop imports.
The recommended custom domain and phased roadmap are documented in
[`markdowns/XeisWorks_Content_Studio_Zielarchitektur_und_Umbauplan_2026-07-20.md`](markdowns/XeisWorks_Content_Studio_Zielarchitektur_und_Umbauplan_2026-07-20.md).

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/XeisWorks/XW-Office.git
cd XW-Office

# Create the repository-local virtual environment (Windows)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
copy .env.example .env
# Edit .env with your credentials

# Run (visible console, for development/diagnosis)
python -m xw_office
```

### Verbindliche Python-Umgebung

Die Desktop-Anwendung und ihre Tests laufen ausnahmslos mit der repository-lokalen
`.venv`. Dadurch werden `PySide6`, `msal` und die übrigen Desktop-Abhängigkeiten nicht
mit einer globalen Python-Installation vermischt. Falls die Umgebung noch nicht existiert:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Alternativ kann die venv ohne Aktivierung direkt verwendet werden:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Qt-UI-Tests ohne sichtbare Fenster (z. B. in einer automatisierten Session) laufen
mit dem Offscreen-Backend ebenfalls aus derselben `.venv`:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest tests/ui -q
```

Für Eingabeaufforderung (`cmd.exe`) lautet die Aktivierung
`.venv\Scripts\activate.bat`. Die Startskripte `run_xw_office.cmd` und
`run_xw_office_debug.cmd` wählen `.venv\Scripts\python.exe` automatisch, sofern die
Umgebung vorhanden ist. `requirements-web.txt` ist ausschließlich für das schlanke
Web-/Railway-Image gedacht und installiert keine Desktop-Abhängigkeiten.

### Empfohlene VS-Code-Erweiterungen

Die Workspace-Empfehlungen stehen in [`.vscode/extensions.json`](.vscode/extensions.json).
Die Erweiterungen sind Entwicklungswerkzeuge, keine Laufzeitabhaengigkeiten der App,
und muessen auf jedem Entwicklungs-PC bzw. im verwendeten VS-Code-Profil installiert sein.

| Erweiterung | Extension-ID | Nutzen |
|---|---|---|
| YAML (Red Hat) | `redhat.vscode-yaml` | YAML-Validierung, Autovervollstaendigung und Schema-Unterstuetzung fuer Konfigurationen. |
| GitLens (GitKraken) | `eamodio.gitlens` | Git-Blame und Commit-/Dateihistorie zur Nachverfolgung von Codeaenderungen. |

```powershell
code --install-extension redhat.vscode-yaml
code --install-extension eamodio.gitlens

# Installierte Erweiterungen und Versionen pruefen
code --list-extensions --show-versions
```

GitLens ist ein Werkzeug zur Historienanalyse; die Repository-Regeln bleiben unveraendert:
`main` ist der gemeinsame Code-Stand, Updates erfolgen per Fast-forward und ohne Force-Push.

### Windows-Desktop-Start (Alltagsbetrieb)

Fuer den taeglichen Betrieb gibt es einen fensterlosen Start ohne Konsole, mit eigenem Icon und
Startmenue-/Taskleisten-Verknuepfung. Details, Architekturentscheidung und Update-Konzept stehen
in
[`markdowns/windows_desktop_start_und_source_update_umbauskizze_2026-08-14.md`](markdowns/windows_desktop_start_und_source_update_umbauskizze_2026-08-14.md).

```bash
# Einmalig: Startmenue-Verknuepfungen erzeugen (idempotent, pro PC)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1 -IncludeDesktopShortcut

# Danach: Startmenue -> "XeisWorks Office" (normal) oder
#         Startmenue -> "XeisWorks Office - Debug" (sichtbare Konsole)
# "XeisWorks Office" per Rechtsklick im Startmenue an die Taskleiste anheften.
# Das Skript aktualisiert bei erneutem Ausfuehren auch Desktop- und vorhandene
# Taskleisten-Verknuepfungen samt Icon und Windows-App-Identitaet.
# Alte Debug-Anheftungen werden auf den fensterlosen Start umgestellt.
# Der Debug-Start bleibt mit eigener Taskleisten-Identitaet im Startmenue verfuegbar.
```

Der normale Start prueft automatisch und lautlos, ob ein Fast-forward-only-Update vorliegt, und
fragt per Dialog nach — nie blockierend, bei Offline/dirty Tree/falschem Branch wird lautlos
uebersprungen. Manuell/administrativ bleibt der Update-Schritt direkt aufrufbar:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_xw_office.ps1
```

Logs liegen unabhaengig vom gewaehlten Start immer unter `logs\` im Repo
(`xw_office.log`, `xw_office_crash.log`, `xw_office_bootstrap.log`, `xw_office_update.log`).

## Eigenstaendiges Druckcenter

```powershell
# Einmalig auf der bestehenden Office-Datenbank: additive Migration
.venv\Scripts\python.exe -m alembic upgrade head

# Einmalig: eingeschraenktes Druckcenter-Konto erzeugen (URL nur lokal in .env)
.venv\Scripts\python.exe scripts\provision_print_center_access.py --apply

# Nur Druckcenter-Verknuepfungen im Startmenue und auf dem Desktop erzeugen
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1 -PrintCenterOnly -IncludeDesktopShortcut

# Alternativ mit Diagnosekonsole
.venv\Scripts\python.exe -m xw_office.print_center
```

Das Druckcenter startet ohne Office-Navigation, Bestandsbuchung oder Wix/sevDesk-Abgleich.
Es nutzt dieselbe `.env`/`DATABASE_URL`-Verbindung und dieselben Office-Druckprofile aus der
Konfiguration. Offizielle Produkte aus dem Office-Katalog und Product Hub sind readonly;
PDF-/Profilzuordnungen werden nur dort gepflegt. Titelbezogene Druckzuordnungen erscheinen als
eigene Auswahlzeilen. Bei aktivem Hub-Lesemodus haben Hub-Zuordnungen fuer die SKU Vorrang,
sonst die bestehenden Office-Zuordnungen.

Eigene Artikel werden ausschliesslich in `print_center.article` gespeichert, mit technischer
UUID, aber ohne SKU, Fremdschluessel zum Office-Katalog oder Sync-Outbox. Name, PDF-Pfad,
Notiz und mehrteiliger Druckplan sind im Druckcenter bearbeitbar. Gleichzeitige Aenderungen
auf anderen PCs werden durch Versionspruefung erkannt. Favoriten sind lokal pro Windows-Benutzer.
Die separate SQLAlchemy-Metadatenbasis wird nicht von den Office-Produkten aufgelistet.
Die Migration veraendert keine offiziellen Produktdaten.

Favoriten werden direkt ueber den Stern in der Tabelle umgeschaltet; die PDF-Spalte zeigt
nur den Dateinamen. Jede Zeile hat Aktionen fuer PDF-Oeffnen, Druckpfad/Einstellungen
und Anzahl + Drucken. Der Detaildialog zeigt den vollstaendigen Pfad und die Profilwerte
readonly; bei eigenen Artikeln fuehrt eine Bearbeiten-Aktion zur editierbaren Zuordnung.
Desktop, Fenster und Taskleiste verwenden das eigene Drucker-Icon.

Der offizielle Katalog wird lokal im Windows-Benutzer-Cache zwischengespeichert und
beim naechsten Start sofort angezeigt (zunaechst noch ungeprueft). Im Hintergrund und
danach alle 60 Sekunden wird auf Railway ein kleiner Inhaltsfingerprint geprueft.
Unveraenderte Daten werden nicht erneut vollstaendig uebertragen oder in der UI aufgebaut;
Aenderungen und Loeschungen an Office-Katalog, Hub-Produkten, Varianten, PDFs oder Druckregeln
fuehren zum Neuladen. Lokale PDF-Pfadaufloesungen werden spaetestens nach fuenf Minuten
erneuert. "Neu laden" erzwingt dies sofort. Eigene Artikel werden bei jeder Pruefung neu gelesen.
Tabwechsel, Suche und Favoriten arbeiten ohne Datenbankabfrage auf dem geladenen Katalog.
Zeilen-Buttons werden nur fuer den sichtbaren Tabellenausschnitt erzeugt; Mengen bleiben
beim Scrollen erhalten.

Vor jedem offiziellen Druck wird der Fingerprint nochmals auf Railway geprueft.
Ein veralteter Cache kann somit weder geaenderte Druckeinstellungen umgehen noch einen
Druck bei fehlender Datenbankverbindung freigeben. Verbindungsfehler werden sichtbar gemeldet;
eine vorhandene Cache-Anzeige bleibt lesbar, ist aber keine bestaetigte Druckfreigabe.

Offizielle Lesevorgaenge laufen auf PostgreSQL in einer readonly-Transaktion; eigene
Schreibvorgaenge sind auf das separate Schema beschraenkt. Die Provisionierung erzeugt
zusaetzlich den eingeschraenkten DB-Login `xw_print_center`: nur SELECT auf den benoetigten
Office-Tabellen, SELECT/INSERT/UPDATE/DELETE auf eigenen Artikeln. Die geheime URL wird
ausschliesslich in der lokalen `.env` unter `XW_PRINT_CENTER_DATABASE_URL` gespeichert,
nicht ins Repo oder in Logs. Auf weiteren PCs diese URL sicher in deren `.env` hinterlegen.
Ein bereits existierendes Konto wird nicht automatisch rotiert. Ohne diese optionale URL
nutzt das Druckcenter das vorhandene Office-Konto; die readonly-Transaktion bleibt aktiv,
aber dann ist die Trennung keine eigenstaendige Datenbank-Berechtigungsgrenze.

PDF-Dateien bleiben auf OneDrive/Netzwerk/lokal und muessen auf dem Druck-PC erreichbar sein.
Zum Druck sind ausschliesslich native PDF-XChange-Profile erlaubt; kein Raster-/Acrobat-Fallback.
Eine Erfolgsmeldung erscheint erst nach Windows-Spooler-Bestaetigung aller Druckschritte.
Bei Teilausfaellen bitte die bereits gedruckten Seiten vor einer Wiederholung pruefen.
Ohne Railway-Verbindung werden Fehler sichtbar gemeldet, nicht durch einen lokalen Schreibcache
oder einen vermeintlich erfolgreichen Druck ersetzt.

## Roadmap / Copilot

- **[docs/copilot_migration_plan.md](docs/copilot_migration_plan.md)** — Phasenplan, DoD und kopierfertige Copilot-Prompts für die nächsten Umbauten.

## Architecture

- **UI Framework:** PySide6 + qt-material
- **Database:** PostgreSQL on Railway
- **Printing:** QPrinter fuer Rechnungen/Labels; nativer PDF-XChange-Vektordruck fuer Noten/Produkte mit Windows-Spooler-Bestaetigung (kein automatischer Acrobat-/Raster-Fallback)
- **Config:** YAML defaults + .env secrets + DB settings
- **Update:** fast-forward-only, checked silently before the normal desktop start with a confirm dialog (`scripts\update_xw_office.ps1`, invoked automatically or manually)

## Database (PostgreSQL / Alembic)

With `DATABASE_URL` and optional `FERNET_MASTER_KEY` set in `.env` (see [.env.example](.env.example)):

```bash
alembic upgrade head
```

Initial schema covers registry, key-value settings, and encrypted API secrets. Apply migrations before relying on DB-backed features in production.

## Performance notes

- Network and heavy CPU work run off the UI thread via workers (see `xw_office.core.worker`).
- CRM duplicate detection is pairwise O(n²); intended for modest contact lists until a batched strategy is added.

## Performance SLOs

- UI response after click: first visible feedback in under 200 ms.
- Module switch: target under 500 ms to first painted content on reference hardware.
- Network actions: always in workers, never blocking the UI thread.
- sevDesk API calls: timeout defaults to 30 s with retry policy for 429/5xx.
- START preflight: target under 2 s for common queue sizes (< 100 invoice rows).

## Development

### Verbindliche Multi-PC-Branch-Regel

`origin/main` ist der einzige gemeinsame und dauerhafte Code-Stand fuer alle PCs. Jeder Clone
soll auf `main` stehen und vor der Arbeit per Fast-Forward aktualisiert werden:

```bash
git switch main
git pull --ff-only origin main
```

Arbeitsbranches (einschliesslich `agent/*`) sind nur temporaer. Fertige, getestete Aenderungen
werden in `main` integriert und zu `origin/main` gepusht; kein PC soll dauerhaft von einem
Arbeitsbranch betrieben oder synchronisiert werden. Weitere Details stehen in
[`docs/multi_pc_betriebsleitfaden.md`](docs/multi_pc_betriebsleitfaden.md).

```bash
# Run tests
pytest tests/

# Type checking
mypy src/

# Linting
ruff check src/
```
