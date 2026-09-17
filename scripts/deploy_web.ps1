<#
.SYNOPSIS
    Kontrollierter, PC-unabhaengiger Deploy-Weg fuer den XW-Product-Hub Railway-Service.

.DESCRIPTION
    Railway ist bereits so verbunden, dass jeder Push nach origin/main automatisch einen
    neuen Build/Deploy von Dockerfile.web fuer den Service "XW-Product-Hub" ausloest
    (siehe railway.toml). Dieses Skript macht diesen bestehenden Weg wiederholbar und
    ueberprueft nachvollziehbar, statt Schritte manuell nacheinander einzutippen:

      1. Branch/Upstream/sauberer Arbeitsbaum pruefen (wie scripts\update_xw_office.ps1) -
         es wird nichts automatisch committet, gemergt, gestasht oder verworfen.
      2. lokale main mit origin/main vergleichen (bei Rueckstand: Abbruch, kein Auto-Pull).
      3. Qualitaets-Gate lokal ausfuehren, exakt wie .github\workflows\ci.yml:
         ruff check src/, mypy src/ (weich, wie CI), pytest tests/.
      4. optional (-VerifyLeanWebImage): requirements-web.txt isoliert in einer
         Wegwerf-venv smoke-testen, damit ein fehlender Abhaengigkeitseintrag nicht erst
         im Railway-Build aufloegt.
      5. git push origin main (loest den bestehenden Railway-Webhook aus).
      6. Railway-CLI-Verfuegbarkeit pruefen; optional (-InstallMissingTools) automatisch
         ueber npm nachinstallieren.
      7. neues Deployment erkennen (andere ID als vor dem Push) und bis zu
         -WatchTimeoutMinutes auf einen Endzustand pollen, Ergebnis protokollieren.
      8. nur bei explizitem -Fallback und wenn nach dem Push kein neues Deployment
         erkannt wurde (z. B. Webhook blieb aus): "railway up" als manueller Ersatzweg.
         Ohne -Fallback wird der Befehl nur vorgeschlagen, nie automatisch ausgefuehrt.

    Datenbankmigrationen werden hier bewusst NICHT ausgefuehrt (siehe
    docs\web_deploy_betriebsleitfaden.md Abschnitt "Migrationen") - das bleibt ein
    separater, bewusst einzeln ausgeloester Schritt.

.PARAMETER SkipTests
    Ueberspringt pytest (ruff/mypy laufen weiterhin).

.PARAMETER SkipQualityChecks
    Ueberspringt ruff, mypy und pytest komplett (z. B. fuer reine Doku-Aenderungen).

.PARAMETER VerifyLeanWebImage
    Baut zusaetzlich eine Wegwerf-venv nur mit requirements-web.txt und importiert
    xw_office.web.app darin, um sicherzustellen, dass das schlanke Railway-Image
    tatsaechlich alles Noetige enthaelt. Dauert 1-2 Minuten, daher nicht Standard.

.PARAMETER InstallMissingTools
    Installiert eine fehlende Railway-CLI automatisch ueber npm, falls vorhanden.
    Ohne diesen Schalter wird eine fehlende CLI nur gemeldet.

.PARAMETER WatchTimeoutMinutes
    Wie lange nach dem Push auf ein neues, terminal abgeschlossenes Railway-Deployment
    gewartet wird. Default: 10 Minuten.

.PARAMETER Fallback
    Falls nach dem Push kein neues Deployment erkannt wird: loest explizit
    "railway up" als manuellen Ersatz-Deploy aus. Ohne diesen Schalter wird nur der
    Befehl vorgeschlagen.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_web.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_web.ps1 -VerifyLeanWebImage -Fallback
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipQualityChecks,
    [switch]$VerifyLeanWebImage,
    [switch]$InstallMissingTools,
    [int]$WatchTimeoutMinutes = 10,
    [switch]$Fallback
)

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LogDir = Join-Path $RepoRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir 'deploy_web.log'
$ServiceName = 'XW-Product-Hub'

function Write-DeployLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Stop-DeployWithError {
    param([string]$Message)
    Write-DeployLog "FEHLER: $Message"
    Write-Error $Message
    exit 1
}

function Invoke-GitCapture {
    param([Parameter(Mandatory)] [string[]]$GitArgs)
    $output = & git -C $RepoRoot @GitArgs
    return [PSCustomObject]@{
        Output   = ($output | Out-String).Trim()
        ExitCode = $LASTEXITCODE
    }
}

function Get-TopDeployment {
    # Erste Datenzeile von "railway deployment list" -> (Id, Status) oder $null.
    $lines = & railway deployment list --service $ServiceName 2>&1
    $top = $lines | Select-Object -Skip 1 -First 1
    if ($top -match '^\s*([0-9a-fA-F-]{36})\s*\|\s*(\S+)\s*\|') {
        return [PSCustomObject]@{ Id = $Matches[1]; Status = $Matches[2] }
    }
    return $null
}

Write-DeployLog "Deploy-Lauf gestartet fuer Service '$ServiceName'. Repo: $RepoRoot"

# 1) Branch muss main sein.
$branch = Invoke-GitCapture -GitArgs @('rev-parse', '--abbrev-ref', 'HEAD')
if ($branch.ExitCode -ne 0 -or $branch.Output -ne 'main') {
    Stop-DeployWithError "Aktueller Branch ist '$($branch.Output)', erwartet 'main'. Bitte 'git switch main' ausfuehren."
}

# 1b) Upstream muss origin/main sein.
$upstream = Invoke-GitCapture -GitArgs @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
if ($upstream.ExitCode -ne 0 -or $upstream.Output -ne 'origin/main') {
    Stop-DeployWithError "Upstream ist '$($upstream.Output)', erwartet 'origin/main'."
}

# 1c) Sauberer Arbeitsbaum - dieses Skript committet nichts selbst.
$status = Invoke-GitCapture -GitArgs @('status', '--porcelain')
if ($status.ExitCode -ne 0) {
    Stop-DeployWithError "git status fehlgeschlagen: $($status.Output)"
}
if ($status.Output) {
    Stop-DeployWithError "Lokale Aenderungen vorhanden. Bitte zuerst bewusst committen:`n$($status.Output)"
}

# 2) lokale main mit origin/main vergleichen (kein automatischer Merge/Pull).
Write-DeployLog "git fetch origin main ..."
& git -C $RepoRoot fetch origin main
if ($LASTEXITCODE -ne 0) {
    Stop-DeployWithError "git fetch origin main fehlgeschlagen (Exit-Code $LASTEXITCODE)."
}
$behindCheck = Invoke-GitCapture -GitArgs @('rev-list', '--count', 'HEAD..origin/main')
if ($behindCheck.ExitCode -eq 0 -and [int]$behindCheck.Output -gt 0) {
    Stop-DeployWithError "Lokale main liegt $($behindCheck.Output) Commit(s) hinter origin/main. Bitte zuerst 'git pull --ff-only origin main' (siehe scripts\update_xw_office.ps1)."
}
$aheadCheck = Invoke-GitCapture -GitArgs @('rev-list', '--count', 'origin/main..HEAD')
if ($aheadCheck.ExitCode -eq 0 -and [int]$aheadCheck.Output -eq 0) {
    Write-DeployLog "main ist bereits auf dem Stand von origin/main - nichts zu deployen. Beende."
    exit 0
}
Write-DeployLog "$($aheadCheck.Output) Commit(s) bereit zum Push."

# 3) Qualitaets-Gate (exakt wie .github\workflows\ci.yml).
$venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-DeployLog "WARNUNG: Kein lokales .venv unter '$venvPython' gefunden - verwende 'python' aus PATH."
    $venvPython = 'python'
}

if (-not $SkipQualityChecks) {
    Write-DeployLog "ruff check src/ ..."
    & $venvPython -m ruff check src/
    if ($LASTEXITCODE -ne 0) {
        Stop-DeployWithError "ruff meldet Fehler. Deploy abgebrochen."
    }

    Write-DeployLog "mypy src/ (weich, wie CI) ..."
    & $venvPython -m mypy src/
    if ($LASTEXITCODE -ne 0) {
        Write-DeployLog "WARNUNG: mypy meldet Fehler (Exit-Code $LASTEXITCODE). CI behandelt mypy als weich (continue-on-error) - Deploy laeuft weiter. Bitte trotzdem pruefen, ob die Fehler zu den eigenen Aenderungen gehoeren."
    }

    if (-not $SkipTests) {
        Write-DeployLog "pytest tests/ ..."
        & $venvPython -m pytest tests/ -q
        if ($LASTEXITCODE -ne 0) {
            Stop-DeployWithError "pytest meldet Fehler. Deploy abgebrochen."
        }
    } else {
        Write-DeployLog "pytest uebersprungen (-SkipTests)."
    }
} else {
    Write-DeployLog "Qualitaets-Gate komplett uebersprungen (-SkipQualityChecks)."
}

# 4) Optional: schlankes Web-Image isoliert smoke-testen.
if ($VerifyLeanWebImage) {
    Write-DeployLog "Pruefe requirements-web.txt isoliert (Wegwerf-venv) ..."
    $leanVenv = Join-Path $env:TEMP 'xw_web_lean_check'
    if (Test-Path $leanVenv) {
        Remove-Item -Recurse -Force $leanVenv
    }
    & $venvPython -m venv $leanVenv
    if ($LASTEXITCODE -ne 0) {
        Stop-DeployWithError "Wegwerf-venv konnte nicht erstellt werden."
    }
    $leanPython = Join-Path $leanVenv 'Scripts\python.exe'
    & $leanPython -m pip install --no-cache-dir -r (Join-Path $RepoRoot 'requirements-web.txt') --quiet
    if ($LASTEXITCODE -ne 0) {
        Stop-DeployWithError "pip install -r requirements-web.txt ist in der Wegwerf-venv fehlgeschlagen."
    }
    $env:PYTHONPATH = (Join-Path $RepoRoot 'src')
    & $leanPython -c "from xw_office.web.app import create_app, ContentWebSettings; create_app(ContentWebSettings(bootstrap_token='t', database_url='sqlite:///:memory:')); print('lean import OK')"
    $leanImportExit = $LASTEXITCODE
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $leanVenv -ErrorAction SilentlyContinue
    if ($leanImportExit -ne 0) {
        Stop-DeployWithError "xw_office.web.app importiert nicht mit nur requirements-web.txt installiert. Deploy abgebrochen - Dockerfile.web wuerde vermutlich ebenfalls fehlschlagen."
    }
    Write-DeployLog "Schlankes Web-Image bestaetigt lauffaehig."
}

# 5) Railway-CLI pruefen.
$railwayCmd = Get-Command railway -ErrorAction SilentlyContinue
if (-not $railwayCmd) {
    if ($InstallMissingTools) {
        Write-DeployLog "Railway-CLI fehlt, installiere ueber npm ..."
        $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
        if (-not $npmCmd) {
            Write-DeployLog "WARNUNG: npm nicht gefunden. Railway-CLI kann nicht automatisch installiert werden. Siehe https://docs.railway.com/guides/cli fuer alternative Installationswege."
        } else {
            & npm install -g '@railway/cli'
            $railwayCmd = Get-Command railway -ErrorAction SilentlyContinue
        }
    } else {
        Write-DeployLog "HINWEIS: Railway-CLI nicht gefunden. Deployment-Ueberwachung nach dem Push wird uebersprungen. Installation: 'npm install -g @railway/cli' oder mit -InstallMissingTools."
    }
}

# 6) Vor dem Push: bekannte letzte Deployment-ID merken (fuer 'neu vs. alt'-Erkennung).
$knownDeploymentId = $null
if ($railwayCmd) {
    try {
        $before = Get-TopDeployment
        if ($before) {
            $knownDeploymentId = $before.Id
        }
    } catch {
        Write-DeployLog "WARNUNG: Railway-Deployment-Liste vor dem Push nicht lesbar: $($_.Exception.Message)"
    }
}

# 7) Push - loest den bestehenden Railway-Webhook aus.
Write-DeployLog "git push origin main ..."
& git -C $RepoRoot push origin main
if ($LASTEXITCODE -ne 0) {
    Stop-DeployWithError "git push origin main fehlgeschlagen (Exit-Code $LASTEXITCODE)."
}
$pushedCommit = (Invoke-GitCapture -GitArgs @('rev-parse', 'HEAD')).Output
Write-DeployLog "Gepusht: $pushedCommit"

if (-not $railwayCmd) {
    Write-DeployLog "Railway-CLI nicht verfuegbar - bitte Deploy-Status manuell im Railway-Dashboard pruefen."
    exit 0
}

# 8) Auf neues, terminal abgeschlossenes Deployment warten.
Write-DeployLog "Warte bis zu $WatchTimeoutMinutes Minute(n) auf ein neues Deployment fuer '$ServiceName' ..."
$deadline = (Get-Date).AddMinutes($WatchTimeoutMinutes)
$newDeploymentId = $null
$finalStatus = $null
$inProgressStatuses = @('QUEUED', 'BUILDING', 'DEPLOYING', 'INITIALIZING', 'WAITING', '')

while ((Get-Date) -lt $deadline) {
    $top = Get-TopDeployment
    if ($top -and $top.Id -ne $knownDeploymentId) {
        $newDeploymentId = $top.Id
        if ($top.Status -notin $inProgressStatuses) {
            $finalStatus = $top.Status
            break
        }
    }
    Start-Sleep -Seconds 15
}

if ($finalStatus -eq 'SUCCESS') {
    Write-DeployLog "Deployment $newDeploymentId erfolgreich (SUCCESS)."
    exit 0
} elseif ($finalStatus) {
    Stop-DeployWithError "Neues Deployment $newDeploymentId hat Status '$finalStatus'. Bitte 'railway logs --build $newDeploymentId' und 'railway logs --deployment $newDeploymentId' pruefen."
} elseif ($newDeploymentId) {
    Write-DeployLog "WARNUNG: Deployment $newDeploymentId nach $WatchTimeoutMinutes Minute(n) noch nicht abgeschlossen. Bitte Railway-Dashboard pruefen."
    exit 0
} else {
    Write-DeployLog "WARNUNG: Kein neues Deployment innerhalb von $WatchTimeoutMinutes Minute(n) erkannt - der GitHub-Webhook koennte ausgeblieben sein."
    if ($Fallback) {
        Write-DeployLog "Loese manuellen Ersatz-Deploy aus: 'railway up' (-Fallback wurde gesetzt) ..."
        & railway up --service $ServiceName --detach
        if ($LASTEXITCODE -ne 0) {
            Stop-DeployWithError "'railway up' ist fehlgeschlagen (Exit-Code $LASTEXITCODE)."
        }
        Write-DeployLog "'railway up' ausgeloest. Status bitte im Railway-Dashboard oder mit 'railway deployment list --service $ServiceName' verfolgen."
    } else {
        Write-DeployLog "Manueller Ersatzweg (nicht automatisch ausgefuehrt): powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_web.ps1 -Fallback   (oder direkt: railway up --service $ServiceName)"
    }
    exit 0
}
