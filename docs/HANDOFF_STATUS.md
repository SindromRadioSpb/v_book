# Handoff Status

## Current Task
- `task31`: product-grade NLP runtime management

## Current Phase
- Wave 3 PATCH-02 structured runtime provenance completed

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

## In Progress
- No active implementation in this patch series.

## Remaining Risks
- Resources Manager still does not provide a full guided install wizard; it provides truthful diagnostics and repair guidance only.
- Structured runtime provenance still lives inside `ProcessorRun.note`; it is machine-readable, but not yet promoted to dedicated schema fields.
- Guided repair flow is still spread across Documents, Health Check, and Resources Manager rather than one coherent step-by-step route.

## Next Step
- Proceed to Wave 3 PATCH-03: harden the guided repair journey across Documents, Health Check, and Resources Manager without adding pseudo-package-manager semantics.
