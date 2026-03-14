# Sentences Filtered Tail Decision (2026-03-14)

## Why this document exists

This note is a narrow decision-gated follow-up to:

- `docs/SENTENCES_WORKSPACE_REPAIR_2026-03-12.md`
- `docs/SENTENCES_FILTERED_SEARCH_DECISION_2026-03-12.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

Its purpose is limited:

- confirm whether the remaining Sentences filtered search/count tail is still a
  real branch;
- confirm whether the repo already contains the prerequisite repair path for
  the blocked FTS acceleration layer;
- decide whether a new runtime patch branch should open now.

This note is **not**:

- a new wide cold-audit wave;
- a second Sentences runtime patch;
- a new generic FTS-tooling branch.

## Canonical sources used

This note is based only on existing sources and current repo inspection:

- `docs/SENTENCES_FILTERED_SEARCH_DECISION_2026-03-12.md`
- `docs/SENTENCES_WORKSPACE_REPAIR_2026-03-12.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`
- `build/logs/cold_audit/sentences_workspace/sentences_filtered_tail_repeated.json`
- `scripts/repair_fts_schema.py`
- `docs/FTS_SCHEMA_REPAIR.md`
- `tests/test_repair_fts_schema.py`
- `app/services/sentences_workspace_service.py`

## Confirmed current state

From the canonical approved-target evidence:

- filtered first page: `2.262s`, `1.782s`, `1.987s`
- filtered exact count: `8.604s`, `8.082s`, `7.945s`
- raw SQL ordered filtered page: `1.762s`, `1.623s`, `1.541s`
- raw SQL exact count: `6.442s`, `6.400s`, `6.436s`

Current search semantics remain:

- `lower(text) LIKE lower('%wiki%')`

Current FTS evidence on the approved target remains:

- `document_sentence` rows: `13,389,383`
- `sentence_fts` rows: `1,792`
- `sentence_fts MATCH 'wiki'`: `0`

Engineering meaning:

- the residual tail is real;
- exact filtered count is still the dominant residual cost;
- however, the branch is still not a default-path blocker;
- the structural acceleration candidate (`sentence_fts`) remains unusable until
  dependency health is restored.

## Confirmed current repo repair surface

Unlike the Dictionary `lemma_fts` branch, the repo already contains a canonical
repair tool for the blocked FTS layer:

- `scripts/repair_fts_schema.py`
- `docs/FTS_SCHEMA_REPAIR.md`
- `tests/test_repair_fts_schema.py`

Current repair coverage already includes:

- `sentence_fts`
- deterministic drop/recreate/rebuild
- post-repair row-count validation against `document_sentence`
- post-repair `MATCH` probe validation

Engineering meaning:

- this branch does **not** need a new repair-tool design task;
- the gating issue is not missing tooling but missing application/revalidation
  on the unhealthy approved target.

## Decision

Current classification:

- `status`: `decision-gated`
- `priority`: `P1`
- `real candidate for more work`: yes, but only after `sentence_fts`
  revalidation
- `open new runtime patch now`: no

Decision logic:

- the filtered tail remains a real workflow cost;
- but current evidence still reflects an unhealthy `sentence_fts` substrate on
  the approved target;
- the repo already contains the repair surface required to cross that gate;
- therefore a new runtime branch now would be premature and would duplicate the
  wrong layer of work.

## Practical next step if this branch is chosen later

If Sentences filtered search is prioritized later, the bounded next move should
be:

1. apply `scripts/repair_fts_schema.py` to the specific unhealthy target DB;
2. re-run approved-target `sentence_fts` health evidence;
3. only then decide whether the remaining filtered first page / exact count tail
   still justifies a second Sentences runtime patch.

That future step is an explicit operator/revalidation step, not a new repair
tool design task.

## What should not happen next

Do **not** treat this branch as justification for:

- a second Sentences code patch immediately;
- a new generic FTS repair refactor;
- another broad cold-hunt wave;
- more generic `P3` sweeps.

## Reopen gate

Open a future Sentences follow-up branch only if all of the following are true:

- Sentences filtered search is important enough to prioritize now;
- the existing `sentence_fts` repair path has been applied or revalidated
  against the unhealthy target DB;
- new approved-target evidence still shows a real residual filtered-tail branch
  after dependency health is restored.

Until then:

- keep the default Sentences repair closed;
- keep the filtered-tail topic decision-gated;
- do not open a second runtime patch branch from current evidence.
