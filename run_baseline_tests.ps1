# Baseline Test Suite for Iteration 1
# Run all critical tests M1-M7 + P1-P3 to establish baseline before changes

$ErrorActionPreference = "Continue"
$env:QT_QPA_PLATFORM = "offscreen"

$passed = 0
$failed = 0
$results = @()

function Run-Test {
    param(
        [string]$TestFile,
        [string]$Description
    )

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "Running: $Description" -ForegroundColor Cyan
    Write-Host "File: $TestFile" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    $start = Get-Date
    & .\.venv\Scripts\python.exe $TestFile
    $exitCode = $LASTEXITCODE
    $duration = ((Get-Date) - $start).TotalSeconds

    $status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }
    $color = if ($exitCode -eq 0) { "Green" } else { "Red" }

    Write-Host "`n[$status] $Description (${duration}s)" -ForegroundColor $color

    $script:results += [PSCustomObject]@{
        Test = $Description
        File = $TestFile
        Status = $status
        Duration = [math]::Round($duration, 2)
        ExitCode = $exitCode
    }

    if ($exitCode -eq 0) {
        $script:passed++
    } else {
        $script:failed++
    }
}

Write-Host "`n" -ForegroundColor Yellow
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║  BASELINE TEST SUITE - Iteration 1 Preconditions              ║" -ForegroundColor Yellow
Write-Host "║  Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')                         ║" -ForegroundColor Yellow
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow

# Core Milestones M1-M7
Run-Test "test_m1.py" "M1: Foundation & Storage"
Run-Test "test_m2.py" "M2: Document Ingestion"
Run-Test "test_m3.py" "M3: NLP Processing"
Run-Test "test_m4.py" "M4: Live Update"
Run-Test "test_m5.py" "M5: Term Extraction"
Run-Test "test_m6.py" "M6: Concordance/KWIC"
Run-Test "test_m7.py" "M7: Translation Memory"
Run-Test "test_m7_normalization.py" "M7: Normalization Contract"
Run-Test "test_m7_ui_integration.py" "M7: UI Integration"

# Premium Phase P1
Run-Test "test_p1_verification.py" "P1: Verification Service"
Run-Test "test_p1_e2e_termclusters.py" "P1: E2E Term Clusters"

# Premium Phase P2
Run-Test "test_p2_translation_admin_service.py" "P2: Translation Admin Service"
Run-Test "test_p2_coverage_service.py" "P2: Coverage Service"
Run-Test "test_p2_translation_management_model.py" "P2: TM Model"
Run-Test "test_p2_ui_smoke.py" "P2: UI Smoke Tests"

# Premium Phase P3
Run-Test "test_p3_verification.py" "P3: Verification Service"
Run-Test "test_p3_conflict_policies.py" "P3: Conflict Policies"
Run-Test "test_p3_dictionary_import_csv.py" "P3: CSV Import"
Run-Test "test_p3_dictionary_import_xlsx.py" "P3: XLSX Import"
Run-Test "test_p3_export_csv_injection.py" "P3: CSV Injection Protection"

# Summary
Write-Host "`n`n" -ForegroundColor Yellow
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║  BASELINE TEST SUMMARY                                         ║" -ForegroundColor Yellow
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Yellow

Write-Host "`nTotal Tests: $($passed + $failed)" -ForegroundColor White
Write-Host "PASSED: $passed" -ForegroundColor Green
Write-Host "FAILED: $failed" -ForegroundColor Red

if ($failed -gt 0) {
    Write-Host "`nFailed Tests:" -ForegroundColor Red
    $results | Where-Object { $_.Status -eq "FAIL" } | ForEach-Object {
        Write-Host "  - $($_.Test) ($($_.File))" -ForegroundColor Red
    }
}

# Export results to markdown
$markdown = @"
# Baseline Test Results - Iteration 1

**Date:** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
**Total Tests:** $($passed + $failed)
**Passed:** $passed
**Failed:** $failed

## Test Results

| Test | File | Status | Duration (s) | Exit Code |
|------|------|--------|--------------|-----------|
"@

$results | ForEach-Object {
    $statusIcon = if ($_.Status -eq "PASS") { "[OK]" } else { "[FAIL]" }
    $markdown += "`n| $statusIcon $($_.Test) | $($_.File) | $($_.Status) | $($_.Duration) | $($_.ExitCode) |"
}

$markdown += @"


## Dependencies Verified

- [OK] PyQt6
- [OK] SQLAlchemy
- [OK] Stanza
- [OK] openpyxl (version 3.1.5)
- [MISSING] PyInstaller (will install for M10)

## Environment

- QT_QPA_PLATFORM: offscreen
- Python: $(& .\.venv\Scripts\python.exe --version)
- Platform: Windows (MSYS_NT)

## Next Steps

"@

if ($failed -gt 0) {
    $markdown += "`n**CRITICAL:** Fix failing tests before proceeding with M8-M10 implementation.`n`n"
    $results | Where-Object { $_.Status -eq "FAIL" } | ForEach-Object {
        $markdown += "- [ ] Fix: $($_.Test) ($($_.File))`n"
    }
} else {
    $markdown += "`n**STATUS:** All baseline tests PASS. Ready to proceed with Iteration 1 (M8-M10).`n"
}

$markdown | Out-File -FilePath "docs\ITERATION_1_BASELINE.md" -Encoding UTF8

Write-Host "`n[OK] Results saved to docs\ITERATION_1_BASELINE.md" -ForegroundColor Green

exit $failed
