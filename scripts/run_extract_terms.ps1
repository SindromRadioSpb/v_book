# Term Extraction Script for Hebrew Wikipedia Reference Corpus

param(
    [string]$DbPath = "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db",
    [string]$ProjectName = "Hebrew Wikipedia Baseline"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Hebrew Wikipedia Term Extraction" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Database:    $DbPath" -ForegroundColor Yellow
Write-Host "Project:     $ProjectName" -ForegroundColor Yellow
Write-Host ""

# Check if database exists
if (-not (Test-Path $DbPath)) {
    Write-Host "[ERROR] Database not found: $DbPath" -ForegroundColor Red
    exit 1
}

Write-Host "Starting term extraction..." -ForegroundColor Green
Write-Host "This will take 3-5 hours." -ForegroundColor Cyan
Write-Host ""

# Run extraction
& "J:\Project_Vibe\V_book\.venv_gpu\Scripts\python.exe" `
    "J:\Project_Vibe\V_book\scripts\extract_reference_terms.py" `
    --db-path $DbPath `
    --project-name $ProjectName

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Term Extraction Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next step: Verify and prepare release" -ForegroundColor Yellow
Write-Host "  .\scripts\run_verify_and_release.ps1" -ForegroundColor Gray
