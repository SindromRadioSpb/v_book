param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing venv python at $python. Recreate .venv before running release diagnostics."
}

$logsDir = Join-Path $repoRoot "build\\logs"
$tmpDir = Join-Path $repoRoot "build\\tmp\\release_gate"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

$releaseLog = Join-Path $logsDir "release_gate_latest.txt"
$inventoryPath = Join-Path $logsDir "release_gate_inventory.md"

$env:QT_QPA_PLATFORM = "offscreen"
$env:TEMP = $tmpDir
$env:TMP = $tmpDir

function Get-FailureCategory {
    param([string]$Line)

    $text = ""
    if ($null -ne $Line) {
        $text = [string]$Line
    }
    $text = $text.ToLowerInvariant()
    if ($text -match "no such table|no such column|schema|migration|schema_meta|alembic") {
        return "schema"
    }
    if ($text -match "access violation|segmentation fault|fatal python error|torch|stanza|onnxruntime") {
        return "native"
    }
    if ($text -match "permissionerror|access is denied|migrate\\.lock|could not acquire lock|appdata|temp") {
        return "env"
    }
    if ($text -match "flaky|intermittent") {
        return "flaky"
    }
    return "functional"
}

Write-Host "== Release Gate Diagnostic ==" -ForegroundColor Cyan
Write-Host "Using TEMP/TMP=$tmpDir" -ForegroundColor Yellow
Write-Host "Writing log: $releaseLog" -ForegroundColor Yellow

$pytestOutput = & $python -m pytest -q -ra --maxfail=0 2>&1 | Tee-Object -FilePath $releaseLog
$pytestExitCode = $LASTEXITCODE

$lines = @()
if ($pytestOutput -is [System.Array]) {
    $lines = $pytestOutput | ForEach-Object { [string]$_ }
} elseif ($null -ne $pytestOutput) {
    $lines = @([string]$pytestOutput)
}
if ($lines.Count -eq 0 -and (Test-Path $releaseLog)) {
    $lines = Get-Content -Path $releaseLog
}

$failureLines = $lines | Where-Object { $_ -match "^(FAILED|ERROR)\s+" }
$grouped = @{}
foreach ($line in $failureLines) {
    $category = Get-FailureCategory -Line $line
    if (-not $grouped.ContainsKey($category)) {
        $grouped[$category] = New-Object System.Collections.Generic.List[string]
    }
    $grouped[$category].Add($line)
}

$inventoryLines = New-Object System.Collections.Generic.List[string]
$inventoryLines.Add("# Release Gate Failure Inventory")
$inventoryLines.Add("")
$inventoryLines.Add("- generated_utc: $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')")
$inventoryLines.Add("- pytest_exit_code: $pytestExitCode")
$inventoryLines.Add("- log_path: build\\logs\\release_gate_latest.txt")
$inventoryLines.Add("- temp_path: build\\tmp\\release_gate")
$inventoryLines.Add("")

if ($failureLines.Count -eq 0) {
    $inventoryLines.Add("## Summary")
    $inventoryLines.Add("")
    $inventoryLines.Add("- No FAILED/ERROR entries detected in pytest summary.")
} else {
    $inventoryLines.Add("## Summary")
    $inventoryLines.Add("")
    $inventoryLines.Add("- total_failure_entries: $($failureLines.Count)")
    $inventoryLines.Add("")
    foreach ($category in @("functional", "schema", "native", "env", "flaky")) {
        if (-not $grouped.ContainsKey($category)) {
            continue
        }
        $items = $grouped[$category]
        $inventoryLines.Add("## Category: $category")
        $inventoryLines.Add("")
        foreach ($item in $items) {
            $inventoryLines.Add("- $item")
        }
        $inventoryLines.Add("")
    }
}

$inventoryLines.Add("## Pytest Tail")
$inventoryLines.Add("")
$tailLines = $lines | Select-Object -Last 40
foreach ($line in $tailLines) {
    $inventoryLines.Add("    $line")
}

Set-Content -Path $inventoryPath -Value $inventoryLines -Encoding UTF8

Write-Host "Release diagnostic log: $releaseLog" -ForegroundColor Yellow
Write-Host "Release inventory: $inventoryPath" -ForegroundColor Yellow
if ($pytestExitCode -eq 0) {
    Write-Host "PASS: Release gate diagnostic is green." -ForegroundColor Green
} else {
    Write-Host "INFO: Release gate diagnostic captured failures (exit code $pytestExitCode)." -ForegroundColor Yellow
}

exit $pytestExitCode
