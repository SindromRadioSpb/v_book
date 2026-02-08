# Run GPU Processing (Batch Optimized) - HDLE Premium
# =====================================================
# Обрабатывает референсный корпус с оптимизацией для избежания database lock
#
# Оптимизации:
# - Один ProcessorRun для всего батча (не 387k записей)
# - Commit только после каждого документа
# - Нет множественных commits внутри обработки
# - Быстрее и безопаснее для SQLite

param(
    [string]$DbPath = "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db",
    [string]$ProjectName = "Hebrew Wikipedia Baseline",
    [switch]$UseGPU = $true,
    [int]$BatchSize = 100
)

Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host "  HDLE Premium - GPU Processing (Batch Optimized)" -ForegroundColor Cyan
Write-Host "=" -ForegroundColor Cyan -NoNewline
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host ""

# Check if virtual environment exists
$projectRoot = Join-Path $PSScriptRoot ".."
$venvPath = Join-Path $projectRoot ".venv_gpu"
if (-not (Test-Path $venvPath)) {
    Write-Host "ERROR: Virtual environment not found at: $venvPath" -ForegroundColor Red
    Write-Host "Please create it first with: python -m venv .venv_gpu" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& $activateScript

# Check if database exists
if (-not (Test-Path $DbPath)) {
    Write-Host "ERROR: Database not found at: $DbPath" -ForegroundColor Red
    exit 1
}

# Display settings
Write-Host "Settings:" -ForegroundColor Green
Write-Host "  Database:    $DbPath" -ForegroundColor White
Write-Host "  Project:     $ProjectName" -ForegroundColor White
Write-Host "  GPU:         $UseGPU" -ForegroundColor White
Write-Host "  Batch size:  $BatchSize (commit every N documents)" -ForegroundColor White
Write-Host ""

# Check GPU availability
if ($UseGPU) {
    Write-Host "Checking GPU availability..." -ForegroundColor Yellow
    $gpuCheck = python -c "import torch; print('GPU Available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
    Write-Host $gpuCheck -ForegroundColor Cyan
    Write-Host ""
}

# Estimate time
Write-Host "Estimated processing time:" -ForegroundColor Magenta
Write-Host "  - With GPU: ~12-18 hours for 387k documents" -ForegroundColor White
Write-Host "  - Progress logged every $BatchSize documents" -ForegroundColor White
Write-Host ""

# Confirm
Write-Host "Press any key to start processing (Ctrl+C to cancel)..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Write-Host ""

# Build command
$scriptPath = Join-Path $PSScriptRoot "process_reference_corpus_batch.py"
$cmd = "python `"$scriptPath`" --db-path `"$DbPath`" --project-name `"$ProjectName`" --batch-size $BatchSize"
if ($UseGPU) {
    $cmd += " --use-gpu"
}

# Run processing
Write-Host "=" -ForegroundColor Green -NoNewline
Write-Host ("=" * 79) -ForegroundColor Green
Write-Host "  Starting Processing..." -ForegroundColor Green
Write-Host "=" -ForegroundColor Green -NoNewline
Write-Host ("=" * 79) -ForegroundColor Green
Write-Host ""

try {
    Invoke-Expression $cmd
    $exitCode = $LASTEXITCODE

    Write-Host ""
    Write-Host "=" -ForegroundColor Green -NoNewline
    Write-Host ("=" * 79) -ForegroundColor Green
    if ($exitCode -eq 0) {
        Write-Host "  Processing Completed Successfully!" -ForegroundColor Green
    } else {
        Write-Host "  Processing Completed with Errors (Exit Code: $exitCode)" -ForegroundColor Yellow
    }
    Write-Host "=" -ForegroundColor Green -NoNewline
    Write-Host ("=" * 79) -ForegroundColor Green
    Write-Host ""

    # Show log location
    $logDir = Split-Path $DbPath -Parent | Join-Path -ChildPath "logs"
    if (Test-Path $logDir) {
        $logFile = Get-ChildItem $logDir -Filter "hdle*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($logFile) {
            Write-Host "Log file: $($logFile.FullName)" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "To view log in real-time:" -ForegroundColor Yellow
            Write-Host "  Get-Content `"$($logFile.FullName)`" -Wait -Tail 50" -ForegroundColor White
        }
    }

    exit $exitCode

} catch {
    Write-Host ""
    Write-Host "ERROR: Processing failed" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
