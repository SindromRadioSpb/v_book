param(
    [string]$ArtifactsGlob = "build/logs/pipeline_bench_metrics_*.json",
    [int]$Take = 20,
    [string]$SandboxDbPath = "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$logsDir = Join-Path $repoRoot "build\logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$gateLog = Join-Path $logsDir "pipeline_perf_gate_latest.log"

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing venv python at $python. Recreate .venv before running perf gate."
}

if ($SandboxDbPath -like "M:\*") {
    Write-Error "Unsafe sandbox DB path: $SandboxDbPath (M:\ is forbidden)"
    exit 1
}
if ($SandboxDbPath -notlike "J:\*") {
    Write-Error "Sandbox DB path must stay on J:\ for local perf safety: $SandboxDbPath"
    exit 1
}

$exitCode = 0

Start-Transcript -Path $gateLog -Force | Out-Null
try {
    Write-Host "== Pipeline stage budget checker ==" -ForegroundColor Cyan
    Write-Host "Using artifact glob: $ArtifactsGlob" -ForegroundColor Yellow
    Write-Host "Using take: $Take" -ForegroundColor Yellow
    Write-Host "Sandbox DB safety path (no execution by default): $SandboxDbPath" -ForegroundColor Yellow

    $selectedArtifacts = & $python -c @"
import glob
import json
import re
from pathlib import Path

glob_pat = r'''$ArtifactsGlob'''
take = int($Take)
required = ('extract_terms', 'niqqud_bootstrap', 'translate_bootstrap')
rx = re.compile(r'^pipeline_bench_metrics_(\d{8}_\d{6})\.json$')

paths = []
for raw in glob.glob(glob_pat):
    p = Path(raw).resolve()
    m = rx.match(p.name)
    if not m:
        continue
    paths.append((m.group(1), p))
paths.sort(key=lambda it: it[0])
if take > 0 and len(paths) > take:
    paths = paths[-take:]

latest = {}
for _, p in paths:
    try:
        payload = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        continue
    stages = payload.get('stages')
    if not isinstance(stages, list) or not stages:
        continue
    stage = stages[0] if isinstance(stages[0], dict) else {}
    name = str(stage.get('name') or '').strip()
    if name not in required:
        continue
    if str(payload.get('overall_status') or '').lower() != 'pass':
        continue
    if str(stage.get('status') or '').lower() != 'ok':
        continue
    latest[name] = str(p)

for stage_name in required:
    value = latest.get(stage_name)
    if value:
        print(value)
"@
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to select stage artifacts for pipeline budget checker."
    }

    $artifactList = @($selectedArtifacts | Where-Object { $_ -and $_.Trim().Length -gt 0 })
    if ($artifactList.Count -lt 3) {
        throw "Could not find PASS artifacts for all required stages (extract_terms, niqqud_bootstrap, translate_bootstrap)."
    }

    Write-Host "Selected artifacts:" -ForegroundColor Yellow
    $artifactList | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }

    $checkerArgs = @("scripts/check_pipeline_stage_budget.py", "--artifacts")
    $checkerArgs += $artifactList
    & $python @checkerArgs
    $checkerExit = $LASTEXITCODE

    if ($checkerExit -eq 0) {
        Write-Host "PASS: pipeline stage budgets are green." -ForegroundColor Green
        $exitCode = 0
    } elseif ($checkerExit -eq 2) {
        Write-Warning "WARN: pipeline stage budgets are in warning band. See build\logs\pipeline_budget_report_latest.md"
        $exitCode = 2
    } elseif ($checkerExit -eq 1) {
        Write-Error "FAIL: pipeline stage budgets failed. See build\logs\pipeline_budget_report_latest.md"
        $exitCode = 1
    } else {
        Write-Error "Unexpected checker exit code: $checkerExit"
        $exitCode = 1
    }
} finally {
    Stop-Transcript | Out-Null
    Write-Host "Pipeline perf gate log: $gateLog" -ForegroundColor Yellow
}

exit $exitCode
