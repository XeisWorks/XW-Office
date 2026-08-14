# XW-Office Multi-PC Betriebsleitfaden

Ziel:
- Jeder Windows-PC kann reproduzierbar installiert, aktualisiert und betrieben werden.
- Betriebsdaten kommen aus PostgreSQL (Railway), Code aus GitHub.

## 1) Voraussetzungen pro PC

- Windows 10/11
- Python 3.11 oder 3.12
- Git
- Drucker lokal installiert (fuer Druck-PCs)

## 2) Erstinstallation

1. Repo klonen:
   - `git clone --recurse-submodules https://github.com/XeisWorks/XW-Office.git`
2. In Projektordner wechseln.
3. Virtuelle Umgebung erstellen:
   - `python -m venv .venv`
4. Umgebung aktivieren:
   - `.venv\\Scripts\\activate`
5. Abhaengigkeiten installieren:
   - `pip install -e ".[dev]"`
6. `.env` aus `.env.example` erstellen und lokale Werte setzen.
7. Migrationen ausfuehren:
   - `alembic upgrade head`
8. Windows-Startmenue-Verknuepfungen erzeugen (einmalig, danach idempotent erneut ausfuehrbar):
   - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1`
   - Legt im Startmenue den Ordner "XeisWorks Office" mit zwei Eintraegen an: normaler Start und
     Debug-Start. Optional zusaetzlich eine Desktop-Verknuepfung mit `-IncludeDesktopShortcut`.
     Der normale Start prueft beim Start automatisch und lautlos auf Updates (siehe Abschnitt 5),
     eine eigene Update-Verknuepfung gibt es deshalb nicht.
9. Normalen Start testen: Startmenue -> "XeisWorks Office" (kein Konsolenfenster, PySide6-Fenster
   erscheint maximiert).
10. Debug-Start testen: Startmenue -> "XeisWorks Office - Debug" (sichtbare Konsole, gleiches
    Dateilog).
11. "XeisWorks Office" im Startmenue per Rechtsklick -> "An Taskleiste anheften" anheften.

Alternativer Direktstart ohne Verknuepfung (z. B. fuer Codex/Claude Code):
- Normaler Start: `.venv\\Scripts\\pythonw.exe scripts\\xw_office_gui.pyw`
- Diagnose-Start mit sichtbarer Konsole: `run_xw_office_debug.cmd`
- Reines Modul (aequivalent zum Debug-Start, ohne Fehlerdialog-Wrapper): `python -m xw_office`

## 3) Pflichtvariablen (.env oder Secret-Store)

- `DATABASE_URL`
- `FERNET_MASTER_KEY`
- `SEVDESK_API_TOKEN`
- optional je nach Modul:
  - `WIX_API_KEY`, `WIX_SITE_ID`, `WIX_ACCOUNT_ID`
  - `CLICKUP_API_TOKEN`
  - `FON_TEILNEHMER_ID`, `FON_BENUTZER_ID`, `FON_PIN`

Hinweis:
- Tokens bevorzugt ueber Settings in die verschluesselte DB-Verwaltung pflegen.
- Keine Secrets ins Repo committen.

## 4) Betrieb auf mehreren PCs

- Betriebsdaten werden zentral in PostgreSQL synchronisiert.
- `origin/main` ist der einzige verbindliche gemeinsame Code-Stand aller PCs.
- Jeder PC wird dauerhaft auf dem lokalen Branch `main` betrieben; dessen Upstream ist
  `origin/main`.
- Temporaere Arbeitsbranches wie `agent/*` muessen nach Abschluss in `main` integriert werden
  und duerfen nicht als dauerhafter Betriebsstand eines PCs verbleiben.
- Code-Updates laufen ueber einen automatischen, lautlosen Check vor dem normalen Start (siehe
  Abschnitt 5): nur bei sauberem Arbeitsbaum, Branch `main`/Upstream `origin/main` und
  tatsaechlich vorhandenem Update erscheint eine Ja/Nein-Rueckfrage; sonst startet die App
  unveraendert weiter. Der Alltagsstart wird dadurch nie laenger als um ein kurzes
  Netzwerk-Timeout verzoegert und haengt nie zwingend von GitHub ab.

Normaler Betrieb pro PC:
- Alltagsstart ueber die Startmenue-/Taskleisten-Verknuepfung "XeisWorks Office" (fensterlos,
  `pythonw.exe`).
- Diagnose/Live-Debugging durch Entwickler, Codex oder Claude Code ueber
  "XeisWorks Office - Debug" (sichtbare Konsole, gleiches Dateilog).
- Alle Betriebsregeln (Rechnungslogs, Log-Pfade) sind unabhaengig vom gewaehlten Start identisch,
  da beide Wege in dieselbe `logs\xw_office.log` schreiben.

Empfehlung Rollenmodell:
- 1 Druck-PC: stabile Druckerzuordnung, Noten-/Rechnungsdruck.
- 1-2 Office-PCs: Rechnungen, CRM, Steuern, Produktpflege.

## 5) Update-Routine

- Normalfall: beim Start ueber "XeisWorks Office" prueft die App selbst lautlos, ob ein Update
  vorliegt, und fragt per Dialog nach ("Jetzt aktualisieren?" / "Nein"). Kein separater Schritt
  noetig.
- Vor Schichtbeginn zusaetzlich sinnvoll:
  - DB-Status in Einstellungen kurz pruefen.
  - Druckerampel pruefen (Druck-PC).
- Manuell/administrativ jederzeit direkt aufrufbar (z. B. um ohne App-Start zu aktualisieren):
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_xw_office.ps1`.
- Auf einem PC, der nie automatisch geprueft werden soll (z. B. bewusst pinned Version), vor dem
  Start `XW_OFFICE_SKIP_UPDATE_CHECK=1` setzen.

Der Update-Schritt (`scripts\update_xw_office.ps1`), automatisch wie manuell gleich:
1. Bricht ab, wenn XW-Office noch laeuft, lokale Aenderungen offen sind, der Branch nicht `main`
   ist oder der Upstream nicht `origin/main` ist. In keinem dieser Faelle wird automatisch
   gemergt, gestasht oder verworfen.
2. `git fetch origin main`, danach ausschliesslich `git pull --ff-only origin main`.
3. Installiert Abhaengigkeiten neu, wenn sich `pyproject.toml` geaendert hat.
4. Meldet geaenderte Datenbankmigrationen nur, fuehrt sie aber nicht automatisch aus (siehe unten).
5. Fuehrt einen kurzen Smoke-Preflight (Modul-Import) aus.
6. Protokolliert Alt-/Neu-Commit und Ergebnis in `logs\xw_office_update.log`.

Manuelle Aktualisierung (Fallback, z. B. wenn PowerShell-Skripte gesperrt sind):
1. App schliessen.
2. Sicherstellen, dass keine lokalen Aenderungen offen sind: `git status --short`
3. Auf den gemeinsamen Branch wechseln: `git switch main`
4. Ausschliesslich als Fast-Forward aktualisieren: `git pull --ff-only origin main`
5. `.venv\\Scripts\\python.exe -m pip install -e ".[dev]"`
6. `alembic upgrade head`
7. App neu starten.

Einrichtung bzw. Reparatur des Upstreams pro PC:
- `git branch --set-upstream-to=origin/main main`
- Kontrolle: `git status --short --branch` muss `main...origin/main` anzeigen.

Datenbankmigrationen (`alembic upgrade head`):
- Nicht unkoordiniert auf mehreren PCs gleichzeitig ausfuehren.
- Bevorzugt einmalig und bewusst von einem festgelegten Admin-/Entwicklungs-PC ausfuehren.
- Der Update-Schritt oben meldet neue Migrationsdateien nur, fuehrt sie aber nicht selbst aus.

## 6) Backup und Wiederherstellung

- Primaer-Backup: Railway PostgreSQL Snapshots/Backups.
- Sekundaer: regelmaessiger SQL-Dump.
- Wiederherstellungstest mindestens monatlich.

## 7) Logs und Diagnose (Codex/Claude Code)

Alle Logs liegen unter `<repo>\logs\`, unabhaengig davon, ob normal (fensterlos) oder per
Debug-Start gestartet wurde:

- `xw_office.log` — laufendes Anwendungslog (Rotating, Standard 8 MB x 8 Backups; ueber
  `XW_OFFICE_LOG_MAX_BYTES`/`XW_OFFICE_LOG_BACKUP_COUNT` anpassbar).
- `xw_office_bootstrap.log` — nur bei Fehlern vor dem eigentlichen App-Start (z. B. defektes
  `.venv`, Importfehler), geschrieben vom GUI-Bootstrap.
- `xw_office_crash.log` — harte Python-Abstuerze (`faulthandler`).
- `xw_office_update.log` — Ergebnis jedes Laufs von `scripts\update_xw_office.ps1`.

Log-Level fuer eine Session erhoehen: `XW_OFFICE_LOG_LEVEL=DEBUG` vor dem Start setzen (z. B. in
der Konsole vor `run_xw_office_debug.cmd`). Secrets/Tokens werden vor dem Schreiben ins Log
redigiert.

## 8) Stoerungsbehebung

- Symptom: kein Sync / keine Daten.
  - `DATABASE_URL` pruefen.
  - In Settings Verbindung testen.
- Symptom: Token-bezogene API-Fehler.
  - Secret-Eintraege in Settings pruefen.
- Symptom: Druck nicht verfuegbar.
  - Druckerampel / konfigurierte Druckernamen pruefen.

## 9) Wartungscheckliste (monatlich)

- `pytest tests/`
- `ruff check src/`
- `alembic current` gegen `head` pruefen
- Drucktest mit Rechnungs- und Noten-PDF
- Start-Preflight mit Testdaten verifizieren
