"""Reference corpus setup wizard (Hybrid: Download or Process Locally)."""

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.reference_setup import (
    LocalProcessingService,
    ReferenceDownloadService,
    SetupStage,
    SetupState,
)

logger = logging.getLogger(__name__)


class SetupWorker(QThread):
    """Background worker for reference corpus setup."""

    progress = pyqtSignal(SetupState)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, mode: str, work_dir: Path, db_path: Path):
        super().__init__()
        self.mode = mode
        self.work_dir = work_dir
        self.db_path = db_path
        self.cancelled = False

    def run(self):
        """Run setup in background."""
        try:
            if self.mode == "download":
                self._run_download()
            elif self.mode == "local_process":
                self._run_local_process()
            else:
                raise ValueError(f"Unknown mode: {self.mode}")

        except Exception as e:
            logger.error(f"Setup failed: {e}", exc_info=True)
            self.finished.emit(False, str(e))

    def _run_download(self):
        """Run download mode."""
        state_file = self.work_dir / "download_state.json"
        service = ReferenceDownloadService(self.work_dir, state_file)

        entry = service.get_latest_entry()
        if not entry:
            self.finished.emit(False, "No manifest entry available")
            return

        try:
            db_path = service.download(entry, progress_callback=self.progress.emit)
            self.finished.emit(True, f"Downloaded: {db_path}")

        except Exception as e:
            self.finished.emit(False, f"Download failed: {e}")

    def _run_local_process(self):
        """Run local processing mode."""
        state_file = self.work_dir / "local_process_state.json"
        service = LocalProcessingService(self.work_dir, state_file, self.db_path)

        # Wikipedia dump URL (hardcoded for now)
        xml_url = (
            "https://dumps.wikimedia.org/hewiki/20260201/hewiki-20260201-pages-articles.xml.bz2"
        )

        try:
            service.run_full_pipeline(
                xml_url,
                use_gpu=False,  # TODO: Add GPU detection
                progress_callback=self.progress.emit,
            )
            self.finished.emit(True, "Processing complete")

        except Exception as e:
            self.finished.emit(False, f"Processing failed: {e}")

    def cancel(self):
        """Cancel setup."""
        self.cancelled = True


class ReferenceSetupWizard(QDialog):
    """Setup wizard for Hebrew Wikipedia reference corpus."""

    def __init__(self, work_dir: Path, db_path: Path, parent=None):
        super().__init__(parent)
        self.work_dir = work_dir
        self.db_path = db_path
        self.worker: SetupWorker | None = None

        self.setWindowTitle("Hebrew Wikipedia Setup")
        self.resize(700, 500)

        # UI state
        self.selected_mode = "download"

        self._init_ui()

    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout()

        # Stacked widget for pages
        self.stack = QStackedWidget()

        # Page 1: Welcome + Mode Selection
        self.page_welcome = self._create_welcome_page()
        self.stack.addWidget(self.page_welcome)

        # Page 2: Progress
        self.page_progress = self._create_progress_page()
        self.stack.addWidget(self.page_progress)

        # Page 3: Complete
        self.page_complete = self._create_complete_page()
        self.stack.addWidget(self.page_complete)

        layout.addWidget(self.stack)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.btn_back = QPushButton("Back")
        self.btn_back.clicked.connect(self._on_back)
        self.btn_back.setEnabled(False)
        button_layout.addWidget(self.btn_back)

        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self._on_next)
        button_layout.addWidget(self.btn_next)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.btn_cancel)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def _create_welcome_page(self) -> QWidget:
        """Create welcome page."""
        page = QWidget()
        layout = QVBoxLayout()

        # Title
        title = QLabel("<h2>Hebrew Wikipedia Reference Corpus</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Description
        desc = QLabel(
            "This wizard will set up the Hebrew Wikipedia baseline corpus "
            "(387,639 documents) for use as a reference corpus in HDLE Premium.\n\n"
            "Please select setup mode:"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(20)

        # Mode selection
        self.mode_group = QButtonGroup()

        # Mode 1: Download
        self.radio_download = QRadioButton(
            "[Recommended] Download Pre-Processed Database (~2.5 GB, 5-15 minutes)"
        )
        self.radio_download.setChecked(True)
        self.mode_group.addButton(self.radio_download)
        layout.addWidget(self.radio_download)

        download_desc = QLabel(
            "   • Fastest setup\n"
            "   • All processing already complete\n"
            "   • Dictionary and terms ready immediately\n"
            "   • Requires internet connection"
        )
        download_desc.setStyleSheet("color: #666; margin-left: 20px;")
        layout.addWidget(download_desc)

        layout.addSpacing(10)

        # Mode 2: Local Processing
        self.radio_local = QRadioButton(
            "[Advanced] Process Locally (~1.5 GB XML, 12-21 hours with GPU)"
        )
        self.mode_group.addButton(self.radio_local)
        layout.addWidget(self.radio_local)

        local_desc = QLabel(
            "   • Fully offline after initial download\n"
            "   • Complete control over processing\n"
            "   • Requires GPU for reasonable speed\n"
            "   • Long processing time (runs in background)"
        )
        local_desc.setStyleSheet("color: #666; margin-left: 20px;")
        layout.addWidget(local_desc)

        layout.addStretch()

        page.setLayout(layout)
        return page

    def _create_progress_page(self) -> QWidget:
        """Create progress page."""
        page = QWidget()
        layout = QVBoxLayout()

        # Status label
        self.lbl_status = QLabel("Initializing...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_status)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # Details
        self.lbl_details = QLabel("")
        self.lbl_details.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_details)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(200)
        layout.addWidget(self.log_output)

        layout.addStretch()

        page.setLayout(layout)
        return page

    def _create_complete_page(self) -> QWidget:
        """Create completion page."""
        page = QWidget()
        layout = QVBoxLayout()

        self.lbl_result = QLabel("")
        self.lbl_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_result.setWordWrap(True)
        layout.addWidget(self.lbl_result)

        layout.addStretch()

        page.setLayout(layout)
        return page

    def _on_next(self):
        """Handle next button."""
        current_page = self.stack.currentIndex()

        if current_page == 0:  # Welcome page
            # Get selected mode
            if self.radio_download.isChecked():
                self.selected_mode = "download"
            else:
                self.selected_mode = "local_process"

            # Start setup
            self._start_setup()
            self.stack.setCurrentIndex(1)
            self.btn_back.setEnabled(False)
            self.btn_next.setEnabled(False)

        elif current_page == 2:  # Complete page
            self.accept()

    def _on_back(self):
        """Handle back button."""
        current_page = self.stack.currentIndex()
        if current_page > 0:
            self.stack.setCurrentIndex(current_page - 1)
            self.btn_back.setEnabled(current_page > 1)

    def _on_cancel(self):
        """Handle cancel button."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()

        self.reject()

    def _start_setup(self):
        """Start setup in background."""
        self.worker = SetupWorker(self.selected_mode, self.work_dir, self.db_path)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

        self.lbl_status.setText(f"Starting {self.selected_mode} mode...")
        self.log_output.append(f"Mode: {self.selected_mode}")

    def _on_progress(self, state: SetupState):
        """Handle progress update."""
        # Update progress bar
        pct = state.get_progress_percentage()
        self.progress_bar.setValue(int(pct))

        # Update status
        stage_text = {
            SetupStage.DOWNLOADING: "Downloading...",
            SetupStage.VERIFYING: "Verifying checksum...",
            SetupStage.DECOMPRESSING: "Decompressing...",
            SetupStage.INSTALLING: "Installing...",
            SetupStage.COMPLETED: "Complete!",
        }.get(state.stage, str(state.stage))

        self.lbl_status.setText(stage_text)

        # Update details
        if state.mode == "download":
            if state.total_bytes > 0:
                downloaded_gb = state.bytes_downloaded / (1024**3)
                total_gb = state.total_bytes / (1024**3)
                speed_mbps = state.download_speed_bps / (1024**2)
                self.lbl_details.setText(
                    f"{downloaded_gb:.2f} / {total_gb:.2f} GB | "
                    f"{speed_mbps:.2f} MB/s | "
                    f"{pct:.1f}%"
                )
        elif state.mode == "local_process":
            if state.total_docs > 0:
                self.lbl_details.setText(
                    f"{state.docs_processed:,} / {state.total_docs:,} documents | " f"{pct:.1f}%"
                )

        # Log
        self.log_output.append(f"[{state.stage.value}] {pct:.1f}%")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def _on_finished(self, success: bool, message: str):
        """Handle setup completion."""
        self.stack.setCurrentIndex(2)
        self.btn_cancel.setEnabled(False)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Finish")

        if success:
            self.lbl_result.setText(
                f"<h2>Setup Complete!</h2><p>{message}</p>"
                "<p>You can now use Hebrew Wikipedia as a reference corpus.</p>"
            )
        else:
            self.lbl_result.setText(
                f"<h2>Setup Failed</h2><p>{message}</p>"
                "<p>Please try again or contact support.</p>"
            )
