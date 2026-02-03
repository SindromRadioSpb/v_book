# CI Test Runner - Windows PowerShell
# Runs all M7 + P1 tests for gating

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "CI Test Runner - M7 + P1 Gate" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Activate virtual environment
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    Write-Host "`nActivating virtual environment..." -ForegroundColor Yellow
    .\.venv\Scripts\Activate.ps1
} else {
    Write-Host "ERROR: Virtual environment not found at .\.venv\" -ForegroundColor Red
    Write-Host "Please run: python -m venv .venv" -ForegroundColor Red
    exit 1
}

# Test counter
$TestsPassed = 0
$TestsFailed = 0

function Run-Test {
    param (
        [string]$TestName,
        [string]$TestCommand
    )

    Write-Host "`n----------------------------------------" -ForegroundColor Cyan
    Write-Host "Running: $TestName" -ForegroundColor Yellow
    Write-Host "----------------------------------------" -ForegroundColor Cyan

    & python $TestCommand
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ PASS: $TestName" -ForegroundColor Green
        $script:TestsPassed++
    } else {
        Write-Host "❌ FAIL: $TestName" -ForegroundColor Red
        $script:TestsFailed++
    }
}

# Run M7 tests
Run-Test "M7 Core Tests" "test_m7.py"
Run-Test "M7 UI Integration" "test_m7_ui_integration.py"
Run-Test "M7 Normalization" "test_m7_normalization.py"

# Run P1 tests
Run-Test "P1 Unit Tests" "test_p1_verification.py"
Run-Test "P1 E2E (Term Clusters)" "test_p1_e2e_termclusters.py"

# Summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "CI Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Passed: $TestsPassed" -ForegroundColor Green
Write-Host "Failed: $TestsFailed" -ForegroundColor $(if ($TestsFailed -eq 0) { "Green" } else { "Red" })

if ($TestsFailed -gt 0) {
    Write-Host "`n❌ CI GATE FAILED" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n✅ CI GATE PASSED" -ForegroundColor Green
    exit 0
}
