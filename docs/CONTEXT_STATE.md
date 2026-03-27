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
- Resources Manager still exposes NLP only as a runtime status summary, not as a full setup/repair workflow.
- Documents still lacks a dedicated `Diagnose NLP` / `Open NLP Setup` CTA.
- Dev-mode vs packaged-mode remediation semantics are not yet documented in-product.

## Constraints
- PowerShell-only workflow.
- Do not touch `AGENTS.md`.
- Keep Wave 1 scope tight: safety and truth foundation only.
- Documentation must be updated after each logically completed step.

## Current Delivery Intent
- Wave 1:
  - safety-first invariant
  - runtime truth layer
  - run-level provenance
  - initial NLP visibility in health/resources UX

## Confirmed Current State After Wave 1
- `ProcessService` no longer silently converts Stanza failures into Mock runs.
- Documents UI requires explicit fallback confirmation before running persisted processing on Mock.
- `ProcessorRun.note` now records configured/effective engine and fallback provenance.
- Health Check includes `nlp_runtime:stanza`.
- Resources Manager shows current Stanza runtime status text.
- Resources Manager no longer crashes if the NLP runtime probe itself raises.
- Documents exposes direct `Diagnose NLP` and `Open NLP Setup` actions.
