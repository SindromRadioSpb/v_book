# Codex Review — Troubleshooting Guide

> Repo: `J:\Project_Vibe\V_book`
> Дата: 2026-03-07
> Версия Codex: 0.107.0

---

## 1. Что было (root cause)

### Проблема: `stream disconnected before completion`

| # | Причина | Доказательство |
|---|---------|----------------|
| 1 | **IPv6-приоритет в Node.js 24** — `chatgpt.com` резолвился в `2a06:98c1:3100::6812:202f` (IPv6). Длинные SSE-потоки через IPv6 на Windows нестабильны на ряде ISP. | `node -e "dns.lookup('chatgpt.com', ...)"` → `family: 6` |
| 2 | **`model_reasoning_effort = "xhigh"`** в глобальном `~/.codex/config.toml` — увеличивает длительность streaming-ответа, повышая вероятность таймаута. | `~/.codex/config.toml` строка 3 |
| 3 | **`J:\Project_Vibe\V_book` не была в trusted projects** глобального конфига — без CODEX_HOME review запускался с `sandbox_policy: read-only` вместо `workspace-write`, что мешало model tool-calls. | Session log 01:25:24: `"sandbox_policy":{"type":"read-only"}` |
| 4 | **Нет локального CODEX_HOME** — при каждом запуске сессии кешировались в глобальный `~/.codex`, что создавало конкуренцию с другими проектами. | `git status`: `?? .codex_home/` только как untracked |

### Дополнительно обнаружено
- Ошибка `failed to clean up stale arg0 temp dirs` (exit code 1) — это **not fatal**; codex возвращает 1 из-за Windows-ограничения при удалении непустой tmp-директории. Review при этом **завершается успешно** с `task_complete`.

---

## 2. Что изменено

### 2.1 Новые файлы

| Файл | Что делает |
|------|------------|
| `scripts/run_codex_review.ps1` | Wrapper-скрипт: выставляет `CODEX_HOME` и `NODE_OPTIONS`, логирует, восстанавливает env после выхода |
| `.codex_home/config.toml` | Локальный конфиг Codex: `reasoning_effort = "high"` (не `xhigh`), V_book как trusted project, `sandbox_mode = "workspace-write"` |
| `build/logs/codex_review_latest.log` | Лог последнего прогона |
| `docs/CODEX_REVIEW_TROUBLESHOOTING.md` | Этот файл |

### 2.2 Изменённые файлы

| Файл | Изменение |
|------|-----------|
| `~/.codex/config.toml` | Добавлены `[projects."J:\\Project_Vibe\\V_book"]` и `[projects."\\\\?\\J:\\..."]` с `trust_level = "trusted"` |
| `.gitignore` | Добавлена строка `.codex_home/` (чтобы не коммитить auth токены и сессии) |

### 2.3 Ключевые настройки wrapper-скрипта

```powershell
$env:CODEX_HOME   = "$repoRoot\.codex_home"     # изолированный home
$env:NODE_OPTIONS = "--dns-result-order=ipv4first" # IPv4 вместо IPv6
```

---

## 3. Команды для запуска

### Рекомендуемый способ (через wrapper)

```powershell
cd J:\Project_Vibe\V_book
powershell -ExecutionPolicy Bypass -File scripts\run_codex_review.ps1
```

Лог: `J:\Project_Vibe\V_book\build\logs\codex_review_latest.log`

### Прямой способ (с ручными env-переменными)

```powershell
$env:CODEX_HOME   = "J:\Project_Vibe\V_book\.codex_home"
$env:NODE_OPTIONS = "--dns-result-order=ipv4first"
C:\Users\Win10_Game_OS\AppData\Roaming\npm\codex.cmd review --uncommitted
```

---

## 4. Результаты 2 прогонов (2026-03-07)

### Прогон 1 — 01:47:55–01:49:30

| Параметр | Значение |
|----------|----------|
| `sandbox_policy` | `workspace-write` (сеть включена) |
| `reasoning_effort` | `high` |
| `task_complete` | ✅ |
| `last_agent_message` | 1859 символов |
| Findings | P0: auth.json в git; P2: hardcoded paths в скрипте |
| `stream disconnected` | ❌ нет |

### Прогон 2 — 01:51:23–~01:52:30

| Параметр | Значение |
|----------|----------|
| `sandbox_policy` | `workspace-write` (сеть включена) |
| `reasoning_effort` | `high` |
| `task_complete` | ✅ |
| `last_agent_message` | 2629 символов |
| Findings | P0: auth.json; P1: sessions в git; P2: CODEX_HOME не восстанавливался |
| `stream disconnected` | ❌ нет |

---

## 5. Риски и ограничения

| Риск | Описание | Митигация |
|------|----------|-----------|
| `exit code 1` от codex | Из-за Windows-ошибки очистки tmp-dir (os error 145). Review при этом завершён успешно. | Проверять `task_complete` в сессионном файле, а не только exit code |
| auth.json в `.codex_home` | Содержит live OAuth-токены. НЕ должен попадать в git. | `.gitignore` уже добавлен |
| IPv6 может потребоваться | Если ISP блокирует IPv4-доступ к chatgpt.com (маловероятно) | Убрать `NODE_OPTIONS` из wrapper |
| `model_reasoning_effort = "xhigh"` остаётся в глобальном конфиге | Локальный `.codex_home/config.toml` переопределяет его через `CODEX_HOME`, но прямой запуск без wrapper всё равно использует `xhigh` | Запускать только через wrapper |
| Node.js обновление < 18 | Флаг `--dns-result-order` поддерживается с Node.js 16.4+. Текущая версия: 24.14.0. | Нет действий |

---

## 6. Откат

```powershell
# Удалить wrapper и локальный конфиг
Remove-Item "J:\Project_Vibe\V_book\scripts\run_codex_review.ps1"
Remove-Item "J:\Project_Vibe\V_book\.codex_home\config.toml"

# Восстановить глобальный конфиг из бэкапа (если нужно)
Copy-Item "C:\Users\Win10_Game_OS\.codex\config.toml.bak-20260304-230504" `
          "C:\Users\Win10_Game_OS\.codex\config.toml" -Force

# Удалить .codex_home из .gitignore (если нужно)
# (редактировать .gitignore вручную, убрать строку .codex_home/)
```

---

## 7. Диагностические команды

```powershell
# Проверить версию и статус логина
C:\Users\Win10_Game_OS\AppData\Roaming\npm\codex.cmd --version
C:\Users\Win10_Game_OS\AppData\Roaming\npm\codex.cmd login status

# Проверить DNS-резолюцию (должен вернуть IPv4 после NODE_OPTIONS)
$env:NODE_OPTIONS = "--dns-result-order=ipv4first"
node -e "const dns=require('dns'); dns.lookup('chatgpt.com',(e,a,f)=>console.log('family:',f,'addr:',a))"

# Проверить последний сессионный файл
$session = Get-ChildItem "J:\Project_Vibe\V_book\.codex_home\sessions" -Recurse -Filter "*.jsonl" |
    Sort-Object LastWriteTime | Select-Object -Last 1
Get-Content $session.FullName | ConvertFrom-Json | Where-Object { $_.payload.type -eq "task_complete" }
```
