# Task 19: Global TM Design - Architecture & Invariants

## Overview

`tm_global` is the canonical cross-project translation layer introduced in Task 19. Every `tm_entry` links to a `tm_global` row via `tm_global_id` FK. Changes to translations/noise propagate across all projects automatically.

## Problem Solved

**Before Task 19:**
- Translations were project-scoped (`tm_entry` with `project_id`)
- Lemma "שווה" translated in Project 4 did NOT appear in Project 7/8
- Users had to manually re-translate identical terms in every project
- Task 18 fixed duplication *within* a single project, but cross-project sync was missing

**After Task 19:**
- Single canonical `tm_global` row per unique key
- All `tm_entry` rows link to `tm_global` via `tm_global_id`
- Editing translation in any project updates `tm_global` → propagates to all projects
- New projects automatically inherit existing translations via backfill

---

## Schema

### tm_global Table

```sql
CREATE TABLE tm_global (
    tm_global_id  INTEGER PRIMARY KEY,
    src_lang      TEXT NOT NULL,
    tgt_lang      TEXT NOT NULL,
    kind          TEXT NOT NULL,  -- lemma|ngram|term_cluster|surface
    src_norm      TEXT NOT NULL,
    src_text      TEXT NOT NULL,
    translation   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',
    origin        TEXT NOT NULL DEFAULT 'mt_auto',
    confidence    REAL,
    is_noise      INTEGER DEFAULT 0,
    noise_reason  TEXT,
    notes         TEXT,
    source_tm_id  INTEGER,  -- tm_entry.tm_id that won the merge
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CONSTRAINT uq_tm_global UNIQUE (src_lang, tgt_lang, kind, src_norm)
);
```

**Canonical Key**: `(src_lang, tgt_lang, kind, src_norm)`

- `src_norm` is computed via `normalize_for_tm(src_lang, src_text, kind)`
- UNIQUE constraint ensures one row per key
- `source_tm_id`: tracks which tm_entry "won" during backfill (for debugging)

### tm_entry Link

```sql
ALTER TABLE tm_entry ADD COLUMN tm_global_id INTEGER REFERENCES tm_global(tm_global_id) ON DELETE SET NULL;
```

- Every `tm_entry` points to its canonical `tm_global` row
- Multiple `tm_entry` rows (across projects) can share the same `tm_global_id`
- `tm_entry.translation` remains authoritative for UI (backwards compatible)

---

## Normalization

**Key Computation**: Always via `normalize_for_tm()`

```python
from app.domain.normalization.normalizer import normalize_for_tm

normalized = normalize_for_tm(src_lang="he", text="שווה", kind="lemma")
src_norm = normalized.norm  # Used as tm_global.src_norm
```

**Consistency Rule**: ALL write paths MUST use `normalize_for_tm()` to compute `src_norm`. Raw text is NOT allowed (known bug in V2 engine `_write_lemma` is documented but not fixed).

---

## Scoring Algorithm (Deterministic Conflict Resolution)

When multiple `tm_entry` rows map to the same `tm_global` key, the "best" entry is chosen deterministically:

**Priority (highest to lowest):**
1. `translation` non-empty > empty
2. `status`: approved (4) > draft (3) > deprecated (2) > rejected (1)
3. `origin`: user_edit (5) > import (4) > mt_accept (3) > merge (2) > mt_auto (1) > revert (0)
4. `updated_at` DESC (most recent wins)
5. `tm_id` ASC (lowest ID = oldest = canonical tiebreaker)

**Example:**
- Entry A: `status=approved, origin=user_edit, translation="User"`
- Entry B: `status=draft, origin=mt_auto, translation="MT"`
- **Winner**: Entry A (approved+user_edit beats draft+mt_auto)

**Implementation**: `TMGlobalService.score_candidate(entry) -> tuple`

---

## Noise Policy

`tm_global.is_noise = 1` **only if ALL** linked `tm_entry` rows have `is_noise=1`.

**Rationale**: If any project considers a term valid, the global canonical should be valid. Noise is opt-in per project, not enforced globally.

**Example:**
- Project 4: `tm_entry.is_noise=1` (marked as noise)
- Project 7: `tm_entry.is_noise=0` (valid term)
- **Result**: `tm_global.is_noise=0` (global canonical is valid)

---

## Write-Path Integration (12 Points)

Every write path that creates/updates `tm_entry` now maintains `tm_global`:

**Pattern (used in all 12 points):**
```python
from app.services.tm_global_service import TMGlobalService

# After creating/updating tm_entry:
session.flush()  # Ensure tm_id is assigned
TMGlobalService().upsert_and_link(session, tm_entry)
session.commit()
```

**Integration Points:**
1. `batch_mt_translate_service.py:_write_lemma()`
2. `batch_mt_translate_service.py:_write_term_cluster()`
3. `batch_mt_translate_service.py:_write_tm_entry()`
4. `dictionary_view.py:on_translation_edited()`
5. `terms_view.py:on_translation_edited()`
6. `translation_admin_service.py:update_translation()`
7. `translation_admin_service.py:set_status()`
8. `translation_admin_service.py:bulk_set_status()`
9. `translation_admin_service.py:revert()`
10. `translation_admin_service.py:set_noise_status_bulk()`
11. `batch_translate_engine_v2.py:_write_lemma()` (NOTE: has known normalization bug)
12. `batch_translate_engine_v2.py:_write_term_cluster()`

---

## Read-Path Fallback

`translation_service.py` now falls back to `tm_global` if no project-scoped `tm_entry` exists:

**Precedence (in `_lookup_tm()`):**
1. Project-scoped `tm_entry` (project_id = X)
2. Global `tm_entry` (project_id IS NULL) - legacy
3. **NEW**: `tm_global` canonical layer (cross-project)

This enables new projects to inherit translations without manually running MT.

---

## Backfill Process

**Purpose**: One-time migration of existing `tm_entry` data into `tm_global`.

**Script**: `scripts/backfill_tm_global.py`

**Algorithm:**
1. Group all `tm_entry` by canonical key `(src_lang, tgt_lang, kind, src_norm)`
2. For each group:
   - Score all entries via `score_candidate()`
   - Select best entry (highest score)
   - Determine global noise: `is_noise=1` only if ALL entries are noise
   - Upsert into `tm_global` with best entry's fields
   - Set `tm_entry.tm_global_id` for all entries in group
3. Commit in chunks (default 500 keys/chunk)

**Idempotency**: Safe to run multiple times (UNIQUE constraint prevents duplicates, existing links are skipped).

**Auto-backfill**: `db.py` automatically runs backfill on startup if `tm_global` is empty and `tm_entry` has data.

---

## Invariants (CRITICAL)

1. **Unique key**: `(src_lang, tgt_lang, kind, src_norm)` in `tm_global` is UNIQUE
2. **Normalization**: `src_norm` is ALWAYS computed via `normalize_for_tm()` (except V2 engine bug)
3. **Linked entries**: If `tm_entry.tm_global_id IS NOT NULL`, the referenced `tm_global` row MUST exist
4. **Consistency**: `tm_entry.translation` should match `tm_global.translation` for linked entries (enforced via `propagate_to_entries()`)
5. **Backwards compatibility**: `tm_entry.translation` remains authoritative for UI (read-path still works if `tm_global` missing)

---

## Recovery Scenarios

### Scenario 1: tm_global desync (translation mismatch)

**Symptom**: `tm_entry.translation` ≠ `tm_global.translation` for linked entries

**Fix**: Run propagation
```python
from app.services.tm_global_service import TMGlobalService
service = TMGlobalService()
# For specific tm_global:
service.propagate_to_entries(session, tm_global_id=123, fields=["translation"])
# Or re-run backfill (will re-score and update):
service.backfill(session, chunk_size=500, dry_run=False)
```

### Scenario 2: tm_entry.tm_global_id IS NULL (unlinked)

**Symptom**: Some tm_entry rows have no `tm_global_id`

**Fix**: Run backfill
```bash
python scripts/backfill_tm_global.py
```

### Scenario 3: Duplicate tm_global rows (UNIQUE constraint violated)

**Symptom**: UNIQUE constraint error during upsert

**Root Cause**: Normalization bug or manual SQL manipulation

**Fix**: Delete duplicate, keep canonical (highest score), then re-link entries
```sql
-- Find duplicates
SELECT src_lang, tgt_lang, kind, src_norm, COUNT(*)
FROM tm_global
GROUP BY src_lang, tgt_lang, kind, src_norm
HAVING COUNT(*) > 1;

-- Manually delete lower-scored duplicate, then run backfill
```

---

## Performance Considerations

### Write-Path Overhead

**Added cost per write:**
1. `session.flush()` - ~0.1ms (assigns tm_id)
2. `upsert_global()` - ~1-5ms (SELECT + INSERT/UPDATE)
3. `entry.tm_global_id = g.tm_global_id` - ~0.1ms

**Total**: ~1-5ms per tm_entry write (negligible for single edits, measurable for batch operations)

**Mitigation**: Batch operations already chunked (50-500 rows/commit), so overhead is amortized.

### Backfill Scale

**Test data**: ~10,000 tm_entry rows → ~3,000 tm_global rows (3:1 ratio typical)

**Backfill time**: ~5-15 seconds (500 keys/chunk, ~6,000 keys total)

**Startup impact**: Auto-backfill only runs ONCE (on first startup after migration 015)

---

## Known Limitations

### V2 Engine Normalization Bug

**File**: `batch_translate_engine_v2.py:490`

**Bug**: `src_norm = item.source_text` (raw text, no normalization)

**Impact**: V2 engine creates tm_global entries with un-normalized `src_norm` for lemmas. This breaks cross-project sharing (different normalization → different keys).

**Status**: Documented but NOT fixed in Task 19 (out of scope). Fix in separate task.

**Workaround**: Use `batch_mt_translate_service.py` (not V2) for critical operations.

---

## Future Enhancements (Out of Scope)

1. **Domain-aware TM**: Add `domain_id` to `tm_global` for library/subject-specific translations
2. **Confidence-based scoring**: Prefer high-confidence MT over low-confidence user_edit
3. **Translation voting**: Multi-user collaborative translation with vote counts
4. **TM Panel "Global View"**: UI toggle to show `tm_global` rows instead of `tm_entry`
5. **Cross-language TM**: Share translations across language pairs (e.g., he→ru + he→en)

---

## References

- **Task file**: `task_19.md`
- **Implementation summary**: `docs/TASK19_IMPLEMENTATION_SUMMARY.md`
- **Backfill guide**: `docs/TASK19_GLOBAL_TM_BACKFILL.md`
- **Service code**: `app/services/tm_global_service.py`
- **Tests**: `tests/test_task19_tm_global.py`
