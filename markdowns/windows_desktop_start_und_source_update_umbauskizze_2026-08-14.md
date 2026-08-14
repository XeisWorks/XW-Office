# XW-Office: Windows-Desktop-Start und leichtes Source-Update

Stand: 2026-08-14
Status: Umbau-Skizze, noch keine Implementierung

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

Update:
separater, bewusst gestarteter Update-Weg
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
6. `xw_office.__main__.main()` bzw. den regulaeren App-Einstieg starten.
7. Fehler vor Erzeugung der `QApplication` in Datei schreiben und sichtbar melden.

Der Bootstrap darf keine zweite fachliche Startlogik entwickeln. Die eigentliche
Anwendungserzeugung bleibt in `xw_office.app.create_application()`.

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
- einen Startmenueeintrag `XeisWorks Office - Debug`,
- optional `XeisWorks Office aktualisieren`.

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

### 8.2 Empfohlener Update-Weg

Vorerst wird ein eigener, bewusst gestarteter Update-Einstieg empfohlen, statt eines versteckten
Updates in der laufenden GUI. Er kann als PowerShell-Skript implementiert und ueber eine
Startmenue-Verknuepfung aufgerufen werden. Ein sichtbares Fenster ist bei dieser Wartungsaktion
akzeptabel und hilfreich; der Alltagsstart bleibt fensterlos.

Der Updater prueft in dieser Reihenfolge:

1. Repo-Root eindeutig aufloesen.
2. Sicherstellen, dass XW-Office nicht laeuft.
3. `git status --porcelain` muss leer sein.
4. Aktueller Branch muss `main` sein.
5. Upstream muss `origin/main` sein.
6. `git fetch origin main`.
7. Nur `git pull --ff-only origin main` erlauben.
8. Alten und neuen Commit protokollieren.
9. Bei geaendertem `pyproject.toml` Abhaengigkeiten im lokalen `.venv` aktualisieren.
10. Erforderliche Alembic-Migrationen kontrolliert ausfuehren oder deutlich als separaten
    Adminschritt melden.
11. Smoke-Preflight ausfuehren.
12. Erfolg bzw. Fehler in `logs/xw_office_update.log` schreiben.
13. Optional nach Erfolg die GUI starten.

Bei lokalen Aenderungen, falschem Branch oder nicht moeglichem Fast-forward wird nichts
automatisch gemergt, gestasht oder verworfen.

### 8.3 Optionale spaetere Komfortstufe

Nach Stabilisierung kann der fensterlose Launcher vor dem Appstart lediglich feststellen, ob ein
Update vorhanden ist, und einen Dialog anbieten:

```text
Neue Version verfuegbar.
[Jetzt aktualisieren] [Diese Version starten] [Abbrechen]
```

Das eigentliche Update laeuft weiterhin vor dem Start der Haupt-App und schreibt ein eigenes Log.
Auf dem VS-Code-Entwicklungs-PC kann diese Pruefung deaktiviert werden, damit offene lokale
Aenderungen nicht stoeren.

Ein vollautomatischer Pull bei jedem Start wird vorerst nicht empfohlen. Er koppelt die
Verfuegbarkeit der App an GitHub, kann einen dringenden Arbeitsstart verzoegern und ist bei
lokalen Aenderungen oder einer fehlerhaften neuen Version unguenstig.

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

scripts/xw_office_gui.pyw                       (neu, moegliche Form)
  schlanker fensterloser Bootstrap

scripts/setup_windows_shortcuts.ps1             (neu)
  Startmenue-/Desktop-Verknuepfungen pro PC

scripts/update_xw_office.ps1                    (neu)
  kontrolliertes Source-Update vor Appstart

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
- Updates separat, bewusst und Fast-forward-only vor dem Appstart ausfuehren.

Damit bleiben kleine woechentliche Updates genauso leicht wie heute, waehrend sich der normale
Betrieb deutlich mehr wie eine eigenstaendige Windows-Anwendung verhaelt.
