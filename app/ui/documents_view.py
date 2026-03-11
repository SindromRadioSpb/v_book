"""Documents view - file import and management with metadata (Tag/Link/Level/Topic)."""
import logging
from pathlib import Path
from typing import List, Optional, Dict

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableView,
    QLabel,
    QFileDialog,
    QCheckBox,
    QProgressBar,
    QLineEdit,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QListWidget,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
)
from PyQt6.QtCore import QItemSelectionModel, QModelIndex, Qt, pyqtSignal, QMimeData, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent

from app.services.db_service import DBService
from app.services.project_service import ProjectService
from app.services.ingest_service import IngestService
from app.services.document_service import DocumentService, validate_link_url, VALID_LEVELS
from app.infra.settings import SettingsService
from app.ui.models_qt import DocumentsTableModel
from app.ui.table_layout_controller import TableLayoutController
from app.ui.workers import (
    IngestWorker,
    ProcessWorker,
    DocumentsPageWorker,
    DocumentDeleteWorker,
    SnapshotReadinessWorker,
)
from app.ui.dialogs.nlp_process_progress_dialog import NLPProcessProgressDialog
from app.ui.dialogs import show_error, show_info, show_warning
from app.ui.widgets.snapshot_readiness_panel import SnapshotReadinessPanel

logger = logging.getLogger(__name__)


class EditMetadataDialog(QDialog):
    """Dialog for editing document metadata (tag, link_url, level, topic)."""

    LEVELS = ["", "aleph", "bet", "gimel", "he"]

    def __init__(self, doc_name: str, tag: str, link_url: str, level: str, topic: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Metadata - {doc_name}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout()

        form = QFormLayout()

        self.tag_edit = QLineEdit(tag or "")
        self.tag_edit.setPlaceholderText("e.g. grammar, vocab, reading (comma-separated)")
        self.tag_edit.setMaxLength(200)
        form.addRow("Tag:", self.tag_edit)

        self.link_edit = QLineEdit(link_url or "")
        self.link_edit.setPlaceholderText("https://example.com/text")
        form.addRow("Link URL:", self.link_edit)

        self.level_combo = QComboBox()
        self.level_combo.addItems(["(none)", "aleph", "bet", "gimel", "he"])
        if level in ("aleph", "bet", "gimel", "he"):
            self.level_combo.setCurrentText(level)
        else:
            self.level_combo.setCurrentIndex(0)
        form.addRow("Level:", self.level_combo)

        self.topic_edit = QLineEdit(topic or "")
        self.topic_edit.setPlaceholderText("e.g. daily life, travel, news")
        self.topic_edit.setMaxLength(500)
        form.addRow("Topic:", self.topic_edit)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def get_values(self):
        """Return (tag, link_url, level, topic) вЂ” level is None if (none)."""
        level_text = self.level_combo.currentText()
        return (
            self.tag_edit.text().strip() or None,
            self.link_edit.text().strip() or None,
            level_text if level_text != "(none)" else None,
            self.topic_edit.text().strip() or None,
        )


class DeleteDocumentsConfirmDialog(QDialog):
    """Scrollable confirmation dialog for destructive document deletion."""

    def __init__(self, doc_names: List[str], parent=None):
        super().__init__(parent)
        self.doc_names = list(doc_names)
        self.setWindowTitle("Confirm Delete")
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        summary = QLabel(self._summary_text())
        summary.setWordWrap(True)
        layout.addWidget(summary)

        names_list = QListWidget()
        names_list.addItems(self.doc_names)
        names_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(names_list, 1)

        warning = QLabel(
            "This action permanently deletes the selected documents and their derived sentence data."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel)
        yes_button = buttons.button(QDialogButtonBox.StandardButton.Yes)
        if yes_button is not None:
            yes_button.setText("Delete")
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Cancel")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _summary_text(self) -> str:
        if len(self.doc_names) == 1:
            return f"Delete the selected document?\n\nFile Name: {self.doc_names[0]}"
        return (
            f"Delete {len(self.doc_names)} selected documents?\n\n"
            "The following File Name values will be permanently removed:"
        )


class DocumentsView(QWidget):
    """Documents view with drag-drop import and metadata columns (Tag/Link/Level/Topic)."""

    document_added = pyqtSignal(int)  # Emits doc_id when document is added
    processing_completed = pyqtSignal()  # Emits when NLP processing is done

    # Column indices (12 columns total)
    COL_ID = 0
    COL_NAME = 1
    COL_SIZE = 2
    COL_STATUS = 3
    COL_SENTENCES = 4
    COL_TOKENS = 5
    COL_IMPORTED = 6
    COL_PATH = 7
    COL_TAG = 8
    COL_LINK = 9
    COL_LEVEL = 10
    COL_TOPIC = 11
    HEADER_LABELS = [
        "ID",
        "File Name",
        "Size (KB)",
        "Status",
        "Sentences",
        "Tokens",
        "Imported",
        "Path",
        "Tag",
        "Link",
        "Level",
        "Topic",
    ]
    COLUMN_TO_DB = {
        COL_ID: "doc_id",
        COL_NAME: "file_name",
        COL_SIZE: "file_size_bytes",
        COL_STATUS: "status",
        COL_SENTENCES: "sentence_count",
        COL_TOKENS: "token_count",
        COL_IMPORTED: "imported_at",
        COL_PATH: "file_path",
        COL_TAG: "tag",
        COL_LINK: "link_url",
        COL_LEVEL: "level",
        COL_TOPIC: "topic",
    }

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.corpus_id = None
        self.is_reference_corpus = False  # Track if this is a reference corpus

        self.db_service = DBService.get_instance()
        self.project_service = ProjectService()
        self.ingest_service = IngestService()
        self.document_service = DocumentService()
        self.settings = SettingsService.get_instance()

        self.current_worker = None
        self.process_worker = None
        self.process_progress_dialog: Optional[NLPProcessProgressDialog] = None
        self._process_worker_active = False
        self.documents_worker: Optional[DocumentsPageWorker] = None
        self.delete_worker: Optional[DocumentDeleteWorker] = None
        self.delete_progress: Optional[QProgressDialog] = None
        self.snapshot_readiness_worker: Optional[SnapshotReadinessWorker] = None
        self.snapshot_readiness_panel: Optional[SnapshotReadinessPanel] = None

        self._current_dtos: list = []  # PATCH-G: DTO cache for current page
        self._request_seq = 0
        self._active_request_id = 0
        self._snapshot_request_seq = 0
        self._active_snapshot_request_id = 0

        # Pagination + sorting state (server-side).
        self.current_page = 1
        self.page_size = max(25, self.settings.get_int("documents_view/page_size", 25))
        self.total_count = 0
        self.sort_column = self.settings.get_string("documents_view/sort_column", "imported_at")
        self.sort_direction = self.settings.get_string("documents_view/sort_direction", "desc")
        if self.sort_column not in {
            "doc_id",
            "file_name",
            "file_size_bytes",
            "status",
            "sentence_count",
            "token_count",
            "imported_at",
            "file_path",
            "tag",
            "link_url",
            "level",
            "topic",
        }:
            self.sort_column = "imported_at"
        if self.sort_direction not in ("asc", "desc"):
            self.sort_direction = "desc"
        self.current_filters: Dict[str, Optional[str]] = {}

        # Debounce timer for search/filter
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)
        self._filter_timer.timeout.connect(self._on_filter_timeout)

        self.init_ui()
        self.load_corpus()
        self.load_documents()

        # Enable drag and drop (will check is_reference_corpus in dragEnterEvent)
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
        self.add_btn = QPushButton("Add Files...")
        self.add_btn.clicked.connect(self.on_add_files)
        header_layout.addWidget(self.add_btn)

        # Add folder button
        self.add_folder_btn = QPushButton("Add Folder...")
        self.add_folder_btn.clicked.connect(self.on_add_folder)
        header_layout.addWidget(self.add_folder_btn)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_documents)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # --- Search / Filter row ---
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Search title:"))
        self.title_search_edit = QLineEdit()
        self.title_search_edit.setPlaceholderText("Filter by file name...")
        self.title_search_edit.setMaximumWidth(220)
        self.title_search_edit.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.title_search_edit)

        filter_layout.addWidget(QLabel("Level:"))
        self.level_filter_combo = QComboBox()
        self.level_filter_combo.addItems(["All", "aleph", "bet", "gimel", "he"])
        self.level_filter_combo.setMaximumWidth(90)
        self.level_filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.level_filter_combo)

        filter_layout.addWidget(QLabel("Tag:"))
        self.tag_filter_edit = QLineEdit()
        self.tag_filter_edit.setPlaceholderText("Filter by tag...")
        self.tag_filter_edit.setMaximumWidth(150)
        self.tag_filter_edit.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.tag_filter_edit)

        clear_filters_btn = QPushButton("Clear")
        clear_filters_btn.setMaximumWidth(60)
        clear_filters_btn.clicked.connect(self._on_clear_filters)
        filter_layout.addWidget(clear_filters_btn)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

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
            engine_label = QLabel(f"вњ… Stanza engine available (GPU: {'Yes' if self.cuda_available else 'No'})")
            engine_label.setStyleSheet("color: green;")
        else:
            engine_label = QLabel("вљ пёЏ Stanza not available - using Mock engine")
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

        self.snapshot_readiness_panel = SnapshotReadinessPanel(self)
        self.snapshot_readiness_panel.refresh_requested.connect(self.refresh_snapshot_readiness)
        self.snapshot_readiness_panel.copy_cli_requested.connect(self._copy_snapshot_coverage_cli)
        self.snapshot_readiness_panel.open_runbook_requested.connect(self._open_snapshot_runbook)
        layout.addWidget(self.snapshot_readiness_panel)

        # Drag-drop hint
        self.hint_label = QLabel(
            "рџ’Ў Drag and drop files here to import them\n"
            "Supported formats: .txt, .docx, .pptx, .pdf"
        )
        self.hint_label.setStyleSheet(
            "padding: 10px; "
            "background-color: #f0f0f0; "
            "border: 2px dashed #ccc; "
            "border-radius: 5px;"
        )
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)

        # Documents table — PATCH-G: QTableView + DocumentsTableModel
        self._docs_model = DocumentsTableModel(self)
        self._docs_model.rename_committed.connect(self._on_rename_committed)

        self.docs_table = QTableView()
        self.docs_table.setModel(self._docs_model)
        self.docs_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.docs_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.docs_table.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.EditKeyPressed
        )
        self.docs_table.setSortingEnabled(False)
        self.docs_table.setAlternatingRowColors(True)
        self.docs_table.verticalHeader().setVisible(False)

        # Install event filter for F2 key
        self.docs_table.installEventFilter(self)

        # Server-side sort: header click → on_header_clicked
        self.docs_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)

        self.table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="documents_view",
            table=self.docs_table,
            default_widths={
                0: 60,   # ID
                1: 220,  # File Name
                2: 90,   # Size
                3: 110,  # Status
                4: 90,   # Sentences
                5: 90,   # Tokens
                6: 130,  # Imported
                7: 260,  # Path
                8: 120,  # Tag
                9: 180,  # Link
                10: 80,  # Level
                11: 160, # Topic
            },
        )
        self.table_layout_controller.install()

        # Context menu
        self.docs_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.docs_table.customContextMenuRequested.connect(self.show_context_menu)

        # Link click handler (QTableView uses clicked signal with QModelIndex)
        self.docs_table.clicked.connect(self._on_cell_clicked)

        # Selection changes
        self.docs_table.selectionModel().selectionChanged.connect(
            lambda *_: self.on_selection_changed()
        )

        layout.addWidget(self.docs_table)

        # Pagination bar
        pagination_layout = QHBoxLayout()
        self.first_btn = QPushButton("<<")
        self.first_btn.setToolTip("First page")
        self.first_btn.clicked.connect(self.on_first_page)
        pagination_layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setToolTip("Previous page")
        self.prev_btn.clicked.connect(self.on_prev_page)
        pagination_layout.addWidget(self.prev_btn)

        pagination_layout.addWidget(QLabel("Page:"))
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.valueChanged.connect(self.on_page_changed)
        pagination_layout.addWidget(self.page_spinbox)

        self.page_total_label = QLabel("of 1")
        pagination_layout.addWidget(self.page_total_label)

        self.next_btn = QPushButton(">")
        self.next_btn.setToolTip("Next page")
        self.next_btn.clicked.connect(self.on_next_page)
        pagination_layout.addWidget(self.next_btn)

        self.last_btn = QPushButton(">>")
        self.last_btn.setToolTip("Last page")
        self.last_btn.clicked.connect(self.on_last_page)
        pagination_layout.addWidget(self.last_btn)

        pagination_layout.addSpacing(12)
        pagination_layout.addWidget(QLabel("Page size:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250", "500"])
        if str(self.page_size) not in {"25", "50", "100", "250", "500"}:
            self.page_size = 25
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        pagination_layout.addWidget(self.page_size_combo)

        pagination_layout.addStretch()
        self.range_label = QLabel("Showing 0-0 of 0")
        pagination_layout.addWidget(self.range_label)
        layout.addLayout(pagination_layout)

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

        self.setLayout(layout)
        self._update_sort_header_labels()
        self.update_pagination_controls(is_loading=False)

    def _check_stanza_available(self):
        """Check if Stanza is available."""
        try:
            import stanza
            return True
        except ImportError:
            return False
        except Exception as exc:
            # Handle native dependency load failures (e.g. torch DLL init errors)
            # so project opening stays operational without NLP acceleration.
            logger.warning("Stanza check failed; NLP features will be disabled: %s", exc)
            return False

    def _check_cuda_available(self):
        """Check if CUDA is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
        except Exception as exc:
            logger.warning("CUDA availability check failed; GPU NLP disabled: %s", exc)
            return False

    def load_corpus(self):
        """Load the default corpus for this project."""
        try:
            with self.db_service.get_session() as session:
                # Get project to check reference flags.
                # is_general_corpus: used as reference corpus for term scoring.
                # is_reference (PERF-SCALE PATCH-A): physical RO DB mount — also read-only.
                project = self.project_service.get_project(session, self.project_id)
                if project:
                    self.is_reference_corpus = bool(
                        project.is_general_corpus
                        or getattr(project, "is_reference", 0)
                    )

                corpus = self.project_service.get_default_corpus(session, self.project_id)
                if corpus:
                    self.corpus_id = corpus.corpus_id
                    logger.info(f"Loaded corpus: {corpus.name} (ID: {corpus.corpus_id}, Reference: {self.is_reference_corpus})")
                else:
                    logger.error(f"No corpus found for project {self.project_id}")

                # Update UI for reference corpus
                if self.is_reference_corpus:
                    self._configure_reference_corpus_ui()
            self.refresh_snapshot_readiness()
        except Exception as e:
            logger.exception("Failed to load corpus")
            show_error(self, "Error", f"Failed to load corpus: {e}")

    def refresh_snapshot_readiness(self) -> None:
        """Load snapshot readiness summary in the background."""
        panel = self.__dict__.get("snapshot_readiness_panel")
        if panel is None:
            return

        self._snapshot_request_seq += 1
        request_id = int(self._snapshot_request_seq)
        self._active_snapshot_request_id = request_id

        if self.snapshot_readiness_worker and self.snapshot_readiness_worker.isRunning():
            self.snapshot_readiness_worker.cancel()

        panel.set_loading("Refreshing snapshot readiness...")

        worker = SnapshotReadinessWorker(request_id=request_id, project_id=self.project_id)
        self.snapshot_readiness_worker = worker
        worker.status.connect(self.on_snapshot_readiness_status)
        worker.summary_ready.connect(self.on_snapshot_readiness_loaded)
        worker.error.connect(self.on_snapshot_readiness_error)
        worker.finished.connect(lambda current=worker: self._on_snapshot_readiness_worker_finished(current))
        worker.start()

    def on_snapshot_readiness_status(self, request_id: int, status_text: str) -> None:
        if int(request_id) != self._active_snapshot_request_id:
            return
        panel = self.__dict__.get("snapshot_readiness_panel")
        if panel is not None:
            panel.set_loading(status_text)

    def on_snapshot_readiness_loaded(self, request_id: int, summary) -> None:
        if int(request_id) != self._active_snapshot_request_id:
            return
        panel = self.__dict__.get("snapshot_readiness_panel")
        if panel is not None:
            panel.set_summary(summary)

    def on_snapshot_readiness_error(self, request_id: int, message: str) -> None:
        if int(request_id) != self._active_snapshot_request_id:
            return
        panel = self.__dict__.get("snapshot_readiness_panel")
        if panel is not None:
            panel.set_error(f"Snapshot readiness unavailable: {message}")

    def _on_snapshot_readiness_worker_finished(self, worker: SnapshotReadinessWorker) -> None:
        if worker is self.snapshot_readiness_worker:
            self.snapshot_readiness_worker = None
        worker.deleteLater()

    def _copy_snapshot_coverage_cli(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        db_path = getattr(self.db_service.db_manager, "db_path", None)
        if db_path is None:
            return
        command = (
            f'python scripts/process_reference_corpus.py --db-path "{db_path}" '
            f"--project-id {int(self.project_id)} --backfill-snapshots --coverage-only"
        )
        app.clipboard().setText(command)
        self.status_label.setText("Coverage CLI copied to clipboard.")

    def _open_snapshot_runbook(self) -> None:
        docs_path = Path(__file__).resolve().parents[1].parent / "docs" / "NLP_SNAPSHOT_BACKFILL_DECISION_GATE.md"
        if not docs_path.exists():
            show_info(self, "Runbook", f"Open manually:\n{docs_path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(docs_path))):
            show_info(self, "Runbook", f"Open manually:\n{docs_path}")

    def _stop_snapshot_readiness_worker(self) -> None:
        if self.snapshot_readiness_worker and self.snapshot_readiness_worker.isRunning():
            logger.info("Stopping snapshot readiness worker on close")
            self.snapshot_readiness_worker.cancel()
            if not self.snapshot_readiness_worker.wait(100):
                logger.info("Snapshot readiness worker will finish cooperatively after close")

    def load_documents(self):
        """Load current page using server-side pagination (global filters/sort)."""
        self.reload_documents(reset_page=False)

    def _on_filter_changed(self):
        """Debounced filter change handler."""
        self._filter_timer.start()

    def _on_filter_timeout(self):
        """Apply filters globally and reset to page 1."""
        self.reload_documents(reset_page=True)

    def _on_clear_filters(self):
        """Clear all search/filter fields."""
        self.title_search_edit.blockSignals(True)
        self.tag_filter_edit.blockSignals(True)
        self.title_search_edit.clear()
        self.tag_filter_edit.clear()
        self.level_filter_combo.setCurrentIndex(0)
        self.title_search_edit.blockSignals(False)
        self.tag_filter_edit.blockSignals(False)
        self.reload_documents(reset_page=True)

    def build_filters(self) -> Dict[str, Optional[str]]:
        """Build global SQL filters from current controls."""
        title_search = self.title_search_edit.text().strip() or None
        tag_filter = self.tag_filter_edit.text().strip() or None
        level_text = self.level_filter_combo.currentText()
        level_filter = level_text if level_text != "All" else None
        return {
            "title_search": title_search,
            "tag_filter": tag_filter,
            "level_filter": level_filter,
            "topic_filter": None,
            "status_filter": None,
        }

    def reload_documents(self, *, reset_page: bool):
        """Start async page load; stale responses are ignored by request_id."""
        if not self.corpus_id:
            return
        if reset_page:
            self.current_page = 1
        self.current_filters = self.build_filters()
        self._request_seq += 1
        request_id = int(self._request_seq)
        self._active_request_id = request_id

        if self.documents_worker and self.documents_worker.isRunning():
            self.documents_worker.cancel()

        self.update_pagination_controls(is_loading=True)
        self.status_label.setText("Loading documents...")

        worker = DocumentsPageWorker(
            request_id=request_id,
            corpus_id=self.corpus_id,
            filters=self.current_filters,
            sort_column=self.sort_column,
            sort_direction=self.sort_direction,
            page_size=self.page_size,
            page_index=self.current_page,
        )
        self.documents_worker = worker
        worker.status.connect(self.on_documents_worker_status)
        worker.page_loaded.connect(self.on_documents_page_loaded)
        worker.error.connect(self.on_documents_page_error)
        worker.start()

    def on_documents_worker_status(self, request_id: int, status_text: str):
        if int(request_id) != self._active_request_id:
            return
        self.status_label.setText(status_text)

    def on_documents_page_loaded(self, request_id: int, total_count: int, rows: list):
        """Apply page result only when request is current (anti-stale)."""
        if int(request_id) != self._active_request_id:
            return

        self.total_count = int(total_count)
        total_pages = self.total_pages
        if total_pages > 0 and self.current_page > total_pages:
            self.current_page = total_pages
            self.reload_documents(reset_page=False)
            return

        self._render_documents_rows(rows)
        self.update_pagination_controls(is_loading=False)

        start = 0 if self.total_count == 0 else self.current_offset + 1
        end = min(self.current_offset + self.page_size, self.total_count)
        self.status_label.setText(f"Loaded {start}-{end} of {self.total_count}")
        self.on_selection_changed()

    def on_documents_page_error(self, request_id: int, error_message: str):
        if int(request_id) != self._active_request_id:
            return
        logger.error("Documents page load failed: %s", error_message)
        self.status_label.setText(f"Load failed: {error_message}")
        self.update_pagination_controls(is_loading=False)

    def _render_documents_rows(self, dtos: list):
        """Push one page of DTOs into the model (PATCH-G: replaces setItem loops)."""
        self._current_dtos = list(dtos)
        self._docs_model.update_rows(dtos)

    @property
    def total_pages(self) -> int:
        if self.total_count <= 0:
            return 1
        return max(1, (self.total_count + self.page_size - 1) // self.page_size)

    @property
    def current_offset(self) -> int:
        return (self.current_page - 1) * self.page_size

    def update_pagination_controls(self, *, is_loading: bool):
        total_pages = self.total_pages
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setMaximum(max(1, total_pages))
        self.page_spinbox.setValue(min(max(1, self.current_page), total_pages))
        self.page_spinbox.blockSignals(False)
        self.page_total_label.setText(f"of {total_pages}")

        if self.total_count <= 0:
            self.range_label.setText("Showing 0-0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}-{end} of {self.total_count}")

        can_prev = (self.current_page > 1) and not is_loading
        can_next = (self.current_page < total_pages) and not is_loading
        self.first_btn.setEnabled(can_prev)
        self.prev_btn.setEnabled(can_prev)
        self.next_btn.setEnabled(can_next)
        self.last_btn.setEnabled(can_next)
        self.page_spinbox.setEnabled(not is_loading)

    def on_first_page(self):
        if self.current_page != 1:
            self.current_page = 1
            self.reload_documents(reset_page=False)

    def on_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.reload_documents(reset_page=False)

    def on_next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.reload_documents(reset_page=False)

    def on_last_page(self):
        target = self.total_pages
        if self.current_page != target:
            self.current_page = target
            self.reload_documents(reset_page=False)

    def on_page_changed(self, page: int):
        page = int(page)
        if page != self.current_page:
            self.current_page = page
            self.reload_documents(reset_page=False)

    def on_page_size_changed(self, value: str):
        try:
            new_size = int(value)
        except (TypeError, ValueError):
            return
        if new_size <= 0 or new_size == self.page_size:
            return
        self.page_size = new_size
        self.settings.set_value("documents_view/page_size", self.page_size)
        self.current_page = 1
        self.reload_documents(reset_page=False)

    def on_header_clicked(self, column: int):
        """Global sorting: SQL ORDER BY before pagination."""
        sort_key = self.COLUMN_TO_DB.get(int(column))
        if not sort_key:
            return

        if self.sort_column == sort_key:
            self.sort_direction = "desc" if self.sort_direction == "asc" else "asc"
        else:
            self.sort_column = sort_key
            self.sort_direction = "asc"

        self.settings.set_value("documents_view/sort_column", self.sort_column)
        self.settings.set_value("documents_view/sort_direction", self.sort_direction)
        self.current_page = 1
        self._update_sort_header_labels()
        self.reload_documents(reset_page=False)

    def _update_sort_header_labels(self):
        """Show active server-side sort indicator in headers (PATCH-G: model-driven)."""
        sort_col_idx = next(
            (k for k, v in self.COLUMN_TO_DB.items() if v == self.sort_column), None
        )
        self._docs_model.set_sort_indicator(sort_col_idx, self.sort_direction)

    def _on_cell_clicked(self, index):
        """Handle click on Link column - open URL safely (PATCH-G: QModelIndex)."""
        if index.column() != self.COL_LINK:
            return
        url = index.data(Qt.ItemDataRole.UserRole + 1)
        if not url:
            return
        # Safety: re-validate scheme before opening
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                show_error(self, "Unsafe Link", f"Link scheme '{parsed.scheme}' is not allowed.")
                return
        except Exception:
            show_error(self, "Invalid Link", "Could not parse link URL.")
            return
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _configure_reference_corpus_ui(self):
        """Configure UI for reference corpus (read-only documents)."""
        # Disable import buttons
        self.add_btn.setEnabled(False)
        self.add_btn.setToolTip("Cannot add documents to reference corpus (read-only)")
        self.add_folder_btn.setEnabled(False)
        self.add_folder_btn.setToolTip("Cannot add documents to reference corpus (read-only)")

        # Disable delete button
        self.delete_btn.setEnabled(False)
        self.delete_btn.setToolTip("Cannot delete documents from reference corpus (read-only)")

        # PERF-SCALE PATCH-J: Disable NLP process/re-process buttons on reference corpus.
        # Processing 387K reference docs must be done via CLI only
        # (scripts/process_reference_corpus.py) to avoid UI lockup and unguarded
        # multi-hour write sessions.
        _process_tip = (
            "NLP processing of reference corpus is CLI-only.\n"
            "Use: python scripts/process_reference_corpus.py --project-id <id>"
        )
        for attr in ("process_btn", "reprocess_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(False)
                btn.setToolTip(_process_tip)

        # Update hint label
        self.hint_label.setText(
            "в„№пёЏ This is a Reference Corpus (read-only documents)\n"
            "You can browse documents, extract terms, and manage translations,\n"
            "but cannot add or remove documents"
        )
        self.hint_label.setStyleSheet(
            "padding: 10px; "
            "background-color: #e3f2fd; "
            "border: 2px solid #2196F3; "
            "border-radius: 5px;"
        )

    def on_add_files(self):
        """Handle add files button."""
        # Block for reference corpus
        if self.is_reference_corpus:
            show_warning(
                self,
                "Reference Corpus",
                "Cannot add documents to reference corpus.\n\n"
                "Reference corpora are read-only for document operations.\n"
                "You can still browse documents and manage translations."
            )
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files",
            "",
            "Supported Files (*.txt *.docx *.pptx *.pdf);;All Files (*.*)"
        )

        if file_paths:
            self.import_files([Path(p) for p in file_paths])

    def on_add_folder(self):
        """Handle add folder button."""
        # Block for reference corpus
        if self.is_reference_corpus:
            show_warning(
                self,
                "Reference Corpus",
                "Cannot add documents to reference corpus.\n\n"
                "Reference corpora are read-only for document operations.\n"
                "You can still browse documents and manage translations."
            )
            return

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder"
        )

        if folder_path:
            folder = Path(folder_path)
            # Find all supported files
            files = []
            for ext in ['.txt', '.docx', '.pptx', '.pdf']:
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

        # PERF-SCALE PATCH-K: throttle check — block concurrent heavy ingest.
        from app.services.pipeline_throttler import PipelineThrottler
        if not PipelineThrottler.instance().check_and_warn(
            "ingest", parent=self, operation_label=f"Import ({len(file_paths)} files)"
        ):
            return

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
        selected_indexes = self.docs_table.selectionModel().selectedRows()
        has_selection = bool(selected_indexes)
        self.view_text_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(
            has_selection and not self.is_reference_corpus and not self._process_worker_active
        )

        if has_selection:
            has_processed = False
            has_unprocessed = False
            for idx in selected_indexes:
                dto = self._docs_model.get_dto(idx.row())
                if dto is None:
                    continue
                if dto.status in ('processed', 'failed'):
                    has_processed = True
                else:
                    has_unprocessed = True
            self.process_btn.setEnabled(has_unprocessed and not self._process_worker_active)
            self.reprocess_btn.setEnabled(has_processed and not self._process_worker_active)
        else:
            self.process_btn.setEnabled(False)
            self.reprocess_btn.setEnabled(False)

    def _selected_document_rows(self) -> list[int]:
        """Return selected model rows in stable visual order."""
        return sorted({idx.row() for idx in self.docs_table.selectionModel().selectedRows()})

    def _selected_document_payload(self) -> tuple[list[int], list[str]]:
        """Return selected document IDs and file names in table order."""
        doc_ids: list[int] = []
        doc_names: list[str] = []
        for row in self._selected_document_rows():
            dto = self._docs_model.get_dto(row)
            if dto is None:
                continue
            doc_ids.append(int(dto.doc_id))
            doc_names.append(str(dto.file_name))
        return doc_ids, doc_names

    def _confirm_delete_documents(self, doc_names: List[str]) -> bool:
        """Show destructive confirmation dialog with the full File Name list."""
        if not doc_names:
            return False
        dialog = DeleteDocumentsConfirmDialog(doc_names, self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _cleanup_delete_worker(self) -> None:
        if self.delete_progress is not None:
            self.delete_progress.close()
            self.delete_progress.deleteLater()
            self.delete_progress = None
        if self.delete_worker is not None:
            self.delete_worker.deleteLater()
            self.delete_worker = None

    def _start_delete_documents(self, doc_ids: List[int], doc_names: List[str]) -> None:
        """Run document deletion in background and refresh once on completion."""
        if self.delete_worker and self.delete_worker.isRunning():
            show_warning(self, "Delete In Progress", "Document deletion is already running.")
            return

        self.delete_btn.setEnabled(False)
        self.delete_progress = QProgressDialog("Deleting documents...", "", 0, max(1, len(doc_ids)), self)
        self.delete_progress.setWindowTitle("Delete Documents")
        self.delete_progress.setCancelButton(None)
        self.delete_progress.setMinimumDuration(0)
        self.delete_progress.setModal(True)
        self.delete_progress.show()

        worker = DocumentDeleteWorker(doc_ids)
        self.delete_worker = worker
        worker.progress.connect(self._on_delete_progress)
        worker.finished.connect(lambda result: self._on_delete_finished(result, doc_names))
        worker.error.connect(self._on_delete_error)
        worker.start()

    def _on_delete_progress(self, current: int, total: int, file_name: str) -> None:
        if self.delete_progress is None:
            return
        self.delete_progress.setMaximum(max(1, int(total)))
        self.delete_progress.setValue(int(current))
        self.delete_progress.setLabelText(f"Deleting {file_name} ({current}/{total})")

    def _on_delete_finished(self, result: dict, doc_names: List[str]) -> None:
        self._cleanup_delete_worker()
        deleted = int(result.get("deleted", 0) or 0)
        failed = int(result.get("failed", 0) or 0)
        self.load_documents()
        if deleted > 0:
            self.refresh_snapshot_readiness()
        if failed:
            show_error(
                self,
                "Delete Failed",
                f"Deleted: {deleted}\nFailed: {failed}\n\nCheck logs for details.",
            )
            return
        if deleted == 1 and doc_names:
            show_info(self, "Success", f"Document deleted: {doc_names[0]}")
            return
        show_info(self, "Success", f"Successfully deleted {deleted} document(s)")

    def _on_delete_error(self, message: str) -> None:
        self._cleanup_delete_worker()
        self.on_selection_changed()
        show_error(self, "Delete Failed", f"Failed to delete document(s): {message}")

    def _sync_context_selection(self, position) -> None:
        """Right-click on an unselected row should target that row, not stale selection."""
        index = self.docs_table.indexAt(position)
        if not index.isValid():
            return
        selection_model = self.docs_table.selectionModel()
        if selection_model.isRowSelected(index.row(), QModelIndex()):
            return
        selection_model.select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )
        self.docs_table.setCurrentIndex(index)

    def on_process(self):
        """Process selected documents with NLP."""
        # PERF-SCALE PATCH-J: hard block for reference corpus — CLI only.
        if self.is_reference_corpus:
            from app.ui.helpers import show_warning
            show_warning(
                self,
                "Reference Corpus — CLI Only",
                "NLP processing of a reference corpus is not allowed from the UI.\n\n"
                "Use the CLI script instead:\n"
                "  python scripts/process_reference_corpus.py --project-id <id>\n\n"
                "This protects against accidental multi-hour write sessions that would\n"
                "block all other operations.",
            )
            return

        selected_rows = {idx.row() for idx in self.docs_table.selectionModel().selectedRows()}
        if not selected_rows:
            return

        # Get selected document IDs and check statuses
        doc_ids = []
        processed_docs = []
        for row in sorted(selected_rows):
            dto = self._docs_model.get_dto(row)
            if dto is None:
                continue
            if dto.status in ('processed', 'failed'):
                processed_docs.append(dto.file_name)
            else:
                doc_ids.append(dto.doc_id)

        # Warn if trying to process already-processed documents
        if processed_docs:
            from PyQt6.QtWidgets import QMessageBox
            msg = (
                f"{len(processed_docs)} document(s) already processed:\n\n" +
                "\n".join(f"вЂў {name}" for name in processed_docs[:5])
            )
            if len(processed_docs) > 5:
                msg += f"\n... and {len(processed_docs) - 5} more"

            msg += "\n\nUse 'Re-process' button instead to re-process these documents."

            reply = QMessageBox.warning(
                self,
                "Documents Already Processed",
                msg,
                QMessageBox.StandardButton.Ok
            )
            return

        if not doc_ids:
            show_info(self, "Info", "No unprocessed documents selected")
            return

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
            # PERF-SCALE PATCH-K: throttle check — block concurrent NLP runs.
            from app.services.pipeline_throttler import PipelineThrottler
            if not PipelineThrottler.instance().check_and_warn(
                "nlp_process", parent=self,
                operation_label=f"NLP Process ({len(doc_ids)} docs)"
            ):
                return

            self._start_process_worker(
                doc_ids,
                use_mock=use_mock,
                use_gpu=use_gpu,
                is_reprocess=False,
            )

    def _set_process_ui_busy(self, busy: bool) -> None:
        self._process_worker_active = bool(busy)
        if busy:
            self.process_btn.setEnabled(False)
            self.reprocess_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
        else:
            self.on_selection_changed()

    def _start_process_worker(
        self,
        doc_ids: list[int],
        *,
        use_mock: bool,
        use_gpu: bool,
        is_reprocess: bool,
    ) -> None:
        if self.process_worker and self.process_worker.isRunning():
            show_error(self, "Error", "Processing already in progress")
            return

        operation_label = "Re-processing" if is_reprocess else "Processing"

        self.process_worker = ProcessWorker(
            doc_ids=doc_ids,
            use_mock=use_mock,
            use_gpu=use_gpu,
            is_reprocess=is_reprocess,
        )
        self.process_worker.progress.connect(self.on_process_progress)
        self.process_worker.state_changed.connect(self.on_process_state)
        self.process_worker.finished.connect(self.on_process_finished)
        self.process_worker.error.connect(self.on_process_error)

        if self.process_progress_dialog is not None:
            self.process_progress_dialog.deleteLater()
            self.process_progress_dialog = None

        self.process_progress_dialog = NLPProcessProgressDialog(
            parent=self,
            total_docs=len(doc_ids),
            operation_label=operation_label,
        )
        self.process_progress_dialog.cancel_requested.connect(self.process_worker.cancel)
        self.process_progress_dialog.pause_requested.connect(self.process_worker.pause)
        self.process_progress_dialog.resume_requested.connect(self.process_worker.resume)
        self.process_progress_dialog.show()

        self.progress_bar.setMaximum(len(doc_ids))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"{operation_label} documents with NLP...")
        self._set_process_ui_busy(True)
        self.process_worker.start()

    def on_process_progress(self, current: int, total: int, doc_name: str):
        """Handle processing progress update."""
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(min(current, total))
        message = f"Starting {current}/{total}: {doc_name}"
        self.status_label.setText(message)
        if self.process_progress_dialog is not None:
            self.process_progress_dialog.append_activity(message)

    def on_process_state(self, state: dict):
        """Handle structured NLP processing state."""
        docs_processed = int(state.get("docs_processed") or 0)
        docs_failed = int(state.get("docs_failed") or 0)
        docs_total = int(state.get("docs_total") or 0)
        docs_done = docs_processed + docs_failed
        stage = str(state.get("message") or state.get("stage") or "Running NLP...")

        if docs_total > 0:
            self.progress_bar.setMaximum(docs_total)
            self.progress_bar.setValue(min(docs_done, docs_total))
        else:
            self.progress_bar.setMaximum(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText(stage)

        if self.process_progress_dialog is not None:
            self.process_progress_dialog.update_state(state)

    def on_process_finished(self, result: dict):
        """Handle processing completion."""
        self.progress_bar.setVisible(False)
        success_count = int(result.get("success_count") or 0)
        error_count = int(result.get("error_count") or 0)
        cancelled = bool(result.get("cancelled"))
        docs_processed = int(result.get("docs_processed") or 0)
        operation_label = str(result.get("operation_label") or "Processing")

        if cancelled:
            self.status_label.setText(
                f"{operation_label} cancelled: {success_count} succeeded, {error_count} failed"
            )
            if self.process_progress_dialog is not None:
                self.process_progress_dialog.set_cancelled()
                self.process_progress_dialog.accept()
        else:
            self.status_label.setText(
                f"{operation_label} complete: {success_count} succeeded, {error_count} failed"
            )
            if self.process_progress_dialog is not None:
                self.process_progress_dialog.set_completed()
                self.process_progress_dialog.accept()

        # Reload documents to show updated status
        self.load_documents()
        if success_count > 0 or docs_processed > 0:
            self.refresh_snapshot_readiness()

        # Emit signal to update other views (e.g., Dictionary)
        if success_count > 0:
            self.processing_completed.emit()

        if cancelled:
            show_info(
                self,
                f"{operation_label} Cancelled",
                f"{operation_label} stopped at a safe checkpoint.\n\n"
                f"Succeeded: {success_count}\n"
                f"Failed: {error_count}",
            )
        elif error_count > 0:
            show_warning(
                self,
                f"{operation_label} Warnings",
                f"{error_count} document(s) failed to process. Check logs for details."
            )

        self._cleanup_process_worker()

    def on_process_error(self, error_msg: str):
        """Handle processing error."""
        self.progress_bar.setVisible(False)
        operation_label = (
            self.process_progress_dialog.operation_label
            if self.process_progress_dialog is not None
            else "Processing"
        )
        self.status_label.setText(f"{operation_label} failed")
        if self.process_progress_dialog is not None:
            self.process_progress_dialog.set_failed(error_msg)
            self.process_progress_dialog.accept()
        show_error(self, f"{operation_label} Error", error_msg)
        self._cleanup_process_worker()

    def _cleanup_process_worker(self) -> None:
        self._set_process_ui_busy(False)
        if self.process_worker is not None:
            self.process_worker.deleteLater()
            self.process_worker = None
        if self.process_progress_dialog is not None:
            self.process_progress_dialog.deleteLater()
            self.process_progress_dialog = None

    def on_reprocess(self):
        """Re-process selected documents with NLP (M4: Live Update)."""
        # PERF-SCALE PATCH-J: hard block for reference corpus — CLI only.
        if self.is_reference_corpus:
            from app.ui.helpers import show_warning
            show_warning(
                self,
                "Reference Corpus — CLI Only",
                "NLP re-processing of a reference corpus is not allowed from the UI.\n\n"
                "Use: python scripts/process_reference_corpus.py --project-id <id>",
            )
            return

        selected_rows = {idx.row() for idx in self.docs_table.selectionModel().selectedRows()}
        if not selected_rows:
            return

        # Get selected document IDs
        doc_ids = []
        for row in sorted(selected_rows):
            dto = self._docs_model.get_dto(row)
            if dto is None:
                continue
            doc_ids.append(dto.doc_id)

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
            # PERF-SCALE PATCH-K: throttle check — block concurrent NLP runs.
            from app.services.pipeline_throttler import PipelineThrottler
            if not PipelineThrottler.instance().check_and_warn(
                "nlp_process", parent=self,
                operation_label=f"NLP Re-process ({len(doc_ids)} docs)"
            ):
                return

            self._start_process_worker(
                doc_ids,
                use_mock=use_mock,
                use_gpu=use_gpu,
                is_reprocess=True,
            )

    def on_view_text(self):
        """View document text."""
        selected_rows = self._selected_document_rows()
        if not selected_rows:
            return

        row = selected_rows[0]
        dto = self._docs_model.get_dto(row)
        if dto is None:
            return
        doc_id = dto.doc_id

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
        """Delete selected document(s) via background worker."""
        if self.process_worker and self.process_worker.isRunning():
            show_error(self, "Processing In Progress", "Cannot delete documents while NLP processing is running.")
            return

        if self.is_reference_corpus:
            show_error(
                self,
                "Reference Corpus",
                "Cannot delete documents from reference corpus.\n\n"
                "Reference corpora are read-only for document operations.",
            )
            return

        doc_ids, doc_names = self._selected_document_payload()
        if not doc_ids:
            return

        if not self._confirm_delete_documents(doc_names):
            return

        self._start_delete_documents(doc_ids, doc_names)

    def show_context_menu(self, position):
        """Show context menu with Rename, Edit Metadata, View Text, and Delete options."""
        self._sync_context_selection(position)
        selected_rows = set(self._selected_document_rows())
        if not selected_rows:
            return

        row = min(selected_rows)

        menu = QMenu(self)

        # Single-selection actions
        if len(selected_rows) == 1:
            rename_action = menu.addAction("Rename (F2)")
            rename_action.triggered.connect(lambda: self.start_rename(row))

            edit_meta_action = menu.addAction("Edit Metadata...")
            edit_meta_action.triggered.connect(lambda: self.on_edit_metadata(row))

            menu.addSeparator()

            view_action = menu.addAction("View Text")
            view_action.triggered.connect(self.on_view_text)

            menu.addSeparator()

        # Delete action (single or multiple)
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(self.on_delete)

        if self.is_reference_corpus:
            delete_action.setEnabled(False)
            delete_action.setToolTip("Cannot delete documents from reference corpus")

        menu.exec(self.docs_table.viewport().mapToGlobal(position))

    def on_edit_metadata(self, row: int):
        """Open Edit Metadata dialog for the document at given row (PATCH-G: DTO-driven)."""
        dto = self._docs_model.get_dto(row)
        if dto is None:
            return
        doc_id = dto.doc_id
        doc_name = dto.file_name
        tag = dto.tag or ""
        link_url = dto.link_url or ""
        level = dto.level or ""
        topic = dto.topic or ""

        dlg = EditMetadataDialog(doc_name, tag, link_url or "", level, topic, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_tag, new_link, new_level, new_topic = dlg.get_values()

        try:
            from app.services.document_service import validate_link_url
            # Validate link_url before saving
            validate_link_url(new_link)
            with self.db_service.get_session() as session:
                self.document_service.update_metadata(
                    session,
                    doc_id,
                    tag=new_tag,
                    link_url=new_link,
                    level=new_level,
                    topic=new_topic,
                )
            self.load_documents()
        except ValueError as e:
            show_error(self, "Validation Error", str(e))
        except Exception as e:
            logger.exception("Failed to update metadata")
            show_error(self, "Error", f"Failed to save metadata: {e}")

    def _on_rename_committed(self, doc_id: int, new_name: str) -> None:
        """Persist inline rename from the table model and refresh the current page."""
        try:
            with self.db_service.get_session() as session:
                self.ingest_service.rename_document(session, int(doc_id), str(new_name))
            self.load_documents()
        except ValueError as e:
            show_error(self, "Validation Error", str(e))
        except Exception as e:
            logger.exception("Failed to rename document")
            show_error(self, "Rename Failed", f"Failed to rename document: {e}")

    def start_rename(self, row):
        """Start editing the File Name column for a specific row (PATCH-G: QTableView)."""
        index = self._docs_model.index(row, self.COL_NAME)
        self.docs_table.setCurrentIndex(index)
        self.docs_table.edit(index)

    # Drag and drop handlers
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event."""
        # Block drag-drop for reference corpus
        if self.is_reference_corpus:
            event.ignore()
            return

        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Handle drop event."""
        # Block drag-drop for reference corpus
        if self.is_reference_corpus:
            show_warning(
                self,
                "Reference Corpus",
                "Cannot add documents to reference corpus.\n\n"
                "Reference corpora are read-only for document operations.\n"
                "You can still browse documents and manage translations."
            )
            event.ignore()
            return

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

    def highlight_document(self, doc_id: int, sentence_id: int = None):
        """
        Highlight and select a specific document in the table (M6 - Concordance navigation).

        Args:
            doc_id: Document ID to highlight
            sentence_id: Optional sentence ID to highlight in text viewer
        """
        logger.info(f"Highlighting document {doc_id}, sentence {sentence_id}")

        # Find the row with this doc_id (PATCH-G: search _current_dtos cache)
        for row, dto in enumerate(self._current_dtos):
            if dto.doc_id == doc_id:
                # Select this row
                self.docs_table.selectRow(row)
                # Scroll to make it visible
                self.docs_table.scrollTo(self._docs_model.index(row, 0))
                logger.info(f"Selected document row {row}")

                # Open text viewer with highlighting (M6 - no placeholder)
                try:
                    with self.db_service.get_session() as session:
                        text = self.ingest_service.get_document_text(session, doc_id)
                        if text:
                            # Get sentence text for highlighting if sentence_id provided
                            highlight_text = None
                            if sentence_id:
                                from app.infra.sa_models import DocumentSentence
                                sentence = session.get(DocumentSentence, sentence_id)
                                if sentence:
                                    highlight_text = sentence.text
                                    logger.info(f"Will highlight: '{highlight_text[:50]}...'")

                            # Open text viewer dialog
                            from app.ui.dialogs import TextViewDialog
                            dialog = TextViewDialog(text, self, highlight_text=highlight_text)
                            dialog.exec()
                        else:
                            logger.warning(f"No text available for document {doc_id}")
                except Exception as e:
                    logger.exception(f"Failed to open text viewer for document {doc_id}")

                break
        else:
            logger.warning(f"Document {doc_id} not found in table")

    def closeEvent(self, event):
        """Handle widget close - ensure workers are stopped."""
        # Stop ingest worker if running
        if self.current_worker and self.current_worker.isRunning():
            logger.info("Stopping ingest worker on close")
            self.current_worker.quit()
            self.current_worker.wait(1000)
            if self.current_worker.isRunning():
                self.current_worker.terminate()

        # Stop process worker if running
        self._stop_process_worker()

        # Stop documents page worker if running
        if self.documents_worker and self.documents_worker.isRunning():
            logger.info("Stopping documents page worker on close")
            self.documents_worker.cancel()
            self.documents_worker.wait(1000)
            if self.documents_worker.isRunning():
                self.documents_worker.terminate()

        self._stop_snapshot_readiness_worker()

        self.table_layout_controller.save_now()

        super().closeEvent(event)

    def _stop_process_worker(self) -> None:
        """Request cooperative stop for NLP processing worker."""
        if not self.process_worker:
            return

        if self.process_progress_dialog is not None:
            self.process_progress_dialog.append_activity(
                "View is closing; requesting cooperative cancellation."
            )

        if self.process_worker.isRunning():
            logger.info("Stopping process worker on close")
            self.process_worker.cancel()
            if not self.process_worker.wait(100):
                logger.info("Process worker will finish cooperatively after close")
                return

        self._cleanup_process_worker()

