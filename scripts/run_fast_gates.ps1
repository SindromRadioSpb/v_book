param(
    [switch]$SkipPrebuild
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing venv python at $python. Recreate .venv before running gates."
}

$env:QT_QPA_PLATFORM = "offscreen"
$pytestTemp = Join-Path $repoRoot ".tmp_pytest_temp"
New-Item -ItemType Directory -Force -Path $pytestTemp | Out-Null
$env:TEMP = $pytestTemp
$env:TMP = $pytestTemp

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Host "== $Name ==" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed (exit code: $LASTEXITCODE)"
    }
    Write-Host "[OK] $Name" -ForegroundColor Green
}

if (-not $SkipPrebuild) {
    Invoke-Step -Name "Prebuild validate (skip export/import)" -Action {
        & $python "scripts/prebuild_validate.py" "--skip-export-import"
    }
}

Invoke-Step -Name "Pytest fast gate (exclude smoke/env)" -Action {
    & $python -m pytest -q `
        tests/test_security.py `
        tests/test_task12_fts_nlp.py `
        tests/test_task13_trigger_sync.py `
        tests/test_db_retry.py `
        tests/test_sqlite_busy_retry.py `
        tests/test_write_gate.py `
        tests/test_translation_admin_write_gate.py `
        tests/test_import_chunking_write_gate.py `
        tests/test_db_migration_lock_path.py `
        -m "not smoke and not env"
}

Write-Host "PASS: Variant A fast gate is green." -ForegroundColor Green
