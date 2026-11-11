[CmdletBinding()]
param(
    [string]$ProjectId = "b9ca5990-0aaf-4757-9efd-14119c1bdabf",
    [string]$EnvironmentName = "production",
    [string]$PythonExecutable = "",
    [string]$OutputDirectory = (Join-Path $env:TEMP "xw-inventory-cutover")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
    throw "Railway CLI wurde nicht gefunden. Bitte 'railway login' und die CLI-Installation prüfen."
}

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $projectPython) { $projectPython } else { "python" }
}
if (-not (Get-Command $PythonExecutable -ErrorAction SilentlyContinue) -and
    -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python interpreter '$PythonExecutable' was not found."
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$snapshotPath = Join-Path $OutputDirectory "inventory-snapshot-$stamp.json"
$dbReadinessPath = Join-Path $OutputDirectory "db-readiness-$stamp.json"
$runtimeReadinessPath = Join-Path $OutputDirectory "runtime-readiness-$stamp.json"

function Invoke-RailwayCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$CapturePath
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & railway @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $output | Set-Content -LiteralPath $CapturePath -Encoding UTF8
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = ($output -join [Environment]::NewLine)
    }
}

$health = Invoke-WebRequest -UseBasicParsing "https://products.xeisworks.at/health"
if ($health.StatusCode -ne 200) {
    throw "Product-Hub-Healthcheck liefert HTTP $($health.StatusCode)."
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $serviceTableJson = & railway service list --project $ProjectId --environment $EnvironmentName --json | Out-String
    $serviceListExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($serviceListExitCode -ne 0) {
    throw "Railway-Serviceinventar fehlgeschlagen (Exit $serviceListExitCode)."
}
$serviceTable = ConvertFrom-Json -InputObject $serviceTableJson
$serviceNames = @($serviceTable.name)
$services = @(
    for ($index = 0; $index -lt $serviceNames.Count; $index++) {
        [pscustomobject]@{
            name = $serviceTable.name[$index]
            id = $serviceTable.id[$index]
            status = $serviceTable.status[$index]
            deploymentId = $serviceTable.deploymentId[$index]
        }
    }
)
$postgresService = $services | Where-Object { $_.name -eq "Postgres" } | Select-Object -First 1
$productHubService = $services | Where-Object { $_.name -eq "XW-Product-Hub" } | Select-Object -First 1
if (-not $postgresService -or -not $productHubService) {
    throw "Postgres- oder XW-Product-Hub-Service wurde in Projekt '$ProjectId' / '$EnvironmentName' nicht gefunden."
}
$serviceSummary = @($services | ForEach-Object {
    [pscustomobject]@{
        Name = $_.name
        Status = $_.status
        DeploymentId = $_.deploymentId
    }
})

$snapshot = Invoke-RailwayCapture `
    -Arguments @(
        "run", "--project", $ProjectId, "--service", $postgresService.id, "--environment", $EnvironmentName, "--",
        $PythonExecutable, "scripts/product_hub/export_inventory_snapshot.py", "--out", $snapshotPath
    ) `
    -CapturePath (Join-Path $OutputDirectory "snapshot-command-$stamp.log")
if ($snapshot.ExitCode -ne 0) {
    throw "Inventory-Snapshot fehlgeschlagen (Exit $($snapshot.ExitCode)). Siehe snapshot-command-$stamp.log."
}

$dbReadiness = Invoke-RailwayCapture `
    -Arguments @(
        "run", "--project", $ProjectId, "--service", $postgresService.id, "--environment", $EnvironmentName, "--",
        $PythonExecutable, "scripts/product_hub/check_inventory_cutover.py", "--skip-runtime-configuration", "--json"
    ) `
    -CapturePath $dbReadinessPath

$runtimeReadiness = Invoke-RailwayCapture `
    -Arguments @(
        "run", "--project", $ProjectId, "--service", $productHubService.id, "--environment", $EnvironmentName, "--",
        $PythonExecutable, "scripts/product_hub/check_inventory_cutover.py", "--runtime-only", "--json"
    ) `
    -CapturePath $runtimeReadinessPath

$summary = [pscustomobject]@{
    checkedAt = (Get-Date).ToUniversalTime().ToString("o")
    healthStatus = $health.StatusCode
    services = $serviceSummary
    snapshot = $snapshotPath
    databaseReadiness = [pscustomobject]@{
        exitCode = $dbReadiness.ExitCode
        expectedBeforeInventory = ($dbReadiness.ExitCode -eq 2)
        report = $dbReadinessPath
    }
    runtimeReadiness = [pscustomobject]@{
        exitCode = $runtimeReadiness.ExitCode
        ready = ($runtimeReadiness.ExitCode -eq 0)
        report = $runtimeReadinessPath
    }
}

$summary | ConvertTo-Json -Depth 6
if ($runtimeReadiness.ExitCode -ne 0) {
    exit $runtimeReadiness.ExitCode
}
if ($dbReadiness.ExitCode -notin @(0, 2)) {
    exit $dbReadiness.ExitCode
}
