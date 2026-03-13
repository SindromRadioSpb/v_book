# Documents View Cold Audit (2026-03-13)

## Why this document exists

This is the tenth task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Documents view cold open / first usable state

This wave does **not**:

- ship a runtime patch;
- reopen Audio, Coverage, TM, Sentences, picker, or startup branches;
- redesign Documents paging, snapshot readiness semantics, or NLP processing;
- open heavy validation.

## Scope

In scope:

- `DocumentsView(project_id=1)` cold open on the approved target
- synchronous UI-thread work during `__init__()` and `init_ui()`
- project default-corpus resolution
- first page loading contract
- snapshot readiness auto-refresh contract
- blocker vs not-blocker classification

Out of scope:

- document import / delete / process write paths
- snapshot coverage backfill
- page-query optimization
- reference-corpus setup/download workflows

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `DV1` | Project dashboard open | approved target | Eliminates a nearby startup surface before opening a new wave | Completed |
| `DV2` | Documents view cold open (full current contract) | approved hewiki test DB | Measures the real user-visible gate | Completed |
| `DV3` | Documents view cold open without NLP engine checks | approved hewiki test DB | Isolates the UI-thread engine-check layer from the async data path | Completed |
| `DV4` | Fresh-process `stanza` import timing | local runtime environment | Confirms the cost of the sync capability probe | Completed |
| `DV5` | Fresh-process `torch` import timing | local runtime environment | Confirms the CUDA-capability probe layer | Completed |

## Entry points and evidence

Code entry points:

- `app/ui/documents_view.py`
- `app/ui/workers.py`
- `app/services/project_service.py`
- `app/services/snapshot_readiness_service.py`

Current smoke/regression entry points:

- `tests/test_documents_pagination_sort_search.py`
- `tests/test_documents_snapshot_readiness_ui.py`
- `tests/test_documents_delete_flow.py`

Evidence artifacts:

- `build/logs/cold_audit/documents_view/documents_view_init_full.json`
- `build/logs/cold_audit/documents_view/documents_view_init_without_engine_checks.json`
- `build/logs/cold_audit/documents_view/documents_view_engine_imports.json`
- `build/logs/cold_audit/documents_view/documents_view_torch_import_fresh.json`
- `build/logs/cold_audit/documents_view/documents_view_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- strict read-only access only

Candidate-selection evidence:

- `ProjectDashboard` cold open on the same approved target is only `0.166s`
- `DocumentsView` cold open is therefore the next justified wave target

## Current UI/workflow contract

Current Documents view open path:

- `DocumentsView.__init__()` instantiates core services and UI controls;
- `init_ui()` synchronously calls:
  - `_check_stanza_available()` which imports `stanza`
  - `_check_cuda_available()` which imports `torch` and checks CUDA only if `stanza` is available
- only after those checks does the view proceed to:
  - `load_corpus()`
  - `load_documents()`
- `load_documents()` is already async through `DocumentsPageWorker`
- snapshot readiness is already async through `SnapshotReadinessWorker`

Engineering meaning:

- the current data-load contract is not one-shot;
- the first page and snapshot readiness already run in background workers;
- the user-visible cold-open cost is dominated by synchronous NLP engine capability checks in the UI thread.

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | Dashboard open and Documents view open were separated before interpretation. | Completed |
| `2. Cold vs warm measurement` | Fresh-process open timings were used for the blocking layer. | Completed |
| `3. Step-by-step cold breakdown` | Full open, no-engine-check open, page-load completion, and import probes were isolated. | Completed |
| `4. SQL-level timing / query audit` | SQL was checked indirectly through async page completion on the approved target. | Completed with bounded scope |
| `5. Service/process timing` | Corpus resolution, page worker, and snapshot readiness worker were distinguished from sync engine checks. | Completed |
| `6. Filesystem / OS / DB-open audit` | Approved DB remained untouched under strict read-only probes. | Completed |
| `7. UI first-render / first-usable-state audit` | First usable state is delayed by sync capability checks before background loading begins. | Completed |
| `8. Degraded / fallback mode audit` | There is no deferred/cached NLP engine capability path today. | Completed |
| `9. Dataset-tier analysis` | The blocker is present on the approved target even though the documents page itself loads asynchronously. | Completed |
| `10. Repeatability protocol` | The commands below are sufficient to reproduce the same bounded decision gate. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `DV1`-`DV5` were fixed before interpretation. | Prevented vague "Documents is slow" claims. |
| `B. Bounded live probes` | Strict read-only offscreen open probes captured the real Documents open path. | This is current evidence, not historical intuition. |
| `C. SQL top offenders log` | The documents page itself reaches `25 / 387,639` rows asynchronously after open. | SQL page load is not the first blocking layer. |
| `D. UI responsiveness probes` | Full cold open is `2.300s`, while the same path without engine checks is `0.063s`. | The UI-thread capability checks are the blocker. |
| `E. Service initialization audit` | `ProjectDashboard` is `0.166s` and does not justify the next wave. | The issue is local to `DocumentsView`, not generic project boot. |
| `F. Drift / fallback path audit` | `stanza`/`torch` checks run synchronously every open today. | A bounded staged/deferred repair is justified. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It crosses the evidence gate for a bounded repair but does not implement it. |

## Current findings

### Approved-target timings

From `documents_view_cold_audit_summary.json`:

- `ProjectDashboard` open: `0.166s`
- `DocumentsView` full cold open: `2.300s`
- `DocumentsView` cold open without engine checks: `0.063s`
- isolated engine-check delta: `2.237s`
- documents page after worker completion:
  - rows shown: `25`
  - total count: `387,639`

Engineering meaning:

- the dominant cold-open layer is not the paged document query;
- without the engine checks, the view becomes available essentially immediately
  and the async loading contract takes over;
- the first page and snapshot readiness are not the primary blocker layers here.

### Runtime import evidence

From fresh-process import probes:

- `stanza` import: `2.298s`
- `torch` import: `1.685s`
- `torch.cuda.is_available()`: effectively `0.000s`
- current approved-target environment reports `cuda_available=false`

Engineering meaning:

- the heavy layer is library import itself, not the CUDA boolean check;
- importing optional NLP dependencies on every Documents view open is the
  dominant synchronous cost;
- this is a capability-probe design issue, not a documents SQL issue.

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- Documents is a primary project-management surface;
- the view currently spends `2.300s` in synchronous open-time work before the
  async data path can even start presenting useful state;
- the blocker is tightly localized and bounded:
  - defer or cache optional NLP engine capability checks
  - keep documents paging and snapshot readiness behavior intact

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- `Documents view staged NLP engine readiness check / first usable state repair`

Bounded patch scope implied by the evidence:

- remove synchronous `stanza` / `torch` import work from the cold-open critical path;
- preserve current async page loading and snapshot readiness workers;
- avoid widening into NLP processing redesign, Documents paging redesign, or schema work.

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
- heavy validation branches

## Verification notes

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\documents_view | Out-Null

New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'

.\.venv\Scripts\python.exe -m pytest tests\test_documents_pagination_sort_search.py tests\test_documents_snapshot_readiness_ui.py tests\test_documents_delete_flow.py -q

.\.venv\Scripts\python.exe -c "import app; from app.ui.documents_view import DocumentsView; print('OK')"
```

Approved-target evidence for this wave was collected through strict read-only
wrappers only; no source/reference DB mutation was performed.
