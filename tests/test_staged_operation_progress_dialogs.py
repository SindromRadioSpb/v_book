"""Direct regressions for staged long-operation progress dialogs."""

from __future__ import annotations

from app.ui.dialogs.nlp_process_progress_dialog import NLPProcessProgressDialog
from app.ui.dialogs.term_extraction_progress_dialog import TermExtractionProgressDialog


def test_nlp_progress_dialog_updates_structured_state(qtbot):
    dialog = NLPProcessProgressDialog(total_docs=5, operation_label="Processing")
    qtbot.addWidget(dialog)

    dialog.update_state(
        {
            "phase": "processing",
            "stage": "Chunk 1/2",
            "run_id": 91,
            "docs_total": 5,
            "docs_processed": 2,
            "docs_failed": 1,
            "chunks_total": 2,
            "chunks_completed": 1,
            "last_doc_id": 44,
            "message": "Processed doc_2.txt",
        }
    )

    assert dialog.stage_label.text() == "Stage: Chunk 1/2"
    assert dialog.run_label.text() == "Run ID: 91"
    assert dialog.docs_label.text() == "Docs: 3 / 5"
    assert dialog.chunks_label.text() == "Chunks: 1 / 2"
    assert dialog.last_doc_label.text() == "Last doc ID: 44"
    assert dialog.progress_bar.value() == 3
    assert "Processed doc_2.txt" in dialog.activity_log.toPlainText()
    assert dialog.status_label.text() == "Processing documents with NLP..."


def test_nlp_progress_dialog_manual_pause_resume_and_completion(qtbot):
    dialog = NLPProcessProgressDialog(total_docs=2, operation_label="Re-processing")
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.pause_requested, timeout=1000):
        dialog.on_pause_resume()
    assert dialog.status_label.text() == "Paused after current document checkpoint"
    assert dialog.pause_btn.text() == "Resume"

    with qtbot.waitSignal(dialog.resume_requested, timeout=1000):
        dialog.on_pause_resume()
    assert dialog.status_label.text() == "Re-processing documents with NLP..."
    assert dialog.pause_btn.text() == "Pause"

    dialog.update_state(
        {
            "phase": "completed",
            "stage": "completed",
            "run_id": 92,
            "docs_total": 2,
            "docs_processed": 2,
            "docs_failed": 0,
            "chunks_total": 2,
            "chunks_completed": 2,
            "last_doc_id": 20,
            "message": "NLP batch run completed",
        }
    )

    assert dialog.status_label.text() == "Re-processing completed"
    assert dialog.pause_btn.isEnabled() is False


def test_nlp_progress_dialog_cancel_appends_pending_activity(qtbot):
    dialog = NLPProcessProgressDialog(total_docs=2, operation_label="Re-processing")
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog.cancel_requested, timeout=1000):
        dialog.on_cancel()

    assert dialog.cancel_btn.isEnabled() is False
    assert dialog.pause_btn.isEnabled() is False
    assert dialog.status_label.text() == "Cancelling after current document checkpoint..."
    assert "Cancelling after current document checkpoint..." in dialog.activity_log.toPlainText()


def test_term_extraction_progress_dialog_finalize_state(qtbot):
    dialog = TermExtractionProgressDialog(total_docs=4)
    qtbot.addWidget(dialog)

    dialog.update_state(
        {
            "phase": "finalize",
            "stage": "Persisting staged counters",
            "run_id": 15,
            "docs_total": 4,
            "docs_processed": 4,
            "docs_failed": 0,
            "chunks_total": 2,
            "chunks_completed": 2,
            "last_doc_id": 81,
            "message": "Finalizing clusters",
        }
    )

    assert dialog.stage_label.text() == "Stage: Persisting staged counters"
    assert dialog.status_label.text() == "Finalizing staged counters..."
    assert dialog.pause_btn.isEnabled() is False
    assert "Finalizing clusters" in dialog.activity_log.toPlainText()


def test_term_extraction_progress_dialog_paused_and_resumed_phase_updates(qtbot):
    dialog = TermExtractionProgressDialog(total_docs=3)
    qtbot.addWidget(dialog)

    dialog.update_state(
        {
            "phase": "paused",
            "stage": "Collecting batch 1/2",
            "run_id": 16,
            "docs_total": 3,
            "docs_processed": 1,
            "docs_failed": 0,
            "chunks_total": 2,
            "chunks_completed": 1,
            "last_doc_id": 11,
            "message": "Paused at safe checkpoint",
        }
    )
    assert dialog.status_label.text() == "Paused after current batch checkpoint"

    dialog.update_state(
        {
            "phase": "resumed",
            "stage": "Collecting batch 2/2",
            "run_id": 16,
            "docs_total": 3,
            "docs_processed": 1,
            "docs_failed": 0,
            "chunks_total": 2,
            "chunks_completed": 1,
            "last_doc_id": 11,
            "message": "Resumed staged extraction",
        }
    )
    assert dialog.status_label.text() == "Running staged extraction..."
