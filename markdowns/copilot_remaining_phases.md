# XW-Studio — Offene Phasen nach Ist-Stand (Phase 2–6)

## Quick test evidence (lokal)
- `pytest tests/`: **grün** (29 bestanden).
- Lokale Config-Leselogik verwendet standardmäßig `.env` via `load_dotenv()` (nicht `.env.example`).
  - In diesem Workspace ist `.env` aktuell **nicht vorhanden**.
  - Ergebnis: `load_config()` liefert lokal `database_url_set=False` und `fernet_key_set=False`.
- Für Railway/Deployment müssen die Variablen tatsächlich im **App-Service** als Environment Variables/Secrets gesetzt sein.

## Blueprint (Single Source of Truth)
Quelle: `docs/copilot_migration_plan.md`

## Ist-Stand vs. Blueprint (kurz & prüfbar)

### Phase 2 — Finance & Analytics
- Blueprint fordert: nicht blockierendes UI + **SOAP-Tests mit Mocks**.
- Ist-Stand:
  - UI `TaxesView` nutzt `BackgroundWorker` (nicht blockierend).
  - UVA SOAP Mocks + Tests existieren (`tests/unit/test_uva_soap_mock.py`).
- Offen:
  - **Echte** Zeep-Implementierung für UVA (SOAP/WSDL, Payload mapping) fehlt.
  - Keine zeep-spezifischen Tests für “filing type”-Varianten (nur generischer Mock/Contract).

### Phase 3 — CRM, Layout, Kalkulation
- Blueprint fordert: **Matching + Merge-Wizard** (Service zuerst) + Layout (Panels) + Pydantic für externe Payloads + DE-UI.
- Ist-Stand:
  - CRM Matching: implementiert (Pydantic DTOs + rapidfuzz scoring).
  - UI zeigt Demo-Scan, aber **kein Merge-Wizard**.
  - Layout/Calculation: vorhanden als Karten/Platzhalter bzw. Skeleton-Services.
- Offen:
  - Merge-Wizard: Service-API (welcher Kontakt bleibt “Master”, wie werden Daten zusammengeführt) + UI für Auswahl/Bestätigung.
  - Layout/Calculation: Panels/DE-UI “echte” Interaktion statt nur Roadmap/Cards.

### Phase 4 — Integration
- Blueprint fordert: Reisekosten Submodule + Bridge, App startet ohne Submodule.
- Ist-Stand:
  - `travel_costs/view.py` ist weiterhin **Placeholder** und beschreibt “Submodule fehlt”.
- Offen:
  - Conditional Submodule Bridge / Loader implementieren (wenn Repo vorhanden, UI einbetten; sonst Placeholder).

### Phase 5 — PostgreSQL (Railway)
- Blueprint fordert: Alembic Migrationen; DB-Hilfen; **Tokens verschlüsselt (Fernet)**; Migration pro Kontext.
- Ist-Stand:
  - Models + Alembic Initial-Migration existieren.
  - `token_crypto.py` und Repository-Klassen existieren.
  - Jedoch: **Repositories sind aktuell nicht in die Token/HTTP-Flow integriert** (HTTP-Client nutzt weiterhin Env Tokens).
- Offen (kritisch):
  - Implementiere einen “Secret/Token Provider” Service, der:
    - `FERNET_MASTER_KEY` nutzt,
    - `ApiSecretRepository` liest/speichert,
    - ggf. Env-Fallback einmalig DB-speichert (mit Verschlüsselung).
  - Aktualisiere sevDesk HTTP Clients so, dass sie DB-basierte Secrets verwenden (nicht nur Env).
  - Optional/erst später: SettingKV/PcRegistry in tatsächlichen Flows nutzen (z.B. Printer gating / UI Settings).

### Phase 6 — Qualität
- Blueprint fordert: pytest-qt + Performance-Ziele im README + Ruff/mypy optional in CI.
- Ist-Stand:
  - pytest-qt existiert (Smoke-Test).
  - CI läuft aktuell nur `pytest`.
  - README enthält Performance-Notes, aber keine expliziten Performance-Ziele.
- Offen:
  - CI erweitern: `ruff check` (und optional `mypy`) laufen lassen.
  - README: konkrete Performance-Ziele ergänzen (z.B. UI Responsiveness / Netzwerk-Timeouts / Worker-Auslastung).

## Prompt für den nächsten Codex/Copilot-Agent

### Ziel
Setze alle **offenen** Punkte aus “Ist-Stand vs Blueprint” um, jeweils als kleine, commit-fähige Einheiten mit Tests, ohne UI-Thread zu blockieren.

### Harte Regeln (aus `CLAUDE.md`, analog)
1. Code: **English** (Namen/Kommentare), UI-Strings **Deutsch**.
2. `logging` statt `print()`.
3. Keine nackten `except`-Blöcke.
4. Blocking Arbeit (SOAP/IO): per `BackgroundWorker` / `QThreadPool`.
5. Externe Payloads: Pydantic Modelle.
6. Secrets niemals committen; nur `.env.example` erweitern, falls nötig.

### Arbeitspakete (empfohlene Reihenfolge)

#### Paket A (Phase 2): Zeep-UVA Backend + Tests
1. In `src/xw_studio/services/finanzonline/uva_soap.py`:
   - Implementiere einen `ZeepUvaSoapBackend` (oder ergänzende Backend-Klasse).
   - Mapping: Payload (internes dict oder besser: Pydantic) → SOAP Calls.
   - Nutze WSDL/Endpoints + Credentials aus Config/DB (zuerst Env, später DB-Provider).
2. Tests:
   - Füge Tests hinzu, die zeep calls **mocken** (z.B. “zeep.Client.service.…”).
   - Stelle sicher, dass pro “Meldungstyp” korrekt die Call-Signatur gewählt wird (filing-type Varianten).
3. UI:
   - Aktualisiere den Button-Text in `src/xw_studio/ui/modules/taxes/view.py` (kein “noch nicht implementiert”, sobald Backend verfügbar ist).

Abnahmekriterien:
- `pytest tests/` grün.
- UVA Submit kann in “Echt-Modus” (mit Zeep backend konfiguriert) eine `UvaSubmitResult(ok=True, ...)` zurückgeben.

#### Paket B (Phase 3): CRM Merge-Wizard (Service zuerst)
1. In `src/xw_studio/services/crm/service.py`:
   - Ergänze eine Merge-Funktion, z.B. `merge_contacts(master: ContactRecord, duplicate: ContactRecord, strategy: ...)`.
   - Nutze den bestehenden `ContactClient` (sevDesk) und Pydantic DTOs.
2. In UI:
   - Implementiere einen Wizard/Dialog im CRM Modul:
     - zeigt Kandidaten-Duplis,
     - erlaubt Auswahl des Master-Kontakts,
     - bestätigt den Merge und zeigt Status.
3. Tests:
   - Unit-Test für Merge-Strategie (mock `ContactClient`).

Abnahmekriterien:
- Merge ist vollständig testbar ohne echte Netzwerkrequests.
- Keine UI-Blocking Calls.

#### Paket C (Phase 4): Travel-Costs Bridge (optional Submodule)
1. In `src/xw_studio/ui/modules/travel_costs/view.py`:
   - Implementiere einen Loader:
     - Wenn Submodule vorhanden: importiere dessen Qt-Widget und zeige es ein.
     - Sonst: Placeholder bleibt.
2. Tests:
   - Optional: Import-Lader als Funktion testbar machen (mock import).

Abnahmekriterien:
- App startet ohne Submodule.
- Sobald Submodule vorhanden ist, funktioniert das Laden.

#### Paket D (Phase 5): DB-secrets provider + Integration in sevDesk HTTP
1. Neue Service-Komponente (z.B. `src/xw_studio/services/secrets/token_provider.py`):
   - Verantwortlich für:
     - `FERNET_MASTER_KEY` Validierung
     - Lesen von Tokens aus `ApiSecretRepository`
     - Verschlüsseln/Entschlüsseln mit `token_crypto`
     - Env-Fallback (wenn DB leer) und optional “seed to DB”
2. Integrationspunkt:
   - Aktualisiere `src/xw_studio/services/http_client.py`:
     - `build_sevdesk_http_client()` nimmt nicht mehr direkt `config.sevdesk.api_token`, sondern TokenProvider/Repo.
   - Aktualisiere DI (`src/xw_studio/bootstrap.py`) entsprechend.
3. Migration/DB:
   - Prüfe, ob die Alembic Migration(en) ausreichen.
   - Bei Bedarf: neue Revisionen.

Abnahmekriterien:
- Keine plaintext Tokens in DB.
- Wenn DB leer ist, kann App (mit env tokens gesetzt) einmalig DB seed-en.

#### Paket E (Phase 6): CI + README Performance-Ziele
1. `.github/workflows/ci.yml`:
   - Ergänze `ruff check src/` (und optional mypy `mypy src/`).
2. `README.md`:
   - Ergänze messbare Performance-Ziele (z.B. Netzwerk-Timeouts/Worker-Responsiveness).

Abnahmekriterien:
- CI bleibt grün.

### Deliverables je Paket
- 1–2 Commits pro Paket, jeweils “commit-fähige Einheit”.
- Neue/angepasste Tests für jedes Paket.

### Testplan (lokal)
- `pytest tests/`
- Optional:
  - `ruff check src/`

