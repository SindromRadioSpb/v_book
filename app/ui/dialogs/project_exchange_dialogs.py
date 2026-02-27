"""Dialogs for project export/import operations."""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QFormLayout,
    QMessageBox,
    QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from app.services.project_exchange.dto import ExportReport, ImportReport, ManifestInfo

logger = logging.getLogger(__name__)


class ExportProgressDialog(QDialog):
    """Progress dialog for project export."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Project Bundle")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._report = None
        self.init_ui()

    def init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)

        # Stage label
        self.stage_label = QLabel("Preparing export...")
        layout.addWidget(self.stage_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Details text (initially hidden)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        self.details_text.setVisible(False)
        layout.addWidget(self.details_text)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_button)

        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self.on_open_folder)
        button_layout.addWidget(self.open_folder_button)

        self.copy_report_button = QPushButton("Copy Report")
        self.copy_report_button.setVisible(False)
        self.copy_report_button.clicked.connect(self.on_copy_report)
        button_layout.addWidget(self.copy_report_button)

        self.close_button = QPushButton("Close")
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.accept)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def update_progress(self, stage: str, current: int, total: int):
        """Update progress bar and stage label."""
        self.stage_label.setText(stage)
        if total > 0:
            self.progress_bar.setValue(int(current * 100 / total))

    def set_completed(self, report: ExportReport):
        """Mark export as completed and show summary."""
        self._report = report

        if report.success:
            self.stage_label.setText("Export completed successfully!")
            self.progress_bar.setValue(100)

            # Show details
            summary = self._format_export_report(report)
            self.details_text.setPlainText(summary)
            self.details_text.setVisible(True)

            # Show completion buttons
            self.cancel_button.setVisible(False)
            self.open_folder_button.setVisible(True)
            self.copy_report_button.setVisible(True)
            self.close_button.setVisible(True)
        else:
            error_text_raw = report.error_message or "Export failed"
            is_cancelled = "cancel" in error_text_raw.lower()
            self.stage_label.setText("Export cancelled" if is_cancelled else "Export failed")
            self.progress_bar.setValue(0)

            # Show error
            error_text = f"Error: {error_text_raw}"
            self.details_text.setPlainText(error_text)
            self.details_text.setVisible(True)

            # Show close button
            self.cancel_button.setVisible(False)
            self.copy_report_button.setVisible(True)
            self.close_button.setVisible(True)

    def on_cancel(self):
        """Handle cancel button click."""
        self.cancel_requested.emit()
        self.stage_label.setText("Cancelling...")
        self.cancel_button.setEnabled(False)

    def on_open_folder(self):
        """Open the folder containing the exported bundle."""
        if self._report and self._report.bundle_path:
            import subprocess
            import sys

            folder_path = self._report.bundle_path.parent
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(self._report.bundle_path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(self._report.bundle_path)])
            else:
                subprocess.Popen(["xdg-open", str(folder_path)])

    def on_copy_report(self):
        """Copy export report to clipboard."""
        if self._report:
            text = self._format_export_report(self._report) if self._report.success else f"Error: {self._report.error_message}"
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            QMessageBox.information(self, "Copied", "Report copied to clipboard")

    def _format_export_report(self, report: ExportReport) -> str:
        """Format export report for display."""
        lines = [
            "=== Export Report ===",
            f"Bundle: {report.bundle_path}",
            f"Size: {report.bundle_path.stat().st_size / 1024 / 1024:.1f} MB" if report.bundle_path else "N/A",
            f"Time: {report.elapsed_seconds:.1f}s",
            "",
            "=== Project Metadata ===",
            f"Name: {report.manifest.project_name}",
            f"Languages: {report.manifest.project_src_lang} → {report.manifest.project_tgt_lang}",
            f"Schema version: {report.manifest.schema_version}",
            f"App version: {report.manifest.app_version}",
            f"Exported at: {report.manifest.exported_at}",
            "",
            "=== Table Counts ===",
        ]

        for table, count in sorted(report.manifest.table_counts.items()):
            if count > 0:
                lines.append(f"  {table}: {count:,}")

        total_rows = sum(report.manifest.table_counts.values())
        lines.append(f"\nTotal rows: {total_rows:,}")

        return "\n".join(lines)


class ImportPreviewDialog(QDialog):
    """Preview dialog before importing a bundle."""

    def __init__(self, manifest: ManifestInfo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Project Bundle - Preview")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.manifest = manifest
        self.custom_name = None

        self.init_ui()

    def init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)

        # Title
        title_label = QLabel("Bundle Preview")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        title_label.setFont(font)
        layout.addWidget(title_label)

        # Metadata form
        form_layout = QFormLayout()

        self.name_edit = QLineEdit(self.manifest.project_name)
        form_layout.addRow("Project Name:", self.name_edit)

        form_layout.addRow("Languages:", QLabel(f"{self.manifest.project_src_lang} → {self.manifest.project_tgt_lang}"))
        form_layout.addRow("Schema Version:", QLabel(str(self.manifest.schema_version)))
        form_layout.addRow("App Version:", QLabel(self.manifest.app_version))
        form_layout.addRow("Exported:", QLabel(self.manifest.exported_at))

        layout.addLayout(form_layout)

        # Table counts summary
        summary_label = QLabel("\nBundle Contents:")
        summary_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(summary_label)

        summary_text = QTextEdit()
        summary_text.setReadOnly(True)
        summary_text.setMaximumHeight(150)
        summary_text.setPlainText(self._format_table_counts())
        layout.addWidget(summary_text)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        import_button = QPushButton("Import")
        import_button.setDefault(True)
        import_button.clicked.connect(self.on_import)
        button_layout.addWidget(import_button)

        layout.addLayout(button_layout)

    def on_import(self):
        """Handle import button click."""
        self.custom_name = self.name_edit.text().strip()
        if not self.custom_name:
            QMessageBox.warning(self, "Invalid Name", "Project name cannot be empty")
            return
        self.accept()

    def get_custom_name(self) -> str:
        """Get the custom project name entered by user."""
        return self.custom_name

    def _format_table_counts(self) -> str:
        """Format table counts for display."""
        lines = []
        key_tables = {
            "source_document": "Documents",
            "document_sentence": "Sentences",
            "lemma": "Lemmas",
            "ngram": "N-grams",
            "term_cluster": "Term Clusters",
            "tm_entry": "TM Entries",
        }

        for table, label in key_tables.items():
            count = self.manifest.table_counts.get(table, 0)
            if count > 0:
                lines.append(f"{label}: {count:,}")

        total_rows = sum(self.manifest.table_counts.values())
        lines.append(f"\nTotal rows: {total_rows:,}")

        return "\n".join(lines)


class ImportProgressDialog(QDialog):
    """Progress dialog for project import."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Project Bundle")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._report = None
        self.init_ui()

    def init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)

        # Stage label
        self.stage_label = QLabel("Preparing import...")
        layout.addWidget(self.stage_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Details text (initially hidden)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(200)
        self.details_text.setVisible(False)
        layout.addWidget(self.details_text)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_button)

        self.open_project_button = QPushButton("Go to Project")
        self.open_project_button.setVisible(False)
        self.open_project_button.clicked.connect(self.on_open_project)
        button_layout.addWidget(self.open_project_button)

        self.copy_report_button = QPushButton("Copy Report")
        self.copy_report_button.setVisible(False)
        self.copy_report_button.clicked.connect(self.on_copy_report)
        button_layout.addWidget(self.copy_report_button)

        self.close_button = QPushButton("Close")
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.accept)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def update_progress(self, stage: str, current: int, total: int):
        """Update progress bar and stage label."""
        self.stage_label.setText(stage)
        if total > 0:
            self.progress_bar.setValue(int(current * 100 / total))

    def set_completed(self, report: ImportReport):
        """Mark import as completed and show summary."""
        self._report = report

        if report.success:
            self.stage_label.setText("Import completed successfully!")
            self.progress_bar.setValue(100)

            # Show details
            summary = self._format_import_report(report)
            self.details_text.setPlainText(summary)
            self.details_text.setVisible(False)

            # Show completion buttons
            self.cancel_button.setVisible(False)
            self.open_project_button.setVisible(True)
            self.copy_report_button.setVisible(True)
            self.close_button.setVisible(True)
        else:
            error_text_raw = report.error_message or "Import failed"
            is_cancelled = "cancel" in error_text_raw.lower()
            self.stage_label.setText("Import cancelled" if is_cancelled else "Import failed")
            self.progress_bar.setValue(0)

            # Show error
            error_text = f"Error: {error_text_raw}"
            self.details_text.setPlainText(error_text)
            self.details_text.setVisible(True)

            # Show close button
            self.cancel_button.setVisible(False)
            self.copy_report_button.setVisible(True)
            self.close_button.setVisible(True)

    def on_cancel(self):
        """Handle cancel button click."""
        self.cancel_requested.emit()
        self.stage_label.setText("Cancelling...")
        self.cancel_button.setEnabled(False)

    def on_open_project(self):
        """Signal to open the imported project."""
        # Will be handled by parent window
        self.accept()

    def on_copy_report(self):
        """Copy import report to clipboard."""
        if self._report:
            text = self._format_import_report(self._report) if self._report.success else f"Error: {self._report.error_message}"
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            QMessageBox.information(self, "Copied", "Report copied to clipboard")

    def get_new_project_id(self) -> int:
        """Get the new project ID after successful import."""
        return self._report.new_project_id if self._report else None

    def _format_import_report(self, report: ImportReport) -> str:
        """Format import report for display."""
        lines = [
            "=== Import Report ===",
            f"New Project ID: {report.new_project_id}",
            f"Project Name: {report.new_project_name}",
            f"Time: {report.elapsed_seconds:.1f}s",
            "",
        ]

        if report.warnings:
            lines.append("=== Warnings ===")
            for warning in report.warnings:
                lines.append(f"  • {warning}")
            lines.append("")

        lines.append("=== Table Counts ===")
        for table, count in sorted(report.table_counts.items()):
            if count > 0:
                lines.append(f"  {table}: {count:,}")

        total_rows = sum(report.table_counts.values())
        lines.append(f"\nTotal rows imported: {total_rows:,}")

        return "\n".join(lines)
