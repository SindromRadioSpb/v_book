# P2 + Regression Test Suite Runner
# Runs all P2 tests and regression tests with proper environment setup

$ErrorActionPreference = "Stop"

# Set headless Qt for PyQt tests
$env:QT_QPA_PLATFORM = "offscreen"

# Get venv python
$python = ".venv\Scripts\python.exe"

# Test files to run
$tests = @(
    # P2 Tests
    "test_p2_translation_admin_service.py",
    "test_p2_coverage_service.py",
    "test_p2_translation_management_model.py",
    "test_p2_ui_smoke.py",

    # Regression Tests
    "test_m7_normalization.py",
    "test_m7.py",
    "test_m7_ui_integration.py",
    "test_m7_view_wiring.py",
    "test_p1_verification.py"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "P2 + Regression Test Suite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Environment:" -ForegroundColor Yellow
Write-Host "  Python: $python"
Write-Host "  QT_QPA_PLATFORM: $env:QT_QPA_PLATFORM"
Write-Host ""

$passed = 0
$failed = 0
$results = @()

foreach ($test in $tests) {
    Write-Host "Running: $test" -ForegroundColor Cyan
    Write-Host "----------------------------------------"

    $output = & $python $test 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "[PASS] $test" -ForegroundColor Green
        $passed++
        $results += @{ Test = $test; Status = "PASS"; ExitCode = $exitCode }
    } else {
        Write-Host "[FAIL] $test (exit code: $exitCode)" -ForegroundColor Red
        Write-Host $output
        $failed++
        $results += @{ Test = $test; Status = "FAIL"; ExitCode = $exitCode }
    }

    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

foreach ($result in $results) {
    $status = $result.Status
    $color = if ($status -eq "PASS") { "Green" } else { "Red" }
    Write-Host "[$status] $($result.Test)" -ForegroundColor $color
}

Write-Host ""
Write-Host "Total: $($tests.Count) tests" -ForegroundColor Yellow
Write-Host "Passed: $passed" -ForegroundColor Green
Write-Host "Failed: $failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host ""

if ($failed -gt 0) {
    Write-Host "OVERALL: FAIL" -ForegroundColor Red
    exit 1
} else {
    Write-Host "OVERALL: PASS" -ForegroundColor Green
    exit 0
}
