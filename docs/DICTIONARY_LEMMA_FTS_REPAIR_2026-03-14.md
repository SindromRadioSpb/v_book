# Dictionary lemma_fts Repair (2026-03-14)

## Why this document exists

This is the bounded repair follow-up to:

- `docs/DICTIONARY_COLD_AUDIT_2026-03-12.md`
- `docs/DICTIONARY_LEMMA_FTS_DECISION_2026-03-14.md`

The goal of this branch is narrow:

- keep Dictionary cold-open classification honest;
- add a canonical repair path for `lemma_fts` rowid parity drift;
- lock search parity recovery with bounded automated evidence.

This repair does **not**:

- reopen Dictionary cold-open work;
- add new generic `P3` sweeps;
- widen into a broader FTS-stack rewrite;
- silently rebuild `lemma_fts` on every startup.

## Objective Dictionary open measurement

Dictionary open was already measured on the approved target and remains
objectively **not** a cold blocker:

- default first page ~= `0.003s`
- default exact count (cold) ~= `0.129s`
- default exact count (cached) ~= `0.000s`

Canonical sources:

- `docs/DICTIONARY_COLD_AUDIT_2026-03-12.md`
- `build/logs/cold_audit/dictionary/dictionary_cold_audit_summary.json`

Engineering meaning:

- this branch is about search correctness / parity-health;
- it is not a Dictionary first-paint reopen.

## Repair scope

Code changes:

- `app/infra/fts_manager.py`
- `scripts/repair_lemma_fts.py`
- `tests/test_repair_lemma_fts.py`

Docs:

- `docs/DICTIONARY_LEMMA_FTS_REPAIR_2026-03-14.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`
- `docs/FTS_SCHEMA_REPAIR.md`

## What was added

### 1. Explicit parity inspection

New bounded health probe in `app/infra/fts_manager.py`:

- `inspect_lemma_fts_parity(conn, schema="main")`

It checks:

- whether `lemma_fts` exists;
- whether `trg_lemma_fts_*` triggers exist;
- `lemma` vs `lemma_fts` row counts;
- missing rowids in `lemma_fts`;
- extra rowids in `lemma_fts`;
- sample mismatched IDs for bounded diagnostics.

### 2. Controlled rebuild path

New bounded repair helper in `app/infra/fts_manager.py`:

- `rebuild_lemma_fts(conn, schema="main")`

It does:

- drop old `lemma_fts` triggers;
- drop old `lemma_fts`;
- recreate canonical external-content `lemma_fts`;
- rebuild from `lemma`;
- run post-repair parity verification before commit.

This intentionally stays an **explicit** repair path, not a startup self-heal.

### 3. Canonical operator script

New script:

- `python scripts/repair_lemma_fts.py --db-path "<db>"`

Supported modes:

- inspect-only: `--dry-run`
- repair without backup: `--no-backup`
- verbose logging: `--verbose`

The script writes JSON summary reports under:

- `build/logs/lemma_fts_repair_*.json`

## Before/after repair evidence

Approved-target evidence already showed the live issue:

- `lemma` rows = `2,071,947`
- `lemma_fts` rows = `2,076,909`
- extra `lemma_fts` rows = `4,962`
- 12-term parity sample:
  - `LIKE` non-zero for `12 / 12`
  - service search non-zero for `0 / 12`
  - `lemma_id IN (SELECT rowid FROM lemma_fts MATCH ...)` non-zero for `0 / 12`

This repair branch adds bounded synthetic before/after evidence for the repair
path itself:

- broken table before repair:
  - `healthy = false`
  - `missing_in_fts_count = 1`
  - `extra_in_fts_count = 1`
  - `service search = 0`
  - `LIKE = 1`
  - raw `lemma_fts MATCH = 1`
- after canonical rebuild:
  - `status = REPAIRED`
  - `healthy = true`
  - `missing_in_fts_count = 0`
  - `extra_in_fts_count = 0`
  - `service search = 1`

Engineering meaning:

- the repo now has a bounded, regression-locked way to restore Dictionary
  search parity when `lemma_fts` drift is the cause;
- this is a meaningful closure path for the branch, not just continued deferral.

## Current status

Current classification after this repair branch:

- Dictionary cold-open path: closed
- Dictionary `lemma_fts` parity branch: bounded repair path implemented
- generic cold-hunt continuation: not justified

What remains outside this patch:

- whether and when to apply the repair tool to a specific unhealthy operator DB;
- whether any future runtime fallback should exist when parity is known
  unhealthy.

Neither of those requires reopening generic cold-audit work.
