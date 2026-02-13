# Task 18: Fix tm_entry Duplication - Pre-Flight Report

## Executive Summary

**Problem**: Duplicate tm_entry records for same lemma in same project:
- Record 1: origin=user_edit, translation="" (empty)
- Record 2: origin=mt_auto, translation="Равный" (filled)
- Dictionary UI shows empty translation despite successful MT

**Root Cause**: **Normalization mismatch** in `batch_mt_translate_service.py:458`
- User inline edit uses `normalize_for_tm()` → `src_norm = "שווה_normalized"`
- MT batch translate uses RAW text → `src_norm = "שווה"`
- UNIQUE constraint doesn't trigger because values are different
- Result: 2 records bypass the constraint

---

## Deep Dive: Code Analysis

### 1. HOW DICTIONARY READS TRANSLATION

**File**: `app/ui/dictionary_view.py:413-440`

Dictionary uses `TranslationResolveWorker` → `TranslationService.bulk_resolve()`

**File**: `app/services/translation_service.py:148-234`

```python
def _lookup_tm(self, session, item):
    # ... search in tm_entry ...
    stmt = select(TMEntry).where(...).order_by(
        TMEntry.status.desc(),  # approved > draft
        TMEntry.updated_at.desc(),  # most recent first
    ).limit(1)
```

**Precedence**: `status (approved)` > `updated_at (most recent)`

**Problem**: When duplicates exist, returns first match by precedence. If empty `user_edit` was updated more recently than filled `mt_auto`, shows empty translation.

---

### 2. HOW MT WRITES TO tm_entry (BUGGY)

**File**: `app/services/batch_mt_translate_service.py:450-497`

```python
def _write_lemma(self, session, item, translation):
    # 🔥 BUG: Line 458 - NO NORMALIZATION!
    src_norm = item.source_text  # RAW TEXT!

    stmt = select(TMEntry).where(
        TMEntry.project_id == item.project_id,
        TMEntry.kind == "lemma",
        TMEntry.src_norm == src_norm,  # searches for RAW text
    )
    existing = session.execute(stmt).scalar()

    if existing:
        # Update existing
        existing.origin = "mt_auto"
    else:
        # Create new - this bypasses UNIQUE constraint!
        tm_entry = TMEntry(
            src_norm=src_norm,  # stores RAW text
            origin="mt_auto",
        )
        session.add(tm_entry)
```

**Bug**: Uses `src_norm = item.source_text` WITHOUT `normalize_for_tm()`

---

### 3. HOW USER EDIT CREATES tm_entry (CORRECT)

**File**: `app/ui/dictionary_view.py:463-534`

```python
def on_translation_edited(self, ...):
    # ✅ CORRECT: Uses normalize_for_tm()
    normalized = normalize_for_tm("he", lemma.lemma_text, "lemma")

    stmt = select(TMEntry).where(
        TMEntry.project_id == self.project_id,
        TMEntry.kind == "lemma",
        TMEntry.src_norm == normalized.norm,  # normalized value
    )
    existing = session.execute(stmt).scalar()

    if existing:
        existing.origin = "user_edit"
    else:
        tm_entry = TMEntry(
            src_norm=normalized.norm,  # stores normalized
            origin="user_edit",
        )
        session.add(tm_entry)
```

**Correct**: Uses `normalize_for_tm()` to compute `src_norm`

---

### 4. tm_entry SCHEMA CONSTRAINTS

**File**: `app/infra/migrations/006_m7_translation_memory.sql:38`

```sql
UNIQUE (project_id, kind, src_lang, tgt_lang, src_norm)
```

**File**: `app/infra/sa_models.py:598`

```python
UniqueConstraint("project_id", "kind", "src_lang", "tgt_lang", "src_norm", name="uq_tm_entry")
```

**Analysis**: UNIQUE constraint is correctly defined, but only prevents duplicates with **identical src_norm values**. Since two code paths produce different values, constraint doesn't trigger.

---

## Reproduction Scenario

### Step-by-Step:

1. **User creates empty translation** (inline edit in Dictionary):
   - Creates tm_entry: `src_norm = "שווה_normalized"`, `origin=user_edit`, `translation=""`

2. **User runs batch MT translate**:
   - `batch_mt_translate_service.py` searches for `src_norm = "שווה"` (RAW)
   - Doesn't find existing (because "שווה" != "שווה_normalized")
   - Creates NEW tm_entry: `src_norm = "שווה"`, `origin=mt_auto`, `translation="Равный"`

3. **UNIQUE constraint check**:
   - Tuple 1: `(project_id, 'lemma', 'he', 'ru', 'שווה_normalized')` ✅
   - Tuple 2: `(project_id, 'lemma', 'he', 'ru', 'שווה')` ✅
   - Different tuples → both allowed!

4. **Dictionary reload**:
   - Searches for `src_norm = "שווה_normalized"` (normalized)
   - Finds user_edit record (empty)
   - `mt_auto` record with "Равный" is orphaned (different src_norm key)

---

## Verification SQL

```sql
SELECT tm_id, src_text, src_norm, translation, origin, status, updated_at
FROM tm_entry
WHERE project_id = 8
  AND kind = 'lemma'
  AND src_text LIKE '%שווה%'
ORDER BY updated_at DESC;
```

**Expected findings**:
- 2 records with same `src_text = "שווה"`
- Different `src_norm` values (normalized vs raw)
- One with `origin='user_edit'`, `translation=''`
- One with `origin='mt_auto'`, `translation='Равный'`

---

## Affected Code Paths

### Dictionary (Lemma) - BUGGY
- ❌ `batch_mt_translate_service.py:458` - `_write_lemma()` uses RAW text
- ✅ `dictionary_view.py:484` - inline edit uses `normalize_for_tm()`

### Terms (Cluster) - CORRECT
- ✅ `batch_mt_translate_service.py:507` - `_write_term_cluster()` uses `normalize_for_tm()`
- ✅ `terms_view.py` - inline edit uses `normalize_for_tm()`

**Conclusion**: Bug affects **Dictionary (lemma) only**, Terms already correct!

---

## Solution Strategy

### PATCH-01: Fix Normalization in _write_lemma() ✅ P0

**File**: `app/services/batch_mt_translate_service.py:458`

**Replace**:
```python
src_norm = item.source_text
```

**With**:
```python
from app.domain.normalization import normalize_for_tm
normalized = normalize_for_tm(item.src_lang, item.source_text, "lemma")
src_norm = normalized.norm
```

**Impact**: MT batch translate will now use same normalization as inline edit → finds existing record → updates instead of creating duplicate

---

### PATCH-02: Data Migration - Deduplicate Existing Records ✅ P0

**Create**: `app/infra/migrations/015_dedupe_tm_entry.sql` or Python migration script

**Algorithm**:
1. Find groups of duplicates: `GROUP BY (project_id, kind, src_text)` with `COUNT(*) > 1`
2. For each group:
   - Select canonical record (priority: non-empty translation > user_edit > most recent)
   - Merge data (translation, status) into canonical
   - Re-normalize canonical record's `src_norm` using `normalize_for_tm()`
   - Delete other records
3. Report: "Merged X groups, deleted Y records"

---

### PATCH-03: Add Unique Index on entity_id ⚠️ P1 (Optional)

**Consideration**: Add unique constraint on `(project_id, kind, lemma_id)` WHERE `lemma_id IS NOT NULL`

**Analysis**:
- **Pro**: Prevents duplicates even if normalization fails
- **Con**: May conflict with existing data/code paths
- **Recommendation**: Do after PATCH-01/02 and testing

---

## Impact Assessment

### Regression Risk: LOW
- Change is localized to one method (`_write_lemma`)
- `_write_term_cluster` already uses correct normalization (no change needed)
- Normalization function is well-tested (used in many places)

### Affected Features:
- ✅ Dictionary batch translate (will now update existing instead of creating duplicate)
- ✅ Dictionary inline edit (no change, already correct)
- ✅ Terms batch translate (no change, already correct)
- ✅ Translation Management panel (will show single record after deduplication)

### Triggers (Task 13/14):
- ✅ Noise sync triggers use `lemma_id/cluster_id`, not `src_norm` → unaffected
- ✅ Triggers will update all records with same `lemma_id` (even if duplicates exist before deduplication)

---

## Files to Modify

| Priority | File | Change | Lines |
|----------|------|--------|-------|
| P0 | `app/services/batch_mt_translate_service.py` | Add normalize_for_tm in _write_lemma | ~5 |
| P0 | `app/infra/migrations/015_dedupe_tm_entry.py` | NEW migration script | ~100 |
| P1 | `tests/test_tm_entry_canonicalization.py` | NEW test file | ~150 |

**Total**: ~255 lines added/modified

---

## Next Steps

1. ✅ **Pre-flight complete** - root cause identified
2. **PATCH-01**: Fix normalization in `_write_lemma()`
3. **PATCH-02**: Create deduplication migration
4. **PATCH-03**: Add tests
5. **Manual smoke**: Test on Project 8 (שווה lemma)

---

## References

- **Task file**: `task_18.md`
- **Exploration agent**: `a7e41e3` (detailed findings)
- **Buggy method**: `batch_mt_translate_service.py:450-497` (_write_lemma)
- **Correct method**: `batch_mt_translate_service.py:505-555` (_write_term_cluster)
- **Normalization**: `app/domain/normalization.py` (normalize_for_tm function)
