param(
    [string]$DbPath = ""
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path "build\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "build\verify" | Out-Null

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [string]$LogPath
    )

    Write-Host "== $Name =="
    & $Action *>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed (exit code: $LASTEXITCODE). Log: $LogPath"
    }
    Write-Host "[OK] $Name"
}

Invoke-Step -Name "Spec contract tests" -LogPath "build\logs\prebuild_spec_contract.log" -Action {
    python -m pytest `
        tests/test_installer_spec_contract_shape.py `
        tests/test_installer_spec_includes_onnx_probe.py `
        tests/test_installer_spec_onnxruntime_hiddenimport.py `
        -q
}

Invoke-Step -Name "Frozen ONNX helper/self-check tests" -LogPath "build\logs\prebuild_frozen_onnx_tests.log" -Action {
    python -m pytest `
        tests/test_onnx_probe_contract.py `
        tests/test_main_self_check_helpers.py `
        tests/test_phonikud_shim_onnx.py `
        tests/test_phonikud_bridge_calls_helper_in_frozen.py `
        -q
}

Invoke-Step -Name "Dev ONNX import probe" -LogPath "build\logs\prebuild_onnx_probe_import.log" -Action {
    python -m app.tools.onnx_probe --mode import --out "build\verify\prebuild_onnx_import.json"
}

if ($DbPath) {
    Invoke-Step -Name "Prebuild validate (reference-ro)" -LogPath "build\logs\prebuild_reference_ro.log" -Action {
        python scripts/prebuild_validate.py --profile reference-ro --skip-quick-check --db-path "$DbPath"
    }
}

Write-Host "PASS: prebuild fast gates completed."
