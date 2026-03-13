# Coverage Panel Cold Audit (2026-03-13)

## Why this document exists

This is the eighth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Coverage panel first usable state on the approved target

This wave does **not**:

- ship a runtime patch;
- reopen TM residual-tail work;
- rewrite metrics semantics;
- reopen heavy validation.

## Scope

In scope:

- Coverage panel open / cold first usable state
- `CoverageWorker` execution order and emit contract
- lemma coverage exact-count path
- cluster coverage and untranslated-list timing as comparison layers
- approved-target blocker vs not-blocker classification

Out of scope:

- runtime code changes
- schema or index migration
- metrics redesign
- historical P2 docs cleanup beyond explicit status alignment

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `C1` | Coverage panel open on a large project | approved hewiki test DB | This is the real cold path when the panel opens for a large project | Completed |
| `C2` | `CoverageWorker` staged vs one-shot emit contract | code | Determines whether any partial first usable state exists today | Completed |
| `C3` | Lemma coverage exact-count path | approved hewiki test DB | Determines whether lemma coverage is the dominant blocker | Completed |
| `C4` | Cluster coverage and untranslated lists | approved hewiki test DB | Separates the dominant blocker from fast comparison layers | Completed |
| `C5` | Historical doc/test guardrail status | repo docs + current tests tree | Prevents relying on stale P2 query-count wording as a current performance guarantee | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/coverage_panel.py`
- `app/ui/workers.py`
- `app/services/coverage_service.py`

Current smoke/regression entry points:

- `tests/test_workspace_navigation_v2.py`
- `tests/test_p1_workspace.py`

Historical-only references:

- `docs/P2_PREMIUM_WORKFLOW.md`
- `docs/P2_TESTS.md`

Evidence artifacts:

- `build/logs/cold_audit/coverage_panel/coverage_panel_probe.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_query_plan.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only
- DB size: `26,148,278,272` bytes

Approved-target row volumes used in this wave:

- `lemma`: `2,071,947` rows for `project_id=1`
- `lemma_project_stat`: `2,071,947` rows for `project_id=1`
- `term_cluster`: `760` rows for `project_id=1`
- approved TM lemma entries: `1,468`
- approved TM term-cluster entries: `759`

## Current UI/workflow contract

Current Coverage flow on open:

- `CoveragePanel.__init__()` calls `load_coverage()` immediately;
- `CoverageWorker.run()` executes four steps in sequence:
  - `compute_lemma_coverage()`
  - `compute_termcluster_coverage()`
  - `list_untranslated_lemmas()`
  - `list_untranslated_termclusters()`
- `CoverageWorker` emits one terminal `results_ready(dict)` payload only after
  all four complete;
- `CoveragePanel.on_coverage_results()` updates metrics and tables only after
  that terminal payload;
- cancel currently uses `terminate()` in the panel.

Engineering meaning:

- there is no staged first usable state today;
- even fast cluster/list layers cannot render until the slowest lemma coverage
  step finishes;
- the blocker is therefore a combination of one slow exact-count layer and a
  one-shot UI contract that withholds the whole panel behind it.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Panel-open cold path, worker contract, lemma coverage count, and cluster/list comparison layers were separated before interpretation. | Completed |
| `2. Cold vs warm measurement` | The approved-target cold panel path was audited through direct worker/service-layer breakdown rather than local assumptions. | Completed |
| `3. Step-by-step cold breakdown` | Totals, cluster coverage, untranslated lists, and lemma coverage count were split into separate probes. | Completed |
| `4. SQL-level timing / query audit` | The dominant lemma coverage query-plan was captured; fast list/query comparison layers were timed separately. | Completed |
| `5. Service/process timing` | Service overhead outside the lemma exact-count layer is minor. The blocker is not generic service initialization. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer here. The approved DB remained unchanged under strict read-only access. | Completed with bounded scope |
| `7. UI first-render / first-usable-state audit` | Current UI is one-shot only; first usable state is blocked behind `compute_lemma_coverage()`. | Completed |
| `8. Degraded / fallback mode audit` | No degraded/warm fallback path currently provides earlier coverage rows or partial metrics. | Completed |
| `9. Dataset-tier analysis` | Decision evidence came from the approved hewiki-scale target, not from the smaller repo-local DB. | Completed |
| `10. Repeatability protocol` | Commands and artifacts below are sufficient to reproduce the same bounded decision gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `C1`-`C5` were fixed before measurement. | Prevented vague "coverage is slow" claims. |
| `B. Bounded live probes` | Strict read-only approved-target probes captured fast counts, cluster/list timings, timeout thresholds, and query plans. | This is current evidence, not historical replay. |
| `C. SQL top offenders log` | The active offender is the lemma coverage exact-count path, not the cluster path or top-100 untranslated lists. | The next fix must stay focused on lemma coverage and staged first paint. |
| `D. UI responsiveness probes` | The panel currently has no staged emit contract; everything waits for the slowest step. | First usable state is blocked structurally, not cosmetically. |
| `E. Service initialization audit` | No meaningful startup/init bottleneck appeared outside the query layer. | Do not misclassify this as service boot overhead. |
| `F. Drift / fallback path audit` | Historical P2 docs still describe query-count ceilings and legacy coverage tests that are absent in current `tests/`. | Historical docs are not current reference-scale cold guardrails. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It crosses the evidence gate for a bounded repair but does not implement it. |

## Current findings

### Approved-target timings

Fast comparison layers from `coverage_panel_probe.json`:

- `SELECT COUNT(*) FROM lemma WHERE project_id = 1`: `0.073s`
- term-cluster coverage: `0.068s`
- untranslated lemmas top 100: `0.185s`
- untranslated term clusters top 100: `0.068s`

Slow-layer observations from the same evidence pack:

- raw exact covered-lemma count did not complete within `120s`
- the full read-only service probe did not complete within `600s`
- the `600s` probe timed out immediately after `START lemma_metrics`

Engineering meaning:

- the panel is not broadly slow across every layer;
- the blocker is tightly localized to lemma coverage exact-count evaluation;
- because that step runs first and nothing renders before terminal
  `results_ready`, the whole panel stays blocked.

### Query-plan evidence

Current lemma coverage plan from `coverage_panel_query_plan.json`:

- `USE TEMP B-TREE FOR count(DISTINCT)`
- `SEARCH l USING COVERING INDEX idx_lemma_project_text (project_id=?)`
- `SEARCH t USING INDEX idx_tm_entry_lookup (project_id=? AND status=? AND kind=?) LEFT-JOIN`
- `SEARCH d USING AUTOMATIC PARTIAL COVERING INDEX (kind=? AND status=? AND src_text=?) LEFT-JOIN`

Current untranslated-lemma top-100 plan:

- `SEARCH s USING INDEX idx_lemma_proj_freq (project_id=?)`
- `SEARCH l USING INTEGER PRIMARY KEY (rowid=?)`
- `SEARCH t USING INDEX idx_tm_entry_lookup (project_id=? AND status=? AND kind=?) LEFT-JOIN`
- `SEARCH d USING AUTOMATIC PARTIAL COVERING INDEX (kind=? AND status=? AND src_text=?) LEFT-JOIN`

Engineering meaning:

- the top-100 untranslated list already uses the intended project-frequency
  access path and is not the blocker;
- the active hot layer is the exact covered-lemma count with `COUNT(DISTINCT)`
  plus text-based joins;
- this is the layer that justifies the next bounded repair wave.

### Historical status alignment

Historical P2 docs still matter as implementation context, but not as current
cold-performance guardrails:

- `docs/P2_PREMIUM_WORKFLOW.md` still states query-count ceilings and references
  `test_p2_coverage_service.py` / `test_p2_ui_smoke.py`;
- `docs/P2_TESTS.md` still references those same legacy coverage tests;
- those files are not present under the current `tests/` tree.

Engineering meaning:

- query-count ceilings were not enough to protect reference-scale latency;
- do not treat the historical P2 docs as evidence that the current Coverage
  panel is healthy on the approved target;
- current cold-audit artifacts are the canonical evidence for this branch.

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- this is a user-visible project QA surface that opens directly into a large
  lemma slice;
- approved-target evidence shows the blocker is real and current, not
  historical;
- the slow layer is tightly localized:
  - cluster coverage is fast;
  - untranslated lists are fast;
  - lemma coverage exact count is the blocker;
- the branch can stay bounded to staged first usable state and lemma coverage
  repair without widening into general metrics redesign.

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- Coverage panel staged first usable state / lemma coverage repair

Bounded patch scope implied by the evidence:

- decouple first usable state from the slow exact lemma coverage step;
- preserve current Coverage panel semantics unless a separate semantics gate is
  opened later;
- keep cluster coverage and untranslated lists intact;
- avoid widening into historical P2 docs cleanup, general TM redesign, or
  heavy validation.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- Sentences filtered-tail branch
- Dictionary search/FTS branch
- Terms cold-path branch
- Concordance dependency-health branch
- TM residual count-tail branch
- heavy validation branches

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\coverage_panel | Out-Null

.\.venv\Scripts\python.exe -m pytest tests\test_workspace_navigation_v2.py tests\test_p1_workspace.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.coverage_panel import CoveragePanel; from app.ui.workers import CoverageWorker; from app.services.coverage_service import CoverageService; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
probes and written to:

- `build/logs/cold_audit/coverage_panel/coverage_panel_probe.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_query_plan.json`
- `build/logs/cold_audit/coverage_panel/coverage_panel_cold_audit_summary.json`
