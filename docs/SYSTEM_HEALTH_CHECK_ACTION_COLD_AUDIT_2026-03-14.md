# System Health Check Action Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-seventh task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `AppWindow.open_system_health_check()` trigger path / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret full background health-check completion time as trigger-path cost;
- audit `HealthCheckService.run_all()` latency as a cold-open blocker;
- reopen first-run wizard health-summary work;
- open heavy validation.

## Scope

In scope:

- top-level `System Health Check` action trigger path from `AppWindow`
- worker creation/start wiring and immediate operator feedback
- candidate comparison against `About HDLE Premium`
- blocker vs not-blocker classification

Out of scope:

- `UnifiedHealthCheckWorker.run()`
- `HealthCheckService.run_all()` completion latency
- modal report rendering after worker finish
- remediation semantics of individual health items

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `SHA1` | New top-level action candidate sweep | current repo code | Confirms the next action-surface wave after visible/dialog sweeps closed | Completed |
| `SHA2` | `open_system_health_check()` trigger path | actual `AppWindow` method body with bounded fake worker | Measures immediate user-visible action latency | Completed |
| `SHA3` | Worker-start contract audit | actual `AppWindow` method body with bounded fake worker | Confirms heavy health work stays background-first | Completed |
| `SHA4` | Immediate operator-feedback audit | actual `AppWindow` method body with bounded fake worker | Confirms action posts status feedback before background completion | Completed |
| `SHA5` | Lower-baseline comparison with `open_about_dialog()` payload build | current repo code | Confirms relative ranking among remaining top-level actions | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/app_window.py`
- `app/ui/workers.py`
- `app/services/health_check_service.py`
- `app/build_meta.py`

Current smoke/regression entry points:

- `tests/test_health_check_service.py`
- `tests/test_first_run_wizard_staged_health.py`
- `tests/test_workspace_app_window_contract.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/top_level_actions_2026-03-14.json`
- `build/logs/cold_audit/system_health_check_action/system_health_check_action_probe.json`
- `build/logs/cold_audit/system_health_check_action/system_health_check_action_cold_audit_summary.json`

## Current UI/workflow contract

Current `AppWindow.open_system_health_check()` path:

- checks whether `_health_check_worker` is already active
- posts status:
  - `Running health check...`
- constructs `UnifiedHealthCheckWorker`
- stores it in `_health_check_worker`
- wires:
  - `finished -> _show_report`
  - `error -> _show_error`
  - completion/error cleanup callbacks
- starts the worker
- returns immediately

Engineering meaning:

- heavy health-check work is intentionally background-only;
- trigger path is just worker setup plus status update;
- no synchronous health-summary computation occurs on the trigger path.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Top-level action trigger was separated from background health completion. | Completed |
| `2. Cold vs warm measurement` | Dedicated bounded trigger probe used the actual `AppWindow` method body. | Completed |
| `3. Step-by-step cold breakdown` | Trigger path, status update, worker creation, and lower-baseline action were isolated. | Completed |
| `4. SQL-level timing / query audit` | Trigger path exposes no SQL layer. | Completed |
| `5. Service/process timing` | Heavy health work is not on the trigger path. | Completed |
| `6. Filesystem / OS / DB-open audit` | Trigger path does not touch DB/network directly before returning. | Completed |
| `7. UI first-render / first-usable-state audit` | Action returns immediately after bounded worker setup. | Completed |
| `8. Degraded / fallback mode audit` | Existing active-worker guard degrades to a status message instead of duplicate work. | Completed |
| `9. Dataset-tier analysis` | Trigger-path latency is independent of corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `SHA1`-`SHA5` were fixed before interpretation. | Prevented mixing action trigger cost with background health runtime. |
| `B. Bounded live probes` | Dedicated top-level-action probe used the real method body with a bounded fake worker. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on the trigger path. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Trigger path is `0.000408s`. | User-visible action latency is effectively instant. |
| `E. Service initialization audit` | Worker construction/start is the only meaningful action-stage work. | Still far below blocker territory. |
| `F. Drift / fallback path audit` | The old visible sweeps did not cover this top-level action; this wave formalized it directly. | Prevented leaving a top-level action unclassified. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### New top-level action candidate sweep

From `top_level_actions_2026-03-14.json`:

- `system_health_check_action`: `0.000408s`
- `about_dialog_action`: `0.000003s`

Engineering meaning:

- after visible/dialog sweeps were closed, `System Health Check` was the next
  meaningful top-level action candidate;
- `About HDLE Premium` remained the lower baseline and did not justify its own
  wave first.

### Trigger-path timings

From `system_health_check_action_probe.json`:

- trigger path: `0.000408s`
- immediate status messages:
  - `Running health check...`
- worker created: `true`
- worker started: `true`
- worker cleared immediately: `false`

Engineering meaning:

- the action stays background-first exactly as intended;
- immediate operator feedback is present;
- heavy health work is not on the trigger path.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- trigger path is effectively instantaneous;
- no synchronous health-summary work is performed before returning;
- the remaining heavy work is background completion, not first usable state;
- no UX evidence justifies a repair branch for the trigger path.

## Reopen gate

Keep the `System Health Check` trigger-path branch closed.

Reopen only if a new evidence gate confirms one of:

- synchronous health-summary computation moves back onto the action trigger path;
- worker creation/start begins doing heavy preflight work before returning;
- repeated action trigger starts blocking the UI materially.

Do not reopen this as a generic health-service latency branch without separate
evidence.

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
- `VerificationPanel` branch
- `UserDictionariesView` branch
- `DatabaseSwitchDialog` branch
- MT `ProviderSettingsDialog` branch
- `ResourcesManagerDialog` branch
- `ImportWizard` branch
- generic first-run branch
- `AudioProviderSettingsDialog` branch
- `SentenceNiqqudBootstrapDialog` branch
- `CommandPaletteDialog` branch
- `PronunciationBootstrapDialog` branch
- `TranslateTextDialog` branch
- `ReferenceSetupWizard` branch
- `HelpCenterDialog` branch
