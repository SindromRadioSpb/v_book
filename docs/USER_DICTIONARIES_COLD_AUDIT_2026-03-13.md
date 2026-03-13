# User Dictionaries Cold Audit (2026-03-13)

## Why this document exists

This is the fourteenth task-specific use of the canonical cold-audit framework
in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- `UserDictionariesView` cold open / first usable state

This wave does **not**:

- open a runtime repair branch;
- widen into translation, audio, or review-mode workflows;
- reinterpret historical user-dictionary feature work as a current blocker;
- open heavy validation.

## Scope

In scope:

- `UserDictionariesView(project_id=1)` cold open on the approved target
- synchronous `load_dictionaries()` breakdown
- first `UserDictItemsPageWorker` page-load timing
- dataset-tier viability for the approved target

Out of scope:

- bulk add/remove workflows
- translate/audio generation workflows
- review-mode execution cost
- write-path semantics

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `UD1` | Full `UserDictionariesView(project_id=1)` cold open | approved hewiki test DB | Measures the actual visible panel-open contract | Completed |
| `UD2` | `list_dictionaries()` breakdown | approved hewiki test DB | Confirms whether constructor-time dictionary listing is meaningful | Completed |
| `UD3` | First async items page + total load | approved hewiki test DB | Confirms whether first usable state hides a large page/count tail | Completed |
| `UD4` | Project-scoped item query replay | approved hewiki test DB | Removes ambiguity between persisted scope state and project embedding | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/user_dictionaries_view.py`
- `app/ui/workers.py`
- `app/services/user_dictionary_service.py`

Current smoke/regression entry points:

- `tests/test_user_dictionaries_scope.py`
- `tests/test_user_dictionaries_review_mode.py`
- `tests/test_patch_h_anti_stale.py`

Evidence artifacts:

- `build/logs/cold_audit/candidate_sweep/candidate_sweep_2026-03-13.json`
- `build/logs/cold_audit/user_dictionaries/user_dictionaries_service_probe.json`
- `build/logs/cold_audit/user_dictionaries/user_dictionaries_ui_probe.json`
- `build/logs/cold_audit/user_dictionaries/user_dictionaries_scope_probe.json`
- `build/logs/cold_audit/user_dictionaries/user_dictionaries_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only

## Current UI/workflow contract

Current `UserDictionariesView` cold-open path:

- `UserDictionariesView.__init__()` performs:
  - `_init_ui()`
  - synchronous `load_dictionaries()`
- `load_dictionaries()` performs:
  - synchronous `UserDictionaryService.list_dictionaries()`
  - dictionary selection restore
  - async `load_items()`
- `load_items()` starts `UserDictItemsPageWorker`
- `UserDictItemsPageWorker` returns page rows and exact filtered total together
- `_update_study_summary()` runs only after the async page returns

Engineering meaning:

- constructor-time risk is limited to dictionary listing and selection restore;
- first page and total are already off the UI thread;
- there is no evidence of a current large-scale dataset on the approved target.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Panel open was separated from review/audio/translate workflows. | Completed |
| `2. Cold vs warm measurement` | Fresh read-only constructor and service probes used current repo code. | Completed |
| `3. Step-by-step cold breakdown` | Constructor, dictionary list, first page, and project-scope replay were timed separately. | Completed |
| `4. SQL-level timing / query audit` | Dictionary list and first page stayed small on the approved target. | Completed |
| `5. Service/process timing` | `query_items()` is bounded because the target dataset is tiny. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained unchanged under read-only access. | Completed |
| `7. UI first-render / first-usable-state audit` | UI becomes usable quickly and reaches first page shortly after open. | Completed |
| `8. Degraded / fallback mode audit` | No fallback path was needed for the cold-open contract. | Completed |
| `9. Dataset-tier analysis` | Approved target is low-viability for user-dictionary cold-scale claims. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the same bounded result. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `UD1`-`UD4` were fixed before interpretation. | Prevented mixing open cost with bulk/review workflows. |
| `B. Bounded live probes` | Strict read-only service and offscreen UI probes captured the real contract. | Current evidence, not guesswork. |
| `C. SQL top offenders log` | `list_dictionaries()` is `0.043s`; `query_items()` is `0.053s`. | No SQL blocker was found here. |
| `D. UI responsiveness probes` | Full view init is `0.058s`; first page is ready at `0.164s`. | Cold open is already bounded. |
| `E. Service initialization audit` | Summary and page totals remain small because only `18` items exist. | No hidden service startup tail is exposed. |
| `F. Drift / fallback path audit` | Persisted scope was observed as `all`, then replayed with explicit `origin_project_id=1`. | Removed ambiguity without reopening scope semantics work. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | No repair branch is opened. |

## Current findings

### Approved-target dataset viability

From `user_dictionaries_service_probe.json`:

- dictionaries on target: `1`
- total `user_dictionary_item` rows: `18`
- selected dictionary item count: `18`

Engineering meaning:

- the approved target does not provide a scale-viable dataset for a major
  `UserDictionariesView` cold-path bottleneck;
- any future performance claim for this subsystem requires a new evidence gate
  on a materially larger user-dictionary dataset.

### Approved-target timings

From `user_dictionaries_ui_probe.json` and `user_dictionaries_scope_probe.json`:

- full `UserDictionariesView(project_id=1)` init: `0.058s`
- first page ready: `0.164s`
- first page rows: `18`
- first page total: `18`
- `list_dictionaries()`: `0.043s`
- `query_items()` with current filters: `0.053s`
- `get_dictionary_review_summary()`: `0.002s`
- explicit project-scope `query_items()`: `0.053s`

Engineering meaning:

- cold open is already bounded;
- async page loading does not hide a heavy first-page tail on the approved
  target;
- the observed persisted scope `all` does not change the conclusion because the
  explicit project-scoped replay is identical on this dataset.

### Selection context

The bounded candidate sweep for still-untriaged surfaces recorded:

- `verification_panel`: `0.219s`
- `user_dictionaries_view`: `0.198s`
- `database_switch_dialog`: `0.128s`
- `provider_settings_dialog`: `0.119s`
- `resources_manager_dialog`: `0.035s`
- `import_wizard`: `0.007s`

Engineering meaning:

- `UserDictionariesView` was the next visible candidate after
  `VerificationPanel`;
- the dedicated audit then confirmed that the view is still not a blocker.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- full cold open is `0.058s`, with first page ready at `0.164s`;
- first page and exact total already run off the UI thread;
- the approved target dataset is tiny (`1` dictionary, `18` items total);
- no UX or operator-flow evidence justifies a repair branch.

## Reopen gate

Keep the `UserDictionariesView` branch closed.

Reopen only if a new evidence gate confirms one of:

- materially larger user-dictionary datasets produce a real first-page tail;
- a hidden synchronous preload step is added back to constructor/open path;
- user-dictionary paging/count work becomes a user-visible blocker in a real
  operator workflow.

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

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes a new blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\user_dictionaries | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_user_dictionaries_scope.py tests\test_user_dictionaries_review_mode.py tests\test_patch_h_anti_stale.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.user_dictionaries_view import UserDictionariesView; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
wrappers only; no source/reference DB mutation was performed.
