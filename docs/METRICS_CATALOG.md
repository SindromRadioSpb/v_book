# Metrics Catalog - Comprehensive Definition

**Purpose:** Single source of truth for ALL project statistics and metrics.

**Scope:** Covers metrics displayed in:
- XLSX Statistics sheet (export_xlsx)
- Coverage Panel UI (coverage_panel.py)
- Smoke test validators
- Any future analytics/reporting features

**Governance:** All metric changes require:
1. Update to this catalog
2. Update to MetricsRegistry
3. Test coverage for the change
4. Version documentation

---

## Metric Categories

### 1. **Identifiers** (TEXT)
Metrics that identify the project.

### 2. **Counts** (COUNT)
Integer counts of entities. Always ≥ 0.

### 3. **Coverage Metrics** (RATE_0_100)
Percentage of items that meet a criterion. Always bounded [0, 100].

### 4. **Approval/Status Metrics** (RATE_0_100)
Percentage of items in a particular status. Always bounded [0, 100].

### 5. **Density Metrics** (DENSITY)
Ratios that can exceed 100% (e.g., items per category).

---

## Metric Inventory

### IDENTIFIERS

#### M001: Project Name
- **ID:** `project_name`
- **Label:** "Project Name"
- **Type:** TEXT
- **Formula:** Project.name from dict_project table
- **Scope:** Single project
- **Bounds:** String, non-empty
- **Source:** `dict_project.name`
- **Used in:** XLSX Statistics

#### M002: Project ID
- **ID:** `project_id`
- **Label:** "Project ID"
- **Type:** COUNT
- **Formula:** Project.project_id
- **Scope:** Single project
- **Bounds:** Integer > 0
- **Source:** `dict_project.project_id`
- **Used in:** XLSX Statistics

---

### COUNTS

#### M010: Documents
- **ID:** `document_count`
- **Label:** "Documents"
- **Type:** COUNT
- **Formula:** `COUNT(SourceDocument WHERE corpus.project_id = project_id)`
- **Scope:** All source documents in project's corpora
- **Filters:** None (count all documents regardless of status)
- **Bounds:** Integer ≥ 0
- **Source:** `source_document` table via `source_corpus`
- **Invariants:** None
- **Used in:** XLSX Statistics
- **Note:** Currently returns 0 (M9 focus was exports, not doc stats)

#### M011: Lemmas (Unique Words)
- **ID:** `lemma_count`
- **Label:** "Lemmas (Unique Words)"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT lemma_id WHERE project_id = project_id)`
- **Scope:** All lemmas extracted from project documents
- **Filters:** None (includes all lemmas regardless of translation status)
- **Bounds:** Integer ≥ 0
- **Source:** `lemma` table
- **Invariants:**
  - `lemmas_with_translation_count ≤ lemma_count`
- **Used in:** XLSX Statistics, Coverage Panel
- **Dependencies:** Document processing, NLP extraction

#### M012: Lemmas with Translation
- **ID:** `lemmas_with_translation_count`
- **Label:** "Lemmas with Translation"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT lemma_id WHERE EXISTS(approved TM entry))`
- **Detailed:** Count distinct lemmas where:
  ```sql
  EXISTS (
    SELECT 1 FROM tm_entry
    WHERE tm_entry.project_id = project_id
      AND tm_entry.kind = 'lemma'
      AND tm_entry.status = 'approved'
      AND tm_entry.src_text = lemma.lemma_text
  )
  ```
- **Scope:** Lemmas that have at least one approved translation
- **Filters:**
  - **Include:** Only approved TM entries (status='approved')
  - **Exclude:** Draft, rejected, deprecated TM entries
  - **Match:** `tm_entry.src_text = lemma.lemma_text` AND `tm_entry.kind = 'lemma'`
- **Bounds:** Integer ≥ 0, ≤ lemma_count
- **Source:** `lemma` table + `tm_entry` table
- **Invariants:**
  - `0 ≤ lemmas_with_translation_count ≤ lemma_count`
  - If `tm_approved_count = 0` then `lemmas_with_translation_count = 0`
- **Used in:** XLSX Statistics
- **Rationale:** Provides numerator for lemma coverage calculation

#### M013: Term Clusters
- **ID:** `term_cluster_count`
- **Label:** "Term Clusters"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT cluster_id WHERE project_id = project_id)`
- **Scope:** All term clusters (multi-word expressions) extracted
- **Filters:** None (includes all curation statuses)
- **Bounds:** Integer ≥ 0
- **Source:** `term_cluster` table
- **Invariants:**
  - `term_approved_count ≤ term_cluster_count`
- **Used in:** XLSX Statistics, Coverage Panel
- **Note:** Includes clusters with curation_status: auto, needs_review, approved, rejected

#### M014: Terms Approved
- **ID:** `term_approved_count`
- **Label:** "Terms Approved"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT cluster_id WHERE project_id = project_id AND curation_status = 'approved')`
- **Scope:** Term clusters marked as approved by curator
- **Filters:**
  - **Include:** Only `curation_status = 'approved'`
  - **Exclude:** auto, needs_review, rejected
- **Bounds:** Integer ≥ 0, ≤ term_cluster_count
- **Source:** `term_cluster.curation_status`
- **Invariants:**
  - `0 ≤ term_approved_count ≤ term_cluster_count`
- **Used in:** XLSX Statistics

#### M015: TM Entries
- **ID:** `tm_entry_count`
- **Label:** "TM Entries"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT tm_id WHERE project_id = project_id)`
- **Scope:** All translation memory entries
- **Filters:** None (includes all statuses: draft, approved, rejected, deprecated)
- **Bounds:** Integer ≥ 0
- **Source:** `tm_entry` table
- **Invariants:**
  - `tm_approved_count ≤ tm_entry_count`
- **Used in:** XLSX Statistics
- **Note:** Includes TM entries of all kinds: lemma, ngram, term_cluster, surface

#### M016: TM Approved
- **ID:** `tm_approved_count`
- **Label:** "TM Approved"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT tm_id WHERE project_id = project_id AND status = 'approved')`
- **Scope:** Translation memory entries marked as approved
- **Filters:**
  - **Include:** Only `status = 'approved'`
  - **Exclude:** draft, rejected, deprecated
- **Bounds:** Integer ≥ 0, ≤ tm_entry_count
- **Source:** `tm_entry.status`
- **Invariants:**
  - `0 ≤ tm_approved_count ≤ tm_entry_count`
  - If `tm_approved_count = 0` then `lemma_coverage_pct = 0`
- **Used in:** XLSX Statistics

#### M017: Dictionary Entries
- **ID:** `dict_entry_count`
- **Label:** "Dictionary Entries"
- **Type:** COUNT
- **Formula:** `COUNT(DISTINCT dict_entry_id WHERE dict_source.project_id = project_id)`
- **Scope:** Static dictionary entries (imported from external dictionaries)
- **Filters:** None
- **Bounds:** Integer ≥ 0
- **Source:** `dict_entry` table JOIN `dict_source`
- **Invariants:** None
- **Used in:** XLSX Statistics
- **Note:** Distinct from TM entries (dynamic vs static translation sources)

---

### COVERAGE METRICS (RATE_0_100)

#### M020: Lemma Coverage (%)
- **ID:** `lemma_coverage_pct`
- **Label:** "Lemma Coverage (%)"
- **Type:** RATE_0_100
- **Formula:** `100 * lemmas_with_translation_count / max(lemma_count, 1)`
- **Numerator:** `lemmas_with_translation_count` (M012)
- **Denominator:** `lemma_count` (M011)
- **Scope:** Percentage of lemmas that have at least one approved translation
- **Filters:** Inherited from `lemmas_with_translation_count`
  - Only approved TM entries count as "translation"
- **Bounds:** 0.0 ≤ value ≤ 100.0
- **Precision:** 1 decimal place
- **Source:** Computed from M011 and M012
- **Invariants:**
  - If `lemma_count = 0` then `lemma_coverage_pct = 0.0`
  - If `lemmas_with_translation_count = lemma_count` then `lemma_coverage_pct = 100.0`
  - Always: `0.0 ≤ lemma_coverage_pct ≤ 100.0`
- **Used in:** XLSX Statistics, Coverage Panel (as "Lemma Coverage")
- **Interpretation:**
  - 0%: No lemmas have translations
  - 100%: All lemmas have at least one approved translation
  - 50%: Half of lemmas have translations

#### M021: TM Approval Rate (%)
- **ID:** `tm_approval_rate_pct`
- **Label:** "TM Approval Rate (%)"
- **Type:** RATE_0_100
- **Formula:** `100 * tm_approved_count / max(tm_entry_count, 1)`
- **Numerator:** `tm_approved_count` (M016)
- **Denominator:** `tm_entry_count` (M015)
- **Scope:** Percentage of TM entries that are approved
- **Filters:** None (considers all TM entries)
- **Bounds:** 0.0 ≤ value ≤ 100.0
- **Precision:** 1 decimal place
- **Source:** Computed from M015 and M016
- **Invariants:**
  - If `tm_entry_count = 0` then `tm_approval_rate_pct = 0.0`
  - If `tm_approved_count = tm_entry_count` then `tm_approval_rate_pct = 100.0`
  - Always: `0.0 ≤ tm_approval_rate_pct ≤ 100.0`
- **Used in:** XLSX Statistics
- **Interpretation:**
  - 0%: All TM entries are draft/rejected/deprecated
  - 100%: All TM entries are approved
  - 60%: 60% of TM entries are approved, 40% need review

#### M022: Term Approval Rate (%)
- **ID:** `term_approval_rate_pct`
- **Label:** "Term Approval Rate (%)"
- **Type:** RATE_0_100
- **Formula:** `100 * term_approved_count / max(term_cluster_count, 1)`
- **Numerator:** `term_approved_count` (M014)
- **Denominator:** `term_cluster_count` (M013)
- **Scope:** Percentage of term clusters that are approved
- **Filters:** None (considers all term clusters)
- **Bounds:** 0.0 ≤ value ≤ 100.0
- **Precision:** 1 decimal place
- **Source:** Computed from M013 and M014
- **Invariants:**
  - If `term_cluster_count = 0` then `term_approval_rate_pct = 0.0`
  - If `term_approved_count = term_cluster_count` then `term_approval_rate_pct = 100.0`
  - Always: `0.0 ≤ term_approval_rate_pct ≤ 100.0`
- **Used in:** XLSX Statistics
- **Interpretation:**
  - 0%: All term clusters need review
  - 100%: All term clusters are approved
  - 40%: 40% approved, 60% need curation

---

### DENSITY METRICS (DENSITY)

#### M030: TM Entries per Lemma (%)
- **ID:** `tm_entries_per_lemma_pct`
- **Label:** "TM Entries per Lemma (%)"
- **Type:** DENSITY
- **Formula:** `100 * tm_approved_count / max(lemma_count, 1)`
- **Numerator:** `tm_approved_count` (M016)
- **Denominator:** `lemma_count` (M011)
- **Scope:** Average number of approved TM entries per lemma (as percentage)
- **Filters:** Only approved TM entries in numerator
- **Bounds:** value ≥ 0.0 (NO UPPER BOUND - can exceed 100%)
- **Precision:** 1 decimal place
- **Source:** Computed from M011 and M016
- **Invariants:**
  - If `lemma_count = 0` then `tm_entries_per_lemma_pct = 0.0`
  - Can exceed 100% (valid for density metrics)
- **Used in:** XLSX Statistics
- **Interpretation:**
  - 100%: On average, 1 approved TM entry per lemma
  - 112.5%: On average, 1.125 approved TM entries per lemma (some lemmas have multiple translations)
  - 50%: On average, 0.5 approved TM entries per lemma (not all lemmas translated)
- **Note:** This is NOT a coverage metric - it's a density/ratio metric

---

## Coverage Panel Specific Metrics

The Coverage Panel UI (app/ui/coverage_panel.py) uses CoverageWorker to compute:

### Lemma Coverage (UI)
- **Matches:** M020 (Lemma Coverage %)
- **Formula:** Same as M020
- **Display:** Progress bar + percentage + "X / Y (Z untranslated)"
- **Options:**
  - `include_draft` checkbox: If checked, count draft TM entries in coverage
  - **Default:** Only approved (same as M020)

### Term Cluster Coverage (UI)
- **ID:** `cluster_coverage_pct` (UI only)
- **Formula:** `100 * clusters_with_translation / max(term_cluster_count, 1)`
- **Note:** Similar to M020 but for term clusters
- **Used in:** Coverage Panel only (not in XLSX Statistics)

---

## Invariants and Consistency Rules

### Count Invariants
```python
# Approved counts never exceed totals
assert tm_approved_count <= tm_entry_count
assert term_approved_count <= term_cluster_count
assert lemmas_with_translation_count <= lemma_count

# Coverage counts are consistent
assert lemmas_with_translation_count <= lemma_count
```

### Rate Invariants
```python
# All RATE_0_100 metrics are bounded
assert 0.0 <= lemma_coverage_pct <= 100.0
assert 0.0 <= tm_approval_rate_pct <= 100.0
assert 0.0 <= term_approval_rate_pct <= 100.0

# Density metrics have no upper bound
assert tm_entries_per_lemma_pct >= 0.0
# (can exceed 100.0)
```

### Logical Invariants
```python
# If no approved TM, no coverage
if tm_approved_count == 0:
    assert lemma_coverage_pct == 0.0
    assert lemmas_with_translation_count == 0

# If all lemmas covered, coverage is 100%
if lemmas_with_translation_count == lemma_count and lemma_count > 0:
    assert lemma_coverage_pct == 100.0
```

---

## Metric Ordering (XLSX Statistics)

**Deterministic order** (defined by MetricsRegistry):

1. Project Name (M001)
2. Project ID (M002)
3. *(blank separator)*
4. Documents (M010)
5. Lemmas (Unique Words) (M011)
6. Lemmas with Translation (M012)
7. Term Clusters (M013)
8. Terms Approved (M014)
9. TM Entries (M015)
10. TM Approved (M016)
11. Dictionary Entries (M017)
12. *(blank separator)*
13. Lemma Coverage (%) (M020)
14. TM Approval Rate (%) (M021)
15. Term Approval Rate (%) (M022)
16. *(blank separator)*
17. TM Entries per Lemma (%) (M030)

**Total:** 17 rows (12 data metrics + 2 identifiers + 3 separators)

---

## Future Metrics (Reserved IDs)

### Reserved for Expansion
- M040-M049: Advanced coverage metrics
- M050-M059: Quality metrics (e.g., confidence scores)
- M060-M069: Performance metrics (e.g., processing time)
- M070-M079: User activity metrics

---

## Version History

- **v1.0** (2026-02-04): Initial catalog
  - 17 metrics defined (2 identifiers + 12 data + 3 separators)
  - XLSX Statistics coverage complete
  - Coverage Panel coverage complete
  - All formulas, bounds, and invariants documented

---

## Governance

### Adding a New Metric
1. Assign next available metric ID
2. Document in this catalog with ALL required fields
3. Add to MetricsRegistry
4. Implement in StatsService (if applicable)
5. Add test coverage
6. Update XLSX/UI rendering (if applicable)
7. Update documentation

### Changing a Metric
1. Update catalog definition
2. Update MetricsRegistry
3. Update StatsService implementation
4. Update tests
5. Document in version history
6. Consider backward compatibility

### Deprecating a Metric
1. Mark as DEPRECATED in catalog
2. Keep in MetricsRegistry for 1 release with warning
3. Remove in next major version
4. Document migration path

---

**End of Catalog**
