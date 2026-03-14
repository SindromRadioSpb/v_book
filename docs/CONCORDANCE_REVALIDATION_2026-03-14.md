# Concordance Revalidation (2026-03-14)

## Why this document exists

This note records Concordance revalidation after lower-layer `sentence_fts`
health was restored on the heavy baseline / reconnect target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

Its purpose is narrow:

- confirm that the old Concordance dependency-health gate is actually crossed;
- classify the current Concordance search path on healthy FTS;
- decide whether any Concordance runtime patch is still justified.

## Preconditions

This revalidation depends on:

- `docs/CONCORDANCE_COLD_AUDIT_2026-03-12.md`
- `docs/CONCORDANCE_SENTENCE_FTS_DECISION_2026-03-14.md`
- `docs/SENTENCE_FTS_LOWER_LAYER_REVALIDATION_2026-03-14.md`
- `docs/HEWIKI_BASELINE_RECONNECT_REVALIDATION_2026-03-14.md`

## Probe boundary

`ConcordanceService.search_concordance()` still writes an audit event.

To keep the measurement bounded and avoid mixing latency with audit-log write
cost, this revalidation again used the raw project-scoped FTS query shape:

- `sentence_fts -> document_sentence -> source_document -> source_corpus`
- same `MATCH`
- same `ORDER BY rank ASC, sentence_id ASC`

## Current evidence on healthy FTS

Artifact:

- `build/logs/cold_audit/concordance/concordance_revalidation_2026-03-14.json`

Observed on the repaired heavy baseline DB:

- page runs: `0.033s`, `0.021s`, `0.021s`
- count runs: `0.011s`, `0.010s`, `0.011s`
- `page_row_count = 100`
- `count_total = 665`
- representative sample sentence IDs were returned

Engineering meaning:

- the old zero-row dependency-health failure is gone;
- Concordance search is now measurable on a healthy substrate;
- on that healthy substrate, the current raw Concordance query path is already
  fast and does not justify a runtime repair branch.

## Decision

Current classification after revalidation:

- `status`: `closed`
- `priority`: `P3`
- `blocker`: no
- `open runtime patch now`: no

Decision logic:

- the old branch was real only as a dependency-health gate;
- that gate has now been crossed on the repaired heavy baseline DB;
- the revalidated Concordance query path is already bounded and fast;
- no honest Concordance performance blocker remains from current evidence.

## What changes strategically

What is now closed:

- Concordance dependency-health gate on healthy `sentence_fts`
- Concordance latency follow-up branch

What remains next:

- Sentences filtered search/count revalidation on the same healthy substrate

What is not justified:

- reopening Concordance as a cold branch
- opening a Concordance UI/runtime patch from current evidence
