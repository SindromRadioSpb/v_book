# First-Run Wizard First-Usable-State Repair (2026-03-13)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/FIRST_RUN_WIZARD_COLD_AUDIT_2026-03-13.md`

This repair stays narrow:

- it changes only the first-run wizard health-summary loading contract;
- it preserves DB selection, resource status, and six-page wizard structure;
- it does not change `HealthCheckService` semantics, provider flows, or setup execution;
- it does not reopen Documents, ProjectView, Audio Add-All, Coverage, TM,
  Sentences, startup, or heavy-validation branches.

## Patch scope

Code changes:

- `app/ui/first_run_wizard.py`
- `tests/test_first_run_wizard.py`
- `tests/test_first_run_wizard_db_step.py`
- `tests/test_first_run_wizard_staged_health.py`

Bounded implementation:

- `FirstRunWizardDialog` no longer runs the full health summary synchronously on
  the constructor path;
- the wizard now opens with staged health state:
  - status label: `Checking health summary in background...`
  - health text preview: `Checking health summary in background...`
- `UnifiedHealthCheckWorker` is now reused for the wizard health summary;
- DB/profile and resource-status sections still load immediately on open;
- the wizard now queues one follow-up refresh if a health rerun is requested
  while the current background run is still active;
- once the background worker completes, the wizard updates:
  - health status label
  - full health summary text
  - refresh-button enabled state
- no `HealthCheckService` logic or check semantics were changed.

## Evidence artifacts

- `build/logs/cold_audit/candidate_sweep/remaining_visible_surfaces_2026-03-13.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_breakdown.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_cold_audit_summary.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_repair_after.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_repair_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- access mode: strict read-only for the after-repair probe

Safety evidence:

- `first_run_wizard_repair_after.json` records `db_mtime_unchanged=true`;
- the repair introduces no new write path;
- the after probe used a read-only DB wrapper while instantiating the wizard.

## Before / after summary

Before the repair, the audit wave recorded:

- bounded remaining-surface sweep:
  - `first_run_wizard`: `4.273s`
  - `audio_provider_settings`: `0.121s`
  - `reference_setup_wizard`: `0.017s`
  - `help_center`: `0.006s`
- first-run breakdown:
  - full wizard cold open: `4.273s`
  - `HealthCheckService.run_all()`: `3.992s`
  - pronunciation bootstrap health probe: `2.378s`
  - sentence niqqud bootstrap health probe: `1.970s`
  - DB/profile inspection: `0.005s`

After the repair:

- `FirstRunWizardDialog` init now returns in `0.034s`
- health summary completes later in `5.254s`
- wizard open state now stays immediately usable:
  - page count: `6`
  - current page index: `0`
  - health label on open: `Checking health summary in background...`
  - health preview on open: `Checking health summary in background...`
- after background completion:
  - final health label: `Health summary ready (warn).`
  - health summary lines: `15`

Engineering meaning:

- the original blocker was constructor-path completeness work, not the wizard shell;
- the repair removes the full health summary from the first usable state
  critical path;
- the user can now interact with the wizard immediately while the health
  summary finishes in the background;
- the heavy pronunciation bootstrap probes still run, but they are now stage-2
  completeness work rather than open-time gating work.

## Current classification

Current status after the repair:

- `first usable state blocker`: closed
- `recommended priority`: `P0` closed
- `current residual tail`: background health-summary completion only
- `open immediate second patch`: no

Decision logic:

- the approved-target and current-machine blocker was synchronous health-summary
  completion on open;
- that work is now off the critical path for wizard usability;
- health completeness still arrives later and remains accurate;
- no provider-flow redesign, setup-execution redesign, or `HealthCheckService`
  rewrite is justified from this repair alone.

## Branch and roadmap effect

This repair closes the active first-run wizard `P0` branch.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- Coverage lemma-count residual-tail branch
- Audio Add-All branch
- generic Documents branch
- ProjectView branch
- standalone `Term Cards` branch
- `VerificationPanel`
- `UserDictionariesView`
- `DatabaseSwitchDialog`
- `ProviderSettingsDialog`
- `ResourcesManagerDialog`
- `ImportWizard`
- `ReferenceSetupWizard`
- `HelpCenterDialog`

What stays decision-gated:

- any future first-run wizard residual-tail work
- any current-machine provider credential-health follow-up
- any broader onboarding flow redesign

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem wave,
  unless new approved-target evidence promotes a new onboarding blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_first_run_wizard.py tests\test_first_run_wizard_db_step.py tests\test_first_run_wizard_staged_health.py -q
```

Import smoke:

```powershell
.\.venv\Scripts\python.exe -c "import app; from app.ui.first_run_wizard import FirstRunWizardDialog; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/first_run_wizard/first_run_wizard_repair_after.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_repair_summary.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_cold_audit_summary.json`
