# XeisWorks Office

PySide6 desktop application for XeisWorks music publishing business management.

## Features

- **Rechnungen:** Invoice processing, printing, fulfillment
- **Produkte:** Inventory management, Wix/sevDesk sync, print plans
- **CRM:** Customer management, deduplication, merge
- **Steuern:** UVA, payment clearing, expense auditing
- **Statistik:** Revenue analytics, charts, export
- **Layout:** PDF tools, cover creation, QR codes, watermarks
- **Provisionen:** Royalty calculations, article analysis
- **Reisekosten:** Travel cost management (embedded)
- **Marketing:** Content planning, social media (scaffold)
- **Notensatz:** Music notation tools (scaffold)

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

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
copy .env.example .env
# Edit .env with your credentials

# Run (visible console, for development/diagnosis)
python -m xw_office
```

### Windows-Desktop-Start (Alltagsbetrieb)

Fuer den taeglichen Betrieb gibt es einen fensterlosen Start ohne Konsole, mit eigenem Icon und
Startmenue-/Taskleisten-Verknuepfung. Details, Architekturentscheidung und Update-Konzept stehen
in
[`markdowns/windows_desktop_start_und_source_update_umbauskizze_2026-08-14.md`](markdowns/windows_desktop_start_und_source_update_umbauskizze_2026-08-14.md).

```bash
# Einmalig: Startmenue-Verknuepfungen erzeugen (idempotent, pro PC)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1

# Danach: Startmenue -> "XeisWorks Office" (normal) oder
#         Startmenue -> "XeisWorks Office - Debug" (sichtbare Konsole)
# "XeisWorks Office" per Rechtsklick im Startmenue an die Taskleiste anheften.
```

Der normale Start prueft automatisch und lautlos, ob ein Fast-forward-only-Update vorliegt, und
fragt per Dialog nach — nie blockierend, bei Offline/dirty Tree/falschem Branch wird lautlos
uebersprungen. Manuell/administrativ bleibt der Update-Schritt direkt aufrufbar:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_xw_office.ps1
```

Logs liegen unabhaengig vom gewaehlten Start immer unter `logs\` im Repo
(`xw_office.log`, `xw_office_crash.log`, `xw_office_bootstrap.log`, `xw_office_update.log`).

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
