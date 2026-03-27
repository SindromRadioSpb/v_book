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
- Run-level provenance is still additive text in `ProcessorRun.note`, not structured relational metadata.
- External runtime dependency repair and managed model import are still surfaced in one dialog, though now with clearer boundaries.

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
