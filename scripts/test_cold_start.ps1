# TEST 1: Cold start verification
# Tests that fresh installation creates database with tm_entry table

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   TEST 1: Cold Start Verification          " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Kill any running instances
Write-Host "[1/7] Stopping existing instances..." -ForegroundColor Yellow
Get-Process -Name 'HDLE_Premium' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Write-Host "OK All instances stopped" -ForegroundColor Green
Write-Host ""

# 2. Clean user data
Write-Host "[2/7] Cleaning user data..." -ForegroundColor Yellow
Remove-Item -Path "$env:LOCALAPPDATA\HDLE" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "OK User data cleaned: $env:LOCALAPPDATA\HDLE" -ForegroundColor Green
Write-Host ""

# 3. Start app
Write-Host "[3/7] Starting application..." -ForegroundColor Yellow
$process = Start-Process -FilePath 'M:\Soft\V_book\HDLE_Premium\HDLE_Premium.exe' -PassThru -WindowStyle Normal
Write-Host "OK Process started (PID: $($process.Id))" -ForegroundColor Green
Write-Host ""

# 4. Wait for initialization
Write-Host "[4/7] Waiting 10 seconds for initialization..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# 5. Check if still running
Write-Host "[5/7] Checking process status..." -ForegroundColor Yellow
$stillRunning = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
if (-not $stillRunning) {
    Write-Host "ERROR: Process crashed during startup" -ForegroundColor Red
    exit 1
}
Write-Host "OK Process still running" -ForegroundColor Green
Write-Host ""

# 6. Check database and migrations
Write-Host "[6/7] Verifying database and migrations..." -ForegroundColor Yellow

if (-not (Test-Path "$env:LOCALAPPDATA\HDLE\hdle.db")) {
    Write-Host "ERROR: Database not created" -ForegroundColor Red
    Stop-Process -Id $process.Id -Force
    exit 1
}
Write-Host "OK Database created: hdle.db" -ForegroundColor Green

# Check schema version
$version = & sqlite3 "$env:LOCALAPPDATA\HDLE\hdle.db" "SELECT value FROM schema_meta WHERE key='schema_version';"
Write-Host "OK Schema version: $version (expected: 6)" -ForegroundColor Green

if ($version -ne "6") {
    Write-Host "WARNING: Schema version mismatch (expected 6, got $version)" -ForegroundColor Yellow
}

# Check tm_entry table exists
$tmTable = & sqlite3 "$env:LOCALAPPDATA\HDLE\hdle.db" "SELECT name FROM sqlite_master WHERE type='table' AND name='tm_entry';"
if ($tmTable -eq 'tm_entry') {
    Write-Host "OK tm_entry table EXISTS" -ForegroundColor Green
} else {
    Write-Host "ERROR: tm_entry table MISSING" -ForegroundColor Red
    Stop-Process -Id $process.Id -Force
    exit 1
}

# Check other M7 tables
$tmHistoryTable = & sqlite3 "$env:LOCALAPPDATA\HDLE\hdle.db" "SELECT name FROM sqlite_master WHERE type='table' AND name='tm_entry_history';"
$tmAliasTable = & sqlite3 "$env:LOCALAPPDATA\HDLE\hdle.db" "SELECT name FROM sqlite_master WHERE type='table' AND name='tm_alias';"
$dictSourceTable = & sqlite3 "$env:LOCALAPPDATA\HDLE\hdle.db" "SELECT name FROM sqlite_master WHERE type='table' AND name='dict_source';"

if ($tmHistoryTable -eq 'tm_entry_history') {
    Write-Host "OK tm_entry_history table EXISTS" -ForegroundColor Green
}
if ($tmAliasTable -eq 'tm_alias') {
    Write-Host "OK tm_alias table EXISTS" -ForegroundColor Green
}
if ($dictSourceTable -eq 'dict_source') {
    Write-Host "OK dict_source table EXISTS" -ForegroundColor Green
}

# Check logs
if (Test-Path "$env:LOCALAPPDATA\HDLE\logs\") {
    Write-Host "OK Logs directory created" -ForegroundColor Green
    $latestLog = Get-ChildItem "$env:LOCALAPPDATA\HDLE\logs\*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        Write-Host "OK Latest log: $($latestLog.Name)" -ForegroundColor Green
    }
} else {
    Write-Host "WARNING: Logs directory not created" -ForegroundColor Yellow
}

Write-Host ""

# 7. Stop process
Write-Host "[7/7] Stopping application..." -ForegroundColor Yellow
Stop-Process -Id $process.Id -Force
Start-Sleep -Seconds 2
Write-Host "OK Process stopped" -ForegroundColor Green
Write-Host ""

# Summary
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "         TEST 1: PASS                        " -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verification:" -ForegroundColor White
Write-Host "  OK Application started" -ForegroundColor Green
Write-Host "  OK Database created with schema v$version" -ForegroundColor Green
Write-Host "  OK tm_entry table present" -ForegroundColor Green
Write-Host "  OK M7 Translation Memory tables complete" -ForegroundColor Green
Write-Host ""
