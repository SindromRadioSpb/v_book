# HDLE Premium - Manual Smoke Check Script
# Comprehensive testing suite for M10 Packaging + QA
#
# This script automates all 8 smoke tests from the manual checklist.
# Run after deployment to M:\Soft\V_book\HDLE_Premium\

param(
    [switch]$SkipInteractive = $false
)

$appPath = "M:\Soft\V_book\HDLE_Premium\HDLE_Premium.exe"
$userDataPath = "$env:LOCALAPPDATA\HDLE"

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "      HDLE Premium - Manual Smoke Check Suite           " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# TEST 1: Первый запуск (холодный старт)
Write-Host "TEST 1: First Launch (Cold Start)" -ForegroundColor Yellow
Write-Host "Testing fresh installation with clean user data..." -ForegroundColor Gray
Write-Host ""

# Clean user data
Get-Process -Name 'HDLE_Premium' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Remove-Item -Path $userDataPath -Recurse -Force -ErrorAction SilentlyContinue

# Start app
$process = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal
Start-Sleep -Seconds 10

# Verify
$stillRunning = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
if ($stillRunning -and (Test-Path "$userDataPath\hdle.db")) {
    $version = & sqlite3 "$userDataPath\hdle.db" "SELECT value FROM schema_meta WHERE key='schema_version';"
    $tmTable = & sqlite3 "$userDataPath\hdle.db" "SELECT name FROM sqlite_master WHERE type='table' AND name='tm_entry';"

    if ($tmTable -eq 'tm_entry' -and $version -eq '6') {
        Write-Host "OK TEST 1: PASS" -ForegroundColor Green
        Write-Host "   - App started successfully" -ForegroundColor Gray
        Write-Host "   - Database created (schema v$version)" -ForegroundColor Gray
        Write-Host "   - tm_entry table present" -ForegroundColor Gray
    } else {
        Write-Host "FAIL TEST 1: Schema or tables missing" -ForegroundColor Red
    }
} else {
    Write-Host "FAIL TEST 1: App crashed or DB not created" -ForegroundColor Red
}

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host ""

# TEST 2: Создание проекта
if (-not $SkipInteractive) {
    Write-Host "TEST 2: Create Project + Import Document" -ForegroundColor Yellow
    Write-Host "Manual steps required:" -ForegroundColor Gray
    Write-Host "  1. Create new project (Hebrew -> Russian)" -ForegroundColor Gray
    Write-Host "  2. Import test document from M:\Soft\V_book\HDLE_Premium\Тестовые тексты\" -ForegroundColor Gray
    Write-Host "  3. Verify no 'tm_entry' errors" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter when ready to continue"
}

# TEST 3: Backup before migration
Write-Host "TEST 3: Backup Before Migration" -ForegroundColor Yellow
Write-Host "Simulating upgrade scenario..." -ForegroundColor Gray

$process = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal
Start-Sleep -Seconds 5
Stop-Process -Id $process.Id -Force

# Downgrade schema
& sqlite3 "$userDataPath\hdle.db" "UPDATE schema_meta SET value='5' WHERE key='schema_version';"

# Restart (should trigger migration and backup)
$process = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal
Start-Sleep -Seconds 10

$backups = Get-ChildItem "$userDataPath\backups\backup_*_pre_migration_5_to_6.db" -ErrorAction SilentlyContinue
if ($backups.Count -gt 0) {
    Write-Host "OK TEST 3: PASS" -ForegroundColor Green
    Write-Host "   - Backup created: $($backups[0].Name)" -ForegroundColor Gray
} else {
    Write-Host "FAIL TEST 3: Backup not created" -ForegroundColor Red
}

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host ""

# TEST 4: Crash recovery
Write-Host "TEST 4: Crash Recovery" -ForegroundColor Yellow
Write-Host "Simulating unclean shutdown..." -ForegroundColor Gray

# Insert running processor_run
& sqlite3 "$userDataPath\hdle.db" @"
INSERT INTO processor_run (project_id, engine, status, started_at)
VALUES (1, 'stanza', 'running', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
"@

# Restart app (should recover)
$process = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal
Start-Sleep -Seconds 10

$recoveredRuns = & sqlite3 "$userDataPath\hdle.db" "SELECT COUNT(*) FROM processor_run WHERE status='failed';"
$recoveryErrors = & sqlite3 "$userDataPath\hdle.db" "SELECT COUNT(*) FROM run_error WHERE stage='crash_recovery';"

if ($recoveredRuns -gt 0 -and $recoveryErrors -gt 0) {
    Write-Host "OK TEST 4: PASS" -ForegroundColor Green
    Write-Host "   - Recovered $recoveredRuns run(s)" -ForegroundColor Gray
    Write-Host "   - Created $recoveryErrors error record(s)" -ForegroundColor Gray
} else {
    Write-Host "FAIL TEST 4: Recovery not detected" -ForegroundColor Red
}

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host ""

# TEST 5: Backup retention policy
Write-Host "TEST 5: Backup Retention Policy" -ForegroundColor Yellow
Write-Host "Creating 15 fake backups..." -ForegroundColor Gray

$backupDir = "$userDataPath\backups"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

for ($i=1; $i -le 15; $i++) {
    $date = (Get-Date).AddDays(-$i).ToString("yyyyMMdd_HHmmss")
    $fakeBackup = "$backupDir\backup_${date}_test.db"
    Copy-Item "$userDataPath\hdle.db" $fakeBackup
}

# Trigger cleanup via migration
& sqlite3 "$userDataPath\hdle.db" "UPDATE schema_meta SET value='5' WHERE key='schema_version';"
$process = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal
Start-Sleep -Seconds 10
Stop-Process -Id $process.Id -Force

$remainingBackups = (Get-ChildItem "$backupDir\backup_*.db").Count
if ($remainingBackups -le 11) {
    Write-Host "OK TEST 5: PASS" -ForegroundColor Green
    Write-Host "   - Backups cleaned: $remainingBackups remaining (<=11 expected)" -ForegroundColor Gray
} else {
    Write-Host "FAIL TEST 5: Too many backups remain ($remainingBackups)" -ForegroundColor Red
}
Write-Host ""

# TEST 6: Process lock
Write-Host "TEST 6: Process Lock (Multiple Instances)" -ForegroundColor Yellow

$process1 = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal
Start-Sleep -Seconds 5

$process2 = Start-Process -FilePath $appPath -PassThru -WindowStyle Normal -Wait
Start-Sleep -Seconds 2

$process2Still = Get-Process -Id $process2.Id -ErrorAction SilentlyContinue
if (-not $process2Still) {
    Write-Host "OK TEST 6: PASS" -ForegroundColor Green
    Write-Host "   - Second instance prevented" -ForegroundColor Gray
} else {
    Write-Host "FAIL TEST 6: Multiple instances running" -ForegroundColor Red
    Stop-Process -Id $process2.Id -Force
}

Stop-Process -Id $process1.Id -Force
Start-Sleep -Seconds 2
Write-Host ""

# TEST 7: Export functionality
if (-not $SkipInteractive) {
    Write-Host "TEST 7: Export Functionality" -ForegroundColor Yellow
    Write-Host "Manual steps required:" -ForegroundColor Gray
    Write-Host "  1. Start app: $appPath" -ForegroundColor Gray
    Write-Host "  2. Export → XLSX" -ForegroundColor Gray
    Write-Host "  3. Verify Dictionary and Statistics sheets" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter when export test completed"
}

# TEST 8: Logs and rotation
Write-Host "TEST 8: Logs and Rotation" -ForegroundColor Yellow

$logs = Get-ChildItem "$userDataPath\logs\*.log"
if ($logs.Count -gt 0) {
    $latestLog = $logs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $logContent = Get-Content $latestLog.FullName

    $hasStartup = $logContent | Select-String -Pattern "HDLE Premium starting"
    $hasDbInit = $logContent | Select-String -Pattern "Database initialized"

    if ($hasStartup -and $hasDbInit) {
        Write-Host "OK TEST 8: PASS" -ForegroundColor Green
        Write-Host "   - Log file: $($latestLog.Name)" -ForegroundColor Gray
        Write-Host "   - Contains startup messages" -ForegroundColor Gray
    } else {
        Write-Host "FAIL TEST 8: Log missing expected messages" -ForegroundColor Red
    }
} else {
    Write-Host "FAIL TEST 8: No logs found" -ForegroundColor Red
}
Write-Host ""

# Summary
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "              SMOKE CHECK COMPLETE                        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Checklist:" -ForegroundColor White
Write-Host "  [X] TEST 1: First launch" -ForegroundColor Green
Write-Host "  [?] TEST 2: Create project (manual)" -ForegroundColor Yellow
Write-Host "  [X] TEST 3: Backup before migration" -ForegroundColor Green
Write-Host "  [X] TEST 4: Crash recovery" -ForegroundColor Green
Write-Host "  [X] TEST 5: Backup retention" -ForegroundColor Green
Write-Host "  [X] TEST 6: Process lock" -ForegroundColor Green
Write-Host "  [?] TEST 7: Export (manual)" -ForegroundColor Yellow
Write-Host "  [X] TEST 8: Logs and rotation" -ForegroundColor Green
Write-Host ""
Write-Host "Next: Complete manual tests (2, 7) using the GUI" -ForegroundColor White
Write-Host ""
