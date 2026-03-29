# Release Notes — HDLE Premium v1.0.1

**Release Date:** 2026-03-29  
**Previous repository release baseline:** `v1.0.0` (`ba252361b13fd52b812f663176338ddcbd9dcf03`)

## Summary

`v1.0.1` is a stabilization and product-hardening release on top of the last shipped
repository release `v1.0.0`.

Compared with `v1.0.0`, this release closes the most important Windows/runtime and
project-exchange gaps that were still blocking a trustworthy release-facing workflow:

- packaged Hebrew payload delivery is now product-owned and verified
- packaged Stanza/Torch runtime is now release-green
- frozen ONNX helper import path is hardened
- runtime provenance is promoted into schema-backed fields for new runs
- project export is now a stage-based, artifact-validated product pipeline
- project import is now a stage-based, verification-backed product pipeline

## What Changed Since v1.0.0

### 1. Packaged NLP Runtime Is Now Release-Green

- bundled Hebrew Stanza payload is staged and shipped inside the frozen artifact
- packaged runtime ownership is explicit and operator-visible:
  - `bundled_packaged`
  - `bundled_dev`
  - `legacy_cache`
  - `repaired_managed`
- frozen Torch bootstrap now runs early enough for packaged `stanza` probe/worker startup
- packaged release smoke now passes with enforced bundled ownership

### 2. Frozen ONNX Helper Import Path Is Fixed

- packaged `HDLE_ONNX_Probe.exe` no longer stalls on inherited Hugging Face cache-path probing
- packaged `--self-check import` and `--self-check health` now complete truthfully for the ONNX helper path

### 3. Runtime Provenance Became Schema-Backed

- new `ProcessorRun` rows now store runtime provenance in dedicated fields
- the legacy machine-readable envelope in `ProcessorRun.note` remains as compatibility fallback
- debug/smoke paths now prefer schema-backed provenance and fall back to legacy note data when needed

### 4. Project Export Is Product-Closed

- export now has stable stage IDs and structured stage history
- long final ZIP/checksum phases are no longer silent
- export success now requires artifact validation:
  - bundle structure
  - checksums
  - payload `quick_check`
- interrupted export no longer leaves a misleading final `.hdleproj`

### 5. Project Import Is Product-Closed

- import now has stable stage IDs and structured stage history
- bundle validation and payload `quick_check` run before destructive DB mutation
- import reports stage-aware failures for invalid/incomplete bundles
- import success now requires post-import verification of the imported project and key row counts
- cleanup outcome is now surfaced explicitly instead of being only best-effort and implicit

## Operator-Facing Impact

- project bundle workflows are now more trustworthy:
  - export success means a validated artifact exists
  - import success means the imported project passed readback verification
- runtime diagnostics are more truthful across packaged surfaces:
  - Resources Manager
  - Health Check
  - Documents runtime detail
- failure messages are now more actionable for interrupted/corrupted bundle selection and packaged runtime issues

## Compatibility

- existing bundle format remains compatible
- import/export core contract is hardened without redesigning the format
- legacy `ProcessorRun.note` provenance remains readable

## Notable Residual Non-Blockers

- very large project export and import still take noticeable time on heavy reference data
- these phases are now explicit and diagnosable rather than silent or misleading
- Resources Manager still provides truthful diagnostics and repair routing, not a full install wizard

## Suggested Verification For This Release

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_project_exchange.py tests\test_project_exchange_preflight.py tests\test_project_exchange_dialogs.py tests\test_heavy_worker_slot_guard.py tests\test_workspace_app_window_contract.py -q
.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --force-hostile-inprocess --require-source-kind bundled_packaged --require-bundled-source
.\dist\HDLE_Premium\HDLE_Premium.exe --self-check import
.\dist\HDLE_Premium\HDLE_Premium.exe --self-check health
```

## Git Summary Against v1.0.0

- baseline tag: `v1.0.0`
- comparison range: `v1.0.0..v1.0.1`
- primary release themes:
  - packaged runtime hardening
  - runtime provenance promotion
  - project export/import product closure
  - validation and semantic-contract expansion
