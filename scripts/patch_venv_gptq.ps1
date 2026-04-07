# patch_venv_gptq.ps1
# Run once after creating/recreating the venv to make HY-MT 7B GPTQ work on Windows.
# Safe to re-run: checks whether each patch is already applied.

param(
    [string]$VenvPath = "$PSScriptRoot\..\\.venv"
)

$ErrorActionPreference = "Stop"
$SitePackages = "$VenvPath\Lib\site-packages"

Write-Host "=== GPTQ venv patches ===" -ForegroundColor Cyan
Write-Host "Site-packages: $SitePackages"

# -------------------------------------------------------------------------
# Helper
# -------------------------------------------------------------------------
function Apply-Patch {
    param([string]$Label, [string]$FilePath, [string]$OldText, [string]$NewText)
    $content = Get-Content $FilePath -Raw -Encoding UTF8
    if ($content -like "*$NewText*") {
        Write-Host "  [SKIP] $Label — already applied" -ForegroundColor Yellow
        return
    }
    if (-not ($content -like "*$OldText*")) {
        Write-Host "  [WARN] $Label — old pattern not found (version changed?)" -ForegroundColor Red
        return
    }
    $patched = $content.Replace($OldText, $NewText)
    [System.IO.File]::WriteAllText($FilePath, $patched, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK]   $Label" -ForegroundColor Green
}

# -------------------------------------------------------------------------
# Step 1: Install gptqmodel (if missing)
# -------------------------------------------------------------------------
Write-Host "`n[1] Checking gptqmodel..." -ForegroundColor Cyan
$installed = & "$VenvPath\Scripts\python.exe" -c "import gptqmodel; print('ok')" 2>$null
if ($installed -eq "ok") {
    Write-Host "  [SKIP] gptqmodel already installed" -ForegroundColor Yellow
} else {
    $src = "\\wsl.localhost\Ubuntu\tmp\gptq_src\gptqmodel-6.0.3"
    if (-not (Test-Path $src)) {
        Write-Host "  [ERR] gptqmodel source not found at: $src" -ForegroundColor Red
        Write-Host "        Download from: https://github.com/ModelCloud/GPTQModel/releases/tag/v6.0.3" -ForegroundColor Red
        Write-Host "        Extract to: $src" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Installing gptqmodel from $src ..."
    & "$VenvPath\Scripts\pip.exe" install --no-deps $src
}

# -------------------------------------------------------------------------
# Step 2: Install optimum + helpers (if missing)
# -------------------------------------------------------------------------
Write-Host "`n[2] Checking optimum and helpers..." -ForegroundColor Cyan
$pkgs = @("optimum", "device_smi", "tokenicer", "defuser")
foreach ($pkg in $pkgs) {
    $ok = & "$VenvPath\Scripts\python.exe" -c "import $($pkg.Replace('-','_')); print('ok')" 2>$null
    if ($ok -eq "ok") {
        Write-Host "  [SKIP] $pkg already installed" -ForegroundColor Yellow
    } else {
        Write-Host "  Installing $pkg ..."
        & "$VenvPath\Scripts\pip.exe" install $pkg
    }
}

# -------------------------------------------------------------------------
# Patch 1: gptqmodel/quantization/config.py
# desc_act=True + act_group_aware=True raises ValueError — override instead
# -------------------------------------------------------------------------
Write-Host "`n[3] Patching gptqmodel/quantization/config.py..." -ForegroundColor Cyan
$gptqConfig = "$SitePackages\gptqmodel\quantization\config.py"

$old1 = @"
        if desc_act_enabled_by_user and act_group_aware_user_value is not None and act_group_aware_enabled_by_user:
            raise ValueError(
                "QuantizeConfig:: ``act_group_aware`` == ``True`` requires ``desc_act`` == ``False`` when both are explicitly set."
            )
"@

$new1 = @"
        if desc_act_enabled_by_user and act_group_aware_user_value is not None and act_group_aware_enabled_by_user:
            # Backward compat: pre-quantized GPTQ v1 models (e.g. HY-MT 7B) may have
            # desc_act=True in their saved config. Override act_group_aware instead of raising.
            self.act_group_aware = False
"@

Apply-Patch "gptqmodel desc_act+act_group_aware compat" $gptqConfig $old1 $new1

# -------------------------------------------------------------------------
# Patch 2: optimum/gptq/quantizer.py
# BACKEND.EXLLAMA_V1 removed in gptqmodel 6.0.3 — guard with getattr
# -------------------------------------------------------------------------
Write-Host "`n[4] Patching optimum/gptq/quantizer.py..." -ForegroundColor Cyan
$optimumQ = "$SitePackages\optimum\gptq\quantizer.py"

$old2 = "        if self.desc_act and self.backend == BACKEND.EXLLAMA_V1 and self.max_input_length is not None:"
$new2 = @"
        _exllama_v1 = getattr(BACKEND, "EXLLAMA_V1", None)
        if self.desc_act and _exllama_v1 is not None and self.backend == _exllama_v1 and self.max_input_length is not None:
"@

Apply-Patch "optimum EXLLAMA_V1 guard" $optimumQ $old2 $new2

# -------------------------------------------------------------------------
# Verify
# -------------------------------------------------------------------------
Write-Host "`n[5] Verification..." -ForegroundColor Cyan
$ver = & "$VenvPath\Scripts\python.exe" -c "import gptqmodel; print(gptqmodel.__version__)" 2>&1 | Select-String -NotMatch "WARN|INFO|Future"
Write-Host "  gptqmodel version: $ver" -ForegroundColor Green

Write-Host "`n=== Done. Run the app normally: ===" -ForegroundColor Cyan
Write-Host 'python -m app.main --db-path "..."'
