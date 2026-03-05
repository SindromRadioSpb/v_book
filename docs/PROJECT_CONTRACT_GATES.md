# HDLE Premium Project Contract: Test Gates and GO/NO-GO

## Canonical Policy

This document is the canonical contract for development and release gate decisions.

- Variant A is mandatory for PATCH/scaling work.
- Release GO is a separate, stricter track and must not block Variant A PATCH flow.

Related docs:
- `docs/QA_TEST_GATES.md` (operational details)
- `docs/RELEASE_GATE_STABILIZATION.md` (release backlog and closure criteria)

## Gate Definitions

### 1) Fast Gate (Variant A, required for PATCH work)

Purpose:
- deterministic prebuild validation
- deterministic core regression checks

Command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_fast_gates.ps1
```

### 2) Smoke Gate (isolated, recommended for PATCH work)

Purpose:
- smoke/env checks in isolated runtime
- must not write lock files/settings into real user AppData

Command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_smoke_gates.ps1 -SmokeDbPath "J:\Project_Vibe\V_book\test_data\test.db"
```

### 3) Release Core Gate (strict, release track)

Purpose:
- full deterministic diagnostics for canonical pytest tree
- failure inventory for stabilization planning

Command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_release_gate_diagnostic.ps1
```

### 4) Packaged Smoke Gate (strict, release track)

Purpose:
- verify packaged executable behavior
- verify build traceability fields are visible and consistent

Command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_packaged_smoke.ps1
```

## GO / NO-GO Rules

### Scaling PATCH GO (Variant A)

- GO: Fast Gate PASS.
- Recommended confidence: Fast Gate PASS + Smoke Gate PASS (isolated).
- NO-GO: Fast Gate FAIL.

### Release / Installer GO

- GO only if all are green:
  - Release Core Gate PASS
  - Packaged Smoke Gate PASS
  - Traceability PASS (version + commit + dirty + built_at verified in app/log/self-check and release evidence)
- Otherwise: Release GO = NO-GO (stabilization track remains active).

## Canonical Commands (copy-paste)

```powershell
cd /d J:\Project_Vibe\V_book
powershell -ExecutionPolicy Bypass -File scripts\run_fast_gates.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_smoke_gates.ps1 -SmokeDbPath "J:\Project_Vibe\V_book\test_data\test.db"
powershell -ExecutionPolicy Bypass -File scripts\run_release_gate_diagnostic.ps1
```

## Required Artifacts

- `build\logs\fast_gate_latest.log`
- `build\logs\smoke_gate_latest.log`
- `build\logs\release_gate_latest.txt`
- `build\logs\release_gate_inventory.md`

## Never Re-Litigate Clause

- Variant A is the only required gate for PATCH/scaling development.
- Release GO is independent and remains blocked until release stabilization criteria are closed.
