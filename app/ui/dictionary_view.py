"""Dictionary view - lemmas and MWE list."""
import logging
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QSpinBox,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QMenu,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QAction

from app.infra.settings import SettingsService
from app.services.db_service import DBService
from app.services.audio_playback_service import AudioPlaybackService
from app.services.translation_service import TranslationService
from app.services.tm_global_service import TMGlobalService
from app.services.user_dictionary_service import UserDictionaryService
from app.domain.normalization.normalizer import normalize_for_tm
from app.domain.dto import LemmaStats
from app.ui.models_qt import LemmaTableModel
from app.ui.multi_sort_proxy import MultiSortProxyModel
from app.ui.table_layout_controller import TableLayoutController
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate
from app.ui.dialogs import show_error, WhyTranslationDialog
from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog
from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.dialogs.add_to_user_dictionary_dialog import show_add_to_user_dictionary_dialog
from app.ui.audio_playlist_actions import add_selected_items_to_playlist_dialog
from app.ui.workers import (
    TranslationResolveWorker,
    DictionarySearchWorker,
    UserDictionaryBulkAddWorker,
    BatchGenerateAudioWorker,
)

logger = logging.getLogger(__name__)


class PosFilterDialog(QDialog):
    """Multi-select checklist dialog for Dictionary POS filter."""

    POS_OPTIONS = [
        ("NOUN", "NOUN"),
        ("VERB", "VERB"),
        ("ADJ", "ADJ"),
        ("ADV", "ADV"),
        ("PROPN", "PROPN"),
        ("NUM", "NUM"),
    ]
    ALL_POS = [pos for pos, _label in POS_OPTIONS]

    def __init__(self, selected_pos: Optional[List[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select POS")
        self.setMinimumSize(280, 260)
        if selected_pos:
            self._selected = [str(pos) for pos in selected_pos if pos]
        else:
            self._selected = list(self.ALL_POS)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        info = QLabel("Select one or more POS tags to include:")
        info.setStyleSheet("font-weight: bold;")
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for pos, label in self.POS_OPTIONS:
            item = QListWidgetItem(label)
            item.setCheckState(
                Qt.CheckState.Checked if pos in self._selected else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, pos)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(self._on_select_all)
        btn_row.addWidget(select_all)
        clear_all = QPushButton("Clear All")
        clear_all.clicked.connect(self._on_clear_all)
        btn_row.addWidget(clear_all)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.setLayout(layout)

    def _on_select_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def _on_clear_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)

    def get_selected_pos(self) -> Optional[List[str]]:
        """Return selected POS tags or None if all/none selected."""
        selected: List[str] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if len(selected) == 0 or len(selected) == len(self.ALL_POS):
            return None
        return selected


class DictionaryView(QWidget):
    """Dictionary view showing lemmas."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()
        self.translation_service = TranslationService()
        self.audio_playback_service = AudioPlaybackService()
        self.user_dict_service = UserDictionaryService()
        self.translation_worker: Optional[TranslationResolveWorker] = None
        self.batch_audio_worker: Optional[BatchGenerateAudioWorker] = None
        self.settings = SettingsService.get_instance()

        # Pagination state
        self.current_page = 1
        self.page_size = self.settings.get_int("dictionary_view/page_size", 100)
        self.total_count = 0
        self.search_worker = None  # Track worker for cancellation
        self._search_request_seq = 0
        self._active_search_seq = 0
        self._search_retry_pending = False
        self._translation_request_seq = 0
        self._active_translation_seq = 0
        self._pending_translation_lemmas: Optional[List[LemmaStats]] = None
        self.sort_column = str(self.settings.get_string("dictionary_view/sort_column", "freq_abs") or "freq_abs")
        self.sort_direction = str(self.settings.get_string("dictionary_view/sort_direction", "desc") or "desc")
        saved_pos = self.settings.get_json("dictionary_view/pos_filter", None)
        if isinstance(saved_pos, list) and len(saved_pos) > 0:
            self.selected_pos: Optional[List[str]] = [str(pos) for pos in saved_pos if pos]
        else:
            self.selected_pos = None

        self.init_ui()
        self.perform_search()

    @property
    def total_pages(self) -> int:
        """Calculate total pages."""
        if self.total_count == 0:
            return 1
        return (self.total_count + self.page_size - 1) // self.page_size

    @property
    def current_offset(self) -> int:
        """Calculate current offset for pagination."""
        return (self.current_page - 1) * self.page_size

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header with filters
        header_layout = QHBoxLayout()

        title = QLabel("Dictionary")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # POS filter
        header_layout.addWidget(QLabel("POS:"))
        self.pos_filter_btn = QPushButton(self._pos_filter_btn_label())
        self.pos_filter_btn.setMinimumWidth(120)
        self.pos_filter_btn.setToolTip("Click to select POS tags to filter")
        self.pos_filter_btn.clicked.connect(self.on_select_pos)
        header_layout.addWidget(self.pos_filter_btn)

        # Hide noise filter (Task 11: Entity Classification)
        self.hide_noise_checkbox = QCheckBox("Hide noise")
        self.hide_noise_checkbox.setChecked(True)  # Default: hide noise
        self.hide_noise_checkbox.setToolTip("Hide punctuation, numbers, symbols, and other noise")
        self.hide_noise_checkbox.stateChanged.connect(self.on_filter_changed)
        header_layout.addWidget(self.hide_noise_checkbox)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.perform_search)
        header_layout.addWidget(refresh_btn)

        # Batch translate button (PATCH-UI-BATCH-T02)
        self.batch_translate_btn = QPushButton("Translate Selected...")
        self.batch_translate_btn.clicked.connect(self.on_batch_translate)
        self.batch_translate_btn.setEnabled(False)  # Disabled until selection
        header_layout.addWidget(self.batch_translate_btn)

        self.generate_audio_btn = QPushButton("Generate Audio...")
        self.generate_audio_btn.clicked.connect(self.on_generate_audio_selected)
        self.generate_audio_btn.setEnabled(False)
        header_layout.addWidget(self.generate_audio_btn)

        self.play_audio_btn = QPushButton("Play Audio")
        self.play_audio_btn.clicked.connect(self.on_play_audio_selected)
        self.play_audio_btn.setEnabled(False)
        header_layout.addWidget(self.play_audio_btn)

        self.pronunciation_bootstrap_btn = QPushButton("Pronunciation Bootstrap...")
        self.pronunciation_bootstrap_btn.clicked.connect(self.on_pronunciation_bootstrap_selected)
        self.pronunciation_bootstrap_btn.setEnabled(False)
        header_layout.addWidget(self.pronunciation_bootstrap_btn)

        layout.addLayout(header_layout)

        # Pagination bar
        pagination_layout = QHBoxLayout()

        # First/Prev buttons
        self.first_btn = QPushButton("<<")
        self.first_btn.setToolTip("First page")
        self.first_btn.setMaximumWidth(40)
        self.first_btn.clicked.connect(self.on_first_page)
        pagination_layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setToolTip("Previous page (Ctrl+Left)")
        self.prev_btn.setMaximumWidth(40)
        self.prev_btn.clicked.connect(self.on_prev_page)
        pagination_layout.addWidget(self.prev_btn)

        # Page number input
        pagination_layout.addWidget(QLabel("Page"))
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(1)
        self.page_spinbox.setValue(1)
        self.page_spinbox.setMaximumWidth(60)
        self.page_spinbox.valueChanged.connect(self.on_page_changed)
        pagination_layout.addWidget(self.page_spinbox)

        self.page_count_label = QLabel("of 1")
        pagination_layout.addWidget(self.page_count_label)

        # Next/Last buttons
        self.next_btn = QPushButton(">")
        self.next_btn.setToolTip("Next page (Ctrl+Right)")
        self.next_btn.setMaximumWidth(40)
        self.next_btn.clicked.connect(self.on_next_page)
        pagination_layout.addWidget(self.next_btn)

        self.last_btn = QPushButton(">>")
        self.last_btn.setToolTip("Last page")
        self.last_btn.setMaximumWidth(40)
        self.last_btn.clicked.connect(self.on_last_page)
        pagination_layout.addWidget(self.last_btn)

        pagination_layout.addSpacing(20)

        # Range label
        self.range_label = QLabel("Showing 0-0 of 0")
        pagination_layout.addWidget(self.range_label)

        pagination_layout.addSpacing(20)

        # Page size selector
        pagination_layout.addWidget(QLabel("Page size:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250", "500"])
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        pagination_layout.addWidget(self.page_size_combo)

        pagination_layout.addStretch()

        layout.addLayout(pagination_layout)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter lemmas...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)

        # Lemma table with proxy model for sorting
        self.lemma_model = LemmaTableModel()
        self.proxy_model = MultiSortProxyModel()
        self.proxy_model.setSourceModel(self.lemma_model)

        self.lemma_table = QTableView()
        self.lemma_table.setModel(self.proxy_model)  # Use proxy model
        self.lemma_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.lemma_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)  # Bulk selection
        # M7 P1: Enable editing for Translation column
        self.lemma_table.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.EditKeyPressed
        )
        self.lemma_table.setSortingEnabled(False)
        header = self.lemma_table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_sort_clicked)

        # Install event filter for Enter key editing and keyboard shortcuts
        self.lemma_table.installEventFilter(self)

        # M7 P1: Context menu for "Why?" action
        self.lemma_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lemma_table.customContextMenuRequested.connect(self.on_context_menu)

        self.table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="dictionary_view",
            table=self.lemma_table,
            default_widths={
                0: 46,   # UD
                1: 220,  # Lemma
                2: 90,   # POS
                3: 95,   # Frequency
                4: 95,   # Doc Freq
                5: 260,  # Translation
                6: 120,  # Source
                7: 110,  # Status
                8: 90,   # Noise
                9: 110,  # Last Review
                10: 180, # Niqqud
                11: 90,  # Audio
            },
        )
        self.table_layout_controller.install()
        self.audio_play_delegate = AudioPlayDelegate(
            self.lemma_table,
            on_play_clicked=self.on_audio_cell_play_clicked,
        )
        self.lemma_table.setItemDelegateForColumn(11, self.audio_play_delegate)

        # M7 P1: Connect dataChanged to save handler
        self.lemma_model.dataChanged.connect(self.on_translation_edited)

        # PATCH-UI-BATCH-T02: Connect selection changed to update button state
        self.lemma_table.selectionModel().selectionChanged.connect(self.on_selection_changed)

        layout.addWidget(self.lemma_table)

        # Status bar
        self.status_label = QLabel("No lemmas")
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self._apply_sort_indicator()

    _SORT_COLUMN_BY_SECTION = {
        1: "lemma_text",
        2: "pos",
        3: "freq_abs",
        4: "doc_freq",
    }
    _SORT_SECTION_BY_COLUMN = {value: key for key, value in _SORT_COLUMN_BY_SECTION.items()}

    def _apply_sort_indicator(self) -> None:
        section = self._SORT_SECTION_BY_COLUMN.get(self.sort_column, 3)
        order = (
            Qt.SortOrder.AscendingOrder
            if str(self.sort_direction).lower() == "asc"
            else Qt.SortOrder.DescendingOrder
        )
        self.lemma_table.horizontalHeader().setSortIndicator(section, order)

    def on_header_sort_clicked(self, section: int) -> None:
        sort_column = self._SORT_COLUMN_BY_SECTION.get(int(section))
        if not sort_column:
            return

        if self.sort_column == sort_column:
            self.sort_direction = "asc" if self.sort_direction == "desc" else "desc"
        else:
            self.sort_column = sort_column
            self.sort_direction = "asc" if sort_column in {"lemma_text", "pos"} else "desc"

        self.settings.set_value("dictionary_view/sort_column", self.sort_column)
        self.settings.set_value("dictionary_view/sort_direction", self.sort_direction)
        self.current_page = 1
        self._apply_sort_indicator()
        self.perform_search()

    def build_filters(self) -> dict:
        """Build filters dict for search."""
        filters = {
            "pos": "All",
            "hide_noise": self.hide_noise_checkbox.isChecked(),
            "search": self.search_edit.text().strip(),
        }
        if self.selected_pos:
            filters["pos_tags"] = list(self.selected_pos)
            filters["pos"] = "All"
        return filters

    def _pos_filter_btn_label(self) -> str:
        if not self.selected_pos:
            return "All POS v"
        if len(self.selected_pos) == 1:
            return f"{self.selected_pos[0]} v"
        return f"{len(self.selected_pos)} POS v"

    def on_select_pos(self):
        """Open POS multi-select dialog and apply filter."""
        dlg = PosFilterDialog(self.selected_pos, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.selected_pos = dlg.get_selected_pos()
        self.settings.set_value("dictionary_view/pos_filter", self.selected_pos)
        self.pos_filter_btn.setText(self._pos_filter_btn_label())
        self.on_filter_changed()

    def on_filter_changed(self):
        """Handle filter change - reset to page 1 and search."""
        self.current_page = 1
        self.perform_search()

    def perform_search(self):
        """Perform search with current filters and pagination."""
        # Cancel previous worker if running
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.cancel()
            if not self.search_worker.wait(100):
                # Don't destroy a running QThread; queue latest request instead.
                self._search_retry_pending = True
                return

        self._search_retry_pending = False

        # Build filters
        filters = self.build_filters()
        self._search_request_seq += 1
        request_seq = self._search_request_seq
        self.total_count = 0

        # Create and start worker
        self.search_worker = DictionarySearchWorker(
            project_id=self.project_id,
            filters=filters,
            limit=self.page_size,
            offset=self.current_offset,
            sort_column=self.sort_column,
            sort_direction=self.sort_direction,
        )
        self._active_search_seq = request_seq

        self.search_worker.results_ready.connect(
            lambda rows, seq=request_seq: self.on_search_results(rows, seq)
        )
        self.search_worker.count_ready.connect(
            lambda total_count, seq=request_seq: self.on_search_count_ready(total_count, seq)
        )
        self.search_worker.error.connect(
            lambda error_msg, seq=request_seq: self.on_search_error(error_msg, seq)
        )
        self.search_worker.finished.connect(
            lambda seq=request_seq, worker=self.search_worker: self._on_search_worker_finished(worker, seq)
        )
        self.search_worker.start()

        # Update status
        self.status_label.setText("Searching...")

    def _on_search_worker_finished(self, worker, request_seq: int):
        """Clean up search worker and run pending search request if queued."""
        if worker is self.search_worker:
            self.search_worker = None

        worker.deleteLater()

        if self._search_retry_pending:
            self._search_retry_pending = False
            QTimer.singleShot(0, self.perform_search)

    def on_search_results(self, rows: list, request_seq: Optional[int] = None):
        """Handle page rows from worker (count arrives asynchronously)."""
        if request_seq is not None and request_seq != self._active_search_seq:
            logger.debug(
                "Ignoring stale dictionary search results: seq=%s, active=%s",
                request_seq,
                self._active_search_seq,
            )
            return

        # Convert rows (Lemma, LemmaProjectStat tuples) to LemmaStats DTOs
        lemmas = []
        for lemma, stat in rows:
            lemma_dto = LemmaStats(
                lemma_id=lemma.lemma_id,
                lemma_text=lemma.lemma_text,
                pos=lemma.pos,
                freq_abs=stat.freq_abs,
                doc_freq=stat.doc_freq,
                translation=None,  # Will be filled by TranslationResolveWorker
                status='auto',
                entity_class=lemma.entity_class if hasattr(lemma, 'entity_class') else None,
                is_noise=lemma.is_noise,
                noise_reason=lemma.noise_reason,
                norm_text=lemma.norm_text,
            )
            lemmas.append(lemma_dto)

        # Show base rows first for fast first-page UX.
        self.lemma_model.update_lemmas(lemmas)
        if not lemmas:
            self.status_label.setText("No lemmas found")
        else:
            start = self.current_offset + 1
            end = self.current_offset + len(lemmas)
            self.status_label.setText(f"Loaded {start}-{end} lemmas (counting total...)")

        self.update_pagination_controls()

        # Stage 2: expensive overlays after first paint.
        QTimer.singleShot(
            0,
            lambda seq=request_seq, payload=lemmas: self._apply_study_overlays_stage2(payload, seq),
        )

        # Start translation worker.
        self.start_translation_worker(lemmas)

    def on_search_count_ready(self, total_count: int, request_seq: Optional[int] = None):
        """Handle deferred total-count result from worker."""
        if request_seq is not None and request_seq != self._active_search_seq:
            logger.debug(
                "Ignoring stale dictionary count: seq=%s, active=%s",
                request_seq,
                self._active_search_seq,
            )
            return

        self.total_count = int(total_count or 0)
        if self.total_count == 0:
            self.status_label.setText("No lemmas found")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + len(self.lemma_model.lemmas), self.total_count)
            self.status_label.setText(f"Showing {start}-{end} of {self.total_count:,} lemmas")
        self.update_pagination_controls()

    def _apply_study_overlays_stage2(self, lemmas: List[LemmaStats], request_seq: Optional[int]) -> None:
        """Attach overlay metadata without delaying initial table render."""
        if request_seq is not None and request_seq != self._active_search_seq:
            return
        if not lemmas:
            return
        self._apply_study_overlays(lemmas)
        if request_seq is not None and request_seq != self._active_search_seq:
            return
        top = self.lemma_model.index(0, 0)
        bottom = self.lemma_model.index(len(lemmas) - 1, self.lemma_model.columnCount() - 1)
        self.lemma_model.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    def _apply_study_overlays(self, lemmas: List[LemmaStats]) -> None:
        """Attach saved-to-UD + study tooltip metadata in one batch lookup."""
        if not lemmas:
            return

        def _lemma_norm(lemma_obj: LemmaStats) -> str:
            normalized = normalize_for_tm("he", lemma_obj.lemma_text, "lemma").norm
            return normalized or (lemma_obj.norm_text or "")

        payloads = []
        raw_norm_pairs = []
        for lemma in lemmas:
            src_norm = _lemma_norm(lemma)
            raw_src_norm = normalize_for_tm("he", lemma.lemma_text, "surface").norm
            raw_src_norm = (raw_src_norm or "").strip() or (lemma.norm_text or "").strip()
            payloads.append(
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "lemma",
                    "src_text": lemma.lemma_text,
                    "src_norm": src_norm,
                    "raw_src_norm": raw_src_norm,
                }
            )
            if raw_src_norm:
                raw_norm_pairs.append(("he", raw_src_norm))

        try:
            with self.db_service.get_session() as session:
                overlay_map = self.user_dict_service.resolve_cross_view_status(session, payloads)
                pronunciation_map = self.user_dict_service._resolve_pronunciation_overlay(session, raw_norm_pairs)
        except Exception as e:
            logger.warning("Failed to resolve dictionary study overlays: %s", e)
            return

        for lemma in lemmas:
            src_norm = _lemma_norm(lemma)
            raw_src_norm = normalize_for_tm("he", lemma.lemma_text, "surface").norm
            raw_src_norm = (raw_src_norm or "").strip() or (lemma.norm_text or "").strip()
            canonical_hash = self.user_dict_service.build_canonical_hash("he", "ru", "lemma", src_norm)
            overlay = overlay_map.get(canonical_hash)
            if not overlay:
                lemma.in_user_dictionary_count = 0
                lemma.study_tooltip = None
                lemma.study_state = None
                lemma.study_due_human = None
                lemma.last_grade = None
                lemma.last_graded_at = None
                lemma.translation_tier = None
                lemma.audio_status = None
                lemma.pronunciation_text = None
                lemma.pronunciation_source = None
                lemma.pronunciation_confidence = None
                lemma.pronunciation_qc = None
                continue

            lemma.in_user_dictionary_count = int(overlay.get("in_user_dictionary_count") or 0)
            lemma.study_tooltip = overlay.get("study_tooltip")
            lemma.study_state = overlay.get("study_state")
            lemma.study_due_human = overlay.get("study_due_human")
            lemma.last_grade = overlay.get("last_grade")
            lemma.last_graded_at = overlay.get("last_graded_at")
            lemma.translation_tier = overlay.get("translation_tier")
            lemma.audio_status = overlay.get("audio_status")
            lemma.pronunciation_text = overlay.get("pronunciation_text")
            lemma.pronunciation_source = overlay.get("pronunciation_source")
            lemma.pronunciation_confidence = overlay.get("pronunciation_confidence")
            lemma.pronunciation_qc = overlay.get("pronunciation_qc")

            row_pron = pronunciation_map.get(("he", raw_src_norm))
            if row_pron:
                lemma.pronunciation_text = row_pron.get("pronunciation_text")
                lemma.pronunciation_source = row_pron.get("pronunciation_source")
                lemma.pronunciation_confidence = row_pron.get("pronunciation_confidence")
                lemma.pronunciation_qc = row_pron.get("pronunciation_qc")

    def on_search_error(self, error_msg: str, request_seq: Optional[int] = None):
        """Handle search error."""
        if request_seq is not None and request_seq != self._active_search_seq:
            logger.debug(f"Ignoring stale dictionary search error: seq={request_seq}, active={self._active_search_seq}")
            return

        logger.error(f"Search error: {error_msg}")
        show_error(self, "Search Error", f"Failed to search lemmas: {error_msg}")
        self.status_label.setText("Search failed")

    def on_search_changed(self, text: str):
        """Handle search text change - reset to page 1 and search."""
        self.current_page = 1
        self.perform_search()

    def on_first_page(self):
        """Navigate to first page."""
        if self.current_page != 1:
            self.current_page = 1
            self.perform_search()

    def on_prev_page(self):
        """Navigate to previous page."""
        if self.current_page > 1:
            self.current_page -= 1
            self.perform_search()

    def on_next_page(self):
        """Navigate to next page."""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.perform_search()

    def on_last_page(self):
        """Navigate to last page."""
        total = self.total_pages
        if self.current_page != total:
            self.current_page = total
            self.perform_search()

    def on_page_changed(self, page: int):
        """Handle page number change from spinbox."""
        if page != self.current_page:
            self.current_page = page
            self.perform_search()

    def on_page_size_changed(self, size_str: str):
        """Handle page size change (Task 15: supports 'All (N)' format)."""
        # Task 15: Handle "All (N)" format
        if size_str.startswith("All"):
            new_size = self.total_count
        else:
            new_size = int(size_str)

        if new_size != self.page_size:
            self.page_size = new_size
            self.settings.set_value("dictionary_view/page_size", self.page_size)
            self.current_page = 1  # Reset to first page
            self.perform_search()

    def update_pagination_controls(self):
        """Update pagination control states based on current page and total."""
        total = self.total_pages

        # Update spinbox range
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setMaximum(total)
        self.page_spinbox.setValue(self.current_page)
        self.page_spinbox.blockSignals(False)

        # Update page count label
        self.page_count_label.setText(f"of {total}")

        # Update button states
        self.first_btn.setEnabled(self.current_page > 1)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < total)
        self.last_btn.setEnabled(self.current_page < total)

        # Update range label
        if self.total_count == 0:
            self.range_label.setText("Showing 0-0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}-{end} of {self.total_count:,}")

        # Task 15: Add "All (N)" page size option if safe
        self._update_page_size_combo()

    def _update_page_size_combo(self):
        """Task 15: Update page_size_combo to include 'All (N)' if safe."""
        MAX_ALL_ROWS_UI = 5000  # Premium safety limit

        # Remove old "All" item if exists
        self.page_size_combo.blockSignals(True)
        for i in range(self.page_size_combo.count()):
            if self.page_size_combo.itemText(i).startswith("All"):
                self.page_size_combo.removeItem(i)
                break

        # Add "All (N)" if safe
        if 0 < self.total_count <= MAX_ALL_ROWS_UI:
            self.page_size_combo.addItem(f"All ({self.total_count})")

        self.page_size_combo.blockSignals(False)

    def focus_lemma_by_id(self, lemma_id: int) -> bool:
        """Best-effort focus helper used by Audio Player 'Go to Source'."""
        for source_row, lemma in enumerate(self.lemma_model.lemmas):
            if int(getattr(lemma, "lemma_id", 0) or 0) != int(lemma_id):
                continue
            source_index = self.lemma_model.index(source_row, 0)
            proxy_index = self.proxy_model.mapFromSource(source_index)
            if not proxy_index.isValid():
                return False
            self.lemma_table.setCurrentIndex(proxy_index)
            self.lemma_table.selectRow(proxy_index.row())
            self.lemma_table.scrollTo(proxy_index, QTableView.ScrollHint.PositionAtCenter)
            return True
        return False

    def start_translation_worker(self, lemmas: List[LemmaStats]):
        """M7 P1: Start worker to resolve translations."""
        if not lemmas:
            return

        # Cancel previous worker if running
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.cancel()
            if not self.translation_worker.wait(100):
                # Keep only latest pending translation request.
                self._pending_translation_lemmas = lemmas
                return

        self._translation_request_seq += 1
        request_seq = self._translation_request_seq

        # Build items for worker: (src_text, kind)
        items = [(lemma.lemma_text, "lemma") for lemma in lemmas]

        # Create and start worker
        self.translation_worker = TranslationResolveWorker(
            items=items,
            project_id=self.project_id,
            src_lang="he",
            tgt_lang="ru",
            allow_draft=False,
        )
        self._active_translation_seq = request_seq

        self.translation_worker.results_ready.connect(
            lambda results, seq=request_seq: self.on_translation_results(results, seq)
        )
        self.translation_worker.error.connect(
            lambda error_msg, seq=request_seq: self.on_translation_error(error_msg, seq)
        )
        self.translation_worker.finished.connect(
            lambda seq=request_seq, worker=self.translation_worker: self._on_translation_worker_finished(worker, seq)
        )
        self.translation_worker.start()

        logger.info(f"Started translation worker for {len(items)} lemmas")

    def _on_translation_worker_finished(self, worker, request_seq: int):
        """Clean up translation worker and run pending request if queued."""
        if worker is self.translation_worker:
            self.translation_worker = None

        worker.deleteLater()

        if self._pending_translation_lemmas:
            pending_lemmas = self._pending_translation_lemmas
            self._pending_translation_lemmas = None
            QTimer.singleShot(0, lambda: self.start_translation_worker(pending_lemmas))

    def on_translation_results(self, results: dict, request_seq: Optional[int] = None):
        """M7 P1: Handle translation results from worker."""
        if request_seq is not None and request_seq != self._active_translation_seq:
            logger.debug(
                f"Ignoring stale dictionary translation results: seq={request_seq}, active={self._active_translation_seq}"
            )
            return

        logger.info(f"Received {len(results)} translation results")

        # Update model with results
        self.lemma_model.update_translations(results)

    def on_translation_error(self, error_msg: str, request_seq: Optional[int] = None):
        """M7 P1: Handle translation worker error."""
        if request_seq is not None and request_seq != self._active_translation_seq:
            logger.debug(
                f"Ignoring stale dictionary translation error: seq={request_seq}, active={self._active_translation_seq}"
            )
            return

        logger.error(f"Translation worker error: {error_msg}")
        show_error(self, "Translation Error", f"Failed to load translations: {error_msg}")

    def on_translation_edited(self, top_left: QModelIndex, bottom_right: QModelIndex, roles):
        """M7 P1: Handle inline edit of translation - save to TM."""
        # Check if Translation column was edited (col 5)
        if top_left.column() != 5:
            return

        row = top_left.row()
        lemma = self.lemma_model.lemmas[row]

        # Get new translation value
        new_translation = lemma.translation

        # Allow empty translations (user can delete translation)
        try:
            with self.db_service.get_session() as session:
                # Save to TM
                from app.infra.sa_models import TMEntry
                from app.domain.normalization import normalize_for_tm
                from datetime import datetime

                # Normalize
                normalized = normalize_for_tm("he", lemma.lemma_text, "lemma")

                # Check if TM entry exists
                from sqlalchemy import select
                stmt = select(TMEntry).where(
                    TMEntry.project_id == self.project_id,
                    TMEntry.kind == "lemma",
                    TMEntry.src_norm == normalized.norm,
                )
                existing = session.execute(stmt).scalar()

                # Strip whitespace but allow empty string (deletion)
                translation_value = new_translation.strip() if new_translation else ""

                if existing:
                    # Update existing
                    existing.translation = translation_value
                    existing.status = "approved"  # User edit -> approved
                    existing.origin = "user_edit"
                    existing.updated_at = datetime.now()
                else:
                    # Create new TM entry with source_id link for is_noise synchronization
                    tm_entry = TMEntry(
                        project_id=self.project_id,
                        kind="lemma",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text=lemma.lemma_text,
                        src_norm=normalized.norm,
                        translation=translation_value,
                        status="approved",  # User edit -> approved
                        origin="user_edit",
                        source_ref="dictionary_view_inline_edit",
                        lemma_id=lemma.lemma_id,  # Link to source for is_noise sync
                        is_noise=lemma.is_noise if lemma.is_noise is not None else 0,
                        noise_reason=lemma.noise_reason,
                    )
                    session.add(tm_entry)

                # PATCH-19-02: Upsert tm_global and link
                # Use retry mechanism to handle database locked errors
                from app.infra.db_retry import with_retry_on_locked

                def save_and_propagate():
                    session.flush()
                    tm_entry_to_link = existing if existing else tm_entry
                    TMGlobalService().upsert_and_link(
                        session,
                        tm_entry_to_link,
                        force_global_update=(translation_value == ""),
                    )
                    session.commit()

                def _on_retry(attempt: int, total_attempts: int, delay: float, _error: str) -> None:
                    self.status_label.setText(f"Database is busy, retrying ({attempt}/{total_attempts})...")

                with_retry_on_locked(
                    save_and_propagate,
                    max_retries=4,
                    rollback_callback=session.rollback,
                    retry_callback=_on_retry,
                )

                # Update status in model to "approved"
                lemma.status = "approved"
                status_idx = self.lemma_model.index(row, 7)  # Status column
                self.lemma_model.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

                logger.info(f"Saved TM entry for lemma: {lemma.lemma_text} -> {translation_value}")

        except Exception as e:
            logger.exception("Failed to save TM entry")
            show_error(self, "Save Error", f"Failed to save translation: {e}")

    def _selected_audio_items(self) -> List[dict]:
        """Build source-audio payloads from selected lemma rows."""
        selected_rows = self.lemma_table.selectionModel().selectedRows()
        items: List[dict] = []
        for proxy_index in sorted(selected_rows, key=lambda idx: idx.row()):
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            lemma = self.lemma_model.lemmas[source_row]
            src_norm = normalize_for_tm("he", lemma.lemma_text, "lemma").norm or (lemma.norm_text or "")
            if not src_norm:
                continue
            items.append(
                {
                    "row_id": str(lemma.lemma_id),
                    "src_text": lemma.lemma_text,
                    "src_lang": "he",
                    "src_norm": src_norm,
                    "kind": "lemma",
                    "source_id": int(lemma.lemma_id),
                    "project_id": getattr(self, "project_id", None),
                    "source_label": "Dictionary",
                    "translation": lemma.translation or "",
                    "pronunciation_text": getattr(lemma, "pronunciation_text", "") or "",
                }
            )
        return items

    def _selected_pronunciation_items(self) -> List[dict]:
        """Build pronunciation payloads from selected lemma rows."""
        selected_rows = self.lemma_table.selectionModel().selectedRows()
        items: List[dict] = []
        for proxy_index in sorted(selected_rows, key=lambda idx: idx.row()):
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            lemma = self.lemma_model.lemmas[source_row]
            src_norm = normalize_for_tm("he", lemma.lemma_text, "surface").norm
            src_norm = (src_norm or "").strip() or (lemma.norm_text or "").strip() or normalize_for_tm(
                "he", lemma.lemma_text, "lemma"
            ).norm
            if not src_norm:
                continue
            items.append(
                {
                    "src_lang": "he",
                    "src_text": lemma.lemma_text,
                    "src_norm": src_norm,
                    "raw_src_norm": src_norm,
                    "source_group": "lemmas",
                }
            )
        return items

    def on_generate_audio_selected(self):
        """Generate source-audio for selected rows."""
        items = self._selected_audio_items()
        if not items:
            return

        accepted, provider_mode, write_mode, _scope = show_batch_audio_dialog(
            parent=self,
            selected_count=len(items),
            scope_enabled=False,
            filtered_count=len(items),
        )
        if not accepted:
            return

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.setWindowTitle("Batch Generate Source Audio")
        progress_dialog.show()

        worker = BatchGenerateAudioWorker(
            items=items,
            provider_mode=provider_mode,
            write_mode=write_mode,
            audio_chunk=25,
        )
        self.batch_audio_worker = worker
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda result: self._on_generate_audio_finished(result, progress_dialog))
        worker.error.connect(lambda err: self._on_generate_audio_error(err, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.generate_audio_btn.setEnabled(False)
        worker.finished.connect(self.on_selection_changed)
        worker.error.connect(self.on_selection_changed)
        worker.start()

    def _on_generate_audio_finished(self, result: dict, progress_dialog: BatchProgressDialogV3):
        progress_dialog.set_completed()
        progress_dialog.update_counts(
            int(result.get("succeeded", 0)),
            int(result.get("skipped", 0)),
            int(result.get("failed", 0)),
        )
        progress_dialog.accept()

        msg = (
            "Audio generation completed.\n\n"
            f"Total: {int(result.get('total', 0))}\n"
            f"Ready: {int(result.get('succeeded', 0))}\n"
            f"Skipped: {int(result.get('skipped', 0))}\n"
            f"Failed: {int(result.get('failed', 0))}"
        )
        if int(result.get("failed", 0)) > 0:
            QMessageBox.warning(self, "Audio Generation Complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Audio Generation Complete", msg)

        if self.batch_audio_worker:
            self.batch_audio_worker.deleteLater()
            self.batch_audio_worker = None
        self.perform_search()

    def _on_generate_audio_error(self, error_msg: str, progress_dialog: BatchProgressDialogV3):
        progress_dialog.reject()
        QMessageBox.warning(self, "Audio Generation Failed", error_msg)
        if self.batch_audio_worker:
            self.batch_audio_worker.deleteLater()
            self.batch_audio_worker = None
        self.on_selection_changed()

    def on_play_audio_selected(self):
        """Play ready audio from selected rows using queue mode."""
        items = self._selected_audio_items()
        if not items:
            return
        self._play_audio_items(items, play_mode="enqueue", start_immediately=True)

    def on_audio_cell_play_clicked(self, index: QModelIndex):
        """Delegate callback: play one row from Audio column."""
        source_row = self.proxy_model.map_to_source_row(index.row())
        lemma = self.lemma_model.lemmas[source_row]
        src_norm = normalize_for_tm("he", lemma.lemma_text, "lemma").norm or (lemma.norm_text or "")
        if not src_norm:
            return
        self._play_audio_items(
            [
                {
                    "src_lang": "he",
                    "src_norm": src_norm,
                    "src_text": lemma.lemma_text,
                    "kind": "lemma",
                    "source_id": int(lemma.lemma_id),
                    "project_id": getattr(self, "project_id", None),
                    "source_label": "Dictionary",
                    "translation": lemma.translation or "",
                    "pronunciation_text": getattr(lemma, "pronunciation_text", "") or "",
                }
            ],
            play_mode="enqueue",
            start_immediately=True,
        )

    def _play_audio_items(self, items: List[dict], *, play_mode: str, start_immediately: bool = False) -> None:
        """Resolve ready assets and route playback through internal player."""
        try:
            with self.db_service.get_session() as session:
                ready_items = self.audio_playback_service.resolve_ready_paths(session, items=items)

            if not ready_items:
                QMessageBox.information(
                    self,
                    "Audio Missing",
                    "No ready audio found for selected rows.\nUse 'Generate Audio...' first.",
                )
                return

            paths = [row[0] for row in ready_items]
            labels = [str((row[1] or {}).get("src_text") or row[0].stem) for row in ready_items]
            contexts = []
            for _, item in ready_items:
                payload = item or {}
                contexts.append(
                    {
                        "snapshot_hebrew": str(payload.get("src_text") or ""),
                        "snapshot_niqqud": str(
                            payload.get("pronunciation_text")
                            or payload.get("snapshot_niqqud")
                            or payload.get("niqqud")
                            or ""
                        ),
                        "snapshot_translation": str(
                            payload.get("translation")
                            or payload.get("snapshot_translation")
                            or ""
                        ),
                        "snapshot_source_label": str(
                            payload.get("source_label")
                            or payload.get("snapshot_source_label")
                            or "Dictionary"
                        ),
                        "kind": payload.get("kind"),
                        "source_id": payload.get("source_id"),
                        "project_id": payload.get("project_id"),
                    }
                )
            self.audio_playback_service.launch_audio_files(
                paths,
                labels=labels,
                play_mode=play_mode,
                contexts=contexts,
                start_immediately=start_immediately,
            )
        except Exception as e:
            logger.error("Failed to play audio in Dictionary: %s", e, exc_info=True)
            QMessageBox.warning(self, "Playback Error", f"Failed to play audio:\n{e}")

    def on_edit_pronunciation_selected(self):
        """Open pronunciation editor for the first selected row."""
        items = self._selected_pronunciation_items()
        if not items:
            return
        first = items[0]
        changed = show_edit_pronunciation_dialog(
            parent=self,
            src_lang=str(first.get("src_lang") or ""),
            src_norm=str(first.get("src_norm") or ""),
            src_text=str(first.get("src_text") or ""),
        )
        if changed:
            self.perform_search()

    def on_pronunciation_bootstrap_selected(self):
        """Open pronunciation bootstrap dialog with selected rows scope."""
        from app.ui.dialogs.pronunciation_bootstrap_dialog import show_pronunciation_bootstrap_dialog

        selected_items = self._selected_pronunciation_items()
        changed = False
        if not selected_items:
            changed = show_pronunciation_bootstrap_dialog(parent=self)
        else:
            changed = show_pronunciation_bootstrap_dialog(parent=self, selected_items=selected_items)
        if changed:
            self.perform_search()

    def on_context_menu(self, pos):
        """M7 P1: Show context menu with 'Why?' action."""
        index = self.lemma_table.indexAt(pos)  # Returns PROXY index
        if not index.isValid():
            return

        # Map proxy row to source row (CRITICAL FIX for sorted tables)
        source_row = self.proxy_model.map_to_source_row(index.row())
        lemma = self.lemma_model.lemmas[source_row]

        # Create menu
        menu = QMenu(self)

        # PATCH-UI-BATCH-T02: "Translate Selected..." action
        selected_rows = self.lemma_table.selectionModel().selectedRows()
        if selected_rows:
            translate_action = QAction(f"Translate Selected ({len(selected_rows)} rows)...", self)
            translate_action.triggered.connect(self.on_batch_translate)
            menu.addAction(translate_action)

            generate_audio_action = QAction(f"Generate Audio Selected ({len(selected_rows)} rows)...", self)
            generate_audio_action.triggered.connect(self.on_generate_audio_selected)
            menu.addAction(generate_audio_action)

            play_audio_action = QAction(f"Play Audio Selected ({len(selected_rows)} rows)", self)
            play_audio_action.triggered.connect(self.on_play_audio_selected)
            menu.addAction(play_audio_action)

            add_action = QAction(f"Add Selected to User Dictionary ({len(selected_rows)} rows)...", self)
            add_action.triggered.connect(self.on_add_selected_to_user_dictionary)
            menu.addAction(add_action)
            add_playlist_action = QAction(f"Add Selected to Playlist ({len(selected_rows)} rows)...", self)
            add_playlist_action.triggered.connect(self.on_add_selected_to_playlist)
            menu.addAction(add_playlist_action)

            edit_pron_action = QAction("Mispronounced -> Add Pronunciation...", self)
            edit_pron_action.triggered.connect(self.on_edit_pronunciation_selected)
            menu.addAction(edit_pron_action)
            bootstrap_pron_action = QAction(f"Pronunciation Bootstrap Selected ({len(selected_rows)} rows)...", self)
            bootstrap_pron_action.triggered.connect(self.on_pronunciation_bootstrap_selected)
            menu.addAction(bootstrap_pron_action)
            menu.addSeparator()

        # "Why?" action - show explainability
        why_action = QAction("Why this translation?", self)
        why_action.triggered.connect(lambda: self.show_why_dialog(source_row))
        menu.addAction(why_action)

        # Task 11: Manual noise override actions
        menu.addSeparator()

        # Check if multiple rows selected
        if len(selected_rows) > 1:
            # Bulk operations
            mark_valid_bulk_action = QAction(f"[OK] Mark Selected as Valid ({len(selected_rows)} rows)", self)
            mark_valid_bulk_action.triggered.connect(lambda: self.set_lemmas_noise_status_bulk(False))
            menu.addAction(mark_valid_bulk_action)

            mark_noise_bulk_action = QAction(f"[X] Mark Selected as Noise ({len(selected_rows)} rows)", self)
            mark_noise_bulk_action.triggered.connect(lambda: self.set_lemmas_noise_status_bulk(True))
            menu.addAction(mark_noise_bulk_action)
        else:
            # Single row operation
            current_is_noise = lemma.is_noise == 1 if lemma.is_noise is not None else False

            if current_is_noise:
                mark_valid_action = QAction("[OK] Mark as Valid (remove from noise)", self)
                mark_valid_action.triggered.connect(lambda: self.set_lemma_noise_status(source_row, False))
                menu.addAction(mark_valid_action)
            else:
                mark_noise_action = QAction("[X] Mark as Noise", self)
                mark_noise_action.triggered.connect(lambda: self.set_lemma_noise_status(source_row, True))
                menu.addAction(mark_noise_action)

        # Show menu
        menu.exec(self.lemma_table.viewport().mapToGlobal(pos))

    def on_add_selected_to_user_dictionary(self):
        """Add selected lemma rows to a user dictionary."""
        selected_rows = self.lemma_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        payloads = []
        for proxy_index in selected_rows:
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            lemma = self.lemma_model.lemmas[source_row]
            src_norm = normalize_for_tm("he", lemma.lemma_text, "lemma").norm
            payloads.append(
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": lemma.lemma_text,
                    "src_norm": src_norm,
                    "is_noise": 1 if lemma.is_noise == 1 else 0,
                    "noise_reason": lemma.noise_reason,
                    "origin_project_id": self.project_id,
                    "origin_entity_type": "lemma",
                    "origin_entity_id": lemma.lemma_id,
                    "origin_source_ref": "dictionary_view",
                }
            )

        accepted, dictionary_id, options = show_add_to_user_dictionary_dialog(
            parent=self,
            selected_count=len(payloads),
        )
        if not accepted or not dictionary_id:
            return

        tags = options.get("tags", [])
        preserve_origin = bool(options.get("preserve_origin_refs", True))
        prepared = []
        for item in payloads:
            row = dict(item)
            if tags:
                row["tags_json"] = tags
            if not preserve_origin:
                row["origin_project_id"] = None
                row["origin_entity_type"] = None
                row["origin_entity_id"] = None
                row["origin_tm_entry_id"] = None
                row["origin_doc_id"] = None
                row["origin_source_ref"] = None
            prepared.append(row)

        from PyQt6.QtWidgets import QProgressDialog

        progress = QProgressDialog("Adding items to dictionary...", "Cancel", 0, len(prepared), self)
        progress.setWindowTitle("User Dictionaries")
        progress.setModal(True)
        progress.setMinimumDuration(0)
        progress.show()

        worker = UserDictionaryBulkAddWorker(
            dictionary_id=dictionary_id,
            items=prepared,
            include_noise=bool(options.get("include_noise", False)),
            skip_duplicates=bool(options.get("skip_duplicates", True)),
            chunk_size=500,
        )
        self._user_dict_add_worker = worker
        worker.progress.connect(lambda done, total: progress.setValue(done))
        worker.finished.connect(lambda result: self._on_user_dict_add_finished(result, progress))
        worker.error.connect(lambda err: self._on_user_dict_add_error(err, progress))
        progress.canceled.connect(worker.cancel)
        worker.start()

    def on_add_selected_to_playlist(self) -> None:
        items = self._selected_audio_items()
        if not items:
            return
        add_selected_items_to_playlist_dialog(
            parent=self,
            items=items,
            db_manager=self.db_service,
        )

    def _on_user_dict_add_finished(self, result, progress_dialog):
        progress_dialog.close()
        from app.ui.dialogs import show_info

        show_info(
            self,
            "Add Complete",
            f"Added: {result.get('added', 0)}\n"
            f"Skipped: {result.get('skipped', 0)}\n"
            f"Failed: {result.get('failed', 0)}",
        )
        self._user_dict_add_worker = None

    def _on_user_dict_add_error(self, error_msg: str, progress_dialog):
        progress_dialog.close()
        from app.ui.dialogs import show_error

        show_error(self, "Add Failed", error_msg)
        self._user_dict_add_worker = None

    def show_why_dialog(self, row: int):
        """M7 P1: Show WhyTranslationDialog for a lemma."""
        lemma = self.lemma_model.lemmas[row]

        # Get translation result from model
        translation_result = self.lemma_model.translation_results.get(row)

        if not translation_result:
            # If no result yet, create a minimal one
            from app.services.translation_service import TranslationResult
            translation_result = TranslationResult(
                translation=lemma.translation or "(no translation)",
                source="unknown",
                status=lemma.status or "unknown",
            )

        # Show dialog
        dialog = WhyTranslationDialog(translation_result, lemma.lemma_text, self)
        dialog.exec()

    def set_lemma_noise_status(self, row: int, is_noise: bool):
        """Task 11: Manually override noise status for a lemma."""
        lemma = self.lemma_model.lemmas[row]

        try:
            with self.db_service.get_session() as session:
                from sqlalchemy import update
                from app.infra.sa_models import Lemma

                # Update is_noise field
                stmt = update(Lemma).where(
                    Lemma.lemma_id == lemma.lemma_id
                ).values(
                    is_noise=1 if is_noise else 0
                )
                session.execute(stmt)
                self.user_dict_service.sync_noise_from_lemmas(session, [lemma.lemma_id])
                session.commit()

                # Update local model
                lemma.is_noise = 1 if is_noise else 0

                status = "noise" if is_noise else "valid"
                logger.info(f"Marked lemma '{lemma.lemma_text}' as {status}")

                # Reload to apply filter if needed
                if self.hide_noise_checkbox.isChecked():
                    self.perform_search()

        except Exception as e:
            logger.exception(f"Failed to update noise status for lemma {lemma.lemma_id}")
            from app.ui.dialogs import show_error
            show_error(self, "Error", f"Failed to update noise status: {e}")

    def set_lemmas_noise_status_bulk(self, is_noise: bool):
        """Task 11 + P0: Bulk operation - update noise status for multiple selected lemmas.

        P0 Safety features:
        - Confirmation dialog for > 100 rows
        - Progress dialog + QThread for > 1000 rows
        - Cancel support for long operations
        """
        selected_rows = self.lemma_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # Map proxy rows to source rows and get lemma IDs
        lemma_ids = []
        source_rows = []
        for proxy_index in selected_rows:
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            lemma = self.lemma_model.lemmas[source_row]
            lemma_ids.append(lemma.lemma_id)
            source_rows.append(source_row)

        count = len(lemma_ids)
        status_text = "noise" if is_noise else "valid"

        # P0: Confirmation dialog for > 100 rows
        if count > 100:
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                'Confirm Bulk Action',
                f'You are about to mark {count:,} lemmas as {status_text}.\n\n'
                f'This operation cannot be undone easily.\n\n'
                f'Continue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No  # Default to No for safety
            )
            if reply == QMessageBox.StandardButton.No:
                logger.info(f"User cancelled bulk noise update for {count} lemmas")
                return

        # P0: Use background worker for > 1000 rows (prevents UI freeze)
        if count > 1000:
            self._run_bulk_update_worker(lemma_ids, source_rows, is_noise)
        else:
            # Fast path: direct update for <= 1000 rows
            self._run_bulk_update_direct(lemma_ids, source_rows, is_noise)

    def _run_bulk_update_direct(self, lemma_ids: list, source_rows: list, is_noise: bool):
        """Direct bulk update for small datasets (<= 1000 rows)."""
        try:
            with self.db_service.get_session() as session:
                from sqlalchemy import update
                from app.infra.sa_models import Lemma

                # Bulk update using WHERE IN
                stmt = update(Lemma).where(
                    Lemma.lemma_id.in_(lemma_ids)
                ).values(
                    is_noise=1 if is_noise else 0
                )
                session.execute(stmt)
                self.user_dict_service.sync_noise_from_lemmas(session, lemma_ids)
                session.commit()

                # Update local model for all affected rows
                for source_row in source_rows:
                    self.lemma_model.lemmas[source_row].is_noise = 1 if is_noise else 0

                status = "noise" if is_noise else "valid"
                logger.info(f"Marked {len(lemma_ids)} lemmas as {status}")

                # Show success message
                from app.ui.dialogs import show_info
                show_info(self, "Success", f"Marked {len(lemma_ids)} lemmas as {status}")

                # Reload to apply filter if needed
                if self.hide_noise_checkbox.isChecked():
                    self.perform_search()

        except Exception as e:
            logger.exception(f"Failed to bulk update noise status for {len(lemma_ids)} lemmas")
            from app.ui.dialogs import show_error
            show_error(self, "Error", f"Failed to bulk update noise status: {e}")

    def _run_bulk_update_worker(self, lemma_ids: list, source_rows: list, is_noise: bool):
        """Background worker for large datasets (> 1000 rows) with progress dialog."""
        from PyQt6.QtWidgets import QProgressDialog
        from app.ui.workers import BulkNoiseUpdateWorker

        # Create progress dialog
        status_text = "noise" if is_noise else "valid"
        self.bulk_progress_dialog = QProgressDialog(
            f"Marking {len(lemma_ids):,} lemmas as {status_text}...",
            "Cancel",
            0,
            len(lemma_ids),
            self
        )
        self.bulk_progress_dialog.setWindowTitle("Bulk Update")
        self.bulk_progress_dialog.setModal(True)
        self.bulk_progress_dialog.setMinimumDuration(0)
        self.bulk_progress_dialog.show()

        # Store source_rows for later model update
        self._pending_source_rows = source_rows
        self._pending_is_noise = is_noise
        self._pending_lemma_ids = list(lemma_ids)

        # Create and start worker
        self.bulk_worker = BulkNoiseUpdateWorker(
            model_class="Lemma",
            item_ids=lemma_ids,
            is_noise=is_noise
        )

        # Connect signals
        self.bulk_worker.progress.connect(self._on_bulk_progress)
        self.bulk_worker.update_complete.connect(self._on_bulk_complete)
        self.bulk_worker.error.connect(self._on_bulk_error)
        self.bulk_progress_dialog.canceled.connect(self._on_bulk_cancel)

        # Start worker
        self.bulk_worker.start()

    def _on_bulk_progress(self, current: int, total: int):
        """Update bulk progress dialog."""
        if hasattr(self, 'bulk_progress_dialog') and self.bulk_progress_dialog:
            self.bulk_progress_dialog.setValue(current)
            self.bulk_progress_dialog.setLabelText(
                f"Updated {current:,} of {total:,} lemmas..."
            )

    def _on_bulk_complete(self, count: int):
        """Handle bulk update completion."""
        # Close progress dialog
        if hasattr(self, 'bulk_progress_dialog') and self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        # Update local model for all affected rows
        for source_row in self._pending_source_rows:
            self.lemma_model.lemmas[source_row].is_noise = 1 if self._pending_is_noise else 0

        # Sync source noise -> User Dictionaries after worker commit.
        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.sync_noise_from_lemmas(
                    session,
                    getattr(self, "_pending_lemma_ids", []),
                )
                session.commit()
        except Exception as e:
            logger.warning("Failed to sync lemma noise to User Dictionaries after bulk update: %s", e)

        status = "noise" if self._pending_is_noise else "valid"
        logger.info(f"Bulk update completed: {count} lemmas marked as {status}")

        # Show success message
        from app.ui.dialogs import show_info
        show_info(self, "Success", f"Marked {count:,} lemmas as {status}")

        # Reload to apply filter if needed
        if self.hide_noise_checkbox.isChecked():
            self.perform_search()

    def _on_bulk_error(self, error_msg: str):
        """Handle bulk update error."""
        # Close progress dialog
        if hasattr(self, 'bulk_progress_dialog') and self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        logger.error(f"Bulk noise update failed: {error_msg}")

        from app.ui.dialogs import show_error
        show_error(self, "Error", f"Bulk update failed:\n{error_msg}")

    def _on_bulk_cancel(self):
        """Handle bulk update cancellation."""
        if hasattr(self, 'bulk_worker') and self.bulk_worker and self.bulk_worker.isRunning():
            self.bulk_worker.cancel()
            logger.info("User cancelled bulk noise update")

    def on_selection_changed(self):
        """PATCH-UI-BATCH-T02: Handle selection change - enable/disable batch translate button."""
        selected_rows = self.lemma_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        self.batch_translate_btn.setEnabled(has_selection)
        self.generate_audio_btn.setEnabled(has_selection)
        self.play_audio_btn.setEnabled(has_selection)
        self.pronunciation_bootstrap_btn.setEnabled(has_selection)

    def on_batch_translate(self):
        """Task 15: Handle batch translate action with scope support."""
        from PyQt6.QtWidgets import QMessageBox
        from app.ui.dialogs import show_batch_translate_dialog
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import BatchTranslateWorker, TranslateAllFilteredWorker
        from app.services.batch_mt_translate_service import (
            BatchTranslateItem,
            BatchTranslateOptions,
        )
        from app.services.db_service import DBService
        from app.services.dictionary_service import DictionaryService

        # Get selected rows
        selected_indexes = self.lemma_table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        # Task 15: Compute filtered count for "All pages" scope
        filtered_count = 0
        dict_service = DictionaryService()
        try:
            db_service = DBService.get_instance()
            with db_service.get_session() as session:
                filtered_count = dict_service.count_lemma_ids_for_translation(
                    session, self.project_id, self.build_filters(), "FILL_EMPTY"
                )
        except Exception as e:
            logger.warning(f"Failed to compute filtered_count: {e}")

        # Show confirm dialog with scope support
        accepted, provider_mode, write_mode, scope = show_batch_translate_dialog(
            parent=self,
            selected_count=len(selected_indexes),
            scope_enabled=True,
            filtered_count=filtered_count,
        )

        if not accepted:
            return

        # Task 15: Handle scope selection
        if scope == "all_filtered":
            # Premium safety: confirm overwrite on large datasets
            if write_mode == "OVERWRITE" and filtered_count > 100:
                reply = QMessageBox.question(
                    self,
                    "Confirm Overwrite",
                    f"This will overwrite {filtered_count} existing translations.\n\n"
                    f"This action cannot be undone.\n\n"
                    f"Do you want to continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Match User Dictionaries behavior: recalculate total with chosen write_mode.
            total_for_scope = filtered_count
            try:
                with db_service.get_session() as session:
                    total_for_scope = dict_service.count_lemma_ids_for_translation(
                        session, self.project_id, self.build_filters(), write_mode
                    )
            except Exception as e:
                logger.warning(f"Failed to recompute total_for_scope: {e}")

            # Create TranslateAllFilteredWorker for chunked translation
            logger.info(f"Starting TranslateAllFilteredWorker for {total_for_scope} lemmas")
            progress_dialog = BatchProgressDialogV3(parent=self, total=total_for_scope)
            progress_dialog.show()

            worker = TranslateAllFilteredWorker(
                entity_type="lemma",
                project_id=self.project_id,
                filters=self.build_filters(),
                provider_mode=provider_mode,
                write_mode=write_mode,
                id_fetch_chunk=200,      # Fetch 200 IDs from DB per iteration
                translation_chunk=1,      # Translate 1 item per commit (per-row semantics)
                src_lang="he",
                tgt_lang="ru",
            )

            # Connect signals
            worker.progress.connect(progress_dialog.update_progress)
            worker.stats_updated.connect(progress_dialog.update_counts)  # Direct connection
            worker.row_translated.connect(progress_dialog.add_recent_item)  # Direct connection
            worker.stage_updated.connect(progress_dialog.set_stage)  # PATCH-16-02: Stage updates
            worker.finished.connect(lambda result: self.on_batch_translate_finished(result, progress_dialog))
            worker.error.connect(lambda error: self.on_batch_translate_error(error, progress_dialog))
            progress_dialog.cancel_requested.connect(worker.cancel)
            progress_dialog.pause_requested.connect(worker.pause)
            progress_dialog.resume_requested.connect(worker.resume)

            # Disable translate button while worker runs
            self.batch_translate_btn.setEnabled(False)
            worker.finished.connect(lambda: self.batch_translate_btn.setEnabled(True))
            worker.error.connect(lambda: self.batch_translate_btn.setEnabled(True))

            # Start worker
            worker.start()
            self._batch_worker = worker

        else:  # scope == "current_page"
            # Map proxy indices to source rows
            source_rows = [
                self.proxy_model.map_to_source_row(index.row())
                for index in selected_indexes
            ]

            # Build items list
            items = []
            for row in source_rows:
                lemma = self.lemma_model.lemmas[row]
                item = BatchTranslateItem(
                    entity_type="lemma",
                    entity_id=lemma.lemma_text,
                    source_text=lemma.lemma_text,
                    src_lang="he",
                    tgt_lang="ru",
                    current_translation=lemma.translation,
                    project_id=self.project_id,
                )
                items.append(item)

            # Create options
            options = BatchTranslateOptions(
                provider_mode=provider_mode,
                write_mode=write_mode,
                chunk_size=1,
                stop_on_error=False,
            )

            # Show premium V3 progress dialog (parity with all_filtered/User Dictionaries)
            progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
            progress_dialog.show()

            # Create worker
            worker = BatchTranslateWorker(
                items=items,
                options=options,
                tab_type="dictionary",
            )

            # Connect signals
            worker.progress.connect(progress_dialog.update_progress)
            worker.stats_updated.connect(progress_dialog.update_counts)
            worker.row_translated.connect(progress_dialog.add_recent_item)
            worker.stage_updated.connect(progress_dialog.set_stage)
            worker.finished.connect(lambda result: self.on_batch_translate_finished(result, progress_dialog))
            worker.error.connect(lambda error: self.on_batch_translate_error(error, progress_dialog))
            progress_dialog.cancel_requested.connect(worker.cancel)
            progress_dialog.pause_requested.connect(worker.pause)
            progress_dialog.resume_requested.connect(worker.resume)

            # Disable translate button while worker runs
            self.batch_translate_btn.setEnabled(False)
            worker.finished.connect(self.on_selection_changed)
            worker.error.connect(self.on_selection_changed)

            # Start worker
            worker.start()
            self._batch_worker = worker

    def on_batch_translate_finished(self, result, progress_dialog):
        """PATCH-UI-BATCH-T02: Handle batch translate completion."""
        from PyQt6.QtWidgets import QMessageBox

        # Update progress dialog
        progress_dialog.set_completed()
        progress_dialog.update_counts(result.succeeded, result.skipped, result.failed)

        # Close progress dialog
        progress_dialog.accept()

        # Show result message
        msg = f"Translation completed!\n\n"
        msg += f"Total: {result.total}\n"
        msg += f"Succeeded: {result.succeeded}\n"
        msg += f"Skipped: {result.skipped}\n"
        msg += f"Failed: {result.failed}"

        if result.failed > 0:
            QMessageBox.warning(self, "Translation Complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Translation Complete", msg)

        # Refresh lemmas to show updated translations
        self.perform_search()

        # Re-evaluate button state and clean up worker
        self.on_selection_changed()
        if hasattr(self, '_batch_worker'):
            self._batch_worker.deleteLater()
            del self._batch_worker

    def on_batch_translate_error(self, error_msg, progress_dialog):
        """PATCH-UI-BATCH-T02: Handle batch translate error."""
        from PyQt6.QtWidgets import QMessageBox

        # Close progress dialog
        progress_dialog.reject()

        # Show error
        QMessageBox.critical(self, "Translation Error", error_msg)

        # Re-evaluate button state and clean up worker
        self.on_selection_changed()
        if hasattr(self, '_batch_worker'):
            self._batch_worker.deleteLater()
            del self._batch_worker

    def eventFilter(self, obj, event):
        """Handle keyboard shortcuts: Enter (edit), Ctrl+Left/Right (pagination)."""
        if obj == self.lemma_table and event.type() == event.Type.KeyPress:
            from PyQt6.QtGui import QKeyEvent
            if isinstance(event, QKeyEvent):
                key = event.key()
                modifiers = event.modifiers()

                # Ctrl+Left: Previous page
                if key == Qt.Key.Key_Left and modifiers == Qt.KeyboardModifier.ControlModifier:
                    self.on_prev_page()
                    return True

                # Ctrl+Right: Next page
                if key == Qt.Key.Key_Right and modifiers == Qt.KeyboardModifier.ControlModifier:
                    self.on_next_page()
                    return True

                # Enter: Start editing Translation column
                if key == Qt.Key.Key_Return:
                    current_index = self.lemma_table.currentIndex()
                    if current_index.isValid():
                        # Start editing Translation column (column 5 in source model)
                        # Map proxy index to source index
                        source_index = self.proxy_model.mapToSource(current_index)
                        # Create translation column index in source model
                        translation_source_index = self.lemma_model.index(source_index.row(), 5)
                        # Map back to proxy
                        translation_proxy_index = self.proxy_model.mapFromSource(translation_source_index)
                        self.lemma_table.setCurrentIndex(translation_proxy_index)
                        self.lemma_table.edit(translation_proxy_index)
                        return True  # Event handled

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        """M7 P1: Clean up translation worker on close."""
        if self.search_worker and self.search_worker.isRunning():
            logger.info("Stopping search worker on close")
            self.search_worker.cancel()
            self.search_worker.wait(1000)
            if self.search_worker.isRunning():
                self.search_worker.terminate()

        if self.translation_worker and self.translation_worker.isRunning():
            logger.info("Stopping translation worker on close")
            self.translation_worker.cancel()
            self.translation_worker.wait(1000)
            if self.translation_worker.isRunning():
                self.translation_worker.terminate()

        if self.batch_audio_worker and self.batch_audio_worker.isRunning():
            logger.info("Stopping batch audio worker on close")
            self.batch_audio_worker.cancel()
            self.batch_audio_worker.wait(1000)
            if self.batch_audio_worker.isRunning():
                self.batch_audio_worker.terminate()

        # Save header state (column order, widths, sort)
        self.table_layout_controller.save_now()

        super().closeEvent(event)

    def refresh(self):
        """Refresh lemma data from database."""
        logger.info("Refreshing dictionary view")
        self.perform_search()

