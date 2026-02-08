# GPU Processing Script for Hebrew Wikipedia Reference Corpus
# This script runs NLP processing with GPU acceleration

param(
    [string]$DbPath = "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db",
    [string]$ProjectName = "Hebrew Wikipedia Baseline",
    [switch]$UseGpu = $true,
    [int]$BatchSize = 100
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Hebrew Wikipedia GPU Processing" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Database:    $DbPath" -ForegroundColor Yellow
Write-Host "Project:     $ProjectName" -ForegroundColor Yellow
Write-Host "GPU:         $UseGpu" -ForegroundColor Yellow
Write-Host "Batch size:  $BatchSize" -ForegroundColor Yellow
Write-Host ""

# Check if database exists
if (-not (Test-Path $DbPath)) {
    Write-Host "[ERROR] Database not found: $DbPath" -ForegroundColor Red
    exit 1
}

# Check GPU availability
Write-Host "Checking GPU availability..." -ForegroundColor Cyan
& "J:\Project_Vibe\V_book\.venv_gpu\Scripts\python.exe" -c @"
import torch
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
else:
    print('WARNING: CUDA not available! Processing will be SLOW.')
"@

Write-Host ""
$confirm = Read-Host "Start NLP processing? This will take 12-21 hours. (y/n)"
if ($confirm -ne 'y') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Starting NLP processing..." -ForegroundColor Green
Write-Host "You can monitor progress in another terminal:" -ForegroundColor Cyan
Write-Host "  tail -f M:\V_book\HDLE_Processing\logs\hdle.log" -ForegroundColor Gray
Write-Host ""

# Run processing
$args = @(
    "J:\Project_Vibe\V_book\scripts\process_reference_corpus.py",
    "--db-path", $DbPath,
    "--project-name", $ProjectName,
    "--batch-size", $BatchSize
)

if ($UseGpu) {
    $args += "--use-gpu"
}

& "J:\Project_Vibe\V_book\.venv_gpu\Scripts\python.exe" @args

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "NLP Processing Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next step: Extract terms" -ForegroundColor Yellow
Write-Host "  .\scripts\run_extract_terms.ps1" -ForegroundColor Gray
