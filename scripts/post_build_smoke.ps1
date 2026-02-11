# Post-Build Smoke Test for HDLE Premium
# Verifies that built executable launches successfully

$ErrorActionPreference = "Stop"

Write-Host "`n=== POST-BUILD SMOKE TEST ===" -ForegroundColor Cyan

# --- CHECK EXECUTABLE EXISTS ---
$exePath = "dist\HDLE_Premium\HDLE_Premium.exe"

if (-not (Test-Path $exePath)) {
    Write-Host "[FAIL] Executable not found: $exePath" -ForegroundColor Red
    Write-Host "Run .\rebuild.ps1 first to build the application" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Executable found: $exePath" -ForegroundColor Green

$exeSize = (Get-Item $exePath).Length / 1MB
Write-Host "Size: $([Math]::Round($exeSize, 2)) MB" -ForegroundColor Gray

# --- CHECK FOR CRITICAL DEPENDENCIES ---
Write-Host "`nChecking critical dependencies..." -ForegroundColor Cyan

$criticalFiles = @(
    "dist\HDLE_Premium\_internal\PyQt6\Qt6\bin\Qt6Core.dll",
    "dist\HDLE_Premium\_internal\torch\lib\torch_cpu.dll",
    "dist\HDLE_Premium\_internal\sqlalchemy\__init__.pyc"
)

$missingFiles = @()
foreach ($file in $criticalFiles) {
    if (-not (Test-Path $file)) {
        $missingFiles += $file
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host "[WARN] Missing critical dependencies:" -ForegroundColor Yellow
    foreach ($file in $missingFiles) {
        Write-Host "  - $file" -ForegroundColor Yellow
    }
    Write-Host "Build may be incomplete - proceed with caution" -ForegroundColor Yellow
} else {
    Write-Host "[OK] All critical dependencies present" -ForegroundColor Green
}

# --- LAUNCH EXECUTABLE (HEADLESS CHECK) ---
Write-Host "`nLaunching executable for smoke test..." -ForegroundColor Cyan
Write-Host "This will start the app - check if UI appears without crashes" -ForegroundColor Gray
Write-Host "Press Ctrl+C in this window to abort, or close the app window to continue" -ForegroundColor Gray

try {
    # Start process and wait for it to initialize or exit
    $process = Start-Process -FilePath $exePath -PassThru -WorkingDirectory "dist\HDLE_Premium"

    # Wait for process to stabilize (5 seconds)
    Start-Sleep -Seconds 5

    # Check if process is still running
    if ($process.HasExited) {
        Write-Host "`n[FAIL] Application crashed during startup!" -ForegroundColor Red
        Write-Host "Exit code: $($process.ExitCode)" -ForegroundColor Yellow

        # Check for log files
        $logDir = Join-Path $env:LOCALAPPDATA "HDLE\logs"
        if (Test-Path $logDir) {
            $latestLog = Get-ChildItem $logDir -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latestLog) {
                Write-Host "`nLatest log file: $($latestLog.FullName)" -ForegroundColor Yellow
                Write-Host "Last 20 lines:" -ForegroundColor Yellow
                Get-Content $latestLog.FullName -Tail 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
            }
        }

        exit 1
    } else {
        Write-Host "`n[OK] Application is running (PID: $($process.Id))" -ForegroundColor Green
        Write-Host "Waiting for you to close the application window..." -ForegroundColor Cyan

        # Wait for user to close the app
        $process.WaitForExit()

        if ($process.ExitCode -eq 0) {
            Write-Host "[OK] Application exited cleanly (exit code 0)" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Application exited with code: $($process.ExitCode)" -ForegroundColor Yellow
        }
    }

} catch {
    Write-Host "`n[FAIL] Failed to launch application!" -ForegroundColor Red
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Yellow
    exit 1
}

# --- CHECK LOG FILES ---
Write-Host "`nChecking application logs..." -ForegroundColor Cyan

$logDir = Join-Path $env:LOCALAPPDATA "HDLE\logs"
if (Test-Path $logDir) {
    $logFiles = Get-ChildItem $logDir -Filter "*.log" | Sort-Object LastWriteTime -Descending
    if ($logFiles.Count -gt 0) {
        Write-Host "[OK] Log directory found: $logDir" -ForegroundColor Green
        Write-Host "Log files: $($logFiles.Count)" -ForegroundColor Gray

        # Check latest log for errors
        $latestLog = $logFiles[0]
        $logContent = Get-Content $latestLog.FullName -Raw

        $errorCount = ([regex]::Matches($logContent, "ERROR|CRITICAL")).Count
        $warningCount = ([regex]::Matches($logContent, "WARNING")).Count

        if ($errorCount -gt 0) {
            Write-Host "[WARN] Found $errorCount ERRORs in latest log" -ForegroundColor Yellow
        } else {
            Write-Host "[OK] No ERRORs in latest log" -ForegroundColor Green
        }

        if ($warningCount -gt 0) {
            Write-Host "[INFO] Found $warningCount WARNINGs in latest log" -ForegroundColor Gray
        }

    } else {
        Write-Host "[WARN] No log files found" -ForegroundColor Yellow
    }
} else {
    Write-Host "[WARN] Log directory not found: $logDir" -ForegroundColor Yellow
    Write-Host "This is expected on first run before app initialization" -ForegroundColor Gray
}

# --- SUMMARY ---
Write-Host "`n=== SMOKE TEST SUMMARY ===" -ForegroundColor Green
Write-Host "[OK] Executable exists and launches successfully" -ForegroundColor Green
Write-Host "[OK] No critical startup crashes detected" -ForegroundColor Green

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Test core features: create project, process documents, export" -ForegroundColor White
Write-Host "  2. Test export/import bundle roundtrip" -ForegroundColor White
Write-Host "  3. Run installer: .\installer\output\HDLE_Premium_Setup.exe" -ForegroundColor White

Write-Host "`n[PASS] Post-build smoke test completed" -ForegroundColor Green
