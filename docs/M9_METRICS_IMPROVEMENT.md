# M9 Metrics Improvement - Translation Coverage Fix

**Date:** 2026-02-04
**Status:** COMPLETE
**Impact:** Premium quality improvement - precise, verifiable, unambiguous metrics

## Problem

The XLSX Statistics sheet showed "Translation Coverage: 112.5%", which is impossible for a true coverage metric (should be 0-100%). This created ambiguity and confusion about what was being measured.

## Root Cause

**Misnamed metric.** The formula was mathematically correct but semantically incorrect:

```python
# OLD (incorrect label):
"Translation Coverage" = tm_approved_count / lemma_count * 100

# Example:
9 approved TM entries / 8 lemmas = 112.5% "coverage"
```

This measures **density** (translations per lemma), not **coverage** (% of lemmas with translations).

## Solution

### 1. Created StatsService

New service: `app/services/stats_service.py`

**Features:**
- Explicit metric computation with clear definitions
- All coverage metrics bounded [0, 100]
- Density metrics clearly labeled
- Comprehensive documentation
- Full test coverage

### 2. Updated XLSX Statistics Sheet

**Changes:**
- Replaced: `"Translation Coverage"` → `"Lemma Coverage (%)"`
- Added: `"Lemmas with Translation"` (count)
- Added: `"TM Approval Rate (%)"`
- Added: `"Term Approval Rate (%)"`
- Renamed: `"Term Curation Coverage"` → `"Term Approval Rate (%)"`
- Kept: `"TM Entries per Lemma (%)"` (clearly labeled as density metric)

**New Statistics Sheet Structure:**
```
Lemma Coverage (%)          | 87.5%    [TRUE COVERAGE: 0-100]
TM Approval Rate (%)        | 100.0%   [BOUNDED: 0-100]
Term Approval Rate (%)      | 0.0%     [BOUNDED: 0-100]
TM Entries per Lemma (%)    | 112.5%   [DENSITY METRIC: can exceed 100]
```

### 3. Comprehensive Testing

**New tests:**
- `test_stats_service.py` - 7 unit tests
- Updated `test_m9.py` - metric bounds verification
- 20x anti-flake: ✅ PASS

**All regression tests PASS:**
- test_m7.py, test_m8.py, test_m9.py, test_stats_service.py, test_p3_export_csv_injection.py

## Before / After

**Before (Ambiguous):**
```
Translation Coverage: 112.5%  ← WRONG! Coverage can't exceed 100%
```

**After (Explicit):**
```
Lemma Coverage (%): 87.5%           ← TRUE COVERAGE [0-100]
TM Entries per Lemma (%): 112.5%   ← DENSITY METRIC (can exceed 100)
```

## Conclusion

✅ Root cause identified
✅ Proper solution implemented
✅ All metrics bounded correctly
✅ Comprehensive test coverage
✅ Documentation complete

**Result:** Premium quality metrics that are precise, verifiable, and unambiguous.
