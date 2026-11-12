[CmdletBinding()]
param(
    [string]$ProjectId = "b9ca5990-0aaf-4757-9efd-14119c1bdabf",
    [string]$EnvironmentName = "production",
    [string]$PythonExecutable = "",
    [string]$OutputDirectory = (Join-Path $env:TEMP "xw-inventory-cutover"),
    [switch]$IncludeExactMappingSummary
)

$ErrorActionPreference = "Stop"
# PowerShell 7 can promote a non-zero native exit code to a terminating
# exception when this preference is enabled.  The preflight intentionally
# accepts DB-readiness exit code 2 before the physical inventory, so keep
# native Railway exit codes data that we inspect explicitly below.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

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
$mappingSummaryPath = Join-Path $OutputDirectory "exact-mapping-summary-$stamp.json"

function Invoke-RailwayCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$CapturePath
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $previousNativeCommandPreference = $null
    $ErrorActionPreference = "Continue"
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $previousNativeCommandPreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $output = & railway @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($null -ne $previousNativeCommandPreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativeCommandPreference
        }
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
$workerService = $services | Where-Object { $_.name -eq "xw-inventory-worker" } | Select-Object -First 1
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

$mappingSummary = $null
if ($IncludeExactMappingSummary) {
    if (-not $workerService) {
        throw "Der optionale Exact-Mapping-Preflight benötigt den Service 'xw-inventory-worker'."
    }
    # railway run executes locally with the selected service's variables.  The
    # worker's DATABASE_URL is private-only and therefore cannot be resolved by
    # this runner.  Combine the worker's sevDesk token with Postgres' public URL
    # in process memory, then run the read-only preview locally.  Secret values
    # never enter logs, arguments, snapshots or the returned summary.
    $previousErrorActionPreference = $ErrorActionPreference
    $previousNativeCommandPreference = $null
    $ErrorActionPreference = "Continue"
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $previousNativeCommandPreference = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        # Keep the variable payload in memory only.  Do not redirect it to a
        # report file because this response contains secrets.
        $workerVariablesJson = & railway variable list --project $ProjectId --service $workerService.id --environment $EnvironmentName --json | Out-String
        $workerVariablesExitCode = $LASTEXITCODE
        $postgresVariablesJson = & railway variable list --project $ProjectId --service $postgresService.id --environment $EnvironmentName --json | Out-String
        $postgresVariablesExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($null -ne $previousNativeCommandPreference) {
            $PSNativeCommandUseErrorActionPreference = $previousNativeCommandPreference
        }
    }
    if ($workerVariablesExitCode -ne 0 -or $postgresVariablesExitCode -ne 0) {
        throw "Railway-Variablen konnten fuer den Exact-Mapping-Preflight nicht gelesen werden."
    }
    $workerVariables = ConvertFrom-Json -InputObject $workerVariablesJson
    $postgresVariables = ConvertFrom-Json -InputObject $postgresVariablesJson
    $mappingDatabaseUrl = [string]$postgresVariables.DATABASE_PUBLIC_URL
    if ([string]::IsNullOrWhiteSpace($mappingDatabaseUrl)) {
        $mappingDatabaseUrl = [string]$postgresVariables.DATABASE_URL
    }
    $mappingSevdeskToken = [string]$workerVariables.SEVDESK_API_TOKEN
    if ([string]::IsNullOrWhiteSpace($mappingDatabaseUrl) -or [string]::IsNullOrWhiteSpace($mappingSevdeskToken)) {
        throw "Exact-Mapping-Preflight benÃ¶tigt eine Postgres-Public-URL und SEVDESK_API_TOKEN."
    }
    $previousDatabaseUrl = $env:DATABASE_URL
    $previousSevdeskToken = $env:SEVDESK_API_TOKEN
    try {
        $env:DATABASE_URL = $mappingDatabaseUrl
        $env:SEVDESK_API_TOKEN = $mappingSevdeskToken
        $mappingOutput = & $PythonExecutable "scripts/product_hub/preview_exact_inventory_mappings.py" "--summary" 2>&1
        $mappingExitCode = $LASTEXITCODE
    }
    finally {
        if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
        else { $env:DATABASE_URL = $previousDatabaseUrl }
        if ($null -eq $previousSevdeskToken) { Remove-Item Env:SEVDESK_API_TOKEN -ErrorAction SilentlyContinue }
        else { $env:SEVDESK_API_TOKEN = $previousSevdeskToken }
    }
    $mappingOutput | Set-Content -LiteralPath $mappingSummaryPath -Encoding UTF8
    $mappingSummary = [pscustomobject]@{ ExitCode = $mappingExitCode; Output = ($mappingOutput -join [Environment]::NewLine) }
}

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
if ($IncludeExactMappingSummary) {
    $summary | Add-Member -NotePropertyName exactMappingSummary -NotePropertyValue ([pscustomobject]@{
        exitCode = $mappingSummary.ExitCode
        ready = ($mappingSummary.ExitCode -eq 0)
        report = $mappingSummaryPath
    })
}

$summary | ConvertTo-Json -Depth 6
if ($runtimeReadiness.ExitCode -ne 0) {
    exit $runtimeReadiness.ExitCode
}
if ($dbReadiness.ExitCode -notin @(0, 2)) {
    exit $dbReadiness.ExitCode
}
if ($IncludeExactMappingSummary -and $mappingSummary.ExitCode -ne 0) {
    exit $mappingSummary.ExitCode
}
