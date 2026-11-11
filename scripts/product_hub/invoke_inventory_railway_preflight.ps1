[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $env:TEMP "xw-inventory-cutover")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
    throw "Railway CLI wurde nicht gefunden. Bitte 'railway login' und die CLI-Installation prüfen."
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

    $output = & railway @Arguments 2>&1
    $exitCode = $LASTEXITCODE
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

$services = (& railway service list --json | ConvertFrom-Json)
$serviceSummary = @($services | ForEach-Object {
    [pscustomobject]@{
        Name = $_.name
        Status = $_.status
        DeploymentId = $_.deploymentId
    }
})

$snapshot = Invoke-RailwayCapture `
    -Arguments @(
        "run", "--service", "Postgres", "--environment", "production", "--",
        "python", "scripts/product_hub/export_inventory_snapshot.py", "--out", $snapshotPath
    ) `
    -CapturePath (Join-Path $OutputDirectory "snapshot-command-$stamp.log")
if ($snapshot.ExitCode -ne 0) {
    throw "Inventory-Snapshot fehlgeschlagen (Exit $($snapshot.ExitCode)). Siehe snapshot-command-$stamp.log."
}

$dbReadiness = Invoke-RailwayCapture `
    -Arguments @(
        "run", "--service", "Postgres", "--environment", "production", "--",
        "python", "scripts/product_hub/check_inventory_cutover.py", "--skip-runtime-configuration", "--json"
    ) `
    -CapturePath $dbReadinessPath

$runtimeReadiness = Invoke-RailwayCapture `
    -Arguments @(
        "run", "--service", "XW-Product-Hub", "--environment", "production", "--",
        "python", "scripts/product_hub/check_inventory_cutover.py", "--runtime-only", "--json"
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
