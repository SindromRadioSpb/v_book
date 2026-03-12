# Terms Cold Audit (2026-03-12)

## Why this document exists

This is the fifth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

The goal of this wave is narrow:

- classify the Terms default first-paint path on the approved target;
- classify one representative Terms search path on the approved target;
- decide whether a new Terms runtime patch branch should open now.

This wave does **not**:

- change runtime behavior;
- reopen term extraction redesign work;
- reopen heavy validation;
- widen into new search infrastructure.

## Scope

In scope:

- Terms first page
- Terms deferred exact count
- Terms representative search page
- Terms representative search exact count
- current staged rows-first UI contract
- blocker vs not-blocker decision

Out of scope:

- term extraction write path
- clustering algorithm changes
- schema/index migrations
- runtime code changes
- heavy validation

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `T1` | Terms default first page | approved hewiki test DB | Clears or confirms current first usable state | Completed |
| `T2` | Terms default exact count | approved hewiki test DB | Checks whether deferred count hides a cold tail | Completed |
| `T3` | Terms representative search page and count | approved hewiki test DB | Checks current filtered workflow for a real cold issue | Completed |
| `T4` | Terms staged first-paint / anti-stale contract | code + targeted regressions | Confirms current UI contract before any prioritization | Completed |

## Entry points and evidence

Code entry points:

- `app/services/term_extraction_service.py`
- `app/ui/terms_view.py`
- `app/ui/workers.py`

Regression entry points:

- `tests/test_dictionary_terms_pagination.py`
- `tests/test_terms_worker_lifecycle.py`
- `tests/test_terms_refresh_flow.py`
- `tests/test_terms_snapshot_reuse_summary.py`

Evidence artifacts:

- `build/logs/cold_audit/terms/terms_probe.json`
- `build/logs/cold_audit/terms/terms_probe_repeat.json`
- `build/logs/cold_audit/terms/terms_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- strict read-only access only

## Current UI/workflow contract

Current Terms search behavior:

- `TermsSearchWorker` loads rows first via `results_ready`;
- exact total is deferred via `count_ready`;
- `TermsView.on_search_results()` renders rows before the final total is known;
- stale responses are dropped by request sequence.

Historical alignment note:

- `docs/PERF_IMPLEMENTATION_AUDIT.md` contains a historical note saying Terms
  computes count before emit;
- current code no longer matches that historical statement;
- the current canonical behavior is the staged rows-first contract above.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Default first page, deferred exact count, representative search path, and staged UI contract were named before interpretation. | Completed |
| `2. Cold vs warm measurement` | First-run and repeat probes were collected on the approved target. | Completed |
| `3. Step-by-step cold breakdown` | Page and count were measured separately for default and representative search paths. | Completed |
| `4. SQL-level timing / query audit` | Query-level timing was bounded to service page/count probes because the measured costs stayed very small. | Completed with bounded scope |
| `5. Service/process timing` | No meaningful service-init layer was exposed. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer here; the approved DB remained unchanged under strict read-only access. | Completed with bounded scope |
| `7. UI first-render / first-usable-state audit` | Current rows-first Terms contract is already aligned with fast first usable state. | Completed |
| `8. Degraded / fallback mode audit` | No degraded/fallback branch was needed for this wave. | Completed with bounded scope |
| `9. Dataset-tier analysis` | Decision evidence came from the approved hewiki test DB, not from the repo-local DB. | Completed |
| `10. Repeatability protocol` | Artifact names and targeted test commands below are sufficient to compare this wave. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `T1`-`T4` were fixed before measurement. | Prevented vague Terms performance claims. |
| `B. Bounded live probes` | First-run and repeat read-only probes were collected on the approved target. | This is current evidence, not historical guesswork. |
| `C. SQL top offenders log` | No dominant SQL offender was exposed because page and count timings were already tiny. | No SQL patch is justified. |
| `D. UI responsiveness probes` | Rows-first staging is already present and aligns with the measured fast first page. | UI is not the current blocker. |
| `E. Service initialization audit` | No material service-init cost was observed. | No service-init branch is justified. |
| `F. Drift / fallback path audit` | Current code and current behavior agree; only a historical perf note is outdated. | This is a docs alignment issue, not a runtime blocker. |
| `G. Before/after evidence protocol` | This is a before-only triage wave. No after artifact exists because no patch was justified. | Correctly keeps the branch closed. |

## Current evidence

From `terms_probe.json` and `terms_probe_repeat.json` on the approved target:

- default first page: `0.003s` first run, `0.056s` repeat probe
- default exact count: `0.009s` first run, `0.002s` repeat probe
- total visible term clusters: `760`
- representative search page: `0.001s` first run, `0.003s` repeat probe
- representative search exact count: `0.001s` first run, `0.001s` repeat probe
- representative search total: `2`

Engineering meaning:

- Terms first usable state is already well below any current blocker threshold;
- deferred exact count is also already cheap;
- representative search is also cheap on the approved target;
- there is no current cold blocker in this subsystem.

## Decision

Current classification:

- `blocker`: no
- `priority`: `P3`
- `open runtime patch now`: no

Decision logic:

- the current default first page is already fast;
- the deferred exact count is already fast;
- representative search is already fast;
- the current Terms UI contract is already rows-first and anti-stale;
- there is no evidence-backed reason to open a Terms patch branch from this wave.

## Reopen gate

Open a Terms follow-up branch only if one of these is crossed with new
approved-target evidence:

- Terms first usable state regresses materially on the approved target;
- a new search/filter path becomes a documented blocker in active workflows;
- a future extraction/output contract change introduces a new cold cost layer.

Until then:

- keep the Terms cold-audit wave closed;
- do not open a Terms performance branch;
- treat the outdated historical perf note as historical context only;
- return to the canonical cold-audit framework for the next narrow subsystem
  wave.

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\terms | Out-Null
.\.venv\Scripts\python.exe -m pytest tests\test_dictionary_terms_pagination.py tests\test_terms_worker_lifecycle.py tests\test_terms_refresh_flow.py tests\test_terms_snapshot_reuse_summary.py -q
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/terms/terms_probe.json`
- `build/logs/cold_audit/terms/terms_probe_repeat.json`
- `build/logs/cold_audit/terms/terms_cold_audit_summary.json`
