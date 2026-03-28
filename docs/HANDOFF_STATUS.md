# Handoff Status

## Current Task
- `task31`: product-grade NLP runtime management

## Current Phase
- P0 re-process lifecycle hotfix completed after PATCH-04

## Completed
- Audit completed and recorded.
- Governance docs created.
- Product direction and rollout decisions recorded.
- Silent mock fallback removed from persisted processing.
- Configured vs effective runtime state added.
- Run-level runtime provenance added via `ProcessorRun.note`.
- NLP runtime visibility added to Health Check and Resources Manager.
- Resources Manager crash on hostile runtime probe was fixed with guarded fallback UI.
- Documents now exposes direct `Diagnose NLP` and `Open NLP Setup` actions.
- Stanza/Torch runtime probing is now isolated in a subprocess instead of the live UI process.
- Resources Manager now exposes packaging-aware repair steps and guarded NLP model-folder access.
- Wave 2 is now treated as the stable baseline for runtime-management behavior.
- Resources Manager now separates `External Runtime Dependency` from `Managed Hebrew Resource`.
- Documents and Health Check now use the same runtime/resource vocabulary.
- `ProcessorRun.note` now includes a stable nested `runtime` provenance envelope alongside legacy flat keys.
- Guided repair routing is now shared across Documents, Health Check, and Resources Manager.
- Live engine-init failures after a successful subprocess probe now collapse into the managed runtime-block path instead of surfacing as raw worker tracebacks.
- Documents can now recover from that managed runtime-block by offering a guided recovery dialog from the main-thread error flow.
- Real Stanza processing can now continue even when the Qt process cannot import Torch directly, because `create_stanza_engine()` falls back to a subprocess-backed runtime.
- Resources Manager now says explicitly that Python runtime dependencies are external to the dialog and that the Hebrew model is a directory-based resource.
- Owner-bound runtime workers now shut down deterministically before `Resources Manager`, `DocumentsView`, or `AppWindow` are destroyed.
- The product now owns a managed Stanza runtime root under app data, with a runtime manifest and a managed `stanza_resources/he` path.
- Windows production processing now prefers an app-owned subprocess runtime launched through `app.main --stanza-worker`.
- The isolated runtime probe now uses the sibling `app.main --stanza-probe` path, so diagnostics and production processing share the same ownership model.
- Resources Manager now exposes an official `Install / Repair NLP Runtime` action for the managed runtime path.
- Documents and Health Check now point to that same official `Install / Repair NLP Runtime` action, so the repair route is shared across the primary UI surfaces.
- Managed runtime bootstrap now rejects partial Hebrew payloads and repairs them from a valid bundled/legacy source instead of reusing a broken copy.
- The app-owned probe/worker runtime now prepares Torch/CUDA DLL search paths before importing `stanza/torch`, eliminating the observed `WinError 1114` blocker in the managed subprocess path.
- `scripts/release_smoke_nlp_runtime.py` now provides the release smoke gate for hostile in-process Qt launch, managed subprocess startup, Hebrew sample processing, and DB-copy `Re-process`.
- Release smoke has confirmed a real `Re-process` success on a copied DB with `run_engine='stanza'`, `run_status='ok'`, and `runtime_effective='stanza'`.
- ProcessWorker no longer shadows QThread.finished; DocumentsView now deletes the worker only from the real thread-finished callback.

## In Progress
- No active implementation in this patch series.

## Remaining Risks
- Resources Manager still does not provide a full guided install wizard; it provides truthful diagnostics and repair guidance only.
- Structured runtime provenance still lives inside `ProcessorRun.note`; it is machine-readable, but not yet promoted to dedicated schema fields.
- The guided repair journey is coherent, but it is still rendered across multiple surfaces rather than one dedicated wizard.
- The current managed bootstrap can copy from bundled resources or a legacy Stanza cache, but the repo still does not contain a bundled Hebrew model payload for packaged release assembly.
- Runtime/bootstrap still needs to prefer the new bundled packaged payload explicitly and surface that ownership truth in probe/UI/smoke output.

## Next Step
- Complete bundled Hebrew payload delivery:
  - prefer bundled packaged payload during managed bootstrap
  - expose payload ownership in runtime probe / UI / smoke
  - keep using `scripts/release_smoke_nlp_runtime.py` as the Windows runtime release gate

## Latest Confirmation
- The original live GUI repro path is now confirmed fixed on the target machine:
  - project `6`
  - document `387646`
  - `Documents -> Re-process` completed successfully
- The `QThread: Destroyed while thread '' is still running` crash no longer reproduces on that path.
- The release smoke DB step is now narrowed to a `document_scoped_clone` path, so the runtime gate no longer depends on copying the full 35GB source DB.
- The narrowed DB smoke has now succeeded on the real Windows source DB with `run_engine='stanza'`, `run_status='ok'`, and `runtime_effective='stanza'`.
- Packaging foundation for bundled Hebrew payload is now in place:
  - staged source root: `installer/resources/local_models/stanza_hebrew/`
  - packaged target root: `_internal/resources/nlp_runtime/stanza_payload/`

