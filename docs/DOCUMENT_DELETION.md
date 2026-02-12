# Document Deletion - Fixed and Improved

## Overview

Document deletion in Documents view now fully supports single and bulk deletion with proper safeguards.

## Problems Fixed

### 1. ❌ Only ONE document deleted (even when multiple selected)
**Before:**
```python
row = min(selected_rows)  # Only took first row!
doc_id = int(self.docs_table.item(row, 0).text())
# Deleted only ONE document
```

**After:**
```python
# Collect ALL selected documents
for row in selected_rows:
    doc_id = int(self.docs_table.item(row, 0).text())
    doc_ids.append(doc_id)

# Use bulk_delete for multiple documents
success_count, error_count = self.ingest_service.bulk_delete(session, doc_ids)
```

### 2. ❌ Delete button NOT disabled for reference corpus
**Before:**
- Add Files / Add Folder blocked ✅
- Delete NOT blocked ❌

**After:**
```python
def _configure_reference_corpus_ui(self):
    # Disable delete button
    self.delete_btn.setEnabled(False)
    self.delete_btn.setToolTip("Cannot delete documents from reference corpus (read-only)")
```

### 3. ❌ Generic error handling
**Before:**
```python
except Exception as e:  # Too generic!
    show_error(self, "Error", f"Failed to delete: {e}")
```

**After:**
```python
except ReferenceCorpusReadonlyError as e:
    # Specific handling for reference corpus
    show_error(self, "Reference Corpus", f"Cannot delete...\n\n{str(e)}")
except Exception as e:
    # Generic fallback
    show_error(self, "Error", f"Failed to delete: {e}")
```

### 4. ❌ Confirmation dialog doesn't show count
**Before:**
- "Delete document 'file.txt'?" - even for 10 selected documents

**After:**
- Single: "Delete document 'file.txt'?"
- Multiple: "Delete 5 documents?\n\nDocuments:\n• file1.txt\n• file2.txt\n..."

## Features

### Single Document Deletion
1. Select one document
2. Click "Delete" button
3. Confirm: "Delete document 'filename.txt'?"
4. Success message: "Document deleted: filename.txt"

### Bulk Document Deletion
1. Select multiple documents (Ctrl+Click or Shift+Click)
2. Click "Delete" button
3. Confirm: "Delete N documents?" with list (up to 5 shown)
4. Success summary: "Successfully deleted N document(s)"
5. Partial success: "Deleted: X\nFailed: Y\n\nCheck logs for details."

### Reference Corpus Protection
- Delete button **disabled** for reference corpus
- UI tooltip: "Cannot delete documents from reference corpus (read-only)"
- Safety check in code prevents deletion even if UI bypassed
- Clear error message if attempted

## Usage Examples

### Delete Single Document
```
1. Select document in table
2. Click "Delete"
3. Confirm dialog: "Delete document 'test.txt'?"
4. Click "Yes"
5. Success: "Document deleted: test.txt"
```

### Delete Multiple Documents
```
1. Select 5 documents (Ctrl+Click)
2. Click "Delete"
3. Confirm dialog:
   "Delete 5 documents?

   Documents:
   • file1.txt
   • file2.txt
   • file3.txt
   • file4.txt
   • file5.txt"
4. Click "Yes"
5. Success: "Successfully deleted 5 document(s)"
```

### Bulk Delete with Partial Failure
```
1. Select 10 documents
2. Click "Delete"
3. Confirm and proceed
4. Result: "Deleted: 8\nFailed: 2\n\nCheck logs for details."
   (e.g., 2 documents may be locked by another process)
```

### Reference Corpus (Blocked)
```
1. Open reference corpus (e.g., Hebrew Wikipedia)
2. Select documents
3. Delete button is DISABLED (grayed out)
4. Tooltip: "Cannot delete documents from reference corpus (read-only)"
```

## Technical Details

**Backend (IngestService):**
- `delete_document(session, doc_id)` - Single document
- `bulk_delete(session, doc_ids)` - Multiple documents
- Both check for reference corpus and raise `ReferenceCorpusReadonlyError`

**Frontend (DocumentsView):**
- Collects all selected document IDs
- Uses bulk_delete for efficiency (single transaction per document)
- Shows progress and summary
- Graceful error handling

**Safety Layers:**
1. UI blocks Delete button for reference corpus
2. `on_delete()` has safety check at start
3. `IngestService.delete_document()` validates corpus type
4. Database constraints prevent orphaned records (CASCADE)

## Code Changes

**Files Modified:**
- `app/ui/documents_view.py`
  - `_configure_reference_corpus_ui()` - Disable delete button
  - `on_selection_changed()` - Check reference corpus before enabling
  - `on_delete()` - Complete rewrite for bulk support

**Lines Changed:** ~100 lines
**Backward Compatible:** Yes (API unchanged)

## Testing

**Manual Tests:**
1. ✅ Single document delete
2. ✅ Multiple documents delete (2, 5, 10, 50)
3. ✅ Reference corpus delete blocked (UI + backend)
4. ✅ Confirmation dialogs (single vs multiple)
5. ✅ Success messages (single vs bulk)
6. ✅ Partial failure handling (manual file lock)

**Automated Tests:**
- Import validation: PASSED
- Syntax check: PASSED
- bulk_delete presence: VERIFIED
- ReferenceCorpusReadonlyError handling: VERIFIED

## Migration Notes

**From Previous Behavior:**
- **Before:** Only first document deleted (silent bug!)
- **After:** ALL selected documents deleted
- **User Impact:** Expected behavior now matches actual behavior

**No Database Migration Required**
- Uses existing `IngestService.bulk_delete()` method
- No schema changes

## Future Enhancements

Potential improvements (not implemented):
- Undo delete (30-second grace period)
- Progress bar for large bulk deletes (>100 documents)
- Context menu "Delete" action
- Keyboard shortcut (Delete key)
- Bulk delete warning threshold ("Are you sure you want to delete 500 documents?")
