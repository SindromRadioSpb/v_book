# Build script for Windows standalone executable
#
# This script builds HDLE Premium into a standalone .exe using PyInstaller.
# The resulting executable can be run on any Windows 10/11 machine without
# requiring Python or dependencies to be installed.

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   HDLE Premium - Windows Build Script     " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Check virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "ERROR: Virtual environment not found." -ForegroundColor Red
    Write-Host "Please create one first: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

Write-Host "[1/5] Activating virtual environment..." -ForegroundColor Yellow
. .venv\Scripts\Activate.ps1

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to activate virtual environment" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Virtual environment activated" -ForegroundColor Green
Write-Host ""

# Check PyInstaller
Write-Host "[2/5] Checking PyInstaller..." -ForegroundColor Yellow
python -c "import PyInstaller; print(f'PyInstaller {PyInstaller.__version__}')" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install PyInstaller" -ForegroundColor Red
        exit 1
    }
}

Write-Host "✓ PyInstaller ready" -ForegroundColor Green
Write-Host ""

# Clean previous build
Write-Host "[3/5] Cleaning previous build..." -ForegroundColor Yellow

if (Test-Path "dist") {
    Remove-Item -Path "dist" -Recurse -Force
    Write-Host "  - Removed dist/" -ForegroundColor Gray
}

if (Test-Path "build\HDLE_Premium") {
    Remove-Item -Path "build\HDLE_Premium" -Recurse -Force
    Write-Host "  - Removed build/HDLE_Premium/" -ForegroundColor Gray
}

Write-Host "✓ Build directory cleaned" -ForegroundColor Green
Write-Host ""

# Run PyInstaller
Write-Host "[4/5] Building executable..." -ForegroundColor Yellow
Write-Host "This may take several minutes..." -ForegroundColor Gray
Write-Host ""

pyinstaller build/v_book.spec --clean --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: PyInstaller build failed!" -ForegroundColor Red
    Write-Host "Check output above for errors." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "✓ Executable built successfully" -ForegroundColor Green
Write-Host ""

# Verify output
Write-Host "[5/5] Verifying build..." -ForegroundColor Yellow

if (-not (Test-Path "dist\HDLE_Premium.exe")) {
    Write-Host "ERROR: Expected executable not found: dist\HDLE_Premium.exe" -ForegroundColor Red
    exit 1
}

$exeSize = (Get-Item "dist\HDLE_Premium.exe").Length
$exeSizeMB = [math]::Round($exeSize / 1MB, 2)

Write-Host "✓ Executable verified: dist\HDLE_Premium.exe ($exeSizeMB MB)" -ForegroundColor Green
Write-Host ""

# Summary
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "           BUILD SUCCESSFUL                  " -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Executable location:" -ForegroundColor White
Write-Host "  $PWD\dist\HDLE_Premium.exe" -ForegroundColor Cyan
Write-Host ""
Write-Host "File size: $exeSizeMB MB" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Test the executable on this machine" -ForegroundColor Gray
Write-Host "  2. Test on a clean Windows VM (no Python installed)" -ForegroundColor Gray
Write-Host "  3. Build installer with Inno Setup (see BUILD_WINDOWS_INSTALLER.md)" -ForegroundColor Gray
Write-Host ""
Write-Host "To run the executable:" -ForegroundColor White
Write-Host "  .\dist\HDLE_Premium.exe" -ForegroundColor Cyan
Write-Host ""
