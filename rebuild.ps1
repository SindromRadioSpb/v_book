# HDLE Premium - Robust Build Script
# Production-grade rebuild with fail-fast checks and AV-resilient output

$ErrorActionPreference = "Stop"

# --- PRECONDITIONS CHECK ---
Write-Host "`n=== PREBUILD VALIDATION ===" -ForegroundColor Cyan

# Check Python version
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Python not found in PATH" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] $pythonVersion" -ForegroundColor Green

# Check PyInstaller
$pyinstallerVersion = pyinstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] PyInstaller not found. Install with: pip install pyinstaller" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] PyInstaller $pyinstallerVersion" -ForegroundColor Green

# Check Inno Setup
$isccPath = "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $isccPath)) {
    Write-Host "[FAIL] Inno Setup not found at: $isccPath" -ForegroundColor Red
    Write-Host "Install from: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Inno Setup found" -ForegroundColor Green

# Check for running processes that could lock files
$runningProcesses = @()
$processNames = @("HDLE_Premium", "HDLE_Premium_Setup")
foreach ($procName in $processNames) {
    $proc = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($proc) {
        $runningProcesses += $procName
    }
}

if ($runningProcesses.Count -gt 0) {
    Write-Host "[WARN] Running processes detected: $($runningProcesses -join ', ')" -ForegroundColor Yellow
    Write-Host "These may lock files during build. Kill them? (Y/N)" -ForegroundColor Yellow
    $response = Read-Host
    if ($response -eq 'Y' -or $response -eq 'y') {
        foreach ($procName in $runningProcesses) {
            Stop-Process -Name $procName -Force -ErrorAction SilentlyContinue
        }
        Write-Host "[OK] Processes killed" -ForegroundColor Green
        Start-Sleep -Seconds 2
    } else {
        Write-Host "[WARN] Continuing with running processes - may fail" -ForegroundColor Yellow
    }
}

# Check output directory is writable
$testFile = "installer\output\.write_test_$(Get-Date -Format 'HHmmss')"
try {
    New-Item -ItemType Directory -Force -Path "installer\output" | Out-Null
    "test" | Out-File $testFile -ErrorAction Stop
    Remove-Item $testFile -ErrorAction Stop
    Write-Host "[OK] installer\output\ is writable" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Cannot write to installer\output\" -ForegroundColor Red
    Write-Host "Check permissions and antivirus exclusions" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n=== STARTING BUILD ===" -ForegroundColor Cyan

# --- CLEAN OLD ARTIFACTS ---
Write-Host "Cleaning old build artifacts..." -ForegroundColor Yellow
if (Test-Path .\build) {
    Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
}
if (Test-Path .\dist)  {
    Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
}

# Create logs directory
New-Item -ItemType Directory -Force -Path "build\logs" | Out-Null

# --- PYINSTALLER BUILD ---
Write-Host "`nBuilding with PyInstaller..." -ForegroundColor Cyan
$pyinstallerLog = "build\logs\pyinstaller_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Run PyInstaller via cmd.exe to avoid PowerShell stderr handling issues
# PyInstaller writes INFO messages to stderr which PowerShell treats as errors
cmd /c "pyinstaller .\hdle_premium_installer.spec --clean --noconfirm > `"$pyinstallerLog`" 2>&1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] PyInstaller build failed!" -ForegroundColor Red
    Write-Host "See log: $pyinstallerLog" -ForegroundColor Yellow
    # Show last 20 lines of log
    Write-Host "`nLast 20 lines of log:" -ForegroundColor Yellow
    Get-Content $pyinstallerLog -Tail 20 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
    exit 1
}

Write-Host "[OK] PyInstaller completed - see log for details: $pyinstallerLog" -ForegroundColor Green

# Verify PyInstaller output
if (-not (Test-Path "dist\HDLE_Premium\HDLE_Premium.exe")) {
    Write-Host "`n[FAIL] dist\HDLE_Premium\HDLE_Premium.exe not found!" -ForegroundColor Red
    exit 1
}

Write-Host "`n[OK] Build successful!" -ForegroundColor Green
Write-Host "Output: dist\HDLE_Premium\HDLE_Premium.exe" -ForegroundColor Green

# --- INNO SETUP BUILD (AV-RESILIENT) ---
Write-Host "`nBuilding installer with Inno Setup..." -ForegroundColor Cyan

# Strategy: Build to temp, then copy with retries to avoid AV locks
$tempOutput = Join-Path $env:TEMP ("HDLE_Inno_Out_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $tempOutput | Out-Null

Write-Host "Temp output: $tempOutput" -ForegroundColor Gray

$innoLog = "build\logs\inno_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Run ISCC via cmd.exe to avoid PowerShell stderr handling issues
cmd /c "`"$isccPath`" /O`"$tempOutput`" /F`"HDLE_Premium_Setup`" .\installer\installer.iss > `"$innoLog`" 2>&1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] Inno Setup build failed!" -ForegroundColor Red
    Write-Host "See log: $innoLog" -ForegroundColor Yellow

    # Show last 30 lines of log
    Write-Host "`nLast 30 lines of log:" -ForegroundColor Yellow
    Get-Content $innoLog -Tail 30 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

    # Check for common error 110
    $logContent = Get-Content $innoLog -Raw
    if ($logContent -match "EndUpdateResource failed.*\(110\)") {
        Write-Host "`n=== TROUBLESHOOTING ===" -ForegroundColor Yellow
        Write-Host "Error 110 = Antivirus/Defender is blocking resource update" -ForegroundColor Yellow
        Write-Host "Solutions:" -ForegroundColor Yellow
        Write-Host "  1. Add exclusions to Windows Defender for:" -ForegroundColor Yellow
        Write-Host "     - J:\Project_Vibe\V_book\installer\output" -ForegroundColor Yellow
        Write-Host "     - $tempOutput" -ForegroundColor Yellow
        Write-Host "  2. Temporarily disable Controlled Folder Access" -ForegroundColor Yellow
        Write-Host "  3. Run PowerShell as Administrator" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "[OK] Inno Setup completed - see log: $innoLog" -ForegroundColor Green

# Verify temp output
$tempSetupExe = Join-Path $tempOutput "HDLE_Premium_Setup.exe"
if (-not (Test-Path $tempSetupExe)) {
    Write-Host "`n[FAIL] Setup.exe not found in temp output!" -ForegroundColor Red
    exit 1
}

# Copy from temp to final location with retries
Write-Host "`nCopying installer to final location (with AV retry logic)..." -ForegroundColor Cyan

$finalSetupExe = "installer\output\HDLE_Premium_Setup.exe"
$maxRetries = 5
$retryDelay = 2

for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        # Remove old file if exists
        if (Test-Path $finalSetupExe) {
            Remove-Item $finalSetupExe -Force -ErrorAction Stop
        }

        # Copy with progress
        Copy-Item $tempSetupExe $finalSetupExe -Force -ErrorAction Stop

        Write-Host "[OK] Installer copied successfully" -ForegroundColor Green
        break
    } catch {
        if ($i -lt $maxRetries) {
            Write-Host "[WARN] Copy failed (attempt $i/$maxRetries), retrying in ${retryDelay}s..." -ForegroundColor Yellow
            Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Gray
            Start-Sleep -Seconds $retryDelay
        } else {
            Write-Host "`n[FAIL] Copy failed after $maxRetries attempts!" -ForegroundColor Red
            Write-Host "Possible cause: Antivirus is scanning/locking the file" -ForegroundColor Yellow
            Write-Host "Temp file available at: $tempSetupExe" -ForegroundColor Yellow
            exit 1
        }
    }
}

# Cleanup temp directory
Remove-Item -Recurse -Force $tempOutput -ErrorAction SilentlyContinue

# Verify final output
if (-not (Test-Path $finalSetupExe)) {
    Write-Host "`n[FAIL] Final installer not found!" -ForegroundColor Red
    exit 1
}

$setupSize = (Get-Item $finalSetupExe).Length / 1MB
Write-Host "`n[OK] Installer created!" -ForegroundColor Green
Write-Host "Output: $finalSetupExe" -ForegroundColor Green
Write-Host "Size: $([Math]::Round($setupSize, 2)) MB" -ForegroundColor Green

# --- SUMMARY ---
Write-Host "`n=== BUILD COMPLETE ===" -ForegroundColor Green
Write-Host "EXE:       dist\HDLE_Premium\HDLE_Premium.exe" -ForegroundColor White
Write-Host "Installer: installer\output\HDLE_Premium_Setup.exe" -ForegroundColor White
Write-Host "`nLogs:" -ForegroundColor White
Write-Host "  PyInstaller: $pyinstallerLog" -ForegroundColor Gray
Write-Host "  Inno Setup:  $innoLog" -ForegroundColor Gray

Write-Host "`nNext: Run smoke tests with .\scripts\post_build_smoke.ps1" -ForegroundColor Cyan
