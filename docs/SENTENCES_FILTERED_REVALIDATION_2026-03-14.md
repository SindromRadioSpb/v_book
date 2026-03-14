# Sentences Filtered Search/Count Revalidation (2026-03-14)

## Why this document exists

This note records the post-repair revalidation of the residual Sentences
filtered search/count branch on a healthy lower-layer substrate:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

Its purpose is narrow:

- confirm whether the old `sentence_fts` health gate was the real blocker for
  further Sentences filtered-tail decisions;
- measure the current Sentences filtered service contract on the repaired heavy
  baseline DB;
- decide whether a second Sentences runtime patch is now justified.

## Preconditions

This revalidation depends on:

- `docs/SENTENCES_WORKSPACE_REPAIR_2026-03-12.md`
- `docs/SENTENCES_FILTERED_SEARCH_DECISION_2026-03-12.md`
- `docs/SENTENCES_FILTERED_TAIL_DECISION_2026-03-14.md`
- `docs/HEWIKI_BASELINE_RECONNECT_REVALIDATION_2026-03-14.md`

## Probe boundary

The probe used the existing Sentences service contract, not an abstract SQL-only
micro-benchmark:

- `app/services/sentences_workspace_service.py`
  - `list_sentences(..., text_search='wiki', page=1, page_size=100)`
  - `count_sentences(..., text_search='wiki')`

The raw SQL shape was also measured for comparison:

- `document_sentence NOT INDEXED`
- same `LIKE` semantics
- same `ORDER BY sentence_id ASC`

No runtime code was changed in this step.

## Current evidence on healthy substrate

Artifact:

- `build/logs/cold_audit/sentences_workspace/sentences_filtered_revalidation_2026-03-14.json`

Observed on the repaired heavy baseline DB:

- raw ordered page runs: `4.372s`, `1.484s`, `1.459s`
- raw unordered page runs: `1.470s`, `1.467s`, `1.474s`
- raw exact count runs: `16.531s`, `6.702s`, `6.688s`
- service filtered page runs: `2.090s`, `1.892s`, `1.958s`
- service filtered count runs: `7.769s`, `7.606s`, `7.656s`
- `row_count = 100`
- `total = 585`
- representative sample sentence IDs: `3679`, `3682`, `3685`

Engineering meaning:

- the old `sentence_fts` health gate is now crossed, so this branch is now
  honestly measurable on a healthy substrate;
- however, the current Sentences filtered path is still driven by `LIKE`
  semantics on `document_sentence.text`, not by `sentence_fts`;
- the filtered first page remains noticeable but bounded;
- the dominant residual tail remains the exact filtered count.

## Comparison to the old unhealthy-target evidence

Before lower-layer repair on the approved target:

- service filtered first page: `2.262s`, `1.782s`, `1.987s`
- service filtered exact count: `8.604s`, `8.082s`, `7.945s`

After lower-layer repair on the healthy heavy baseline DB:

- service filtered first page: `2.090s`, `1.892s`, `1.958s`
- service filtered exact count: `7.769s`, `7.606s`, `7.656s`

Interpretation:

- lower-layer `sentence_fts` health was a real prerequisite for honest
  evaluation, but it was not the dominant runtime cost of the current Sentences
  filtered contract;
- the branch does not unlock into an obvious bounded acceleration patch just by
  restoring `sentence_fts`;
- the residual cost remains tied to current `LIKE` semantics and exact-count
  expectations.

## Decision

Current classification after healthy-substrate revalidation:

- `status`: `decision-gated`
- `priority`: `P1`
- `blocker`: no
- `open second Sentences runtime patch now`: no

Decision logic:

- the main Sentences cold blocker was already closed by the first-usable-state
  repair;
- the remaining filtered tail is still real, but it remains a secondary,
  search-heavy workflow residual rather than a default-path blocker;
- the healthy `sentence_fts` substrate removes the old dependency-health gate,
  but the current service semantics still do not admit an obvious bounded patch
  without widening into search semantics or count semantics work;
- no honest immediate runtime patch is justified from current evidence.

## What changes strategically

What is now resolved:

- the old uncertainty about whether unhealthy `sentence_fts` was masking the
  true Sentences filtered-tail picture

What remains:

- a documented `P1` residual tail for search-heavy Sentences workflows

What is now justified operationally:

- close the application-layer cold revalidation stage
- move separately to lower-layer recovery on the unhealthy
  `hewiki_gpu_processing test.db`

What is not justified:

- reopening a broad Sentences runtime optimization branch from current evidence
- reopening generic cold-hunt or P3 sweeps
