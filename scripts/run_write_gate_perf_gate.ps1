param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$logsDir = Join-Path $repoRoot "build\logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$gateLog = Join-Path $logsDir "write_gate_perf_gate_latest.log"

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing venv python at $python. Recreate .venv before running perf gate."
}

$dbPath = "J:\Project_Vibe\V_book\build\bench\hewiki_sandbox.db"
if ($dbPath -like "M:\*") {
    Write-Error "Unsafe db-path for perf gate: $dbPath (M:\ is forbidden)"
    exit 1
}

if (-not (Test-Path $dbPath)) {
    $sourceDb = "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db"
    if (-not (Test-Path $sourceDb)) {
        Write-Error "Sandbox DB is missing and source copy not found: $sourceDb"
        exit 1
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dbPath) | Out-Null
    Copy-Item -Force $sourceDb $dbPath
}

$tmpDir = Join-Path $repoRoot "build\tmp\perf_gate"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$env:TEMP = $tmpDir
$env:TMP = $tmpDir

$exitCode = 0

Start-Transcript -Path $gateLog -Force | Out-Null
try {
    Write-Host "Using sandbox DB: $dbPath" -ForegroundColor Yellow
    Write-Host "Using TEMP/TMP: $tmpDir" -ForegroundColor Yellow

    1..3 | ForEach-Object {
        $idx = $_
        Write-Host "== Write-gate benchmark run $idx/3 ==" -ForegroundColor Cyan
        & $python "scripts/benchmark_import_concurrent_save.py" `
            "--db-path" $dbPath `
            "--copy-target" `
            "--seed-docs" "6000" `
            "--seed-lemmas" "120000" `
            "--lemma-batch-size" "2000" `
            "--save-cadence-ms" "100" `
            "--max-save-attempts" "100" `
            "--quick-check-timeout-sec" "5"
        if ($LASTEXITCODE -ne 0) {
            throw "Benchmark run $idx failed with exit code $LASTEXITCODE"
        }
    }

    Write-Host "== Write-gate budget checker ==" -ForegroundColor Cyan
    & $python "scripts/check_write_gate_budget.py" `
        "--take" "3" `
        "--glob" "build/logs/import_concurrent_save_metrics_*.json"
    $checkerExit = $LASTEXITCODE

    if ($checkerExit -eq 0) {
        Write-Host "PASS: write-gate perf budget is green." -ForegroundColor Green
        $exitCode = 0
    } elseif ($checkerExit -eq 2) {
        Write-Warning "WARN: write-gate perf budget is in warning band. See build\logs\write_gate_budget_report_latest.md"
        $exitCode = 2
    } elseif ($checkerExit -eq 1) {
        Write-Error "FAIL: write-gate perf budget failed. See build\logs\write_gate_budget_report_latest.md"
        $exitCode = 1
    } else {
        Write-Error "Unexpected checker exit code: $checkerExit"
        $exitCode = 1
    }
} finally {
    Stop-Transcript | Out-Null
    Write-Host "Perf gate log: $gateLog" -ForegroundColor Yellow
}

exit $exitCode
