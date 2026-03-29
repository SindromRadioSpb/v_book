# Context State

## Confirmed Current Architecture
- Documents processing entry point:
  - `app/ui/documents_view.py`
- Documents NLP readiness worker:
  - `app/ui/workers.py`
- Persisted processing and processor-run tracking:
  - `app/services/process_service.py`
- NLP runtime backends:
  - `app/infra/nlp_engines/stanza_engine.py`
  - `app/infra/nlp_engines/mock_engine.py`
- Health checks:
  - `app/services/health_check_service.py`
- Managed resources:
  - `app/services/resources/resource_registry.py`
  - `app/resources/resource_manifest.json`

## Confirmed Gaps
- Resources Manager still does not provide a true install wizard; it provides status, repair guidance, and model-path actions only.
- Historical runtime provenance rows still depend on the legacy `ProcessorRun.note` envelope until explicitly re-run or resumed under schema version `52`.
- External runtime dependency repair and managed model import are still surfaced in one dialog, though now with clearer boundaries.
- Very large project bundle export remains disk/CPU heavy in the final compression phase even after payload creation is complete.
- Project export preflight on the large reference DB is still a visible stage of its own; it is now observable, but not instantaneous.

## Constraints
- PowerShell-only workflow.
- Do not touch `AGENTS.md`.
- Keep Wave 1 scope tight: safety and truth foundation only.
- Documentation must be updated after each logically completed step.

## Current Delivery Intent
- Wave 2:
  - subprocess-isolated runtime truth
  - packaging-aware remediation
  - stronger setup/repair guidance in Resources Manager

## Confirmed Current State After Wave 2
- `ProcessService` no longer silently converts Stanza failures into Mock runs.
- Documents UI requires explicit fallback confirmation before running persisted processing on Mock.
- `ProcessorRun.note` now records configured/effective engine and fallback provenance.
- Health Check includes `nlp_runtime:stanza`.
- Resources Manager shows current Stanza runtime status text.
- Resources Manager no longer crashes if the NLP runtime probe itself raises.
- Documents exposes direct `Diagnose NLP` and `Open NLP Setup` actions.
- `RuntimeProbe` now executes Stanza/Torch checks in an isolated subprocess and returns machine-readable reason codes.
- Resources Manager exposes packaging-aware repair steps and a guarded NLP model-folder action.
- Wave 2 is now treated as the stable runtime-management baseline for subsequent UX/provenance work.

## Confirmed Current State After Wave 3 PATCH-01
- Resources Manager now separates `External Runtime Dependency` from `Managed Hebrew Resource`.
- Documents and Health Check now use the same runtime/resource vocabulary as Resources Manager.
- The UI continues to provide truthful next steps without promising in-place package installation.

## Confirmed Current State After Wave 3 PATCH-02
- `ProcessorRun.note` now carries a stable nested `runtime` provenance envelope in addition to the legacy flat fields.
- The structured envelope records `configured_engine_id`, `effective_engine_id`, `fallback_used`, `reason_code`, `runtime_mode`, and `probe_summary`.
- Batch and single-document processing now share the same machine-readable runtime provenance shape.

## Confirmed Current State After Optional Provenance Promotion
- `processor_run` now stores dedicated schema-backed runtime provenance for new runs:
  - `configured_engine_id`
  - `effective_engine_id`
  - `fallback_used`
  - `runtime_reason_code`
  - `runtime_mode`
  - `runtime_probe_summary_json`
- `ProcessService` still preserves the stable nested `runtime` envelope in `ProcessorRun.note` as a compatibility layer.
- Single-document, batch, and snapshot-backfill runs now share the same dual-write provenance contract.
- Compatibility read paths prefer dedicated schema fields and fall back to the legacy note envelope for old rows.

## Confirmed Current State After Project Bundle Stability Hardening
- `ProjectExportEngine` now reports the final export phases explicitly after payload creation:
  - `Computing checksums`
  - `Writing manifest`
  - `Writing payload`
  - `Writing checksums`
  - `Finalizing bundle`
- Bundle creation now stages to `*.hdleproj.partial` and only promotes to the final `.hdleproj` on success.
- This prevents an interrupted heavy export from leaving a misleading final bundle that later fails import as `Invalid ZIP file`.
- The heavy export payload cleanup path now closes export cursors before the final schema-drop phase, which removed the reproduced `database is locked` failure on the large live project export path.

## Confirmed Current State After Project Export Product Closure
- The source-of-truth export path is now explicit and singular:
  - `app/ui/app_window.py`
  - `app/services/project_exchange/worker.py`
  - `app/services/project_exchange/export_engine.py`
  - `app/services/project_exchange/bundle_format.py`
- Export now reports product stages instead of only opportunistic UI strings:
  - `prepare_context`
  - `preflight_checks`
  - `create_staging_db`
  - `apply_schema`
  - `attach_host_db`
  - `prepare_fts`
  - `resolve_project_scope`
  - `copy_tables`
  - `prune_payload`
  - `finalize_sqlite`
  - `build_manifest`
  - `build_bundle`
  - `validate_artifact`
  - `completed`
- The live reference-DB hang after `Dropping excluded tables` is now localized and fixed:
  - payload finalization previously re-entered `sentence_fts` / `term_fts` through the generic exclusion loop after already dropping them explicitly
  - the exclusion loop now skips those duplicate FTS drops
- Export success is now stricter:
  - the final `.hdleproj` must exist
  - bundle structure/checksums must validate
  - extracted payload must pass `PRAGMA quick_check(1)`
- Import compatibility for exported bundles is now restored for schema `31+` payloads because `document_sentence.corpus_id` is remapped together with `doc_id`.

## Confirmed Current State After Wave 3 PATCH-03
- `RuntimeProbe` now exposes a shared guided repair plan derived from the machine-readable error taxonomy.
- Documents tooltips, Health Check remediation, and Resources Manager repair guidance now point to the same next-step route.
- The guided route distinguishes runtime repair from managed Hebrew resource repair without introducing fake in-place package installation.

## Confirmed Current State After Live Engine Init Divergence Fix
- `ProcessService` now treats probe/runtime divergence as a managed runtime-block condition.
- A live `create_stanza_engine()` failure no longer escapes as a raw traceback from the worker path when the subprocess probe had previously reported ready.

## Confirmed Current State After Documents Retry Flow Fix
- `ProcessWorker` now preserves controlled runtime-block messages instead of collapsing them into a generic Stanza error.
- Controlled runtime-block failures are logged as warnings rather than full worker tracebacks.
- `DocumentsView` can now convert a late live-init Stanza failure into a guided recovery dialog without forcing the user to restart the action manually.
- The guided recovery dialog routes the user to `Use Mock Once`, `Open NLP Setup`, `Run Health Check`, or `Cancel`.

## Confirmed Current State After Production Subprocess Stanza Fix
- `create_stanza_engine()` can now recover from hostile in-process `torch/stanza` initialization by spawning a clean subprocess-backed Stanza engine instead of hard-failing the processing request.
- The subprocess-backed engine preserves the `NLPEngine` contract and returns real sentence/token payloads to the existing pipeline.
- A live app-like Qt process (`QApplication` + `QMediaPlayer`) now auto-falls back to `SubprocessStanzaEngine` after a real `WinError 1114` and still processes Hebrew text successfully.
- A real `reprocess_document()` run succeeded on a copy of the user DB while using this subprocess runtime recovery path.
- The detected Hebrew model resource is currently a directory at `C:\Users\lletp\AppData\Local\StanfordNLP\stanza\Cache\1.11.0\resources\he`; there is no single bundled installer file for it inside the dialog.

## Confirmed Current State After PATCH-01 Thread Lifecycle Hardening
- `Resources Manager`, `DocumentsView`, and `AppWindow` now enforce deterministic QThread shutdown before owner destruction.
- Runtime recovery, health-check, and resource-management flows no longer rely on owner deletion while a worker is still running.
- The remaining runtime gap is no longer thread ownership; it is product ownership of the Stanza subprocess runtime/bootstrap path itself.

## Confirmed Current State After PATCH-02 Managed Subprocess Runtime
- Windows production Stanza now prefers an app-owned subprocess runtime launched through `app.main --stanza-worker`.
- The isolated probe now uses the sibling `app.main --stanza-probe` path, so diagnostics and production processing share the same runtime ownership model.
- `ManagedStanzaRuntime` now owns a writable runtime root, a managed `stanza_resources/he` path, and a runtime manifest under the app data tree.
- The managed runtime can bootstrap the Hebrew model from either bundled resources or an existing legacy Stanza cache and then use that managed copy as the product-owned resource path.
- Resources Manager now exposes an official `Install / Repair NLP Runtime` action for this managed runtime path.

## Confirmed Current State After PATCH-03 Official Setup / Repair Flow
- `Install / Repair NLP Runtime` is now the explicit product-owned recovery action surfaced by Resources Manager.
- Documents runtime tooltips and runtime-block dialogs now point to the same official setup action instead of only generic setup wording.
- Health Check remediation now references the same official setup action, so the guided route is consistent across the three primary surfaces.

## Confirmed Current State After PATCH-04 Release-grade Smoke Validation
- `ManagedStanzaRuntime` now rejects partial managed Hebrew payloads and repairs them from a valid bundled/legacy source instead of reusing a broken local copy.
- The app-owned probe/worker runtime now prepares Torch/CUDA DLL search paths before importing `stanza/torch`, which allows the managed subprocess runtime to initialize successfully on the target Windows machine.
- `scripts/release_smoke_nlp_runtime.py` now provides the release smoke contract for this subsystem:
  - hostile in-process Qt launch with forced Stanza failure
  - managed subprocess startup
  - Hebrew sample processing
  - DB-copy `Re-process` with `runtime_effective='stanza'`
- Release smoke has now confirmed a real `Re-process` success on a copied DB while the effective runtime remained `stanza`.

## Confirmed Current State After P0 Re-process Lifecycle Hotfix
- `ProcessWorker` now emits `result_ready` for business results and no longer shadows the base `QThread.finished` signal.
- `DocumentsView` now waits for the real thread-finished callback before deleting the worker object or launching an explicit Mock retry.
- The `Re-process` cleanup path is now aligned with the earlier owner-shutdown contract instead of tearing down a still-running worker from an early payload signal.

## Confirmed Current State After Live GUI Re-process Confirmation
- The original live repro path on the target machine now completes successfully:
  - project `6`
  - document `387646`
  - `Documents -> Re-process`
- The prior `QThread: Destroyed while thread '' is still running` crash is no longer reproducing on that GUI path.
- The fixed worker lifecycle and the managed subprocess `stanza` runtime now coexist correctly in the real desktop flow, not only in automated regression tests.

## Confirmed Current State After Document-scoped Release Smoke Narrowing
- `scripts/release_smoke_nlp_runtime.py` no longer depends on copying the whole source DB for the reprocess smoke step.
- The DB smoke path now builds a tiny migrated target DB for a single document by cloning only the required base tables and then running `reprocess_document()` against that clone.
- The real Windows source DB smoke now completes successfully with:
  - `db_copy_strategy = document_scoped_clone`
  - `run_engine = stanza`
  - `run_status = ok`
  - `runtime_effective = stanza`

## Confirmed Current State After Bundled Hebrew Payload Packaging Foundation
- The canonical staged Hebrew payload root is now `installer/resources/local_models/stanza_hebrew/`.
- The staged payload is directory-based and includes:
  - `payload_manifest.json`
  - `stanza_resources/resources.json`
  - `stanza_resources/he/...`
- `rebuild.ps1` now stages this payload before PyInstaller runs.
- `hdle_premium_installer.spec` now bundles that staged tree into the frozen app under `_internal/resources/nlp_runtime/stanza_payload/`.
- The remaining gap is no longer packaging assembly; it is runtime/bootstrap preference and ownership truth for the bundled packaged payload.

## Confirmed Current State After Bundled Payload Ownership Bootstrap
- Managed bootstrap now prefers `bundled_packaged` over `bundled_dev`, then `legacy_cache`, while preserving `repaired_managed` for already healthy managed copies.
- The runtime manifest now records bundled payload ownership and payload-manifest linkage explicitly.
- The runtime probe now carries that ownership truth into machine-readable status so UI/health/smoke can report whether processing is using a bundled packaged payload or only a legacy cache source.

## Confirmed Current State After Bundled Ownership UI / Health / Smoke Alignment
- Resources Manager now renders bundled payload ownership and bundled payload root directly in both the external runtime and managed Hebrew resource messages.
- Health Check now includes source ownership and bundled payload root in the NLP runtime line when available.
- Documents runtime detail tooltip now exposes the same ownership truth.
- Release smoke can now fail fast if the managed runtime does not report the expected bundled source kind.

## Confirmed Current State After Bundled Payload Release Gate Validation
- The dev release path now passes both engine smoke and DB reprocess smoke with enforced bundled ownership:
  - `source_kind = bundled_dev`
  - `runtime_effective = stanza`
- Obsolete managed manifests are now upgraded to current bundled ownership when a valid bundled payload is available.
- Managed payload refresh is overwrite-safe and no longer trips `WinError 183` during release smoke.


## Confirmed Current State After Packaged Rebuild Audit
- The current packaged build is no longer stale: `dist/HDLE_Premium/_internal/resources/nlp_runtime/stanza_payload/...` now exists after a full rebuild.
- Packaged self-check respects `HDLE_DATA_ROOT` when invoked with an explicit output path.
- On a clean workspace-managed root, packaged bootstrap now writes:
  - `ownership = packaged_app`
  - `model_source_kind = bundled_packaged`
  - `bundled_payload_root = dist/HDLE_Premium/_internal/resources/nlp_runtime/stanza_payload`
- This confirms that bundled Hebrew payload delivery into the frozen artifact is working.
- The remaining release blocker is now narrower and more concrete:
  - packaged `--stanza-probe` still reports `hostile_torch_state`
  - packaged `--stanza-worker` still fails on the same `torch\lib\c10.dll` import chain
- Therefore bundled payload delivery is complete, but packaged Torch/Stanza runtime readiness is not yet release-green.

## Confirmed Current State After Frozen Torch Runtime Hook Hardening
- The packaged `torch\lib\c10.dll` failure was caused by bootstrap timing, not by missing bundled Hebrew payload files.
- Torch DLL directories and the critical `c10.dll` chain are now prepared in a PyInstaller runtime hook before the frozen app imports user code.
- The packaged frozen runtime is now release-green for the Stanza/Torch track:
  - packaged `--stanza-probe` succeeds on a clean managed root
  - packaged `--stanza-worker` initializes the managed runtime successfully
  - release smoke now passes with `--require-source-kind bundled_packaged --require-bundled-source`
  - DB reprocess smoke keeps `run_engine='stanza'`, `run_status='ok'`, and `runtime_effective='stanza'`
- Bundled payload delivery remains confirmed and unchanged:
  - `source_kind = bundled_packaged`
  - bundled payload root still resolves to `_internal/resources/nlp_runtime/stanza_payload`
- The remaining frozen validation item is outside this track:
  - `--self-check import` still reports an ONNX helper timeout for `HDLE_ONNX_Probe.exe`

## Confirmed Current State After Frozen ONNX Helper HF Home Hardening
- The packaged `HDLE_ONNX_Probe.exe` timeout was not a Torch/Stanza regression and not an ONNX DLL bootstrap failure.
- The frozen helper was stalling inside `_ensure_hf_home()` before `import onnxruntime`, while trying to write-probe an inherited `HF_HOME=F:\huggingface`.
- The helper now accepts an existing configured `HF_HOME` as a read-first cache root and only falls back to a local writable cache when the configured path is missing or unusable.
- The frozen ONNX helper track is now green again:
  - `HDLE_ONNX_Probe.exe --mode import` succeeds in the rebuilt packaged artifact
  - packaged `--self-check import` now reports `checks.onnxruntime_import.ok = true`
  - packaged `--self-check health` now reports a successful `frozen_onnx_probe`
- The already closed packaged Stanza/Torch track remains conceptually separate and was not redesigned by this fix.

## Confirmed Current State After Project Import Product Closure
- The active source-of-truth import path remains:
  - `app/ui/app_window.py` -> `ProjectImportWorker` -> `ProjectImportEngine.import_project()`
- Import is no longer just a best-effort long operation:
  - it now has stable stage IDs and structured stage history
  - bundle validation and payload `quick_check` run before host DB mutation
  - importability checks still run before offsets and write phases
  - success now requires post-import readback verification
- Import failure is now operator-usable:
  - invalid archives fail during `preflight_bundle`
  - failure reports preserve the true failure stage
  - cleanup outcome is surfaced separately instead of being silently implicit
- The current proven acceptance path is green:
  - `Mishneh Torah_project_6_acceptance.hdleproj` imports into a clean migrated target DB with `exit code 0`
  - CLI prints `[OK] Import successful!` only after the verification stage completes
  - invalid bundle smoke now fails truthfully with `failure_code = invalid_archive` and `cleanup_status = not_needed`

## Confirmed Current State After NLP Processing Transport Hardening
- The active source-of-truth NLP processing path remains:
  - `DocumentsView` -> `ProcessWorker` -> `ProcessService.process_documents_batch()` -> `ProcessService.process_document()` / `reprocess_document()` -> `SubprocessStanzaEngine.process()`
- The release-blocking bug was localized to the managed subprocess transport layer, not to Stanza runtime ownership/bootstrap itself:
  - real user logs showed `UnicodeDecodeError` from `app/infra/nlp_engines/stanza_engine.py` while reading subprocess JSON output
  - the failure occurred after sentence splitting and during per-sentence NLP calls on real Hebrew documents
- The transport contract is now hardened:
  - `--stanza-worker` and `--stanza-probe` normalize stdio to UTF-8 with replacement semantics
  - parent-side subprocess readers now decode with `errors="replace"`
- Live repro evidence on a copy of `hdle_premium.db` is green again:
  - `reprocess_document(session, 387647, use_mock=False, configured_engine_id='stanza')` -> `ok=True`
  - the same document had previously failed in logs with `UnicodeDecodeError` during `engine.process(...)`

