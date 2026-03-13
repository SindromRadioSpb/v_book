# Project View Cold Audit (2026-03-13)

## Why this document exists

This is the eleventh task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Project workspace cold open / first usable state

This wave does **not**:

- ship a runtime patch;
- reopen Documents, Audio, Coverage, TM, Sentences, picker, Concordance, or
  startup branches;
- redesign hidden-tab behavior broadly without a new evidence gate;
- open heavy validation.

## Scope

In scope:

- `ProjectView(project_id=1)` cold open on the approved target
- sync constructor work before the project workspace becomes usable
- eager child-tab construction cost
- hidden-tab blocker localization
- blocker vs not-blocker classification

Out of scope:

- post-open async steady-state behavior inside every child tab
- Documents, Sentences, Dictionary, Terms, or User Dictionaries query redesign
- Term Cards semantics or study workflow redesign
- workspace shell / app window navigation redesign

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `PV1` | Full `ProjectView(project_id=1)` cold open | approved hewiki test DB | Measures the real open-project workflow | Completed |
| `PV2` | `ProjectView` cold open with all child tabs stubbed | approved hewiki test DB | Establishes shell-only baseline | Completed |
| `PV3` | `ProjectView` cold open with only `DocumentsView` real | approved hewiki test DB | Confirms whether the visible default tab is the current blocker | Completed |
| `PV4` | `ProjectView` cold open with only `UserDictionariesView` real | approved hewiki test DB | Eliminates another eager child candidate | Completed |
| `PV5` | `ProjectView` cold open with only `TermCardView` real | approved hewiki test DB | Localizes hidden-tab open cost | Completed |
| `PV6` | Standalone `TermCardView(project_id=1)` cold open | approved hewiki test DB | Verifies the dominant hidden child in isolation | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/project_view.py`
- `app/ui/term_card_view.py`
- `app/ui/documents_view.py`
- `app/ui/user_dictionaries_view.py`

Current smoke/regression entry points:

- `tests/test_workspace_app_window_contract.py`
- `tests/test_p1_workspace.py`
- `tests/test_p1_layout_persistence.py`

Evidence artifacts:

- `build/logs/cold_audit/project_view/project_view_probe.json`
- `build/logs/cold_audit/project_view/project_view_all_stub.json`
- `build/logs/cold_audit/project_view/project_view_termcard_only.json`
- `build/logs/cold_audit/project_view/term_card_view_probe.json`
- `build/logs/cold_audit/project_view/project_view_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only

## Current UI/workflow contract

Current project-open path:

- `ProjectView.__init__()` creates the entire tab stack synchronously;
- the default visible tab is `Documents`;
- however `ProjectView.init_ui()` eagerly instantiates all child tabs:
  - `DocumentsView`
  - `DictionaryView`
  - `TermsView`
  - `ConcordanceView`
  - `TermCardView`
  - `UserDictionariesView`
  - `SentencesView`
  - `ExportView`
- `TermCardView.__init__()` immediately calls `load_review_queue()`;
- that queue load runs synchronously before `ProjectView` open finishes, even
  though the `Term Cards` tab is hidden on entry.

Engineering meaning:

- the current blocker is not in the visible default tab;
- a hidden eager child tab is consuming almost the entire project-open budget;
- this is a structural first-usable-state defect, not just a slow secondary tab.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Project dashboard, Documents view, and project workspace open were kept separate. | Completed |
| `2. Cold vs warm measurement` | Fresh-process offscreen constructor probes were used for the sync open path. | Completed |
| `3. Step-by-step cold breakdown` | Full open, shell-only baseline, and child-localization probes were separated. | Completed |
| `4. SQL-level timing / query audit` | SQL was bounded to the `TermCardView` review queue load, not the visible Documents tab. | Completed with bounded scope |
| `5. Service/process timing` | The open cost is constructor wiring plus eager child creation, not generic service init. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained untouched under strict read-only probes. | Completed |
| `7. UI first-render / first-usable-state audit` | Hidden `TermCardView` work still blocks the visible `Documents` entry path. | Completed |
| `8. Degraded / fallback mode audit` | No lazy/deferred hidden-tab policy exists today. | Completed |
| `9. Dataset-tier analysis` | The blocker appears on the approved large project slice, not from the shell alone. | Completed |
| `10. Repeatability protocol` | The commands below reproduce the same bounded decision gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `PV1`-`PV6` were fixed before interpretation. | Prevented vague "project open feels slow" conclusions. |
| `B. Bounded live probes` | Strict read-only offscreen constructor probes captured the real open-project path. | Current evidence, not historical intuition. |
| `C. SQL top offenders log` | The dominant open-time layer is not Documents paging or User Dictionaries. | The blocker is hidden `TermCardView` eager loading. |
| `D. UI responsiveness probes` | Full `ProjectView` init is `1.627s`; all-stub shell is `0.071s`. | Most open cost is unnecessary hidden child work. |
| `E. Service initialization audit` | `DocumentsView`-only is `0.089s` and `UserDictionariesView`-only is `0.087s`. | The visible default tab is not the blocker. |
| `F. Drift / fallback path audit` | No deferred/lazy hidden-tab strategy exists today. | A bounded first-usable-state repair is justified. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It opens a bounded repair but does not implement it. |

## Current findings

### Approved-target timings

From `project_view_cold_audit_summary.json`:

- full `ProjectView` cold open: `1.627s`
- shell-only `ProjectView` with all tabs stubbed: `0.071s`
- `ProjectView` with only `DocumentsView` real: `0.089s`
- `ProjectView` with only `UserDictionariesView` real: `0.087s`
- `ProjectView` with only `TermCardView` real: `1.593s`
- standalone `TermCardView` cold open: `1.553s`
- standalone `TermCardView` queue rows on open: `760`

Engineering meaning:

- the visible `Documents` tab is no longer the open-project blocker;
- `UserDictionariesView` is also not a material contributor on this target;
- hidden `TermCardView` eager loading explains essentially the full
  project-open delay;
- the open-project workflow is currently paying for the wrong tab.

### Structural localization

The full open path resolves to:

- current tab after open: `Documents`
- total tab count: `8`

Yet the dominant measured contributor is:

- hidden `TermCardView.load_review_queue()` on constructor path

Engineering meaning:

- this is not a case where the default visible tab itself is slow;
- the fix can stay sharply bounded:
  - defer `TermCardView` queue load until activation, or
  - otherwise prevent hidden `TermCardView` init from blocking `ProjectView`
    return

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- opening a project workspace is a primary user workflow;
- `1.627s` of sync open-time work is now mostly hidden-tab cost that contributes
  nothing to the first visible `Documents` experience;
- the visible default tab path is already bounded at `0.089s` in the same
  shell contract;
- the blocker is sharply localized and has a bounded repair shape.

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- `ProjectView deferred hidden Term Cards load / first usable state repair`

Bounded patch scope implied by the evidence:

- stop hidden `TermCardView` queue load from blocking `ProjectView` open;
- keep current Documents / Dictionary / Terms / Sentences tab semantics intact;
- avoid broad tab-lazy-loading refactors unless new evidence requires them.

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
- heavy validation branches

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\project_view | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_workspace_app_window_contract.py tests\test_p1_workspace.py tests\test_p1_layout_persistence.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.project_view import ProjectView; from app.ui.term_card_view import TermCardView; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
wrappers only; no source/reference DB mutation was performed.
