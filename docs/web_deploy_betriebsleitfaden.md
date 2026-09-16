# XW-Content-Web Deploy-Betriebsleitfaden

Ziel:
- Ein einziger, wiederholbarer, PC-unabhaengiger Weg, um Aenderungen an
  `src/xw_office/web/` (Content Studio + Product Hub Read API) produktiv auf Railway
  zu bringen, mit denselben Pruefungen wie CI.
- Nachvollziehbar machen, was bei einem Deploy tatsaechlich passiert, statt Schritte
  aus dem Gedaechtnis in verschiedene Terminals zu tippen.

## 1) Ueberblick: was deployt wird und wie

- Service: **XW-Content-Web** (Railway-Projekt "XW-Studio").
- Build: `Dockerfile.web`, Abhaengigkeiten aus `requirements-web.txt` (bewusst schlank -
  **kein** `config/default.yaml`, **keine** Desktop-/Druck-Abhaengigkeiten aus
  `pyproject.toml`; siehe Abschnitt 5).
- Auslöser im Normalfall: jeder Push nach `origin/main` (siehe `railway.toml` /
  Railway-GitHub-Verbindung). Kein separater "Deploy"-Klick noetig, wenn der Webhook
  zuverlaessig feuert.
- **Bekannte Einschraenkung (Stand 2026-09-16):** Der GitHub-Webhook hat mehrfach nicht
  zuverlaessig ausgeloest (zwei FAILED-Deployments am 15.09. abends ohne Build-/
  Deploy-Log-Inhalt; ein Push am 16.09. hat 10+ Minuten lang **gar kein** neues
  Deployment ausgeloest). Deshalb: nach jedem Push aktiv pruefen (Abschnitt 3) und im
  Zweifel `railway up` als manuellen Ersatzweg nutzen (Abschnitt 6) - nicht blind
  darauf vertrauen, dass der Push allein reicht.

## 2) Empfohlener Weg: `scripts\deploy_web.ps1`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_web.ps1
```

Fuehrt aus (Details siehe Kommentarkopf im Skript):

1. Branch/Upstream/sauberer Arbeitsbaum pruefen - committet, mergt, stasht oder
   verwirft **nichts** selbst.
2. lokale `main` mit `origin/main` vergleichen (bei Rueckstand: Abbruch, kein Auto-Pull).
3. Qualitaets-Gate exakt wie `.github/workflows/ci.yml`: `ruff check src/`,
   `mypy src/` (weich, wie CI), `pytest tests/`.
4. optional `-VerifyLeanWebImage`: `requirements-web.txt` isoliert in einer
   Wegwerf-venv smoke-testen (siehe Abschnitt 5) - faengt einen fehlenden
   Abhaengigkeitseintrag ab, bevor er erst im Railway-Build auffaellt.
5. `git push origin main`.
6. Railway-CLI-Verfuegbarkeit pruefen (optional `-InstallMissingTools`, siehe Abschnitt 7).
7. neues Deployment erkennen und bis zu `-WatchTimeoutMinutes` (Default 10) auf einen
   Endzustand pollen.
8. nur mit explizitem `-Fallback` und nur wenn kein neues Deployment erkannt wurde:
   `railway up` als manueller Ersatz-Deploy. Ohne `-Fallback` wird der Befehl nur
   vorgeschlagen, nie automatisch ausgefuehrt.

Praktisch, angesichts der bekannten Webhook-Einschraenkung:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_web.ps1 -Fallback
```

Log: `logs\deploy_web.log` (gleiches Muster wie `logs\xw_office_update.log`).

## 3) Bekannter Vorfall: Deploys scheitern lautlos an der Startphase (seit 2026-09-15)

Beobachtung (2x am 15.09. abends vor jeder Code-Aenderung dieses Leitfadens, 2x erneut
am 16.09. bei PR07-Deploy-Versuchen - vier von vier Versuchen):

- `railway logs --build <id>` zeigt einen vollstaendig erfolgreichen Build (inkl. Image
  Push), auch mit den seit PR07 neuen Abhaengigkeiten `sqlalchemy`/`psycopg2-binary`/
  `python-dotenv`.
- `railway logs --deployment <id>` liefert **keine einzige Zeile** - kein Python-
  Traceback, kein Uvicorn-Log, nichts. `Dockerfile.web` setzt `PYTHONUNBUFFERED=1`,
  ein echter Python-Crash sollte also sichtbar sein.
- Status springt direkt von `DEPLOYING`/`INITIALIZING` auf `FAILED`.
- Die zuletzt erfolgreich laufende Version bleibt online und gesund (Railway ersetzt
  eine funktionierende Instanz nicht durch eine fehlgeschlagene) - kein Produktions-
  ausfall, nur kein neuer Code live.
- Lokale Reproduktion mit identischem Befehl (`python -m uvicorn xw_office.web.app:app
  --host 0.0.0.0 --port <PORT>`), identischen Abhaengigkeiten (nur
  `requirements-web.txt`, frische venv) und ohne `DATABASE_URL` startet fehlerfrei und
  beantwortet `/health` mit 200.
- Die Build-Logs erwaehnen "scheduling build on Metal builder" - vermutlich ein
  (neuerer) Railway-Builder/Runtime-Pfad, der fuer diesen Service aktuell gestoert ist.

**Einschaetzung:** kein Code-Problem dieses Repos, sondern eine Railway-seitige
Instabilitaet fuer den Service "XW-Content-Web". Vor weiterem Debugging hier zuerst:

1. Im Railway-Dashboard (nicht nur CLI) direkt nachsehen - die Web-UI zeigt teils mehr
   Diagnosedetails als `railway logs`.
2. Falls das Problem anhaelt: Railway-Support kontaktieren bzw. Status-Page pruefen.
3. Erneuter Versuch zu einem spaeteren Zeitpunkt, statt wiederholt blind zu retryen.

## 4) Deploy-Status manuell pruefen

```powershell
railway status
railway deployment list --service XW-Content-Web
railway logs --build <deployment-id>
railway logs --deployment <deployment-id>
railway logs --http --status ">=400" --lines 50
```

- `railway logs --build`/`--deployment` waren bei allen vier bisher beobachteten
  fehlgeschlagenen Deployments inhaltsleer (siehe Abschnitt 3). Bei einem
  FAILED-Status ohne erkennbaren Grund in den Logs: nicht in leeren Logs graben,
  sondern Abschnitt 3 pruefen und ggf. erneut deployen (Abschnitt 6).

## 5) Schlankes Web-Image: was es enthaelt und warum

`Dockerfile.web` kopiert **nur** `src/` und `config/content_brands.yaml` - explizit
**nicht** `config/default.yaml`. `requirements-web.txt` enthaelt nur, was
`xw_office.web.app` tatsaechlich transitiv braucht:

- `fastapi`, `pydantic`, `uvicorn` - Web-Fundament.
- `PyYAML` - fuer `BrandProfileCatalog`.
- `sqlalchemy`, `psycopg2-binary`, `python-dotenv` - seit PR07 (Product Hub Read API):
  `xw_office.repositories.product_hub` importiert `xw_office.core.database`, was
  wiederum `xw_office.core.config` importiert; letzteres braucht `python-dotenv` beim
  Modul-Import, obwohl diese Web-App `load_config()`/`config/default.yaml` **nie**
  aufruft - `ContentWebSettings` liest ihre eigenen Umgebungsvariablen direkt.

Bei jeder neuen Abhaengigkeit, die ein `web/`-Modul (transitiv) braucht: **zuerst**
`requirements-web.txt` ergaenzen, **dann** mit `-VerifyLeanWebImage` lokal bestaetigen,
dass `xw_office.web.app` mit nur dieser Datei installierbar importiert - nicht erst im
Railway-Build herausfinden.

## 6) Manueller Ersatz-Deploy ohne Skript

```powershell
railway up --service XW-Content-Web --ci -m "Kurzbeschreibung"
```

- `--ci` beendet den Stream nach den Build-Logs, statt dauerhaft angehaengt zu bleiben.
- Lokale, uncommittete Aenderungen werden mit hochgeladen (kein Git-Zwischenschritt) -
  fuer produktive Deploys trotzdem immer von einem sauberen, committeten `main`-Stand
  aus ausfuehren, damit das, was laeuft, mit dem Repo-Stand uebereinstimmt.
- Ein `reqwest error .../operation timed out` direkt nach dem Upload bedeutet nicht
  zwingend, dass der Deploy fehlgeschlagen ist - das war ein CLI-seitiger
  Verbindungsabbruch beim Log-Streaming, waehrend der Build serverseitig weiterlief.
  Immer mit `railway deployment list --service XW-Content-Web` nachpruefen, statt sich
  auf den Exit-Code des CLI-Aufrufs zu verlassen.

## 7) Railway-CLI installieren

```powershell
npm install -g @railway/cli
railway login
railway link   # einmalig: Projekt/Service verknuepfen
```

Alternative ohne npm: offizielles Installationsskript, siehe
https://docs.railway.com/guides/cli.

## 8) Migrationen - bewusst NICHT Teil dieses Deploy-Wegs

`scripts\deploy_web.ps1` fuehrt **keine** Alembic-Migration aus. Grund: Migrationen
sind eine Aenderung an der produktiven Datenbank, nicht nur am Code, und sollen bewusst
einzeln, mit Blick auf das Ergebnis, ausgefuehrt werden - nicht als Nebeneffekt eines
Web-Deploys. Vorgehen bei neuen Migrationen im aktuellen Push:

```powershell
git -C . log --name-only -1 -- src/xw_office/migrations/versions
alembic upgrade head
alembic current
```

Siehe auch `docs/multi_pc_betriebsleitfaden.md` und, fuer den Product-Hub-Kontext,
`docs/product_hub/PROGRESS.md`.

## 9) Rollback

```powershell
railway deployment list --service XW-Content-Web
railway redeploy --service XW-Content-Web   # letztes Deployment erneut ausrollen
```

Fuer einen Rollback auf einen bestimmten, aelteren Stand: den gewuenschten Commit in
`main` per `git revert` rueckgaengig machen und erneut ueber diesen Leitfaden deployen -
kein `git reset --hard`/Force-Push auf `main`.
