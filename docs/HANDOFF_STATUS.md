# Handoff Status

## Current Task
- `task31`: product-grade NLP runtime management

## Current Phase
- PATCH-03 official setup / repair flow completed

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

## In Progress
- No active implementation in this patch series.

## Remaining Risks
- Resources Manager still does not provide a full guided install wizard; it provides truthful diagnostics and repair guidance only.
- Structured runtime provenance still lives inside `ProcessorRun.note`; it is machine-readable, but not yet promoted to dedicated schema fields.
- The guided repair journey is coherent, but it is still rendered across multiple surfaces rather than one dedicated wizard.
- The runtime recovery path is thread-safe now, but it is still diagnosis/setup/fallback orchestration only; it does not yet establish a product-owned managed Stanza runtime/bootstrap path.
- The current managed bootstrap can copy from bundled resources or a legacy Stanza cache, but the repo still does not contain a bundled Hebrew model payload for packaged release assembly.
- Release-grade smoke artifacts and handoff still need one final sync pass around the new app-owned runtime path.

## Next Step
- PATCH-04: add release-grade smoke validation, final docs sync, and short handoff for the managed Windows Stanza runtime.
