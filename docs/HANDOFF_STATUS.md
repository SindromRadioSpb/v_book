# Handoff Status

## Current Task
- `task34`: corrective NLP processing / re-process transport hardening

## Current Phase
- Packaged runtime sign-off is complete for the currently scoped NLP runtime tracks.
- There is no active implementation blocker in the packaged Hebrew payload, packaged Stanza/Torch runtime, or packaged ONNX helper startup paths.
- The next optional provenance wave is now also complete for newly created `ProcessorRun` rows:
  - runtime provenance is dual-written into dedicated schema fields
  - the legacy `ProcessorRun.note` envelope remains the backward-compatible fallback
- The separate project bundle stability track is now narrowed and hardened:
  - interrupted export no longer leaves a misleading final `.hdleproj`
  - import now gives a clearer message when the selected file is an incomplete bundle
- The active project-exchange work has now moved from “stability hardening” to “product export closure”:
  - export has an explicit stage contract
  - export success requires validated artifact completion
  - the exported bundle now passes a clean import compatibility gate on the reference DB acceptance path
- The import-focused follow-up wave is now also closed for the current source-of-truth path:
  - import has an explicit stage contract
  - import runs truth-based pre-mutation bundle validation before host DB mutation
  - import success now requires post-import verification, not only “no exception”
- A post-release corrective hotfix is now required before the next public rerelease:
  - persisted `Process with NLP` / `Re-process` failed on real Hebrew documents in both repo and installed app
  - the failure was localized to managed Stanza subprocess JSON transport, not to the already-closed packaged runtime ownership/bootstrap tracks
  - the active corrective wave is limited to transport hardening, regression coverage, and rerelease preparation

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
- Project bundle import/export stability is now improved for the confirmed failure chain:
  - heavy export now exposes final-stage progress after payload creation (`Computing checksums`, `Writing manifest`, `Writing payload`, `Writing checksums`, `Finalizing bundle`)
  - interrupted export writes to `*.hdleproj.partial` first and only renames to the final `.hdleproj` on success
  - import now surfaces an explicit “incomplete or interrupted export” hint when the selected bundle is not a valid ZIP
- Project export is now product-closed for the current scope:
  - the export path has stable stage IDs and structured stage history
  - the live `Mishneh Torah` hang after `Dropping excluded tables` was fixed by removing duplicate FTS prune work in payload finalization
  - `.hdleproj` success now requires post-build validation (`read_bundle()` + payload `quick_check`)
  - clean import compatibility is restored for schema `31+` payloads via `document_sentence.corpus_id` remapping
- Project import is now product-closed for the current scope:
  - the import path has stable stage IDs and structured stage history
  - import now distinguishes artifact validation, compatibility/importability checks, DB mutation, verification, and cleanup
  - invalid archives fail during `preflight_bundle` with stage-aware reporting instead of a generic import failure
  - success now requires post-import readback verification of the imported project and its key row counts

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
- Project exchange root cause was split cleanly:
  - import failure reproduced on an invalid partial bundle left after an interrupted heavy export (`Invalid ZIP file: File is not a zip file`)
  - heavy export did not deadlock in table-copy phases; the user-visible “hang” was the long final zip/checksum phase with no heartbeat after payload creation
  - an additional heavy-project export failure on `project_id=1` was reproduced in the payload cleanup tail (`database is locked`) and resolved by explicit cursor cleanup before schema-drop finalization
- Product export closure is now confirmed on the large reference DB path:
  - `project_id=6`, `name='Mishneh Torah'`
  - CLI export now completes with `exit code 0`, `[OK] Export successful!`, and a validated bundle artifact
  - the produced bundle imports into a clean migrated target DB without errors
- Product import closure is now confirmed on the same proven bundle path:
  - the `Mishneh Torah` acceptance bundle imports into a clean migrated target DB with `exit code 0`
  - CLI import now reports `[OK] Import successful!` only after post-import verification passes
  - invalid bundles now fail with stage-aware diagnostics and no misleading success signal
- The NLP processing regression is now localized and fixed for the current source-of-truth path:
  - real persisted processing failures were traced to `UnicodeDecodeError` while the parent process decoded managed Stanza subprocess JSON output
  - the worker/probe subprocesses now force UTF-8 stdio with `errors="replace"`
  - the parent-side probe/worker launches now also decode subprocess pipes with `errors="replace"`
  - a live reprocess of the previously failing Hebrew document (`doc_id=387647`) now completes successfully on a copied DB

## Remaining Risks
- Resources Manager still does not provide a full guided install wizard; it provides truthful diagnostics and repair guidance only.
- The guided repair journey is coherent, but it is still rendered across multiple surfaces rather than one dedicated wizard.
- Historical `ProcessorRun` rows created before schema version `52` still rely on the legacy note envelope unless they are resumed or re-run.
- Very large project bundle export can still take noticeable time in the preflight and final compression phases; it is now explicit and bounded enough for diagnosis, but not “instant”.
- Very large bundle import can still spend noticeable time in the `import_tables` stage; it is now stage-visible and ends with verification evidence instead of a generic success/failure surface.
- Release `v1.0.1` is now a known-bad public artifact for persisted NLP processing and should be superseded by a corrective rebuild/rerelease that includes Step 25.

## Next Step
- No packaged runtime ownership/bootstrap blocker is currently open.
- Runtime provenance promotion is not the active issue.
- Project export and project import remain closed for the currently proven paths.
- The immediate next step is a corrective rerelease wave only:
  - rebuild the app and installer with the managed Stanza transport hardening from Step 25
  - rerun targeted repo and installed-app persisted processing smoke on real Hebrew documents
  - supersede `v1.0.1` with a corrected release once the processing smoke is green
- Do not reopen the already-closed packaged runtime, provenance, export, or import core tracks without new direct evidence.
