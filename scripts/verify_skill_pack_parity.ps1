param(
    [string]$CodexPack = "J:\Project_Vibe\V_book\.codex\skills\premium_desktop_pyqt_sqlite",
    [string]$AgentsPack = "J:\Project_Vibe\V_book\.agents\skills\premium_desktop_pyqt_sqlite"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RelativeFileMap {
    param([string]$Root)

    $resolvedRoot = (Resolve-Path $Root).Path
    $map = @{}
    Get-ChildItem -Path $resolvedRoot -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($resolvedRoot.Length).TrimStart('\')
        $map[$relative] = $_.FullName
    }
    return $map
}

if (-not (Test-Path $CodexPack -PathType Container)) {
    Write-Output "FAIL: missing canonical pack directory: $CodexPack"
    exit 1
}
if (-not (Test-Path $AgentsPack -PathType Container)) {
    Write-Output "FAIL: missing mirror pack directory: $AgentsPack"
    exit 1
}

$codexMap = Get-RelativeFileMap -Root $CodexPack
$agentsMap = Get-RelativeFileMap -Root $AgentsPack

$allRelative = @($codexMap.Keys + $agentsMap.Keys | Sort-Object -Unique)
$missingInAgents = @()
$missingInCodex = @()
$hashMismatches = @()

foreach ($relative in $allRelative) {
    if (-not $agentsMap.ContainsKey($relative)) {
        $missingInAgents += $relative
        continue
    }
    if (-not $codexMap.ContainsKey($relative)) {
        $missingInCodex += $relative
        continue
    }

    $codexHash = (Get-FileHash -Algorithm SHA256 -Path $codexMap[$relative]).Hash
    $agentsHash = (Get-FileHash -Algorithm SHA256 -Path $agentsMap[$relative]).Hash

    if ($codexHash -ne $agentsHash) {
        $hashMismatches += [PSCustomObject]@{
            RelativePath = $relative
            CodexHash    = $codexHash
            AgentsHash   = $agentsHash
        }
    }
}

if ($missingInAgents.Count -eq 0 -and $missingInCodex.Count -eq 0 -and $hashMismatches.Count -eq 0) {
    Write-Output ("OK: skill pack parity verified ({0} files)." -f $allRelative.Count)
    exit 0
}

Write-Output "FAIL: skill pack parity check failed."
if ($missingInAgents.Count -gt 0) {
    Write-Output "Missing in .agents:"
    $missingInAgents | ForEach-Object { Write-Output ("  - {0}" -f $_) }
}
if ($missingInCodex.Count -gt 0) {
    Write-Output "Missing in .codex:"
    $missingInCodex | ForEach-Object { Write-Output ("  - {0}" -f $_) }
}
if ($hashMismatches.Count -gt 0) {
    Write-Output "Hash mismatches:"
    $hashMismatches | ForEach-Object {
        Write-Output ("  - {0}" -f $_.RelativePath)
        Write-Output ("      codex : {0}" -f $_.CodexHash)
        Write-Output ("      agents: {0}" -f $_.AgentsHash)
    }
}

exit 1
