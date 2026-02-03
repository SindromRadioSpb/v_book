# Bug Fix: Terms Tab Translation Persistence After Refresh

## Symptom

User scenario:
1. Terms → Extract Terms → table appears
2. User enters translation inline (e.g., "Книга большая" for Term "ספר גדול")
3. Status changes from None to Approved in UI
4. User clicks Refresh → **Translation disappears, status returns to None**

Dictionary tab works correctly - inline edits persist after refresh.

## Root Cause Analysis

**Key mismatch in TermClusterTableModel.update_translations()**

### The Bug (app/ui/models_qt.py:308)

```python
# WRONG: Model searches for results by canonical_key
key = (cluster.canonical_key, "term_cluster")
if key in results:
    ...
```

### What Worker Returns (app/services/translation_service.py:404)

```python
# Worker returns results keyed by original src_text (representative_he)
results[item] = tm_result  # where item = (representative_he, "term_cluster")
```

### The Mismatch

- **Worker sends**: `{(representative_he, "term_cluster"): TranslationResult}`
- **Model searches**: `(canonical_key, "term_cluster")`
- **canonical_key ≠ representative_he** → Results NOT FOUND → Translation disappears!

### Example

Given cluster:
- `representative_he = "ספר גדול"` (surface form)
- `canonical_key = "ספר_גדול"` (normalized with underscores)

After Refresh:
1. Worker returns: `{"ספר גדול": TranslationResult(translation="Книга большая")}`
2. Model searches for: `"ספר_גדול"` → **NOT FOUND**
3. Translation cell becomes empty

## The Fix

**File**: app/ui/models_qt.py:308

**Before**:
```python
key = (cluster.canonical_key, "term_cluster")
```

**After**:
```python
key = (cluster.representative_he, "term_cluster")
```

**Rationale**: Match what TranslationResolveWorker uses as keys.

## Save Path Analysis (Confirmed Working)

app/ui/terms_view.py:418-452 - **CORRECT**:
- Normalizes `representative_he` → `src_norm`
- Saves TMEntry with `project_id=self.project_id`
- Commits transaction
- No issues found

## Load Path Analysis (Fixed)

app/ui/terms_view.py:345 - **CORRECT**:
- Sends `representative_he` to worker

app/ui/models_qt.py:308 - **FIXED**:
- Now uses `representative_he` to match worker results

## Verification

### Regression Test
`test_terms_persistence.py` - Reproduces bug and verifies fix:
1. Create term cluster in DB
2. Simulate inline edit via TermsView
3. Verify TM entry saved with correct fields
4. Simulate Refresh (reload translations)
5. Assert translation persists (FAILS before fix, PASSES after)

### Manual Test
1. Open Terms tab
2. Extract Terms
3. Enter translation inline
4. Click Refresh
5. ✅ Translation should remain visible with status="approved"

## Related Files Changed

- `app/ui/models_qt.py` - Fixed key lookup
- `test_terms_persistence.py` - New regression test
- `BUGFIX_TERMS_PERSISTENCE.md` - This document

## Impact

- **Before**: All inline TM edits in Terms tab lost after Refresh
- **After**: Edits persist correctly (same behavior as Dictionary tab)
- **Scope**: Terms tab only (Dictionary tab was already correct)
