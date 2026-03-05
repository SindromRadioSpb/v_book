# QA Test Gates (Variant A)

## Policy

Variant A is the default for development and PATCH work.

- Fast Gate: required before/after PATCH work.
- Smoke/Env Gate: separate, non-blocking for PATCH by default.
- Full/Release Gate: required for packaging/release decisions.

This prevents env-only smoke failures from blocking scaling patches while keeping correctness checks strict.

## Gate Definitions

### 1) Fast Gate (required for PATCH work)

Scope:
- deterministic prebuild validation (no export/import side effects)
- deterministic core regression suite (security, DB/WAL, FTS, write-gate, migration-lock path)

Command:

```powershell
.\scripts\run_fast_gates.ps1
```

Equivalent manual commands:

```powershell
.\.venv\Scripts\python.exe scripts/prebuild_validate.py --skip-export-import
$tmp="J:\Project_Vibe\V_book\.tmp_pytest_temp"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TEMP=$tmp; $env:TMP=$tmp; $env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_security.py `
  tests/test_task12_fts_nlp.py `
  tests/test_task13_trigger_sync.py `
  tests/test_db_retry.py `
  tests/test_sqlite_busy_retry.py `
  tests/test_write_gate.py `
  tests/test_translation_admin_write_gate.py `
  tests/test_import_chunking_write_gate.py `
  tests/test_db_migration_lock_path.py `
  -m "not smoke and not env"
```

### 2) Smoke/Env Gate (separate)

Scope:
- smoke scenarios that require explicit DB/input artifacts
- runs in isolated temp runtime to avoid writing to real AppData

Command:

```powershell
.\scripts\run_smoke_gates.ps1 -SmokeDbPath "J:\path\to\smoke_source.db"
```

Equivalent manual command:

```powershell
$env:SMOKE_DB_PATH="J:\path\to\smoke_source.db"
$tmp="J:\Project_Vibe\V_book\.tmp_pytest_temp\smoke"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TEMP=$tmp; $env:TMP=$tmp; $env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests/smoke -m "smoke and env" -vv
```

### 3) Full/Release Gate (required for packaging/release)

Scope:
- full prebuild validation
- full canonical pytest tree under `tests/`
- smoke/env gate
- packaging smoke flow

Recommended command sequence:

```powershell
.\.venv\Scripts\python.exe scripts/prebuild_validate.py
.\.venv\Scripts\python.exe -m pytest -q tests
.\scripts\run_smoke_gates.ps1 -SmokeDbPath "J:\path\to\smoke_source.db"
.\scripts\run_packaged_smoke.ps1
```

## Determinism Rules

- Canonical pytest collection is `tests/` (configured in `pytest.ini`).
- Markers are explicit: `unit`, `integration`, `smoke`, `env`, `serial`.
- Smoke fixtures copy source DB to a per-run temp location.
- Smoke fixtures redirect `LOCALAPPDATA`, `APPDATA`, `HDLE_DATA_ROOT`, and migration lock dir to temp.
- Smoke tests must never write lock files or settings into real user directories.

## GO / NO-GO Policy

- GO for PATCH work: Fast Gate green.
- NO-GO for PATCH work: Fast Gate red.
- GO for release: Full/Release Gate green (including smoke/env + packaging smoke).
