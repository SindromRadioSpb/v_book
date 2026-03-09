"""Progress dialog for staged term extraction."""

from __future__ import annotations

from app.ui.dialogs.staged_operation_progress_dialog import StagedOperationProgressDialog


class TermExtractionProgressDialog(StagedOperationProgressDialog):
    """Modal progress dialog for chunked term extraction."""

    def __init__(self, parent=None, total_docs: int = 0):
        super().__init__(
            parent,
            total_docs=total_docs,
            window_title="Term Extraction",
            initial_status_text="Preparing staged extraction...",
            running_status_text="Running staged extraction...",
            paused_status_text="Paused after current batch checkpoint",
            cancel_pending_status_text="Cancelling after current checkpoint...",
            completed_status_text="Extraction completed",
            cancelled_status_text="Extraction cancelled",
            failed_status_text="Extraction failed",
            phase_status_overrides={
                "finalize": "Finalizing staged counters...",
                "resumed": "Running staged extraction...",
            },
            disable_pause_phases={"finalize", "completed", "cancelled"},
        )
