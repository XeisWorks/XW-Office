<#
.SYNOPSIS
    Erzeugt oder aktualisiert die Windows-Start-Verknuepfungen fuer XW-Office auf diesem PC.

.DESCRIPTION
    Legt im Startmenue einen Ordner "XeisWorks Office" mit drei Verknuepfungen an:
      - XeisWorks Office         (fensterloser Alltagsstart ueber pythonw.exe)
      - XeisWorks Office - Debug (sichtbare Diagnosekonsole)
      - XeisWorks Druckcenter    (separates Druckfenster ohne Office-Navigation)
    Der normale Start prueft beim Start automatisch und ohne zu blockieren, ob ein
    Source-Update vorliegt, und bietet es bei Bedarf per Dialog an (siehe
    scripts\xw_office_gui.pyw). Eine eigene Verknuepfung "XeisWorks Office aktualisieren"
    ist deshalb nicht mehr noetig; eine bereits vorhandene alte Verknuepfung dieses Namens
    wird beim Ausfuehren entfernt. scripts\update_xw_office.ps1 bleibt fuer manuelle bzw.
    administrative Ausfuehrung direkt aufrufbar.
    Das Skript ist idempotent: wiederholtes Ausfuehren aktualisiert nur die
    Verknuepfungen, es werden weder Benutzerdaten noch das lokale .venv angefasst.
    Eine vorhandene angeheftete Office-Verknuepfung wird ebenfalls aktualisiert.
    Alte Debug-Anheftungen werden auf den fensterlosen Alltagsstart umgestellt;
    der Debug-Start bleibt separat im Startmenue verfuegbar.

.PARAMETER IncludeDesktopShortcut
    Legt Desktop-Verknuepfungen fuer Office und Druckcenter an. Eine vorhandene
    Office-Desktop-Verknuepfung wird auch ohne diesen Schalter aktualisiert.

.PARAMETER PrintCenterOnly
    Aktualisiert nur Druckcenter-Verknuepfungen, ohne Office-Verknuepfungen anzufassen.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1
#>
[CmdletBinding()]
param(
    [switch]$IncludeDesktopShortcut,
    [switch]$PrintCenterOnly
)

$ErrorActionPreference = 'Stop'
$script:OfficeAppUserModelId = 'at.xeisworks.xwoffice'
$script:OfficeDebugAppUserModelId = 'at.xeisworks.xwoffice.debug'
$script:PrintCenterAppUserModelId = 'at.xeisworks.printcenter'

if (-not ('XwShortcutIdentity' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct XwPropertyKey
{
    public Guid FormatId;
    public uint PropertyId;
}

[StructLayout(LayoutKind.Explicit)]
public struct XwPropVariant
{
    [FieldOffset(0)] public ushort VariantType;
    [FieldOffset(8)] public IntPtr Value;
}

[ComImport]
[Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface XwPropertyStore
{
    void GetCount(out uint propertyCount);
    void GetAt(uint propertyIndex, out XwPropertyKey key);
    void GetValue(ref XwPropertyKey key, IntPtr value);
    void SetValue(ref XwPropertyKey key, ref XwPropVariant value);
    void Commit();
}

public static class XwShortcutIdentity
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void SHGetPropertyStoreFromParsingName(
        string path,
        IntPtr bindingContext,
        uint flags,
        ref Guid interfaceId,
        out XwPropertyStore propertyStore);

    [DllImport("shell32.dll", PreserveSig = true)]
    private static extern void SHChangeNotify(
        uint eventId, uint flags, IntPtr item1, IntPtr item2);

    public static void NotifyShellChanges()
    {
        SHChangeNotify(0x08000000, 0, IntPtr.Zero, IntPtr.Zero);
    }

    public static void SetAppUserModelId(string shortcutPath, string appUserModelId)
    {
        Guid interfaceId = typeof(XwPropertyStore).GUID;
        XwPropertyStore propertyStore;
        SHGetPropertyStoreFromParsingName(
            shortcutPath, IntPtr.Zero, 2, ref interfaceId, out propertyStore);

        XwPropertyKey key = new XwPropertyKey
        {
            FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
            PropertyId = 5
        };
        XwPropVariant value = new XwPropVariant
        {
            VariantType = 31,
            Value = Marshal.StringToCoTaskMemUni(appUserModelId)
        };
        try
        {
            propertyStore.SetValue(ref key, ref value);
            propertyStore.Commit();
        }
        finally
        {
            Marshal.FreeCoTaskMem(value.Value);
            Marshal.ReleaseComObject(propertyStore);
        }
    }
}
'@
}

function New-XwShortcut {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$TargetPath,
        [string]$Arguments = '',
        [Parameter(Mandatory)] [string]$WorkingDirectory,
        [string]$IconLocation = '',
        [string]$Description = '',
        [string]$AppUserModelId = ''
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
    if ($AppUserModelId) {
        [XwShortcutIdentity]::SetAppUserModelId($Path, $AppUserModelId)
    }
    Write-Host "Verknuepfung aktualisiert: $Path"
}

try {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $VenvPythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
    $GuiBootstrap = Join-Path $RepoRoot 'scripts\xw_office_gui.pyw'
    $PrintCenterBootstrap = Join-Path $RepoRoot 'scripts\xw_print_center_gui.pyw'
    $DebugCmd = Join-Path $RepoRoot 'run_xw_office_debug.cmd'
    $IconPath = Join-Path $RepoRoot 'icons\xw_office.ico'
    $PrintCenterIconPath = Join-Path $RepoRoot 'icons\print_center.ico'
    $Desktop = [Environment]::GetFolderPath('Desktop')
    $OfficeDesktopShortcut = Join-Path $Desktop 'XeisWorks Office.lnk'

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

    if (-not (Test-Path $IconPath)) {
        throw "Office-Icon nicht gefunden unter '$IconPath'."
    }
    $IconArg = "$IconPath,0"

    $StartMenuPrograms = [Environment]::GetFolderPath('Programs')
    $AppFolder = Join-Path $StartMenuPrograms 'XeisWorks Office'
    New-Item -ItemType Directory -Force -Path $AppFolder | Out-Null

    $script:Shell = New-Object -ComObject WScript.Shell

    if (-not (Test-Path $PrintCenterBootstrap)) {
        throw "Druckcenter-Bootstrap nicht gefunden unter '$PrintCenterBootstrap'."
    }
    if (-not (Test-Path $PrintCenterIconPath)) {
        throw "Druckcenter-Icon nicht gefunden unter '$PrintCenterIconPath'."
    }
    $PrintCenterIconArg = "$PrintCenterIconPath,0"
    New-XwShortcut -Path (Join-Path $AppFolder 'XeisWorks Druckcenter.lnk') `
        -TargetPath $VenvPythonw `
        -Arguments "`"$PrintCenterBootstrap`"" `
        -WorkingDirectory $RepoRoot `
        -IconLocation $PrintCenterIconArg `
        -AppUserModelId $script:PrintCenterAppUserModelId `
        -Description 'Druckcenter: offizielle Produkte lesen und eigene Druckartikel verwalten'
    if ($IncludeDesktopShortcut) {
        New-XwShortcut -Path (Join-Path $Desktop 'XeisWorks Druckcenter.lnk') `
            -TargetPath $VenvPythonw `
            -Arguments "`"$PrintCenterBootstrap`"" `
            -WorkingDirectory $RepoRoot `
            -IconLocation $PrintCenterIconArg `
            -AppUserModelId $script:PrintCenterAppUserModelId `
            -Description 'XeisWorks Druckcenter ohne die Office-Oberflaeche starten'
    }
    if ($PrintCenterOnly) {
        Write-Host 'Druckcenter-Verknuepfungen eingerichtet.'
        exit 0
    }

    New-XwShortcut -Path (Join-Path $AppFolder 'XeisWorks Office.lnk') `
        -TargetPath $VenvPythonw `
        -Arguments "`"$GuiBootstrap`"" `
        -WorkingDirectory $RepoRoot `
        -IconLocation $IconArg `
        -AppUserModelId $script:OfficeAppUserModelId `
        -Description 'XeisWorks Office starten (ohne Konsolenfenster)'

    New-XwShortcut -Path (Join-Path $AppFolder 'XeisWorks Office - Debug.lnk') `
        -TargetPath $DebugCmd `
        -WorkingDirectory $RepoRoot `
        -IconLocation $IconArg `
        -AppUserModelId $script:OfficeDebugAppUserModelId `
        -Description 'XeisWorks Office mit sichtbarer Diagnosekonsole starten'

    $OldUpdateShortcut = Join-Path $AppFolder 'XeisWorks Office aktualisieren.lnk'
    if (Test-Path $OldUpdateShortcut) {
        Remove-Item -Path $OldUpdateShortcut -Force
        Write-Host "Alte Verknuepfung entfernt (durch automatischen Update-Check ersetzt): $OldUpdateShortcut"
    }

    if ($IncludeDesktopShortcut -or (Test-Path $OfficeDesktopShortcut)) {
        New-XwShortcut -Path $OfficeDesktopShortcut `
            -TargetPath $VenvPythonw `
            -Arguments "`"$GuiBootstrap`"" `
            -WorkingDirectory $RepoRoot `
            -IconLocation $IconArg `
            -AppUserModelId $script:OfficeAppUserModelId `
            -Description 'XeisWorks Office starten (ohne Konsolenfenster)'
    }

    $TaskbarPinFolder = Join-Path ([Environment]::GetFolderPath('ApplicationData')) `
        'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
    $script:UpdatedOfficePins = 0
    if (Test-Path $TaskbarPinFolder) {
        Get-ChildItem -Path $TaskbarPinFolder -Filter '*.lnk' -File | ForEach-Object {
            $pinnedShortcut = $script:Shell.CreateShortcut($_.FullName)
            if ($pinnedShortcut.Arguments -like '*xw_office_gui.pyw*' -or
                $pinnedShortcut.TargetPath -eq $DebugCmd) {
                New-XwShortcut -Path $_.FullName `
                    -TargetPath $VenvPythonw `
                    -Arguments "`"$GuiBootstrap`"" `
                    -WorkingDirectory $RepoRoot `
                    -IconLocation $IconArg `
                    -AppUserModelId $script:OfficeAppUserModelId `
                    -Description 'XeisWorks Office starten (ohne Konsolenfenster)'
                $script:UpdatedOfficePins++
                Write-Host "Angeheftete Office-Verknuepfung aktualisiert: $($_.FullName)"
            }
        }
    }
    if ($script:UpdatedOfficePins -eq 0) {
        Write-Warning (
            'Keine angeheftete Office-Verknuepfung gefunden. ' +
            'Falls das Taskleisten-Symbol weiter falsch aussieht, die alte Anheftung ' +
            'entfernen und "XeisWorks Office" erneut aus dem Startmenue anheften.'
        )
    }
    [XwShortcutIdentity]::NotifyShellChanges()

    Write-Host ''
    Write-Host "Fertig. Startmenue-Ordner: $AppFolder"
    Write-Host 'Im Startmenue nach "XeisWorks Office" suchen, dann per Rechtsklick'
    Write-Host '"An Taskleiste anheften" auswaehlen.'
}
catch {
    Write-Error "Einrichtung der Verknuepfungen fehlgeschlagen: $($_.Exception.Message)"
    exit 1
}
