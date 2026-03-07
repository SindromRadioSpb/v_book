#Requires -Version 5.1
<#
.SYNOPSIS
    Запускает codex review --uncommitted с изолированным CODEX_HOME и стабильным IPv4.
.DESCRIPTION
    Фиксирует:
    1. IPv6-нестабильность: NODE_OPTIONS=--dns-result-order=ipv4first
    2. CODEX_HOME — repo-local (.codex_home рядом со скриптом), не смешивает сессии других проектов
    3. Логирует вывод в build\logs\codex_review_latest.log
    4. Пути вычисляются динамически от $PSScriptRoot
.EXAMPLE
    .\scripts\run_codex_review.ps1
.NOTES
    Откат: удалить этот файл и .codex_home\config.toml.
    Все переменные окружения выставляются только в рамках этого процесса.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# ---------- пути (динамические) ----------
$repoRoot  = Split-Path -Parent $PSScriptRoot   # .../V_book/scripts -> .../V_book
$codexHome = Join-Path $repoRoot ".codex_home"
$logDir    = Join-Path $repoRoot "build\logs"
$logFile   = Join-Path $logDir   "codex_review_latest.log"

# Ищем codex.cmd в PATH, затем в npm-директории пользователя (fallback)
$codexCmd = $null
$found = Get-Command "codex.cmd" -ErrorAction SilentlyContinue
if ($found) {
    $codexCmd = $found.Source
} else {
    $npmFallback = Join-Path $env:APPDATA "npm\codex.cmd"
    if (Test-Path $npmFallback) { $codexCmd = $npmFallback }
}

if (-not $codexCmd) {
    Write-Error "codex.cmd not found in PATH or npm directory. Install via: npm install -g @openai/codex"
    exit 1
}

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# ---------- env (process-scoped, не постоянные) ----------
$savedCodexHome    = $env:CODEX_HOME
$env:CODEX_HOME    = $codexHome

# IPv4-приоритет: исправляет stream disconnected на Windows через IPv6.
# Node.js 18+ предпочитает IPv6 (RFC 6724), что вызывает дропы длинных SSE-потоков
# на ряде ISP. Форсируем IPv4 только внутри этого процесса.
$savedNodeOpts     = $env:NODE_OPTIONS
$env:NODE_OPTIONS  = "--dns-result-order=ipv4first"

# ---------- banner ----------
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$header = @"
=== codex review --uncommitted ===
Timestamp    : $ts
CODEX_HOME   : $env:CODEX_HOME
NODE_OPTIONS : $env:NODE_OPTIONS
Codex cmd    : $codexCmd
Repo         : $repoRoot
=================================
"@

Write-Host $header
$header | Out-File -FilePath $logFile -Encoding UTF8

# ---------- run ----------
Write-Host "[INFO] Starting review... (log: $logFile)"

& $codexCmd review --uncommitted 2>&1 | Tee-Object -FilePath $logFile -Append

$exitCode = $LASTEXITCODE

# ---------- restore env ----------
if ($null -eq $savedNodeOpts) {
    Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
} else {
    $env:NODE_OPTIONS = $savedNodeOpts
}
if ($null -eq $savedCodexHome) {
    Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue
} else {
    $env:CODEX_HOME = $savedCodexHome
}

# ---------- result ----------
# exit code 1 от codex может быть только cleanup-предупреждением (stale tmp dirs).
# Если review получил task_complete с ответом — это успех.
$footer = "`n=== Exit code: $exitCode | $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
Write-Host $footer
$footer | Out-File -FilePath $logFile -Append -Encoding UTF8

exit $exitCode
