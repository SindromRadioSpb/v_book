# Translation Coverage Metrics - Analysis and Improvement

## Problem Statement

The XLSX Statistics sheet currently shows "Translation Coverage: 112.5%", which is impossible for a true coverage metric (should be 0-100%).

## Current Implementation (AS-IS)

**Location:** `app/services/export_service.py:478`

**Formula:**
```python
Translation Coverage = (tm_approved_count / max(lemma_count, 1) * 100)
```

**Real Project Example:**
- `tm_approved_count = 9` (approved TM entries)
- `lemma_count = 8` (total lemmas)
- Result: `9 / 8 * 100 = 112.5%`

## Why This Can Exceed 100%

The current formula is **NOT** a coverage metric. It's a **density metric** (translations per lemma).

**Scenario causing >100%:**
- 8 unique lemmas in project
- 9 approved TM entries
- This means some lemmas have multiple translations, or some TM entries don't correspond to lemmas

**Example:**
```
Lemma: "בית" → TM entries: "дом", "house" (2 translations)
Lemma: "ספר" → TM entry: "книга" (1 translation)
...
Total: 8 lemmas, 9 TM entries → 112.5% "density"
```

## Root Cause

**Misnamed metric.** The formula calculates:
- **What it actually measures:** Average number of (approved) translations per lemma
- **What the name implies:** Percentage of lemmas that have translations

This is a **semantic error** - the metric is mathematically correct but incorrectly labeled.

## Proposed Solution

Replace ambiguous metrics with explicit, bounded metrics:

### 1. **Lemma Coverage (%)** [0-100]
**Definition:** Percentage of lemmas that have at least one translation.

**Formula:**
```python
covered_lemmas = COUNT(DISTINCT lemma_id WHERE EXISTS approved translation)
total_lemmas = COUNT(DISTINCT lemma_id)
lemma_coverage_pct = 100 * covered_lemmas / max(total_lemmas, 1)
```

**Criteria:**
- Translation sources: TM entries with status='approved' (OR dict entries, pinned translations if decided)
- Always bounded: 0 ≤ lemma_coverage_pct ≤ 100

**Example:**
- 8 lemmas total
- 7 lemmas have ≥1 approved translation
- Lemma Coverage = 7/8 * 100 = 87.5%

### 2. **TM Entries per Lemma (Ratio)**
**Definition:** Average number of approved TM entries per lemma.

**Formula:**
```python
tm_entries_per_lemma_ratio = tm_approved_count / max(lemma_count, 1)
tm_entries_per_lemma_pct = tm_entries_per_lemma_ratio * 100
```

**Can exceed 100%:** Yes, this is a density metric, not coverage.

**Example:**
- 9 approved TM entries
- 8 lemmas
- Ratio = 9/8 = 1.125 (or 112.5%)

### 3. **TM Approval Rate (%)** [0-100]
**Definition:** Percentage of TM entries that are approved.

**Formula:**
```python
tm_approval_rate_pct = 100 * tm_approved_count / max(tm_total_count, 1)
```

**Example:**
- 9 approved TM entries
- 9 total TM entries
- TM Approval Rate = 9/9 * 100 = 100%

### 4. **Term Approval Rate (%)** [0-100]
**Definition:** Percentage of term clusters that are approved.

**Formula:**
```python
term_approval_rate_pct = 100 * term_approved_count / max(term_total_count, 1)
```

**Example:**
- 0 approved term clusters
- 5 total term clusters
- Term Approval Rate = 0/5 * 100 = 0%

## Implementation Plan

1. **Create `StatsService`** with explicit metric computation
2. **Update XLSX Statistics sheet** with clear metric names
3. **Add unit tests** to verify formulas and bounds
4. **Update documentation** for metric interpretation
5. **Update smoke runner** to validate new metrics

## Backward Compatibility

**Breaking change:** Metric names will change.

**Migration strategy:**
- Remove: "Translation Coverage" (ambiguous)
- Add: "Lemma Coverage (%)" (0-100)
- Add: "TM Entries per Lemma (%)" (can exceed 100, clearly not "coverage")
- Update: "Term Curation Coverage" → "Term Approval Rate (%)" (0-100)

**Impact:** Internal project only, no external API consumers.

## Expected Results After Fix

**XLSX Statistics (new):**
```
Project Name: ТЕСТ М8,М9
Lemmas: 8
TM Entries: 9
TM Approved: 9

Lemma Coverage (%): 87.5%        [0-100, true coverage]
TM Entries per Lemma (%): 112.5% [can exceed 100, density metric]
TM Approval Rate (%): 100%       [0-100, approval rate]
Term Approval Rate (%): 0%       [0-100, approval rate]
```

**Benefits:**
1. No ambiguity - each metric has clear definition
2. True coverage metrics bounded 0-100%
3. Density metrics clearly labeled as such
4. Testable and verifiable
5. Premium quality standards

## Verification

**Test cases:**
1. All lemmas covered → Lemma Coverage = 100%
2. No lemmas covered → Lemma Coverage = 0%
3. Half lemmas covered → Lemma Coverage = 50%
4. Multiple translations per lemma → TM Entries per Lemma > 100% (valid)
5. All TM approved → TM Approval Rate = 100%
6. No TM approved → TM Approval Rate = 0%

---

**Status:** ANALYSIS COMPLETE
**Next:** Implementation (Patches A-D)
