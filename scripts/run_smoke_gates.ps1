param(
    [string]$SmokeDbPath = $env:SMOKE_DB_PATH,
    [string]$SmokeProjectId = $env:SMOKE_PROJECT_ID
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot
$logsDir = Join-Path $repoRoot "build\\logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$smokeGateLog = Join-Path $logsDir "smoke_gate_latest.log"

$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing venv python at $python. Recreate .venv before running smoke gate."
}

if ([string]::IsNullOrWhiteSpace($SmokeDbPath)) {
    throw "SMOKE_DB_PATH is required. Example: .\\scripts\\run_smoke_gates.ps1 -SmokeDbPath 'J:\\tmp\\smoke_source.db'"
}

if (-not (Test-Path $SmokeDbPath)) {
    throw "SMOKE_DB_PATH not found: $SmokeDbPath"
}

$env:SMOKE_DB_PATH = (Resolve-Path $SmokeDbPath).Path
if (-not [string]::IsNullOrWhiteSpace($SmokeProjectId)) {
    $env:SMOKE_PROJECT_ID = $SmokeProjectId
}
$env:QT_QPA_PLATFORM = "offscreen"
$pytestTemp = Join-Path $repoRoot ".tmp_pytest_temp\\smoke"
New-Item -ItemType Directory -Force -Path $pytestTemp | Out-Null
$env:TEMP = $pytestTemp
$env:TMP = $pytestTemp

Write-Host "Using SMOKE_DB_PATH=$env:SMOKE_DB_PATH" -ForegroundColor Yellow
if ($env:SMOKE_PROJECT_ID) {
    Write-Host "Using SMOKE_PROJECT_ID=$env:SMOKE_PROJECT_ID" -ForegroundColor Yellow
}
Write-Host "Using TEMP/TMP=$pytestTemp" -ForegroundColor Yellow

Start-Transcript -Path $smokeGateLog -Force | Out-Null
try {
    & $python -m pytest -q tests/smoke -m "smoke and env" -vv
    if ($LASTEXITCODE -ne 0) {
        throw "Smoke gate failed (exit code: $LASTEXITCODE)"
    }

    Write-Host "PASS: Smoke/env gate completed." -ForegroundColor Green
} finally {
    Stop-Transcript | Out-Null
    Write-Host "Smoke gate log: $smokeGateLog" -ForegroundColor Yellow
}
