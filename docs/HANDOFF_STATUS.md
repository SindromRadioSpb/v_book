# Handoff Status

## Current Task
- `task31`: product-grade NLP runtime management

## Current Phase
- Wave 2 probe hardening and repair guidance completed

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

## In Progress
- No active implementation in this patch series.

## Remaining Risks
- Resources Manager still does not provide a full guided install wizard; it provides truthful diagnostics and repair guidance only.
- Run provenance is still stored additively in `ProcessorRun.note`.
- Managed Hebrew model actions and external Python runtime diagnostics still share one dialog surface.

## Next Step
- Proceed to Wave 3 UX hardening: deepen the guided setup/repair path without turning Resources Manager into a pseudo package manager, and consider structured provenance once the runtime contract stabilizes.
