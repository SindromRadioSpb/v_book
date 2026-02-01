# M4: Live Update - Implementation Plan

**Status:** 🔄 IN PROGRESS
**Priority:** HIGH
**Estimated Time:** 4-5 days

---

## Overview

M4 adds dynamic statistics management for production workflows:
- Add/remove documents without full recalculation
- Re-process documents with automatic delta updates
- Bulk operations for efficiency
- Proper error handling and rollback

---

## Requirements

### 1. Delta Statistics ⭐⭐⭐
**Problem:** Currently, deleting a document leaves incorrect statistics.

**Solution:**
- Track lemma frequencies per document (`lemma_doc_stat`)
- On delete: subtract document's stats from project totals
- Remove lemmas with zero frequency
- Update remaining lemma frequencies

**Implementation:**
- `ProcessService.remove_document_stats(session, doc_id)`
- Update `IngestService.delete_document()` to call it
- Transactional: rollback if fails

### 2. Re-processing Documents ⭐⭐⭐
**Problem:** Cannot update a document's NLP analysis.

**Solution:**
- Button "Re-process" in Documents view
- Steps:
  1. Set status: `processed → processing`
  2. Remove old stats (delta subtraction)
  3. Delete old sentences
  4. Run NLP again
  5. Add new stats (delta addition)
  6. Set status: `processing → processed`

**Implementation:**
- `ProcessService.reprocess_document(session, doc_id, use_gpu, use_mock)`
- UI: "Re-process" button (enabled only for processed docs)

### 3. Incremental Updates ⭐⭐
**Problem:** Slow for large corpora (1000+ docs).

**Solution:**
- Never recalculate from scratch
- Always use delta approach:
  - Add doc: `project_stat += doc_stat`
  - Remove doc: `project_stat -= doc_stat`
- Use SQL UPDATE instead of DELETE+INSERT

**Implementation:**
- Optimize `ProcessService._update_lemma_stats()` for delta
- Add `_add_document_stats()` and `_subtract_document_stats()`

### 4. Bulk Operations ⭐
**Problem:** Processing/deleting 100 docs one-by-one is slow.

**Solution:**
- Bulk delete with single transaction
- Bulk re-process with progress tracking
- UI: multi-select + "Delete Selected", "Re-process Selected"

**Implementation:**
- `ProcessService.bulk_reprocess(session, doc_ids, ...)`
- `IngestService.bulk_delete(session, doc_ids)`
- Worker threads for background processing

---

## Database Changes

### New Queries

**Get document stats for deletion:**
```sql
SELECT lemma_id, freq_abs, first_seen_sent_id
FROM lemma_doc_stat
WHERE doc_id = ?
```

**Subtract from project stats:**
```sql
UPDATE lemma_project_stat
SET
    freq_abs = freq_abs - ?,
    doc_freq = doc_freq - 1
WHERE project_id = ? AND lemma_id = ?
```

**Delete zero-frequency lemmas:**
```sql
DELETE FROM lemma
WHERE project_id = ?
  AND lemma_id NOT IN (
    SELECT DISTINCT lemma_id FROM lemma_project_stat WHERE freq_abs > 0
  )
```

---

## Code Structure

### ProcessService Updates

**New methods:**
```python
def remove_document_stats(self, session, doc_id: int) -> bool:
    """Remove document statistics (delta subtraction)."""

def reprocess_document(self, session, doc_id: int, use_gpu=False, use_mock=False) -> bool:
    """Re-process document with automatic delta update."""

def bulk_reprocess(self, session, doc_ids: List[int], ...) -> tuple[int, int]:
    """Bulk re-process multiple documents."""
```

**Updated methods:**
```python
def _update_lemma_stats(self, session, project_id, doc_id, lemmas, operation='add'):
    """Update stats with add/subtract operation."""
```

### IngestService Updates

**Updated methods:**
```python
def delete_document(self, session, doc_id: int) -> bool:
    """Delete document with delta statistics update."""
    # 1. Remove stats first
    # 2. Delete sentences
    # 3. Delete document
    # 4. Delete file
```

**New methods:**
```python
def bulk_delete(self, session, doc_ids: List[int]) -> tuple[int, int]:
    """Bulk delete documents with stats update."""
```

### UI Updates

**DocumentsView:**
- [x] "Process with NLP" - already exists
- [ ] "Re-process" button (enabled only for processed docs)
- [ ] Multi-select support
- [ ] "Delete Selected" for bulk delete
- [ ] Context menu: Process, Re-process, Delete

**Workers:**
- [x] ProcessWorker - already exists
- [ ] ReprocessWorker (similar to ProcessWorker)
- [ ] DeleteWorker (for bulk delete with progress)

---

## Acceptance Criteria

- [ ] Delete document → statistics updated correctly
- [ ] Delete document → zero-frequency lemmas removed
- [ ] Re-process document → old stats removed, new stats added
- [ ] Re-process document → status transitions correctly
- [ ] Bulk delete (10 docs) → single transaction, progress shown
- [ ] Bulk re-process (10 docs) → background worker, progress shown
- [ ] Error during delete → rollback, document not deleted
- [ ] Error during re-process → status set to 'failed', old stats preserved

---

## Testing

**Test script:** `test_m4.py`

**Test cases:**
1. Import 3 documents, process them
2. Delete 1 document → verify stats updated
3. Re-process 1 document → verify stats recalculated
4. Bulk delete 2 documents → verify transaction
5. Error during delete → verify rollback

**Manual testing:**
1. GUI: Import documents
2. GUI: Process with NLP
3. GUI: View Dictionary (note top lemmas)
4. GUI: Delete a document
5. GUI: Refresh Dictionary → verify lemmas updated
6. GUI: Re-process a document
7. GUI: Refresh Dictionary → verify lemmas updated

---

## Implementation Order

### Phase 1: Core Delta Statistics (2-3 hours)
1. ✅ Plan created
2. [ ] Implement `ProcessService.remove_document_stats()`
3. [ ] Implement delta subtraction logic
4. [ ] Update `IngestService.delete_document()`
5. [ ] Test with `test_m4.py`

### Phase 2: Re-processing (1-2 hours)
1. [ ] Implement `ProcessService.reprocess_document()`
2. [ ] Add "Re-process" button to DocumentsView
3. [ ] Test re-processing workflow

### Phase 3: Bulk Operations (1-2 hours)
1. [ ] Implement `ProcessService.bulk_reprocess()`
2. [ ] Implement `IngestService.bulk_delete()`
3. [ ] Add multi-select to DocumentsView
4. [ ] Add "Delete Selected" button
5. [ ] Test bulk operations

### Phase 4: Testing & Polish (1 hour)
1. [ ] Create comprehensive `test_m4.py`
2. [ ] Manual GUI testing
3. [ ] Edge cases (empty corpus, all docs deleted, etc.)
4. [ ] Documentation

---

## Files to Create/Modify

**New files:**
- `test_m4.py` - Test script
- `M4_COMPLETE.md` - Completion documentation

**Modified files:**
- `app/services/process_service.py` - Add delta methods
- `app/services/ingest_service.py` - Update delete method
- `app/ui/documents_view.py` - Add re-process button, multi-select
- `app/ui/workers.py` - Add ReprocessWorker, DeleteWorker (optional)

**Estimated lines added:** ~400-500 lines

---

## Risk Assessment

**Low Risk:**
- Delta statistics logic is straightforward (add/subtract)
- All operations are transactional
- Rollback on error

**Medium Risk:**
- Edge case: deleting last document with a lemma
- Edge case: concurrent re-processing
- Performance: bulk operations on 1000+ docs

**Mitigation:**
- Thorough testing with edge cases
- Transaction isolation
- Progress reporting for long operations

---

## Next Steps After M4

**M5: MWE Extraction** (5-6 days)
- N-gram extraction
- PMI/T-score calculation
- Collocation detection

**M6: Concordance** (3-4 days)
- KWIC search
- FTS5 integration
- Context display

---

**Ready to implement:** Phase 1 - Core Delta Statistics
