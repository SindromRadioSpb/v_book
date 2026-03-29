# Implementation Ledger

## Task
- `task31`: product-grade NLP runtime management for Documents processing

## Scope Baseline
- Target direction: Variant B (`Premium Product Requirements`)
- Current delivery wave: Wave 1 safety-first foundation

## Step 0 — Initial Audit Capture
- Status: completed
- Confirmed findings:
  - `DocumentsView` readiness is currently based on a shallow Stanza availability check, not actual runtime truth.
  - Persisted processing can silently fall back from Stanza to Mock.
  - `project.nlp_engine` is only a coarse snapshot and is not audit-grade provenance.
  - `Resources Manager` and `Health Check` do not expose NLP runtime state.
- Code evidence:
  - `app/ui/documents_view.py`
  - `app/ui/workers.py`
  - `app/services/process_service.py`
  - `app/services/health_check_service.py`
  - `app/services/resources/resource_registry.py`
- Risks:
  - silent degradation of persisted NLP output
  - misleading UI readiness signal
  - no self-service remediation path

## Step 1 — Governance Docs Foundation
- Status: completed
- Deliverables:
  - `docs/DECISIONS_LOG.md`
  - `docs/CONTEXT_STATE.md`
  - `docs/TRACEABILITY_MATRIX.md`
  - `docs/HANDOFF_STATUS.md`

## Step 2 — Wave 1 Safety-First Foundation
- Status: completed
- Code deliverables:
  - `app/services/nlp_runtime/`
  - `app/services/process_service.py`
  - `app/ui/workers.py`
  - `app/ui/documents_view.py`
  - `app/services/health_check_service.py`
  - `app/ui/resources_manager_dialog.py`
  - `app/infra/nlp_engines/mock_engine.py`
- Confirmed behavior changes:
  - silent fallback from Stanza to Mock was removed from `ProcessService.get_nlp_engine()`
  - persisted processing now requires explicit Mock fallback confirmation from Documents UI
  - runtime state now distinguishes configured vs effective engine
  - processor runs now persist runtime provenance in `ProcessorRun.note`
  - Documents readiness uses machine-readable runtime status instead of import-only probing
  - Health Check now reports an NLP runtime item
  - Resources Manager now exposes current NLP runtime status text
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py -q` -> `2 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_documents_engine_readiness.py -q` -> `3 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_health_check_service.py -q` -> `5 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_run_state_foundation.py -q` -> `4 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_batch_run_state.py -q` -> `10 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_documents_process_progress_ui.py -q` -> `6 passed`
  - `.\.venv\Scripts\python.exe -c "from app.services.nlp_runtime import NlpRuntimeProbe, NlpRuntimeStatus; from app.services.health_check_service import HealthCheckService; print('OK')"` -> `OK`

## Step 3 — Resources Manager Crash Fix
- Status: completed
- Trigger:
  - opening Resources Manager crashed when `probe_stanza()` surfaced a hostile `torch/stanza` DLL import failure
- Code deliverables:
  - `app/ui/resources_manager_dialog.py`
  - `tests/test_resources_manager_dialog.py`
- Confirmed behavior changes:
  - Resources Manager now catches NLP probe failures and degrades to a warning label instead of crashing the dialog
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_resources_manager_dialog.py -q` -> `1 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py -q` -> `32 passed`

## Step 4 — Wave 2 Diagnose / Setup Flow
- Status: completed
- Code deliverables:
  - `app/ui/documents_view.py`
  - `tests/test_documents_engine_readiness.py`
- Confirmed behavior changes:
  - Documents now shows explicit `Diagnose NLP` and `Open NLP Setup` actions next to the runtime status
  - unavailable runtime states now expose richer tooltip details instead of only a terse label
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_documents_engine_readiness.py tests/test_resources_manager_dialog.py -q` -> `5 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py -q` -> `32 passed`

## Step 5 — Wave 2 Probe Hardening + Repair Flow
- Status: completed
- Code deliverables:
  - `app/services/nlp_runtime/runtime_probe.py`
  - `app/ui/resources_manager_dialog.py`
  - `tests/test_nlp_runtime_probe.py`
  - `tests/test_resources_manager_dialog.py`
- Confirmed behavior changes:
  - Stanza readiness probing now runs in an isolated subprocess instead of importing `stanza/torch` in the UI process
  - probe results now classify `package_missing`, `runtime_import_failed`, `hostile_torch_state`, `model_missing`, `pipeline_init_failed`, `smoke_failed`, `probe_timeout`, `probe_subprocess_failed`, and `probe_invalid_output`
  - remediation text now distinguishes development vs packaged runtime expectations
  - Resources Manager now exposes packaging-aware repair guidance and enables the NLP model-folder action only when a model path is actually detected
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_nlp_runtime_probe.py tests/test_resources_manager_dialog.py tests/test_health_check_service.py tests/test_documents_engine_readiness.py -q` -> `15 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py -q` -> `37 passed`

## Step 6 — Wave 3 PATCH-01 Runtime/Resource UX Split
- Status: completed
- Baseline note:
  - Wave 2 is now treated as the stable checkpoint for subprocess probe isolation, packaging-aware remediation, and guarded setup/repair flow.
- Code deliverables:
  - `app/ui/resources_manager_dialog.py`
  - `app/services/health_check_service.py`
  - `app/ui/documents_view.py`
  - `tests/test_resources_manager_dialog.py`
  - `tests/test_health_check_service.py`
  - `tests/test_documents_engine_readiness.py`
- Confirmed behavior changes:
  - Resources Manager now separates `External Runtime Dependency` from `Managed Hebrew Resource`
  - Documents and Health Check now use the same runtime/resource vocabulary
  - the UI continues to guide the user without implying one-click Python package installation
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_resources_manager_dialog.py -q` -> `12 passed`

## Step 7 — Wave 3 PATCH-02 Structured Runtime Provenance
- Status: completed
- Code deliverables:
  - `app/services/process_service.py`
  - `tests/test_process_service_nlp_runtime.py`
  - `tests/test_process_batch_run_state.py`
- Confirmed behavior changes:
  - single-document processing now writes a stable nested `runtime` provenance envelope inside `ProcessorRun.note`
  - batch processing now records the same structured runtime envelope under `note["runtime"]`
  - legacy flat note keys remain present for backward compatibility
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py -q` -> `16 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py -q` -> `37 passed`

## Step 8 — Wave 3 PATCH-03 Guided Repair Journey
- Status: completed
- Code deliverables:
  - `app/services/nlp_runtime/runtime_probe.py`
  - `app/ui/documents_view.py`
  - `app/services/health_check_service.py`
  - `app/ui/resources_manager_dialog.py`
  - `tests/test_nlp_runtime_probe.py`
  - `tests/test_documents_engine_readiness.py`
  - `tests/test_health_check_service.py`
  - `tests/test_resources_manager_dialog.py`
- Confirmed behavior changes:
  - `RuntimeProbe` now exposes a shared guided repair plan based on runtime vs resource routes
  - Documents tooltips now include a recommended route and next action
  - Health Check remediation now carries the same guided route context
  - Resources Manager repair guide now presents the shared route and next action before the detailed steps
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_nlp_runtime_probe.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_resources_manager_dialog.py -q` -> `17 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py -q` -> `39 passed`

## Step 9 — Live Engine Init Divergence Fix
- Status: completed
- Trigger:
  - probe reported Stanza ready, but live in-process `create_stanza_engine()` could still fail with `WinError 1114` during `torch` DLL initialization.
- Code deliverables:
  - `app/services/process_service.py`
  - `tests/test_process_service_nlp_runtime.py`
- Confirmed behavior changes:
  - live engine-init failures are now converted into the same runtime-block contract instead of surfacing as a raw traceback from `create_stanza_engine()`
  - the runtime-block message now explicitly distinguishes subprocess-probe success from live process initialization failure
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py -q` -> `40 passed`

## Step 10 — Documents Retry Flow for Runtime Block
- Status: completed
- Trigger:
  - `Documents -> Re-process` still failed after Step 9 when the subprocess probe reported Stanza ready but live worker initialization failed in-process.
- Code deliverables:
  - `app/ui/workers.py`
  - `app/ui/documents_view.py`
  - `tests/test_documents_process_progress_ui.py`
- Confirmed behavior changes:
  - controlled runtime-block errors are no longer collapsed into a generic `"NLP engine error"` string inside `ProcessWorker`
  - controlled runtime-block errors are logged as warnings instead of full worker tracebacks
  - `DocumentsView` now offers a guided recovery router when a live Stanza init failure occurs after the worker has already started
  - the recovery router offers `Use Mock Once`, `Open NLP Setup`, `Run Health Check`, and `Cancel`
  - the explicit Mock retry reuses the same document selection, forces CPU Mock mode, and keeps the fallback explicit
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_documents_process_progress_ui.py tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py -q` -> `30 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py -q` -> `44 passed`

## Step 11 — Production Subprocess Stanza Runtime
- Status: completed
- Trigger:
  - the product still depended on in-process `torch/stanza` initialization inside the Qt application process, so the UI recovery flow could only route around the failure instead of restoring real Stanza processing.
- Code deliverables:
  - `app/infra/nlp_engines/stanza_engine.py`
  - `app/infra/nlp_engines/stanza_subprocess_worker.py`
  - `app/ui/resources_manager_dialog.py`
  - `tests/test_stanza_engine_subprocess.py`
  - `tests/test_resources_manager_dialog.py`
- Confirmed behavior changes:
  - `create_stanza_engine()` now falls back to a subprocess-backed Stanza engine when in-process runtime initialization fails with hostile DLL/runtime conditions
  - the subprocess engine preserves the same `NLPEngine` contract and returns real sentence/token payloads
  - Resources Manager now says explicitly that Python runtime dependencies are not represented as a bundled install file in this dialog
  - Resources Manager now says explicitly that the Hebrew model is a directory-based resource, not a single installer file
- Test evidence:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_stanza_engine_subprocess.py tests/test_resources_manager_dialog.py tests/test_documents_process_progress_ui.py tests/test_process_service_nlp_runtime.py tests/test_nlp_runtime_probe.py -q` -> `24 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests/test_process_service_nlp_runtime.py tests/test_documents_engine_readiness.py tests/test_health_check_service.py tests/test_process_run_state_foundation.py tests/test_process_batch_run_state.py tests/test_documents_process_progress_ui.py tests/test_resources_manager_dialog.py tests/test_nlp_runtime_probe.py tests/test_stanza_engine_subprocess.py -q` -> `47 passed`
- Live smoke evidence:
  - App-like Qt process (`QApplication` + `QMediaPlayer`) now auto-falls back from in-process Stanza to `SubprocessStanzaEngine` after a real `WinError 1114` and still processes Hebrew text successfully
  - Real reprocess succeeded on a copy of the user DB:
    - DB copy: `E:\projects\Project_Vibe\V_book\reports\runtime_smoke\hewiki_gpu_processing_test_copy.db`
    - Document: `doc_id=1`
    - Result: `ok=True`, status remained `processed`, latest `ProcessorRun.engine='stanza'`
    - Detected Hebrew model directory: `C:\Users\lletp\AppData\Local\StanfordNLP\stanza\Cache\1.11.0\resources\he`

## Step 12 — PATCH-01 Thread Lifecycle Hardening
- Status: completed
- Trigger:
  - live Windows scenario could still end in `QThread: Destroyed while thread '' is still running` during runtime recovery / dialog shutdown paths.
- Code deliverables:
  - `app/ui/thread_lifecycle.py`
  - `app/ui/resources_manager_dialog.py`
  - `app/ui/documents_view.py`
  - `app/ui/app_window.py`
  - `tests/test_documents_process_progress_ui.py`
  - `tests/test_resources_manager_dialog.py`
  - `tests/test_workspace_app_window_contract.py`
- Confirmed behavior changes:
  - UI owners now have an explicit shutdown contract for background QThreads: cooperative cancel/quit, bounded `wait()`, force `terminate()` only during owner shutdown, and close deferral if a worker still refuses to stop
  - `Resources Manager` now closes its progress dialog and stops download/import/health workers before dialog destruction
  - `DocumentsView` no longer leaves process/readiness/snapshot/page workers running past widget close
  - `AppWindow.closeEvent()` now waits for the global health-check worker before allowing window destruction
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\ui\thread_lifecycle.py app\ui\resources_manager_dialog.py app\ui\documents_view.py app\ui\app_window.py tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_workspace_app_window_contract.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_workspace_app_window_contract.py -q` -> `24 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_process_service_nlp_runtime.py tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_workspace_app_window_contract.py -q` -> `58 passed`

## Next Step
- PATCH-02:
  - promote the subprocess-backed Stanza runtime from recovery-only fallback to an application-controlled managed runtime path with explicit ownership metadata and out-of-box bootstrap semantics

## Step 13 — PATCH-02 Managed Subprocess Runtime
- Status: completed
- Trigger:
  - production processing still depended on ad-hoc fallback semantics instead of an app-owned managed runtime path; `Qt` should not need to import `torch/stanza` successfully for normal Stanza processing on Windows.
- Code deliverables:
  - `app/services/nlp_runtime/managed_runtime.py`
  - `app/services/nlp_runtime/stanza_probe_worker.py`
  - `app/services/nlp_runtime/runtime_probe.py`
  - `app/main.py`
  - `app/infra/nlp_engines/stanza_engine.py`
  - `app/infra/nlp_engines/stanza_subprocess_worker.py`
  - `app/ui/resources_manager_dialog.py`
  - `app/ui/workers.py`
  - `tests/test_managed_stanza_runtime.py`
  - `tests/test_nlp_runtime_probe.py`
  - `tests/test_stanza_engine_subprocess.py`
  - `tests/test_resources_manager_dialog.py`
- Confirmed behavior changes:
  - `app.main` now exposes headless `--stanza-worker` and `--stanza-probe` entry points, so the product executable itself becomes the app-owned runtime command surface
  - `ManagedStanzaRuntime` now owns:
    - runtime root
    - managed `stanza_resources/he` path
    - runtime manifest
    - bootstrap from bundled or legacy Hebrew model sources
  - Windows `create_stanza_engine()` now prefers the managed subprocess runtime as the normal success path instead of waiting for an in-process failure first
  - `RuntimeProbe` now probes the same app-owned runtime path and the same managed Hebrew resource path used by production processing
  - Resources Manager now has an official `Install / Repair NLP Runtime` action for the product-owned runtime path
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\nlp_runtime\managed_runtime.py app\services\nlp_runtime\stanza_probe_worker.py app\services\nlp_runtime\runtime_probe.py app\main.py app\infra\nlp_engines\stanza_engine.py app\infra\nlp_engines\stanza_subprocess_worker.py app\ui\resources_manager_dialog.py app\ui\workers.py tests\test_managed_stanza_runtime.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_resources_manager_dialog.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_managed_stanza_runtime.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_resources_manager_dialog.py -q` -> `17 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_process_service_nlp_runtime.py tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_workspace_app_window_contract.py tests\test_managed_stanza_runtime.py -q` -> `63 passed`

## Step 14 — PATCH-03 Official Setup / Repair Flow
- Status: completed
- Trigger:
  - the managed runtime existed, but Documents, Health Check, and Resources Manager still did not point the user clearly enough to one official product-owned recovery action.
- Code deliverables:
  - `app/ui/resources_manager_dialog.py`
  - `app/services/health_check_service.py`
  - `app/ui/documents_view.py`
  - `tests/test_documents_engine_readiness.py`
  - `tests/test_health_check_service.py`
  - `tests/test_resources_manager_dialog.py`
- Confirmed behavior changes:
  - Resources Manager now promotes `Install / Repair NLP Runtime` as the official product-owned bootstrap path
  - Documents tooltips and runtime-block recovery text now point to the same official action
  - Health Check remediation now references the same official setup action instead of leaving the user with only generic runtime advice
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\ui\documents_view.py app\ui\resources_manager_dialog.py app\services\health_check_service.py tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_resources_manager_dialog.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_resources_manager_dialog.py -q` -> `14 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_process_service_nlp_runtime.py tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_workspace_app_window_contract.py tests\test_managed_stanza_runtime.py -q` -> `63 passed`

## Step 15 — PATCH-04 Release-grade Smoke Validation
- Status: completed
- Trigger:
  - the managed runtime path existed, but we still needed release-grade proof that Windows hostile in-process `torch/stanza` state does not block real Stanza processing and does not regress into incomplete managed resource payloads.
- Code deliverables:
  - `app/services/nlp_runtime/managed_runtime.py`
  - `app/infra/nlp_engines/stanza_engine.py`
  - `app/services/nlp_runtime/stanza_probe_worker.py`
  - `scripts/release_smoke_nlp_runtime.py`
  - `tests/test_managed_stanza_runtime.py`
  - `tests/test_stanza_engine_subprocess.py`
- Confirmed behavior changes:
  - managed runtime bootstrap now treats the local managed copy as valid only when the full Hebrew Stanza payload is present (`resources.json` + required model entries), so an incomplete copy is repaired from a valid bundled/legacy source instead of being reused
  - Windows runtime preparation now registers Torch/CUDA DLL directories before importing `stanza/torch`, allowing the app-owned probe/worker subprocess to initialize successfully even when the live Qt process remains hostile
  - release smoke now covers both:
    - hostile in-process runtime -> managed subprocess success path
    - real `reprocess_document()` on a copied DB with `runtime_effective='stanza'`
  - the smoke script is now UTF-8 safe and selects the newly created `ProcessorRun` deterministically instead of assuming the table contains only one row
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\nlp_runtime\managed_runtime.py app\infra\nlp_engines\stanza_engine.py app\services\nlp_runtime\stanza_probe_worker.py scripts\release_smoke_nlp_runtime.py tests\test_managed_stanza_runtime.py tests\test_stanza_engine_subprocess.py tests\test_nlp_runtime_probe.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_managed_stanza_runtime.py tests\test_stanza_engine_subprocess.py tests\test_nlp_runtime_probe.py -q` -> `15 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_process_service_nlp_runtime.py tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_workspace_app_window_contract.py tests\test_managed_stanza_runtime.py -q` -> `66 passed`
  - `.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --force-hostile-inprocess` -> managed subprocess `stanza` processed Hebrew sample successfully after forced in-process failure
  - `.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --db-path "E:\projects\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --copy-db-to "E:\projects\Project_Vibe\V_book\reports\runtime_smoke\managed_runtime_smoke_copy.db" --doc-id 1` -> `ok=True`, `document_status='processed'`, `run_engine='stanza'`, `run_status='ok'`, `runtime_effective='stanza'`

## Next Step
- Final handoff only:
  - preserve the managed runtime/model payload in release packaging
  - keep using `scripts/release_smoke_nlp_runtime.py` as the Windows runtime release gate

## Step 16 — P0 Hotfix: ProcessWorker lifecycle must wait for real QThread finish
- Status: completed
- Trigger:
  - live `Documents -> Re-process` on project `6`, document `387646` still crashed with `QThread: Destroyed while thread '' is still running` even after the broader thread-hardening patch.
- Code deliverables:
  - `app/ui/workers.py`
  - `app/ui/documents_view.py`
  - `tests/test_documents_process_progress_ui.py`
- Confirmed behavior changes:
  - `ProcessWorker` no longer masks the base `QThread.finished` signal with its result payload signal; it now emits `result_ready` for business results and leaves `QThread.finished` available for lifecycle cleanup
  - `DocumentsView` now tears down the process dialog immediately but defers `ProcessWorker.deleteLater()` until the real `QThread.finished` fires
  - explicit Mock retry after a runtime block is now scheduled only after the previous process thread has actually finished, instead of being started from an early result/error callback while the previous `QThread` may still be running
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\ui\workers.py app\ui\documents_view.py tests\test_documents_process_progress_ui.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_documents_process_progress_ui.py -q` -> `11 passed`
- `.\.venv\Scripts\python.exe -m pytest tests\test_process_service_nlp_runtime.py tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_resources_manager_dialog.py tests\test_nlp_runtime_probe.py tests\test_stanza_engine_subprocess.py tests\test_workspace_app_window_contract.py tests\test_managed_stanza_runtime.py -q` -> `67 passed`

## Next Step
- Re-run the live GUI scenario for `Documents -> Re-process` and confirm the prior `QThread` destruction crash is gone.

## Step 17 — Live GUI Confirmation After P0 Re-process Hotfix
- Status: completed
- Trigger:
  - Step 16 fixed the thread lifecycle bug in code and tests, but the target machine still needed a real GUI confirmation on the original failing scenario.
- Confirmation evidence:
  - user re-ran the live desktop flow against:
    - project `6`
    - document `387646`
  - `Documents -> Re-process` completed successfully
  - the prior `QThread: Destroyed while thread '' is still running` crash did not reproduce
- Outcome:
  - the Step 16 lifecycle hotfix is now confirmed both by automated regression coverage and by the original live GUI repro path
  - the managed subprocess `stanza` runtime remains compatible with the fixed `Documents` worker lifecycle
- Test evidence:
  - live GUI confirmation on the target machine: `python -m app.main --db-path "E:\projects\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db"` -> `Documents -> Re-process` succeeded for project `6`, document `387646`

## Next Step
- Run the release smoke gate again and keep `scripts/release_smoke_nlp_runtime.py` as the Windows runtime release check.

## Step 18 — Release Smoke DB Path Narrowed to Document-scoped Clone
- Status: completed
- Trigger:
  - the release smoke DB step still depended on either a full DB copy or a project-scoped import path, which remained too heavy for the real `hewiki_gpu_processing test.db` source.
- Code deliverables:
  - `scripts/release_smoke_nlp_runtime.py`
  - `tests/test_release_smoke_nlp_runtime.py`
- Confirmed behavior changes:
  - the DB smoke path no longer copies the whole source database
  - the smoke script now builds a tiny migrated target DB containing only the required base rows for one document:
    - `library`
    - `dict_project`
    - `source_corpus`
    - `source_document`
    - `document_text`
  - `reprocess_document()` then rebuilds all derived NLP rows on that small clone instead of depending on a 35GB source DB copy
  - the smoke report now records `db_copy_strategy = document_scoped_clone`
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile scripts\release_smoke_nlp_runtime.py tests\test_release_smoke_nlp_runtime.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_release_smoke_nlp_runtime.py tests\test_stanza_engine_subprocess.py tests\test_managed_stanza_runtime.py tests\test_nlp_runtime_probe.py tests\test_documents_process_progress_ui.py -q` -> `27 passed`
  - `.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --force-hostile-inprocess` -> managed subprocess `stanza` processed the Hebrew sample successfully
  - `.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --db-path "E:\projects\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --copy-db-to "E:\projects\Project_Vibe\V_book\reports\runtime_smoke\managed_runtime_smoke_copy.db" --doc-id 1` -> `ok=True`, `db_copy_strategy='document_scoped_clone'`, `run_engine='stanza'`, `run_status='ok'`, `runtime_effective='stanza'`

## Next Step
- Keep the document-scoped smoke path as the release gate default for large Windows databases.

## Step 19 — Bundled Hebrew Payload Packaging Source of Truth
- Status: completed
- Trigger:
  - the managed runtime contract was ready, but packaged release assembly still did not guarantee a bundled Hebrew payload inside the release artifact.
- Code/doc deliverables:
  - `scripts/stage_stanza_hebrew_payload.py`
  - `rebuild.ps1`
  - `hdle_premium_installer.spec`
  - `installer/resources/README.md`
  - `docs/BUILD_WINDOWS_INSTALLER.md`
- Confirmed behavior changes:
  - `rebuild.ps1` now stages a bundled Hebrew Stanza payload before PyInstaller runs
  - the canonical staging root is now:
    - `installer/resources/local_models/stanza_hebrew/`
  - the canonical packaged root is now:
    - `dist/HDLE_Premium/_internal/resources/nlp_runtime/stanza_payload/`
  - the staged payload includes:
    - `payload_manifest.json`
    - `stanza_resources/resources.json`
    - `stanza_resources/he/...`
  - the PyInstaller spec now collects that staged tree recursively into the frozen app
- Test evidence:
  - code review / file-level audit only in this patch foundation step

## Next Step
- Update managed runtime bootstrap so bundled packaged payload becomes the first-class source and ownership metadata is recorded explicitly.
## Step 20 — Managed Bootstrap Prefers Bundled Hebrew Payload Ownership
- Status: completed
- Trigger:
  - packaged release assembly now had a canonical bundled Hebrew payload root, but runtime bootstrap still treated bundled sources too generically and did not expose ownership truth.
- Code deliverables:
  - `app/services/nlp_runtime/managed_runtime.py`
  - `app/services/nlp_runtime/runtime_probe.py`
  - `app/services/nlp_runtime/dto.py`
  - `tests/test_managed_stanza_runtime.py`
  - `tests/test_nlp_runtime_probe.py`
- Confirmed behavior changes:
  - managed bootstrap source precedence is now deterministic:
    - `bundled_packaged`
    - `bundled_dev`
    - `legacy_cache`
    - existing managed copy remains `repaired_managed`
  - runtime manifest now records:
    - `model_source_kind`
    - `model_source_path`
    - `bundled_payload_root`
    - `payload_manifest_path`
  - runtime probe now surfaces bundled/source ownership as part of machine-readable status
  - repair/setup steps now mention payload ownership and bundled root when known
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\nlp_runtime\managed_runtime.py app\services\nlp_runtime\runtime_probe.py app\services\nlp_runtime\dto.py tests\test_managed_stanza_runtime.py tests\test_nlp_runtime_probe.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_managed_stanza_runtime.py tests\test_nlp_runtime_probe.py -q` -> `11 passed`

## Next Step
- Align Resources Manager / Health Check / Documents / release smoke to display and validate bundled payload ownership explicitly.
## Step 21 — Bundled Payload Ownership Exposed in UI, Health, and Smoke
- Status: completed
- Trigger:
  - bundled payload ownership was now recorded in bootstrap/probe state, but the primary product surfaces and release smoke still did not expose or assert that truth.
- Code deliverables:
  - `app/ui/resources_manager_dialog.py`
  - `app/services/health_check_service.py`
  - `app/ui/documents_view.py`
  - `scripts/release_smoke_nlp_runtime.py`
  - `tests/test_resources_manager_dialog.py`
  - `tests/test_health_check_service.py`
  - `tests/test_documents_engine_readiness.py`
  - `tests/test_release_smoke_nlp_runtime.py`
- Confirmed behavior changes:
  - Resources Manager now shows managed Hebrew payload ownership and bundled payload root in both runtime and resource sections
  - Health Check now reports bundled/source ownership in the runtime line when available
  - Documents runtime detail tooltip now includes managed source ownership and bundled payload root
  - release smoke now reports and can assert source ownership via:
    - `source_kind`
    - `source_path`
    - `bundled_payload_root`
  - release smoke now supports:
    - `--require-source-kind`
    - `--require-bundled-source`
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\ui\resources_manager_dialog.py app\services\health_check_service.py app\ui\documents_view.py scripts\release_smoke_nlp_runtime.py tests\test_resources_manager_dialog.py tests\test_health_check_service.py tests\test_documents_engine_readiness.py tests\test_release_smoke_nlp_runtime.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_resources_manager_dialog.py tests\test_health_check_service.py tests\test_documents_engine_readiness.py tests\test_release_smoke_nlp_runtime.py -q` -> `16 passed`

## Next Step
- Run full runtime regression and release smoke with `bundled_dev` enforcement, then finish handoff.
## Step 22 — Release Gate Confirmed for Bundled Hebrew Payload Delivery
- Status: completed
- Trigger:
  - release smoke originally surfaced an upgrade-path gap: an old managed manifest with obsolete `managed_existing` ownership prevented the smoke gate from proving bundled payload usage.
- Code deliverables:
  - `app/services/nlp_runtime/managed_runtime.py`
  - `tests/test_managed_stanza_runtime.py`
- Confirmed behavior changes:
  - bootstrap now upgrades obsolete managed manifest ownership to the current bundled source when a valid bundled payload is present
  - overwrite-safe payload copy semantics prevent `WinError 183` during managed payload refresh
  - release smoke now passes with enforced bundled ownership on the dev release path
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\nlp_runtime\managed_runtime.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_managed_stanza_runtime.py -q` -> `6 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_managed_stanza_runtime.py tests\test_stanza_engine_subprocess.py tests\test_nlp_runtime_probe.py tests\test_resources_manager_dialog.py tests\test_health_check_service.py tests\test_documents_engine_readiness.py tests\test_process_service_nlp_runtime.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_workspace_app_window_contract.py tests\test_release_smoke_nlp_runtime.py -q` -> `71 passed`
  - `$env:HDLE_DATA_ROOT='E:\projects\Project_Vibe\V_book\reports\runtime_smoke\managed_data_root'; .\.venv\Scripts\python.exe scripts\stage_stanza_hebrew_payload.py` -> staged payload from local cache into `installer/resources/local_models/stanza_hebrew`
  - `$env:HDLE_DATA_ROOT='E:\projects\Project_Vibe\V_book\reports\runtime_smoke\managed_data_root'; .\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --force-hostile-inprocess --require-source-kind bundled_dev --require-bundled-source` -> managed subprocess `stanza`, Hebrew sample processed, `source_kind='bundled_dev'`
  - `$env:HDLE_DATA_ROOT='E:\projects\Project_Vibe\V_book\reports\runtime_smoke\managed_data_root'; .\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --db-path "E:\projects\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --copy-db-to "E:\projects\Project_Vibe\V_book\reports\runtime_smoke\managed_runtime_smoke_copy.db" --doc-id 1 --require-source-kind bundled_dev --require-bundled-source` -> `ok=true`, `run_engine='stanza'`, `run_status='ok'`, `runtime_effective='stanza'`, `source_kind='bundled_dev'`

## Next Step
- Release engineering only:
  - verify the same smoke contract on the actual packaged build with `--require-source-kind bundled_packaged`
  - keep the staged bundled Hebrew payload as part of the release artifact pipeline


## Step 18 — Packaged Rebuild Audit for Bundled Hebrew Payload
- Status: completed
- Trigger:
  - the code path for `bundled_packaged` existed, but the previously checked `dist` artifact was stale and could not prove packaged ownership.
- Audit findings:
  - the canonical build flow is `rebuild.ps1` + `hdle_premium_installer.spec`
  - `scripts/build_windows.ps1` is an older standalone build helper and is not the current source of truth for installer-grade packaging
  - fast pre-build gates are currently blocked by unrelated dirty validation/runtime files, so packaged verification had to use `rebuild.ps1 -SkipFastGates`
- Confirmed packaging results:
  - `scripts/stage_stanza_hebrew_payload.py` stages the Hebrew payload correctly into `installer/resources/local_models/stanza_hebrew`
  - rebuilt `dist/HDLE_Premium/_internal/resources/nlp_runtime/stanza_payload/...` now exists and contains the staged Hebrew payload
  - packaged self-check respects `HDLE_DATA_ROOT` when run with an explicit output file
  - packaged `--stanza-probe` on a clean workspace-managed root now writes a manifest with:
    - `ownership = packaged_app`
    - `model_source_kind = bundled_packaged`
    - `bundled_payload_root = dist/HDLE_Premium/_internal/resources/nlp_runtime/stanza_payload`
- Remaining packaged runtime blocker:
  - the same packaged `--stanza-probe` still reports `error_code = hostile_torch_state`
  - packaged `--stanza-worker` still fails on the same `torch\lib\c10.dll` import path
  - this means bundled Hebrew payload delivery is now confirmed, but frozen Torch/Stanza runtime readiness is still not release-green
- Operational evidence:
  - `powershell -ExecutionPolicy Bypass -File .\rebuild.ps1 -SkipFastGates` -> build and installer succeeded
  - `reports/runtime_smoke/packaged_import_check.json` confirms packaged self-check with workspace `HDLE_DATA_ROOT`
  - `reports/runtime_smoke/packaged_stanza_probe.json` confirms `bundled_packaged` ownership plus `hostile_torch_state`
  - `reports/runtime_smoke/packaged_stanza_worker.jsonl` confirms packaged worker still fails on `c10.dll`

## Step 19 — Frozen Torch Runtime Hook Hardening for Packaged Probe/Worker
- Status: completed
- Trigger:
  - the packaged Hebrew payload was already bundled and ownership was already `bundled_packaged`, but the frozen `--stanza-probe` / `--stanza-worker` path still died on `torch\lib\c10.dll`.
- Code deliverables:
  - `app/infra/runtime_torch_bootstrap.py`
  - `app/runtime_hooks/pyi_rth_torch_dll_bootstrap.py`
  - `app/infra/nlp_engines/stanza_engine.py`
  - `hdle_premium_installer.spec`
  - `tests/test_stanza_engine_subprocess.py`
- Confirmed behavior changes:
  - Windows Torch DLL bootstrap is now shared through `app.infra.runtime_torch_bootstrap` instead of living only inside `stanza_engine.py`
  - the frozen app now runs Torch DLL bootstrap from a PyInstaller runtime hook before user-code imports
  - the runtime hook preloads the CRT bridge and `c10.dll` chain on frozen Windows builds to avoid the packaged `WinError 1114` import failure
  - packaged `--stanza-probe` now succeeds with:
    - `pipeline_init_ok = true`
    - `smoke_ok = true`
    - `source_kind = bundled_packaged`
  - packaged release smoke now succeeds with enforced bundled ownership on both:
    - direct engine smoke
    - DB reprocess smoke
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\infra\runtime_torch_bootstrap.py app\runtime_hooks\pyi_rth_torch_dll_bootstrap.py app\infra\nlp_engines\stanza_engine.py app\services\nlp_runtime\stanza_probe_worker.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_stanza_engine_subprocess.py tests\test_managed_stanza_runtime.py tests\test_nlp_runtime_probe.py -q` -> `19 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_managed_stanza_runtime.py tests\test_stanza_engine_subprocess.py tests\test_nlp_runtime_probe.py tests\test_resources_manager_dialog.py tests\test_health_check_service.py tests\test_documents_engine_readiness.py tests\test_process_service_nlp_runtime.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_documents_process_progress_ui.py tests\test_workspace_app_window_contract.py tests\test_release_smoke_nlp_runtime.py -q` -> `73 passed`
  - `$env:PATH='E:\projects\Project_Vibe\V_book\.venv\Scripts;' + $env:PATH; pyinstaller .\hdle_premium_installer.spec --clean --noconfirm` -> packaged rebuild succeeded and included `pyi_rth_torch_dll_bootstrap.py`
  - `dist\HDLE_Premium\HDLE_Premium.exe --stanza-probe` on a clean `HDLE_DATA_ROOT` -> `pipeline_init_ok=true`, `smoke_ok=true`, `source_kind='bundled_packaged'`
  - `.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --force-hostile-inprocess --require-source-kind bundled_packaged --require-bundled-source` with `HDLE_DATA_ROOT=reports\runtime_smoke\managed_data_root_packaged_hook2` -> passed
  - `.\.venv\Scripts\python.exe scripts\release_smoke_nlp_runtime.py --db-path hdle_premium.db --copy-db-to reports\runtime_smoke\runtime_smoke_copy_packaged_hook.db --doc-id 1 --require-source-kind bundled_packaged --require-bundled-source` with the same `HDLE_DATA_ROOT` -> passed
- Residual note:
  - packaged `--self-check import` still reports a separate ONNX helper timeout for `HDLE_ONNX_Probe.exe`; that is outside the frozen Torch/Stanza runtime track.

## Step 20 — Frozen ONNX Helper HF Home Hardening
- Status: completed
- Trigger:
  - the packaged Stanza/Torch runtime track was already release-green, but packaged `--self-check import` and the frozen ONNX helper still timed out separately.
- Audit findings:
  - `HDLE_ONNX_Probe.exe --help` returned immediately, so the bootloader/entrypoint path was alive.
  - `HDLE_ONNX_Probe.exe --mode import` and `--mode probe` both stalled before emitting JSON.
  - env-gated helper tracing showed the stall inside `_ensure_hf_home()` before `import onnxruntime`.
  - the blocking path was an inherited `HF_HOME=F:\huggingface`; write-probing that configured path was the actual startup timeout source.
- Code deliverables:
  - `app/tools/onnx_probe.py`
  - `tests/test_onnx_probe_contract.py`
  - governance docs in this patch
- Confirmed behavior changes:
  - the helper now treats an existing configured `HF_HOME` as a read-first cache root instead of forcing a write probe during frozen startup
  - missing/unusable configured HF cache paths now fall back to a local writable helper cache
  - the helper now also sets the Hugging Face startup guard rails needed for deterministic packaged probing:
    - `HF_HUB_DISABLE_SYMLINKS_WARNING=1`
    - `HF_HUB_DISABLE_TELEMETRY=1`
    - `HF_HUB_DISABLE_XET=1`
  - env-gated helper tracing is now available for future frozen ONNX diagnosis without changing the runtime contract
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\tools\onnx_probe.py tests\test_onnx_probe_contract.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_onnx_probe_contract.py tests\test_main_self_check_helpers.py tests\test_phonikud_adapter_modes.py tests\test_installer_spec_includes_onnx_probe.py -q` -> `38 passed`
  - `$env:PATH='E:\projects\Project_Vibe\V_book\.venv\Scripts;' + $env:PATH; pyinstaller .\hdle_premium_installer.spec --clean --noconfirm` -> packaged rebuild succeeded
  - `dist\HDLE_Premium\HDLE_ONNX_Probe.exe --mode import --out reports\runtime_smoke\onnx_probe_import_after_fix.json` -> `ok=true`, `stage='import'`
  - `dist\HDLE_Premium\HDLE_Premium.exe --self-check import --self-check-out reports\runtime_smoke\packaged_self_check_import_after_fix.json` -> `checks.onnxruntime_import.ok=true`
  - `dist\HDLE_Premium\HDLE_Premium.exe --self-check health --db-path hdle_premium.db --self-check-out reports\runtime_smoke\packaged_self_check_health_after_fix.json` -> `onnx_probe.ok=true`, `stage='infer'`, `has_niqqud=true`
- Outcome:
  - the packaged ONNX helper startup timeout track is now closed without reopening the already-green packaged Stanza/Torch runtime path.

## Step 21 — Schema-backed Runtime Provenance Promotion
- Status: completed
- Trigger:
  - packaged NLP runtime sign-off was already green, but run-level runtime provenance still required `ProcessorRun.note` parsing for SQL/debug/audit use.
- Code deliverables:
  - `app/infra/migrations/052_processor_run_runtime_provenance.sql`
  - `app/infra/sa_models.py`
  - `app/services/process_service.py`
  - `scripts/release_smoke_nlp_runtime.py`
  - `tests/test_process_service_nlp_runtime.py`
  - `tests/test_process_run_state_foundation.py`
  - `tests/test_process_batch_run_state.py`
  - `tests/test_release_smoke_nlp_runtime.py`
- Confirmed behavior changes:
  - `processor_run` now has dedicated runtime provenance fields for new rows:
    - `configured_engine_id`
    - `effective_engine_id`
    - `fallback_used`
    - `runtime_reason_code`
    - `runtime_mode`
    - `runtime_probe_summary_json`
  - `ProcessService` now dual-writes these fields while preserving the legacy machine-readable runtime envelope in `ProcessorRun.note`
  - single-document, batch, and snapshot-backfill runs all share the same schema-backed provenance write path
  - resumed legacy batch runs opportunistically receive the dedicated fields without dropping the old note contract
  - debug/smoke reads now prefer schema-backed provenance and fall back to `note` for older rows
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\process_service.py app\infra\sa_models.py scripts\release_smoke_nlp_runtime.py tests\test_process_service_nlp_runtime.py tests\test_process_batch_run_state.py tests\test_process_run_state_foundation.py tests\test_release_smoke_nlp_runtime.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_process_service_nlp_runtime.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_release_smoke_nlp_runtime.py -q` -> `20 passed`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_documents_engine_readiness.py tests\test_health_check_service.py tests\test_resources_manager_dialog.py tests\test_documents_process_progress_ui.py tests\test_workspace_app_window_contract.py tests\test_process_service_nlp_runtime.py tests\test_process_run_state_foundation.py tests\test_process_batch_run_state.py tests\test_release_smoke_nlp_runtime.py -q` -> `55 passed`
- Outcome:
  - runtime provenance is now schema-backed for new runs without reopening the already-closed packaged runtime tracks
  - old rows remain readable through the legacy note envelope fallback

## Step 22 — Project Bundle Stability Hardening
- Status: completed
- Trigger:
  - live operator feedback reported two separate project exchange symptoms:
    - `Import Project Bundle` ended with an error
    - `Export Project Bundle` looked hung on large projects
- Audit findings:
  - baseline project-exchange tests were still green, so the issue was not a generic bundle-format regression
  - heavy export on `project_id=1` reproduced a long final phase after payload creation with no granular heartbeat
  - interrupting that heavy export left a file under the final `.hdleproj` name that was not a valid ZIP; importing it reproduced the user-facing failure
  - the large live export path also reproduced a `database is locked` failure in the payload cleanup tail before bundle finalization
- Code deliverables:
  - `app/services/project_exchange/bundle_format.py`
  - `app/services/project_exchange/export_engine.py`
  - `app/services/project_exchange/worker.py`
  - `tests/test_project_exchange.py`
  - `tests/test_heavy_worker_slot_guard.py`
- Confirmed behavior changes:
  - bundle creation now stages to `*.hdleproj.partial` and publishes the final `.hdleproj` only on success
  - the export UI/CLI progress contract now shows final-stage heartbeat after payload creation:
    - `Computing checksums`
    - `Writing manifest`
    - `Writing payload`
    - `Writing checksums`
    - `Finalizing bundle`
  - import worker messaging now tells the operator when the selected bundle looks like an interrupted/incomplete export rather than a valid archive
  - export-side SQLite cursors are now explicitly closed before the final payload schema cleanup, which removed the reproduced `database is locked` tail failure on the heavy live export path
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\project_exchange\bundle_format.py app\services\project_exchange\export_engine.py app\services\project_exchange\worker.py tests\test_project_exchange.py tests\test_heavy_worker_slot_guard.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_project_exchange.py tests\test_project_exchange_preflight.py tests\test_project_exchange_dialogs.py tests\test_heavy_worker_slot_guard.py tests\test_workspace_app_window_contract.py -q` -> `41 passed`
  - `.\.venv\Scripts\python.exe scripts\export_project_bundle.py --db-path .\hdle_premium.db --project-id 7 --out .\reports\project_exchange_repro\project7_smoke.hdleproj` -> success with granular final-stage progress
  - `.\.venv\Scripts\python.exe scripts\import_project_bundle.py --db-path .\reports\project_exchange_repro\import_target_smoke.db --bundle .\reports\project_exchange_repro\project7_smoke.hdleproj` -> roundtrip import success
  - interrupted heavy export smoke on `project_id=1` now leaves only `project1_smoke.hdleproj.partial` and does not publish a misleading final `.hdleproj`
- Outcome:
  - the confirmed import/export failure chain is now narrowed and safer without reopening packaged runtime work
  - very large export remains long-running, but it is no longer silent and no longer leaves a false final bundle name when interrupted

## Step 23 — Project Export Product Closure
- Status: completed
- Trigger:
  - the previous stability hardening removed the invalid-final-bundle failure chain, but export still hung on the live reference DB after `Dropping excluded tables`.
  - product acceptance now required a deterministic export lifecycle for project `6` (`Mishneh Torah`) on the large reference DB.
- Audit findings:
  - the active source-of-truth export path is:
    - `app/ui/app_window.py` -> `ProjectExportWorker` -> `ProjectExportEngine.export_project()` -> `bundle_format.create_bundle()`
  - the live hang was not generic SQLite slowness and not an import-side issue:
    - export stalled on a second `DROP TABLE IF EXISTS sentence_fts` inside the generic exclusion loop
    - the first explicit FTS prune had already dropped `sentence_fts` / `term_fts`
  - the clean import gate exposed a separate compatibility gap:
    - `document_sentence.corpus_id` exists since schema `31`
    - the import remap contract still treated `document_sentence` as if only `doc_id` were a foreign key
- Code deliverables:
  - `app/services/project_exchange/dto.py`
  - `app/services/project_exchange/bundle_format.py`
  - `app/services/project_exchange/export_engine.py`
  - `app/services/project_exchange/constants.py`
  - `app/services/project_exchange/worker.py`
  - `app/ui/dialogs/project_exchange_dialogs.py`
  - `scripts/export_project_bundle.py`
  - `tests/test_project_exchange.py`
  - `tests/test_project_exchange_dialogs.py`
- Confirmed behavior changes:
  - export now uses an explicit product stage model with structured stage history:
    - `prepare_context`
    - `preflight_checks`
    - `create_staging_db`
    - `apply_schema`
    - `attach_host_db`
    - `prepare_fts`
    - `resolve_project_scope`
    - `copy_tables`
    - `export_pronunciation_metadata`
    - `build_manifest`
    - `prune_payload`
    - `finalize_sqlite`
    - `build_bundle`
    - `validate_artifact`
    - `completed`
  - finalization now skips duplicate FTS drops by pruning `sentence_fts` / `term_fts` once, then excluding only the remaining operational tables
  - payload finalization steps now run with stage-aware heartbeat and bounded timeout semantics instead of silent indefinite execution
  - bundle success now depends on explicit post-build validation:
    - ZIP structure and checksums via `read_bundle()`
    - payload `PRAGMA quick_check(1)` on the extracted `payload.sqlite`
  - CLI/UI success surfaces now expose final stage and artifact validation evidence
  - import compatibility for exported bundles is restored for schema `31+` payloads because `document_sentence.corpus_id` is now part of the remap contract
- Test evidence:
  - `.\.venv\Scripts\python.exe -m py_compile app\services\project_exchange\constants.py app\services\project_exchange\dto.py app\services\project_exchange\bundle_format.py app\services\project_exchange\export_engine.py app\services\project_exchange\worker.py app\ui\dialogs\project_exchange_dialogs.py scripts\export_project_bundle.py tests\test_project_exchange.py tests\test_project_exchange_dialogs.py` -> `OK`
  - `.\.venv\Scripts\python.exe -m pytest tests\test_project_exchange.py tests\test_project_exchange_preflight.py tests\test_project_exchange_dialogs.py tests\test_heavy_worker_slot_guard.py tests\test_workspace_app_window_contract.py -q` -> `46 passed`
  - reference DB export acceptance:
    - `.\.venv\Scripts\python.exe .\scripts\export_project_bundle.py --db-path "E:\projects\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --project-id 6 --out "E:\projects\Project_Vibe\V_book\-info files\Экспорт проекта\Mishneh_Torah_project_6_acceptance.hdleproj"` -> `exit code 0`, `[OK] Export successful!`, validated bundle produced
  - clean import compatibility gate:
    - `.\.venv\Scripts\python.exe .\scripts\import_project_bundle.py --db-path "E:\projects\Project_Vibe\V_book\reports\project_exchange_repro\mishneh_torah_import_target.db" --bundle "E:\projects\Project_Vibe\V_book\-info files\Экспорт проекта\Mishneh_Torah_project_6_acceptance.hdleproj"` -> `exit code 0`, `[OK] Import successful!`
- Outcome:
  - project export is now a deterministic, observable, artifact-validated pipeline rather than a best-effort long operation
  - the reference-DB `Mishneh Torah` export path is now closed with a validated bundle and a clean import roundtrip

