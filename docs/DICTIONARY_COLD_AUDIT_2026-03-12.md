# Dictionary Cold Audit (2026-03-12)

## Why this document exists

This is the fourth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

The goal of this wave is narrow:

- classify the Dictionary default first-paint path on the approved target;
- classify the Dictionary text-search path on the approved target;
- decide whether a new Dictionary runtime patch branch should open now.

This wave does **not**:

- change runtime behavior;
- repair or rebuild FTS;
- add new performance instrumentation;
- reopen heavy validation.

## Scope

In scope:

- Dictionary default first page
- Dictionary exact count
- Dictionary staged first-paint contract
- Dictionary search path on the approved target
- `lemma_fts` parity evidence on the approved target
- blocker vs not-blocker decision

Out of scope:

- runtime code changes
- FTS rebuild / repair work
- search semantics redesign
- schema or index migration
- heavy validation

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `D1` | Default Dictionary first page and count | approved hewiki test DB | Clears or confirms the cold default user path | Completed |
| `D2` | Dictionary text search first page and exact count | approved hewiki test DB | Determines whether search is a current cold blocker | Completed |
| `D3` | Dictionary staged first-paint / deferred count contract | code + targeted regressions | Confirms whether UI is still rows-first and anti-stale | Completed |
| `D4` | Dictionary FTS parity / drift check | approved hewiki test DB | Verifies whether current search evidence is trustworthy | Completed |

## Entry points and evidence

Code entry points:

- `app/services/dictionary_service.py`
- `app/ui/dictionary_view.py`
- `app/ui/workers.py`
- `app/infra/fts_manager.py`

Regression entry points:

- `tests/test_dictionary_pagination_flow.py`
- `tests/test_perf_lemma_fts.py`
- `tests/test_dictionary_worker_lifecycle.py`

Evidence artifacts:

- `build/logs/cold_audit/dictionary/dictionary_probe.json`
- `build/logs/cold_audit/dictionary/dictionary_fts_drift_probe.json`
- `build/logs/cold_audit/dictionary/dictionary_search_parity_sample.json`
- `build/logs/cold_audit/dictionary/dictionary_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- strict read-only access only

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Default page, exact count, search page, and FTS parity were explicitly named before interpretation. | Completed |
| `2. Cold vs warm measurement` | Default page and exact count were measured cold on the approved target; count cache behavior was also observed. | Completed |
| `3. Step-by-step cold breakdown` | Default page, search page, exact count, and parity checks were split into separate bounded probes. | Completed |
| `4. SQL-level timing / query audit` | The service/query layer was audited through direct service calls, direct `lemma_fts MATCH`, and direct `LIKE` comparisons. | Completed |
| `5. Service/process timing` | No material service-init layer was exposed; the main service cost question narrowed to query path and FTS parity. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer for this wave. The approved DB was accessed in strict read-only mode and remained unchanged. | Completed with bounded scope |
| `7. UI first-render / first-usable-state audit` | The Dictionary view still uses rows-first staging and deferred count updates. No new first-paint regression was found. | Completed |
| `8. Degraded / fallback mode audit` | Current search behavior was checked against the documented FTS-vs-fallback contract and revealed approved-target parity drift. | Completed |
| `9. Dataset-tier analysis` | Decision evidence came from the approved hewiki test DB, not from the smaller repo-local DB. | Completed |
| `10. Repeatability protocol` | Commands and artifact names below are sufficient to repeat the same bounded wave. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `D1`-`D4` were fixed before measurement. | Prevented vague "dictionary is slow" claims. |
| `B. Bounded live probes` | Default/search/parity probes were collected read-only on the approved target. | This is real evidence, not local guesswork. |
| `C. SQL top offenders log` | Default path did not expose a significant SQL offender; search evidence instead exposed FTS parity drift. | Search cannot be treated as a normal performance-only issue yet. |
| `D. UI responsiveness probes` | Existing staged first-paint contract remains intact by code and regression coverage. | UI is not the dominant issue in this wave. |
| `E. Service initialization audit` | No meaningful service-init bottleneck appeared. | No Dictionary init patch is justified. |
| `F. Drift / fallback path audit` | `lemma_fts` exists, but approved-target parity is not healthy enough for the preferred search path to be trusted. | Search correctness/health must be decision-gated separately from cold performance. |
| `G. Before/after evidence protocol` | This is a before-only triage wave. No after artifact exists because no runtime patch was justified. | Correctly keeps the branch in audit/decision mode. |

## Current evidence

### Default Dictionary path

From `dictionary_probe.json` on the approved target:

- default first page: `0.003s`
- default exact count (cold): `0.129s`
- default exact count (cached): `0.000s`
- total visible Dictionary rows with current noise filter: `2,070,890`

Engineering meaning:

- the default Dictionary cold path is not a blocker;
- the count cache is behaving as intended for repeated exact counts;
- no default first-paint patch branch is justified.

### Current staged first-paint contract

The current Dictionary flow remains:

- `DictionarySearchWorker.results_ready` emits page rows first;
- `DictionarySearchWorker.count_ready` emits exact total later;
- `DictionaryView.on_search_results()` renders rows before the final total is known;
- anti-stale request sequencing remains explicit in `DictionaryView`.

Engineering meaning:

- the Dictionary UI contract remains staged and responsive by design;
- this wave found no reason to reopen Dictionary UI wiring.

### Search path and approved-target parity

Initial approved-target probe:

- single-character sample term returned:
  - `lemma_fts MATCH` rows: `378`
  - service page rows: `0`
  - service exact count: `0`

Follow-up parity probes:

- `lemma` rows: `2,071,947`
- `lemma_fts` rows: `2,076,909`
- extra `lemma_fts` rows vs `lemma`: `4,962`
- in a 12-term approved-target sample:
  - `LIKE` count was non-zero for `12 / 12` terms
  - service search count was non-zero for `0 / 12` terms
  - `lemma_id IN (SELECT rowid FROM lemma_fts MATCH ...)` was non-zero for `0 / 12` terms

Representative drift examples from the approved target:

- lemma row `lemma_id=12` exists and `lemma_fts rowid=12` also exists;
- the same lemma text matches `lemma_fts rowid=2074089`, not `12`;
- this means the FTS search result set is no longer aligned with current
  `lemma.lemma_id` values used by the service filter.

Engineering meaning:

- the approved-target Dictionary search path is not currently classifiable as a
  clean cold-performance issue;
- the preferred search route is affected by FTS parity drift;
- a new Dictionary performance patch would widen immediately into
  FTS-health/search-correctness work.

## Decision

Current classification:

- `default first-path blocker`: no
- `dictionary search cold blocker`: no
- `dictionary search contract healthy`: no
- `priority`: `P1`
- `open runtime patch now`: no

Decision logic:

- the default first page and exact count are already fast on the approved
  target;
- the UI staged first-paint contract remains correct;
- current search evidence is dominated by `lemma_fts` parity drift rather than a
  proven cold bottleneck on a healthy search path;
- opening a performance patch now would over-expand scope into search
  correctness / FTS health work without a separate decision gate.

## Reopen gate

Open a Dictionary follow-up branch only if one of these is crossed with new
approved-target evidence:

- a separate bounded `lemma_fts` health/parity review is approved and confirms a
  safe repair path;
- Dictionary search is shown to be a current workflow blocker after search
  correctness is restored or bypassed for measurement;
- a bounded fallback-path decision is approved and measured honestly against the
  current contract.

Until then:

- keep the Dictionary cold-audit wave closed;
- do not open a Dictionary performance patch branch;
- treat Dictionary search/FTS health as a separate decision-gated topic, not as
  an automatic continuation of this cold wave;
- return to the canonical cold-audit framework for the next narrow subsystem
  wave.

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\dictionary | Out-Null

.\.venv\Scripts\python.exe -m pytest tests\test_dictionary_pagination_flow.py tests\test_perf_lemma_fts.py tests\test_dictionary_worker_lifecycle.py -q
```

This wave's approved-target live probes were run through bounded inline
read-only sessions against:

- `app/services/dictionary_service.py`
- `app/infra/db.py`

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/dictionary/dictionary_probe.json`
- `build/logs/cold_audit/dictionary/dictionary_fts_drift_probe.json`
- `build/logs/cold_audit/dictionary/dictionary_search_parity_sample.json`
- `build/logs/cold_audit/dictionary/dictionary_cold_audit_summary.json`
