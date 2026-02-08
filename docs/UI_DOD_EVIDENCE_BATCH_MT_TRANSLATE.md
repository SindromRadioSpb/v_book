# UI DoD Evidence: Batch MT Translate

**Feature:** Batch MT Translation for Dictionary, Terms, and Translation Management tabs
**Date:** 2026-02-08
**Status:** 🚧 IN PROGRESS (skeleton created in PATCH-UI-BATCH-T00)
**Testing:** Manual + Automated

---

## Feature Summary

**User Story:**
As a user, I want to translate multiple selected rows in Dictionary/Terms/Translation Management tables via MT providers (Local MT + Cloud), so that I can quickly fill or update translations in bulk without manual entry.

**Implemented:**
- ⏭️ Multi-select support (Ctrl/Shift selection, non-contiguous)
- ⏭️ Provider selection dialog (chain or force specific provider)
- ⏭️ Write mode selection (fill empty, overwrite, skip non-empty)
- ⏭️ Background translation (no UI freeze)
- ⏭️ Progress dialog with cancel support
- ⏭️ Per-row error handling (continue on failure)
- ⏭️ Integration into Dictionary tab
- ⏭️ Integration into Terms tab
- ⏭️ Integration into Translation Management tab

---

## Manual Test Scenarios

### Scenario 1: Dictionary - Fill Empty Only (Contiguous Selection)

**Prerequisites:**
- Project with Hebrew lemmas loaded (some with empty translations)
- Local NLLB enabled in Provider Settings
- At least 10 lemmas visible in Dictionary tab

**Steps:**
1. Open a project (Hebrew → Russian)
2. Navigate to Dictionary tab
3. Identify 10 contiguous lemmas with empty translations
4. Select rows 1-10 (click row 1, Shift+click row 10)
5. Click "Translate Selected..." button (or press Ctrl+Shift+M)
6. Verify confirm dialog opens: "Batch Translate Selected Rows"
7. Verify "Selected rows: 10" displayed
8. Select provider mode: "Use provider chain (recommended)" [default]
9. Select write mode: "Fill empty only" [default]
10. Click "Translate" button
11. Observe progress dialog appears: "Translating..."
12. Observe progress bar advances, counts update (Succeeded, Skipped, Failed)
13. Wait for completion (10-20 seconds for 10 rows)
14. Verify result dialog: "Translation completed successfully!"
15. Verify counts: Succeeded = N (rows with empty translations), Skipped = M (rows with existing translations)
16. Close result dialog
17. Verify translations appear in Translation column (Hebrew → Russian)
18. Verify translations saved (refresh tab, verify still present)

**Expected Result:**
- ✅ Confirm dialog shows correct row count
- ✅ Progress dialog visible, not freezing UI
- ✅ Only empty translations filled (existing translations preserved)
- ✅ Translations appear in UI after completion
- ✅ Translations persist after refresh

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 2: Terms - Overwrite Existing (Non-Contiguous Selection)

**Prerequisites:**
- Project with extracted terms (MWE + clustering)
- Local NLLB enabled
- Terms tab showing clusters (some with existing translations)

**Steps:**
1. Open project, navigate to Terms tab
2. Select 5 non-contiguous rows (Ctrl+click rows 2, 5, 8, 12, 15)
3. Verify selection: 5 rows selected (some with existing translations)
4. Right-click → "Translate Selected..." (context menu)
5. Verify confirm dialog: "Selected rows: 5"
6. Select provider mode: "Force provider: local_nllb"
7. Select write mode: "Overwrite existing"
8. Click "Translate"
9. Observe progress dialog
10. Wait for completion
11. Verify result dialog: Succeeded = 5, Skipped = 0, Failed = 0
12. Verify ALL 5 rows now have translations (including previously translated)
13. Verify translations are different from previous (if they had translations before)

**Expected Result:**
- ✅ Non-contiguous selection works (Ctrl+click)
- ✅ Context menu action works
- ✅ Force provider works (uses local_nllb, not chain)
- ✅ Overwrite mode replaces existing translations
- ✅ All 5 rows translated successfully

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 3: Translation Management - Skip Non-Empty

**Prerequisites:**
- TM entries loaded (mix of empty and filled translations)
- Local NLLB enabled

**Steps:**
1. Open Translation Management panel (Premium → Translation Management)
2. Filter: Status = "draft", Translation column empty/filled mix
3. Select 10 rows (mix of empty and filled translations)
4. Click "Translate Selected..." button
5. Verify confirm dialog: "Selected rows: 10"
6. Select provider mode: "Use provider chain"
7. Select write mode: "Skip non-empty (no changes)"
8. Click "Translate"
9. Observe progress
10. Wait for completion
11. Verify result: Succeeded = N (empty rows), Skipped = M (filled rows), Failed = 0
12. Verify only previously empty rows now have translations
13. Verify previously filled rows unchanged

**Expected Result:**
- ✅ TM panel integration works
- ✅ Skip non-empty mode works correctly
- ✅ Only empty translations filled
- ✅ Existing translations preserved

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 4: Cancel Mid-Batch (Graceful Cancel)

**Prerequisites:**
- Large dataset (100+ lemmas/terms)
- Local NLLB enabled (slow enough to allow cancel)

**Steps:**
1. Select 100 rows in Dictionary tab
2. Start batch translate: "Translate Selected..."
3. Write mode: "Fill empty only"
4. Click "Translate"
5. Observe progress dialog appears
6. Wait until progress ~20% (20 rows completed)
7. Click "Cancel" button
8. Observe progress dialog closes
9. Verify result dialog: "Translation cancelled" or partial results shown
10. Verify ~20 rows translated (partial success)
11. Refresh tab
12. Verify translated rows persist (committed)
13. Verify remaining rows untranslated (not corrupted)

**Expected Result:**
- ✅ Cancel button responsive
- ✅ Partial results committed (no rollback of completed chunks)
- ✅ No data corruption
- ✅ UI remains responsive

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 5: Error Handling - Providers Disabled

**Prerequisites:**
- ALL MT providers disabled in Settings

**Steps:**
1. Open Provider Settings (Ctrl+Alt+P)
2. Disable ALL providers (Local NLLB, DeepL, etc.)
3. Save settings
4. Open Dictionary tab, select 5 rows
5. Click "Translate Selected..."
6. Select "Use provider chain"
7. Click "Translate"
8. Observe error dialog appears
9. Verify error message actionable:
   - "MT providers disabled" or "No providers available"
   - "Enable MT providers in Settings"
10. Click OK
11. Verify no crash, no translations written

**Expected Result:**
- ✅ Error dialog appears (not crash)
- ✅ Error message actionable (tells user what to do)
- ✅ No partial writes
- ✅ UI remains responsive

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 6: Error Handling - Model Not Installed

**Prerequisites:**
- Local NLLB enabled in Settings
- Local NLLB model NOT installed (delete model files)

**Steps:**
1. Ensure model not installed: `python scripts/install_local_mt_model.py --list` → empty
2. Open Dictionary tab, select 5 rows
3. Click "Translate Selected..."
4. Select "Force provider: local_nllb"
5. Click "Translate"
6. Observe error dialog appears
7. Verify error message mentions:
   - "Model not installed"
   - Installation command: `python scripts/install_local_mt_model.py ...`
   - Or: "Use cloud providers"
8. Click OK
9. Verify no crash

**Expected Result:**
- ✅ Error message actionable (install command shown)
- ✅ Suggests alternative (use cloud providers)
- ✅ No crash

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 7: Provider Fallback (Chain Mode)

**Prerequisites:**
- Local NLLB disabled OR not installed
- Cloud provider (LibreTranslate) enabled

**Steps:**
1. Disable Local NLLB in Settings
2. Enable LibreTranslate (or DeepL)
3. Open Dictionary tab, select 5 rows
4. Click "Translate Selected..."
5. Select "Use provider chain"
6. Click "Translate"
7. Wait for completion (network delay)
8. Verify result: Succeeded = 5
9. Verify translations appear
10. Check logs (if accessible): verify provider_id = "libretranslate" or "deepl" (NOT local_nllb)

**Expected Result:**
- ✅ Chain fallback works (uses cloud provider)
- ✅ Translations appear
- ✅ Provider metadata correct (not local_nllb)

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 8: Glossary Applied (Approved Terms)

**Prerequisites:**
- Approved term in TM: `database` → `מסד-נתונים-מאושר` (status='approved')
- Lemma/term containing "database" in source text
- Local NLLB enabled

**Setup:**
```sql
-- Run in dev database
INSERT INTO tm_entry (
    source_text, translation, src_lang, tgt_lang,
    status, priority_score, created_at, updated_at
) VALUES (
    'database', 'מסד-נתונים-מאושר', 'en', 'he',
    'approved', 3.0, datetime('now'), datetime('now')
);
```

**Steps:**
1. Open Dictionary tab, find lemma containing "database"
2. Select row
3. Click "Translate Selected..."
4. Write mode: "Overwrite existing"
5. Click "Translate"
6. Wait for completion
7. Verify translation contains approved term `מסד-נתונים-מאושר` (not default NLLB)
8. Check logs (if accessible): verify `used_glossary: true`

**Cleanup:**
```sql
DELETE FROM tm_entry WHERE translation = 'מסד-נתונים-מאושר';
```

**Expected Result:**
- ✅ Translation uses approved term (not raw NLLB)
- ✅ Glossary postprocess applied in batch mode

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 9: Large Batch Warning (500+ Rows)

**Prerequisites:**
- Dataset with 500+ lemmas/terms

**Steps:**
1. Select ALL rows (500+) in Dictionary tab (Ctrl+A)
2. Click "Translate Selected..."
3. Observe warning dialog appears (BEFORE confirm dialog)
4. Verify warning: "Large selection (N rows). This may take several minutes. Continue?"
5. Click "Yes"
6. Verify confirm dialog appears as normal
7. Click "Cancel" (don't actually translate 500 rows)

**Expected Result:**
- ✅ Warning appears for large batches (500+)
- ✅ User can cancel before starting
- ✅ If user proceeds, confirm dialog appears as normal

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

### Scenario 10: Keyboard Shortcut (Ctrl+Shift+M)

**Prerequisites:**
- Dictionary tab open

**Steps:**
1. Select 5 rows in Dictionary tab
2. Press `Ctrl+Shift+M` (keyboard shortcut)
3. Verify confirm dialog opens (no need to click button)
4. Press `Esc` to cancel
5. Navigate to Terms tab
6. Select 5 rows
7. Press `Ctrl+Shift+M`
8. Verify confirm dialog opens
9. Press `Esc` to cancel
10. Navigate to Translation Management panel
11. Select 5 rows
12. Press `Ctrl+Shift+M`
13. Verify confirm dialog opens

**Expected Result:**
- ✅ Keyboard shortcut works in all 3 tabs
- ✅ Esc cancels dialog (keyboard-first UX)

**Actual Result:** ________________

**Pass/Fail:** ☐ PASS ☐ FAIL

---

## Automated Tests

### Unit Tests

**File:** `tests/test_ui_batch_mt_translate_service.py`

**Tests:**
- `test_batch_translate_fill_empty_only` - Only translates empty rows
- `test_batch_translate_overwrite_existing` - Overwrites all rows
- `test_batch_translate_skip_non_empty` - Skips filled rows
- `test_batch_translate_per_row_error` - Continues on per-row error
- `test_batch_translate_stop_on_error` - Stops on first error
- `test_batch_translate_chunk_commits` - Commits in chunks
- `test_batch_translate_cancel` - Graceful cancel mid-batch
- `test_batch_translate_dry_run` - Dry run mode (no writes)
- `test_batch_translate_constraint_validation` - Validates language codes, empty text

**Status:** ⏭️ TO BE IMPLEMENTED (PATCH-UI-BATCH-T01)

### UI Tests (Headless)

**File:** `tests/test_ui_batch_translate_dialogs.py`

**Tests:**
- `test_confirm_dialog_creation` - Dialog renders correctly
- `test_progress_dialog_creation` - Progress dialog renders
- `test_selection_extraction_dictionary` - Extracts selected rows from Dictionary model
- `test_selection_extraction_terms` - Extracts selected rows from Terms model
- `test_selection_extraction_tm` - Extracts selected rows from TM model
- `test_settings_persistence` - QSettings keys saved/restored

**Status:** ⏭️ TO BE IMPLEMENTED (PATCH-UI-BATCH-T02+)

---

## Regression Tests

**Verify no regression:**
- ✅ Existing inline translation editing still works (Dictionary, Terms, TM)
- ✅ Existing "Why?" context menu still works
- ✅ Existing automatic translation (Terms view) still works
- ✅ Provider Settings dialog still works
- ✅ All existing tests PASS: `pytest -q`

---

## Performance Tests

**Latency benchmarks:**
- Batch of 50 rows (Local MT, cache miss): ~60-100 seconds (1-2s per row)
- Batch of 50 rows (Local MT, cache hit): ~5 seconds (instant)
- Batch of 50 rows (Cloud MT, cache miss): ~75-150 seconds (1.5-3s per row)
- Chunk commit overhead: < 1 second per chunk

**UI Responsiveness:**
- ✅ Confirm dialog opens instantly (< 100 ms)
- ✅ UI doesn't freeze during translation (background worker)
- ✅ Progress indicator updates smoothly (not stuck)
- ✅ Cancel button responsive (< 500 ms)

---

## Accessibility Tests

**Keyboard-first:**
- ✅ Ctrl+Shift+M opens dialog (no mouse needed)
- ✅ Tab order logical in confirm dialog
- ✅ Enter triggers Translate button
- ✅ Esc closes dialog

**Focus visibility:**
- ✅ Focus outline visible on all widgets
- ✅ Focus starts on first input (provider mode radio)

**Screen reader (future):**
- ⏭️ Aria labels for buttons
- ⏭️ Status announcements for progress updates

---

## Security Tests

**Input validation:**
- ✅ Empty source text → Skip row with warning (not crash)
- ✅ Invalid language codes → Validation error (not crash)
- ✅ Very long text (10KB+) → Segmentation works, no crash

**Logging:**
- ✅ User input sanitized before logging
- ✅ No sensitive data (API keys) in logs
- ✅ Structured logging with trace_id

**Data integrity:**
- ✅ Chunked commits prevent corruption on cancel
- ✅ Constraint validation (origin, status, kind)
- ✅ No duplicate TM entries created

---

## DoD Checklist

**Functional:**
- ☐ User can batch translate selected rows in Dictionary tab
- ☐ User can batch translate selected rows in Terms tab
- ☐ User can batch translate selected rows in Translation Management tab
- ☐ Multi-select works (Ctrl/Shift, non-contiguous)
- ☐ Provider selection works (chain or force provider)
- ☐ Write modes work (fill empty, overwrite, skip non-empty)
- ☐ Background translation (no UI freeze)
- ☐ Progress dialog with cancel support
- ☐ Per-row error handling (continue on failure)
- ☐ Translations saved to DB correctly
- ☐ Translations persist after refresh

**UX:**
- ☐ Keyboard-first (Ctrl+Shift+M shortcut)
- ☐ Discoverable (toolbar button + context menu)
- ☐ Error messages actionable (not stack traces)
- ☐ Progress indicator visible and accurate
- ☐ No fixed heights (scroll for long content)
- ☐ Settings remembered (QSettings persistence)

**Quality:**
- ☐ Compilation PASS
- ☐ Unit tests PASS (service + worker)
- ☐ UI tests PASS (dialogs, headless)
- ☐ No regression (existing features work)
- ☐ Documentation updated (PROVIDER_SETUP_GUIDE.md)

**Release-Ready:**
- ☐ Feature-safe (errors don't crash app)
- ☐ Logging structured (trace_id, provider_id, latency_ms)
- ☐ Large batch warning (500+ rows)
- ☐ Chunked commits (no huge transactions)
- ☐ Manual test scenarios documented

---

## Test Results Summary

**Manual Tests:** __ / 10 PASSED

**Automated Tests:** __ / __ PASSED

**Regression Tests:** ⏭️ TO BE TESTED

**Overall Status:** 🚧 IN PROGRESS

---

## Notes

**Known Limitations:**
- Dictionary and Terms tabs hardcoded to he→ru language pair (cannot batch translate other pairs)
- Large batches (500+) may take 10-20 minutes (network latency for cloud providers)
- Cancel is graceful but not instant (finishes current item before stopping)

**Future Enhancements:**
- Configurable language pairs per tab
- Batch translate by filter (e.g., "all lemmas with freq > 10")
- Resume partial batches
- Undo/redo for batch operations
- Export batch results to CSV

---

**Last Updated:** 2026-02-08 (PATCH-UI-BATCH-T00 - skeleton created)
**Tester:** _________________
**Signature:** _________________
