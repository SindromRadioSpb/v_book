# Dictionary lemma_fts Parity Decision (2026-03-14)

## Why this document exists

This note is a **decision-gated follow-up** to:

- `docs/DICTIONARY_COLD_AUDIT_2026-03-12.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

It is intentionally **not** a new broad cold-audit wave.

Its scope is narrow:

- confirm whether Dictionary search / `lemma_fts` parity-health is still a real
  remaining branch;
- confirm whether the current repo already contains a safe repair path;
- decide whether this branch deserves future work or should be explicitly held.

This note does **not**:

- change runtime behavior;
- rebuild `lemma_fts`;
- open a runtime patch branch automatically;
- reopen generic `P3` cold sweeps.

## Canonical sources used

This decision uses only existing repo sources and current code inspection:

- `docs/DICTIONARY_COLD_AUDIT_2026-03-12.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`
- `build/logs/cold_audit/dictionary/dictionary_cold_audit_summary.json`
- `build/logs/cold_audit/dictionary/dictionary_fts_drift_probe.json`
- `build/logs/cold_audit/dictionary/dictionary_search_parity_sample.json`
- `app/services/dictionary_service.py`
- `app/infra/fts_manager.py`
- `scripts/repair_fts_schema.py`
- `docs/FTS_SCHEMA_REPAIR.md`

## Confirmed current state

### 1. Dictionary default cold path is already closed

From the canonical cold-audit evidence:

- default first page ~= `0.003s`
- default exact count (cold) ~= `0.129s`
- default exact count (cached) ~= `0.000s`

This remains a closed branch. The current issue is **not** Dictionary open-time.

### 2. Dictionary search contract is still unhealthy on the approved target

From the recorded parity artifacts:

- `lemma` rows = `2,071,947`
- `lemma_fts` rows = `2,076,909`
- extra `lemma_fts` rows = `4,962`

In the recorded 12-term approved-target parity sample:

- `LIKE` was non-zero for `12 / 12` terms
- service search was non-zero for `0 / 12` terms
- `lemma_id IN (SELECT rowid FROM lemma_fts MATCH ...)` was non-zero for
  `0 / 12` terms

Representative recorded drift:

- `lemma_id=12` exists
- `lemma_fts rowid=12` also exists
- the matching FTS hit for the same lemma text was recorded at
  `rowid=2074089`, not `12`

Engineering meaning:

- the current approved-target issue is a **user-facing search correctness /
  health problem**, not just a latency tail;
- a clean performance-only Dictionary patch is still not justified.

## Confirmed current repo repair surface

### 1. Runtime search path assumes rowid parity

`app/services/dictionary_service.py` currently routes search through:

- `lemma.lemma_id IN (SELECT rowid FROM lemma_fts WHERE lemma_fts MATCH ...)`

That path is only valid when `lemma_fts.rowid == lemma.lemma_id` parity is
healthy.

### 2. Startup/self-heal logic does not repair parity drift

`app/infra/fts_manager.py` currently provides:

- `ensure_lemma_fts_health(conn, schema="main", rebuild=False)`

Confirmed behavior:

- creates `lemma_fts` + sync triggers if missing;
- with `rebuild=True`, rebuilds only when the FTS table is empty;
- if `lemma_fts` already contains rows, it reports the table as populated and
  skips rebuild.

Engineering meaning:

- current startup health logic is **presence/population-oriented**;
- it does **not** detect or repair the already-recorded approved-target parity
  drift case where rows exist but rowids are misaligned.

### 3. Existing repair tooling does not cover lemma_fts

`scripts/repair_fts_schema.py` and `docs/FTS_SCHEMA_REPAIR.md` currently cover:

- `sentence_fts`
- `term_fts`

They do **not** cover:

- `lemma_fts`
- `lemma` vs `lemma_fts` rowid parity validation
- deterministic `lemma_fts` parity rebuild / repair

Engineering meaning:

- the repo does **not** currently contain a canonical offline repair path for
  the Dictionary parity issue.

## Decision

Current classification:

- `status`: `decision-gated`
- `priority`: `P1`
- `real candidate for more work`: yes
- `open runtime patch now`: no

Decision logic:

- this branch remains real because the issue is user-facing search correctness,
  not merely cosmetic performance residue;
- however, the current repo does not yet show a bounded, already-proven repair
  path;
- opening a runtime patch immediately would widen scope into:
  - search correctness,
  - FTS parity validation,
  - repair semantics,
  - and possibly offline/operator tooling.

## What future work would be justified

If this branch is chosen later, the acceptable next step is **one bounded
Dictionary parity-health branch only**.

That future branch should focus on just three questions:

1. how to detect `lemma` vs `lemma_fts` parity drift deterministically;
2. whether the safe fix is an explicit offline repair path, not a startup
   silent self-heal;
3. whether Dictionary search should temporarily bypass the FTS path when parity
   is known unhealthy.

## What should not happen next

Do **not** treat this as:

- a generic new cold-hunt wave;
- a Dictionary first-paint reopen;
- an automatic performance-only patch;
- a reason to resume generic `P3` sweeps.

Do **not** widen this branch into:

- broader FTS refactors,
- unrelated search semantics redesign,
- or heavy validation by default.

## Reopen gate

Open a future Dictionary follow-up branch only if all of the following are
true:

- Dictionary search correctness is important enough to prioritize now;
- the branch is explicitly scoped as `lemma_fts parity-health`, not generic
  Dictionary cold work;
- the proposed fix stays bounded to detection + repair-path choice + narrow
  search-path handling.

Until then:

- keep Dictionary default cold work closed;
- keep this branch decision-gated;
- do not open more generic cold-audit waves from this topic.
