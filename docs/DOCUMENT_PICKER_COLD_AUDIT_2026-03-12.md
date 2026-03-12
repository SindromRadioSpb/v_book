# Document Picker Cold Audit (2026-03-12)

## Why this document exists

This is the second task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Document Picker search / first-paint cold path

This wave does **not**:

- add a runtime patch;
- reopen the old picker patch track automatically;
- widen into a general UI-performance program;
- claim that all document-list surfaces share the same conclusion.

## Historical context

The picker already has historical evidence in:

- `docs/PERF_IMPLEMENTATION_AUDIT.md`
- `docs/PERF_SCALE_AUDIT_HEWIKI_2026-03-07.md`
- `build/logs/picker_p003/perf_harness_post_patch.json`

Those artifacts remain valid history, but this wave decides only whether the
picker is a **current** cold blocker now.

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `P1` | Picker first page, empty search | approved hewiki test DB | Confirms whether the first visible picker page is still cold-heavy at scale | Completed |
| `P2` | Picker search page, text query `wiki` | approved hewiki test DB | Confirms whether the historical picker search blocker still exists | Completed |
| `P3` | Picker staged first-paint contract | code + tests | Confirms whether rows still render before total count | Completed |
| `P4` | Repo-local picker harness viability | local `hdle_premium.db` | Checks whether local dev evidence is usable for this subsystem | Completed with no-op decision |

## Evidence artifacts

- `build/logs/cold_audit/document_picker/picker_hewiki_test_summary.json`
- `build/logs/cold_audit/document_picker/picker_hewiki_test_query_plan.json`
- `build/logs/cold_audit/document_picker/picker_cold_audit_summary.json`
- `build/logs/picker_p003/perf_harness_post_patch.json`
- `app/services/document_service.py`
- `app/ui/workers.py`
- `app/ui/dialogs/document_picker_dialog.py`
- `tests/test_document_picker_flow.py`

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Empty first page, text search page, and staged first paint were explicitly chosen. | Completed |
| `2. Cold vs warm measurement` | Current wave used the existing bounded picker harness on the approved target and compared against the historical post-patch harness output. This is enough for blocker triage, but it is not a fresh-process UI startup measurement. | Completed with bounded scope |
| `3. Step-by-step cold breakdown` | Breakdown is now clear: query selection -> worker emits rows -> dialog renders rows -> total count follows later. | Completed |
| `4. SQL-level timing / query audit` | Current query-plan artifact shows residual TEMP B-TREE use for both empty and search flows, plus a UNION-based search path. Despite that, measured p95 is comfortably within the historical budgets. | Completed |
| `5. Service/process timing` | No dominant service-layer blocker was exposed. The main service work is query assembly plus DTO fetch, and it remains bounded on the approved target. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer for this wave. The approved hewiki test DB was already readable and safe for the read-only harness. | Optional and not active |
| `7. UI first-render / first-usable-state audit` | Code and regression tests confirm staged first paint: rows render before total count. No new live stopwatch probe was required because the staged contract is already deterministic and covered by tests. | Completed |
| `8. Degraded / fallback mode audit` | Fallback still exists in the search layer: if FTS is unavailable, the service falls back to LIKE search. On the approved target FTS is available, so fallback drift is not the active issue. | Completed |
| `9. Dataset-tier analysis` | The approved reference test DB is the valid decision target for this wave. The repo-local DB was explicitly cleared from decision use because it is not schema-compatible with the current picker harness. | Completed |
| `10. Repeatability protocol` | Commands below reproduce the approved-target harness, query-plan audit, and targeted regressions without opening any write path. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `P1` through `P4` were named before any conclusion. | Prevented historical picker debt from being auto-promoted into a new blocker. |
| `B. Bounded live probes` | Current safe harness on the approved target measured `picker_page_empty` and `picker_page_search`. | Gives the current scale-tier truth. |
| `C. SQL top offenders log` | Query-plan evidence shows TEMP B-TREE residue and UNION cost, but timings stay well inside the accepted budgets. | Structural residue exists, but it is not a current patch trigger. |
| `D. UI responsiveness probes` | Existing staged-render contract is verified by code and targeted regression tests. | First paint remains intentionally staged, not fully blocked on total count. |
| `E. Service initialization audit` | No material service-init problem was exposed; the dominant work remains read-path query execution. | No separate service-init branch is justified. |
| `F. Drift / fallback path audit` | FTS-backed fast path is active on the approved target, and the fallback path remains bounded rather than silently taking over. | No fallback-drift issue was found. |
| `G. Before/after evidence protocol` | Historical post-patch evidence from `picker_p003` was compared with the current approved-target run. | This wave is continuity triage, not a new before/after patch cycle. |

## Current findings

### Approved-target performance

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- size `26,148,278,272` bytes

Current measured results:

- `picker_page_empty p95`: `0.152 s`
- `picker_page_search p95`: `0.120 s`

Historical post-patch comparison from `build/logs/picker_p003/perf_harness_post_patch.json`:

- historical `picker_page_empty p95`: `0.139 s`
- historical `picker_page_search p95`: `0.097 s`

Interpretation:

- both current results remain comfortably inside the historical budgets:
  - empty page budget `<= 0.30 s`
  - search page budget `<= 1.50 s`
- current variance does not justify reopening a picker performance branch.

### Query-plan residue

Current query-plan audit still shows:

- TEMP B-TREE for empty-page `ORDER BY`
- TEMP B-TREE for search-page `ORDER BY`
- UNION-based search plan with:
  - FTS-backed arm
  - fallback `lower(file_name) LIKE lower('%wiki%')` arm
  - exact tag arm

This is structural residue, but not a current blocker because the approved-target
timings remain low.

### First-paint contract

The first-paint path remains intentionally staged:

- `ProjectDocumentsPageWorker` emits `rows_loaded` before `count_loaded`
- `DocumentPickerDialog._on_rows_loaded()` renders rows immediately
- total count can remain pending without blocking the first visible table rows

Regression lock:

- `tests/test_document_picker_flow.py::test_document_picker_rows_render_before_total_count`

This means the picker still has a real staged first-paint contract, not a hidden
wait-for-count UI regression.

### Repo-local dev target caveat

The repo-local DB was **not** used for the final picker decision:

- target: `J:\Project_Vibe\V_book\hdle_premium.db`
- current schema in that DB: `41`
- current picker runtime model expects `snapshot_sentence_count`

As a result, the existing picker harness fails there with a schema-mismatch
exception. That is a local compatibility note, not evidence that picker search or
first paint is a current blocker on the approved target.

## Prioritization outcome

Current classification:

- `blocker`: no
- `recommended priority`: `P3`
- `open patch now`: no

Decision logic:

- approved-target search and empty-page timings are well inside the existing budgets;
- first paint remains staged by design and by regression coverage;
- structural query-plan residue exists, but it no longer translates into a real
  current user-visible blocker;
- the old picker branch therefore remains closed.

## Decision gate for any future picker branch

Do **not** reopen a picker branch from this wave alone.

Open a new picker patch branch only if one of these happens:

- approved-target evidence shows a new `picker_page_search` or `picker_page_empty`
  budget breach;
- live UI evidence shows that rows no longer become usable before the count path
  finishes;
- fallback/drift evidence shows that the FTS-backed path is no longer active on a
  target where it should be active.

Until then:

- picker cold-audit triage is closed;
- the picker remains a historical optimization area, not a current active branch;
- do not reopen it without a new evidence gate.

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\document_picker | Out-Null
.\.venv\Scripts\python.exe scripts\perf_harness.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db" --runs 3 --warmup 1 --out build\logs\cold_audit\document_picker\picker_hewiki_test_summary.json
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_document_picker_flow.py -q
```
