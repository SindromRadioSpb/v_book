# Release Ship Gate Phase 4

## Scope

Bounded release-facing follow-up after Ship Gate Phase 3:

- fix packaged ONNX probe model discovery in fresh `dist`
- verify that the frozen payload includes the required offline Phonikud model
- rerun frozen self-check contract on rebuilt artifacts

This wave does **not** reopen generic cold/perf work, lower-layer DB recovery,
or installer redesign.

## Problem

After rebuilding fresh release artifacts from current `main`, the packaged
frozen helper:

- `dist\HDLE_Premium\HDLE_ONNX_Probe.exe`

failed immediately with:

- `Phonikud ONNX model path is not configured or not found.`

Root cause from repo/build evidence:

1. `hdle_premium_installer.spec` did not explicitly bundle the staged ONNX
   model from:
   - `installer\resources\local_models\phonikud\phonikud-1.0.int8.onnx`
2. bundled resources in the fresh PyInstaller output were resolved under:
   - `dist\HDLE_Premium\_internal\resources\...`
   but runtime bundled-resource lookup still assumed:
   - `dist\HDLE_Premium\resources\...`

## Implementation

### Runtime

- `app/infra/resource_paths.py`
  - `ResourcePaths.resolve_bundled_resources_root()` now prefers:
    - `<exe_root>\_internal\resources`
    when running in frozen mode and that directory exists
- `app/tools/onnx_probe.py`
  - default model discovery now checks both:
    - writable runtime models root
    - bundled models root from `ResourcePaths`

### Packaging

- `hdle_premium_installer.spec`
  - now explicitly bundles staged ONNX models into:
    - `resources/models/phonikud/`

### Tests

- `tests/test_resource_paths.py`
  - locks the frozen `_internal\resources` bundled-root preference
- `tests/test_onnx_probe_contract.py`
  - locks bundled-model discovery fallback
- `tests/test_installer_spec_contract_shape.py`
  - locks explicit phonikud ONNX data inclusion in the spec

## Rebuild + verification evidence

Fresh rebuild completed successfully with:

```powershell
powershell -ExecutionPolicy Bypass -File .\rebuild.ps1 -SkipFastGates
```

Fresh logs:

- `build\logs\pyinstaller_20260315_232941.log`
- `build\logs\inno_20260315_233617.log`

Fresh frozen helper probe:

```powershell
& "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_ONNX_Probe.exe" --out "J:\Project_Vibe\V_book\build\verify_dist\probe_dist_manual.json"
```

Result:

- `ok = true`
- `details = real_inference`
- `model_path = J:\Project_Vibe\V_book\dist\HDLE_Premium\_internal\resources\models\phonikud\phonikud-1.0.int8.onnx`

Fresh frozen verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_frozen_health.ps1 -DistRoot "J:\Project_Vibe\V_book\dist\HDLE_Premium" -DbPath "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" -OutDir "J:\Project_Vibe\V_book\build\verify_dist"
```

Result:

- `PASS: frozen dist checks completed.`

Artifacts:

- `build\verify_dist\probe_dist.json`
- `build\verify_dist\import_dist.json`
- `build\verify_dist\health_dist.json`
- `build\verify_dist\db_open_dist.json`
- `build\verify_dist\frozen_health_summary.json`
- `build\verify_dist\build_meta_dist.txt`

## Decision

Ship Gate Phase 4 is closed.

What this means:

- fresh `dist` now passes the frozen ONNX/runtime contract again
- packaged phonikud model discovery is no longer the active release blocker
- remaining release work is now outside this bounded fix:
  - installed-app smoke on fresh installer
  - clean VM smoke
  - final release sign-off evidence
