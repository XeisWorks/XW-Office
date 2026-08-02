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
8. App starten:
   - `python -m xw_office`

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
- Code-Updates laufen ueber GitHub + Auto-Update beim Appstart. Das Auto-Update verweigert
  Updates auf anderen Branches, damit `main` nicht versehentlich in einen Arbeitsbranch
  gemischt wird.
- Nach groesseren Updates App neu starten.

Empfehlung Rollenmodell:
- 1 Druck-PC: stabile Druckerzuordnung, Noten-/Rechnungsdruck.
- 1-2 Office-PCs: Rechnungen, CRM, Steuern, Produktpflege.

## 5) Update-Routine

- Vor Schichtbeginn auf jedem PC:
  - App starten (Auto-Update prueft Pull/Install)
  - DB-Status in Einstellungen kurz pruefen
  - Druckerampel pruefen (Druck-PC)

Bei manueller Aktualisierung:
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

## 6) Backup und Wiederherstellung

- Primaer-Backup: Railway PostgreSQL Snapshots/Backups.
- Sekundaer: regelmaessiger SQL-Dump.
- Wiederherstellungstest mindestens monatlich.

## 7) Stoerungsbehebung

- Symptom: kein Sync / keine Daten.
  - `DATABASE_URL` pruefen.
  - In Settings Verbindung testen.
- Symptom: Token-bezogene API-Fehler.
  - Secret-Eintraege in Settings pruefen.
- Symptom: Druck nicht verfuegbar.
  - Druckerampel / konfigurierte Druckernamen pruefen.

## 8) Wartungscheckliste (monatlich)

- `pytest tests/`
- `ruff check src/`
- `alembic current` gegen `head` pruefen
- Drucktest mit Rechnungs- und Noten-PDF
- Start-Preflight mit Testdaten verifizieren
