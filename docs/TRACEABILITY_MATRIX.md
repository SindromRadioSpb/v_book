# Traceability Matrix

| Problem | Requirement | Code Area | Planned Verification | Docs |
|---|---|---|---|---|
| Silent persisted fallback to Mock | Persisted processing must not silently fall back | `app/services/process_service.py`, `app/ui/documents_view.py` | `tests/test_process_service_nlp_runtime.py`, `tests/test_documents_engine_readiness.py` | `IMPLEMENTATION_LEDGER.md`, `HANDOFF_STATUS.md` |
| User cannot tell expected vs actual engine | Split configured vs effective engine | `app/services/process_service.py`, `app/services/nlp_runtime/` | `tests/test_process_service_nlp_runtime.py` | `DECISIONS_LOG.md`, `CONTEXT_STATE.md` |
| Readiness is shallow and misleading | Introduce runtime diagnostics truth | `app/ui/workers.py`, `app/services/nlp_runtime/` | `tests/test_documents_engine_readiness.py` | `IMPLEMENTATION_LEDGER.md` |
| No audit-grade provenance per run | Add run-level NLP provenance | `app/services/process_service.py` | `tests/test_process_service_nlp_runtime.py`, `tests/test_process_run_state_foundation.py` | `HANDOFF_STATUS.md` |
| NLP invisible in health/resources UX | Expose NLP in Health Check and Resources Manager | `app/services/health_check_service.py`, `app/ui/resources_manager_dialog.py` | `tests/test_health_check_service.py`, `tests/test_resources_manager_dialog.py` | `CONTEXT_STATE.md`, `HANDOFF_STATUS.md` |
| Documents has no obvious remediation path | Add explicit diagnose/setup actions in Documents | `app/ui/documents_view.py` | `tests/test_documents_engine_readiness.py` | `IMPLEMENTATION_LEDGER.md`, `HANDOFF_STATUS.md` |
