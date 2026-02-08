# Verify and Prepare Release Script

param(
    [string]$DbPath = "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db",
    [string]$ProjectName = "Hebrew Wikipedia Baseline",
    [string]$Version = (Get-Date -Format "yyyyMMdd")
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Verify & Prepare Release" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Verify
Write-Host "Step 1: Verifying database..." -ForegroundColor Green
& "J:\Project_Vibe\V_book\.venv_gpu\Scripts\python.exe" `
    "J:\Project_Vibe\V_book\scripts\verify_reference_corpus.py" `
    --db-path $DbPath `
    --project-name $ProjectName

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Verification failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Step 2: Preparing release files..." -ForegroundColor Green
& "J:\Project_Vibe\V_book\.venv_gpu\Scripts\python.exe" `
    "J:\Project_Vibe\V_book\scripts\prepare_release_db.py" `
    --db-path $DbPath `
    --version $Version

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Release Preparation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Files ready in: M:\V_book\HDLE_Processing\" -ForegroundColor Yellow
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Upload hewiki_ref_processed_v$Version.db to GitHub Release" -ForegroundColor Gray
Write-Host "  2. Update manifest.py with the manifest entry from output" -ForegroundColor Gray
Write-Host "  3. Test download on clean machine" -ForegroundColor Gray
