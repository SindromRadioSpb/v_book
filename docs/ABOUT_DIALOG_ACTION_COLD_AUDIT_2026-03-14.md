# About Dialog Action Cold Audit (2026-03-14)

## Why this document exists

This is the twenty-eighth task-specific use of the canonical cold-audit
framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `AppWindow.open_about_dialog()` trigger path / first usable state

This wave does **not**:

- open a runtime repair branch;
- reinterpret full app startup or packaging provenance generation as action
  trigger cost;
- audit message-box rendering internals;
- audit installer/build reproducibility itself;
- open heavy validation.

## Scope

In scope:

- top-level `About HDLE Premium` action trigger path from `AppWindow`
- build-metadata payload construction via `get_build_meta()`
- immediate modal payload shape
- blocker vs not-blocker classification

Out of scope:

- broader build pipeline behavior
- installer/versioning correctness beyond the runtime payload shape
- QMessageBox platform rendering cost
- any unrelated app-window open path

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `ADA1` | Top-level action candidate comparison | prior top-level action sweep evidence | Confirms why this is the next narrow wave after system health action | Completed |
| `ADA2` | `open_about_dialog()` payload build | actual `AppWindow` action contract via `get_build_meta()` | Measures immediate user-visible action latency | Completed |
| `ADA3` | Build-meta payload audit | `app.build_meta.get_build_meta()` | Confirms exact runtime data surfaced on open | Completed |
| `ADA4` | Modal content-shape audit | current repo code | Confirms bounded detail-line contract | Completed |
| `ADA5` | Lower-baseline confirmation | same top-level action sweep | Confirms this action is the smallest remaining top-level surface | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/app_window.py`
- `app/build_meta.py`

Current smoke/regression entry points:

- `tests/test_build_meta.py`
- `tests/test_workspace_app_window_contract.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/top_level_actions_2026-03-14.json`
- `build/logs/cold_audit/about_dialog_action/about_dialog_action_probe.json`
- `build/logs/cold_audit/about_dialog_action/about_dialog_action_cold_audit_summary.json`

## Current UI/workflow contract

Current `AppWindow.open_about_dialog()` path:

- imports `QMessageBox`
- imports `get_build_meta()`
- reads normalized build metadata
- formats six detail lines:
  - app name
  - blank spacer
  - version
  - commit
  - dirty flag
  - build time
- shows one modal information box

Engineering meaning:

- the action is a pure in-process metadata-formatting path;
- no DB, worker, or network dependency exists on the trigger path;
- latency is bounded by local string formatting only.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | About action was separated from broader app startup/build concerns. | Completed |
| `2. Cold vs warm measurement` | Dedicated bounded probe used current runtime build-meta contract. | Completed |
| `3. Step-by-step cold breakdown` | Metadata load and detail-line construction were isolated together. | Completed |
| `4. SQL-level timing / query audit` | Trigger path exposes no SQL layer. | Completed |
| `5. Service/process timing` | No service/worker startup exists on the action path. | Completed |
| `6. Filesystem / OS / DB-open audit` | Trigger path depends only on already-importable runtime build metadata. | Completed |
| `7. UI first-render / first-usable-state audit` | Action payload is ready immediately. | Completed |
| `8. Degraded / fallback mode audit` | Unknown commit/build time degrade to normalized fallback strings, not blocked open. | Completed |
| `9. Dataset-tier analysis` | Trigger-path latency is independent of corpus scale. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `ADA1`-`ADA5` were fixed before interpretation. | Prevented mixing about-action cost with unrelated startup/build work. |
| `B. Bounded live probes` | Dedicated about-action probe captured the real payload contract. | Current evidence, not assumption. |
| `C. SQL top offenders log` | No SQL exists on the action path. | This is not a DB-latency branch. |
| `D. UI responsiveness probes` | Trigger path is `0.000005s`. | User-visible action latency is effectively instant. |
| `E. Service initialization audit` | `get_build_meta()` payload formatting is the only action-stage work. | Still far below blocker territory. |
| `F. Drift / fallback path audit` | Fallback build metadata (`unknown`, `dirty=0`) is normalized and explicit. | Prevented hidden dependency assumptions. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Top-level action comparison context

From `top_level_actions_2026-03-14.json`:

- `system_health_check_action`: `0.000408s`
- `about_dialog_action`: `0.000003s`

Engineering meaning:

- after the system-health trigger wave, `About HDLE Premium` remained the lower
  top-level action baseline;
- it still warranted formal closure because it is user-visible and lives on the
  live `AppWindow` contract;
- the dedicated probe confirmed it is not a blocker.

### Dedicated trigger-path timings

From `about_dialog_action_probe.json`:

- trigger path: `0.000005s`
- detail lines: `6`
- title:
  - `About HDLE Premium`
- current runtime payload:
  - `version = 1.0.0`
  - `commit = unknown`
  - `dirty = 0`
  - `built_at_utc = unknown`

Engineering meaning:

- the action remains effectively instantaneous;
- runtime build metadata is already normalized for traceability;
- no cold-open/performance branch is justified here.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- trigger path is effectively instantaneous;
- no heavy work is performed before the modal is shown;
- there is no DB, worker, or network dependency on the action path;
- no UX evidence justifies a repair branch.

## Reopen gate

Keep the `About HDLE Premium` trigger-path branch closed.

Reopen only if a new evidence gate confirms one of:

- build metadata lookup becomes materially slower on real targets;
- remote or filesystem-heavy provenance discovery is moved into the trigger path;
- modal content generation grows into a measurable user-visible delay.

Do not reopen this as a generic build/release correctness branch without
separate evidence.

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
- `System Health Check` trigger-path branch
