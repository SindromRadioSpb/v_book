# Sentences Filtered Search Decision Note (2026-03-12)

## Why this document exists

This document records the post-repair decision-gated review of the residual
Sentences filtered search tail that remained after:

- `docs/SENTENCES_WORKSPACE_REPAIR_2026-03-12.md`

This is not a new runtime patch wave. It is a bounded decision note used to
answer one narrow question:

- should the repo open a second Sentences patch branch immediately for filtered
  search/count, or keep that tail documented and gated?

## Scope

In scope:

- filtered Sentences first page with `text_search`
- exact filtered count
- current `LIKE` semantics
- current `ORDER BY` residue
- current `sentence_fts` health on the approved target
- bounded query-shape implications

Out of scope:

- new runtime code
- FTS rebuild or repair work
- schema/index migrations
- UI redesign
- heavy validation

## Entry points and evidence

Code entry points:

- `app/services/sentences_workspace_service.py`
- `app/ui/sentences_view.py`
- `app/infra/fts_manager.py`

Evidence artifacts:

- `build/logs/cold_audit/sentences_workspace/sentences_repair_after.json`
- `build/logs/cold_audit/sentences_workspace/sentences_repair_breakdown_after.json`
- `build/logs/cold_audit/sentences_workspace/sentences_filtered_tail_probe.json`
- `build/logs/cold_audit/sentences_workspace/sentences_filtered_tail_repeated.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- strict read-only access only

## Current UI/workflow contract

The Sentences text filter remains an interactive workflow:

- `text_search_edit.textChanged -> _filter_timer.start()`
- debounce interval: `400 ms`
- stage 1: `page_ready` renders rows first
- stage 2: `count_ready` updates exact total later

Engineering meaning:

- exact filtered count does not block the first filtered row render;
- exact filtered count does delay final pagination totals and navigation bounds;
- filtered first-page latency still matters because the user does not see new
  rows until stage 1 completes.

## Current evidence

### Service-level timings after the first-page repair

From the repeated approved-target probe:

- filtered first page: `2.262s`, `1.782s`, `1.987s`
- filtered exact count: `8.604s`, `8.082s`, `7.945s`

From the after-breakdown probe:

- filtered `page_rows ~= 1.852s`
- filtered `audio ~= 0.243s`
- filtered `count ~= 7.592s`

Engineering meaning:

- the residual tail is real;
- the dominant residual cost is the exact filtered count;
- the filtered first page is noticeable, but it is materially smaller than the
  old default first-page blocker and no longer blocks the main user path.

### ORDER BY residue

Repeated raw SQL probe on the approved target:

- ordered filtered page: `1.762s`, `1.623s`, `1.541s`
- unordered filtered page: `1.524s`, `1.518s`, `1.530s`

Interpretation:

- `ORDER BY sentence_id ASC` still has measurable cost;
- after the first-page repair, that cost is no longer the dominant filtered-tail
  issue;
- removing ordering would only recover a small fraction of the current
  search-page latency and would weaken deterministic paging semantics.

### LIKE semantics and exact count

Current filtered search semantics are still:

- `lower(text) LIKE lower('%wiki%')`

Exact filtered count remains expensive because it must scan the sentence text
predicate across the large sentence table:

- raw SQL exact count: `6.442s`, `6.400s`, `6.436s`
- service exact count: `8.604s`, `8.082s`, `7.945s`

Interpretation:

- exact filtered count is the dominant residual tail;
- the repo currently has no bounded exact-count optimization for this path that
  preserves current semantics without opening broader work.

### FTS health on the approved target

Current `sentence_fts` evidence on the approved target:

- `document_sentence` rows: `13,389,383`
- `sentence_fts` rows: `1,792`
- `sentence_fts MATCH 'wiki'`: `0`
- `document_sentence` row `sentence_id=3679` exists
- `sentence_fts` rowid `3679` does not exist

Interpretation:

- `sentence_fts` is not healthy enough on the approved target to serve as a safe
  bounded optimization path for this decision;
- an FTS-based Sentences search patch would implicitly widen into FTS health /
  rebuild / semantics work.

## Decision

Current classification:

- `blocker`: no
- `priority`: `P1`
- `open second Sentences patch now`: no

Decision logic:

- the main Sentences blocker was the default first usable state, and that is now
  closed;
- filtered first page is slower than ideal, but it is a secondary workflow and
  is no longer the dominant system bottleneck by default;
- exact filtered count is still expensive, but it is stage-2 async work rather
  than a first-render blocker;
- the most obvious structural acceleration path (`sentence_fts`) is not healthy
  enough on the approved target for a bounded immediate patch;
- the remaining options would either recover limited value (`ORDER BY` residue)
  or widen scope into FTS health / search semantics / count semantics work.

## Reopen gate

Open a second Sentences filtered-search patch branch only if one of these is
crossed with new approved-target evidence:

- filtered first page becomes a documented blocker for active user workflows;
- filtered exact count is shown to be operationally blocking pagination or core
  search usage rather than remaining an async tail;
- `sentence_fts` health is separately repaired and validated on the approved
  target;
- a narrower exact-count strategy is approved without widening scope.

Until then:

- keep this residual tail documented;
- keep the Sentences branch closed;
- return to the canonical cold-audit framework for the next narrow subsystem
  wave.
