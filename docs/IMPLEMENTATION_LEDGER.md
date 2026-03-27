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

## Next Step
- Wave 3 UX remediation hardening:
  - expand setup/repair guidance into a more guided in-product flow
  - differentiate external runtime dependency issues from managed Hebrew model/resource actions more explicitly
  - consider structured provenance beyond `ProcessorRun.note` once the Wave 1/2 contract stabilizes
