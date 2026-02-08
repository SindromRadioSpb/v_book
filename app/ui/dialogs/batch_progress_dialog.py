"""Batch Progress Dialog - PATCH-UI-BATCH-T02.

Progress dialog for batch translation with cancel support.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal


class BatchProgressDialog(QDialog):
    """Progress dialog for batch translation.

    Shows:
    - Progress bar with percentage
    - Counts: succeeded, skipped, failed, remaining
    - Cancel button for graceful cancellation
    """

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None, total: int = 0):
        """Initialize dialog.

        Args:
            parent: Parent widget
            total: Total number of items to translate
        """
        super().__init__(parent)
        self.total = total
        self.completed = 0
        self.succeeded = 0
        self.skipped = 0
        self.failed = 0
        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        self.setWindowTitle("Translating...")
        self.setMinimumWidth(400)
        self.setModal(True)

        # Disable close button (only Cancel button should work)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint
        )

        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        self.header_label = QLabel("Translating rows...")
        self.header_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        header_layout.addWidget(self.cancel_btn)

        layout.addLayout(header_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m (%p%)")
        layout.addWidget(self.progress_bar)

        # Counts group
        counts_group = QGroupBox("Status")
        counts_layout = QVBoxLayout()

        self.succeeded_label = QLabel("Succeeded: 0")
        self.succeeded_label.setStyleSheet("color: #4caf50;")
        counts_layout.addWidget(self.succeeded_label)

        self.skipped_label = QLabel("Skipped: 0")
        self.skipped_label.setStyleSheet("color: #ff9800;")
        counts_layout.addWidget(self.skipped_label)

        self.failed_label = QLabel("Failed: 0")
        self.failed_label.setStyleSheet("color: #f44336;")
        counts_layout.addWidget(self.failed_label)

        self.remaining_label = QLabel(f"Remaining: {self.total}")
        counts_layout.addWidget(self.remaining_label)

        counts_group.setLayout(counts_layout)
        layout.addWidget(counts_group)

        self.setLayout(layout)

    def update_progress(self, completed: int, total: int):
        """Update progress bar and completed count.

        Args:
            completed: Number of completed items
            total: Total number of items
        """
        self.completed = completed
        self.total = total
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(completed)

        remaining = total - completed
        self.remaining_label.setText(f"Remaining: {remaining}")

        # Update header percentage
        if total > 0:
            percent = int((completed / total) * 100)
            self.header_label.setText(f"Translating rows... {percent}%")

    def update_counts(self, succeeded: int, skipped: int, failed: int):
        """Update status counts.

        Args:
            succeeded: Number of succeeded translations
            skipped: Number of skipped rows
            failed: Number of failed translations
        """
        self.succeeded = succeeded
        self.skipped = skipped
        self.failed = failed

        self.succeeded_label.setText(f"Succeeded: {succeeded}")
        self.skipped_label.setText(f"Skipped: {skipped}")
        self.failed_label.setText(f"Failed: {failed}")

    def on_cancel(self):
        """Handle cancel button click."""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling...")
        self.header_label.setText("Cancelling... (finishing current item)")
        self.cancel_requested.emit()

    def set_completed(self):
        """Mark dialog as completed (disable cancel, update header)."""
        self.cancel_btn.setEnabled(False)
        self.header_label.setText("Translation complete!")

        # Update progress to 100%
        self.progress_bar.setValue(self.total)

    def closeEvent(self, event):
        """Prevent closing via X button (only Cancel button works)."""
        event.ignore()
