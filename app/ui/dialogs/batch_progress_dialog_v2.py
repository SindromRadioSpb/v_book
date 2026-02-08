"""Batch Progress Dialog V2 - PATCH-02.

Improved progress dialog with stage support and better UX.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal


class BatchProgressDialogV2(QDialog):
    """Progress dialog for batch translation V2."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None, total: int = 0):
        """Initialize dialog.

        Args:
            parent: Parent widget
            total: Total number of items
        """
        super().__init__(parent)
        self.total = total
        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Batch Translation")
        self.setMinimumWidth(450)
        self.setModal(True)

        layout = QVBoxLayout()

        # Stage label
        self.stage_label = QLabel("Initializing...")
        self.stage_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 8px;")
        layout.addWidget(self.stage_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total if self.total > 0 else 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel(f"0 of {self.total} completed")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        layout.addWidget(self.status_label)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Counts (succeeded/failed/skipped)
        counts_layout = QHBoxLayout()

        self.succeeded_label = QLabel("✓ Succeeded: 0")
        self.succeeded_label.setStyleSheet("color: #4caf50; padding: 4px;")
        counts_layout.addWidget(self.succeeded_label)

        self.failed_label = QLabel("✗ Failed: 0")
        self.failed_label.setStyleSheet("color: #f44336; padding: 4px;")
        counts_layout.addWidget(self.failed_label)

        self.skipped_label = QLabel("⊘ Skipped: 0")
        self.skipped_label.setStyleSheet("color: #ff9800; padding: 4px;")
        counts_layout.addWidget(self.skipped_label)

        counts_layout.addStretch()
        layout.addLayout(counts_layout)

        # Cancel button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def update_stage(self, stage: str):
        """Update stage description.

        Args:
            stage: Stage description (e.g., "Translating...", "Writing...")
        """
        self.stage_label.setText(stage)

    def update_progress(self, completed: int, total: int):
        """Update progress bar.

        Args:
            completed: Number of completed items
            total: Total number of items
        """
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)
            self.status_label.setText(f"{completed} of {total} completed")

    def update_counts(self, succeeded: int, skipped: int, failed: int):
        """Update success/failed/skipped counts.

        Args:
            succeeded: Number of succeeded items
            skipped: Number of skipped items
            failed: Number of failed items
        """
        self.succeeded_label.setText(f"✓ Succeeded: {succeeded}")
        self.failed_label.setText(f"✗ Failed: {failed}")
        self.skipped_label.setText(f"⊘ Skipped: {skipped}")

    def set_completed(self):
        """Mark as completed (disable cancel, update UI)."""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Close")
        self.cancel_btn.clicked.disconnect()
        self.cancel_btn.clicked.connect(self.accept)
        self.stage_label.setText("✓ Translation complete!")
        self.stage_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; padding: 8px; color: #4caf50;"
        )

    def on_cancel(self):
        """Handle cancel button click."""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling...")
        self.stage_label.setText("Cancelling...")
        self.cancel_requested.emit()


def show_batch_progress_dialog_v2(parent=None, total: int = 0) -> BatchProgressDialogV2:
    """Show batch progress dialog and return instance.

    Args:
        parent: Parent widget
        total: Total number of items

    Returns:
        BatchProgressDialogV2 instance
    """
    dialog = BatchProgressDialogV2(parent, total)
    dialog.show()
    return dialog
