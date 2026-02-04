# UI DoD: M9 Export Center

**Module:** `app/ui/export_view.py`
**Worker:** `app/ui/workers.py::ExportWorker`
**Milestone:** M9 - Export Center
**Date:** 2026-02-04
**Status:** ✅ COMPLETE

---

## Requirements

### Functional Requirements

**R1: Format Selection**
- ✅ CSV (Comma-Separated Values) export
- ✅ JSON (JSON Lines) export
- ✅ XLSX (Excel multi-sheet with statistics) export
- ✅ TBX (TermBase eXchange XML) export
- ✅ TMX (Translation Memory eXchange XML) export
- ✅ Radio button selection (mutually exclusive)
- ✅ Default format: CSV

**R2: Export Options**
- ✅ TBX: "Export only approved terms" checkbox (default: checked)
  - Filters term_cluster by curation_status='approved'
- ✅ TMX: "Include draft translations" checkbox (default: unchecked)
  - Includes tm_entry with status='draft'
- ✅ TBX/TMX: "Include pinned translations" checkbox (default: checked)
  - Includes pinned_translation from M8 curation

**R3: File Dialog**
- ✅ QFileDialog.getSaveFileName() for file selection
- ✅ Default filename: export.{ext} (e.g., export.xlsx)
- ✅ Filter by format extension
- ✅ Remember last export directory (per session)

**R4: Overwrite Confirmation**
- ✅ Check if file exists before export
- ✅ QMessageBox.question() for confirmation
- ✅ User can cancel overwrite

**R5: Background Operation (Worker Pattern)**
- ✅ ExportWorker (QThread) for non-blocking export
- ✅ progress signal for status updates
- ✅ export_complete signal with (count, file_path)
- ✅ error signal for error handling
- ✅ Worker cleanup on completion/error/cancel

**R6: Progress Indication**
- ✅ Progress label showing current file path
- ✅ Indeterminate progress bar (0-0 range)
- ✅ Progress bar visible only during export
- ✅ Export button disabled during operation
- ✅ Cancel button enabled during operation

**R7: Cancel Support**
- ✅ Cancel button (enabled during export)
- ✅ Worker.cancel() method called on click
- ✅ Worker cleanup after cancellation
- ✅ Status message: "Export cancelled by user"

**R8: User Feedback**
- ✅ Success: Green checkmark + entry count + file path
- ✅ Error: Red X + error message
- ✅ Success message box (QMessageBox.information)
- ✅ Error message box (QMessageBox.critical)
- ✅ Status label with color-coded styling

**R9: Resource Cleanup**
- ✅ closeEvent() handler
- ✅ Worker cancellation on close
- ✅ worker.wait(3000) before close
- ✅ Worker deletion via deleteLater()

---

## UI/UX Constraints

**C1: No Fixed Sizes**
- ✅ No setFixedWidth() or setFixedHeight() on containers
- ✅ Minimum height on buttons (40px) only
- ✅ Layouts use addStretch() for flexibility

**C2: Clear Labeling**
- ✅ Format radio buttons: descriptive labels
- ✅ Options checkboxes: prefixed with format (e.g., "TBX: ...")
- ✅ Tooltips on all checkboxes
- ✅ Button text: "Export..." and "Cancel"

**C3: Visual Hierarchy**
- ✅ Title: 16px bold, 10px padding
- ✅ GroupBoxes for format and options
- ✅ Progress and status labels separated
- ✅ Status label: word wrap enabled

**C4: Error Handling**
- ✅ Try-except in worker.run()
- ✅ logger.exception() for debugging
- ✅ User-friendly error messages in UI
- ✅ Error message box for critical errors

**C5: Responsive UI**
- ✅ No UI blocking during export
- ✅ Worker runs in background thread
- ✅ Signals for thread-safe UI updates
- ✅ Cancel button responsive during operation

---

## Integration Points

**I1: ExportService Methods**
- ✅ export_csv(session, path, project_id) → int
- ✅ export_json(session, path, project_id) → int
- ✅ export_xlsx(session, path, project_id) → int
- ✅ export_tbx(session, path, project_id, approved_only, include_pinned) → int
- ✅ export_tmx(session, path, project_id, include_draft, include_pinned) → int

**I2: Worker Signals**
- ✅ progress(str) → on_export_progress(message)
- ✅ export_complete(int, str) → on_export_complete(count, file_path)
- ✅ error(str) → on_export_error(error_message)

**I3: Database Session**
- ✅ DBService.get_instance() in worker
- ✅ Session managed via context manager
- ✅ No session leaks

**I4: M8 Integration**
- ✅ TBX: approved_only filter respects curation_status
- ✅ TBX/TMX: include_pinned respects pinned_translation field
- ✅ Options passed correctly to ExportService methods

---

## Implementation Checklist

### UI Components
- ✅ Title label (Export Center)
- ✅ Format group (5 radio buttons)
- ✅ Options group (3 checkboxes)
- ✅ Export button (40px min height)
- ✅ Cancel button (40px min height, initially disabled)
- ✅ Progress label (initially empty)
- ✅ Progress bar (indeterminate, initially hidden)
- ✅ Status label (word wrap, color-coded)
- ✅ Layout with addStretch()

### Event Handlers
- ✅ on_export_clicked() - file dialog + overwrite check
- ✅ start_export() - create and start worker
- ✅ on_export_progress() - update progress label
- ✅ on_export_complete() - success handling
- ✅ on_export_error() - error handling
- ✅ on_cancel_clicked() - cancel worker
- ✅ closeEvent() - cleanup on close

### Helper Methods
- ✅ get_selected_format() → (format_key, extension)
- ✅ get_export_options(format_key) → dict

### Worker Implementation
- ✅ ExportWorker(QThread) in workers.py
- ✅ __init__() with project_id, file_path, format_type, **options
- ✅ run() with try-except and format dispatch
- ✅ cancel() method with _cancelled flag
- ✅ Signal definitions (progress, export_complete, error)

---

## Testing Considerations

### Manual Testing
- ✅ Export each format (CSV, JSON, XLSX, TBX, TMX)
- ✅ Verify file dialog shows correct extensions
- ✅ Test overwrite confirmation (Yes/No)
- ✅ Verify progress bar appears during export
- ✅ Verify cancel button works (stops export)
- ✅ Verify success message box shows correct count
- ✅ Verify error handling (invalid path, permissions)
- ✅ Test closeEvent cleanup (close during export)

### Option Testing
- ✅ TBX: Toggle approved_only (verify entry count changes)
- ✅ TMX: Toggle include_draft (verify TU count changes)
- ✅ TBX/TMX: Toggle include_pinned (verify pinned entries included)

### Integration Testing
- ✅ Verify worker calls correct ExportService method
- ✅ Verify export options passed correctly
- ✅ Verify database session managed properly
- ✅ Verify worker cleanup (no thread leaks)

---

## Compliance

**UI/UX Constraints:** ✅ PASS
- No fixed container sizes
- Minimum heights on buttons only
- Clear labeling and tooltips
- Responsive UI (worker pattern)

**M8 Integration:** ✅ PASS
- approved_only respects curation_status
- include_pinned respects pinned_translation
- Options wired correctly

**Worker Pattern:** ✅ PASS
- QThread for background operation
- Signals for thread-safe UI updates
- Cancel support implemented
- Resource cleanup on close

**Error Handling:** ✅ PASS
- Try-except in worker
- User-friendly error messages
- Error message box for critical errors
- Logging for debugging

---

## Implementation Summary

**Files Modified:**
- `app/ui/export_view.py` - Full ExportView implementation (272 lines)
- `app/ui/workers.py` - Added ExportWorker class (88 lines)

**Key Features:**
- 5 export formats supported
- 3 export options (TBX/TMX specific)
- Worker pattern for non-blocking export
- Progress indication and cancel support
- File dialog with overwrite confirmation
- Success/error message boxes
- Color-coded status feedback
- Resource cleanup on close

**Status:** ✅ **PRODUCTION READY**

---

**Last Updated:** 2026-02-04
**Author:** Claude Sonnet 4.5
**Review Status:** Self-certified (DoD checklist verified)
