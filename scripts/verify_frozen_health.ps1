param(
    [string]$DistRoot = "J:\Project_Vibe\V_book\dist\HDLE_Premium",
    [string]$DbPath = "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db",
    [string]$OutDir = "J:\Project_Vibe\V_book\build\verify"
)

$ErrorActionPreference = "Stop"

$mainExe = Join-Path $DistRoot "HDLE_Premium.exe"
$probeExe = Join-Path $DistRoot "HDLE_ONNX_Probe.exe"

if (-not (Test-Path $mainExe)) {
    throw "Missing executable: $mainExe"
}
if (-not (Test-Path $probeExe)) {
    throw "Missing executable: $probeExe"
}
if (-not (Test-Path $DbPath)) {
    throw "Missing DB path: $DbPath"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$probeOut = Join-Path $OutDir "probe_dist.json"
$importOut = Join-Path $OutDir "import_dist.json"
$healthOut = Join-Path $OutDir "health_dist.json"
$buildMetaOut = Join-Path $OutDir "build_meta_dist.txt"

function Invoke-SelfCheck {
    param(
        [string]$ExePath,
        [string]$ArgumentLine,
        [string]$OutPath,
        [string]$Label
    )

    Remove-Item -Force $OutPath -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $ExePath -ArgumentList $ArgumentLine -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "$Label self-check failed with exit code $($proc.ExitCode)"
    }
    if (-not (Test-Path $OutPath)) {
        throw "$Label self-check did not produce output file: $OutPath"
    }
}

Invoke-SelfCheck -ExePath $probeExe -ArgumentLine "--out `"$probeOut`"" -OutPath $probeOut -Label "Probe"
Invoke-SelfCheck -ExePath $mainExe -ArgumentLine "--self-check import --self-check-out `"$importOut`"" -OutPath $importOut -Label "Import"
Invoke-SelfCheck -ExePath $mainExe -ArgumentLine "--self-check health --db-path `"$DbPath`" --self-check-out `"$healthOut`"" -OutPath $healthOut -Label "Health"

$importPayload = Get-Content -Path $importOut -Raw | ConvertFrom-Json
$healthPayload = Get-Content -Path $healthOut -Raw | ConvertFrom-Json

if (-not $importPayload.build) {
    throw "Import self-check payload missing build metadata"
}
if (-not $healthPayload.build) {
    throw "Health self-check payload missing build metadata"
}

$importCommit = [string]$importPayload.build.commit
$healthCommit = [string]$healthPayload.build.commit
if ($importCommit -ne $healthCommit) {
    throw "Build commit mismatch between import and health self-check payloads ($importCommit vs $healthCommit)"
}

$importDirty = [string]$importPayload.build.dirty
$healthDirty = [string]$healthPayload.build.dirty
if ($importDirty -ne $healthDirty) {
    throw "Build dirty mismatch between import and health payloads ($importDirty vs $healthDirty)"
}

$importBuiltAt = [string]$importPayload.build.built_at_utc
$healthBuiltAt = [string]$healthPayload.build.built_at_utc
if ($importBuiltAt -ne $healthBuiltAt) {
    throw "Build timestamp mismatch between import and health payloads ($importBuiltAt vs $healthBuiltAt)"
}

$version = [string]$importPayload.build.version
$metaLines = @(
    "version=$version"
    "commit=$importCommit"
    "dirty=$importDirty"
    "built_at_utc=$importBuiltAt"
)
Set-Content -Path $buildMetaOut -Value $metaLines -Encoding UTF8

Write-Host "PASS: frozen dist checks completed."
Write-Host "Probe report:  $probeOut"
Write-Host "Import report: $importOut"
Write-Host "Health report: $healthOut"
Write-Host "Build metadata report: $buildMetaOut"
Write-Host "Build metadata: version=$version commit=$importCommit dirty=$importDirty built_at=$importBuiltAt"
