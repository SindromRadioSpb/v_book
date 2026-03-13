# Verification Panel Cold Audit (2026-03-13)

## Why this document exists

This is the thirteenth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `VerificationPanel` cold open / first usable state

This wave does **not**:

- audit the long-running `P1VerificationWorker` execution path itself;
- reopen any already-closed blocker branch;
- change verification semantics, snapshot workflow, or worker behavior;
- open heavy validation.

## Scope

In scope:

- `VerificationPanel()` cold open on the approved target
- `load_db_path()` and `load_projects()` breakdown
- blocker vs not-blocker classification

Out of scope:

- running P1 Scenario 7
- snapshot-copy execution cost
- worker cancel/progress behavior

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `VP1` | Full `VerificationPanel()` cold open | approved hewiki test DB | Measures the actual panel-open path | Completed |
| `VP2` | `load_db_path()` breakdown | approved hewiki test DB | Confirms whether DB-path resolution contributes meaningfully | Completed |
| `VP3` | `load_projects()` breakdown | approved hewiki test DB | Confirms whether project listing is the gating layer | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/verification_panel.py`
- `app/ui/workers.py`

Current smoke/regression entry points:

- `tests/test_p1_workspace.py`
- `tests/test_workspace_app_window_contract.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/candidate_sweep_2026-03-13.json`
- `build/logs/cold_audit/verification_panel/verification_panel_probe.json`
- `build/logs/cold_audit/verification_panel/verification_panel_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only

## Current UI/workflow contract

Current `VerificationPanel` cold-open path:

- `VerificationPanel.__init__()` performs:
  - `init_ui()`
  - `load_db_path()`
  - `load_projects()`
- the worker is not started on open;
- panel open only prepares controls and project selection.

Engineering meaning:

- cold-open risk is limited to layout creation plus one simple project list
  query;
- the heavy verification path is a user-triggered worker path, not an open-time
  contract.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Panel open was separated from worker execution. | Completed |
| `2. Cold vs warm measurement` | Fresh read-only constructor probe used current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Init, DB-path load, and project-list load were timed separately. | Completed |
| `4. SQL-level timing / query audit` | Project listing is one small ordered `dict_project` read. | Completed |
| `5. Service/process timing` | Open cost is almost entirely UI construction, not service work. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained unchanged under read-only access. | Completed |
| `7. UI first-render / first-usable-state audit` | Panel becomes usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | No fallback path was needed for the cold-open contract. | Completed |
| `9. Dataset-tier analysis` | Evidence used the approved target and current project set. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `VP1`-`VP3` were fixed before interpretation. | Prevented mixing panel-open cost with verification-run cost. |
| `B. Bounded live probes` | Strict read-only open probe captured the real panel contract. | Current evidence, not historical intuition. |
| `C. SQL top offenders log` | `load_projects()` is `0.001s` for `4` projects. | Project query is not a bottleneck. |
| `D. UI responsiveness probes` | Full panel init is `0.244s`. | Cold open is already well below blocker range. |
| `E. Service initialization audit` | `load_db_path()` is effectively `0.000s`. | No hidden DB-service startup issue was found here. |
| `F. Drift / fallback path audit` | The worker is not auto-started on panel open. | Heavy work is already kept off the cold-open path. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Approved-target timings

From `verification_panel_cold_audit_summary.json`:

- full `VerificationPanel` cold open: `0.244s`
- `load_db_path()`: `0.000s`
- `load_projects()`: `0.001s`
- `dict_project` rows: `4`
- project combo items after init: `5`
  - includes `Global (All Projects)`

Engineering meaning:

- open cost is already small and mostly UI construction;
- DB-path and project-list loading are negligible;
- this surface is not a meaningful cold blocker.

### Selection context

The bounded candidate sweep for still-untriaged surfaces recorded:

- `verification_panel`: `0.219s`
- `user_dictionaries_view`: `0.198s`
- `database_switch_dialog`: `0.128s`
- `provider_settings_dialog`: `0.119s`
- `resources_manager_dialog`: `0.035s`
- `import_wizard`: `0.007s`

Engineering meaning:

- `VerificationPanel` was selected as the next wave because it was the largest
  remaining sweep candidate;
- even so, it still does not justify a runtime branch.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- `0.244s` cold open is already bounded;
- the worker does not auto-start on open, so the heavy verification path is not
  part of first usable state;
- project-list query cost is negligible on the approved target;
- no UX or operator-flow evidence justifies a repair branch.

## Reopen gate

Keep the `VerificationPanel` branch closed.

Reopen only if a new evidence gate confirms one of:

- panel open becomes materially slower on the real operator target;
- a hidden synchronous preflight step is added to the open path;
- verification worker startup is moved into automatic panel initialization.

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
- Documents view branch
- ProjectView branch
- standalone `Term Cards` branch

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\verification_panel | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_p1_workspace.py tests\test_workspace_app_window_contract.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.verification_panel import VerificationPanel; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
wrappers only; no source/reference DB mutation was performed.
