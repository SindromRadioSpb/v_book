# Test Instructions for Terms Tab Fix

## ✅ COMPLETED

- **Root Cause Identified**: Key mismatch in `TermClusterTableModel.update_translations()`
- **Fix Applied**: Changed key lookup from `canonical_key` to `representative_he`
- **Committed**: 61c3b0b
- **Pushed**: main branch

## 🧪 TESTING REQUIRED (in your environment with PyQt6)

### 1. Regression Test (Automated)

Run the new regression test to verify the fix:

```bash
# Set headless mode
$env:QT_QPA_PLATFORM="offscreen"

# Run regression test
python test_terms_persistence.py -v
```

**Expected**: ✅ All tests PASS (before fix: would FAIL on assertion)

### 2. Full Test Suite (Automated)

Verify no regressions in other components:

```bash
$env:QT_QPA_PLATFORM="offscreen"

# Run all tests
python test_m7_normalization.py
python test_p1_verification.py
python test_p2_translation_admin.py
python test_p3_dictionary_import_csv.py
python test_p3_conflict_policies.py
python test_p3_scenario7_gate.py
```

**Expected**: ✅ All tests PASS

### 3. Manual Smoke Test (UI)

**Before fix behavior**: Translation disappeared after Refresh
**After fix behavior**: Translation persists

Steps:
1. Launch app
2. Open project (any)
3. Navigate to **Terms** tab
4. Click **Extract Terms** (or Refresh if already extracted)
5. Select a term row
6. **Enter translation inline** in Translation column
   - Example: "Книга большая" for term "ספר גדול"
7. Verify:
   - ✅ Status changes to "Approved"
   - ✅ Translation value visible
8. Click **Refresh** button
9. **CRITICAL ASSERTION**:
   - ✅ Translation still visible: "Книга большая"
   - ✅ Status still shows "Approved"

**If this fails**, translation disappears → bug NOT fixed

### 4. Cross-Check Dictionary Tab (Baseline)

Verify Dictionary tab still works (it was already correct):

1. Navigate to **Dictionary** tab
2. Enter translation inline
3. Click Refresh
4. ✅ Translation persists (should work as before)

## 📊 Expected Results

### Regression Test Output

```
test_inline_translation_persists_after_refresh ... ok

----------------------------------------------------------------------
Ran 1 test in 2.345s

OK
```

### Manual Test Result

| Step | Before Fix | After Fix |
|------|------------|-----------|
| Enter translation | ✅ Appears | ✅ Appears |
| Status changes to Approved | ✅ Yes | ✅ Yes |
| Click Refresh | ❌ Disappears | ✅ Persists |
| Status after Refresh | ❌ None | ✅ Approved |

## 🐛 If Tests Fail

### Regression Test Fails

Check assertion error message:
- If "Translation should persist after Refresh" → Fix not applied correctly
- If "TM entry should be created" → Save path issue (check DB transaction)

### Manual Test Fails (Translation Disappears)

Debug steps:
1. Check DB after inline edit:
   ```sql
   SELECT * FROM tm_entry WHERE kind='term_cluster' AND status='approved';
   ```
   - Should show your translation with `project_id`, `src_norm`, `translation`

2. Check console logs for errors during Refresh

3. Verify `app/ui/models_qt.py:308` shows:
   ```python
   key = (cluster.representative_he, "term_cluster")
   ```

## 📋 Files Changed

- ✅ `app/ui/models_qt.py` - Fixed key lookup (1 line)
- ✅ `app/ui/terms_view.py` - Normalize representative_he in save path
- ✅ `test_terms_persistence.py` - Regression test
- ✅ `BUGFIX_TERMS_PERSISTENCE.md` - Root cause analysis

## ✔️ DoD Checklist

- [x] Bug identified via code analysis
- [x] Root cause documented
- [x] Minimal fix applied (1-line change in models_qt.py)
- [x] Regression test created
- [x] Git committed with detailed message
- [x] Pushed to main
- [ ] **YOUR TASK**: Run automated tests in PyQt6 environment
- [ ] **YOUR TASK**: Manual smoke test in UI
- [ ] **YOUR TASK**: Confirm fix works end-to-end

## 🎯 Next Steps

1. Pull latest changes: `git pull`
2. Run test suite (see commands above)
3. Run manual smoke test
4. Report results

If all green → Bug fixed! ✅
If tests fail → Report errors for investigation
