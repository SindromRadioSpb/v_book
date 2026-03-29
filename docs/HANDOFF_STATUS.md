# Handoff Status

## Current Task
- `task31`: product-grade NLP runtime management

## Current Phase
- Packaged runtime sign-off is complete for the currently scoped NLP runtime tracks.
- There is no active implementation blocker in the packaged Hebrew payload, packaged Stanza/Torch runtime, or packaged ONNX helper startup paths.
- The next optional provenance wave is now also complete for newly created `ProcessorRun` rows:
  - runtime provenance is dual-written into dedicated schema fields
  - the legacy `ProcessorRun.note` envelope remains the backward-compatible fallback

## Closed Tracks
- Bundled Hebrew payload delivery is complete for packaged release assembly.
- Managed runtime ownership truth remains explicit and stable:
  - `bundled_packaged`
  - `bundled_dev`
  - `legacy_cache`
  - `repaired_managed`
- Packaged Stanza/Torch runtime readiness remains release-green:
  - packaged `--stanza-probe` was previously confirmed on a clean managed root
  - packaged `--stanza-worker` was previously confirmed on the same bundled ownership contract
  - release smoke previously passed with `--require-source-kind bundled_packaged --require-bundled-source`
- The separate packaged ONNX helper startup issue is now closed:
  - `HDLE_ONNX_Probe.exe --mode import` succeeds in the rebuilt frozen artifact
  - packaged `HDLE_Premium.exe --self-check import` now reports `checks.onnxruntime_import.ok = true`
  - packaged `HDLE_Premium.exe --self-check health` now reports `frozen_onnx_probe.status = ok`
- Structured runtime provenance promotion is now complete for new runs:
  - `processor_run` now stores `configured_engine_id`, `effective_engine_id`, `fallback_used`, `runtime_reason_code`, `runtime_mode`, and `runtime_probe_summary_json`
  - single-document and batch processing both dual-write the dedicated fields and the legacy note envelope
  - compatibility reads still fall back to `ProcessorRun.note` for legacy rows

## Latest Confirmation
- The ONNX helper timeout root cause was localized to `app/tools/onnx_probe.py`:
  - the helper stalled inside `_ensure_hf_home()`
  - the stall happened before `import onnxruntime`
  - the trigger was an inherited `HF_HOME=F:\huggingface` path that was being write-probed during frozen startup
- Frozen ONNX helper bootstrap now treats an existing configured `HF_HOME` as read-first and only falls back to a local writable cache when the configured path is missing/unusable.
- This fix did not reopen or redesign the already-green packaged Stanza/Torch runtime path.
- Runtime provenance no longer depends only on `ProcessorRun.note` for newly created runs:
  - `ProcessService` now writes dedicated schema-backed provenance fields on single, batch, and snapshot-backfill runs
  - resumed legacy batch runs opportunistically gain the same dedicated fields without dropping the old note contract
  - debug/smoke paths now prefer schema fields and fall back to `note` for older rows

## Remaining Risks
- Resources Manager still does not provide a full guided install wizard; it provides truthful diagnostics and repair guidance only.
- The guided repair journey is coherent, but it is still rendered across multiple surfaces rather than one dedicated wizard.
- Historical `ProcessorRun` rows created before schema version `52` still rely on the legacy note envelope unless they are resumed or re-run.

## Next Step
- No packaged NLP runtime blocker is currently open.
- Runtime provenance promotion is no longer an open blocker.
- If a future release wave requires installer-path reconfirmation, rerun:
  - packaged `HDLE_Premium.exe --self-check import`
  - packaged `HDLE_Premium.exe --self-check health`
  - packaged Stanza release smoke on a clean `HDLE_DATA_ROOT`
