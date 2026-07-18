# XeisWorks Studio

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

## Setup

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/XeisWorks/XW-Studio.git
cd XW-Studio

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
copy .env.example .env
# Edit .env with your credentials

# Run
python -m xw_studio
```

## Roadmap / Copilot

- **[docs/copilot_migration_plan.md](docs/copilot_migration_plan.md)** — Phasenplan, DoD und kopierfertige Copilot-Prompts für die nächsten Umbauten.

## Architecture

- **UI Framework:** PySide6 + qt-material
- **Database:** PostgreSQL on Railway
- **Printing:** QPrinter + PyMuPDF at 600 DPI
- **Config:** YAML defaults + .env secrets + DB settings
- **Auto-Update:** git pull + pip install at startup

## Database (PostgreSQL / Alembic)

With `DATABASE_URL` and optional `FERNET_MASTER_KEY` set in `.env` (see [.env.example](.env.example)):

```bash
alembic upgrade head
```

Initial schema covers registry, key-value settings, and encrypted API secrets. Apply migrations before relying on DB-backed features in production.

## Performance notes

- Network and heavy CPU work run off the UI thread via workers (see `xw_studio.core.worker`).
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
