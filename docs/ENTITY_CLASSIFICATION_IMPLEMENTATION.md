# Entity Classification Implementation Summary

**Task**: Task 11 - Entity Classification & Noise Filtering
**Date**: 2026-02-11
**Status**: ✅ COMPLETE
**Patches**: PATCH-00 through PATCH-08 (8 patches)

---

## Executive Summary

Implemented a comprehensive entity classification system that automatically categorizes and filters noise (punctuation, symbols, numbers, formulas) from lemmas and term clusters across the entire application.

**Impact**:
- **42% of lemmas** automatically marked as noise (2,522/5,960 on dev database)
- **18% of clusters** automatically marked as noise (520/2,812 on dev database)
- Clean UI experience by default (noise hidden)
- Clean exports by default (noise excluded)
- Full manual override capability for quality control

---

## Architecture

### Classification Engine (`app/services/entity_classifier.py`)

Pure Python implementation, no external dependencies beyond stdlib.

**Performance**: <0.012ms per classification (~83,000 classifications/second)

**Components**:
- `normalize_text()` - NFKC normalization, dash/quote unification
- `classify_text()` - Single lemma classification
- `classify_phrase()` - Multi-token term cluster classification

**Entity Classes** (9 types):
1. `WORD_HE` - Pure Hebrew words (including geresh/gershayim) - **NOT noise**
2. `WORD_LATIN` - Pure Latin words - **NOT noise**
3. `NUMBER` - Pure numeric values - **noise**
4. `QUANTITY_UNIT` - Number + unit (1.2kg, 10 מטר) - **noise**
5. `MIXED_ALPHA_NUM` - Mixed letters + digits - **noise**
6. `MATH_EXPR` - Math formulas (∑F, cos30°) - **noise**
7. `SYMBOL` - Single symbols (μ, θ, –) - **noise**
8. `PUNCT` - Punctuation marks - **noise**
9. `OTHER` - Unclassified - **noise**

**Noise Reason Codes** (8 codes):
- `NOISE_PUNCT_ONLY` - Pure punctuation
- `NOISE_SYMBOL_ONLY` - Single symbol character
- `NOISE_NUMERIC_ONLY` - Number or quantity+unit
- `NOISE_MATH_EXPR` - Mathematical expression
- `NOISE_MIXED_GARBAGE` - Mixed alpha-numeric
- `NOISE_TOO_SHORT` - Single character (non-letter)
- `NOISE_RATIO_NON_LETTER_HIGH` - >60% non-letters
- `NOISE_LEADING_TRAILING_PUNCT_HEAVY` - 2+ punct at edges

---

## Database Schema (Migration 010)

**Schema Version**: 10 (from v9)

**Added Columns** (both `lemma` and `term_cluster` tables):
- `entity_class` TEXT - Classification type
- `is_noise` INTEGER DEFAULT 0 - Noise flag (0=valid, 1=noise)
- `noise_reason` TEXT - Reason code if noise
- `norm_text` TEXT - Normalized form

**Indexes Created**:
- `idx_lemma_noise` (project_id, is_noise)
- `idx_lemma_entity_class` (project_id, entity_class)
- `idx_cluster_noise` (project_id, is_noise)
- `idx_cluster_entity_class` (project_id, entity_class)

**Backward Compatibility**:
- All columns nullable with defaults
- `is_noise` defaults to 0
- NULL treated as valid (not noise) in queries: `WHERE (is_noise = 0 OR is_noise IS NULL)`

---

## Pipeline Integration

### Lemma Creation (`app/services/process_service.py`)

**When**: New lemmas created during document processing

```python
classification = classify_text(lemma_text)
lemma = Lemma(
    # ... existing fields ...
    entity_class=classification.entity_class,
    is_noise=1 if classification.is_noise else 0,
    noise_reason=classification.noise_reason,
    norm_text=classification.norm_text,
)
```

**Logging**: Statistics per batch (N lemmas, M noise, class distribution)

### Term Cluster Creation (`app/services/term_extraction_service.py`)

**When**: Clusters created during term extraction

```python
classification = classify_phrase(representative_he)
cluster = TermCluster(
    # ... existing fields ...
    entity_class=classification.entity_class,
    is_noise=1 if classification.is_noise else 0,
    noise_reason=classification.noise_reason,
    norm_text=classification.norm_text,
)
```

**Logging**: Statistics per clustering run

---

## Backfill Script

**Location**: `scripts/backfill_entity_classification.py`

**Usage**:
```bash
# Preview changes (dry-run)
python scripts/backfill_entity_classification.py --db-path "path/to/db.db" --dry-run

# Actual backfill
python scripts/backfill_entity_classification.py --db-path "path/to/db.db"

# Custom batch size
python scripts/backfill_entity_classification.py --db-path "path/to/db.db" --batch-size 1000
```

**Performance**: ~2,600 items/second
**Dev Database Results**: 8,772 items classified in 3.4 seconds

**Process**:
1. Finds all rows WHERE entity_class IS NULL
2. Classifies in batches (default 500 rows/commit)
3. Updates database
4. Logs progress and statistics
5. Idempotent (safe to re-run)

---

## UI Features

### Dictionary View (`app/ui/dictionary_view.py`)

**Filter Controls**:
- "Hide noise" checkbox (default: **checked**)
- Tooltip: "Hide punctuation, numbers, symbols, and other noise"
- Live filter - unchecking shows ALL lemmas

**Context Menu** (right-click):
- "✓ Mark as Valid (remove from noise)" - promotes noise to valid
- "✗ Mark as Noise" - demotes valid to noise
- Updates database + reloads view immediately

**Query Filter**:
```sql
WHERE (is_noise = 0 OR is_noise IS NULL)
```

### Terms View (`app/ui/terms_view.py`)

**Filter Controls**:
- "Hide noise" checkbox (default: **checked**)
- Tooltip: "Hide numeric, symbolic, and other noisy terms"
- Live filter - unchecking shows ALL clusters

**Context Menu** (right-click):
- Same manual override actions as Dictionary

**Service Integration**:
```python
clusters = term_service.list_term_clusters(
    session, project_id,
    hide_noise=self.hide_noise_checkbox.isChecked()
)
```

---

## Export Filtering

All export functions default to **exclude_noise=True**.

### XLSX Export (`export_xlsx`)

**Filter**: Excludes noisy lemmas from Dictionary sheet

**Impact**: ~42% fewer lemmas in default export

### TBX Export (`export_tbx`)

**Filter**: Excludes noisy term clusters from TBX XML

**Impact**: ~18% fewer clusters in default export

### TMX Export (`export_tmx`)

**Filter**: Excludes noisy clusters from pinned translations

**Impact**: Only valid terms included in TM

### CSV/JSON Export

**No filtering**: TM entries exported as-is (not classified)

**Bug Fixed**: `export_csv()` → `export_tm_csv()`, `export_json()` → `export_tm_json()`

---

## Testing

### Unit Tests (`tests/test_entity_classifier.py`)

**Coverage**: 59 tests, all passing

**Test Categories**:
- Normalization (4 tests) - whitespace, dashes, quotes
- Lemma classification (30 tests) - all entity classes
- Phrase classification (13 tests) - multi-token terms
- Hebrew-specific (3 tests) - geresh, gershayim, single letter
- Edge cases (8 tests) - empty, URLs, mixed scripts
- Performance (1 test) - <10ms average target

**Golden Test Vectors**:
```python
("!", EntityClass.PUNCT, True, NOISE_PUNCT_ONLY)
("שלום", EntityClass.WORD_HE, False, None)
("1.2kg", EntityClass.QUANTITY_UNIT, True, NOISE_NUMERIC_ONLY)
("∑F", EntityClass.MATH_EXPR, True, NOISE_MATH_EXPR)
```

### Integration Tests

**Migration**: Applied migration 010 to dev database (schema v9 → v10)

**Backfill**: Classified 8,772 items in 3.4 seconds

**Results**:
- Lemmas: 2,944 WORD_HE, 810 OTHER, 770 MATH_EXPR, 648 NUMBER
- Clusters: 2,375 WORD_HE, 302 WORD_LATIN, 74 QUANTITY_UNIT, 38 NUMBER

### Module Imports

All modules import without errors:
- ✅ `app.services.entity_classifier`
- ✅ `app.ui.dictionary_view`
- ✅ `app.ui.terms_view`
- ✅ `app.services.term_extraction_service`
- ✅ `app.services.export_service`

---

## User Workflows

### Workflow 1: Default User (Hide Noise)

1. Process documents → lemmas/clusters automatically classified
2. Open Dictionary → sees only valid words (no punctuation/numbers)
3. Open Terms → sees only valid terminology
4. Export XLSX → clean dictionary without noise
5. Translation work focused on meaningful content

**Noise hidden**: 42% lemmas, 18% clusters

### Workflow 2: Quality Control (Review Noise)

1. Uncheck "Hide noise" checkbox
2. Review noisy items
3. Right-click on misclassified item → "Mark as Valid"
4. Item now visible even with filter ON
5. Can translate, export, curate as needed

### Workflow 3: Manual Curation

1. Find garbage/typo in valid items
2. Right-click → "Mark as Noise"
3. Item hidden from working vocabulary
4. Excluded from exports by default

---

## File Inventory

### Created Files (11 new)

**Core**:
- `app/services/entity_classifier.py` (500 lines) - Classification engine
- `app/infra/migrations/010_entity_classification.sql` - DB migration

**Documentation**:
- `docs/ENTITY_CLASSIFICATION_SPEC.md` - Full specification
- `docs/ENTITY_CLASSIFICATION_IMPLEMENTATION.md` - This file

**Testing**:
- `tests/test_entity_classifier.py` (258 lines) - 59 unit tests

**Scripts**:
- `scripts/backfill_entity_classification.py` (300 lines) - Backfill tool

### Modified Files (7 modified)

**Models**:
- `app/infra/sa_models.py` - Added 4 columns to Lemma, TermCluster

**Services**:
- `app/services/process_service.py` - Classify on lemma creation
- `app/services/term_extraction_service.py` - Classify on cluster creation + filtering
- `app/services/export_service.py` - Export noise filtering

**UI**:
- `app/ui/dictionary_view.py` - Hide noise checkbox + manual override
- `app/ui/terms_view.py` - Hide noise checkbox + manual override
- `app/ui/workers.py` - Bug fix: export function names

---

## Performance Metrics

**Classification Speed**: 0.012ms per item (83,000 items/second)

**Backfill Performance**: 2,600 items/second (batch processing)

**Memory**: No additional runtime memory overhead (pure functions)

**Database**: Efficient indexed queries, backward compatible

---

## Known Limitations & Future Work

### Current Limitations

1. **No reclassification on edit**: If lemma text is manually edited, classification not updated
2. **No batch manual override**: Must mark items one-by-one
3. **No classification history**: No audit log of manual overrides
4. **Domain-specific tuning**: Classifier is general-purpose, may need domain tuning

### Future Enhancements

1. **Bulk Actions**: "Mark selected as noise/valid" for batch operations
2. **Classification Review UI**: Dedicated panel to review all noise items
3. **Custom Rules**: Allow users to define project-specific classification rules
4. **ML Integration**: Learn from manual overrides to improve classifier
5. **Export Options UI**: Checkbox in export dialog to include/exclude noise
6. **Classification Columns in Export**: Optional columns for entity_class, noise_reason

---

## Production Deployment Checklist

### Pre-Deployment

- [x] All unit tests passing (59/59)
- [x] Migration 010 tested on dev database
- [x] Backfill script tested (8,772 items)
- [x] UI modules import successfully
- [x] Export functions tested
- [ ] Manual UI testing (pending)
- [ ] Production database backup created

### Deployment Steps

1. **Backup production database**:
   ```bash
   cp M:\V_book\HDLE\hdle.db M:\V_book\HDLE\backups\hdle_pre_migration_010.db
   ```

2. **Apply migration** (automatic on app startup):
   - Migration 010 will run automatically
   - Schema version 9 → 10

3. **Run backfill** (offline, before first use):
   ```bash
   python scripts/backfill_entity_classification.py --db-path "M:\V_book\HDLE\hdle.db"
   ```

4. **Verify**:
   - Check schema_version = 10
   - Verify entity_class populated
   - Test "Hide noise" checkbox
   - Test manual override
   - Test export

### Rollback Plan

If issues occur:
1. Restore backup: `cp backups\hdle_pre_migration_010.db hdle.db`
2. Revert to previous code version
3. Schema v10 is backward compatible (columns nullable)

---

## Success Metrics

**Goals** (from task specification):
- [x] Deterministic classification with explainable reason codes
- [x] <1ms per classification (achieved: 0.012ms)
- [x] UI filters to hide noise (default ON)
- [x] Export filters to exclude noise (default ON)
- [x] Manual override capability
- [x] No data loss (noise marked, not deleted)
- [x] Backward compatible (NULL handling)
- [x] Comprehensive testing (59 tests)

**Measured Results**:
- Classification speed: **83,000 items/sec** (target: >1,000/sec)
- Noise detection: **42% lemmas, 18% clusters** (reasonable for technical corpus)
- Test coverage: **59 unit tests** covering all entity classes and edge cases
- User control: **Toggle + manual override** for full flexibility

---

## Conclusion

The entity classification system is **fully implemented and tested**. All 8 patches (PATCH-00 through PATCH-08) are complete.

**Key Achievements**:
- Automatic noise detection across entire pipeline
- Clean UI experience by default
- Full manual override for quality control
- Fast, efficient, backward compatible
- Comprehensive documentation and testing

**Ready for production deployment** pending final manual UI testing.

---

**Authors**: Claude Sonnet 4.5 + User
**Review Status**: Implementation Complete
**Last Updated**: 2026-02-11
