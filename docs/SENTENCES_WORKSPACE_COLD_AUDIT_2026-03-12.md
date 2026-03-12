# Sentences Workspace Cold Audit (2026-03-12)

## Why this document exists

This is the third task-specific use of the canonical cold-audit framework in:

- `docs/COLD_AUDIT_FRAMEWORK.md`

This wave targets one bounded subsystem only:

- Sentences workspace first page / count / first-usable-state cold path

This wave does **not**:

- ship a runtime patch;
- reopen closed governance, picker, startup, or telemetry branches;
- widen into a general Sentences feature redesign;
- open heavy validation.

## Historical context

Historical sentences performance context already existed in:

- `docs/PERF_SCALE_AUDIT_HEWIKI_2026-03-07.md`
- `docs/PERF_IMPLEMENTATION_AUDIT.md`

That history claimed the major sentences path had already been structurally
improved through staged first paint, `SUM(sentence_count)` fast path, and
`corpus_id` denormalization. This wave checks whether the current approved target
still behaves like a non-blocking path in practice.

## Scenario matrix

| Scenario ID | Scenario | Target | Why it matters now | Status |
| --- | --- | --- | --- | --- |
| `S1` | Sentences view first page, no filters | approved hewiki test DB | This is the first user-visible Sentences load and therefore the first usable state for the tab | Completed |
| `S2` | Sentences total count, no filters | approved hewiki test DB | Confirms whether the documented `SUM(sentence_count)` fast path still holds | Completed |
| `S3` | Sentences filtered count, `text_search='wiki'` | approved hewiki test DB | Confirms whether interactive search count is now a material cold tail or blocker | Completed |
| `S4` | Sentences staged first paint + anti-stale contract | code + tests | Confirms whether the UI still renders rows before count and drops stale responses | Completed |

## Evidence artifacts

- `build/logs/cold_audit/sentences_workspace/sentences_service_hewiki_test_summary.json`
- `build/logs/cold_audit/sentences_workspace/sentences_service_hewiki_breakdown.json`
- `build/logs/cold_audit/sentences_workspace/sentences_cold_audit_summary.json`
- `app/services/sentences_workspace_service.py`
- `app/ui/sentences_view.py`
- `tests/test_sentences_workspace_service.py`
- `tests/test_patch_h_anti_stale.py`

## Cold-audit Levels 1-10

| Level | Result for this wave | Outcome |
| --- | --- | --- |
| `1. Inventory user-visible cold scenarios` | The first page, unfiltered count, filtered count, and staged first-paint contract were explicitly selected. | Completed |
| `2. Cold vs warm measurement` | Three strict read-only runs on the approved target show the first-page path staying around `3.56s` to `4.10s`, not collapsing into a negligible warm-only tail. | Completed |
| `3. Step-by-step cold breakdown` | The dominant cost is the main page query itself (`~3.68s`), not the overlay batch work. Filtered count with `text_search='wiki'` takes `~8.89s`. | Completed |
| `4. SQL-level timing / query audit` | The page query still uses `USE TEMP B-TREE FOR ORDER BY`. The filtered count path still scans through the sentence text predicate on the large sentence table. | Completed |
| `5. Service/process timing` | Service overhead outside SQL is small. Translation and niqqud overlays are millisecond-scale; audio overlay is `~0.21s`, but the page query remains dominant. | Completed |
| `6. Filesystem / OS / DB-open audit` | Not the active layer. This wave used the already-open strict read-only DB manager on the approved target. | Optional and not active |
| `7. UI first-render / first-usable-state audit` | The UI still stages rows before count, but first usable state is blocked by the main page query because rows are not available until that query finishes. | Completed |
| `8. Degraded / fallback mode audit` | No hidden degraded/fallback mode was found here. The problem is not contract drift; it is the live read path itself. | Completed |
| `9. Dataset-tier analysis` | The decision target for this wave is the approved hewiki test DB. No local-only shortcut evidence was used to downgrade the issue. | Completed |
| `10. Repeatability protocol` | The commands below reproduce the strict read-only service timings, breakdown, and regression coverage. | Completed |

## Research matrix A-G

| Block | Result | Engineering meaning |
| --- | --- | --- |
| `A. Scenario matrix` | `S1` through `S4` were named before interpretation. | Prevented mixing UI first paint with secondary count-tail behavior. |
| `B. Bounded live probes` | Strict read-only probes on the approved target captured current service timings. | This is current evidence, not historical replay. |
| `C. SQL top offenders log` | Page-query ordering and filtered count search are the active offenders. | The blocker is structural and query-backed. |
| `D. UI responsiveness probes` | The UI contract is staged and anti-stale, but rows still arrive too late because the stage-1 page query is slow. | UI wiring is not enough to hide the read-path cost. |
| `E. Service initialization audit` | Non-SQL service work is minor. | Do not misclassify this as service-init overhead. |
| `F. Drift / fallback path audit` | No fallback-path drift was found. The path is simply slow on the approved target. | A real patch branch is justified instead of more drift triage. |
| `G. Before/after evidence protocol` | This is a before-only audit wave. | It crosses an evidence gate and justifies a bounded next patch, but does not implement it. |

## Current findings

### Approved-target timings

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- access mode: strict read-only

Current results:

- first-page runs: `3.806s`, `4.097s`, `3.558s`
- unfiltered total count runs: `0.024s`, `0.016s`, `0.016s`
- filtered count with `text_search='wiki'`: `8.307s`, `8.418s`, `8.716s`

Interpretation:

- the documented unfiltered `SUM(sentence_count)` path is still healthy;
- the first visible page load is not healthy;
- filtered interactive count is materially worse than the first page itself.

### Breakdown

Current measured breakdown on the approved target:

- `get_project_corpus_ids`: `0.000s`
- `page_query`: `3.682s`
- `get_project_src_lang`: `0.000s`
- `batch_get_translations`: `0.005s`
- `batch_get_sentence_niqqud`: `0.002s`
- `batch_get_audio`: `0.208s`
- `count_all`: `0.026s`
- `count_text_search_wiki`: `8.887s`

The dominant blocker is the page query itself. Audio overlay is visible but
secondary. Translation and niqqud overlays are negligible here.

### Query-plan evidence

Current page-query plan:

- `SEARCH document_sentence USING INDEX idx_sentence_corpus_sent_id (corpus_id=?)`
- `SEARCH source_document USING INTEGER PRIMARY KEY (rowid=?)`
- `USE TEMP B-TREE FOR ORDER BY`

Current filtered-count plan:

- `SEARCH document_sentence USING INDEX idx_sentence_corpus_sent_id (corpus_id=?)`

Engineering meaning:

- the page query still pays a temp-sort cost for `ORDER BY sentence_id, sent_index`;
- the filtered count path still executes a large text-search scan pattern over the
  sentence table.

### First-usable-state and anti-stale contract

The UI contract is still correct:

- `_SentencesLoadWorker.page_ready` emits before `count_ready`
- `SentencesView._on_page_ready()` applies only for the active request
- stale responses are dropped by `request_id`

Regression evidence:

- `tests/test_patch_h_anti_stale.py`
- `tests/test_sentences_workspace_service.py`

However, this does **not** clear the subsystem. First usable state is still
blocked by the stage-1 page query because rows do not exist until the `~3.68s`
query completes.

## Prioritization outcome

Current classification:

- `blocker`: yes
- `recommended priority`: `P0`
- `open patch now`: yes

Decision logic:

- this is a real user-visible path in a core workspace tab;
- the approved target shows multi-second first-page latency even before count;
- the filtered search count is materially slower still;
- the dominant layer is structural SQL/query cost, not a small residual tail;
- the branch can stay bounded to Sentences list/count first-usable-state repair.

## Next bounded patch gate

This wave crosses a new evidence gate.

The next active layer should now be:

- bounded Sentences workspace cold-path repair

Bounded patch scope implied by the evidence:

- reduce or eliminate the page-query temp-sort path;
- reduce filtered `text_search` count cost on the approved target;
- preserve staged first paint and anti-stale behavior;
- do not widen into unrelated Sentences feature work.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- governance/readiness/telemetry branches
- heavy validation branches

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\sentences_workspace | Out-Null
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_sentences_workspace_service.py tests\test_patch_h_anti_stale.py tests\test_sentences_context_menu.py tests\test_sentences_user_dictionary_refresh.py -q
```
