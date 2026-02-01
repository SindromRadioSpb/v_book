"""Documents view - file import and management."""
import logging
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QFileDialog,
    QHeaderView,
    QCheckBox,
    QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from app.services.db_service import DBService
from app.services.project_service import ProjectService
from app.services.ingest_service import IngestService
from app.ui.workers import IngestWorker, ProcessWorker
from app.ui.dialogs import show_error, show_info, show_warning

logger = logging.getLogger(__name__)


class DocumentsView(QWidget):
    """Documents view with drag-drop import."""

    document_added = pyqtSignal(int)  # Emits doc_id when document is added
    processing_completed = pyqtSignal()  # Emits when NLP processing is done

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.corpus_id = None

        self.db_service = DBService.get_instance()
        self.project_service = ProjectService()
        self.ingest_service = IngestService()

        self.current_worker = None
        self.process_worker = None

        self.init_ui()
        self.load_corpus()
        self.load_documents()

        # Enable drag and drop
        self.setAcceptDrops(True)

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Documents")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Add files button
        add_btn = QPushButton("Add Files...")
        add_btn.clicked.connect(self.on_add_files)
        header_layout.addWidget(add_btn)

        # Add folder button
        add_folder_btn = QPushButton("Add Folder...")
        add_folder_btn.clicked.connect(self.on_add_folder)
        header_layout.addWidget(add_folder_btn)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_documents)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # OCR option
        ocr_layout = QHBoxLayout()
        self.ocr_checkbox = QCheckBox("Use OCR for scanned PDFs (Premium)")
        self.ocr_checkbox.setChecked(False)
        ocr_layout.addWidget(self.ocr_checkbox)
        ocr_layout.addStretch()
        layout.addLayout(ocr_layout)

        # NLP options
        nlp_layout = QHBoxLayout()

        # Check if Stanza is available
        self.stanza_available = self._check_stanza_available()
        self.cuda_available = self._check_cuda_available() if self.stanza_available else False

        # Engine info label
        if self.stanza_available:
            engine_label = QLabel(f"✅ Stanza engine available (GPU: {'Yes' if self.cuda_available else 'No'})")
            engine_label.setStyleSheet("color: green;")
        else:
            engine_label = QLabel("⚠️ Stanza not available - using Mock engine")
            engine_label.setStyleSheet("color: orange;")
        nlp_layout.addWidget(engine_label)

        # GPU checkbox (only if CUDA available)
        if self.cuda_available:
            self.gpu_checkbox = QCheckBox("Use GPU for NLP")
            self.gpu_checkbox.setChecked(True)
            nlp_layout.addWidget(self.gpu_checkbox)
        else:
            self.gpu_checkbox = None

        nlp_layout.addStretch()
        layout.addLayout(nlp_layout)

        # Drag-drop hint
        hint = QLabel(
            "💡 Drag and drop files here to import them\n"
            "Supported formats: .txt, .docx, .pdf"
        )
        hint.setStyleSheet(
            "padding: 10px; "
            "background-color: #f0f0f0; "
            "border: 2px dashed #ccc; "
            "border-radius: 5px;"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        # Documents table
        self.docs_table = QTableWidget()
        self.docs_table.setColumnCount(6)
        self.docs_table.setHorizontalHeaderLabels([
            "ID", "File Name", "Size (KB)", "Status", "Imported", "Path"
        ])
        self.docs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.docs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Auto-resize columns
        header = self.docs_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        # Context menu
        self.docs_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.docs_table.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.docs_table)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status
        self.status_label = QLabel("No documents")
        layout.addWidget(self.status_label)

        # Action buttons
        action_layout = QHBoxLayout()
        action_layout.addStretch()

        self.process_btn = QPushButton("Process with NLP")
        self.process_btn.clicked.connect(self.on_process)
        self.process_btn.setEnabled(False)
        action_layout.addWidget(self.process_btn)

        self.reprocess_btn = QPushButton("Re-process")
        self.reprocess_btn.clicked.connect(self.on_reprocess)
        self.reprocess_btn.setEnabled(False)
        self.reprocess_btn.setToolTip("Re-process selected documents with NLP (updates statistics)")
        action_layout.addWidget(self.reprocess_btn)

        self.view_text_btn = QPushButton("View Text")
        self.view_text_btn.clicked.connect(self.on_view_text)
        self.view_text_btn.setEnabled(False)
        action_layout.addWidget(self.view_text_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.on_delete)
        self.delete_btn.setEnabled(False)
        action_layout.addWidget(self.delete_btn)

        layout.addLayout(action_layout)

        # Enable/disable buttons on selection
        self.docs_table.itemSelectionChanged.connect(self.on_selection_changed)

        self.setLayout(layout)

    def _check_stanza_available(self):
        """Check if Stanza is available."""
        try:
            import stanza
            return True
        except ImportError:
            return False

    def _check_cuda_available(self):
        """Check if CUDA is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def load_corpus(self):
        """Load the default corpus for this project."""
        try:
            with self.db_service.get_session() as session:
                corpus = self.project_service.get_default_corpus(session, self.project_id)
                if corpus:
                    self.corpus_id = corpus.corpus_id
                    logger.info(f"Loaded corpus: {corpus.name} (ID: {corpus.corpus_id})")
                else:
                    logger.error(f"No corpus found for project {self.project_id}")
        except Exception as e:
            logger.exception("Failed to load corpus")
            show_error(self, "Error", f"Failed to load corpus: {e}")

    def load_documents(self):
        """Load documents from database."""
        if not self.corpus_id:
            return

        try:
            with self.db_service.get_session() as session:
                from sqlalchemy import select
                from app.infra.sa_models import SourceDocument

                stmt = select(SourceDocument).where(
                    SourceDocument.corpus_id == self.corpus_id
                ).order_by(SourceDocument.imported_at.desc())

                docs = session.execute(stmt).scalars().all()

                self.docs_table.setRowCount(len(docs))

                for row, doc in enumerate(docs):
                    self.docs_table.setItem(row, 0, QTableWidgetItem(str(doc.doc_id)))
                    self.docs_table.setItem(row, 1, QTableWidgetItem(doc.file_name))
                    size_kb = doc.file_size_bytes / 1024
                    self.docs_table.setItem(row, 2, QTableWidgetItem(f"{size_kb:.1f}"))
                    self.docs_table.setItem(row, 3, QTableWidgetItem(doc.status))
                    self.docs_table.setItem(row, 4, QTableWidgetItem(doc.imported_at[:19]))
                    self.docs_table.setItem(row, 5, QTableWidgetItem(doc.file_path))

                self.status_label.setText(f"Total documents: {len(docs)}")

        except Exception as e:
            logger.exception("Failed to load documents")
            show_error(self, "Error", f"Failed to load documents: {e}")

    def on_add_files(self):
        """Handle add files button."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files",
            "",
            "Supported Files (*.txt *.docx *.pdf);;All Files (*.*)"
        )

        if file_paths:
            self.import_files([Path(p) for p in file_paths])

    def on_add_folder(self):
        """Handle add folder button."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder"
        )

        if folder_path:
            folder = Path(folder_path)
            # Find all supported files
            files = []
            for ext in ['.txt', '.docx', '.pdf']:
                files.extend(folder.rglob(f'*{ext}'))

            if files:
                self.import_files(files)
            else:
                show_info(self, "Info", "No supported files found in folder")

    def import_files(self, file_paths: List[Path]):
        """Import files using background worker."""
        if not self.corpus_id:
            show_error(self, "Error", "No corpus available")
            return

        if self.current_worker and self.current_worker.isRunning():
            show_error(self, "Error", "Import already in progress")
            return

        use_ocr = self.ocr_checkbox.isChecked()

        # Create worker
        self.current_worker = IngestWorker(
            self.corpus_id,
            file_paths,
            use_ocr
        )
        self.current_worker.progress.connect(self.on_import_progress)
        self.current_worker.finished.connect(self.on_import_finished)
        self.current_worker.error.connect(self.on_import_error)

        # Show progress
        self.progress_bar.setMaximum(len(file_paths))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        # Start worker
        self.current_worker.start()

    def on_import_progress(self, current: int, total: int, file_name: str):
        """Handle import progress update."""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Importing {current}/{total}: {file_name}")

    def on_import_finished(self, results):
        """Handle import completion."""
        self.progress_bar.setVisible(False)

        success_count = sum(1 for _, doc, _ in results if doc is not None)
        error_count = sum(1 for _, _, err in results if err is not None)

        self.status_label.setText(
            f"Import complete: {success_count} succeeded, {error_count} failed"
        )

        # Reload documents
        self.load_documents()

        if error_count > 0:
            errors = [f"{p.name}: {err}" for p, _, err in results if err]
            show_error(
                self,
                "Import Errors",
                f"{error_count} files failed to import:\n\n" + "\n".join(errors[:5])
            )

    def on_import_error(self, error_msg: str):
        """Handle import error."""
        self.progress_bar.setVisible(False)
        show_error(self, "Import Error", error_msg)

    def on_selection_changed(self):
        """Handle table selection change."""
        has_selection = len(self.docs_table.selectedItems()) > 0
        self.process_btn.setEnabled(has_selection)
        self.view_text_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

        # Enable re-process only for processed documents
        if has_selection:
            selected_rows = set(item.row() for item in self.docs_table.selectedItems())
            # Check if all selected documents are processed
            all_processed = True
            for row in selected_rows:
                status = self.docs_table.item(row, 3).text()  # Column 3 is Status
                if status not in ('processed', 'failed'):
                    all_processed = False
                    break
            self.reprocess_btn.setEnabled(all_processed)
        else:
            self.reprocess_btn.setEnabled(False)

    def on_process(self):
        """Process selected documents with NLP."""
        selected_rows = set(item.row() for item in self.docs_table.selectedItems())
        if not selected_rows:
            return

        # Get selected document IDs
        doc_ids = []
        for row in selected_rows:
            doc_id = int(self.docs_table.item(row, 0).text())
            doc_ids.append(doc_id)

        if self.process_worker and self.process_worker.isRunning():
            show_error(self, "Error", "Processing already in progress")
            return

        # Determine engine and GPU settings
        use_mock = not self.stanza_available
        use_gpu = False
        if self.stanza_available and self.gpu_checkbox and self.gpu_checkbox.isChecked():
            use_gpu = True

        # Build confirmation message
        from PyQt6.QtWidgets import QMessageBox
        if use_mock:
            engine_info = "Note: Using Mock engine (rule-based).\nFor production accuracy, install Stanza."
        else:
            engine_info = f"Using Stanza engine (GPU: {'Yes' if use_gpu else 'No'}).\nThis will provide accurate lemmatization and POS tagging."

        reply = QMessageBox.question(
            self,
            "Confirm Processing",
            f"Process {len(doc_ids)} document(s) with NLP?\n\n{engine_info}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Create worker
            self.process_worker = ProcessWorker(
                doc_ids=doc_ids,
                use_mock=use_mock,
                use_gpu=use_gpu
            )
            self.process_worker.progress.connect(self.on_process_progress)
            self.process_worker.finished.connect(self.on_process_finished)
            self.process_worker.error.connect(self.on_process_error)

            # Show progress
            self.progress_bar.setMaximum(len(doc_ids))
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)

            # Start worker
            self.process_worker.start()

    def on_process_progress(self, current: int, total: int, doc_name: str):
        """Handle processing progress update."""
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processing {current}/{total}: {doc_name}")

    def on_process_finished(self, success_count: int, error_count: int):
        """Handle processing completion."""
        self.progress_bar.setVisible(False)

        self.status_label.setText(
            f"Processing complete: {success_count} succeeded, {error_count} failed"
        )

        # Reload documents to show updated status
        self.load_documents()

        # Emit signal to update other views (e.g., Dictionary)
        if success_count > 0:
            self.processing_completed.emit()

        if error_count > 0:
            show_warning(
                self,
                "Processing Warnings",
                f"{error_count} document(s) failed to process. Check logs for details."
            )

    def on_process_error(self, error_msg: str):
        """Handle processing error."""
        self.progress_bar.setVisible(False)
        show_error(self, "Processing Error", error_msg)

    def on_reprocess(self):
        """Re-process selected documents with NLP (M4: Live Update)."""
        selected_rows = set(item.row() for item in self.docs_table.selectedItems())
        if not selected_rows:
            return

        # Get selected document IDs
        doc_ids = []
        for row in selected_rows:
            doc_id = int(self.docs_table.item(row, 0).text())
            doc_ids.append(doc_id)

        if self.process_worker and self.process_worker.isRunning():
            show_error(self, "Error", "Processing already in progress")
            return

        # Determine engine and GPU settings
        use_mock = not self.stanza_available
        use_gpu = False
        if self.stanza_available and self.gpu_checkbox and self.gpu_checkbox.isChecked():
            use_gpu = True

        # Build confirmation message
        from PyQt6.QtWidgets import QMessageBox
        if use_mock:
            engine_info = "Note: Using Mock engine (rule-based)."
        else:
            engine_info = f"Using Stanza engine (GPU: {'Yes' if use_gpu else 'No'})."

        reply = QMessageBox.question(
            self,
            "Confirm Re-processing",
            f"Re-process {len(doc_ids)} document(s) with NLP?\n\n"
            f"{engine_info}\n\n"
            f"This will:\n"
            f"- Remove old statistics\n"
            f"- Re-run NLP analysis\n"
            f"- Update Dictionary with new results",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Create worker (same as process, will handle reprocessing automatically)
            self.process_worker = ProcessWorker(
                doc_ids=doc_ids,
                use_mock=use_mock,
                use_gpu=use_gpu,
                is_reprocess=True  # Flag to indicate reprocessing
            )
            self.process_worker.progress.connect(self.on_process_progress)
            self.process_worker.finished.connect(self.on_process_finished)
            self.process_worker.error.connect(self.on_process_error)

            # Show progress
            self.progress_bar.setMaximum(len(doc_ids))
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)

            # Start worker
            self.process_worker.start()

    def on_view_text(self):
        """View document text."""
        selected_rows = set(item.row() for item in self.docs_table.selectedItems())
        if not selected_rows:
            return

        row = min(selected_rows)
        doc_id = int(self.docs_table.item(row, 0).text())

        try:
            with self.db_service.get_session() as session:
                text = self.ingest_service.get_document_text(session, doc_id)
                if text:
                    from app.ui.dialogs import TextViewDialog
                    dialog = TextViewDialog(text, self)
                    dialog.exec()
                else:
                    show_info(self, "Info", "No text available")
        except Exception as e:
            logger.exception("Failed to view text")
            show_error(self, "Error", f"Failed to view text: {e}")

    def on_delete(self):
        """Delete selected document."""
        selected_rows = set(item.row() for item in self.docs_table.selectedItems())
        if not selected_rows:
            return

        row = min(selected_rows)
        doc_id = int(self.docs_table.item(row, 0).text())
        file_name = self.docs_table.item(row, 1).text()

        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete document '{file_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                with self.db_service.get_session() as session:
                    if self.ingest_service.delete_document(session, doc_id):
                        self.load_documents()
                    else:
                        show_error(self, "Error", "Document not found")
            except Exception as e:
                logger.exception("Failed to delete document")
                show_error(self, "Error", f"Failed to delete: {e}")

    def show_context_menu(self, position):
        """Show context menu."""
        pass  # Future: add context menu actions

    # Drag and drop handlers
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle drop event."""
        mime_data: QMimeData = event.mimeData()
        if mime_data.hasUrls():
            file_paths = []
            for url in mime_data.urls():
                path = Path(url.toLocalFile())
                if path.is_file() and self.ingest_service.is_supported(path):
                    file_paths.append(path)

            if file_paths:
                self.import_files(file_paths)
            else:
                show_info(self, "Info", "No supported files in drop")
