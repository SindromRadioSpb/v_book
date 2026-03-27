# Handoff Status

## Current Task
- `task31`: product-grade NLP runtime management

## Current Phase
- Wave 1 safety-first foundation completed

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

## In Progress
- No active implementation in this patch series.

## Remaining Risks
- Runtime probe still depends on importing the local Stanza/Torch stack and may surface hostile environment failures as warnings.
- Resources Manager currently exposes runtime truth, but not a full repair wizard.
- Product still lacks packaged-vs-dev remediation guidance in the UI.

## Next Step
- Proceed to deeper runtime-probe hardening, preferably subprocess-based, plus packaging-aware remediation.
