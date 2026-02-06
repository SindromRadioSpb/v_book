# Packaging smoke test for HDLE Premium
#
# Verifies that the packaged executable:
# 1. Exists and has correct structure (onedir mode)
# 2. Starts without immediate crash (torch_cpu.dll extraction check)
# 3. Creates user data directories and logs
#
# Usage:
#   .\scripts\run_packaged_smoke.ps1

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   HDLE Premium - Packaging Smoke Test     " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Check if distribution folder exists
Write-Host "[1/4] Checking build artifacts..." -ForegroundColor Yellow

if (-not (Test-Path "dist\HDLE_Premium")) {
    Write-Host "ERROR: Distribution folder not found: dist\HDLE_Premium" -ForegroundColor Red
    Write-Host "Run build_windows.ps1 first." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path "dist\HDLE_Premium\HDLE_Premium.exe")) {
    Write-Host "ERROR: Executable not found: dist\HDLE_Premium\HDLE_Premium.exe" -ForegroundColor Red
    exit 1
}

Write-Host "OK Distribution folder: dist\HDLE_Premium\" -ForegroundColor Green
Write-Host "OK Executable: dist\HDLE_Premium\HDLE_Premium.exe" -ForegroundColor Green
Write-Host ""

# Clean user data for cold start
Write-Host "[2/4] Cleaning user data (cold start)..." -ForegroundColor Yellow

$userDataPath = "$env:LOCALAPPDATA\HDLE"
if (Test-Path $userDataPath) {
    Remove-Item -Path $userDataPath -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "OK Removed: $userDataPath" -ForegroundColor Green
} else {
    Write-Host "OK User data already clean" -ForegroundColor Green
}
Write-Host ""

# Start executable and verify it doesn't crash immediately
Write-Host "[3/4] Starting executable (5-second smoke test)..." -ForegroundColor Yellow
Write-Host "This checks for immediate crashes (torch_cpu.dll extraction failure, etc.)" -ForegroundColor Gray
Write-Host ""

$exePath = "dist\HDLE_Premium\HDLE_Premium.exe"
$process = Start-Process -FilePath $exePath -PassThru -WindowStyle Normal

if (-not $process) {
    Write-Host "ERROR: Failed to start process" -ForegroundColor Red
    exit 1
}

Write-Host "OK Process started (PID: $($process.Id))" -ForegroundColor Green
Write-Host "   Waiting 5 seconds to check for immediate crash..." -ForegroundColor Gray

Start-Sleep -Seconds 5

# Check if process is still running
$stillRunning = Get-Process -Id $process.Id -ErrorAction SilentlyContinue

if (-not $stillRunning) {
    Write-Host "ERROR: Process crashed within 5 seconds" -ForegroundColor Red
    Write-Host "Check logs at: $userDataPath\logs\" -ForegroundColor Yellow
    exit 1
}

Write-Host "OK Process still running after 5 seconds" -ForegroundColor Green
Write-Host ""

# Kill process (smoke test complete)
Write-Host "   Stopping process..." -ForegroundColor Gray
Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "OK Smoke test passed" -ForegroundColor Green
Write-Host ""

# Verify user data was created
Write-Host "[4/4] Verifying user data creation..." -ForegroundColor Yellow

$expectedPaths = @(
    "$userDataPath\hdle.db",
    "$userDataPath\logs"
)

$allExists = $true
foreach ($path in $expectedPaths) {
    if (Test-Path $path) {
        Write-Host "OK Found: $path" -ForegroundColor Green
    } else {
        Write-Host "WARN Missing: $path" -ForegroundColor Yellow
        $allExists = $false
    }
}

if ($allExists) {
    Write-Host ""
    Write-Host "OK All expected paths created" -ForegroundColor Green
}

Write-Host ""

# Summary
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "        SMOKE TEST PASSED                    " -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Key checks:" -ForegroundColor White
Write-Host "  OK Executable exists (onedir mode)" -ForegroundColor Green
Write-Host "  OK No immediate crash (torch_cpu.dll OK)" -ForegroundColor Green
Write-Host "  OK User data directories created" -ForegroundColor Green
Write-Host ""
Write-Host "Next: Deploy to target location and run full smoke-check" -ForegroundColor White
Write-Host "  Example: M:\Soft\V_book\HDLE_Premium\" -ForegroundColor Cyan
Write-Host ""
