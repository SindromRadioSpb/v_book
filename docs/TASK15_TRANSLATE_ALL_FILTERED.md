# Task 15: Translate All Filtered + "All (N)" Page Size

**Date**: 2026-02-13
**Status**: ✅ Complete

## Overview

Adds two major UX improvements to Dictionary and Terms views:
1. **Translate All Filtered** - Translate all records matching current filters (across pages), not just visible rows
2. **"All (N)" Page Size** - Safely view all records when count ≤ 5000

## Problem

With server-side pagination (limit/offset), users could only translate rows visible on the current page. They could not translate all matching records across pages without:
- Manually selecting all pages one-by-one (tedious)
- Temporarily increasing page size to MAX and selecting all (risky, could freeze UI on large datasets)

## Solution

### 1. Scope Selector in Translate Dialog

The "Translate Selected" dialog now includes a **Scope** radio group:
- **Current page** (default) - Translate only selected rows from current page (original behavior)
- **All pages (filtered)** - Translate ALL records matching current filters, across all pages

When "All pages" is selected, the dialog shows: "→ Will translate ~N items matching current filters"

### 2. Chunked Translation Worker

`TranslateAllFilteredWorker` (in `app/ui/workers.py`) handles "All pages" scope:
- Fetches entity IDs in chunks (200 at a time) to avoid loading all into memory
- For each chunk: loads entities + current translations, builds `BatchTranslateItem` objects
- Reuses existing `BatchMTTranslateService.execute_batch()` for actual translation/write logic (no duplication)
- Supports real-time progress updates and graceful cancellation

### 3. Service Layer ID Fetching

New methods in `DictionaryService` and `TermExtractionService`:
- `count_*_ids_for_translation(session, project_id, filters, write_mode) -> int`
- `fetch_*_ids_for_translation(session, project_id, filters, write_mode, limit, offset) -> list[int]`

These methods:
- Apply the same filters as table search (pos, hide_noise, search, min_freq, source_filter, preset)
- For `FILL_EMPTY` / `SKIP_NON_EMPTY` write modes: LEFT JOIN `tm_entry` and filter for empty/missing translations
- For `OVERWRITE` write mode: include all matching records (no translation filter)
- Order by ID ASC for deterministic chunking

### 4. "All (N)" Page Size Option

When `total_count <= MAX_ALL_ROWS_UI` (5000), page size combo includes "All (N)" option:
- Example: "All (2,345)" appears in dropdown when 2,345 total records
- Selecting it loads all records in one page
- If total > 5000: option not shown (prevents UI freeze on massive datasets)

## Safety Constraints

### 1. Overwrite Confirmation
If write mode = "Overwrite" AND scope = "All pages" AND count > 100:
- Show QMessageBox confirmation: "This will overwrite N existing translations. This cannot be undone."
- User must explicitly confirm (Yes/No)

### 2. MAX_ALL_ROWS_UI Limit
- Hard limit: 5000 records for "All (N)" page size
- Prevents UI freeze/crash from loading 100k+ rows into QTableView
- For larger datasets, users must:
  - Use pagination (recommended)
  - Apply filters to reduce count
  - Use export instead

### 3. Chunked Processing
- TranslateAllFilteredWorker processes in chunks (200 IDs at a time)
- Each chunk: fetch → translate → commit → next
- Memory-bounded: never loads all entities at once
- Handles 100k+ records safely

### 4. Button Locking
While "All pages" translation runs:
- "Translate Selected" button disabled
- Re-enabled only after worker finishes or errors

## Implementation Details

### Modified Files

| File | Changes |
|------|---------|
| `app/services/dictionary_service.py` | Added `count_lemma_ids_for_translation()`, `fetch_lemma_ids_for_translation()` |
| `app/services/term_extraction_service.py` | Added `count_cluster_ids_for_translation()`, `fetch_cluster_ids_for_translation()` |
| `app/ui/workers.py` | Added `TranslateAllFilteredWorker` class |
| `app/ui/dialogs/batch_translate_dialog.py` | Added Scope radio group, updated signature to return scope |
| `app/ui/dictionary_view.py` | Handle scope in `on_batch_translate()`, added `_update_page_size_combo()`, updated `on_page_size_changed()` |
| `app/ui/terms_view.py` | Mirror of dictionary_view changes for term_cluster entities |

### New Files

| File | Purpose |
|------|---------|
| `tests/test_task15_translate_scope.py` | Smoke tests for new methods and signatures |
| `docs/TASK15_TRANSLATE_ALL_FILTERED.md` | This documentation |

## Usage

### Example: Translate All Nouns with Empty Translations

1. Go to Dictionary view
2. Set POS filter = "NOUN"
3. Enable "Hide Noise"
4. Click "Translate Selected..." (no selection needed for "All pages" scope)
5. In dialog:
   - Scope: Select "All pages (filtered)"
   - Write Mode: "Fill empty only"
   - Provider Mode: "Use provider chain"
6. Click "Translate"
7. Progress dialog shows: "Translated 1,234/5,678..."
8. Can cancel anytime

### Example: View All Records (Small Dataset)

1. Apply filters to reduce total count to ≤ 5000
2. Page size dropdown now shows "All (2,345)"
3. Select it
4. All records load in single page
5. Can scroll through all, select all, bulk translate

## Testing

### Smoke Tests
- `tests/test_task15_translate_scope.py`
- 11 tests: import checks, signature validation, basic logic
- All passed ✅

### Regression Tests
- `tests/test_dictionary_terms_pagination.py` - 51 passed, 12 skipped ✅
- `tests/test_security.py` - 33 passed ✅
- `tests/test_task12_fts_nlp.py` - 10 passed ✅

### Manual Testing Required
- Launch app with production DB
- Test "All pages" scope with Dictionary view
- Test "All pages" scope with Terms view
- Test overwrite confirmation
- Test cancel during translation
- Test "All (N)" page size with small/large datasets

## Performance

### Chunked Translation Benchmarks (estimated)

| Total Records | Chunk Size | Chunks | Translation Time | Memory Usage |
|---------------|------------|--------|------------------|--------------|
| 1,000         | 200        | 5      | ~30 sec          | ~20 MB       |
| 10,000        | 200        | 50     | ~5 min           | ~20 MB       |
| 100,000       | 200        | 500    | ~50 min          | ~20 MB       |

**Notes:**
- Memory usage remains constant (only 200 entities in memory at a time)
- Translation time depends on MT provider (local NLLB ~0.5s/item, cloud ~0.1s/item)
- Chunked commits: 50 rows/commit (vs 1 row/commit in old code)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Dictionary/Terms View                                        │
│  on_batch_translate()                                        │
│    ├─ scope == "current_page"                                │
│    │   └─> BatchTranslateWorker (existing)                   │
│    └─ scope == "all_filtered"                                │
│        ├─> count_*_ids_for_translation() [get total]         │
│        ├─> TranslateAllFilteredWorker                        │
│        │    ├─> Loop: fetch_*_ids_for_translation(chunk)     │
│        │    │   ├─> Load entities + translations             │
│        │    │   ├─> Build BatchTranslateItem list            │
│        │    │   └─> BatchMTTranslateService.execute_batch()  │
│        │    └─> Emit progress, check cancel                  │
│        └─> BatchProgressDialog (show/update/cancel)          │
└─────────────────────────────────────────────────────────────┘
```

## Future Enhancements

1. **Export filtered + translate** - Export all filtered records with translations in one step
2. **Batch scheduling** - Queue large translation jobs for background processing
3. **Resume after cancel** - Save progress, resume from last chunk
4. **Parallel chunking** - Process multiple chunks concurrently (with rate limiting)

## Related

- **Task 12**: FTS5 + NLP Pipeline (session isolation patterns)
- **Task 13**: is_noise trigger sync (noise filtering in count queries)
- **Task 14**: Pagination UI (page_size_combo, update_pagination_controls)
- **Batch Translation V2**: BatchMTTranslateService (reused for translation logic)
