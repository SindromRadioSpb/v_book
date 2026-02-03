"""P1 Verification Panel - Premium UI for TM persistence testing.

Non-technical user interface for running P1 Scenario 7 verification.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from app.services.db_service import DBService
from app.ui.workers import P1VerificationWorker

logger = logging.getLogger(__name__)


class VerificationPanel(QWidget):
    """P1 Verification Panel."""

    back_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.worker: Optional[P1VerificationWorker] = None
        self.current_report_md: Optional[str] = None
        self.current_report_json: Optional[str] = None
        self.init_ui()
        self.load_db_path()
        self.load_projects()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("P1 Scenario 7 Verification")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        back_btn = QPushButton("← Back to Dashboard")
        back_btn.clicked.connect(self.on_back)
        header_layout.addWidget(back_btn)

        layout.addLayout(header_layout)

        # Info
        info_label = QLabel(
            "Automated verification that TM entries persist through re-extraction and restart.\n"
            "⚠️ Runs on snapshot - production DB is never modified."
        )
        info_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 4px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # DB Section
        db_group = QGroupBox("Database")
        db_layout = QVBoxLayout()

        db_path_layout = QHBoxLayout()
        db_path_layout.addWidget(QLabel("Production DB:"))
        self.db_path_edit = QLineEdit()
        self.db_path_edit.setReadOnly(True)
        db_path_layout.addWidget(self.db_path_edit)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.on_browse_db)
        db_path_layout.addWidget(self.browse_btn)

        db_layout.addLayout(db_path_layout)

        db_note = QLabel("Note: Verification runs on a snapshot copy. Your production DB will not be modified.")
        db_note.setStyleSheet("color: #0288d1; font-size: 11px;")
        db_note.setWordWrap(True)
        db_layout.addWidget(db_note)

        db_group.setLayout(db_layout)
        layout.addWidget(db_group)

        # Project Section
        project_group = QGroupBox("Project")
        project_layout = QVBoxLayout()

        project_select_layout = QHBoxLayout()
        project_select_layout.addWidget(QLabel("Select Project:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(200)
        project_select_layout.addWidget(self.project_combo)
        project_select_layout.addStretch()

        project_layout.addLayout(project_select_layout)
        project_group.setLayout(project_layout)
        layout.addWidget(project_group)

        # Run Controls
        controls_layout = QHBoxLayout()

        self.run_btn = QPushButton("▶ Run P1 Scenario 7")
        self.run_btn.setStyleSheet("QPushButton { background: #4caf50; color: white; font-weight: bold; padding: 8px 16px; }")
        self.run_btn.clicked.connect(self.on_run)
        controls_layout.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel)
        controls_layout.addWidget(self.cancel_btn)

        self.open_report_btn = QPushButton("📄 Open Report")
        self.open_report_btn.setEnabled(False)
        self.open_report_btn.clicked.connect(self.on_open_report)
        controls_layout.addWidget(self.open_report_btn)

        self.copy_summary_btn = QPushButton("📋 Copy Summary")
        self.copy_summary_btn.setEnabled(False)
        self.copy_summary_btn.clicked.connect(self.on_copy_summary)
        controls_layout.addWidget(self.copy_summary_btn)

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

        # Status Badge
        self.status_label = QLabel("Status: Ready")
        self.status_label.setStyleSheet("font-weight: bold; padding: 4px 8px; background: #e0e0e0; border-radius: 4px;")
        layout.addWidget(self.status_label)

        # Log Output
        log_layout = QVBoxLayout()
        log_layout.addWidget(QLabel("Log Output:"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Courier New", 9))
        self.log_output.setMaximumBlockCount(1000)  # Limit log size
        log_layout.addWidget(self.log_output)
        layout.addLayout(log_layout)

        self.setLayout(layout)

    def load_db_path(self):
        """Load current production DB path."""
        try:
            db_service = DBService.get_instance()
            if db_service and db_service._db_manager:
                db_path = str(db_service._db_manager.db_path)
                self.db_path_edit.setText(db_path)
            else:
                self.db_path_edit.setText("(No database loaded)")
                self.run_btn.setEnabled(False)
        except Exception as e:
            logger.exception("Failed to load DB path")
            self.db_path_edit.setText("(Error loading DB)")
            self.run_btn.setEnabled(False)

    def load_projects(self):
        """Load projects from DB."""
        try:
            db_service = DBService.get_instance()
            if not db_service:
                self.project_combo.clear()
                self.project_combo.addItem("(No database loaded)")
                self.run_btn.setEnabled(False)
                return

            with db_service.get_session() as session:
                from app.infra.sa_models import DictProject
                from sqlalchemy import select

                stmt = select(DictProject).order_by(DictProject.project_id)
                projects = session.execute(stmt).scalars().all()

                self.project_combo.clear()

                if not projects:
                    self.project_combo.addItem("(No projects - create one first)")
                    self.run_btn.setEnabled(False)
                else:
                    # Add "Global (All Projects)" option
                    self.project_combo.addItem("Global (All Projects)", None)

                    # Add individual projects
                    for project in projects:
                        self.project_combo.addItem(
                            f"{project.name} (ID: {project.project_id})",
                            project.project_id
                        )

                    self.run_btn.setEnabled(True)

        except Exception as e:
            logger.exception("Failed to load projects")
            self.project_combo.clear()
            self.project_combo.addItem("(Error loading projects)")
            self.run_btn.setEnabled(False)

    def on_browse_db(self):
        """Browse for DB file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database File",
            "",
            "SQLite Database (*.db);;All Files (*)"
        )

        if file_path:
            self.db_path_edit.setText(file_path)
            # Reinitialize DBService with new DB
            try:
                DBService.shutdown()
                DBService.initialize(file_path)
                self.load_projects()
            except Exception as e:
                logger.exception("Failed to load DB")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to load database:\n\n{str(e)}"
                )

    def on_run(self):
        """Run P1 verification."""
        db_path = self.db_path_edit.text()
        if not db_path or db_path.startswith("("):
            QMessageBox.warning(
                self,
                "No Database",
                "Please select a valid database file."
            )
            return

        if not Path(db_path).exists():
            QMessageBox.critical(
                self,
                "Database Not Found",
                f"Database file not found:\n{db_path}"
            )
            return

        # Get selected project
        project_id = self.project_combo.currentData()

        # Reset UI
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("Status: Running...")
        self.status_label.setStyleSheet("font-weight: bold; padding: 4px 8px; background: #ffc107; border-radius: 4px;")
        self.current_report_md = None
        self.current_report_json = None

        # Disable controls
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_report_btn.setEnabled(False)
        self.copy_summary_btn.setEnabled(False)

        # Create and start worker
        self.worker = P1VerificationWorker(
            db_path=db_path,
            project_id=project_id,
            out_dir=None  # Use default runtime/verifications/p1/<timestamp>
        )

        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.on_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)

        self.worker.start()

        logger.info(f"Started P1 verification: db={db_path}, project={project_id}")

    def on_cancel(self):
        """Cancel verification."""
        if self.worker:
            self.worker.cancel()
            self.log_output.appendPlainText("\n[CANCELLING...]")
            self.cancel_btn.setEnabled(False)

    def on_progress(self, value: int):
        """Update progress bar."""
        self.progress_bar.setValue(value)

    def on_log(self, message: str):
        """Append log message."""
        self.log_output.appendPlainText(message)

    def on_finished(self, report_md: str, report_json: str, status: str):
        """Handle verification finished."""
        self.current_report_md = report_md
        self.current_report_json = report_json

        # Update status
        status_styles = {
            "PASS": "background: #4caf50; color: white;",
            "PARTIAL": "background: #ff9800; color: white;",
            "SKIPPED": "background: #9e9e9e; color: white;",
            "FAIL": "background: #f44336; color: white;",
        }

        style = status_styles.get(status, "background: #e0e0e0;")
        self.status_label.setText(f"Status: {status}")
        self.status_label.setStyleSheet(f"font-weight: bold; padding: 4px 8px; border-radius: 4px; {style}")

        # Enable controls
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.open_report_btn.setEnabled(True)
        self.copy_summary_btn.setEnabled(True)

        # Show completion message
        if status == "PASS":
            QMessageBox.information(
                self,
                "Verification Complete",
                f"✅ P1 Scenario 7 verification PASSED!\n\n"
                f"TM entries persisted through all phases.\n\n"
                f"Report: {report_md}"
            )
        elif status == "PARTIAL":
            QMessageBox.warning(
                self,
                "Verification Partial",
                f"⚠️ P1 Scenario 7 verification PARTIAL\n\n"
                f"Some tests passed, but not all.\n\n"
                f"Report: {report_md}"
            )
        elif status == "SKIPPED":
            QMessageBox.information(
                self,
                "Verification Skipped",
                f"ℹ️ P1 Scenario 7 verification SKIPPED\n\n"
                f"No processed data found in project.\n\n"
                f"Report: {report_md}"
            )
        else:
            QMessageBox.critical(
                self,
                "Verification Failed",
                f"❌ P1 Scenario 7 verification FAILED\n\n"
                f"Check the log for details.\n\n"
                f"Report: {report_md}"
            )

        logger.info(f"Verification complete: {status}")

    def on_failed(self, error_summary: str, error_details: str):
        """Handle verification failed."""
        self.status_label.setText("Status: ERROR")
        self.status_label.setStyleSheet("font-weight: bold; padding: 4px 8px; background: #f44336; color: white; border-radius: 4px;")

        # Enable controls
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        # Show error dialog
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Verification Error")
        msg.setText(error_summary)
        msg.setDetailedText(error_details)
        msg.exec()

        logger.error(f"Verification failed: {error_summary}")

    def on_open_report(self):
        """Open report in default viewer."""
        if not self.current_report_md:
            QMessageBox.warning(
                self,
                "No Report",
                "No report available. Run verification first."
            )
            return

        # Open report directory
        report_dir = Path(self.current_report_md).parent

        try:
            if sys.platform == "win32":
                os.startfile(str(report_dir))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(report_dir)])
            else:
                subprocess.run(["xdg-open", str(report_dir)])

            logger.info(f"Opened report directory: {report_dir}")

        except Exception as e:
            logger.exception("Failed to open report")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open report directory:\n\n{str(e)}"
            )

    def on_copy_summary(self):
        """Copy summary to clipboard."""
        if not self.current_report_json:
            QMessageBox.warning(
                self,
                "No Report",
                "No report available. Run verification first."
            )
            return

        try:
            import json
            from PyQt6.QtWidgets import QApplication

            with open(self.current_report_json, 'r', encoding='utf-8') as f:
                report = json.load(f)

            summary = f"""P1 Scenario 7 Verification Summary
{'='*50}
Status: {report['status']}
Timestamp: {report['timestamp']}
Database: {report['source_db_path']}
Project ID: {report.get('project_id', 'Global')}

Test Items: {len(report['test_items'])}

Phases:
- Pre-extraction: {report['phases']['pre_extraction']['items_passed']}/{report['phases']['pre_extraction']['items_checked']} PASS
- Post-extraction: {report['phases']['post_extraction']['items_passed']}/{report['phases']['post_extraction']['items_checked']} PASS
- Post-restart: {report['phases']['post_restart']['items_passed']}/{report['phases']['post_restart']['items_checked']} PASS

Total Duration: {report['total_duration_ms']:.2f} ms

Report: {self.current_report_md}
"""

            clipboard = QApplication.clipboard()
            clipboard.setText(summary)

            QMessageBox.information(
                self,
                "Summary Copied",
                "Verification summary copied to clipboard!"
            )

        except Exception as e:
            logger.exception("Failed to copy summary")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to copy summary:\n\n{str(e)}"
            )

    def on_back(self):
        """Go back to dashboard."""
        # Cancel worker if running
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Verification?",
                "Verification is running. Cancel and go back?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.worker.cancel()
                self.worker.wait()
            else:
                return

        self.back_requested.emit()
