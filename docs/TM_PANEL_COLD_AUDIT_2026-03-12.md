# TM Panel Cold Audit (2026-03-12)

## Why this document exists

This is the seventh task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Translation Management panel first page / exact count / first-usable-state cold path

This wave does **not**:

- ship a runtime patch;
- reopen closed startup, picker, governance, telemetry, Dictionary, Terms, or Concordance branches;
- widen into a broad TM search redesign;
- open heavy validation.

## Historical context

Historical TM panel performance context already existed in:

- `docs/PERF_SCALE_AUDIT_HEWIKI_2026-03-07.md`
- `docs/TM_PANEL_UX_OVERHAUL_COMPLETE.md`

That history already recorded two important facts:

- TM panel operates on a very large `tm_entry` surface at hewiki scale;
- migration `030` introduced `idx_tm_entry_proj_updated_at(project_id, updated_at DESC)`
  to remove the old default sort bottleneck.

This wave checks the current approved target to determine whether the present
TM panel is still a blocker after that sort-layer repair.

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `T1` | TM panel default first page, project scope | approved hewiki test DB | This is the first visible TM state when the panel opens from a project | Completed |
| `T2` | TM panel default exact count, project scope | approved hewiki test DB | Confirms whether first usable state is being held by exact count work | Completed |
| `T3` | TM panel representative search page and exact count | approved hewiki test DB | Confirms whether filtered TM search is a separate residual tail or the same gating layer | Completed |
| `T4` | TM worker first-paint gating contract | code + regressions | Confirms whether rows are rendered only after exact count completes | Completed |
| `T5` | Current query-plan status after migration `030` | approved hewiki test DB + code | Confirms whether the old sort-path blocker is still active or already closed | Completed |

## Entry points and evidence

Code entry points:

- `app/services/translation_admin_service.py`
- `app/ui/translation_management_panel.py`
- `app/ui/workers.py`
- `app/infra/migrations/030_perf_sort_indexes.sql`

Regression entry points:

- `tests/test_tm_panel_ux.py`
- `tests/test_tm_results_label_context.py`
- `tests/test_tm_panel_translate_query_builder.py`

Evidence artifacts:

- `build/logs/cold_audit/tm_panel/tm_panel_probe.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repeated.json`
- `build/logs/cold_audit/tm_panel/tm_panel_query_plan.json`
- `build/logs/cold_audit/tm_panel/tm_panel_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- strict read-only access only

## Current UI/workflow contract

Current TM panel behavior:

- project-scoped panel defaults to `project_ids=[project_id]`;
- default kind filter is `lemma`, `term_cluster`, `ngram`;
- default sort is `updated_at DESC`;
- `TMSearchWorker.run()` executes `search_tm_entries()` first;
- the same worker then executes `count_tm_entries()`;
- `results_ready(entries, total_count)` is emitted only after both complete.

Engineering meaning:

- first visible TM rows are currently gated by exact count completion;
- even if the page query itself is fast, the user still waits for the full
  search-plus-count wall time before the panel becomes usable;
- this makes exact count part of the first-paint critical path, not a secondary
  tail.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Default first page, default exact count, representative search, worker gating contract, and query-plan status were explicitly separated. | Completed |
| `2. Cold vs warm measurement` | Three strict read-only runs show the rows-gate staying around `7.594s` to `10.628s`; this is not a negligible warm-only tail. | Completed |
| `3. Step-by-step cold breakdown` | The dominant cost is exact count, not page fetch. Default page stays near `0.050s` to `0.137s` while default exact count stays near `7.545s` to `10.490s`. | Completed |
| `4. SQL-level timing / query audit` | The page path uses the expected `idx_tm_entry_proj_updated_at` index. The count path still spends seconds scanning the project/kind slice for exact totals. | Completed |
| `5. Service/process timing` | Service overhead outside the SQL path is minor. The blocker is the count-backed worker contract, not service initialization. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer. The approved DB stayed unchanged under strict read-only access. | Completed with bounded scope |
| `7. UI first-render / first-usable-state audit` | First usable state is blocked because rows are not emitted until exact count finishes. | Completed |
| `8. Degraded / fallback mode audit` | No hidden fallback path exists here. The live path is structurally count-gated by design. | Completed |
| `9. Dataset-tier analysis` | The decision evidence came from the approved hewiki test DB with `2,071,849` visible TM rows in current project scope. | Completed |
| `10. Repeatability protocol` | The commands and artifacts below are sufficient to repeat the same bounded gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `T1` through `T5` were fixed before interpretation. | Prevented vague "TM panel is slow" claims. |
| `B. Bounded live probes` | Strict read-only probes captured page, count, combined gate, and query-plan evidence on the approved target. | This is current branch evidence, not historical replay. |
| `C. SQL top offenders log` | Exact count is the active offender; default page query is already healthy after migration `030`. | The next fix should not target the sort layer again. |
| `D. UI responsiveness probes` | UI wiring is simple but not staged. Rows still wait for count. | The blocker is a first-paint gating contract, not a rendering bug. |
| `E. Service initialization audit` | No meaningful init bottleneck appeared. | Do not misclassify this as service startup overhead. |
| `F. Drift / fallback path audit` | No contract drift was required to explain the slowdown. The measured live path is enough. | A bounded repair branch is justified without widening scope. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It crosses the evidence gate for a bounded next repair, but does not implement it. |

## Current findings

### Approved-target timings

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- access mode: strict read-only
- current visible TM rows in default project scope: `2,071,849`

Current repeated results:

- default page runs: `0.137s`, `0.059s`, `0.050s`
- default exact count runs: `10.490s`, `8.409s`, `7.545s`
- default rows-gate runs: `10.628s`, `8.468s`, `7.594s`

Representative search results on the same scope:

- search sample returned `2` rows / `2` exact matches
- search page runs: `0.706s`, `0.814s`, `0.717s`
- search exact count runs: `8.502s`, `8.591s`, `8.733s`
- search rows-gate runs: `9.208s`, `9.405s`, `9.450s`

Interpretation:

- default TM page fetch itself is already healthy;
- exact count is the dominant cold cost and the direct first-paint blocker;
- filtered search does not escape the same layer: even a tiny result set still
  pays seconds-scale exact count cost.

### Query-plan evidence

Current query-plan evidence from `tm_panel_query_plan.json`:

- default page:
  - `SEARCH tm_entry USING INDEX idx_tm_entry_proj_updated_at (project_id=?)`
- default count:
  - `SEARCH tm_entry USING INDEX sqlite_autoindex_tm_entry_1 (project_id=? AND kind=?)`
- representative search page:
  - `SEARCH tm_entry USING INDEX idx_tm_entry_proj_updated_at (project_id=?)`
- representative search count:
  - `SEARCH tm_entry USING INDEX sqlite_autoindex_tm_entry_1 (project_id=? AND kind=?)`

Engineering meaning:

- migration `030` did its job for the default sort path;
- the current blocker is not another `ORDER BY updated_at DESC` failure;
- the exact count path still scans a very large project/kind slice and applies
  the remaining filters before returning the final total.

### First-usable-state contract

The current first-usable-state contract is not staged:

- `TMSearchWorker` emits only one terminal result signal;
- `TranslationManagementPanel.on_search_results()` receives rows and total count
  together;
- rows are therefore not visible until exact count is finished.

Regression evidence for the current subsystem still exists in:

- `tests/test_tm_panel_ux.py`
- `tests/test_tm_results_label_context.py`
- `tests/test_tm_panel_translate_query_builder.py`

Engineering meaning:

- the panel does not need a broad search redesign to improve first paint;
- it needs a bounded staged-load contract similar to the already-healthy
  Dictionary flow.

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- this is a user-visible core data-management surface;
- approved-target page fetch is already fast, so the current blocker is sharply
  localized rather than spread across the whole subsystem;
- exact count alone keeps first usable state in the `~7.6s` to `10.6s` range;
- search path evidence points to the same count-gated contract, not to a
  separate first fix;
- the branch can stay bounded to staged first paint / deferred exact count
  repair without widening into a broad TM refactor.

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- bounded TM panel staged first paint / deferred exact count repair

Bounded patch scope implied by the evidence:

- emit the first page rows before exact count completes;
- keep the exact count as a later stage or deferred update;
- preserve current filters, sorting, cancellation, and project-scope behavior;
- do not widen into search semantics redesign, FTS work, or unrelated TM write
  workflows.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail follow-up branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- heavy validation branches

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\tm_panel | Out-Null
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_tm_panel_ux.py tests\test_tm_results_label_context.py tests\test_tm_panel_translate_query_builder.py -q
```

This wave's approved-target live probes were run through bounded inline
read-only sessions against:

- `app/services/translation_admin_service.py`
- `app/infra/db.py`

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/tm_panel/tm_panel_probe.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repeated.json`
- `build/logs/cold_audit/tm_panel/tm_panel_query_plan.json`
- `build/logs/cold_audit/tm_panel/tm_panel_cold_audit_summary.json`
