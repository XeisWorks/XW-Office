# XeisWorks Studio — Codex Agent Instructions

## Project Overview
PySide6 desktop application for XeisWorks music publishing business.
Manages invoices, inventory, printing, CRM, tax declarations, and more.
Multi-PC sync via PostgreSQL on Railway.

## Architecture
- **UI:** PySide6 with sidebar navigation + card-based content
- **Services:** Business logic layer with DI container
- **Data:** PostgreSQL (Railway) for all operational data
- **Config:** YAML + .env + DB settings
- **Printing:** Rechnungen/Labels via QPrinter; qualitaetskritische Noten-/Produkt-PDFs nativ und vektorbasiert via PDF-XChange. Erfolg erst nach Windows-Spooler-Bestaetigung; kein automatischer Acrobat- oder Raster-Fallback.

## Code Conventions
- **Language:** English code (variables, classes, comments), German UI labels
- **Type hints:** Required on all functions (mypy --strict)
- **Imports:** Absolute from `xw_studio.` package
- **Naming:** snake_case functions/variables, PascalCase classes
- **Max file length:** ~800 lines. Split if larger.
- **No print():** Use `logging` module
- **No bare except:** Catch specific exceptions
- **No raw threading:** Use `BackgroundWorker` from `xw_studio.core.worker`

## Key Patterns
- Services receive dependencies via constructor (DI)
- UI widgets receive services from container, never create them
- Background tasks: `BackgroundWorker(fn).signals.result.connect(handler)`
- Cross-module communication: `AppSignals` from `xw_studio.core.signals`
- All API responses: Pydantic models (not raw dicts)
- Config access: `container.config.sevdesk.api_token`

## Testing
- `pytest` + `pytest-qt`
- Run: `pytest tests/`
- Fixtures in `tests/conftest.py`

## File Structure
- `src/xw_studio/ui/modules/{name}/view.py` — Module main view
- `src/xw_studio/services/{name}/` — Service package
- `resources/themes/` — QSS stylesheets
- `config/` — YAML configuration
