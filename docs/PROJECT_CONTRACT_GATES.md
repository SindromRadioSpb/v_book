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

### 5) Write-Gate Perf Gate (optional, evidence track)

Purpose:
- deterministic 3-run write-gate benchmark + budget classification (PASS/WARN/FAIL)
- produce machine-readable and markdown evidence for scaling patches

Command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_write_gate_perf_gate.ps1
```

Policy:
- optional by default and does not block Variant A PATCH flow.
- can be opt-in from Fast Gate with `HDLE_ENABLE_PERF_GATE=1`.
- result handling when enabled from Fast Gate:
  - exit `0` (PASS): continue
  - exit `2` (WARN): continue with warning and report link
  - exit `1` (FAIL): fail Fast Gate

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
powershell -ExecutionPolicy Bypass -File scripts\run_write_gate_perf_gate.ps1
```

## Required Artifacts

- `build\logs\fast_gate_latest.log`
- `build\logs\smoke_gate_latest.log`
- `build\logs\release_gate_latest.txt`
- `build\logs\release_gate_inventory.md`
- `build\logs\write_gate_perf_gate_latest.log` (optional perf gate)
- `build\logs\write_gate_budget_report_latest.md` (optional perf gate)

## Never Re-Litigate Clause

- Variant A is the only required gate for PATCH/scaling development.
- Release GO is independent and remains blocked until release stabilization criteria are closed.
