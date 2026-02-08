# Integration Guide: Batch Translate V2

## Overview

This guide shows how to integrate BatchTranslateEngineV2 into Dictionary and Terms tabs.

## Quick Integration (Minimal Changes)

### Dictionary View

Replace `on_batch_translate()` method:

```python
def on_batch_translate(self):
    """Batch translate selected lemmas using V2 engine."""
    from app.ui.workers_batch_v2 import BatchTranslateWorkerV2
    from app.ui.dialogs.batch_progress_dialog_v2 import show_batch_progress_dialog_v2
    from app.services.batch_translate_engine_v2 import (
        BatchTranslateItem,
        BatchTranslateOptions,
    )
    from app.ui.dialogs.batch_translate_dialog import show_batch_translate_dialog

    # Get selected rows
    selected_indexes = self.lemma_table.selectionModel().selectedRows()
    if not selected_indexes:
        return

    # Build items list
    items = []
    for index in selected_indexes:
        source_row = self.proxy_model.map_to_source_row(index.row())
        lemma = self.lemma_model.lemmas[source_row]
        item = BatchTranslateItem(
            entity_type="lemma",
            entity_id=lemma.lemma_text,
            source_text=lemma.lemma_text,
            src_lang="he",
            tgt_lang="ru",
            current_translation=lemma.translation,
            project_id=self.project_id,
        )
        items.append(item)

    # Show dialog
    accepted, provider_mode, write_mode = show_batch_translate_dialog(
        parent=self,
        selected_count=len(items),
    )

    if not accepted:
        return

    # Create options
    options = BatchTranslateOptions(
        provider_mode=provider_mode,
        write_mode=write_mode,
        chunk_size=50,
    )

    # Show progress dialog
    progress_dialog = show_batch_progress_dialog_v2(parent=self, total=len(items))

    # Create worker V2
    worker = BatchTranslateWorkerV2(
        items=items,
        options=options,
        tab_type="dictionary",
    )

    # Connect signals
    worker.progress.connect(progress_dialog.update_progress)
    worker.stage_changed.connect(progress_dialog.update_stage)
    worker.finished.connect(lambda result: self.on_batch_finished(result, progress_dialog))
    worker.error.connect(lambda error: self.on_batch_error(error, progress_dialog))
    progress_dialog.cancel_requested.connect(worker.cancel)

    # Start worker
    worker.start()

    # Keep reference
    self._batch_worker = worker


def on_batch_finished(self, result, progress_dialog):
    """Handle batch complete."""
    from PyQt6.QtWidgets import QMessageBox

    # Update progress dialog
    progress_dialog.set_completed()
    progress_dialog.update_counts(result.succeeded, result.skipped, result.failed)

    # Show summary
    msg = f"Translation completed!\n\n"
    msg += f"Total: {result.total}\n"
    msg += f"Succeeded: {result.succeeded}\n"
    msg += f"Skipped: {result.skipped}\n"
    msg += f"Failed: {result.failed}"

    if result.failed > 0:
        QMessageBox.warning(self, "Translation Complete (with errors)", msg)
    else:
        QMessageBox.information(self, "Translation Complete", msg)

    # Refresh
    self.load_lemmas()

    # Clean up
    progress_dialog.accept()
    if hasattr(self, '_batch_worker'):
        self._batch_worker.deleteLater()
        del self._batch_worker


def on_batch_error(self, error_msg, progress_dialog):
    """Handle batch error."""
    from PyQt6.QtWidgets import QMessageBox

    progress_dialog.reject()
    QMessageBox.critical(self, "Translation Error", error_msg)

    if hasattr(self, '_batch_worker'):
        self._batch_worker.deleteLater()
        del self._batch_worker
```

### Terms View

Similar changes as Dictionary, but use:

```python
item = BatchTranslateItem(
    entity_type="term_cluster",
    entity_id=cluster.representative_he,
    source_text=cluster.representative_he,
    src_lang="he",
    tgt_lang="ru",
    current_translation=cluster.pinned_translation,  # Note: pinned_translation
    project_id=self.project_id,
)
```

## Migration Strategy

1. **Keep Old Code**: Don't delete old batch_mt_translate_service.py yet
2. **Test V2**: Use E2E test script to verify
3. **Gradual Rollout**:
   - First: Test with Dictionary tab
   - Then: Test with Terms tab
   - Finally: Remove old code

## Testing Checklist

- [ ] Dictionary: 10 rows → force provider: local_nllb → fill empty only
- [ ] Terms: 10 rows → same settings
- [ ] Cancel works mid-translation
- [ ] Error messages clear
- [ ] Progress updates smoothly
- [ ] UI stays responsive

## Rollback Plan

If V2 has issues:

1. Revert dictionary_view.py / terms_view.py changes
2. Keep using old BatchMTTranslateService
3. Debug V2 offline
4. Fix and retry

## Next Steps

1. Run E2E test: `python scripts/test_batch_translate_e2e_v2.py`
2. Manual UI test
3. If successful → update Dictionary/Terms views
4. Commit all changes
