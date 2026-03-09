"""Progress dialog for staged NLP processing."""

from __future__ import annotations

from app.ui.dialogs.staged_operation_progress_dialog import StagedOperationProgressDialog


class NLPProcessProgressDialog(StagedOperationProgressDialog):
    """Modal progress dialog for resumable NLP processing."""

    def __init__(self, parent=None, total_docs: int = 0, operation_label: str = "Processing"):
        self.operation_label = str(operation_label or "Processing")
        super().__init__(
            parent,
            total_docs=total_docs,
            window_title=f"{self.operation_label} with NLP",
            initial_status_text=f"{self.operation_label} documents with NLP...",
            running_status_text=f"{self.operation_label} documents with NLP...",
            paused_status_text="Paused after current document checkpoint",
            cancel_pending_status_text="Cancelling after current document checkpoint...",
            completed_status_text=f"{self.operation_label} completed",
            cancelled_status_text=f"{self.operation_label} cancelled",
            failed_status_text=f"{self.operation_label} failed",
        )
