# Audio Add-All Dialog Cold Audit (2026-03-13)

## Why this document exists

This is the ninth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Audio Player "Add All to Queue" dialog cold open / first usable state

This wave does **not**:

- ship a runtime patch;
- reopen Coverage residual-tail work;
- redesign Audio queue semantics;
- open heavy validation;
- widen into playlist/history refresh work.

## Scope

In scope:

- `AddAllToQueueDialog` cold open on the approved target
- project load, default project selection, default `sentence` mode
- processed-document list loading and UI materialization
- sentence estimate count on dialog open
- blocker vs not-blocker classification

Out of scope:

- Audio playback engine runtime
- queue/playlists/history mutation paths
- audio asset generation or pronunciation health
- export/import/operator tooling

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `A1` | Audio panel base dock open | code + approved target metadata | Separates the main panel from the Add-All dialog | Completed |
| `A2` | Add-All dialog cold open on large project | approved hewiki test DB | This is the real user-visible gate before large sentence-to-queue operations | Completed |
| `A3` | Processed-document list load | approved hewiki test DB | Determines whether document enumeration is part of the blocker | Completed |
| `A4` | Sentence estimate count | approved hewiki test DB | Determines whether exact count is the dominant SQL layer | Completed |
| `A5` | UI materialization cost | offscreen read-only dialog probe | Separates SQL time from list widget population cost | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/widgets/audio_player_panel.py`
- `app/services/project_service.py`

Current smoke/regression entry points:

- `tests/test_audio_player_panel_dock_state.py`
- `tests/test_audio_queue_populate_worker.py`
- `tests/test_audio_player_nondestructive.py`

Evidence artifacts:

- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_ui_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_query_plan.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only
- DB size: `26,148,278,272` bytes

Approved-target project volumes used in this wave:

- `dict_project`: `4` rows
- `project_id=1` processed documents: `387,639`
- `project_id=1` sentence estimate for Add-All dialog: `13,387,588`

## Current UI/workflow contract

Current Audio Player dock behavior:

- `AudioPlayerPanel.__init__()` refreshes queue, playlists, and history;
- on the approved target those surfaces are not the blocker:
  - queue rows: `0`
  - history rows: `0`
  - playlists: `1`

Current Add-All dialog behavior:

- `AddAllToQueueDialog.__init__()` calls `_load_projects()` immediately;
- `_load_projects()` populates the project combo and immediately calls
  `_on_project_changed(self.project_combo.currentIndex())`;
- the default kind is `sentence`;
- `_on_project_changed()` therefore calls `_load_documents(project_id)` for the
  first project;
- `_load_documents()` loads **all** processed documents for that project and
  appends one `QListWidgetItem` per document;
- `_update_estimate()` then runs an exact sentence count for the same project
  slice;
- there is no staged first usable state in this dialog today.

Engineering meaning:

- the blocker is not the base Audio Player dock;
- the blocker is the Add-All dialog cold open path for the large default
  project selection;
- the current contract performs both a large document list materialization and
  an exact sentence estimate before the dialog becomes useful.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Audio dock open, Add-All dialog open, processed-doc loading, and sentence estimate were separated before interpretation. | Completed |
| `2. Cold vs warm measurement` | The approved-target dialog open path was measured directly instead of extrapolated from smaller local data. | Completed |
| `3. Step-by-step cold breakdown` | Project load, document list query, sentence estimate query, and full UI init were isolated. | Completed |
| `4. SQL-level timing / query audit` | Document-list and sentence-estimate plans were captured independently. | Completed |
| `5. Service/process timing` | There is no separate service boot bottleneck; the problem sits in synchronous data fetch plus UI population. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer here. The approved DB remained untouched under strict read-only probes. | Completed with bounded scope |
| `7. UI first-render / first-usable-state audit` | Dialog init itself is blocked behind document list population and exact estimate calculation. | Completed |
| `8. Degraded / fallback mode audit` | No fallback path currently skips or defers exact count for first usable state. | Completed |
| `9. Dataset-tier analysis` | The blocker exists only on the approved large project slice; small projects on the same DB do not reproduce it. | Completed |
| `10. Repeatability protocol` | Commands and artifacts below are sufficient to reproduce the same bounded decision gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `A1`-`A5` were fixed before measurement. | Prevented vague "audio is slow" claims. |
| `B. Bounded live probes` | Strict read-only probes captured project volumes, doc-list query time, exact sentence estimate time, and full dialog init time. | This is current evidence, not guesswork from code shape alone. |
| `C. SQL top offenders log` | Exact sentence estimate is the dominant SQL layer at `18.499s`; document-list SQL alone is `0.818s`. | SQL is part of the blocker, but not the whole blocker. |
| `D. UI responsiveness probes` | Offscreen dialog init still takes `48.989s` because `387,639` rows are materialized into `QListWidget`. | UI materialization and synchronous contract are also blocker layers. |
| `E. Service initialization audit` | Project load is only `0.019s`; the blocker is not generic startup/service overhead. | Do not misclassify this as panel bootstrap overhead. |
| `F. Drift / fallback path audit` | No staged or approximate count path exists today for Add-All dialog open. | The next patch can stay bounded to staged first usable state plus deferred estimate. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It crosses the evidence gate for a bounded repair but does not implement it. |

## Current findings

### Approved-target timings

From `audio_add_all_dialog_probe.json`:

- project list load: `0.019s`
- `project_id=1` processed document query: `0.818s`
- `project_id=1` processed documents returned: `387,639`
- `project_id=1` exact sentence estimate: `18.499s`
- exact sentence estimate result: `13,387,588`

Small-project comparison from the same probe:

- `project_id=6` processed document query: `0.000s`
- `project_id=6` processed documents returned: `1`

From `audio_add_all_dialog_ui_probe.json`:

- offscreen dialog init: `48.989s`
- default kind: `sentence`
- default project id: `1`
- doc list count after init: `387,639`
- estimate label after init: `~13,387,588 sentences from all documents`

Engineering meaning:

- the blocker is real and user-visible on the approved target;
- project loading is negligible;
- the exact sentence estimate is already seconds-scale by itself;
- the full dialog open time is much worse than raw SQL time, proving that UI
  row materialization is also part of the cold blocker.

### Query-plan evidence

Document-list plan from `audio_add_all_dialog_query_plan.json`:

- `SEARCH sc USING COVERING INDEX sqlite_autoindex_source_corpus_1 (project_id=?)`
- `SEARCH sd USING INDEX idx_doc_corpus_status (corpus_id=? AND status=?)`
- `USE TEMP B-TREE FOR ORDER BY`

Sentence-estimate plan from the same artifact:

- `SEARCH sc USING COVERING INDEX sqlite_autoindex_source_corpus_1 (project_id=?)`
- `SEARCH sd USING COVERING INDEX idx_doc_corpus_sentence_count_sum (corpus_id=?)`
- `SEARCH ds USING COVERING INDEX idx_sentence_doc (doc_id=?)`

Engineering meaning:

- document-list SQL is not free, but it is not the dominant layer by itself;
- the exact sentence estimate still performs a large project-scoped scan across
  the sentence table;
- the current blocker is a combination of:
  - exact sentence estimate cost;
  - large list widget materialization cost;
  - a one-shot init contract that waits for both before the dialog is useful.

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- this is a user-visible dialog directly attached to the Audio Player workflow;
- approved-target evidence shows a real current blocker, not a hypothetical
  tail;
- the blocker is tightly localized:
  - project load is fast;
  - dock surfaces are not the blocker;
  - the dialog open contract is the blocker;
- the next patch can stay bounded to:
  - staged first usable state;
  - deferred or reduced initial estimate work;
  - narrowing or postponing large document list materialization.

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- Audio Add-All dialog staged first usable state / deferred estimate repair

Bounded patch scope implied by the evidence:

- decouple dialog usability from exact sentence estimate;
- avoid eagerly materializing the full `387,639`-row document list on cold open;
- preserve add-to-queue semantics unless a separate semantics gate is opened;
- keep queue/playlists/history runtime behavior out of scope.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- Coverage lemma-count residual-tail branch
- heavy validation branches

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\audio_add_all_dialog | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_audio_player_panel_dock_state.py tests\test_audio_queue_populate_worker.py tests\test_audio_player_nondestructive.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.widgets.audio_player_panel import AudioPlayerPanel, AddAllToQueueDialog; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
probes and written to:

- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_ui_probe.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_query_plan.json`
- `build/logs/cold_audit/audio_add_all_dialog/audio_add_all_dialog_cold_audit_summary.json`
