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
- **Geloester Vorfall (2026-09-15/16, siehe Abschnitt 3):** ein `startCommand`-Fehler
  in `railway.toml` hat fuenf Deploys in Folge lautlos am Containerstart scheitern
  lassen, unabhaengig vom Code-Inhalt. Seit Commit `c40ac50` behoben und bestaetigt.
- **Weiterhin offen:** der GitHub-Webhook hat nach dem PR07-Push am 16.09. 10+ Minuten
  lang **kein** neues Deployment ausgeloest (alle Deploys dieser Session liefen ueber
  den manuellen `railway up`-Weg). Ob das am selben Vorfall lag oder eine eigene,
  separate Webhook-Anbindungsfrage ist, ist nicht abschliessend geklaert. Deshalb:
  nach jedem Push aktiv pruefen (Abschnitt 4) und im Zweifel `railway up` als
  manuellen Ersatzweg nutzen (Abschnitt 6) - nicht blind darauf vertrauen, dass der
  Push allein reicht.

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

## 3) Geloester Vorfall: Deploys scheitern lautlos an der Startphase (2026-09-15/16)

**Ursache gefunden und behoben (2026-09-16, Commit `c40ac50`):** `railway.toml` hatte ein
explizites `[deploy].startCommand`:

```toml
startCommand = "PYTHONPATH=src python -m uvicorn xw_office.web.app:app --host 0.0.0.0 --port $PORT"
```

Das wurde am 15.09. um 09:32/09:38 Uhr als vermeintlicher Fix fuer ein anderes Problem
ergaenzt (`8c76047`, `2d2f0b7`) - **noch nie erfolgreich deployt**, bevor die
Fehlschlaege abends begannen. `PYTHONPATH=src ...` ist eine Shell-Syntax
(Variablenzuweisung vor dem Befehl); Railways `startCommand` laeuft bei
Dockerfile-Builds nicht garantiert durch eine Shell wie `Dockerfile.web`s eigenes
`CMD ["sh", "-c", "..."]`. Ohne Shell wird `PYTHONPATH=src` als Programmname
interpretiert -> der Container startet gar nicht erst, **bevor** Python ueberhaupt
laeuft - exakt deckungsgleich mit der Beobachtung "Build erfolgreich, Deploy-Logs
komplett leer".

`Dockerfile.web` macht dasselbe bereits korrekt (`ENV PYTHONPATH=/app/src` fest im
Image, `CMD` mit echtem `sh -c` und `${PORT:-8000}`-Fallback) - das
`startCommand`-Override war ueberfluessig und hat genau das kaputt gemacht, was es
reparieren sollte. Fix: die Zeile aus `railway.toml` entfernt, Railway faellt jetzt auf
das Dockerfile-`CMD` zurueck. Naechster Deploy-Versuch (`dd87c443`) war sofort
erfolgreich.

**Lehre fuer kuenftige Aenderungen an `railway.toml`/Start-Kommandos:** eine Aenderung
an `startCommand`/`Procfile` ist selbst ein Deploy-relevanter Code-Pfad und muss wie
jede andere Aenderung durch einen tatsaechlichen, beobachteten Deploy bestaetigt werden -
nicht nur "sollte funktionieren, sieht plausibel aus".

Beobachtung waehrend der ungeloesten Phase (2x am 15.09. abends, 3x am 16.09. vor dem
Fix - fuenf von fuenf Versuchen mit identischem Muster):

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
- Die Build-Logs erwaehnen "scheduling build on Metal builder" - das war eine
  Ablenkung, keine Ursache; der eigentliche Fehler lag in `railway.toml` (siehe oben).

**Tatsaechliche Ursache:** ein `startCommand`-Override in `railway.toml`, nicht die
Railway-Plattform. "Leere Deploy-Logs trotz erfolgreichem Build" bedeutet: der
Container-Prozess startet gar nicht erst - bei einem Docker-Build zuerst
`railway.toml`s `[deploy].startCommand` pruefen, bevor man Plattforminstabilitaet
vermutet oder Zeit in wiederholte blinde Retries steckt.

## 4) Deploy-Status manuell pruefen

```powershell
railway status
railway deployment list --service XW-Content-Web
railway logs --build <deployment-id>
railway logs --deployment <deployment-id>
railway logs --http --status ">=400" --lines 50
```

- `railway logs --build`/`--deployment` waren bei allen fuenf Deployments des geloesten
  Vorfalls inhaltsleer (siehe Abschnitt 3) - leere Deploy-Logs trotz erfolgreichem Build
  sind ein starkes Signal fuer ein `railway.toml`/`startCommand`-Problem, nicht fuer
  einen Python-Fehler.

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
