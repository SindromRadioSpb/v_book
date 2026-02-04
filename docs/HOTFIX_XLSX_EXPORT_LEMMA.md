# Hotfix: XLSX Export - Lemma Frequency AttributeError

**Date:** 2026-02-04
**Issue:** XLSX export failed when exporting lemmas
**Error:** `'Lemma' object has no attribute 'freq_abs'`
**Status:** ✅ RESOLVED

---

## Problem Description

User reported error when exporting to Excel (XLSX) format via Export tab:

```
Export Error
An error occurred during export:
'Lemma' object has no attribute 'freq_abs'
```

### Root Cause

The `export_xlsx()` method in `ExportService` was trying to access `lemma.freq_abs` directly:

```python
# OLD CODE (line 391)
frequency = lemma.freq_abs or ""
```

**Problem:** The `Lemma` model does not have a `freq_abs` field. Frequency statistics are stored in a separate table `LemmaProjectStat` with a foreign key relationship.

**Model Structure:**
- `Lemma`: Basic lemma info (lemma_text, pos, morph_json)
- `LemmaProjectStat`: Frequency statistics (freq_abs, doc_freq) per project

---

## Solution

Added JOIN query to fetch frequency from `LemmaProjectStat` table:

```python
# NEW CODE (lines 380-394)
# Look up frequency from LemmaProjectStat
from app.infra.sa_models import LemmaProjectStat
lemma_stat = (
    session.query(LemmaProjectStat)
    .filter(
        LemmaProjectStat.project_id == project_id,
        LemmaProjectStat.lemma_id == lemma.lemma_id,
    )
    .first()
)

frequency = lemma_stat.freq_abs if lemma_stat else ""
```

**Logic:**
1. Query `LemmaProjectStat` for each lemma
2. If stat exists, use `freq_abs` value
3. If no stat (new lemma), use empty string

---

## Changes

**File Modified:**
- `app/services/export_service.py` (lines 369-395)

**Changes:**
- Added import of `LemmaProjectStat` model
- Added query to fetch lemma frequency stats
- Store frequency in variable before appending to sheet
- Handle missing stats gracefully (frequency = "")

---

## Testing

**Manual Test (Required):**
1. Restart application
2. Open project with lemmas
3. Go to Export tab
4. Select "Excel (Multi-sheet with statistics)" format
5. Click "Export..."
6. Choose save location
7. Verify export completes successfully
8. Open exported XLSX file
9. Verify:
   - Dictionary sheet has data
   - Frequency column shows correct values for lemmas
   - No errors during export

**Expected Result:**
- Export completes without errors
- File is created successfully
- Frequency column shows numeric values where available

---

## Related

**M9 Export Center:**
- PATCH 5: XLSX multi-sheet export (original implementation)
- This hotfix addresses production bug found during manual testing

**Other Export Formats:**
- CSV/JSON exports not affected (don't use lemma frequency)
- TBX/TMX exports not affected (use term_cluster, not lemma)

---

## Prevention

**Code Review Note:**
When accessing model attributes in export code:
1. Always check model definition in `sa_models.py`
2. Verify which fields exist directly on the model
3. Use JOINs for related table data (e.g., stats tables)
4. Handle missing related records gracefully

**Testing Note:**
- M9 tests use small test datasets, may not catch all edge cases
- Manual testing with production-like data is essential
- Consider adding test case with lemmas without stats

---

## Commit

**SHA:** 98dd4af
**Message:** HOTFIX: Fix XLSX export - Lemma.freq_abs AttributeError
**Push:** ✅ Pushed to origin/main

---

**Status:** ✅ RESOLVED
**Action Required:** User restart + manual test of XLSX export
