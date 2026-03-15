# Dictionary Search Correctness Rollout (2026-03-15)

## Why this document exists

This note records the first product-facing rollout step after:

- `docs/DICTIONARY_LEMMA_FTS_DECISION_2026-03-14.md`
- `docs/DICTIONARY_LEMMA_FTS_REPAIR_2026-03-14.md`
- `docs/RELEASE_SHIP_GATE_PHASE1_2026-03-15.md`

Its scope is intentionally narrow:

- keep Dictionary cold-open classification honest;
- preserve the explicit offline `lemma_fts` repair path;
- prevent false-negative Dictionary search results when `lemma_fts` parity is
  known unhealthy at runtime.

This rollout does **not**:

- reopen Dictionary cold-open work;
- add a silent startup rebuild of `lemma_fts`;
- widen into a broader search semantics redesign;
- replace the canonical offline repair flow.

## Objective Dictionary open measurement

Dictionary open remains objectively **not** a cold blocker from canonical
approved-target evidence:

- default first page ~= `0.003s`
- default exact count (cold) ~= `0.129s`
- default exact count (cached) ~= `0.000s`

Canonical sources:

- `docs/DICTIONARY_COLD_AUDIT_2026-03-12.md`
- `build/logs/cold_audit/dictionary/dictionary_cold_audit_summary.json`

Engineering meaning:

- this wave is about search trust and result correctness;
- it is not a first-paint reopen.

## Runtime rollout scope

Code changes:

- `app/services/dictionary_service.py`
- `tests/test_perf_lemma_fts.py`

Docs:

- `docs/DICTIONARY_SEARCH_CORRECTNESS_ROLLOUT_2026-03-15.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

## What changed

### 1. Runtime search no longer blindly trusts `lemma_fts` existence

`DictionaryService` previously switched to the FTS path whenever the
`lemma_fts` table existed.

That was insufficient because the user-visible search contract depends on
rowid parity:

- `lemma.rowid == lemma.lemma_id`
- `lemma_fts.rowid == lemma.lemma_id`

The new runtime behavior is:

- if `lemma_fts` is missing: use existing `LIKE` fallback;
- if `lemma_fts` exists and parity is healthy: keep using FTS;
- if `lemma_fts` exists but parity is unhealthy: log one bounded warning and
  fall back to `LIKE`.

### 2. Runtime parity checks are cached

The service now caches `lemma_fts` parity-health per DB path for a short TTL.

Engineering intent:

- prevent repeated heavy parity probes on every search/count call;
- keep the fallback deterministic during the current interaction window;
- clear health state together with the existing Dictionary count cache when
  invalidation is requested.

### 3. Operator repair path stays explicit

This rollout does **not** repair `lemma_fts` silently.

When runtime drift is detected, the warning points to the canonical operator
repair command:

`python scripts/repair_lemma_fts.py --db-path "<db-path>"`

That keeps the branch bounded:

- runtime path protects search trust;
- offline tool remains the canonical restore path.

## Regression evidence

New bounded automated evidence now covers:

- broken `lemma_fts` parity with existing table present:
  - Dictionary search returns matching rows via `LIKE` fallback;
  - Dictionary count stays correct for the same search term;
- repeated search/count on the same DB:
  - parity inspection is cached and not re-run on every call.

This is intentionally narrower than a full search semantics redesign.

## Current status after rollout

Current classification:

- Dictionary cold-open path: closed
- Dictionary offline `lemma_fts` repair path: implemented
- Dictionary runtime trust issue from parity drift: mitigated

What still remains outside this patch:

- applying `repair_lemma_fts.py` to a specific unhealthy operator DB when
  needed;
- any future redesign of Dictionary search semantics beyond the current
  `FTS-or-LIKE` bounded contract.
