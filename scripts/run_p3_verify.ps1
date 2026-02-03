# P3 Verification Runner Script
# Runs P3 verification tests in headless mode

$ErrorActionPreference = "Stop"

Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "P3 VERIFICATION GATE - Test Runner" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# Set headless mode for Qt
$env:QT_QPA_PLATFORM = "offscreen"
Write-Host "QT_QPA_PLATFORM=offscreen" -ForegroundColor Gray
Write-Host ""

# Track results
$total_tests = 0
$passed_tests = 0
$failed_tests = 0

# Function to run a test
function Run-Test {
    param(
        [string]$TestFile,
        [string]$Description
    )

    Write-Host "Running: $Description" -ForegroundColor Yellow
    Write-Host "  File: $TestFile" -ForegroundColor Gray

    $global:total_tests++

    try {
        & .venv\Scripts\python.exe $TestFile

        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Result: PASS" -ForegroundColor Green
            $global:passed_tests++
        } else {
            Write-Host "  Result: FAIL (exit code $LASTEXITCODE)" -ForegroundColor Red
            $global:failed_tests++
        }
    } catch {
        Write-Host "  Result: ERROR - $_" -ForegroundColor Red
        $global:failed_tests++
    }

    Write-Host ""
}

# Run P3 verification service tests
Run-Test "test_p3_verification.py" "P3 Verification Service Tests"

# Run existing P3 tests for regression
Run-Test "test_p3_dictionary_import_csv.py" "P3 Dictionary Import CSV Tests"
Run-Test "test_p3_dictionary_import_xlsx.py" "P3 Dictionary Import XLSX Tests"
Run-Test "test_p3_conflict_policies.py" "P3 Conflict Policies Tests"
Run-Test "test_p3_export_csv_injection.py" "P3 Export CSV Injection Tests"

# Run M7 regression tests
Write-Host "Running M7 regression tests..." -ForegroundColor Yellow
Run-Test "test_m7_normalization.py" "M7 Normalization Tests"
Run-Test "test_m7.py" "M7 Core Tests"

# Run P1 regression tests
Write-Host "Running P1 regression tests..." -ForegroundColor Yellow
Run-Test "test_p1_verification.py" "P1 Verification Tests"

# Summary
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "TEST SUMMARY" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "Total:  $total_tests" -ForegroundColor White
Write-Host "Passed: $passed_tests" -ForegroundColor Green
Write-Host "Failed: $failed_tests" -ForegroundColor $(if ($failed_tests -eq 0) { "Green" } else { "Red" })
Write-Host "=" * 80 -ForegroundColor Cyan

if ($failed_tests -gt 0) {
    Write-Host "RESULT: FAIL" -ForegroundColor Red
    exit 1
} else {
    Write-Host "RESULT: PASS" -ForegroundColor Green
    exit 0
}
