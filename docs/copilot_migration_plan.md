# XW-Office — Copilot-fähiger weiterer Umbauplan

Ziel: Weiterarbeit mit GitHub Copilot **ohne Kontextbrüche**. Dieses Dokument ist die **Single Source of Truth** für Reihenfolge, Konventionen und Abnahmekriterien.

**Repo:** [github.com/XeisWorks/XW-Office](https://github.com/XeisWorks/XW-Office)  
**Alt-Repo (nur Referenz):** `XeisWorks/sevDesk` — Verhalten nachvollziehen, **keine** Blindkopien.

---

## 0) Copilot-Arbeitsregeln (verbindlich)

Vor jeder Session:

1. [CLAUDE.md](../CLAUDE.md) lesen und einhalten: Englisch im Code, Deutsch in der UI, `logging` statt `print()`, keine nackten `except`, `BackgroundWorker` statt freiem Threading für blockierende Arbeit.
2. **Kleinteilig** arbeiten: ein PR/Thema = eine logische Einheit (z. B. nur sevDesk-InvoiceClient).
3. **Keine** Secrets committen; nur [.env.example](../.env.example) ergänzen.
4. Nach Änderungen: `pytest tests/` grün; UI: `python -m xw_office` startbar.
5. Neue Fachlogik unter `xw_office.services.*`, UI unter `xw_office.ui.modules.*`; DI in [src/xw_office/bootstrap.py](../src/xw_office/bootstrap.py) bzw. `register_default_services`.

---

## 1) Architektur-Vertrag

- **UI** importiert keine Roh-`httpx`-Clients; nur **Services** und DTOs.
- **Netzwerk** nie im UI-Thread: [worker.py](../src/xw_office/core/worker.py) oder `QThreadPool`.
- **Navigation:** [signals.py](../src/xw_office/core/signals.py) `navigate_to_module` — [main_window.py](../src/xw_office/ui/main_window.py) bleibt zentral.
- **Konfiguration:** [config.py](../src/xw_office/core/config.py) + `config/default.yaml` + `.env`.

---

## 2) Phase 1 — Core Business (Priorität)

| ID  | Task                                 | Orte                                                                 | Definition of Done |
| --- | ------------------------------------ | -------------------------------------------------------------------- | ------------------ |
| 1.1 | HTTP-Basis                           | [services/http_client.py](../src/xw_office/services/http_client.py)  | Timeout, Token aus `AppConfig`, `SevdeskApiError` |
| 1.2 | sevDesk Invoice-Client               | [services/sevdesk/invoice_client.py](../src/xw_office/services/sevdesk/invoice_client.py) | Liste + Pydantic, Fehler-Mapping |
| 1.3 | sevDesk Contact-Client               | [services/sevdesk/contact_client.py](../src/xw_office/services/sevdesk/contact_client.py) | Minimal |
| 1.4 | InvoiceProcessing Facade             | [services/invoice_processing/service.py](../src/xw_office/services/invoice_processing/service.py) | Keine UI-Logik |
| 1.5 | Rechnungen View                      | [ui/modules/rechnungen/view.py](../src/xw_office/ui/modules/rechnungen/view.py) | Worker, Tabelle, DE-Labels, Statusfilter, „Weitere laden“, Detailpanel |
| 1.6 | pdf_renderer                         | [services/printing/pdf_renderer.py](../src/xw_office/services/printing/pdf_renderer.py) | 600 DPI Musik, 300 Rechnung, Druckdialog-Seitenbereich |
| 1.7 | Drucker-Ampel + Druck sperren        | [main_window.py](../src/xw_office/ui/main_window.py), `printing.configured_printer_names` | Rot = Druck deaktiviert |
| 1.8 | sevDesk HTTP-Retries + Fehlertexte    | [services/http_client.py](../src/xw_office/services/http_client.py), `sevdesk.http_max_retries` in config | 429/5xx mit Backoff, deutschsprachige Hinweise |

**Abhängigkeit:** 1.1 → 1.2/1.3 → 1.4 → 1.5; 1.6 parallel; 1.7 nach 1.5 oder parallel.

---

## 3) Phase 2 — Finance & Analytics

- FinanzOnline/UVA: Pakete unter [services/finanzonline/](../src/xw_office/services/finanzonline/) (mehrere Dateien, kein Monolith).
- UI: [ui/modules/taxes/view.py](../src/xw_office/ui/modules/taxes/view.py) — Tabs UVA | Clearing | Ausgaben; Inhalte schrittweise.
- **DoD:** Kein blockierendes Netz im UI-Thread; SOAP-Tests mit Mocks.

---

## 4) Phase 3 — CRM, Layout, Kalkulation

- CRM: Matching + Merge-Wizard — Service zuerst.
- Layout: Werkzeugkarten → Panels.
- **DoD:** Pydantic für externe Payloads, DE-UI.

---

## 5) Phase 4 — Integration

- **Reisekosten:** Submodule `reisekosten/` + Bridge: [travel_costs/view.py](../src/xw_office/ui/modules/travel_costs/view.py).
- Marketing / Notensatz: Roadmap + lokale Ideen-Speicherung.
- **DoD:** README: Submodule optional; App startet ohne Submodule.

---

## 6) Phase 5 — PostgreSQL (Railway)

- Models unter [models/](../src/xw_office/models/), Migrationen unter `migrations/` (Alembic).
- DB-Hilfen: [database.py](../src/xw_office/core/database.py).
- **DoD:** Migration pro Kontext; Tokens verschlüsselt (Fernet).

---

## 7) Phase 6 — Qualität

- pytest-qt; Performance-Ziele im README; Ruff/mypy optional in CI.

---

## 8) Copilot — Initialer Start (Session 1)

```text
You are working in the XeisWorks/XW-Office repository (XeisWorks Office desktop app, PySide6).

Before coding:
1. Read CLAUDE.md and follow it strictly: English code, German UI strings, logging not print(), no bare except, use BackgroundWorker for blocking work.
2. Do NOT copy-paste large chunks from the legacy XeisWorks/sevDesk repo; re-implement small, well-typed modules.
3. Keep secrets out of git; only update .env.example if new env vars are needed.

Goal for this session (Phase 1 start):
A) Add a small shared HTTP layer (httpx) under src/xw_office/services/http_client.py used by new sevDesk clients.
B) Implement src/xw_office/services/sevdesk/invoice_client.py with Pydantic models and SevdeskApiError on failure.
C) Add src/xw_office/services/invoice_processing/service.py as a thin facade.
D) Create src/xw_office/ui/modules/rechnungen/view.py: DataTable, load invoice list via BackgroundWorker, German labels, empty/error states.
E) Register the Rechnungen view in MainWindow so sidebar "rechnungen" opens this view instead of a placeholder.

Constraints:
- pytest tests/ must pass; add minimal tests for HTTP error mapping or DTO parsing if easy.
- Never block the UI thread with network I/O.

Deliver: one cohesive commit-sized change set with short summary in PR description style (what/why).
```

---

## 9) Kurz-Prompt für Folge-Sessions

```text
Continue XW-Office per CLAUDE.md and docs/copilot_migration_plan.md. Pick the next checklist item in the current phase, implement with tests, keep UI non-blocking, German UI labels only in UI layer.
```
