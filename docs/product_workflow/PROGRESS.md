# Unified Product Workflow – Fortschritt

## T01 – Iststand und Verbraucher erfassen

Status: erledigt am 2026-09-26.

Änderungen:

- Belegte Bestandsaufnahme in `CURRENT_STATE.md` angelegt.
- Den Taskstatus in `markdowns/unifying product flow/TASK_QUEUE.yaml` auf `done` gesetzt.
- Keine Produkt-, Datenbank- oder Provider-Schreibaktion ausgeführt.

Tests:

- `python -m alembic heads` → `017_wix_reconciliation_disposition (head)`
- `python -m pytest tests/unit/test_product_hub_onboarding.py tests/unit/test_product_hub_outbox_worker.py tests/unit/test_product_hub_web_api.py -q` → 27 bestanden; eine bekannte Starlette/httpx-Deprecation-Warnung.
- `git diff --check` → ohne Befund.

Offene externe Einrichtung:

- Serverseitiger Microsoft-Graph-/OneDrive-Zugriff samt sicherer Tokenablage.
- Ausgewählte OneDrive- und Cover-Hintergrundordner sowie die privaten Book-Antiqua-/Deneane-Fonts.
- Reale Wix-/sevDesk-Leseprüfung, Editor-Link-Strategie und ein persistenter Railway-Worker.
- Amazon-SP-API-Rollen und Produktidentifikatoren erst für P07.

Commit: noch nicht erstellt.

Nächster freigegebener Task: **T02 – Migration als Vorschau planen**.
