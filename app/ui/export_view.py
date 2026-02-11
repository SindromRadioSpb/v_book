"""Export view - export to various formats (M9)."""
import logging
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QFileDialog,
    QProgressBar,
    QMessageBox,
)
from PyQt6.QtCore import Qt

from app.ui.workers import ExportWorker

logger = logging.getLogger(__name__)


class ExportView(QWidget):
    """Export view for various formats (M9)."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.export_worker = None
        self.last_export_dir = str(Path.home())
        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Title
        title = QLabel("Export Center")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        # Format selection group
        format_group = QGroupBox("Export Format")
        format_layout = QVBoxLayout()

        self.format_buttons = QButtonGroup(self)
        formats = [
            ("csv", "CSV (Comma-Separated Values)", ".csv"),
            ("json", "JSON Lines", ".jsonl"),
            ("xlsx", "Excel (Multi-sheet with statistics)", ".xlsx"),
            ("tbx", "TBX (TermBase eXchange)", ".tbx"),
            ("tmx", "TMX (Translation Memory eXchange)", ".tmx"),
        ]

        self.format_data = {}
        for i, (fmt_key, fmt_label, ext) in enumerate(formats):
            radio = QRadioButton(fmt_label)
            self.format_buttons.addButton(radio, i)
            self.format_data[i] = (fmt_key, ext)
            format_layout.addWidget(radio)
            if i == 0:  # Default to CSV
                radio.setChecked(True)

        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        # Options group
        options_group = QGroupBox("Export Options")
        options_layout = QVBoxLayout()

        self.approved_only_cb = QCheckBox("TBX: Export only approved terms")
        self.approved_only_cb.setChecked(True)
        self.approved_only_cb.setToolTip("Only export terms with 'approved' curation status")
        options_layout.addWidget(self.approved_only_cb)

        self.include_draft_cb = QCheckBox("TMX: Include draft translations")
        self.include_draft_cb.setChecked(False)
        self.include_draft_cb.setToolTip("Include translations with 'draft' status")
        options_layout.addWidget(self.include_draft_cb)

        self.include_pinned_cb = QCheckBox("TBX/TMX: Include pinned translations")
        self.include_pinned_cb.setChecked(True)
        self.include_pinned_cb.setToolTip("Include user-pinned translations from M8 curation")
        options_layout.addWidget(self.include_pinned_cb)

        # Task 11: Noise filtering options
        options_layout.addWidget(QLabel(""))  # Spacer
        self.exclude_noise_cb = QCheckBox("Exclude noise items (punctuation, numbers, symbols)")
        self.exclude_noise_cb.setChecked(True)  # Default: exclude noise
        self.exclude_noise_cb.setToolTip("Exclude lemmas and terms marked as noise from export")
        options_layout.addWidget(self.exclude_noise_cb)

        self.show_classification_cb = QCheckBox("Include classification columns (entity_class, is_noise, noise_reason)")
        self.show_classification_cb.setChecked(False)  # Default: don't show
        self.show_classification_cb.setToolTip("Add columns showing entity classification and noise status")
        options_layout.addWidget(self.show_classification_cb)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Export button
        button_layout = QHBoxLayout()
        self.export_btn = QPushButton("Export...")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.clicked.connect(self.on_export_clicked)
        button_layout.addWidget(self.export_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        # Progress
        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status/result
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("padding: 10px; font-size: 12px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()
        self.setLayout(layout)

    def get_selected_format(self):
        """Get currently selected format."""
        selected_id = self.format_buttons.checkedId()
        return self.format_data.get(selected_id, ("csv", ".csv"))

    def get_export_options(self, format_key):
        """Get export options based on format."""
        options = {}

        # Task 11: Noise filtering options (apply to all formats)
        options["exclude_noise"] = self.exclude_noise_cb.isChecked()
        options["include_classification"] = self.show_classification_cb.isChecked()

        # Format-specific options
        if format_key == "tbx":
            options["approved_only"] = self.approved_only_cb.isChecked()
            options["include_pinned"] = self.include_pinned_cb.isChecked()
        elif format_key == "tmx":
            options["include_draft"] = self.include_draft_cb.isChecked()
            options["include_pinned"] = self.include_pinned_cb.isChecked()
        elif format_key == "xlsx":
            # XLSX also uses these options
            pass
        return options

    def on_export_clicked(self):
        """Handle export button click."""
        format_key, extension = self.get_selected_format()

        # File dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export as {format_key.upper()}",
            os.path.join(self.last_export_dir, f"export{extension}"),
            f"{format_key.upper()} Files (*{extension});;All Files (*.*)",
        )

        if not file_path:
            return

        # Remember directory
        self.last_export_dir = str(Path(file_path).parent)

        # Check if file exists and confirm overwrite
        if os.path.exists(file_path):
            reply = QMessageBox.question(
                self,
                "Confirm Overwrite",
                f"File already exists:\n{file_path}\n\nDo you want to overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Start export
        self.start_export(format_key, file_path)

    def start_export(self, format_key, file_path):
        """Start export worker."""
        export_options = self.get_export_options(format_key)

        self.export_worker = ExportWorker(
            self.project_id, file_path, format_key, **export_options
        )

        # Connect signals
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.export_complete.connect(self.on_export_complete)
        self.export_worker.error.connect(self.on_export_error)

        # Update UI
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.status_label.setText("")
        self.progress_label.setText(f"Exporting to {file_path}...")

        # Start worker
        self.export_worker.start()

    def on_export_progress(self, message):
        """Handle progress update."""
        self.progress_label.setText(message)

    def on_export_complete(self, count, file_path):
        """Handle export completion."""
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")

        self.status_label.setText(
            f"✓ Export completed successfully!\n\n"
            f"Entries exported: {count}\n"
            f"File: {file_path}"
        )
        self.status_label.setStyleSheet("padding: 10px; font-size: 12px; color: green;")

        # Cleanup worker
        if self.export_worker:
            self.export_worker.deleteLater()
            self.export_worker = None

        # Show success message box
        QMessageBox.information(
            self,
            "Export Complete",
            f"Successfully exported {count} entries to:\n\n{file_path}",
        )

    def on_export_error(self, error_message):
        """Handle export error."""
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")

        self.status_label.setText(f"✗ Export failed:\n\n{error_message}")
        self.status_label.setStyleSheet("padding: 10px; font-size: 12px; color: red;")

        # Cleanup worker
        if self.export_worker:
            self.export_worker.deleteLater()
            self.export_worker = None

        # Show error message box
        QMessageBox.critical(
            self,
            "Export Error",
            f"An error occurred during export:\n\n{error_message}",
        )

    def on_cancel_clicked(self):
        """Handle cancel button click."""
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.export_worker.wait(3000)  # Wait up to 3 seconds

            self.export_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress_bar.setVisible(False)
            self.progress_label.setText("")
            self.status_label.setText("Export cancelled by user.")
            self.status_label.setStyleSheet("padding: 10px; font-size: 12px;")

            if self.export_worker:
                self.export_worker.deleteLater()
                self.export_worker = None

    def closeEvent(self, event):
        """Handle widget close event."""
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.export_worker.wait(3000)
        event.accept()
