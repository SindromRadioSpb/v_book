# Import Wizard Cold Audit (2026-03-13)

## Why this document exists

This is the eighteenth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `ImportWizard` cold open / first usable state

This wave does **not**:

- audit file parsing or import execution;
- reopen dictionary import worker behavior;
- open heavy validation.

## Scope

In scope:

- `ImportWizard()` cold open on the approved target via strict read-only DB shim
- `ProjectService.list_projects()` breakdown
- blocker vs not-blocker classification

Out of scope:

- `ImportWorker`
- file selection and validation flow
- CSV/XLSX parse cost
- conflict resolution or import persistence

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `IW1` | Full `ImportWizard()` cold open | approved hewiki test DB via read-only shim | Measures the actual visible wizard-open contract | Completed |
| `IW2` | `ProjectService.list_projects()` breakdown | approved hewiki test DB via read-only shim | Confirms whether project-combo load is the gating layer | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/import_wizard.py`
- `app/services/project_service.py`
- `app/ui/app_window.py`

Current smoke/regression entry points:

- `tests/test_p1_workspace.py`
- `tests/test_workspace_navigation_v2.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/candidate_sweep_2026-03-13.json`
- `build/logs/cold_audit/import_wizard/import_wizard_probe.json`
- `build/logs/cold_audit/import_wizard/import_wizard_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only shim used for project-list reads during the probe

## Current UI/workflow contract

Current `ImportWizard` cold-open path:

- `ImportWizard.__init__()` performs:
  - `init_ui()`
- `init_ui()` performs:
  - widget/layout construction
  - synchronous `load_projects()`
- `load_projects()` performs:
  - `ProjectService.list_projects(session)`
  - `project_combo` population
- heavy work is not started on open:
  - no file is parsed
  - no `ImportWorker` is started
  - no validation or write path runs until explicit user action

Engineering meaning:

- cold-open risk is limited to UI shell creation plus one small project-list
  query;
- import execution is already off the open path.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Wizard open was separated from actual import execution. | Completed |
| `2. Cold vs warm measurement` | Fresh offscreen probe used current repo code and a read-only DB shim. | Completed |
| `3. Step-by-step cold breakdown` | Full init and `list_projects()` were timed separately. | Completed |
| `4. SQL-level timing / query audit` | Open uses only one bounded project-list query. | Completed |
| `5. Service/process timing` | No heavy import service work occurs on open. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained unchanged under the read-only shim. | Completed |
| `7. UI first-render / first-usable-state audit` | Wizard becomes usable immediately on open. | Completed |
| `8. Degraded / fallback mode audit` | No fallback path was needed for the cold-open contract. | Completed |
| `9. Dataset-tier analysis` | Project-list size on target stayed small (`4`). | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `IW1`-`IW2` were fixed before interpretation. | Prevented mixing wizard open with actual import work. |
| `B. Bounded live probes` | Strict read-only offscreen probe captured the real open contract. | Current evidence, not guesswork. |
| `C. SQL top offenders log` | `ProjectService.list_projects()` is `0.043s`. | No query bottleneck exists here. |
| `D. UI responsiveness probes` | Full wizard init is `0.006s`. | Cold open is already comfortably bounded. |
| `E. Service initialization audit` | Open-time service work is only project combo population. | No hidden import-service tail exists on open. |
| `F. Drift / fallback path audit` | Run stays enabled and Cancel stays disabled before a worker starts. | Open contract matches current UX expectations. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Approved-target timings

From `import_wizard_probe.json`:

- `ProjectService.list_projects()`: `0.043s`
- project count: `4`
- full `ImportWizard` init: `0.006s`
- `project_combo` count after open: `4`

Engineering meaning:

- cold open is already bounded well below blocker range;
- synchronous project loading is small and deterministic;
- there is no current open-time blocker in this subsystem.

### Current open state

From `import_wizard_probe.json`:

- `Run Import` button enabled: `true`
- `Cancel` button enabled: `false`
- file placeholder:
  - `Select CSV or XLSX file...`
- approved DB unchanged:
  - `db_mtime_unchanged = true`

Engineering meaning:

- the wizard opens directly into a usable idle state;
- no background worker or partial state is needed to reach first usability.

### Selection context

The bounded candidate sweep for still-untriaged surfaces recorded:

- `import_wizard`: `0.007s`

Engineering meaning:

- `ImportWizard` was the last remaining visible candidate from the original
  bounded sweep;
- the dedicated probe confirmed it is not a blocker.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.006s`;
- project-list load is `0.043s` for only `4` projects;
- heavy import work is not part of the open contract;
- no UX or operator-flow evidence justifies a repair branch.

## Reopen gate

Keep the `ImportWizard` branch closed.

Reopen only if a new evidence gate confirms one of:

- file preview/parsing work is moved into constructor/open path;
- project-list loading becomes materially larger or more expensive on real
  operator targets;
- import validation/preflight starts automatically on open.

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
- `VerificationPanel` branch
- `UserDictionariesView` branch
- `DatabaseSwitchDialog` branch
- `ProviderSettingsDialog` branch
- `ResourcesManagerDialog` branch

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\import_wizard | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_p1_workspace.py tests\test_workspace_navigation_v2.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.import_wizard import ImportWizard; print('OK')"
```

Approved-target evidence for this wave was collected through a strict read-only
DB shim; no source/reference DB mutation was performed.
