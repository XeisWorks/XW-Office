# XW-Office: Windows-Desktop-Start und leichtes Source-Update

Stand: 2026-08-14 (Update-Konzept am selben Tag um automatischen Update-Check erweitert)
Status: umgesetzt und auf dem Entwicklungs-PC verifiziert

## 1. Ziel und Entscheidung

XW-Office soll sich im Alltagsbetrieb wie eine normale Windows-Anwendung verhalten:

- kein sichtbares CMD-/PowerShell-Fenster beim normalen Start,
- eigener Name und eigenes Icon in Startmenue und Taskleiste,
- weiterhin vollstaendige, fuer Codex und Claude Code leicht lesbare Dateilogs,
- weiterhin einfacher Betrieb direkt aus einem Git-Checkout,
- kleine, haeufige Source-Updates ohne kompletten Anwendungs-Build,
- reproduzierbare Einrichtung auf mehreren Windows-PCs,
- ein separater Diagnose-/Debug-Start mit sichtbarer Konsole bleibt erhalten.

### Architekturentscheidung

Vorerst **kein Voll-Bundling der Anwendung mit PyInstaller**. Das bestehende Source-/Git-Modell
passt besser zu den woechentlichen kleinen Updates aus VS Code. Stattdessen wird der normale
Start auf `pythonw.exe` umgestellt und durch einen kleinen Python-GUI-Bootstrap sowie pro PC
generierte Windows-Verknuepfungen abgesichert.

Zielbild:

```text
Normaler Start:
Startmenue/Taskleiste
  -> .lnk (pro PC generiert, eigenes Icon, korrektes Arbeitsverzeichnis)
  -> .venv\Scripts\pythonw.exe
  -> GUI-Bootstrap im Repo
  -> python -m xw_office / create_application()
  -> PySide6-Hauptfenster, keine Konsole

Debug-Start:
run_xw_office_debug.cmd
  -> .venv\Scripts\python.exe
  -> sichtbare Konsole plus dieselben Dateilogs

Update (automatischer, lautloser Check vor dem normalen Start):
GUI-Bootstrap, vor dem eigentlichen App-Start
  -> Branch=main? Upstream=origin/main? Arbeitsbaum sauber? (sonst: lautlos ueberspringen)
  -> git fetch origin main (kurzes Timeout, bei Offline/Fehler: lautlos ueberspringen)
  -> Update vorhanden? -> Ja/Nein-Dialog ("Jetzt aktualisieren?")
       Ja  -> scripts\update_xw_office.ps1 (ff-only, eigenes Update-Log) -> App startet aktualisiert
       Nein/Fehler -> App startet unveraendert, nie blockierend

Update (manuell/administrativ, weiterhin direkt aufrufbar):
scripts\update_xw_office.ps1
  -> Branch-/Working-Tree-Pruefung
  -> git fetch + git pull --ff-only origin main
  -> Abhaengigkeiten/Migrationen nur wenn erforderlich
  -> eigenes Update-Log
```

Ein kleiner kompilierter Launcher bleibt eine spaetere Option, ist fuer die erste Ausbaustufe
aber nicht erforderlich. Er soll nur eingefuehrt werden, wenn sich beim Test auf den realen PCs
zeigt, dass Windows die Taskleistenverknuepfung trotz AppUserModelID und Fenstericon nicht stabil
behandelt oder wenn ein robusterer Self-Repair-Start gebraucht wird.

## 2. Verifizierter Ist-Zustand

### 2.1 Startkette

Die aktuelle Kette lautet korrekt:

```text
run_xw_office.cmd
  -> .venv\Scripts\python.exe (bevorzugt, sonst globaler Python-Fallback)
  -> python -m xw_office
  -> src/xw_office/__main__.py
  -> src/xw_office/app.py:create_application()
  -> QApplication
  -> MainWindow.showMaximized()
```

Es gibt keine `src/xw_office/main.py` in dieser Startkette. Der Moduleinstieg ist
`src/xw_office/__main__.py`.

Das sichtbare Fenster ist technisch ein Konsolenfenster, nicht zwingend ein
"PowerShell-Fenster":

- Beim Doppelklick auf `.cmd` stellt `cmd.exe` die Konsole bereit.
- Beim Aufruf aus PowerShell wird die vorhandene PowerShell-Konsole verwendet.
- `python.exe` ist ein Console-Subsystem-Prozess und bleibt an diese Konsole gebunden.
- Die Qt-GUI ist davon funktional unabhaengig, laeuft aber im selben Python-Prozess.

### 2.2 Logging

`src/xw_office/core/logging_setup.py` richtet derzeit zwei Handler am Root-Logger ein:

- `StreamHandler(sys.stdout)` fuer die Konsole,
- `RotatingFileHandler` fuer `logs/xw_office.log`.

Beide verwenden derzeit dasselbe Level und Format. Damit landen normale Python-Logging-Records
in beiden Zielen. Die Aussage "alles aus der Konsole steht 1:1 im Dateilog" gilt jedoch nur fuer
Ausgaben, die tatsaechlich ueber `logging` laufen. Nicht automatisch abgedeckt sind insbesondere:

- Fehler vor der Initialisierung des Loggings,
- direkte `print()`- oder `stderr`-Ausgaben,
- native Qt-/DLL-Diagnosen,
- harte Prozessabbrueche,
- nicht erfasste Ausgaben gestarteter Unterprozesse.

Der Logpfad `Path("logs")` ist relativ zum aktuellen Arbeitsverzeichnis. Der bestehende
CMD-Launcher stabilisiert ihn mit `pushd` auf das Repo. Eine Windows-Verknuepfung muss deshalb
ebenfalls ein korrektes Arbeitsverzeichnis setzen; mittelfristig ist ein zentraler absoluter
App-Pfad robuster.

### 2.3 Auto-Update

`src/xw_office/core/updater.py` enthaelt einen Git-basierten Updater. In
`src/xw_office/app.py` wird er aktuell jedoch mit `enabled=False` aufgerufen. Das in README und
Multi-PC-Betriebsleitfaden beschriebene automatische Update beim Appstart findet daher momentan
nicht statt.

Ein Update innerhalb der bereits laufenden GUI ist fuer dieses Betriebsmodell nicht ideal:

- Python-Dateien koennen waehrend der laufenden Session wechseln,
- `pip install` kann die gerade verwendete Umgebung veraendern,
- eine Migration kann parallel auf mehreren PCs angestossen werden,
- lokale VS-Code-Aenderungen koennen mit einem Pull kollidieren,
- Fehler sind ohne sichtbare Konsole schwerer zu verstehen.

Der Update-Schritt soll daher ausserhalb der laufenden App und bewusst kontrolliert stattfinden.

## 3. Warum vorerst kein vollstaendiges PyInstaller-Bundle

Ein Voll-Bundle haette Vorteile bei der Erstinstallation und bei der Unabhaengigkeit von Python.
Fuer den aktuellen Arbeitsablauf ueberwiegen vorerst aber die Nachteile:

- Jede kleine Python-Aenderung braeuchte einen neuen Windows-Build.
- Jeder PC muesste ein neues Bundle bzw. einen Installer erhalten.
- PySide6, OpenCV, NumPy, Matplotlib, PyMuPDF, lxml, cryptography und pywin32 vergroessern und
  verkomplizieren den Build.
- Das vorhandene `git pull`-/Editable-Install-Modell waere nicht mehr direkt nutzbar.
- Ressourcen- und State-Pfade muessen vor einem Bundle ohnehin zuerst bereinigt werden.

Das Source-Modell ist akzeptabel, solange die Betriebs-PCs kontrolliert sind und pro PC gelten:

- Git-Checkout auf `main`,
- eigenes `.venv`,
- sauberer Arbeitsbaum fuer Updates,
- gleiche dokumentierte Python-Version,
- reproduzierbarer Setup- und Update-Befehl.

Ein spaeteres Bundle bleibt sinnvoll, wenn Releases seltener und formeller werden oder wenn die
App auf PCs ohne Git/Python verteilt werden soll.

## 4. Geplanter normaler GUI-Start

### 4.1 `pythonw.exe`

Der normale Start verwendet ausschliesslich:

```text
<repo>\.venv\Scripts\pythonw.exe
```

Fuer den Alltagsstart soll es keinen Fallback auf irgendeine globale Python-Installation geben.
Ein solcher Fallback macht Mehr-PC-Fehler schwer reproduzierbar. Fehlt das lokale `.venv`, wird
ein klarer Reparaturhinweis angezeigt bzw. das Setup erneut ausgefuehrt.

### 4.2 Kleiner GUI-Bootstrap

Vorgesehen ist ein schlanker, versionierter Bootstrap im Repo, beispielsweise
`scripts/xw_office_gui.pyw` oder ein entsprechend klar benanntes Modul. Seine Aufgaben bleiben
eng begrenzt:

1. Repo-Root aus dem eigenen Dateipfad bestimmen.
2. Arbeitsverzeichnis auf das Repo setzen.
3. `src` kontrolliert in den Importpfad aufnehmen, falls der Editable-Install repariert werden
   muss.
4. das fruehe Bootstrap-/Crash-Log oeffnen.
5. AppUserModelID setzen.
6. lautlosen, fail-open Update-Check ausfuehren und bei Bedarf per Dialog anbieten (Abschnitt
   8.3) — laeuft komplett vor Schritt 7, damit ein frisch gezogener Source-Stand noch unimportiert
   ist.
7. `xw_office.__main__.main()` bzw. den regulaeren App-Einstieg starten.
8. Fehler vor Erzeugung der `QApplication` in Datei schreiben und sichtbar melden.

Der Bootstrap darf keine zweite fachliche Startlogik entwickeln. Die eigentliche
Anwendungserzeugung bleibt in `xw_office.app.create_application()`. Der Update-Check ist davon
ausgenommen: er ist reine Prozess-/Git-Orchestrierung ohne fachliche App-Logik und gehoert
strukturell zum Start, nicht zur App selbst.

### 4.3 Fehler vor dem Qt-Start

Die vorhandene globale Exception-Behandlung mit `QMessageBox` greift erst, nachdem Qt und die App
weit genug initialisiert sind. Fuer Fehler davor braucht der Bootstrap eine einfache
Windows-taugliche Meldung, etwa ueber `ctypes.windll.user32.MessageBoxW`.

Beispiele:

- Importfehler,
- defekte virtuelle Umgebung,
- fehlende Qt-DLL,
- nicht beschreibbarer Logordner,
- unlesbare Konfiguration.

Die Meldung zeigt nur eine kurze Zusammenfassung und den absoluten Pfad zur Logdatei.

## 5. Logging-Konzept ohne Konsole

### 5.1 Verhalten von `StreamHandler` unter `pythonw.exe`

Unter `pythonw.exe` koennen `sys.stdout` und `sys.stderr` `None` sein. Ein
`StreamHandler(sys.stdout)` muss daher nicht zwingend bereits bei seiner Konstruktion abstuerzen,
kann aber spaetestens beim ersten Schreibversuch unbrauchbar sein und interne Logging-Fehler
erzeugen.

Geplante Regel:

- File-Handler immer aktivieren.
- Console-Handler nur anlegen, wenn ein gueltiger Stream vorhanden ist.
- Im Debug-Start Console- und File-Handler parallel verwenden.
- Im GUI-Start primaer File-Handler verwenden.

### 5.2 Zielpfad

Erste, minimal-invasive Stufe:

```text
<repo>\logs\xw_office.log
```

Damit bleiben bestehende Agenten- und Supportablaeufe kompatibel.

Empfohlene zweite Stufe:

```text
%LOCALAPPDATA%\XeisWorks\XW Office\Logs\xw_office.log
```

Dieser Pfad ist unabhaengig von Checkout-Ort, Verknuepfung und Schreibrechten im Repo. Fuer Codex
und Claude Code wird der absolute Pfad in der Betriebsdoku und optional in einer kleinen
`logs-location.txt` im Repo dokumentiert. Alternativ kann fuer eine Uebergangszeit an beiden
Orten protokolliert werden; zwei dauerhafte Wahrheiten sollen vermieden werden.

### 5.3 Zusaetzlich zu erfassende Quellen

- Python-Warnings via `logging.captureWarnings(True)`.
- `sys.excepthook` fuer unbehandelte Python-Fehler.
- Fehler des Bootstrap vor dem regulaeren Logging.
- Qt-Meldungen ueber `qInstallMessageHandler`, soweit praktikabel.
- `faulthandler` in eine separate Crashdatei fuer harte Python-Abbrueche.
- Rueckgabecode, stdout und stderr relevanter Unterprozesse.
- Startinformationen: App-Version, Commit, Computername, Prozess-ID, Interpreterpfad,
  Repo-Pfad, Logpfad und Startmodus (`gui`/`debug`).

Secrets, Authorization-Header, Pins und Datenbankpasswoerter muessen redigiert bleiben.

### 5.4 Rotation und Diagnose

Die derzeitigen 2 MB plus drei Backups sind fuer den Anfang ausreichend, fuer laengere
Agentenanalysen aber knapp. Vorgesehen ist eine konfigurierbare Rotation, beispielsweise:

- normal: 5 bis 10 MB pro Datei, 5 bis 10 Backups,
- Debug: optional `DEBUG`-Level und hoehere Aufbewahrung,
- keine unbegrenzten Logdateien.

Spaeter sinnvolle UI-Aktionen:

- Logordner oeffnen,
- aktuelle Logdatei oeffnen,
- Diagnosepaket ohne Secrets erzeugen,
- Log-Level fuer die naechste Session temporaer erhoehen.

## 6. Windows-Identitaet und Taskleiste

### 6.1 App-Icon

Aus dem freigegebenen Logo wird ein echtes Multi-Resolution-`.ico` erzeugt. Vorher ist zu
pruefen, ob `icons/logo NEU.png` bei kleinen Groessen lesbar ist oder eine vereinfachte
Iconvariante benoetigt.

Das Icon wird gesetzt fuer:

- `QApplication`,
- `MainWindow`,
- Startmenue-/Desktop-Verknuepfung,
- einen eventuellen spaeteren kompilierten Launcher.

### 6.2 AppUserModelID

Der GUI-Prozess setzt unter Windows vor der Erzeugung der sichtbaren Fenster eine feste ID, zum
Beispiel:

```text
at.xeisworks.xwoffice
```

Dadurch kann Windows das Fenster unabhaengig von anderen `pythonw.exe`-Prozessen gruppieren.
Nicht-Windows-Systeme ueberspringen diesen Schritt sauber.

Wichtig: AppUserModelID, Fenstericon und Shortcut-Identitaet muessen gemeinsam auf den realen
Windows-10-/11-PCs getestet werden. Ein Shortcut auf `pythonw.exe` mit individuellen Argumenten
ist nicht in jeder Windows-Situation so stabil wie eine echte produktspezifische EXE. Falls das
Anheften oder erneute Starten ueber das angeheftete Icon unzuverlaessig ist, wird Phase 2 um einen
kleinen nativen Launcher erweitert.

### 6.3 Verknuepfungen

Eine `.lnk` wird nicht ins Repo eingecheckt, weil sie absolute Pfade enthaelt. Stattdessen erzeugt
ein versioniertes Setup-Skript pro PC:

- einen Startmenueeintrag `XeisWorks Office`,
- optional einen Desktop-Eintrag,
- einen Startmenueeintrag `XeisWorks Office - Debug`.

Ein eigener Startmenueeintrag `XeisWorks Office aktualisieren` wird bewusst **nicht** mehr
angelegt: der normale Start prueft automatisch und lautlos auf Updates (siehe Abschnitt 8.3) und
bietet sie per Dialog an, ein separater manueller Aufruf ist fuer den Alltag nicht mehr noetig.
Das Setup-Skript entfernt eine bereits vorhandene alte `XeisWorks Office aktualisieren.lnk` beim
naechsten Lauf automatisch. `scripts\update_xw_office.ps1` bleibt als Datei erhalten und ist
weiterhin direkt aus einer Konsole aufrufbar (Admin-/Entwicklungsfall, siehe Abschnitt 8.2).

Die normale Verknuepfung enthaelt:

- Ziel: lokales `.venv\Scripts\pythonw.exe`,
- Argument: GUI-Bootstrap,
- Arbeitsverzeichnis: Repo-Root,
- Icon: versioniertes `.ico` im Repo.

Der Benutzer heftet danach `XeisWorks Office` aus dem Startmenue selbst an die Taskleiste an.

## 7. Debug-Start

Der bisherige sichtbare Start wird als klar benannter Diagnoseweg erhalten:

```text
run_xw_office_debug.cmd
```

Er soll:

- das lokale `.venv` bevorzugen bzw. fuer reproduzierbaren Betrieb verlangen,
- das Repo als Arbeitsverzeichnis setzen,
- `python.exe -m xw_office` starten,
- Konsole und Dateilog parallel bedienen,
- bei einem Fehler den Exit-Code und Logpfad anzeigen,
- bei Bedarf mit `XW_OFFICE_LOG_LEVEL=DEBUG` gestartet werden koennen.

Der normale Benutzer startet ueber Taskleiste/Startmenue. Codex, Claude Code und Entwickler
koennen bei einer Live-Diagnose gezielt den Debug-Start verwenden. Fuer die nachtraegliche
Analyse bleibt die Logdatei die primaere Quelle.

## 8. Update-Konzept fuer woechentliche Source-Aenderungen

### 8.1 Grundsatz

Source-Updates bleiben leichtgewichtig:

```text
VS Code / Entwicklungs-PC
  -> getestete Aenderung nach main
  -> Push zu origin/main

Betriebs-PC
  -> App schliessen
  -> Update-Aktion ausfuehren
  -> Fast-forward auf origin/main
  -> App starten
```

Eine reine `.py`-Aenderung braucht keinen Build und normalerweise kein erneutes `pip install`,
weil das Projekt editable installiert ist bzw. aus `src` gestartet wird.

### 8.2 Update-Mechanik (`scripts\update_xw_office.ps1`)

Die eigentliche Update-Logik lebt in einem PowerShell-Skript, unabhaengig davon, ob es automatisch
(Abschnitt 8.3) oder manuell/administrativ aufgerufen wird. Ein sichtbares Fenster ist bei
manuellem Aufruf akzeptabel und hilfreich; beim automatischen Aufruf aus dem GUI-Bootstrap laeuft
es ohne Konsolenfenster.

Der Updater prueft in dieser Reihenfolge:

1. Repo-Root eindeutig aufloesen.
2. Sicherstellen, dass XW-Office nicht laeuft (der aufrufende Bootstrap-Prozess kann sich dabei
   ueber `-ExcludeProcessId` von der eigenen Pruefung ausnehmen, da er selbst noch nicht die
   fertig gestartete App ist).
3. `git status --porcelain` muss leer sein.
4. Aktueller Branch muss `main` sein.
5. Upstream muss `origin/main` sein.
6. `git fetch origin main`.
7. Nur `git pull --ff-only origin main` erlauben.
8. Alten und neuen Commit protokollieren.
9. Bei geaendertem `pyproject.toml` Abhaengigkeiten im lokalen `.venv` aktualisieren.
10. Erforderliche Alembic-Migrationen nur melden, nicht automatisch ausfuehren (separater
    Adminschritt).
11. Smoke-Preflight ausfuehren.
12. Erfolg bzw. Fehler in `logs/xw_office_update.log` schreiben.
13. Optional (`-StartAfterUpdate`) nach Erfolg die GUI starten; wird vom automatischen Check in
    8.3 nicht gesetzt, da der Bootstrap den Start selbst uebernimmt.

Bei lokalen Aenderungen, falschem Branch oder nicht moeglichem Fast-forward wird nichts
automatisch gemergt, gestasht oder verworfen. Fuer den manuellen/administrativen Fall bleibt das
Skript direkt aus einer Konsole aufrufbar:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_xw_office.ps1
```

Eine eigene Startmenue-Verknuepfung dafuer gibt es bewusst nicht (mehr) — siehe 8.3.

### 8.3 Automatischer Update-Check vor dem normalen Start (umgesetzt)

Der fensterlose GUI-Bootstrap (`scripts\xw_office_gui.pyw`) prueft vor jedem normalen Start
lautlos, ob ein Update vorliegt, und bietet es per Dialog an:

```text
Eine neue Version von XeisWorks Office ist verfuegbar.
Jetzt aktualisieren (dauert meist nur wenige Sekunden)?
"Nein" startet die aktuelle Version unveraendert.
[Ja] [Nein]
```

Ablauf und Sicherheitsnetz:

- Branch muss `main` sein, Upstream muss `origin/main` sein, Arbeitsbaum muss sauber sein —
  jede Abweichung fuehrt zu einem lautlosen Ueberspringen, niemals zu einer Fehlermeldung beim
  Start. Das schuetzt insbesondere den VS-Code-Entwicklungs-PC: bei offenem Arbeitsbaum (der
  Normalfall waehrend aktiver Entwicklung) erscheint der Dialog gar nicht erst.
- `git fetch origin main` laeuft mit kurzem Timeout (Sekunden, nicht Minuten). Offline-Betrieb
  oder ein nicht erreichbares GitHub fuehren zu einem lautlosen Ueberspringen, nie zu einer
  Verzoegerung des Arbeitsstarts.
- Nur wenn Branch/Upstream/Arbeitsbaum sauber sind UND `origin/main` tatsaechlich neue Commits
  hat, erscheint der Ja/Nein-Dialog.
- "Ja" ruft `scripts\update_xw_office.ps1` auf (siehe 8.2, inkl. allem dort Beschriebenen:
  ff-only, Update-Log, Migrations-Warnung statt Automatik). Schlaegt das Update dennoch fehl,
  startet XeisWorks Office trotzdem mit der bisherigen, funktionierenden Version weiter — der
  Start wird nie dauerhaft blockiert.
- "Nein" startet sofort mit der aktuellen Version, ohne jede Aenderung.
- Explizit deaktivierbar per Umgebungsvariable `XW_OFFICE_SKIP_UPDATE_CHECK=1`, falls auf einem
  PC auch bei zufällig sauberem Arbeitsbaum nie automatisch geprueft werden soll.

Ein vollautomatischer, stiller Pull ohne Rueckfrage bei jedem Start bleibt bewusst
**nicht** umgesetzt: er wuerde die Verfuegbarkeit der App an GitHub koppeln, koennte einen
dringenden Arbeitsstart verzoegern und wuerde bei einer fehlerhaften neuen Version ohne Vorwarnung
durchschlagen. Die Kombination aus lautlosem Fail-open-Check plus expliziter Rueckfrage nur im
sicheren Fall vermeidet genau das, bei minimaler zusaetzlicher Reibung im Alltag.

### 8.4 Abhaengigkeiten und Migrationen

Reine Source-Aenderung:

```text
git pull --ff-only -> sofort startbar
```

Geaendertes `pyproject.toml`:

```text
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Geaenderte Datenbankmigrationen:

- nicht gleichzeitig unkoordiniert auf allen PCs starten,
- bevorzugt einmalig und bewusst von einem festgelegten Admin-/Entwicklungs-PC ausfuehren,
- Clientkompatibilitaet und Rollback vorher beurteilen,
- Migrationsergebnis protokollieren.

## 9. Multi-PC-Einrichtung

Pro PC bleibt ein eigener Checkout notwendig. Die dokumentierte Ersteinrichtung wird um einen
reproduzierbaren Setup-Schritt erweitert:

1. Repo auf `main` klonen.
2. `.venv` mit der freigegebenen Python-Version erzeugen.
3. `pip install -e ".[dev]"` ausfuehren.
4. lokale `.env`/Secrets konfigurieren.
5. notwendige PC-spezifische Drucker und Pfade konfigurieren.
6. Setup-Skript fuer Startmenue-Verknuepfungen ausfuehren.
7. normalen GUI-Start testen.
8. Debug-Start testen.
9. Logpfad pruefen.
10. Eintrag aus dem Startmenue manuell an die Taskleiste anheften.

Das Setup-Skript muss idempotent sein: erneutes Ausfuehren aktualisiert bestehende
Verknuepfungen, ohne Benutzerdaten oder das `.venv` zu loeschen.

Empfehlung fuer alle PCs:

- moeglichst gleicher Checkout-Pfad, aber keine harte Voraussetzung,
- immer lokaler Branch `main` mit Upstream `origin/main`,
- keine dauerhaften Arbeitsbranches auf Betriebs-PCs,
- Entwicklung mit offenen Aenderungen bevorzugt nur auf dem Entwicklungs-PC,
- feste Python-Major-/Minor-Version dokumentieren.

## 10. Geplante Dateien und Verantwortlichkeiten

Die genaue Benennung wird bei der Implementierung finalisiert. Voraussichtlich betroffen bzw. neu:

```text
src/xw_office/__main__.py
  regulaerer gemeinsamer App-Einstieg

src/xw_office/app.py
  Windows-App-Identitaet, App-Icon, Fehlerdialoge

src/xw_office/core/logging_setup.py
  console-abhaengige Handler, Rotation, fruehe Diagnose

src/xw_office/core/app_paths.py                  (neu)
  zentrale Aufloesung von Repo-, Log-, State- und Ressourcenpfaden

scripts/xw_office_gui.pyw                       (neu)
  schlanker fensterloser Bootstrap, inkl. automatischem Update-Check (Abschnitt 8.3)

scripts/setup_windows_shortcuts.ps1             (neu)
  Startmenue-/Desktop-Verknuepfungen pro PC (kein eigener Update-Eintrag mehr, siehe 6.3)

scripts/update_xw_office.ps1                    (neu)
  kontrolliertes Source-Update; wird automatisch vom GUI-Bootstrap sowie manuell/administrativ
  aus einer Konsole aufgerufen

run_xw_office_debug.cmd                         (neu/Umbenennung)
  sichtbarer Diagnose-Start

icons/xw_office.ico                             (neu)
  Windows-Multi-Resolution-Icon

docs/multi_pc_betriebsleitfaden.md
README.md
  korrigierter Start-, Setup- und Update-Ablauf
```

Der vorhandene `run_xw_office.cmd` kann waehrend einer Uebergangsphase bestehen bleiben und
spaeter entweder zum Debug-Launcher werden oder einen klaren Hinweis auf den neuen normalen Start
geben.

## 11. Tests und Abnahmekriterien

### 11.1 Start

- Normaler Start zeigt zu keinem Zeitpunkt ein Konsolenfenster.
- Das Qt-Hauptfenster erscheint maximiert wie bisher.
- Start funktioniert aus Startmenue, Taskleiste und Desktop-Verknuepfung.
- Ein abweichendes aktuelles Arbeitsverzeichnis beeinflusst Start und Logpfad nicht.
- Fehlendes/defektes `.venv` fuehrt zu einem verstaendlichen Dialog mit Logpfad.

### 11.2 Windows-Integration

- Eigenes Icon im Hauptfenster, Alt-Tab, Startmenue und in der Taskleiste.
- Keine Gruppierung mit fremden Python-/pythonw-Anwendungen.
- Angeheftetes Icon startet XW-Office auch nach einem normalen Git-Update.
- Setup-Skript funktioniert mit unterschiedlichen Benutzernamen und Checkout-Pfaden.

### 11.3 Logging

- Normale INFO-/WARNING-/ERROR-Records landen im Dateilog.
- Debug-Start zeigt dieselben Logging-Records zusaetzlich in der Konsole.
- Unbehandelte Exception nach Qt-Start erzeugt Dialog und Traceback im Log.
- Importfehler vor Qt-Start erzeugt Bootstrap-Log und sichtbare Fehlermeldung.
- Unterprozesse oeffnen im normalen GUI-Betrieb keine unerwarteten Konsolenfenster.
- Logs enthalten keine bekannten Secrets.
- Codex/Claude Code koennen den dokumentierten Pfad mit einem Befehl auslesen.

### 11.4 Updates

- Reine Python-Aenderung auf `origin/main` ist ohne Rebuild einspielbar.
- Update verweigert falschen Branch und schmutzigen Arbeitsbaum.
- Es findet kein Merge und kein Force-Push statt.
- Offline- oder GitHub-Fehler zerstoert die vorhandene lauffaehige Version nicht.
- Abhaengigkeitsfehler werden im Update-Log sichtbar.
- App wird nicht aktualisiert, waehrend sie laeuft.
- Datenbankmigrationen werden nicht unkoordiniert parallel von mehreren PCs ausgefuehrt.
- Automatischer Update-Check (verifiziert, siehe unten): erscheint nur bei sauberem Arbeitsbaum,
  Branch `main`, Upstream `origin/main` und tatsaechlich vorhandenem Update; ueberspringt sich in
  jedem anderen Fall lautlos, inklusive Offline-/Timeout-Fall.
- Automatischer Update-Check verzoegert den normalen Start im Nicht-Update-Fall nur um die kurzen
  Git-Check-Timeouts (keine spuerbare Wartezeit im Alltag), im Offline-Fall maximal um das
  Fetch-Timeout.
- Der GUI-Bootstrap-Prozess erkennt sich beim automatischen Aufruf des Updaters nicht
  faelschlich selbst als "App laeuft bereits" (eigene PID wird ausgeschlossen).
- `XW_OFFICE_SKIP_UPDATE_CHECK=1` deaktiviert den automatischen Check zuverlaessig.

### 11.5 Regression

- bestehende Unit- und UI-Tests laufen weiterhin,
- Druckerkennung und alle Druck-Backends funktionieren,
- Outlook-/COM-Unterprozesse funktionieren ohne Konsolenfenster,
- Themes, Icons, XSD- und JSON-Ressourcen werden weiterhin gefunden,
- `.env`, DB-Secrets und MSAL-Cache werden wie vorgesehen geladen.

## 12. Rollout-Reihenfolge

1. Umsetzung und Test auf dem VS-Code-Entwicklungs-PC.
2. Normalen und Debug-Start mehrere Tage parallel verwenden.
3. Update-Skript mit harmlosen Source-Aenderungen pruefen.
4. Einen zweiten Office-PC einrichten.
5. Erst danach den Druck-PC umstellen und alle Druckprofile testen.
6. Alten CMD-Start waehrend der Beobachtungsphase behalten.
7. Nach erfolgreicher Abnahme Doku auf den neuen Standard umstellen.

Rollback ist einfach: Die bestehende CMD-Startkette bleibt zunaechst erhalten. Falls der
fensterlose Start Probleme macht, kann unmittelbar wieder ueber den Debug-/Legacy-Launcher
gestartet werden, ohne Sourcecode oder Datenbestand zurueckzusetzen.

## 13. Spaetere Ausbauoptionen

Nicht Bestandteil der ersten Umsetzung:

- kompiliertes produktspezifisches Launcher-EXE,
- PyInstaller-`onedir`-Release,
- Installer und Deinstaller,
- signierte Windows-Binaries,
- zentraler Release-Feed mit Rollback,
- zentrale, PC-uebergreifende Logaggregation.

Der vorgeschlagene Umbau blockiert diese Optionen nicht. Die zentrale Pfad-, Logging- und
Windows-Identitaetsarbeit ist auch fuer ein spaeteres Bundle erforderlich und kann dann
weiterverwendet werden.

## 14. Endempfehlung

Der aktuelle Konsolenstart soll **nicht** unveraendert der normale Alltagsstart bleiben. Ebenso
soll die gesamte App derzeit **nicht** gebundelt werden.

Der angemessene Mittelweg fuer den aktuellen Entwicklungsrhythmus ist:

- Source-/Git-Checkout und `.venv` beibehalten,
- normal ueber `pythonw.exe` ohne Konsole starten,
- Windows-Icon und AppUserModelID setzen,
- Verknuepfungen pro PC reproduzierbar generieren,
- sichtbaren Debug-Start behalten,
- File-/Crash-Logging fuer den fensterlosen Betrieb haerten,
- Updates Fast-forward-only, mit automatischem lautlosem Check plus Rueckfrage vor dem
  Appstart (Abschnitt 8.3) statt eines separaten manuellen Startmenue-Eintrags.

Damit bleiben kleine woechentliche Updates genauso leicht wie heute, waehrend sich der normale
Betrieb deutlich mehr wie eine eigenstaendige Windows-Anwendung verhaelt — und das Aktuellhalten
passiert von selbst, ohne die Zuverlaessigkeit des taeglichen Starts zu gefaehrden.
