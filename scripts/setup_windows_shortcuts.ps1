<#
.SYNOPSIS
    Erzeugt oder aktualisiert die Windows-Start-Verknuepfungen fuer XW-Office auf diesem PC.

.DESCRIPTION
    Legt im Startmenue einen Ordner "XeisWorks Office" mit drei Verknuepfungen an:
      - XeisWorks Office               (fensterloser Alltagsstart ueber pythonw.exe)
      - XeisWorks Office - Debug       (sichtbare Diagnosekonsole)
      - XeisWorks Office aktualisieren (kontrolliertes Source-Update)
    Das Skript ist idempotent: wiederholtes Ausfuehren aktualisiert nur die
    Verknuepfungen, es werden weder Benutzerdaten noch das lokale .venv angefasst.

.PARAMETER IncludeDesktopShortcut
    Legt zusaetzlich eine Desktop-Verknuepfung fuer den normalen Alltagsstart an.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1
#>
[CmdletBinding()]
param(
    [switch]$IncludeDesktopShortcut
)

$ErrorActionPreference = 'Stop'

function New-XwShortcut {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$TargetPath,
        [string]$Arguments = '',
        [Parameter(Mandatory)] [string]$WorkingDirectory,
        [string]$IconLocation = '',
        [string]$Description = ''
    )
    $shortcut = $script:Shell.CreateShortcut($Path)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $WorkingDirectory
    if ($IconLocation) {
        $shortcut.IconLocation = $IconLocation
    }
    if ($Description) {
        $shortcut.Description = $Description
    }
    $shortcut.Save()
    Write-Host "Verknuepfung aktualisiert: $Path"
}

try {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $VenvPythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
    $GuiBootstrap = Join-Path $RepoRoot 'scripts\xw_office_gui.pyw'
    $DebugCmd = Join-Path $RepoRoot 'run_xw_office_debug.cmd'
    $UpdateScript = Join-Path $RepoRoot 'scripts\update_xw_office.ps1'
    $IconPath = Join-Path $RepoRoot 'icons\xw_office.ico'

    if (-not (Test-Path $VenvPythonw)) {
        Write-Error (
            "Lokales .venv nicht gefunden unter '$VenvPythonw'. " +
            "Bitte zuerst die Ersteinrichtung ausfuehren:`n" +
            "  python -m venv .venv`n" +
            "  .venv\Scripts\python.exe -m pip install -e "".[dev]"""
        )
    }
    if (-not (Test-Path $GuiBootstrap)) {
        Write-Error "GUI-Bootstrap nicht gefunden unter '$GuiBootstrap'."
    }

    $IconArg = ''
    if (Test-Path $IconPath) {
        $IconArg = "$IconPath,0"
    } else {
        Write-Warning "Icon nicht gefunden unter '$IconPath'. Verknuepfungen verwenden das Standard-Icon."
    }

    $StartMenuPrograms = [Environment]::GetFolderPath('Programs')
    $AppFolder = Join-Path $StartMenuPrograms 'XeisWorks Office'
    New-Item -ItemType Directory -Force -Path $AppFolder | Out-Null

    $script:Shell = New-Object -ComObject WScript.Shell

    New-XwShortcut -Path (Join-Path $AppFolder 'XeisWorks Office.lnk') `
        -TargetPath $VenvPythonw `
        -Arguments "`"$GuiBootstrap`"" `
        -WorkingDirectory $RepoRoot `
        -IconLocation $IconArg `
        -Description 'XeisWorks Office starten (ohne Konsolenfenster)'

    New-XwShortcut -Path (Join-Path $AppFolder 'XeisWorks Office - Debug.lnk') `
        -TargetPath $DebugCmd `
        -WorkingDirectory $RepoRoot `
        -IconLocation $IconArg `
        -Description 'XeisWorks Office mit sichtbarer Diagnosekonsole starten'

    if (Test-Path $UpdateScript) {
        New-XwShortcut -Path (Join-Path $AppFolder 'XeisWorks Office aktualisieren.lnk') `
            -TargetPath 'powershell.exe' `
            -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`"" `
            -WorkingDirectory $RepoRoot `
            -IconLocation $IconArg `
            -Description 'XeisWorks Office Source-Update ausfuehren (git fetch/pull --ff-only)'
    } else {
        Write-Warning "Update-Skript nicht gefunden unter '$UpdateScript', Verknuepfung wird uebersprungen."
    }

    if ($IncludeDesktopShortcut) {
        $Desktop = [Environment]::GetFolderPath('Desktop')
        New-XwShortcut -Path (Join-Path $Desktop 'XeisWorks Office.lnk') `
            -TargetPath $VenvPythonw `
            -Arguments "`"$GuiBootstrap`"" `
            -WorkingDirectory $RepoRoot `
            -IconLocation $IconArg `
            -Description 'XeisWorks Office starten (ohne Konsolenfenster)'
    }

    Write-Host ''
    Write-Host "Fertig. Startmenue-Ordner: $AppFolder"
    Write-Host 'Im Startmenue nach "XeisWorks Office" suchen, dann per Rechtsklick'
    Write-Host '"An Taskleiste anheften" auswaehlen.'
}
catch {
    Write-Error "Einrichtung der Verknuepfungen fehlgeschlagen: $($_.Exception.Message)"
    exit 1
}
