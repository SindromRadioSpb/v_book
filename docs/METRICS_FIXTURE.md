# Metrics Fixture - Ground Truth Test Data

**Purpose:** Deterministic fixture project for validating metrics calculations.

**Project Name:** `METRICS_FIXTURE_v1`

**Created by:** `python -m app.tools.seed_metrics_fixture_project`

---

## Ground Truth Data

### Entities

| Entity | Count | Notes |
|--------|-------|-------|
| Documents | 1 | fixture_doc.txt |
| Lemmas | 10 | lemma_01 to lemma_10 |
| TM Entries | 8 | 6 approved, 2 draft |
| Term Clusters | 5 | 2 approved, 3 needs_review |
| Dict Entries | 2 | From fixture_dict source |

### Lemmas

```
lemma_01 - has 2 approved TM entries (перевод_01, перевод_01_alt)
lemma_02 - has 1 approved TM entry (перевод_02)
lemma_03 - has 1 approved TM entry (перевод_03)
lemma_04 - has 1 approved TM entry (перевод_04)
lemma_05 - has 1 approved TM entry (перевод_05)
lemma_06 - has 1 draft TM entry (перевод_06_draft) - NOT COVERED
lemma_07 - has 1 draft TM entry (перевод_07_draft) - NOT COVERED
lemma_08 - no TM entries - NOT COVERED
lemma_09 - no TM entries - NOT COVERED
lemma_10 - no TM entries - NOT COVERED
```

**Coverage:** 5 lemmas with approved translations = 50%

### TM Entries

| ID | Source | Translation | Status | Kind |
|----|--------|-------------|--------|------|
| 1 | lemma_01 | перевод_01 | approved | lemma |
| 2 | lemma_02 | перевод_02 | approved | lemma |
| 3 | lemma_03 | перевод_03 | approved | lemma |
| 4 | lemma_04 | перевод_04 | approved | lemma |
| 5 | lemma_05 | перевод_05 | approved | lemma |
| 6 | lemma_01 | перевод_01_alt | approved | lemma |
| 7 | lemma_06 | перевод_06_draft | draft | lemma |
| 8 | lemma_07 | перевод_07_draft | draft | lemma |

**Total:** 8 TM entries
**Approved:** 6 (75%)
**Draft:** 2 (25%)

### Term Clusters

| ID | Surface | Curation Status | Pinned Translation |
|----|---------|----------------|-------------------|
| 1 | term_cluster_01 | approved | термин_01 |
| 2 | term_cluster_02 | approved | термин_02 |
| 3 | term_cluster_03 | needs_review | null |
| 4 | term_cluster_04 | needs_review | null |
| 5 | term_cluster_05 | needs_review | null |

**Total:** 5 term clusters
**Approved:** 2 (40%)
**Needs Review:** 3 (60%)

### Dict Entries

| ID | Source | Translation | Status |
|----|--------|-------------|--------|
| 1 | dict_word_01 | словарь_01 | approved |
| 2 | dict_word_02 | словарь_02 | approved |

**Total:** 2 dict entries

---

## Expected Metrics

### Identifiers

| Metric | Expected Value |
|--------|---------------|
| Project Name | METRICS_FIXTURE_v1 |
| Project ID | (dynamic) |

### Counts

| Metric | Expected Value | Calculation |
|--------|---------------|-------------|
| Documents | 1 | 1 document in corpus |
| Lemmas (Unique Words) | 10 | lemma_01 to lemma_10 |
| Lemmas with Translation | 5 | lemmas 01-05 have approved TM |
| Term Clusters | 5 | 5 term clusters created |
| Terms Approved | 2 | clusters 01-02 approved |
| TM Entries | 8 | 6 approved + 2 draft |
| TM Approved | 6 | entries 1-6 approved |
| Dictionary Entries | 2 | 2 dict entries |

### Coverage/Rate Metrics (0-100%)

| Metric | Expected Value | Formula | Notes |
|--------|---------------|---------|-------|
| Lemma Coverage (%) | 50.0% | 5 / 10 * 100 | 5 lemmas have approved TM |
| TM Approval Rate (%) | 75.0% | 6 / 8 * 100 | 6 out of 8 TM entries approved |
| Term Approval Rate (%) | 40.0% | 2 / 5 * 100 | 2 out of 5 clusters approved |

### Density Metrics (Unbounded)

| Metric | Expected Value | Formula | Notes |
|--------|---------------|---------|-------|
| TM Entries per Lemma (%) | 60.0% | 6 / 10 * 100 | 6 approved TM / 10 lemmas = 0.6 |

---

## Validation

Run the seed tool to create and validate the fixture:

```bash
python -m app.tools.seed_metrics_fixture_project
```

**Expected output:**
```
✓ project_name                  = METRICS_FIXTURE_v1 (expected METRICS_FIXTURE_v1)
✓ document_count                = 1 (expected 1)
✓ lemma_count                   = 10 (expected 10)
✓ lemmas_with_translation_count = 5 (expected 5)
✓ term_cluster_count            = 5 (expected 5)
✓ term_approved_count           = 2 (expected 2)
✓ tm_entry_count                = 8 (expected 8)
✓ tm_approved_count             = 6 (expected 6)
✓ dict_entry_count              = 2 (expected 2)
✓ lemma_coverage_pct            = 50.0 (expected 50.0)
✓ tm_approval_rate_pct          = 75.0 (expected 75.0)
✓ term_approval_rate_pct        = 40.0 (expected 40.0)
✓ tm_entries_per_lemma_pct      = 60.0 (expected 60.0)

✅ ALL METRICS MATCH GROUND TRUTH
```

**Exit code:** 0 (success)

---

## Coverage Matrix

The fixture data is designed to cover all branches of metric formulas:

| Scenario | Covered By |
|----------|-----------|
| Empty project | (use separate test) |
| 0% coverage | lemmas 06-10 (no approved TM) |
| 50% coverage | 5/10 lemmas with approved TM |
| 100% coverage | (use separate test) |
| Approved TM entries | 6 entries (status='approved') |
| Draft TM entries | 2 entries (status='draft') |
| Multiple TM per lemma | lemma_01 has 2 approved entries |
| Approved term clusters | 2 clusters (curation_status='approved') |
| Needs review clusters | 3 clusters (curation_status='needs_review') |
| Pinned translations | clusters 01-02 have pinned_translation |
| Dict entries | 2 static dict entries |
| Document count | 1 document in corpus |

---

## Usage in Tests

### Integration Tests

```python
def test_fixture_metrics(self):
    """Test metrics on METRICS_FIXTURE_v1 project."""
    # Seed fixture
    from app.tools.seed_metrics_fixture_project import FixtureSeed
    seeder = FixtureSeed()
    assert seeder.seed(), "Fixture validation failed"

    # Additional tests using fixture project...
```

### Regression Tests

Run fixture seeding as part of regression suite to ensure:
- StatsService formulas remain correct
- MetricsRegistry validation works
- XLSX Statistics exports correct values

---

## Version History

- **v1** (2026-02-04): Initial fixture
  - 10 lemmas, 8 TM entries, 5 term clusters, 2 dict entries
  - 50% lemma coverage, 75% TM approval, 40% term approval
  - Covers all metric branches

---

**Last Updated:** 2026-02-04
