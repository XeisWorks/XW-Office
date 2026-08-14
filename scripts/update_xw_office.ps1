<#
.SYNOPSIS
    Kontrolliertes, bewusst gestartetes Source-Update fuer XW-Office (Fast-forward-only).

.DESCRIPTION
    Fuehrt die in markdowns\windows_desktop_start_und_source_update_umbauskizze_2026-08-14.md
    Abschnitt 8.2 beschriebene Update-Reihenfolge aus:
      1. Repo-Root aufloesen
      2. Pruefen, dass XW-Office nicht laeuft
      3. Sauberen Arbeitsbaum verlangen (git status --porcelain leer)
      4. Branch muss main sein
      5. Upstream muss origin/main sein
      6. git fetch origin main
      7. Nur git pull --ff-only origin main
      8. Alten/neuen Commit protokollieren
      9. Bei geaendertem pyproject.toml: pip install -e ".[dev]" im lokalen .venv
      10. Geaenderte Alembic-Migrationen nur melden, nicht automatisch ausfuehren
      11. Smoke-Preflight (Modul-Import im lokalen .venv)
      12. Ergebnis in logs\xw_office_update.log schreiben
      13. Optional (-StartAfterUpdate): GUI nach Erfolg starten
    Bei lokalen Aenderungen, falschem Branch oder nicht moeglichem Fast-Forward wird nichts
    automatisch gemergt, gestasht oder verworfen.

.PARAMETER StartAfterUpdate
    Startet nach einem erfolgreichen Update (oder wenn bereits aktuell) den normalen,
    fensterlosen GUI-Start.

.PARAMETER SkipRunningCheck
    Ueberspringt die Pruefung auf einen laufenden XW-Office-Prozess. Nur fuer den Fall,
    dass die Prozesserkennung auf einem PC nicht zuverlaessig funktioniert.

.PARAMETER ExcludeProcessId
    Schliesst eine einzelne Prozess-ID von der Laeuft-bereits-Pruefung aus. Wird vom
    fensterlosen GUI-Bootstrap (scripts\xw_office_gui.pyw) gesetzt, wenn dieser den
    automatischen Update-Check vor dem eigentlichen App-Start ausfuehrt: der Bootstrap-Prozess
    selbst zaehlt an dieser Stelle noch nicht als laufende App.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_xw_office.ps1
#>
[CmdletBinding()]
param(
    [switch]$StartAfterUpdate,
    [switch]$SkipRunningCheck,
    [int]$ExcludeProcessId = 0
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LogDir = Join-Path $RepoRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir 'xw_office_update.log'

function Write-UpdateLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Invoke-GitCapture {
    param([Parameter(Mandatory)] [string[]]$GitArgs)
    $output = & git -C $RepoRoot @GitArgs
    return [PSCustomObject]@{
        Output   = ($output | Out-String).Trim()
        ExitCode = $LASTEXITCODE
    }
}

function Stop-UpdateWithError {
    param([string]$Message)
    Write-UpdateLog "FEHLER: $Message"
    Write-Error $Message
    exit 1
}

Write-UpdateLog "Update gestartet. Repo: $RepoRoot"

# 2) Sicherstellen, dass XW-Office nicht laeuft.
if (-not $SkipRunningCheck) {
    try {
        $running = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object {
                $_.ProcessId -ne $ExcludeProcessId -and
                $_.CommandLine -and
                ($_.CommandLine -match [regex]::Escape($RepoRoot) -or $_.CommandLine -match 'xw_office')
            }
        if ($running) {
            $pids = ($running | Select-Object -ExpandProperty ProcessId) -join ', '
            Stop-UpdateWithError "XW-Office scheint noch zu laufen (PID $pids). Bitte App schliessen und Update erneut starten. Mit -SkipRunningCheck kann diese Pruefung uebersprungen werden."
        }
    }
    catch {
        Write-UpdateLog "WARNUNG: Laufende-Prozess-Pruefung nicht moeglich ($($_.Exception.Message)). Fahre fort."
    }
}

# 3) Sauberer Arbeitsbaum.
$status = Invoke-GitCapture -GitArgs @('status', '--porcelain')
if ($status.ExitCode -ne 0) {
    Stop-UpdateWithError "git status fehlgeschlagen: $($status.Output)"
}
if ($status.Output) {
    Stop-UpdateWithError "Lokale Aenderungen vorhanden. Bitte zuerst committen oder stashen:`n$($status.Output)"
}

# 4) Branch muss main sein.
$branch = Invoke-GitCapture -GitArgs @('rev-parse', '--abbrev-ref', 'HEAD')
if ($branch.ExitCode -ne 0 -or $branch.Output -ne 'main') {
    Stop-UpdateWithError "Aktueller Branch ist '$($branch.Output)', erwartet 'main'. Bitte 'git switch main' ausfuehren."
}

# 5) Upstream muss origin/main sein.
$upstream = Invoke-GitCapture -GitArgs @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
if ($upstream.ExitCode -ne 0 -or $upstream.Output -ne 'origin/main') {
    Stop-UpdateWithError "Upstream ist '$($upstream.Output)', erwartet 'origin/main'. Reparatur: git branch --set-upstream-to=origin/main main"
}

$oldCommit = (Invoke-GitCapture -GitArgs @('rev-parse', 'HEAD')).Output

# 6) Fetch.
Write-UpdateLog "git fetch origin main ..."
& git -C $RepoRoot fetch origin main
if ($LASTEXITCODE -ne 0) {
    Stop-UpdateWithError "git fetch origin main fehlgeschlagen (Exit-Code $LASTEXITCODE). Vorhandener Stand bleibt unveraendert."
}

$diffCheck = Invoke-GitCapture -GitArgs @('diff', '--quiet', 'HEAD', 'origin/main')
if ($diffCheck.ExitCode -eq 0) {
    Write-UpdateLog "Bereits aktuell auf origin/main ($oldCommit). Kein Update noetig."
    if ($StartAfterUpdate) {
        & "$RepoRoot\.venv\Scripts\pythonw.exe" "$RepoRoot\scripts\xw_office_gui.pyw"
    }
    exit 0
}

# 7) Nur Fast-forward.
Write-UpdateLog "Aenderungen gefunden. git pull --ff-only origin main ..."
& git -C $RepoRoot pull --ff-only origin main
if ($LASTEXITCODE -ne 0) {
    Stop-UpdateWithError "Fast-Forward nicht moeglich (Exit-Code $LASTEXITCODE). Es wurde nichts gemergt oder verworfen. Bitte Git-Stand manuell pruefen."
}

# 8) Alten/neuen Commit protokollieren.
$newCommit = (Invoke-GitCapture -GitArgs @('rev-parse', 'HEAD')).Output
Write-UpdateLog "Aktualisiert: $oldCommit -> $newCommit"

# 9) Abhaengigkeiten nur bei geaendertem pyproject.toml.
$pyprojectDiff = Invoke-GitCapture -GitArgs @('diff', '--name-only', $oldCommit, $newCommit, '--', 'pyproject.toml')
if ($pyprojectDiff.Output) {
    Write-UpdateLog "pyproject.toml geaendert, installiere Abhaengigkeiten neu ..."
    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        & $venvPython -m pip install -e "$RepoRoot[dev]" --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-UpdateLog "WARNUNG: pip install -e .[dev] ist mit Exit-Code $LASTEXITCODE fehlgeschlagen. Bitte manuell pruefen."
        } else {
            Write-UpdateLog "Abhaengigkeiten aktualisiert."
        }
    } else {
        Write-UpdateLog "WARNUNG: Kein lokales .venv unter '$venvPython' gefunden, Abhaengigkeiten wurden nicht installiert."
    }
}

# 10) Migrationen nur melden, nicht automatisch ausfuehren.
$migrationsDiff = Invoke-GitCapture -GitArgs @('diff', '--name-only', $oldCommit, $newCommit, '--', 'src/xw_office/migrations/versions')
if ($migrationsDiff.Output) {
    Write-UpdateLog "HINWEIS: Neue/geaenderte Datenbankmigrationen erkannt:"
    Write-UpdateLog $migrationsDiff.Output
    Write-UpdateLog (
        "Migrationen werden hier NICHT automatisch ausgefuehrt. Bitte 'alembic upgrade head' " +
        "bewusst und einmalig von einem festgelegten Admin-/Entwicklungs-PC ausfuehren (siehe " +
        "docs\multi_pc_betriebsleitfaden.md)."
    )
}

# 11) Smoke-Preflight.
$venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    Write-UpdateLog "Smoke-Preflight (Modul-Import) ..."
    & $venvPython -c "import xw_office.app"
    if ($LASTEXITCODE -ne 0) {
        Write-UpdateLog "WARNUNG: Smoke-Preflight fehlgeschlagen (Exit-Code $LASTEXITCODE). Code wurde bereits aktualisiert; bitte pruefen, bevor die App produktiv genutzt wird."
    } else {
        Write-UpdateLog "Smoke-Preflight erfolgreich."
    }
} else {
    Write-UpdateLog "WARNUNG: Kein lokales .venv gefunden, Smoke-Preflight uebersprungen."
}

Write-UpdateLog "Update abgeschlossen: $oldCommit -> $newCommit."

# 13) Optional GUI starten.
if ($StartAfterUpdate) {
    $pythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
    $gui = Join-Path $RepoRoot 'scripts\xw_office_gui.pyw'
    if ((Test-Path $pythonw) -and (Test-Path $gui)) {
        Write-UpdateLog "Starte XeisWorks Office ..."
        & $pythonw $gui
    }
}

exit 0
