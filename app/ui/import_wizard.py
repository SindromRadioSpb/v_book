"""P3 Dictionary Import Wizard.

Minimal wizard for importing dictionaries from CSV/XLSX with:
- File selection
- Scope (global/project)
- Conflict policy
- Normalize mode
- Progress tracking with cancellation
"""

import logging
from typing import Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QRadioButton,
    QButtonGroup,
    QProgressBar,
    QPlainTextEdit,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from app.services.db_service import DBService
from app.ui.workers import ImportWorker
from app.infra.security import (
    validate_file_size,
    validate_path_security,
    MAX_DICTIONARY_SIZE,
    ValidationError,
    PathSecurityError,
)

logger = logging.getLogger(__name__)


class ImportWizard(QWidget):
    """P3 Import Wizard."""

    back_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.worker: Optional[ImportWorker] = None
        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Dictionary Import")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.on_back)
        header_layout.addWidget(back_btn)

        layout.addLayout(header_layout)

        # File selection
        file_group = QGroupBox("File Selection")
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("File:"))
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("Select CSV or XLSX file...")
        file_layout.addWidget(self.file_path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.on_browse_file)
        file_layout.addWidget(browse_btn)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Import settings
        settings_group = QGroupBox("Import Settings")
        settings_layout = QVBoxLayout()

        # Scope
        scope_layout = QHBoxLayout()
        scope_layout.addWidget(QLabel("Scope:"))
        self.scope_global_radio = QRadioButton("Global")
        self.scope_project_radio = QRadioButton("Project")
        self.scope_global_radio.setChecked(True)
        self.scope_button_group = QButtonGroup()
        self.scope_button_group.addButton(self.scope_global_radio)
        self.scope_button_group.addButton(self.scope_project_radio)
        scope_layout.addWidget(self.scope_global_radio)
        scope_layout.addWidget(self.scope_project_radio)

        self.project_combo = QComboBox()
        self.project_combo.setEnabled(False)
        scope_layout.addWidget(QLabel("Project:"))
        scope_layout.addWidget(self.project_combo)
        scope_layout.addStretch()

        settings_layout.addLayout(scope_layout)

        # Connect scope radio to enable/disable project combo
        self.scope_global_radio.toggled.connect(lambda checked: self.project_combo.setEnabled(not checked))

        # Default kind
        kind_layout = QHBoxLayout()
        kind_layout.addWidget(QLabel("Default Kind:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["lemma", "term_cluster", "ngram", "surface"])
        kind_layout.addWidget(self.kind_combo)
        kind_layout.addStretch()
        settings_layout.addLayout(kind_layout)

        # Conflict policy
        conflict_layout = QHBoxLayout()
        conflict_layout.addWidget(QLabel("On Conflict:"))
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["skip", "overwrite", "keep_both_as_variants"])
        conflict_layout.addWidget(self.conflict_combo)
        conflict_layout.addStretch()
        settings_layout.addLayout(conflict_layout)

        # Normalize mode
        normalize_layout = QHBoxLayout()
        normalize_layout.addWidget(QLabel("Normalize Mode:"))
        self.normalize_combo = QComboBox()
        self.normalize_combo.addItems(["strict", "compat"])
        normalize_layout.addWidget(self.normalize_combo)
        normalize_layout.addStretch()
        settings_layout.addLayout(normalize_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Controls
        controls_layout = QHBoxLayout()

        self.run_btn = QPushButton("▶ Run Import")
        self.run_btn.setStyleSheet("QPushButton { background: #4caf50; color: white; font-weight: bold; padding: 8px 16px; }")
        self.run_btn.clicked.connect(self.on_run_import)
        controls_layout.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel_import)
        controls_layout.addWidget(self.cancel_btn)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Progress
        progress_layout = QVBoxLayout()
        progress_layout.addWidget(QLabel("Progress:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        layout.addLayout(progress_layout)

        # Log output
        log_layout = QVBoxLayout()
        log_layout.addWidget(QLabel("Log:"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        log_layout.addWidget(self.log_output)
        layout.addLayout(log_layout)

        self.setLayout(layout)

        # Load projects
        self.load_projects()

    def load_projects(self):
        """Load projects into combo."""
        try:
            from app.services.project_service import ProjectService

            project_service = ProjectService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                projects = project_service.list_projects(session)

            self.project_combo.clear()
            for project in projects:
                self.project_combo.addItem(project.name, project.project_id)

        except Exception as e:
            logger.error(f"Failed to load projects: {e}")

    def on_browse_file(self):
        """Browse for file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Dictionary File",
            "",
            "Dictionary Files (*.csv *.xlsx *.xls);;CSV Files (*.csv);;Excel Files (*.xlsx *.xls)",
        )

        if file_path:
            self.file_path_edit.setText(file_path)
            self.log_output.appendPlainText(f"Selected file: {file_path}")

    def on_run_import(self):
        """Run import."""
        # Validate inputs
        file_path = self.file_path_edit.text().strip()
        if not file_path:
            QMessageBox.warning(self, "No File", "Please select a file to import.")
            return

        if not Path(file_path).exists():
            QMessageBox.warning(self, "File Not Found", f"File not found: {file_path}")
            return

        # UI-layer validation: Check file path security and size
        path_obj = Path(file_path)

        try:
            # Validate path security (blocks UNC, system dirs, resolves symlinks)
            safe_path = validate_path_security(path_obj, operation="dictionary import")
        except PathSecurityError as e:
            error_messages = {
                "UNC_PATH": "Network paths (UNC) are not allowed.\n\nPlease copy the file to a local directory first.",
                "SYSTEM_DIRECTORY": "Cannot import from system directories.\n\nPlease select a file from your user directories.",
                "RESOLVE_FAILED": f"Cannot access file path.\n\n{str(e)}",
            }

            error_msg = error_messages.get(
                e.reason,
                f"File path security check failed: {e.reason}"
            )

            QMessageBox.critical(self, "Path Security Error", error_msg)
            logger.warning(f"Path security check failed: {e.reason}, path={file_path}")
            return

        try:
            # Validate file size (10 MB limit for dictionaries)
            validate_file_size(safe_path, MAX_DICTIONARY_SIZE, file_type="dictionary")
        except ValidationError as e:
            file_size_mb = safe_path.stat().st_size / 1024 / 1024
            max_size_mb = MAX_DICTIONARY_SIZE / 1024 / 1024

            QMessageBox.critical(
                self,
                "File Too Large",
                f"Dictionary file is too large: {file_size_mb:.1f} MB\n\n"
                f"Maximum allowed size: {max_size_mb:.0f} MB\n\n"
                f"Please reduce the file size or split it into smaller files."
            )
            logger.warning(f"File size limit exceeded: {file_size_mb:.1f} MB > {max_size_mb:.0f} MB")
            return

        # Log validation success
        self.log_output.appendPlainText(f"✓ File path validated")
        self.log_output.appendPlainText(f"✓ File size: {safe_path.stat().st_size / 1024:.1f} KB")

        # Get scope
        if self.scope_global_radio.isChecked():
            scope = "global"
            project_id = None
        else:
            scope = "project"
            project_id = self.project_combo.currentData()
            if project_id is None:
                QMessageBox.warning(self, "No Project", "Please select a project for project scope.")
                return

        # Get settings
        default_kind = self.kind_combo.currentText()
        on_conflict = self.conflict_combo.currentText()
        normalize_mode = self.normalize_combo.currentText()

        # Clear log
        self.log_output.clear()

        # Disable controls
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        # Start worker
        self.worker = ImportWorker(
            file_path=file_path,
            project_id=project_id,
            scope=scope,
            on_conflict=on_conflict,
            normalize_mode=normalize_mode,
            default_kind=default_kind,
            default_status="approved",
            force_reimport=False,
        )

        self.worker.progress.connect(self.on_progress)
        self.worker.log_message.connect(self.on_log_message)
        self.worker.import_complete.connect(self.on_import_complete)
        self.worker.error.connect(self.on_import_error)
        self.worker.finished.connect(self.on_worker_finished)

        self.worker.start()

    def on_cancel_import(self):
        """Cancel import."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def on_progress(self, current: int, total: int):
        """Handle progress update."""
        if total > 0:
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            self.log_output.appendPlainText(f"Progress: {current}/{total} ({pct}%)")

    def on_log_message(self, message: str):
        """Handle log message."""
        self.log_output.appendPlainText(message)

    def on_import_complete(self, report):
        """Handle import completion."""
        self.log_output.appendPlainText("=" * 50)
        self.log_output.appendPlainText("IMPORT COMPLETE")
        self.log_output.appendPlainText(f"Total rows: {report.total}")
        self.log_output.appendPlainText(f"Added: {report.added}")
        self.log_output.appendPlainText(f"Updated: {report.updated}")
        self.log_output.appendPlainText(f"Skipped: {report.skipped}")
        self.log_output.appendPlainText(f"Conflicts: {report.conflicts}")
        self.log_output.appendPlainText(f"Invalid: {report.invalid}")
        self.log_output.appendPlainText(f"Elapsed: {report.elapsed_ms:.1f}ms")
        self.log_output.appendPlainText(f"SHA256: {report.sha256[:16]}...")
        self.log_output.appendPlainText("=" * 50)

        if report.invalid_rows:
            self.log_output.appendPlainText(f"\nInvalid rows: {len(report.invalid_rows)}")
            for inv in report.invalid_rows[:10]:  # Show first 10
                self.log_output.appendPlainText(f"  Row {inv.row_index}: {inv.reason}")

        if report.conflict_details:
            self.log_output.appendPlainText(f"\nConflicts: {len(report.conflict_details)}")
            for conf in report.conflict_details[:10]:  # Show first 10
                self.log_output.appendPlainText(
                    f"  Row {conf.row_index}: {conf.src_text} - "
                    f"existing='{conf.existing_translation}', incoming='{conf.incoming_translation}', "
                    f"action={conf.action_taken}"
                )

        QMessageBox.information(
            self,
            "Import Complete",
            f"Import completed successfully!\n\n"
            f"Added: {report.added}\n"
            f"Updated: {report.updated}\n"
            f"Skipped: {report.skipped}\n"
            f"Invalid: {report.invalid}",
        )

    def on_import_error(self, error_msg: str):
        """Handle import error."""
        self.log_output.appendPlainText(f"ERROR: {error_msg}")
        QMessageBox.critical(self, "Import Error", f"Import failed:\n{error_msg}")

    def on_worker_finished(self):
        """Handle worker finished."""
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(0)

    def closeEvent(self, event):
        """Handle close event."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        event.accept()

    def on_back(self):
        """Handle back button."""
        self.back_requested.emit()
