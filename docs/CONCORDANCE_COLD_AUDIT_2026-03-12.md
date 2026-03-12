# Concordance Cold Audit (2026-03-12)

## Why this document exists

This is the sixth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

The goal of this wave is narrow:

- determine whether Concordance search can be meaningfully cold-audited on the
  approved target;
- classify the current Concordance search path as blocker / not-blocker /
  dependency-gated;
- decide whether a Concordance runtime patch branch should open now.

This wave does **not**:

- change runtime behavior;
- repair or rebuild `sentence_fts`;
- reopen the Sentences filtered-search follow-up;
- open heavy validation.

## Scope

In scope:

- Concordance search dependency health on the approved target
- current Concordance raw FTS query path
- current Concordance UI contract
- blocker vs not-blocker decision

Out of scope:

- runtime code changes
- FTS rebuild / repair work
- search semantics redesign
- pagination redesign
- heavy validation

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `C1` | Concordance search dependency health | approved hewiki test DB | Confirms whether the current feature path is measurable at all | Completed |
| `C2` | Raw project-scoped Concordance FTS query | approved hewiki test DB | Measures current search path only if the dependency is viable | Completed |
| `C3` | Concordance UI contract | code inspection | Confirms current first-usable-state contract before prioritization | Completed |

## Entry points and evidence

Code entry points:

- `app/services/concordance_service.py`
- `app/ui/concordance_view.py`
- `app/ui/workers.py`
- `app/infra/security/audit.py`

Regression entry points:

- `tests/test_security.py`

Evidence artifacts:

- `build/logs/cold_audit/concordance/concordance_sentence_fts_sample.json`
- `build/logs/cold_audit/concordance/concordance_probe.json`
- `build/logs/cold_audit/concordance/concordance_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- strict read-only access only

## Current UI/workflow contract

Current Concordance behavior:

- user enters a query and explicitly triggers search;
- `ConcordanceSearchWorker` resolves the search in one stage;
- the view waits for the final result set before rendering;
- the current view uses `QTableWidget`, not staged rows-first pagination.

Engineering meaning:

- if Concordance search is healthy and materially slow, first usable state is
  directly tied to the full worker completion;
- this makes dependency health a prerequisite for any meaningful cold-latency
  classification.

## Probe boundary

`ConcordanceService.search_concordance()` is not safe for a strict read-only
probe as-is because it creates an `AuditLogger(session)` and that logger writes
to `security_audit_log` with an immediate commit.

For this wave, the approved-target probe therefore used the raw project-scoped
FTS query shape directly, without changing runtime code:

- same `sentence_fts -> document_sentence -> source_document -> source_corpus`
  join path;
- same `MATCH` predicate shape;
- same `ORDER BY rank ASC, sentence_id ASC`;
- no audit-log write attempt against the read-only target.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Concordance dependency health and raw search path were explicitly separated before interpretation. | Completed |
| `2. Cold vs warm measurement` | Not the main differentiator. Dependency viability failed before a meaningful warm-vs-cold latency comparison could matter. | Completed with bounded scope |
| `3. Step-by-step cold breakdown` | The wave reduced to dependency health first, then one raw FTS probe. | Completed |
| `4. SQL-level timing / query audit` | The raw project-scoped FTS query was measured directly. | Completed |
| `5. Service/process timing` | Service timing was intentionally not treated as the dominant layer because the dependency failed first. | Completed with bounded scope |
| `6. Filesystem / OS / DB-open audit` | Not the active layer; the approved DB stayed unchanged under strict read-only access. | Completed with bounded scope |
| `7. UI first-render / first-usable-state audit` | The current UI waits for full result completion, but dependency health failure prevents meaningful latency classification beyond that. | Completed |
| `8. Degraded / fallback mode audit` | Concordance has no healthy fallback path if `sentence_fts` coverage is absent. | Completed |
| `9. Dataset-tier analysis` | Evidence came from the approved hewiki test DB and is therefore valid for current branch prioritization. | Completed |
| `10. Repeatability protocol` | Artifact names and verification commands below are sufficient for this gate note. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `C1`-`C3` were fixed before measurement. | Prevented broad “Concordance is slow” claims. |
| `B. Bounded live probes` | Only read-only FTS health and one raw query probe were collected. | This answered the gate question without widening scope. |
| `C. SQL top offenders log` | No real Concordance SQL offender could be isolated because the prerequisite FTS coverage is absent. | No bounded SQL latency patch is justified. |
| `D. UI responsiveness probes` | UI is one-stage and would surface latency directly, but current dependency failure blocks meaningful UX timing interpretation. | UI is not the first repair layer. |
| `E. Service initialization audit` | Service init is not the active issue in this wave. | No service branch is justified. |
| `F. Drift / fallback path audit` | The current runtime service expects a writable audit logger and a healthy `sentence_fts`; the approved target currently provides neither for a meaningful search result path. | Concordance is dependency-gated, not cold-latency-classified. |
| `G. Before/after evidence protocol` | This is a before-only gate note. No after artifact exists because no patch was justified. | Correctly keeps the branch closed. |

## Current evidence

From `concordance_sentence_fts_sample.json` and `concordance_probe.json`:

- `sentence_fts` rows: `1,792`
- project-scoped sentence rows for project `1`: `13,387,588`
- project-joined `sentence_fts` rows: `0`
- one bounded raw FTS probe returned:
  - `fts_page_elapsed_s ~= 0.038s`
  - `project_fts_count = 0`
  - `page_row_count = 0`

Engineering meaning:

- the approved-target Concordance path is currently not measurable as a normal
  cold-latency workflow;
- the issue is prerequisite coverage, not search-page wall time;
- a fast zero-result path on zero joined rows is not evidence of a healthy
  Concordance surface.

## Decision

Current classification:

- `cold latency blocker`: no
- `concordance path healthy`: no
- `priority`: `P1`
- `open runtime patch now`: no

Decision logic:

- the approved-target `sentence_fts` coverage for project `1` is effectively
  absent on the real join path used by Concordance;
- Concordance cannot be honestly cold-profiled until that dependency is healthy;
- opening a Concordance latency patch now would misdiagnose the layer and
  immediately widen into `sentence_fts` repair work.

## Reopen gate

Open a Concordance follow-up branch only if one of these is crossed with new
approved-target evidence:

- `sentence_fts` health is separately repaired and validated for project-scoped
  joins on the approved target;
- Concordance still shows a real user-visible cold blocker after that health
  gate is crossed;
- a bounded fallback/search-contract decision is approved for Concordance.

Until then:

- keep the Concordance cold-audit wave closed;
- do not open a Concordance latency patch branch;
- treat this as a dependency-health gate tied to `sentence_fts`, not as an
  isolated Concordance performance wave;
- keep the Sentences filtered-search / FTS follow-up branch closed unless its
  own evidence gate is separately crossed.

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\concordance | Out-Null
.\.venv\Scripts\python.exe -m pytest tests\test_security.py -q
.\.venv\Scripts\python.exe -c "import app; from app.services.concordance_service import ConcordanceService, normalize_hebrew_search; from app.ui.concordance_view import ConcordanceView; print('OK')"
```

The canonical artifacts to compare or review are:

- `build/logs/cold_audit/concordance/concordance_sentence_fts_sample.json`
- `build/logs/cold_audit/concordance/concordance_probe.json`
- `build/logs/cold_audit/concordance/concordance_cold_audit_summary.json`
