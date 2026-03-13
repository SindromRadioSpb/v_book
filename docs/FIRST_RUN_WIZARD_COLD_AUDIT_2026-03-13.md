# First-Run Wizard Cold Audit (2026-03-13)

## Why this document exists

This is the nineteenth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- first-run setup wizard cold open / first usable state

This wave does **not**:

- ship a runtime patch;
- reopen Documents, ProjectView, Audio Add-All, Coverage, TM, Sentences, or
  startup branches;
- redesign setup execution, resource download/import, or provider flows;
- open heavy validation.

## Scope

In scope:

- `FirstRunWizardDialog` cold open on the current machine state
- bounded candidate sweep across remaining visible surfaces
- strict read-only DB-backed checks against the approved hewiki test DB
- synchronous open-time health summary work
- blocker vs not-blocker classification

Out of scope:

- actual setup execution (`Finish`, restart, or resource install actions)
- `ReferenceSetupWizard` background processing flow
- MT/audio provider configuration semantics
- resource install/import repair flows
- wizard redesign beyond staged first usable state

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `FR1` | Remaining visible-surface candidate sweep | current machine + read-only approved-target DB shim where needed | Picks the next wave from fresh evidence after the original sweep was exhausted | Completed |
| `FR2` | Full `FirstRunWizardDialog` cold open | current machine + read-only approved-target DB shim | Measures the real onboarding gate | Completed |
| `FR3` | DB/profile step breakdown | current machine | Separates database-selection metadata work from the rest of the wizard open path | Completed |
| `FR4` | Resource status breakdown | current machine | Separates resource registry checks from the heavy layer | Completed |
| `FR5` | Health summary breakdown | current machine + read-only approved-target DB shim | Localizes the dominant synchronous stage inside the wizard | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/first_run_wizard.py`
- `app/services/health_check_service.py`
- `app/infra/pronunciation/phonikud_adapter.py`
- `app/services/resources/resource_registry.py`
- `app/infra/db_path_resolver.py`

Current smoke/regression entry points:

- `tests/test_first_run_wizard.py`
- `tests/test_first_run_wizard_db_step.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/remaining_visible_surfaces_2026-03-13.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_breakdown.json`
- `build/logs/cold_audit/first_run_wizard/first_run_wizard_cold_audit_summary.json`

DB-backed probe target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only

## Current UI/workflow contract

Current first-run wizard open path:

- `FirstRunWizardDialog.__init__()` instantiates:
  - `SettingsService`
  - `ResourceRegistry`
  - `HealthCheckService`
- `_init_ui()` builds all six pages and then immediately runs:
  - `_refresh_db_step_paths()`
  - `_update_db_step_state()`
  - `_refresh_resource_status()`
  - `_refresh_health_summary()`
- `_refresh_health_summary()` synchronously calls `HealthCheckService.run_all()`
- `HealthCheckService.run_all()` currently includes:
  - required resource checks
  - pronunciation bootstrap check
  - sentence niqqud bootstrap check
  - cloud-provider readiness checks
  - baseline reference check

Engineering meaning:

- the wizard shell is not staged today;
- first usable state is blocked by the full health summary;
- the dominant cost is not DB-path metadata or resource-status refresh.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | A new bounded candidate sweep was run before opening a new branch. | Completed |
| `2. Cold vs warm measurement` | Fresh-process constructor probes were used for the remaining visible surfaces. | Completed |
| `3. Step-by-step cold breakdown` | Wizard open, DB/profile work, resource status, and health summary were separated. | Completed |
| `4. SQL-level timing / query audit` | DB-backed work stayed bounded to read-only health checks only. | Completed with bounded scope |
| `5. Service/process timing` | `HealthCheckService.run_all()` and its subchecks were measured separately. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained unchanged under strict read-only probes. | Completed |
| `7. UI first-render / first-usable-state audit` | The full wizard shell waits on sync health summary completion today. | Completed |
| `8. Degraded / fallback mode audit` | No staged or deferred health-summary path exists today. | Completed |
| `9. Dataset-tier analysis` | DB-backed checks stayed cheap; local pronunciation bootstrap probes dominate instead. | Completed |
| `10. Repeatability protocol` | The commands below reproduce the same bounded decision gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `FR1`-`FR5` were fixed before interpretation. | Prevented vague “setup wizard feels slow” claims. |
| `B. Bounded live probes` | Remaining visible surfaces were compared under the same offscreen probe style. | The next wave target came from current evidence. |
| `C. SQL top offenders log` | DB/profile inspection is only `0.005s`; baseline reference check is only `0.001s`. | SQL is not the current blocker layer. |
| `D. UI responsiveness probes` | `FirstRunWizardDialog` cold open is `4.273s`; the next largest remaining candidate is only `0.121s`. | The wizard is now the clear next blocker. |
| `E. Service initialization audit` | `HealthCheckService.run_all()` is `3.992s`. | The health summary dominates the constructor path. |
| `F. Drift / fallback path audit` | `PhonikudAdapter.health_check()` is still invoked synchronously on open through the health summary. | A staged/deferred repair is justified. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It opens a bounded repair branch but does not implement it. |

## Current findings

### Candidate-selection evidence

From `remaining_visible_surfaces_2026-03-13.json`:

- `first_run_wizard`: `4.273s`
- `audio_provider_settings`: `0.121s`
- `reference_setup_wizard`: `0.017s`
- `help_center`: `0.006s`

Engineering meaning:

- after the original visible candidate sweep was exhausted, the next bounded
  candidate sweep found one clear outlier;
- `FirstRunWizardDialog` is materially slower than the remaining visible
  surfaces;
- `AudioProviderSettingsDialog` is no longer a latency candidate, only a
  separate credential-health topic if needed.

### First-run breakdown

From `first_run_wizard_breakdown.json`:

- `inspect_default_db_s`: `0.005s`
- `resource_status::nikud_pronunciation_model_s`: `0.003s`
- `resource_status::sentence_niqqud_model_s`: `0.001s`
- `resource_status::hewiki_baseline_processed_bundle_s`: `0.001s`
- `health_required_resources_s`: `0.002s`
- `health_pronunciation_bootstrap_s`: `2.378s`
- `health_sentence_niqqud_bootstrap_s`: `1.970s`
- `health_cloud_providers_s`: `0.089s`
- `health_baseline_reference_s`: `0.001s`
- `health_run_all_s`: `3.992s`

Additional current-state context:

- default DB schema on this machine: `35`
- health overall: `warn`
- health item count: `9`
- approved DB `mtime` stayed unchanged

Engineering meaning:

- the wizard is not blocked by DB metadata inspection;
- the wizard is not blocked by resource registry status refresh;
- the dominant cold layer is synchronous health summary work;
- inside that summary, the heavy substeps are the two inline pronunciation
  bootstrap probes driven through `PhonikudAdapter.health_check()`.

### Current-machine dependency-health note

The same breakdown also surfaced a separate warning:

- `Failed to read credential audio_provider:google_cloud_tts:service_account_json: Failed to decrypt credential: Decryption failed: authentication tag invalid (data corrupted or tampered)`

Engineering meaning:

- this is a current-machine credential-health drift;
- it is not the main first-run latency blocker;
- it should not widen this wave into provider-settings runtime work.

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- first-run onboarding is a high-visibility entry workflow;
- the wizard currently spends `4.273s` in synchronous open-time work before the
  user gets a usable setup screen;
- `3.992s` of that cost sits inside the health summary, and nearly all of that
  is local pronunciation bootstrap probing;
- the repair shape is bounded:
  - make the shell/pages usable first;
  - defer or stage the health summary;
  - keep DB/profile and resource status semantics intact.

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- `First-run wizard staged health summary / first usable state repair`

Bounded patch scope implied by the evidence:

- remove full health-summary completion from the wizard open critical path;
- preserve the existing six-page wizard structure;
- keep DB selection and resource-status display immediately available;
- update health status later through a staged/deferred path;
- avoid widening into provider-settings redesign, resource install work, or
  reference-setup execution changes.

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

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\first_run_wizard | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_first_run_wizard.py tests\test_first_run_wizard_db_step.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.first_run_wizard import FirstRunWizardDialog; print('OK')"

rg -n "FIRST_RUN_WIZARD_COLD_AUDIT_2026-03-13.md|4\\.273s|3\\.992s|First-run wizard staged health summary / first usable state repair" docs\FIRST_RUN_WIZARD_COLD_AUDIT_2026-03-13.md docs\ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md
```

Expected bounded outcomes:

- the first-run wizard remains a proven current blocker;
- the dominant layer stays localized to sync health-summary work;
- approved DB evidence remains read-only;
- the next repair branch stays bounded to staged first usable state.
