# Term Cards Cold Audit (2026-03-13)

## Why this document exists

This is the twelfth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- standalone `TermCardView(project_id=1)` cold open / first usable state

This wave does **not**:

- reopen the `ProjectView` branch that is already closed;
- change Term Cards semantics, aliases, stopwords, or audio workflow;
- open a repair branch without a separate evidence gate;
- open heavy validation.

## Scope

In scope:

- standalone `TermCardView(project_id=1)` cold open on the approved target
- review queue load path
- queue enrichment path
- blocker vs not-blocker classification

Out of scope:

- hidden-tab `ProjectView` open path
- user-curation write flows
- bulk audio flow
- Term Cards redesign or pagination redesign

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `TC1` | Standalone `TermCardView(project_id=1)` cold open | approved hewiki test DB | Measures the actual Term Cards activation path after `ProjectView` repair | Completed |
| `TC2` | Raw `term_cluster` queue query | approved hewiki test DB | Separates base SQL page cost from the rest of the view load | Completed |
| `TC3` | `TermCardService.list_review_queue()` | approved hewiki test DB | Measures DTO construction path | Completed |
| `TC4` | `resolve_cross_view_status()` enrichment | approved hewiki test DB | Measures cross-view overlay contribution | Completed |
| `TC5` | `count_review_queue()` | approved hewiki test DB | Confirms whether exact count is a meaningful contributor | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/term_card_view.py`
- `app/services/term_card_service.py`
- `app/services/user_dictionary_service.py`

Current smoke/regression entry points:

- `tests/test_project_view_deferred_term_cards.py`
- `tests/test_term_card_audio_context_menu.py`
- `tests/test_term_card_last_review_visuals.py`
- `tests/test_term_card_table_model.py`

Evidence artifacts:

- `build/logs/cold_audit/term_cards/term_cards_probe.json`
- `build/logs/cold_audit/term_cards/term_cards_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only

## Current UI/workflow contract

Current Term Cards cold-open path:

- `TermCardView.__init__()` still loads the review queue synchronously;
- the queue path still performs:
  - `TermCardService.list_review_queue()`
  - `_apply_study_overlays()`
  - queue model update and first-card display
- there is no staged rows-first / overlays-later contract today;
- queue count is not the gating layer.

Engineering meaning:

- the remaining activation cost is no longer hidden inside `ProjectView`;
- it is now the visible standalone `Term Cards` activation path;
- the likely optimization target, if needed, is overlay staging rather than raw
  queue SQL.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Standalone `Term Cards` activation was separated from `ProjectView` open. | Completed |
| `2. Cold vs warm measurement` | Fresh read-only cold-open probe was captured after the `ProjectView` repair. | Completed |
| `3. Step-by-step cold breakdown` | Raw queue, full service, overlays, and count were measured separately. | Completed |
| `4. SQL-level timing / query audit` | Base queue query is indexed and cheap. | Completed |
| `5. Service/process timing` | DTO build plus overlay enrichment dominate the cold path. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained untouched under read-only access. | Completed |
| `7. UI first-render / first-usable-state audit` | The tab still waits for full queue + overlay preparation before becoming useful. | Completed |
| `8. Degraded / fallback mode audit` | No staged overlay/fallback contract exists today. | Completed |
| `9. Dataset-tier analysis` | Evidence came from the approved large project slice, not a toy dataset. | Completed |
| `10. Repeatability protocol` | The commands below reproduce the same bounded decision gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `TC1`-`TC5` were fixed before interpretation. | Prevented vague “Term Cards still feel slow” conclusions. |
| `B. Bounded live probes` | Strict read-only probe captured the actual standalone tab-open path. | Current evidence, not leftover `ProjectView` numbers. |
| `C. SQL top offenders log` | Raw queue SQL is `0.011s` and uses `idx_cluster_freq`. | Raw queue SQL is not the blocker. |
| `D. UI responsiveness probes` | Full `TermCardView` cold open is `1.043s`. | The tab still blocks first usable state for about a second. |
| `E. Service initialization audit` | `list_review_queue()` is `0.330s`; overlay enrichment is `0.606s`. | Overlay/status enrichment is the dominant layer. |
| `F. Drift / fallback path audit` | No staged rows-first overlay-later contract exists. | A future bounded UX patch would likely target staging, not SQL. |
| `G. Before/after evidence protocol` | This is an audit-only wave. | It opens no repair branch yet. |

## Current findings

### Approved-target timings

From `term_cards_cold_audit_summary.json`:

- standalone `TermCardView` cold open: `1.043s`
- raw `term_cluster` queue query: `0.011s`
- `TermCardService.list_review_queue()`: `0.330s`
- `resolve_cross_view_status()`: `0.606s`
- `resolve_pronunciation_overlay()`: `0.002s`
- `count_review_queue()`: `0.001s`
- queue rows after init: `760`

Engineering meaning:

- the exact count path is negligible;
- raw queue SQL is already cheap and indexed;
- the current dominant cold layer is cross-view overlay enrichment;
- a future patch, if justified, should target staged first usable state rather
  than query indexing.

### Query-plan evidence

Current queue plan:

- `SEARCH term_cluster USING INDEX idx_cluster_freq (project_id=?)`

Engineering meaning:

- no temp B-tree or large-sort residue is present on the base queue query;
- the problem is not the raw project-scoped queue lookup.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P1`
- `open patch now`: no

Decision logic:

- the path is visible and still synchronous, but the approved-target cost is
  now about `1.043s`, not a multi-second workspace-open blocker;
- the dominant layer is overlay enrichment, not structural DB failure or count
  gating;
- the `ProjectView` P0 blocker is already closed, and no evidence in this wave
  justifies reopening a new branch immediately;
- this remains a controlled residual tail unless Term Cards becomes a higher
  user-priority workflow with stronger UX evidence.

## Reopen gate

Keep the standalone `Term Cards` branch closed for now.

Reopen only if a new evidence gate confirms one of:

- term curation is a current high-frequency workflow and `~1s` activation is
  materially harming operator flow;
- a staged rows-first / overlays-later repair can be done narrowly without
  redesigning Term Cards semantics;
- another approved-target probe shows materially higher cold cost on the real
  workflow than this wave captured.

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

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem
  wave, unless new approved-target evidence promotes standalone `Term Cards`
  from `P1` residual tail to an active blocker

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\term_cards | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_project_view_deferred_term_cards.py tests\test_term_card_audio_context_menu.py tests\test_term_card_last_review_visuals.py tests\test_term_card_table_model.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.term_card_view import TermCardView; from app.services.term_card_service import TermCardService; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
wrappers only; no source/reference DB mutation was performed.
