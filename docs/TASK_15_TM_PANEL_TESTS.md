# Task #15: Comprehensive Tests for Translation Management Panel

**Status:** ✅ COMPLETE
**Date:** 2026-02-12
**Test File:** `tests/test_tm_panel_ux.py`
**Tests Passed:** 30/30

---

## Summary

Created comprehensive test suite for Translation Management Panel UX improvements covering pagination, sorting, filtering, export, and settings persistence.

## Test Coverage

### 1. Pagination Math (6 tests)

Tests for pagination calculation edge cases and boundary conditions:

- **test_pagination_math_zero_results**: Verify 1 page for empty results
- **test_pagination_math_one_result**: Verify 1 page for single result
- **test_pagination_math_exact_page_boundary**: 100 results = 1 page, 200 results = 2 pages
- **test_pagination_math_partial_last_page**: 101 results = 2 pages (1 full, 1 partial)
- **test_pagination_offset_calculation**: Page 1→0, Page 2→100, Page 50→4900
- **test_pagination_with_different_page_sizes**: 1000 results with 25/50/100/250/500 page sizes

**Formula Tested:**
```python
total_pages = max(1, (total_count + page_size - 1) // page_size)
offset = (current_page - 1) * page_size
```

### 2. Server-Side Sorting (6 tests)

Tests for SQL injection prevention and sort order correctness:

- **test_sort_column_validation**: Invalid column falls back to default (SQL injection prevention)
- **test_sort_by_tm_id_asc**: Ascending order verification
- **test_sort_by_tm_id_desc**: Descending order verification
- **test_sort_by_kind**: Alphabetical sort ('lemma' < 'term_cluster')
- **test_sort_by_status**: Status field sorting
- **test_sort_by_src_text**: Source text sorting

**SQL Injection Protection:**
```python
SORT_COLUMNS = {"tm_id": TMEntry.tm_id, "kind": TMEntry.kind, ...}
column = SORT_COLUMNS.get(sort_column, TMEntry.updated_at)  # Fallback to default
```

### 3. Multi-Project Filter (6 tests)

Tests for project filtering with SQL OR logic:

- **test_filter_single_project**: 10 entries from Project Alpha
- **test_filter_multiple_projects**: 15 entries from Alpha (10) + Beta (5)
- **test_filter_global_only**: 7 global entries (project_id=None)
- **test_filter_mixed_projects_and_global**: 17 entries (Alpha 10 + Global 7)
- **test_filter_all_projects_implicit**: 25 total entries (no filter)
- **test_filter_empty_project_list**: 0 results (empty list)

**SQL Logic:**
```python
if real_ids:
    conditions.append(TMEntry.project_id.in_(real_ids))
if include_global:
    conditions.append(TMEntry.project_id.is_(None))
if conditions:
    stmt = stmt.where(or_(*conditions))
```

### 4. Combined Filters + Sorting + Pagination (2 tests)

Integration tests combining multiple features:

- **test_combined_filter_sort_pagination**: Filter by kind='lemma', sort by src_text ASC, paginate (5/page)
- **test_count_matches_filter**: Verify count_tm_entries() matches search_tm_entries() filters

### 5. Excel Export with Filters (3 tests)

Tests for export functionality:

- **test_export_with_filters**: Export 10 filtered entries, verify XLSX format
- **test_export_empty_results**: Export with no matches, verify header-only file
- **test_export_respects_sorting**: Verify exported data maintains sort order

**Verification:**
```python
from openpyxl import load_workbook
wb = load_workbook(export_path)
ws = wb["Translation Memory"]
assert ws.max_row == 11  # 1 header + 10 data rows
```

### 6. Settings Persistence (2 tests)

Tests for QSettings integration:

- **test_settings_save_and_load**: Save and restore page_size, sort_column, sort_direction
- **test_settings_default_values**: Verify default values for non-existent keys

### 7. Edge Cases and Boundary Conditions (4 tests)

Tests for error handling and edge cases:

- **test_large_offset_beyond_results**: Offset 9900 with 25 entries → empty list
- **test_zero_page_size_fallback**: Zero page size → fallback to minimum 25
- **test_negative_offset**: Negative offset → max(0, offset)
- **test_filter_by_status_and_kind**: Combined filters (kind='lemma' AND status='approved')

---

## Test Data Structure

### Fixtures

**temp_db**: Temporary database with schema
- Creates Library, DictProject, TMEntry tables
- Disposes engine before cleanup
- Retries cleanup on Windows (file lock handling)

**populated_db**: Test data (25 entries total)
- 1 Library ("Test Library")
- 3 Projects (Alpha, Beta, Gamma)
- Project Alpha: 10 lemma entries (approved)
- Project Beta: 5 term_cluster entries (draft)
- Project Gamma: 3 lemma entries (deprecated)
- Global: 7 lemma entries (no project, approved)

### Schema Constraints Enforced

**TMEntry:**
- `kind` must be: 'lemma', 'ngram', 'term_cluster', 'surface'
- `status` must be: 'draft', 'approved', 'rejected', 'deprecated'
- `origin` must be: 'user_edit', 'import', 'mt_accept', 'mt_auto', 'merge', 'revert'
- `src_lang`, `tgt_lang`, `src_norm`, `translation_norm` are NOT NULL
- `library_id` FK required for DictProject

---

## Test Results

```
============================= 30 passed in 1.70s ==============================
```

### Breakdown by Category

| Category | Tests | Status |
|----------|-------|--------|
| Pagination math | 6 | ✅ All passed |
| Server-side sorting | 6 | ✅ All passed |
| Multi-project filter | 6 | ✅ All passed |
| Combined features | 2 | ✅ All passed |
| Excel export | 3 | ✅ All passed |
| Settings persistence | 2 | ✅ All passed |
| Edge cases | 4 | ✅ All passed |
| Summary | 1 | ✅ Passed |
| **Total** | **30** | **✅ 100%** |

---

## How to Run Tests

### All Tests
```bash
python -m pytest tests/test_tm_panel_ux.py -v
```

### Specific Category
```bash
# Pagination tests
python -m pytest tests/test_tm_panel_ux.py -k "pagination" -v

# Sorting tests
python -m pytest tests/test_tm_panel_ux.py -k "sort" -v

# Filter tests
python -m pytest tests/test_tm_panel_ux.py -k "filter" -v

# Export tests
python -m pytest tests/test_tm_panel_ux.py -k "export" -v
```

### Single Test
```bash
python -m pytest tests/test_tm_panel_ux.py::test_sort_by_tm_id_asc -v
```

---

## Test Fixtures Design Patterns

### Temporary Database with Cleanup

```python
@pytest.fixture
def temp_db():
    """Create temporary database with schema."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    engine = None
    try:
        engine = create_engine(f"sqlite:///{db_path}")

        # Create only essential tables (avoid problematic indexes)
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        TMEntry.__table__.create(engine, checkfirst=True)

        yield engine, db_path
    finally:
        # Dispose engine before cleanup
        if engine is not None:
            engine.dispose()

        # Retry cleanup on Windows (file lock handling)
        import time
        for attempt in range(3):
            try:
                Path(db_path).unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.1)
```

**Key Patterns:**
1. Use `tempfile.NamedTemporaryFile` for isolated test databases
2. Create only essential tables (avoid full `Base.metadata.create_all()` to skip problematic indexes)
3. **Always** dispose engine before cleanup (critical on Windows)
4. Retry cleanup with delay to handle file locks (Windows-specific)

### Populated Test Data

```python
@pytest.fixture
def populated_db(temp_db):
    """Database with test data: 3 projects + global entries."""
    engine, db_path = temp_db

    with Session(engine) as session:
        # Create library (required FK)
        library = Library(name="Test Library")
        session.add(library)
        session.flush()

        # Create projects
        projects = [
            DictProject(library_id=library.library_id, name="Project Alpha"),
            DictProject(library_id=library.library_id, name="Project Beta"),
            DictProject(library_id=library.library_id, name="Project Gamma"),
        ]
        for p in projects:
            session.add(p)
        session.flush()

        # Add TM entries (satisfy all constraints)
        entry = TMEntry(
            kind='lemma',                # Valid: lemma, ngram, term_cluster, surface
            src_lang='he',               # NOT NULL
            tgt_lang='ru',               # NOT NULL
            src_text='alpha_src_0',
            src_norm='alpha_src_0',      # NOT NULL
            translation='alpha_trans_0',
            translation_norm='alpha_trans_0',  # NOT NULL
            status='approved',           # Valid: draft, approved, rejected, deprecated
            project_id=project_ids[0],
            origin='user_edit',          # Valid: user_edit, import, mt_accept, mt_auto, merge, revert
        )
        session.add(entry)

        session.commit()
        yield session, project_ids
```

---

## Coverage Analysis

### What's Tested ✅

1. **Pagination Logic**: All edge cases and boundary conditions
2. **SQL Injection**: Invalid column names rejected
3. **Sort Order**: ASC/DESC for all sortable columns
4. **Project Filters**: Single, multiple, global, mixed, empty
5. **Export**: Filter respect, empty results, sort preservation
6. **Settings**: Save/load, defaults
7. **Edge Cases**: Large offset, zero/negative values, combined filters

### What's NOT Tested ⚠️

1. **UI Components**: QTableView, QProgressDialog, QPushButton (UI tests out of scope)
2. **Worker Threads**: TMSearchWorker, TMExportWorker cancellation (async behavior hard to test)
3. **Header State**: Column widths, resize, reorder (Qt-specific)
4. **Performance**: Large datasets (100k+ entries), response time benchmarks
5. **Concurrency**: Simultaneous searches, race conditions
6. **Network**: Export to network drives, file permissions

---

## Related Files

### Implementation
- `app/services/translation_admin_service.py` - Backend logic
- `app/services/export_service.py` - Excel export
- `app/ui/translation_management_panel.py` - UI components
- `app/ui/workers.py` - Async workers
- `app/infra/settings.py` - Settings persistence

### Tests
- `tests/test_tm_panel_ux.py` - **THIS FILE** (30 tests)
- `scripts/test_tm_settings_persistence.py` - Smoke test for settings
- `scripts/test_tm_export_excel.py` - Smoke test for export

### Documentation
- `info-UI-dashboard.md` - Original plan (7 features)
- `docs/TASK_13_SETTINGS_PERSISTENCE.md` - Settings implementation
- `docs/TASK_14_EXCEL_EXPORT.md` - Export implementation
- `docs/P0_BULK_NOISE_SAFETY.md` - Bulk operations safety

---

## Lessons Learned

### 1. Avoid Full Schema Creation in Tests

**Problem:** `Base.metadata.create_all(engine)` failed with:
```
AttributeError: 'str' object has no attribute '_compiler_dispatch'
```

**Cause:** Some indexes use string `sqlite_where` clauses instead of SQLAlchemy expressions:
```python
Index("idx_tm_lookup_lemma", "project_id", "lemma_id",
      sqlite_where="lemma_id IS NOT NULL")  # ← String, not expression
```

**Solution:** Create only essential tables explicitly:
```python
Library.__table__.create(engine, checkfirst=True)
DictProject.__table__.create(engine, checkfirst=True)
TMEntry.__table__.create(engine, checkfirst=True)
```

### 2. Windows File Lock Handling

**Problem:** `PermissionError: [WinError 32]` when deleting temp database

**Cause:** SQLite keeps file locks even after session closes (Windows-specific)

**Solution:**
```python
# 1. Dispose engine BEFORE cleanup
if engine is not None:
    engine.dispose()

# 2. Retry with delay
for attempt in range(3):
    try:
        Path(db_path).unlink(missing_ok=True)
        break
    except PermissionError:
        if attempt < 2:
            time.sleep(0.1)
```

### 3. Check Constraint Validation

**Problem:** `sqlite3.IntegrityError: CHECK constraint failed: ck_tm_kind`

**Cause:** Used invalid enum values:
- ❌ `kind='term'` → ✅ `kind='term_cluster'`
- ❌ `status='pending'` → ✅ `status='draft'`
- ❌ `origin='manual'` → ✅ `origin='user_edit'`

**Solution:** Always check schema constraints before creating test data:
```bash
grep "CheckConstraint" app/infra/sa_models.py
```

### 4. NOT NULL Constraints

**Problem:** `NOT NULL constraint failed: tm_entry.src_norm`

**Cause:** Forgot required fields in test data

**Solution:** Complete field list for TMEntry:
- `src_lang`, `tgt_lang` (language codes)
- `src_norm`, `translation_norm` (normalized text)
- `library_id` FK (for DictProject)

---

## Future Enhancements

### P1: Performance Tests
```python
def test_large_dataset_performance():
    """Test pagination with 100k entries."""
    # Create 100k entries
    # Measure search time < 1s
    # Measure memory usage < 100 MB
```

### P2: Concurrency Tests
```python
def test_concurrent_searches():
    """Test multiple simultaneous searches don't conflict."""
    # Launch 10 parallel searches
    # Verify no race conditions
```

### P3: Export Cancellation
```python
def test_export_cancel_midway():
    """Test TMExportWorker cancellation."""
    # Start export of 10k entries
    # Cancel after 5k
    # Verify partial file not created
```

---

## Conclusion

✅ **All 30 tests passed** - Translation Management Panel UX improvements are production-ready.

**Test Coverage:**
- Pagination math: 6/6 ✅
- Server-side sorting: 6/6 ✅
- Multi-project filter: 6/6 ✅
- Combined features: 2/2 ✅
- Excel export: 3/3 ✅
- Settings persistence: 2/2 ✅
- Edge cases: 4/4 ✅
- Summary: 1/1 ✅

**Total: 30/30 tests (100%)**
