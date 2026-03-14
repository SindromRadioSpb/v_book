# Concordance sentence_fts Decision (2026-03-14)

## Why this document exists

This note is a narrow decision-gated follow-up to:

- `docs/CONCORDANCE_COLD_AUDIT_2026-03-12.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

Its purpose is limited:

- confirm whether Concordance / `sentence_fts` dependency-health is still a
  real remaining branch;
- confirm whether the repo already contains a canonical repair path;
- decide whether a new repair branch should open now.

This note is **not**:

- a new wide cold-audit wave;
- a new Concordance latency patch;
- a new generic FTS repair campaign.

## Canonical sources used

This note is based only on existing sources and current code inspection:

- `docs/CONCORDANCE_COLD_AUDIT_2026-03-12.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`
- `build/logs/cold_audit/concordance/concordance_cold_audit_summary.json`
- `scripts/repair_fts_schema.py`
- `docs/FTS_SCHEMA_REPAIR.md`
- `tests/test_repair_fts_schema.py`
- `app/services/concordance_service.py`
- `app/infra/fts_manager.py`

## Confirmed current state

From the canonical Concordance cold-audit evidence on the approved target:

- `sentence_fts` rows: `1,792`
- project `1` sentence rows: `13,387,588`
- project-joined `sentence_fts` rows: `0`
- bounded raw FTS probe:
  - `fts_page_elapsed_s ~= 0.038s`
  - `project_fts_count = 0`
  - `page_row_count = 0`

Engineering meaning:

- Concordance was correctly classified as a dependency-health gate, not as a
  clean latency branch;
- the remaining issue is still real and user-facing if Concordance matters;
- however, the issue is on the `sentence_fts` prerequisite layer, not on the
  Concordance UI/query shell itself.

## Confirmed current repo repair surface

Unlike the Dictionary `lemma_fts` branch, this repo already contains a
canonical repair path for the relevant FTS dependency:

- `scripts/repair_fts_schema.py`
- `docs/FTS_SCHEMA_REPAIR.md`
- `tests/test_repair_fts_schema.py`

Current repair coverage already includes:

- `sentence_fts`
- `term_fts`
- duplicate `sqlite_master` namespace cleanup
- deterministic drop/recreate/rebuild
- post-repair row-count validation
- post-repair `MATCH` probe validation

Engineering meaning:

- there is **already** a bounded, tested repair tool for the specific class of
  FTS dependency failures that blocks Concordance triage;
- this branch does **not** require inventing a new repair surface first.

## Decision

Current classification:

- `status`: `decision-gated`
- `priority`: `P1`
- `real candidate for more work`: yes, but only as an explicit dependency-health
  application step
- `open new runtime patch now`: no

Decision logic:

- the Concordance branch remains meaningful only if Concordance is still a
  product-relevant feature;
- the repo already has a canonical `sentence_fts` repair tool;
- therefore, opening a new code branch right now would likely duplicate already
  existing repair tooling instead of moving the branch forward.

## Practical next step if this branch is chosen later

If Concordance is prioritized later, the bounded next move should be:

1. apply `scripts/repair_fts_schema.py` to the specific unhealthy target DB;
2. re-run approved-target `sentence_fts` join evidence;
3. only then decide whether Concordance still has a real latency/UI branch.

That future step is an **operator/application step**, not a new repair-tool
design task.

## What should not happen next

Do **not** treat this branch as justification for:

- a new generic FTS repair refactor;
- a new Concordance UI patch before dependency health is restored;
- another broad cold-hunt wave;
- more generic `P3` sweeps.

## Reopen gate

Open a future Concordance follow-up branch only if all of the following are
true:

- Concordance still matters enough to prioritize;
- the existing `sentence_fts` repair path has been applied or revalidated
  against the target DB;
- new approved-target evidence still shows a real Concordance blocker after
  dependency health is restored.

Until then:

- keep Concordance cold latency work closed;
- keep this topic decision-gated;
- do not open a new repair-tool branch from it.
