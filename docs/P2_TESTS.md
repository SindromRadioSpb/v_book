# P2 Premium Workflow - Test Suite Documentation

## Overview

P2 Premium workflow provides Translation Management and QA/Coverage features for power users. The test suite ensures all service operations, UI models, and panels work correctly.

## Test Files

### 1. **test_p2_translation_admin_service.py** (7 tests)
**Purpose**: Test TranslationAdminService CRUD operations

**Tests**:
- `test_search_filters_origin_and_source_ref`: Verify origin and source_ref filters
- `test_scope_filter_project_vs_global`: Verify project vs global scope filtering
- `test_set_status_approve_sets_approved_at`: Verify approve sets approved_at/approved_by
- `test_set_status_reject_clears_approved_at`: Verify reject/deprecate clears approval info
- `test_update_translation_creates_history`: Verify history entry created on update
- `test_revert_sets_origin_revert_and_restores_translation`: **P2.3** Verify revert contract (origin="revert")
- `test_bulk_set_status_transactional`: Verify bulk operations are atomic

**Key Contracts**:
- Status workflow: draft → approved/rejected/deprecated
- Change_kind mapping: approved → "approve", rejected → "reject"
- Revert MUST set origin="revert" (P2.3 requirement)
- Approved_at/approved_by MUST be set on approve, cleared on reject/deprecate

**Run**:
```bash
python test_p2_translation_admin_service.py
```

### 2. **test_p2_coverage_service.py** (6 tests)
**Purpose**: Test CoverageService metrics and query efficiency

**Tests**:
- `test_compute_lemma_coverage_basic`: Verify lemma coverage % calculation
- `test_compute_termcluster_coverage_basic`: Verify term cluster coverage %
- `test_list_untranslated_lemmas_excludes_translated`: Verify filtering logic
- `test_list_untranslated_termclusters_excludes_translated`: Verify filtering logic
- `test_ordering_untranslated_lemmas_by_freq`: Verify freq descending order
- `test_query_count_guard_no_n_plus_one`: **CRITICAL** Verify no N+1 queries

**Query Count Ceilings**:
- `compute_lemma_coverage`: ≤ 3 queries (actual: 2)
- `compute_termcluster_coverage`: ≤ 3 queries (actual: 2)
- `list_untranslated_lemmas`: ≤ 5 queries (actual: 1 with joins)
- `list_untranslated_termclusters`: ≤ 5 queries (actual: 1 with joins)

**Key Mechanism**:
Uses SQLAlchemy event listener `before_cursor_execute` to count queries:
```python
@contextmanager
def count_sql_queries(db_service):
    counter = {"count": 0}
    engine = db_service.db_manager.engine

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
```

**Run**:
```bash
python test_p2_coverage_service.py
```

### 3. **test_p2_translation_management_model.py** (12 tests)
**Purpose**: Test TranslationManagementTableModel (Qt Model/View)

**Tests**:
- `test_column_count`: Verify 9 columns
- `test_row_count`: Verify row count matches data
- `test_header_data`: Verify column headers
- `test_data_display_translation`: Verify translation display
- `test_data_display_status`: Verify status display
- `test_data_display_scope`: Verify scope display (Project N / Global)
- `test_data_display_origin`: Verify origin display
- `test_data_display_source_ref`: Verify source_ref display
- `test_flags_translation_editable`: Verify Translation column is editable
- `test_setdata_updates_translation`: Verify inline editing works
- `test_setdata_emits_datachanged`: Verify dataChanged signal emitted
- `test_update_entries_resets_model`: Verify model reset on data update

**Key Features**:
- Headless Qt testing (QT_QPA_PLATFORM=offscreen)
- Single QApplication instance pattern
- Editable translation column only
- Scope display: "Project N" for project_id=N, "Global" for project_id=NULL

**Run**:
```bash
python test_p2_translation_management_model.py
```

### 4. **test_p2_ui_smoke.py** (6 tests)
**Purpose**: Smoke tests for UI panel instantiation

**Tests**:
- `test_import_translation_management_panel`: Verify import works
- `test_import_coverage_panel`: Verify import works
- `test_instantiate_translation_management_panel`: Verify panel can be created
- `test_instantiate_coverage_panel`: Verify panel can be created
- `test_translation_management_panel_has_required_attributes`: Verify widgets exist
- `test_coverage_panel_has_required_attributes`: Verify widgets exist

**Purpose**: Early detection of import errors, missing dependencies, or broken UI constructors.

**Run**:
```bash
python test_p2_ui_smoke.py
```

## Test Suite Summary

| Test File | Tests | Focus | Critical Checks |
|-----------|-------|-------|-----------------|
| test_p2_translation_admin_service.py | 7 | Service CRUD | Revert contract, status workflow, history |
| test_p2_coverage_service.py | 6 | Coverage metrics | **Query count ceilings**, filtering |
| test_p2_translation_management_model.py | 12 | Qt model | Inline editing, signals, headless |
| test_p2_ui_smoke.py | 6 | UI smoke | Panel instantiation, imports |
| **Total** | **31** | | |

## Running All P2 Tests

```bash
# Run all P2 tests
python test_p2_translation_admin_service.py && \
python test_p2_coverage_service.py && \
python test_p2_translation_management_model.py && \
python test_p2_ui_smoke.py

# Or individually
python test_p2_translation_admin_service.py
python test_p2_coverage_service.py
python test_p2_translation_management_model.py
python test_p2_ui_smoke.py
```

## Schema Requirements

P2 tests require the following schema migrations:
1. **004_m7_translation_memory.sql**: Base TM schema
2. **005_m7_add_revert_origin.sql**: Add 'revert' to tm_entry_history.origin
3. **006_p2_add_revert_origin.sql**: Add 'revert' to tm_entry.origin (P2.3)

All tests use temporary SQLite databases and apply migrations automatically.

## Test Data

Tests use deterministic test data:
- **Lemmas**: בית (NOUN, 100), ספר (NOUN, 80), שולחן (NOUN, 60), כסא (NOUN, 40)
- **Term Clusters**: בית הספר (50, 0.8), שולחן עגול (30, 0.6), כסא נוח (20, 0.4)
- **TM Entries**: בית → дом (approved), בית הספר → школа (approved)
- **Dict Entries**: ספר → книга (approved)

**Coverage Expected**:
- Lemma coverage: 2/4 = 50%
- Cluster coverage: 1/3 = 33.3%

## Regression Testing

After P2 implementation, verify that existing functionality still works:

```bash
# M7 regression
python test_m7.py

# P1 regression
python test_p1_verification.py
```

## DoD Checklist

- [ ] All P2 tests PASS (31/31)
- [ ] Query count ceilings verified (coverage tests)
- [ ] Revert contract verified (origin="revert")
- [ ] UI smoke tests PASS
- [ ] Regression tests PASS (M7, P1)
- [ ] No runtime DB files in git
- [ ] Git status clean

## Known Issues

None currently.

## Future Enhancements

Potential future test additions:
1. E2E tests with actual UI interaction (requires pytest-qt)
2. Performance benchmarks for large datasets (10K+ entries)
3. Concurrency tests for simultaneous edits
4. Pagination tests for search results
5. History dialog interaction tests
