"""Terms view - MWE extraction and clustering (M5+)."""

import json
import logging

from PyQt6.QtCore import QModelIndex, Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.settings import SettingsService
from app.services.audio_playback_service import AudioPlaybackService
from app.services.batch_mt_translate_service import BatchTranslateItem, BatchTranslateOptions
from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService
from app.services.tm_global_service import TMGlobalService
from app.services.translation_service import TranslationService
from app.services.user_dictionary_service import UserDictionaryService
from app.ui.audio_playlist_actions import add_selected_items_to_playlist_dialog
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate
from app.ui.dialogs import WhyTranslationDialog, show_batch_translate_dialog, show_error, show_info
from app.ui.dialogs.add_to_user_dictionary_dialog import show_add_to_user_dictionary_dialog
from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog
from app.ui.dialogs.term_extraction_progress_dialog import TermExtractionProgressDialog
from app.ui.models_qt import TermClusterTableModel
from app.ui.multi_sort_proxy import MultiSortProxyModel
from app.ui.table_layout_controller import TableLayoutController
from app.ui.workers import (
    BatchGenerateAudioWorker,
    BatchTranslateWorker,
    CrossViewOverlayWorker,
    TermsSearchWorker,
    TranslationResolveWorker,
    UserDictionaryBulkAddWorker,
)

logger = logging.getLogger(__name__)


class TermsView(QWidget):
    """Terms view showing extracted MWEs and clusters (M5)."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.term_service = TermExtractionService()
        self.user_dict_service = UserDictionaryService()
        self.db_service = DBService.get_instance()
        self.translation_service = TranslationService()
        self.audio_playback_service = AudioPlaybackService()
        self.settings = SettingsService.get_instance()
        self.extract_worker = None
        self.extract_progress_dialog: TermExtractionProgressDialog | None = None
        self.translation_worker: TranslationResolveWorker | None = None
        self.batch_translate_worker: BatchTranslateWorker | None = None
        self.batch_audio_worker: BatchGenerateAudioWorker | None = None
        self.overlay_worker: CrossViewOverlayWorker | None = None

        # Pagination state
        self.current_page = 1
        self.page_size = self.settings.get_int("terms_view/page_size", 100)
        self.total_count = 0
        self.search_worker = None  # Track worker for cancellation
        self._search_request_seq = 0
        self._active_search_seq = 0
        self._search_retry_pending = False
        self._translation_request_seq = 0
        self._active_translation_seq = 0
        self._pending_translation_clusters = None
        self._overlay_request_seq = 0
        self._active_overlay_seq = 0
        self._pending_overlay_clusters = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.perform_search)

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
        """Initialize UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Terms (MWE + Clustering)")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.batch_translate_btn = QPushButton("Translate Selected...")
        self.batch_translate_btn.clicked.connect(self.on_batch_translate)
        self.batch_translate_btn.setEnabled(False)
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

        self.extract_btn = QPushButton("Extract Terms")
        self.extract_btn.clicked.connect(self.on_extract)
        header_layout.addWidget(self.extract_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.perform_search)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        # Extraction controls (M5.3)
        extract_controls_layout = QHBoxLayout()

        self.include_np_checkbox = QCheckBox("Include NP chunks")
        saved_include_np = self.settings.get_bool("terms_view/include_np", True)
        self.include_np_checkbox.setChecked(saved_include_np)
        self.include_np_checkbox.stateChanged.connect(self.on_include_np_changed)
        extract_controls_layout.addWidget(self.include_np_checkbox)

        # N-gram sizes: configurable bigrams/trigrams (persisted via QSettings)
        extract_controls_layout.addWidget(QLabel("N-grams:"))
        self.ngram_bigrams_checkbox = QCheckBox("Bigrams")
        self.ngram_bigrams_checkbox.setToolTip(
            "Extract 2-word n-grams (bigrams).\n"
            "Each checked size is extracted independently.\n"
            "Bigrams only → only 2-word sequences.\n"
            "Both checked → 2-word and 3-word sequences."
        )
        self.ngram_trigrams_checkbox = QCheckBox("Trigrams")
        self.ngram_trigrams_checkbox.setToolTip(
            "Extract 3-word n-grams (trigrams).\n"
            "Each checked size is extracted independently.\n"
            "Trigrams only → only 3-word sequences.\n"
            "Both checked → 2-word and 3-word sequences."
        )
        saved_ngram_ns_json = self.settings.get_string(
            "terms_view/ngram_ns_json", "[2,3]"
        )
        try:
            _saved_ns = set(json.loads(saved_ngram_ns_json))
        except (ValueError, TypeError):
            _saved_ns = {2, 3}
        self.ngram_bigrams_checkbox.setChecked(2 in _saved_ns)
        self.ngram_trigrams_checkbox.setChecked(3 in _saved_ns)
        self.ngram_bigrams_checkbox.stateChanged.connect(self.on_ngram_ns_changed)
        self.ngram_trigrams_checkbox.stateChanged.connect(self.on_ngram_ns_changed)
        extract_controls_layout.addWidget(self.ngram_bigrams_checkbox)
        extract_controls_layout.addWidget(self.ngram_trigrams_checkbox)

        extract_controls_layout.addWidget(QLabel("Max NP length:"))
        self.np_max_len_spin = QSpinBox()
        self.np_max_len_spin.setRange(2, 5)
        # Load saved value or use maximum (5) as default
        saved_np_max_len = self.settings.get_int("terms_view/np_max_len", 5)
        self.np_max_len_spin.setValue(saved_np_max_len)
        self.np_max_len_spin.valueChanged.connect(self.on_np_max_len_changed)
        extract_controls_layout.addWidget(self.np_max_len_spin)

        extract_controls_layout.addWidget(QLabel("Min freq:"))
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(1, 100)
        # Load saved value or use default (2)
        saved_min_freq = self.settings.get_int("terms_view/min_freq", 2)
        self.min_freq_spin.setValue(saved_min_freq)
        self.min_freq_spin.valueChanged.connect(self.on_min_freq_changed)
        extract_controls_layout.addWidget(self.min_freq_spin)

        # PATCH-10: Min doc freq filter (separate from min_freq)
        extract_controls_layout.addWidget(QLabel("Min doc freq:"))
        self.min_doc_freq_spin = QSpinBox()
        self.min_doc_freq_spin.setRange(1, 50)
        self.min_doc_freq_spin.setToolTip(
            "Minimum number of documents a term must appear in.\n"
            "Filters out terms that appear many times in a single document.\n"
            "Default 1 = no filter."
        )
        saved_min_doc_freq = self.settings.get_int("terms_view/min_doc_freq", 1)
        self.min_doc_freq_spin.setValue(saved_min_doc_freq)
        self.min_doc_freq_spin.valueChanged.connect(self.on_min_doc_freq_changed)
        extract_controls_layout.addWidget(self.min_doc_freq_spin)

        extract_controls_layout.addStretch()
        layout.addLayout(extract_controls_layout)

        # Migration 011: Last extraction parameters info
        self.last_extract_label = QLabel("")
        self.last_extract_label.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        layout.addWidget(self.last_extract_label)

        self.last_extract_source_mix_label = QLabel("")
        self.last_extract_source_mix_label.setStyleSheet("color: #475569; padding: 0 5px 5px 5px;")
        self.last_extract_source_mix_label.setWordWrap(True)
        layout.addWidget(self.last_extract_source_mix_label)

        # Filters
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["All", "N-grams", "NP"])
        self.source_combo.currentTextChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.source_combo)

        filter_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["freq", "strong", "balanced", "termhood", "keyness", "weirdness"])
        self.preset_combo.currentTextChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.preset_combo)

        # M5.4: Reference project for termhood
        filter_layout.addWidget(QLabel("Ref Project:"))
        self.reference_combo = QComboBox()
        self.reference_combo.addItem("None", None)
        self.reference_combo.currentIndexChanged.connect(self.on_reference_changed)
        filter_layout.addWidget(self.reference_combo)

        filter_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter terms...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        filter_layout.addWidget(self.search_edit)

        # Hide noise filter (Task 11: Entity Classification)
        self.hide_noise_checkbox = QCheckBox("Hide noise")
        self.hide_noise_checkbox.setChecked(True)  # Default: hide noise
        self.hide_noise_checkbox.setToolTip("Hide numeric, symbolic, and other noisy terms")
        self.hide_noise_checkbox.stateChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.hide_noise_checkbox)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # PATCH-08: Staleness warning — shown when reference corpus changed since last extraction.
        self.staleness_warning_btn = QPushButton(
            "⚠ Keyness/Weirdness may be outdated — Recalculate"
        )
        self.staleness_warning_btn.setStyleSheet(
            "QPushButton {"
            "  background: #fef3c7; color: #92400e; border: 1px solid #f59e0b;"
            "  border-radius: 4px; padding: 4px 10px; font-weight: bold;"
            "}"
            "QPushButton:hover { background: #fde68a; }"
        )
        self.staleness_warning_btn.setToolTip(
            "The reference corpus was changed since the last extraction.\n"
            "Click to recalculate Keyness and Weirdness without re-extracting.\n"
            "Or re-run full extraction to update all metrics."
        )
        self.staleness_warning_btn.clicked.connect(self.on_recalculate_keyness)
        self.staleness_warning_btn.setVisible(False)
        layout.addWidget(self.staleness_warning_btn)

        # Terms table with proxy model for sorting (M7 P1: converted to QTableView + TermClusterTableModel)
        self.terms_model = TermClusterTableModel()
        self.proxy_model = MultiSortProxyModel()
        self.proxy_model.setSourceModel(self.terms_model)

        self.terms_table = QTableView()
        self.terms_table.setModel(self.proxy_model)  # Use proxy model
        self.terms_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.terms_table.setSelectionMode(
            QTableView.SelectionMode.ExtendedSelection
        )  # Bulk selection
        # M7 P1: Enable editing for Translation column
        self.terms_table.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.EditKeyPressed
        )
        self.terms_table.setSortingEnabled(True)

        # Install event filter for Enter key editing
        self.terms_table.installEventFilter(self)

        # M7 P1: Context menu for "Why?" action
        self.terms_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.terms_table.customContextMenuRequested.connect(self.on_context_menu)

        # Connect selection change to enable/disable batch translate button
        self.terms_table.selectionModel().selectionChanged.connect(self.on_selection_changed)

        self.table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="terms_view",
            table=self.terms_table,
            default_widths={
                0: 46,  # UD
                1: 260,  # Term
                2: 180,  # Lemma
                3: 85,  # Freq
                4: 90,  # DocFreq
                5: 90,  # Members
                6: 90,  # PMI
                7: 90,  # LLR
                8: 90,  # Dice
                9: 105,  # Weirdness
                10: 105,  # Keyness
                11: 105,  # Termhood
                12: 260,  # Translation
                13: 120,  # Source
                14: 110,  # Status
                15: 90,  # Noise
                16: 110,  # Last Review
                17: 180,  # Niqqud
                18: 90,  # Audio
            },
        )
        self.table_layout_controller.install()
        self.audio_play_delegate = AudioPlayDelegate(
            self.terms_table,
            on_play_clicked=self.on_audio_cell_play_clicked,
        )
        self.terms_table.setItemDelegateForColumn(18, self.audio_play_delegate)

        # M7 P1: Connect dataChanged to save handler
        self.terms_model.dataChanged.connect(self.on_translation_edited)

        layout.addWidget(self.terms_table)

        # Pagination bar
        pagination_layout = QHBoxLayout()

        # First/Prev buttons
        self.first_btn = QPushButton("В«")
        self.first_btn.setToolTip("First page")
        self.first_btn.setMaximumWidth(40)
        self.first_btn.clicked.connect(self.on_first_page)
        pagination_layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("вЂ№")
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
        self.next_btn = QPushButton("вЂє")
        self.next_btn.setToolTip("Next page (Ctrl+Right)")
        self.next_btn.setMaximumWidth(40)
        self.next_btn.clicked.connect(self.on_next_page)
        pagination_layout.addWidget(self.next_btn)

        self.last_btn = QPushButton("В»")
        self.last_btn.setToolTip("Last page")
        self.last_btn.setMaximumWidth(40)
        self.last_btn.clicked.connect(self.on_last_page)
        pagination_layout.addWidget(self.last_btn)

        pagination_layout.addSpacing(20)

        # Range label
        self.range_label = QLabel("Showing 0вЂ“0 of 0")
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

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status
        self.status_label = QLabel("No terms extracted")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

        # M5.4: Load reference projects dropdown
        self.load_reference_projects()

    def load_reference_projects(self):
        """Load available projects for reference selection (M5.4)."""
        try:
            with self.db_service.get_session() as session:
                # Get list of all projects
                projects = self.term_service.list_projects(session)

                # Get current reference setting
                current_ref = self.term_service.get_reference_project(session, self.project_id)

                # If no reference set, auto-select default reference corpus (is_general_corpus=1)
                default_ref_id = None
                if current_ref is None:
                    default_ref_id = self.term_service._get_default_reference_corpus_id(session)
                    if default_ref_id and default_ref_id != self.project_id:
                        # Auto-assign default reference corpus for this project
                        self.term_service.set_reference_project(
                            session, self.project_id, default_ref_id
                        )
                        current_ref = default_ref_id
                        logger.info(
                            f"Auto-assigned default reference corpus (ID: {default_ref_id}) to project {self.project_id}"
                        )

                # Clear and populate combo
                self.reference_combo.clear()
                self.reference_combo.addItem("None", None)

                current_index = 0
                for idx, (proj_id, proj_name) in enumerate(projects, start=1):
                    # Don't allow selecting self as reference
                    if proj_id == self.project_id:
                        continue

                    self.reference_combo.addItem(proj_name, proj_id)

                    if current_ref and proj_id == current_ref:
                        current_index = self.reference_combo.count() - 1

                # Set current selection
                self.reference_combo.setCurrentIndex(current_index)

                # PATCH-08: Staleness check — show warning if reference changed since last run.
                last_run_ref = self.term_service.get_last_run_reference_project_id(
                    session, self.project_id
                )
                self._update_staleness_warning(current_ref, last_run_ref)

        except Exception:
            logger.exception("Failed to load reference projects")

    def _update_staleness_warning(
        self, current_ref_id: int | None, last_run_ref_id: int | None
    ) -> None:
        """Show/hide staleness warning based on reference corpus mismatch.

        Hidden when: no completed run exists, run has NULL reference_project_id (pre-044 rows),
        or current reference matches the run's snapshot.
        Shown when: both are non-NULL and they differ.
        """
        stale = (
            current_ref_id is not None
            and last_run_ref_id is not None
            and current_ref_id != last_run_ref_id
        )
        self.staleness_warning_btn.setVisible(stale)

    def on_reference_changed(self, index: int):
        """Handle reference project selection change (M5.4)."""
        try:
            reference_id = self.reference_combo.currentData()

            with self.db_service.get_session() as session:
                self.term_service.set_reference_project(session, self.project_id, reference_id)
                # Re-check staleness after reference change.
                last_run_ref = self.term_service.get_last_run_reference_project_id(
                    session, self.project_id
                )
                self._update_staleness_warning(reference_id, last_run_ref)

            # Refresh terms table
            self.current_page = 1
            self.perform_search()

        except Exception as e:
            logger.exception("Failed to set reference project")
            show_error(self, "Error", f"Failed to set reference project: {e}")

    def on_recalculate_keyness(self):
        """Recalculate Keyness/Weirdness without re-extracting (PATCH-08)."""
        from PyQt6.QtWidgets import QProgressDialog
        from app.ui.workers import RecalculateKeynessWorker

        self.staleness_warning_btn.setEnabled(False)
        self.staleness_warning_btn.setText("Recalculating...")

        self._recalc_worker = RecalculateKeynessWorker(project_id=self.project_id)
        self._recalc_worker.progress.connect(
            lambda msg: self.staleness_warning_btn.setText(f"Recalculating… {msg}")
        )
        self._recalc_worker.finished.connect(self._on_recalculate_finished)
        self._recalc_worker.error.connect(self._on_recalculate_error)
        self._recalc_worker.start()

    def _on_recalculate_finished(self, result: dict):
        """Handle recalculate completion."""
        self.staleness_warning_btn.setEnabled(True)
        self.staleness_warning_btn.setText("⚠ Keyness/Weirdness may be outdated — Recalculate")
        updated = result.get("updated", 0)
        self.staleness_warning_btn.setVisible(False)
        self.status_label.setText(f"Recalculated metrics for {updated} clusters.")
        self.perform_search()

    def _on_recalculate_error(self, error_msg: str):
        """Handle recalculate error."""
        self.staleness_warning_btn.setEnabled(True)
        self.staleness_warning_btn.setText("⚠ Keyness/Weirdness may be outdated — Recalculate")
        show_error(self, "Recalculate Error", f"Failed to recalculate metrics:\n{error_msg}")

    def on_np_max_len_changed(self):
        """Handle Max NP length change - save setting (no reload needed, used only during extraction)."""
        self.settings.set_value("terms_view/np_max_len", self.np_max_len_spin.value())

    def on_min_freq_changed(self):
        """Handle Min freq change - save setting (no reload needed, used only during extraction)."""
        self.settings.set_value("terms_view/min_freq", self.min_freq_spin.value())

    def on_min_doc_freq_changed(self):
        """Handle Min doc freq change - persist and refresh view (PATCH-10)."""
        self.settings.set_value("terms_view/min_doc_freq", self.min_doc_freq_spin.value())
        self.current_page = 1
        self.perform_search()

    def on_include_np_changed(self):
        """Handle Include NP chunks toggle - persist via QSettings."""
        self.settings.set_value("terms_view/include_np", self.include_np_checkbox.isChecked())

    def on_ngram_ns_changed(self):
        """Handle bigram/trigram checkbox toggle - persist selection via QSettings."""
        ns = sorted(
            n
            for n, cb in ((2, self.ngram_bigrams_checkbox), (3, self.ngram_trigrams_checkbox))
            if cb.isChecked()
        )
        self.settings.set_value("terms_view/ngram_ns_json", json.dumps(ns))

    def build_filters(self) -> dict:
        """Build filters dict for search."""
        return {
            "search": self.search_edit.text().strip(),
            "preset": self.preset_combo.currentText().lower(),
            "source_filter": self._get_source_filter(),
            "min_freq": self.min_freq_spin.value() if self.min_freq_spin.value() > 1 else None,
            "min_doc_freq": (
                self.min_doc_freq_spin.value() if self.min_doc_freq_spin.value() > 1 else None
            ),
            "hide_noise": self.hide_noise_checkbox.isChecked(),
        }

    def _get_source_filter(self) -> str | None:
        """Get source filter value from combo."""
        source = self.source_combo.currentText()
        if source == "All":
            return None
        elif source == "N-grams":
            return "ngram"
        elif source == "NP":
            return "np"
        return None

    def on_filter_changed(self):
        """Handle filter change - reset to page 1 and search."""
        self.current_page = 1
        self.perform_search()

    def on_search_changed(self, text: str):
        """Handle search text change - reset to page 1 and search."""
        self.current_page = 1
        self._search_timer.start()

    def perform_search(
        self, *, include_total_count: bool = True, preserve_existing_state: bool = False
    ):
        """Perform search with current filters and pagination."""
        # Cancel previous worker if running
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.cancel()
            if not self.search_worker.wait(100):
                self._search_retry_pending = True
                return

        self._search_retry_pending = False
        self._search_request_seq += 1
        request_seq = self._search_request_seq
        preserved_state = self._snapshot_cluster_state() if preserve_existing_state else {}
        if include_total_count:
            self.total_count = 0

        # Build filters
        filters = self.build_filters()

        # Create and start worker
        self.search_worker = TermsSearchWorker(
            project_id=self.project_id,
            filters=filters,
            limit=self.page_size,
            offset=self.current_offset,
            include_total_count=include_total_count,
        )
        self._active_search_seq = request_seq

        self.search_worker.results_ready.connect(
            lambda clusters, seq=request_seq, preserved=preserved_state, recount=include_total_count: self.on_search_results(
                clusters,
                seq,
                preserved_state=preserved,
                include_total_count=recount,
            )
        )
        self.search_worker.count_ready.connect(
            lambda total_count, seq=request_seq: self.on_search_count_ready(total_count, seq)
        )
        self.search_worker.error.connect(
            lambda error_msg, seq=request_seq: self.on_search_error(error_msg, seq)
        )
        self.search_worker.finished.connect(
            lambda seq=request_seq, worker=self.search_worker: self._on_search_worker_finished(
                worker, seq
            )
        )
        self.search_worker.start()

        # Update status
        self.status_label.setText("Searching...")

    def _on_search_worker_finished(self, worker, request_seq: int) -> None:
        if worker is self.search_worker:
            self.search_worker = None

        worker.deleteLater()

        if self._search_retry_pending:
            self._search_retry_pending = False
            QTimer.singleShot(0, self.perform_search)

    def on_search_results(
        self,
        clusters: list,
        request_seq: int | None = None,
        *,
        preserved_state: dict | None = None,
        include_total_count: bool = True,
    ):
        """Handle search results from worker."""
        if request_seq is not None and request_seq != self._active_search_seq:
            logger.debug(
                "Ignoring stale terms search results: seq=%s active=%s",
                request_seq,
                self._active_search_seq,
            )
            return

        translation_results = self._rehydrate_cluster_state(clusters, preserved_state or {})

        self.terms_model.update_clusters(clusters)
        self.terms_model.translation_results = translation_results

        if include_total_count and self.total_count == 0:
            self.status_label.setText("No term clusters found")
        else:
            start = self.current_offset + 1
            if include_total_count:
                end = self.current_offset + len(clusters)
                self.status_label.setText(f"Loaded {start}-{end} term clusters (counting total...)")
            else:
                end = min(self.current_offset + len(clusters), self.total_count)
                self.status_label.setText(
                    f"Showing {start}-{end} of {self.total_count:,} term clusters"
                )

        self.update_pagination_controls()

        # Load last extraction info (only need session briefly)
        try:
            with self.db_service.get_session() as session:
                self._update_last_extract_info(session)
        except Exception:
            logger.exception("Failed to load last extraction info")

        self.start_overlay_worker(clusters, request_seq)
        self.start_translation_worker(clusters)

    def on_search_count_ready(self, total_count: int, request_seq: int | None = None):
        """Handle deferred total-count result from worker."""
        if request_seq is not None and request_seq != self._active_search_seq:
            logger.debug(
                "Ignoring stale terms count: seq=%s active=%s",
                request_seq,
                self._active_search_seq,
            )
            return

        self.total_count = int(total_count or 0)
        if self.total_count == 0:
            self.status_label.setText("No term clusters found")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + len(self.terms_model.clusters), self.total_count)
            self.status_label.setText(
                f"Showing {start}-{end} of {self.total_count:,} term clusters"
            )
        self.update_pagination_controls()

    def _snapshot_cluster_state(self) -> dict[int, dict]:
        snapshot: dict[int, dict] = {}
        for row, cluster in enumerate(getattr(self.terms_model, "clusters", []) or []):
            cluster_id = int(getattr(cluster, "cluster_id", 0) or 0)
            if cluster_id <= 0:
                continue
            snapshot[cluster_id] = {
                "translation": getattr(cluster, "translation", None),
                "translation_status": getattr(cluster, "translation_status", None),
                "in_user_dictionary_count": getattr(cluster, "in_user_dictionary_count", 0),
                "study_tooltip": getattr(cluster, "study_tooltip", None),
                "study_state": getattr(cluster, "study_state", None),
                "study_due_human": getattr(cluster, "study_due_human", None),
                "last_grade": getattr(cluster, "last_grade", None),
                "last_graded_at": getattr(cluster, "last_graded_at", None),
                "translation_tier": getattr(cluster, "translation_tier", None),
                "audio_status": getattr(cluster, "audio_status", None),
                "pronunciation_text": getattr(cluster, "pronunciation_text", None),
                "pronunciation_source": getattr(cluster, "pronunciation_source", None),
                "pronunciation_confidence": getattr(cluster, "pronunciation_confidence", None),
                "pronunciation_qc": getattr(cluster, "pronunciation_qc", None),
                "translation_result": self.terms_model.translation_results.get(row),
            }
        return snapshot

    def _rehydrate_cluster_state(
        self, clusters: list, preserved_state: dict[int, dict]
    ) -> dict[int, object]:
        translation_results: dict[int, object] = {}
        if not preserved_state:
            return translation_results
        for row, cluster in enumerate(clusters):
            payload = preserved_state.get(int(getattr(cluster, "cluster_id", 0) or 0))
            if not payload:
                continue
            for field, value in payload.items():
                if field == "translation_result":
                    continue
                setattr(cluster, field, value)
            if payload.get("translation_result") is not None:
                translation_results[row] = payload["translation_result"]
        return translation_results

    def start_overlay_worker(self, clusters: list, request_seq: int | None = None) -> None:
        if not clusters:
            return
        if self.overlay_worker and self.overlay_worker.isRunning():
            self.overlay_worker.cancel()
            if not self.overlay_worker.wait(100):
                self._pending_overlay_clusters = clusters
                return
        self._overlay_request_seq += 1
        seq = self._overlay_request_seq
        rows = [
            {
                "item_id": int(cluster.cluster_id),
                "kind": "term_cluster",
                "src_text": cluster.representative_he,
                "norm_text": cluster.norm_text or "",
            }
            for cluster in clusters
        ]
        self.overlay_worker = CrossViewOverlayWorker(rows)
        self._active_overlay_seq = seq
        self.overlay_worker.results_ready.connect(
            lambda payload, overlay_seq=seq, search_seq=request_seq: self.on_overlay_results(
                payload,
                overlay_seq,
                request_seq=search_seq,
            )
        )
        self.overlay_worker.error.connect(
            lambda error_msg, overlay_seq=seq: self.on_overlay_error(error_msg, overlay_seq)
        )
        self.overlay_worker.finished.connect(
            lambda overlay_seq=seq, worker=self.overlay_worker: self._on_overlay_worker_finished(
                worker, overlay_seq
            )
        )
        self.overlay_worker.start()

    def _on_overlay_worker_finished(self, worker, overlay_seq: int) -> None:
        if worker is self.overlay_worker:
            self.overlay_worker = None
        worker.deleteLater()
        if self._pending_overlay_clusters:
            pending = self._pending_overlay_clusters
            self._pending_overlay_clusters = None
            QTimer.singleShot(0, lambda: self.start_overlay_worker(pending))

    def on_overlay_results(
        self, overlay_map: dict, overlay_seq: int, *, request_seq: int | None = None
    ) -> None:
        if overlay_seq != self._active_overlay_seq:
            return
        if request_seq is not None and request_seq != self._active_search_seq:
            return
        if not overlay_map:
            return
        changed_rows = []
        for row, cluster in enumerate(self.terms_model.clusters):
            payload = overlay_map.get(int(getattr(cluster, "cluster_id", 0) or 0))
            if not payload:
                continue
            changed_rows.append(row)
            for field in (
                "in_user_dictionary_count",
                "study_tooltip",
                "study_state",
                "study_due_human",
                "last_grade",
                "last_graded_at",
                "translation_tier",
                "audio_status",
                "pronunciation_text",
                "pronunciation_source",
                "pronunciation_confidence",
                "pronunciation_qc",
            ):
                setattr(cluster, field, payload.get(field))
        if changed_rows:
            top = self.terms_model.index(min(changed_rows), 0)
            bottom = self.terms_model.index(max(changed_rows), self.terms_model.columnCount() - 1)
            self.terms_model.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    def on_overlay_error(self, error_msg: str, overlay_seq: int) -> None:
        if overlay_seq != self._active_overlay_seq:
            return
        logger.warning("Terms overlay worker error: %s", error_msg)

    def _apply_study_overlays(self, clusters: list) -> None:
        """Attach saved-to-UD + study tooltip metadata in one batch lookup."""
        if not clusters:
            return

        def _cluster_norm(cluster_obj) -> str:
            normalized = normalize_for_tm("he", cluster_obj.representative_he, "term_cluster").norm
            return normalized or (cluster_obj.norm_text or "")

        payloads = []
        raw_norm_pairs = []
        for cluster in clusters:
            src_norm = _cluster_norm(cluster)
            raw_src_norm = normalize_for_tm("he", cluster.representative_he, "surface").norm
            raw_src_norm = (raw_src_norm or "").strip() or (cluster.norm_text or "").strip()
            payloads.append(
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": cluster.representative_he,
                    "src_norm": src_norm,
                    "raw_src_norm": raw_src_norm,
                }
            )
            if raw_src_norm:
                raw_norm_pairs.append(("he", raw_src_norm))

        try:
            with self.db_service.get_session() as session:
                overlay_map = self.user_dict_service.resolve_cross_view_status(session, payloads)
                pronunciation_map = self.user_dict_service._resolve_pronunciation_overlay(
                    session, raw_norm_pairs
                )
        except Exception as e:
            logger.warning("Failed to resolve terms study overlays: %s", e)
            return

        for cluster in clusters:
            src_norm = _cluster_norm(cluster)
            raw_src_norm = normalize_for_tm("he", cluster.representative_he, "surface").norm
            raw_src_norm = (raw_src_norm or "").strip() or (cluster.norm_text or "").strip()
            canonical_hash = self.user_dict_service.build_canonical_hash(
                "he", "ru", "term_cluster", src_norm
            )
            overlay = overlay_map.get(canonical_hash)
            if not overlay:
                cluster.in_user_dictionary_count = 0
                cluster.study_tooltip = None
                cluster.study_state = None
                cluster.study_due_human = None
                cluster.last_grade = None
                cluster.last_graded_at = None
                cluster.translation_tier = None
                cluster.audio_status = None
                cluster.pronunciation_text = None
                cluster.pronunciation_source = None
                cluster.pronunciation_confidence = None
                cluster.pronunciation_qc = None
                continue

            cluster.in_user_dictionary_count = int(overlay.get("in_user_dictionary_count") or 0)
            cluster.study_tooltip = overlay.get("study_tooltip")
            cluster.study_state = overlay.get("study_state")
            cluster.study_due_human = overlay.get("study_due_human")
            cluster.last_grade = overlay.get("last_grade")
            cluster.last_graded_at = overlay.get("last_graded_at")
            cluster.translation_tier = overlay.get("translation_tier")
            cluster.audio_status = overlay.get("audio_status")
            cluster.pronunciation_text = overlay.get("pronunciation_text")
            cluster.pronunciation_source = overlay.get("pronunciation_source")
            cluster.pronunciation_confidence = overlay.get("pronunciation_confidence")
            cluster.pronunciation_qc = overlay.get("pronunciation_qc")

            row_pron = pronunciation_map.get(("he", raw_src_norm))
            if row_pron:
                cluster.pronunciation_text = row_pron.get("pronunciation_text")
                cluster.pronunciation_source = row_pron.get("pronunciation_source")
                cluster.pronunciation_confidence = row_pron.get("pronunciation_confidence")
                cluster.pronunciation_qc = row_pron.get("pronunciation_qc")

    def on_search_error(self, error_msg: str, request_seq: int | None = None):
        """Handle search error."""
        if request_seq is not None and request_seq != self._active_search_seq:
            logger.debug(
                "Ignoring stale terms search error: seq=%s active=%s",
                request_seq,
                self._active_search_seq,
            )
            return

        logger.error(f"Search error: {error_msg}")
        show_error(self, "Search Error", f"Failed to search term clusters: {error_msg}")
        self.status_label.setText("Search failed")

    def on_first_page(self):
        """Navigate to first page."""
        if self.current_page != 1:
            self.current_page = 1
            self.perform_search(include_total_count=False, preserve_existing_state=True)

    def on_prev_page(self):
        """Navigate to previous page."""
        if self.current_page > 1:
            self.current_page -= 1
            self.perform_search(include_total_count=False, preserve_existing_state=True)

    def on_next_page(self):
        """Navigate to next page."""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.perform_search(include_total_count=False, preserve_existing_state=True)

    def on_last_page(self):
        """Navigate to last page."""
        total = self.total_pages
        if self.current_page != total:
            self.current_page = total
            self.perform_search(include_total_count=False, preserve_existing_state=True)

    def on_page_changed(self, page: int):
        """Handle page number change from spinbox."""
        if page != self.current_page:
            self.current_page = page
            self.perform_search(include_total_count=False, preserve_existing_state=True)

    def on_page_size_changed(self, size_str: str):
        """Handle page size change (Task 15: supports 'All (N)' format)."""
        # Task 15: Handle "All (N)" format
        if size_str.startswith("All"):
            new_size = self.total_count
        else:
            new_size = int(size_str)

        if new_size != self.page_size:
            self.page_size = new_size
            self.settings.set_value("terms_view/page_size", self.page_size)
            self.current_page = 1  # Reset to first page
            self.perform_search(include_total_count=False, preserve_existing_state=True)

    def refresh_current_page_after_operation(self) -> None:
        """Refresh visible rows without forcing expensive recount or blanking visible state."""
        try:
            self.perform_search(include_total_count=False, preserve_existing_state=True)
        except TypeError:
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
            self.range_label.setText("Showing 0вЂ“0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}вЂ“{end} of {self.total_count:,}")

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

    def focus_term_by_id(self, cluster_id: int) -> bool:
        """Best-effort focus helper used by Audio Player 'Go to Source'."""
        for source_row, cluster in enumerate(self.terms_model.clusters):
            if int(getattr(cluster, "cluster_id", 0) or 0) != int(cluster_id):
                continue
            source_index = self.terms_model.index(source_row, 0)
            proxy_index = self.proxy_model.mapFromSource(source_index)
            if not proxy_index.isValid():
                return False
            self.terms_table.setCurrentIndex(proxy_index)
            self.terms_table.selectRow(proxy_index.row())
            self.terms_table.scrollTo(proxy_index, QTableView.ScrollHint.PositionAtCenter)
            return True
        return False

    def on_extract(self):
        """Handle extract terms button."""
        from PyQt6.QtWidgets import QMessageBox

        from app.ui.workers import ProjectTermExtractionWorker

        reply = QMessageBox.question(
            self,
            "Extract Terms",
            "Extract terms (n-grams + NP chunks + clustering) for this project?\n\n"
            "Large projects are processed in resumable batches.\n"
            "If extraction is interrupted, re-running will resume the latest staged run.\n\n"
            "This may take a few minutes for large corpora.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Get extraction parameters from UI
        include_np = self.include_np_checkbox.isChecked()
        np_max_len = self.np_max_len_spin.value()
        min_freq = self.min_freq_spin.value()
        ngram_ns_list = [
            n
            for n, cb in (
                (2, self.ngram_bigrams_checkbox),
                (3, self.ngram_trigrams_checkbox),
            )
            if cb.isChecked()
        ]
        # Validate: n-gram extraction requires at least one size selected
        if not ngram_ns_list:
            QMessageBox.warning(
                self,
                "N-gram size required",
                "For n-gram extraction, select at least one size: Bigrams and/or Trigrams.",
            )
            return
        ngram_ns: tuple[int, ...] = tuple(ngram_ns_list)

        # Disable UI during extraction (prevent QThread lifecycle issues)
        self.extract_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText("Extracting terms...")

        # PERF-SCALE PATCH-K: throttle check вЂ” block concurrent term extraction.
        from app.services.pipeline_throttler import PipelineThrottler

        if not PipelineThrottler.instance().check_and_warn(
            "term_extract", parent=self, operation_label="Term Extraction"
        ):
            # Re-enable UI since we're not starting
            self.extract_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.status_label.setText("Ready")
            return

        # Epic 5A PATCH-03: impact preview before destructive overwrite.
        # Run a quick read-only query to count clusters and linked TM entries
        # that will be affected. Show a confirmation if any TM links exist.
        with self.db_service.get_session() as _impact_sess:
            impact = self.term_service.get_overwrite_impact(
                _impact_sess, self.project_id
            )
        if impact["linked_tm_entries"] > 0:
            linked = impact["linked_tm_entries"]
            clusters = impact["clusters"]
            msg = (
                f"Full Overwrite will delete {clusters} term cluster(s).\n\n"
                f"{linked} Translation Memory entry(ies) will lose their active cluster link\n"
                f"(they will be kept in TM with status \u201csource_cluster_missing\u201d).\n\n"
                "Continue?"
            )
            overwrite_reply = QMessageBox.question(
                self,
                "Overwrite Impact",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if overwrite_reply != QMessageBox.StandardButton.Yes:
                self.extract_btn.setEnabled(True)
                self.refresh_btn.setEnabled(True)
                self.progress_bar.setVisible(False)
                self.status_label.setText("Ready")
                return

        # Create and start worker (keep strong reference to prevent GC)
        self.extract_worker = ProjectTermExtractionWorker(
            project_id=self.project_id,
            enable_ngrams=True,
            include_np=include_np,
            min_freq=min_freq,
            ngram_ns=ngram_ns,
            np_max_len=np_max_len,
            overwrite=True,
        )

        self.extract_worker.progress.connect(self.on_extract_progress)
        self.extract_worker.state_changed.connect(self.on_extract_state)
        self.extract_worker.finished.connect(self.on_extract_finished)
        self.extract_worker.error.connect(self.on_extract_error)
        self.extract_progress_dialog = TermExtractionProgressDialog(parent=self, total_docs=0)
        self.extract_progress_dialog.cancel_requested.connect(self.extract_worker.cancel)
        self.extract_progress_dialog.pause_requested.connect(self.extract_worker.pause)
        self.extract_progress_dialog.resume_requested.connect(self.extract_worker.resume)
        self.extract_progress_dialog.show()

        self.extract_worker.start()

    def on_extract_progress(self, message: str):
        """Handle extraction progress updates."""
        self.status_label.setText(message)

    def on_extract_state(self, state: dict):
        """Handle structured extraction progress state."""
        docs_total = max(0, int(state.get("docs_total") or 0))
        docs_processed = max(0, int(state.get("docs_processed") or 0))
        docs_failed = max(0, int(state.get("docs_failed") or 0))
        stage = str(state.get("message") or state.get("stage") or "Extracting terms...")

        self.progress_bar.setVisible(True)
        if docs_total > 0:
            self.progress_bar.setRange(0, docs_total)
            self.progress_bar.setValue(min(docs_processed + docs_failed, docs_total))
        else:
            self.progress_bar.setRange(0, 0)
        self.status_label.setText(stage)

        if self.extract_progress_dialog:
            self.extract_progress_dialog.update_state(state)

    def _finish_extract_dialog(self, *, accepted: bool, failed_message: str | None = None) -> None:
        dialog = self.extract_progress_dialog
        if not dialog:
            return
        if failed_message:
            dialog.set_failed(failed_message)
            dialog.reject()
        elif accepted:
            dialog.accept()
        else:
            dialog.reject()
        dialog.deleteLater()
        self.extract_progress_dialog = None

    def _cleanup_extract_worker(self) -> None:
        if self.extract_worker:
            self.extract_worker.deleteLater()
            self.extract_worker = None

    def _stop_extract_worker(self) -> None:
        if self.extract_worker and self.extract_worker.isRunning():
            logger.info("Stopping term extraction worker on close")
            if self.extract_progress_dialog:
                self.extract_progress_dialog.append_activity(
                    "View is closing; cancellation requested."
                )
            self.extract_worker.cancel()
            if not self.extract_worker.wait(100):
                logger.info("Term extraction worker will finish cooperatively after close")

    def on_extract_finished(self, report):
        """Handle extraction completion."""
        self.progress_bar.setVisible(False)

        # Re-enable UI
        self.extract_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

        if report.success:
            self.status_label.setText("Extraction complete")
            if self.extract_progress_dialog:
                self.extract_progress_dialog.set_completed()
            self._finish_extract_dialog(accepted=True)
            msg = "Term extraction successful!\n\n"
            msg += f"N-grams: {report.ngrams_extracted}\n"
            msg += f"NP chunks: {report.np_chunks_extracted}\n"
            msg += f"Clusters: {report.clusters_created}"
            source_mix = self._format_extract_source_mix(report)
            if source_mix:
                msg += f"\n\n{source_mix}"

            show_info(self, "Extraction Complete", msg)
            self._set_last_extract_source_mix(report)
            self.perform_search()
        elif getattr(report, "cancelled", False):
            self.status_label.setText("Extraction cancelled")
            if self.extract_progress_dialog:
                self.extract_progress_dialog.set_cancelled()
            self._finish_extract_dialog(accepted=True)
            msg = (
                "Term extraction was cancelled.\n\n"
                f"Processed docs: {int(getattr(report, 'docs_processed', 0))} / "
                f"{int(getattr(report, 'docs_total', 0))}\n"
                "Re-run Extract Terms to resume the latest staged run."
            )
            source_mix = self._format_extract_source_mix(report)
            if source_mix:
                msg += f"\n\n{source_mix}"
            show_info(self, "Extraction Cancelled", msg)
            self._set_last_extract_source_mix(report)
        else:
            self.status_label.setText("Extraction failed")
            self._finish_extract_dialog(
                accepted=False,
                failed_message=str(
                    getattr(report, "error_message", "") or "Unknown extraction error"
                ),
            )
            show_error(self, "Extraction Failed", report.error_message)

        self._cleanup_extract_worker()

    def on_extract_error(self, error_msg: str):
        """Handle extraction error."""
        self.progress_bar.setVisible(False)

        # Re-enable UI
        self.extract_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.status_label.setText("Extraction failed")

        self._finish_extract_dialog(accepted=False, failed_message=error_msg)
        self._cleanup_extract_worker()

        show_error(self, "Error", error_msg)

    def start_translation_worker(self, clusters: list):
        """M7 P1: Start worker to resolve translations for term clusters."""
        if not clusters:
            return

        # Cancel previous worker if running
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.cancel()
            if not self.translation_worker.wait(100):
                self._pending_translation_clusters = clusters
                return

        self._pending_translation_clusters = None
        self._translation_request_seq = getattr(self, "_translation_request_seq", 0) + 1
        request_seq = self._translation_request_seq

        # Build items for worker: (src_text, kind)
        items = [(cluster.representative_he, "term_cluster") for cluster in clusters]

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
            lambda seq=request_seq, worker=self.translation_worker: self._on_translation_worker_finished(
                worker, seq
            )
        )
        self.translation_worker.start()

        logger.info(f"Started translation worker for {len(items)} term clusters")

    def _on_translation_worker_finished(self, worker, request_seq: int) -> None:
        if worker is self.translation_worker:
            self.translation_worker = None

        worker.deleteLater()

        pending_clusters = getattr(self, "_pending_translation_clusters", None)
        if pending_clusters:
            self._pending_translation_clusters = None
            QTimer.singleShot(0, lambda: self.start_translation_worker(pending_clusters))

    def on_translation_results(self, results: dict, request_seq: int | None = None):
        """M7 P1: Handle translation results from worker."""
        if request_seq is not None and request_seq != getattr(self, "_active_translation_seq", 0):
            logger.debug(
                "Ignoring stale terms translation results: seq=%s active=%s",
                request_seq,
                getattr(self, "_active_translation_seq", 0),
            )
            return

        logger.info(f"Received {len(results)} translation results")

        # Update model with results
        self.terms_model.update_translations(results)

    def on_translation_error(self, error_msg: str, request_seq: int | None = None):
        """M7 P1: Handle translation worker error."""
        if request_seq is not None and request_seq != getattr(self, "_active_translation_seq", 0):
            logger.debug(
                "Ignoring stale terms translation error: seq=%s active=%s",
                request_seq,
                getattr(self, "_active_translation_seq", 0),
            )
            return

        logger.error(f"Translation worker error: {error_msg}")
        show_error(self, "Translation Error", f"Failed to load translations: {error_msg}")

    def on_translation_edited(self, top_left: QModelIndex, bottom_right: QModelIndex, roles):
        """M7 P1: Handle inline edit of translation - save to TM."""
        # Check if Translation column was edited (col 12)
        if top_left.column() != 12:
            return

        row = top_left.row()
        cluster = self.terms_model.clusters[row]

        # Get new translation value
        new_translation = cluster.translation

        # Allow empty translations (user can delete translation)
        try:
            with self.db_service.get_session() as session:
                # Save to TM
                from datetime import datetime

                from sqlalchemy import select

                from app.infra.sa_models import TermCluster, TMEntry

                # Get cluster canonical_key from database
                stmt = select(TermCluster).where(
                    TermCluster.project_id == self.project_id,
                    TermCluster.representative_he == cluster.representative_he,
                )
                db_cluster = session.execute(stmt).scalar()

                if not db_cluster:
                    logger.error(f"Could not find cluster for {cluster.representative_he}")
                    return

                # Normalize representative_he to match what TranslationResolveWorker uses
                from app.domain.normalization.normalizer import normalize_for_tm

                normalized = normalize_for_tm("he", cluster.representative_he, "term_cluster")
                src_norm = normalized.norm

                # Strip whitespace but allow empty string (deletion)
                translation_value = new_translation.strip() if new_translation else ""

                # Check if TM entry exists
                stmt = select(TMEntry).where(
                    TMEntry.project_id == self.project_id,
                    TMEntry.kind == "term_cluster",
                    TMEntry.src_norm == src_norm,
                )
                existing = session.execute(stmt).scalar()

                if existing:
                    # Update existing
                    existing.translation = translation_value
                    existing.status = "approved"  # User edit в†’ approved
                    existing.origin = "user_edit"
                    existing.updated_at = datetime.now()
                else:
                    # Create new TM entry with source_id link for is_noise synchronization
                    tm_entry = TMEntry(
                        project_id=self.project_id,
                        kind="term_cluster",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text=cluster.representative_he,
                        src_norm=src_norm,
                        translation=translation_value,
                        status="approved",  # User edit в†’ approved
                        origin="user_edit",
                        source_ref="terms_view_inline_edit",
                        cluster_id=cluster.cluster_id,  # Link to source for is_noise sync
                        is_noise=cluster.is_noise if cluster.is_noise is not None else 0,
                        noise_reason=cluster.noise_reason,
                    )
                    session.add(tm_entry)

                # PATCH-19-02: Upsert tm_global and link
                # Use retry mechanism to handle database locked errors
                from app.infra.db_retry import with_retry_on_locked
                from app.infra.write_gate import serialized_db_write

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
                    self.status_label.setText(
                        f"Database is busy, retrying ({attempt}/{total_attempts})..."
                    )

                with serialized_db_write("terms.inline_tm_save"):
                    with_retry_on_locked(
                        save_and_propagate,
                        max_retries=4,
                        rollback_callback=session.rollback,
                        retry_callback=_on_retry,
                    )

                # Update status in model to "approved"
                cluster.translation_status = "approved"
                status_idx = self.terms_model.index(row, 14)  # Status column
                self.terms_model.dataChanged.emit(
                    status_idx, status_idx, [Qt.ItemDataRole.DisplayRole]
                )

                logger.info(
                    f"Saved TM entry for term: {cluster.representative_he} -> {translation_value}"
                )

        except Exception as e:
            logger.exception("Failed to save TM entry")
            show_error(self, "Save Error", f"Failed to save translation: {e}")

    def _selected_audio_items(self) -> list[dict]:
        """Build source-audio payloads from selected term rows."""
        selected_rows = self.terms_table.selectionModel().selectedRows()
        items: list[dict] = []
        for proxy_index in sorted(selected_rows, key=lambda idx: idx.row()):
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            cluster = self.terms_model.clusters[source_row]
            src_norm = normalize_for_tm("he", cluster.representative_he, "term_cluster").norm or (
                cluster.norm_text or ""
            )
            if not src_norm:
                continue
            items.append(
                {
                    "row_id": str(cluster.cluster_id),
                    "src_text": cluster.representative_he,
                    "src_lang": "he",
                    "src_norm": src_norm,
                    "kind": "term",
                    "source_id": int(cluster.cluster_id),
                    "project_id": getattr(self, "project_id", None),
                    "source_label": "Terms",
                    "translation": cluster.translation or "",
                    "pronunciation_text": getattr(cluster, "pronunciation_text", "") or "",
                }
            )
        return items

    def _selected_pronunciation_items(self) -> list[dict]:
        """Build pronunciation payloads from selected term rows."""
        selected_rows = self.terms_table.selectionModel().selectedRows()
        items: list[dict] = []
        for proxy_index in sorted(selected_rows, key=lambda idx: idx.row()):
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            cluster = self.terms_model.clusters[source_row]
            src_norm = normalize_for_tm("he", cluster.representative_he, "surface").norm
            src_norm = (
                (src_norm or "").strip()
                or (cluster.norm_text or "").strip()
                or normalize_for_tm("he", cluster.representative_he, "term_cluster").norm
            )
            if not src_norm:
                continue
            items.append(
                {
                    "src_lang": "he",
                    "src_text": cluster.representative_he,
                    "src_norm": src_norm,
                    "raw_src_norm": src_norm,
                    "source_group": "terms",
                }
            )
        return items

    def on_generate_audio_selected(self):
        """Generate source-audio for selected term rows."""
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
        worker.finished.connect(
            lambda result: self._on_generate_audio_finished(result, progress_dialog)
        )
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
        self.refresh_current_page_after_operation()

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
        cluster = self.terms_model.clusters[source_row]
        src_norm = normalize_for_tm("he", cluster.representative_he, "term_cluster").norm or (
            cluster.norm_text or ""
        )
        if not src_norm:
            return
        self._play_audio_items(
            [
                {
                    "src_lang": "he",
                    "src_norm": src_norm,
                    "src_text": cluster.representative_he,
                    "kind": "term",
                    "source_id": int(cluster.cluster_id),
                    "project_id": getattr(self, "project_id", None),
                    "source_label": "Terms",
                    "translation": cluster.translation or "",
                    "pronunciation_text": getattr(cluster, "pronunciation_text", "") or "",
                }
            ],
            play_mode="enqueue",
            start_immediately=True,
        )

    def _play_audio_items(
        self, items: list[dict], *, play_mode: str, start_immediately: bool = False
    ) -> None:
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
                            payload.get("translation") or payload.get("snapshot_translation") or ""
                        ),
                        "snapshot_source_label": str(
                            payload.get("source_label")
                            or payload.get("snapshot_source_label")
                            or "Terms"
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
            logger.error("Failed to play audio in Terms: %s", e, exc_info=True)
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
            self.refresh_current_page_after_operation()

    def on_pronunciation_bootstrap_selected(self):
        """Open pronunciation bootstrap dialog with selected rows scope."""
        from app.ui.dialogs.pronunciation_bootstrap_dialog import (
            show_pronunciation_bootstrap_dialog,
        )

        selected_items = self._selected_pronunciation_items()
        changed = False
        if not selected_items:
            changed = show_pronunciation_bootstrap_dialog(parent=self)
        else:
            changed = show_pronunciation_bootstrap_dialog(
                parent=self, selected_items=selected_items
            )
        if changed:
            self.refresh_current_page_after_operation()

    def on_context_menu(self, pos):
        """M7 P1: Show context menu with 'Why?' action."""
        index = self.terms_table.indexAt(pos)  # Returns PROXY index
        if not index.isValid():
            return

        # Map proxy row to source row (CRITICAL FIX for sorted tables)
        source_row = self.proxy_model.map_to_source_row(index.row())
        cluster = self.terms_model.clusters[source_row]

        # Create menu
        menu = QMenu(self)

        # Batch translate action (parity with Translate Selected button)
        selected_rows = self.terms_table.selectionModel().selectedRows()
        if selected_rows:
            batch_action = QAction(f"Translate selected ({len(selected_rows)} rows)...", self)
            batch_action.triggered.connect(self.on_batch_translate)
            menu.addAction(batch_action)

            generate_audio_action = QAction(
                f"Generate Audio Selected ({len(selected_rows)} rows)...", self
            )
            generate_audio_action.triggered.connect(self.on_generate_audio_selected)
            menu.addAction(generate_audio_action)

            play_audio_action = QAction(f"Play Audio Selected ({len(selected_rows)} rows)", self)
            play_audio_action.triggered.connect(self.on_play_audio_selected)
            menu.addAction(play_audio_action)

            add_action = QAction(
                f"Add Selected to User Dictionary ({len(selected_rows)} rows)...", self
            )
            add_action.triggered.connect(self.on_add_selected_to_user_dictionary)
            menu.addAction(add_action)
            add_playlist_action = QAction(
                f"Add Selected to Playlist ({len(selected_rows)} rows)...", self
            )
            add_playlist_action.triggered.connect(self.on_add_selected_to_playlist)
            menu.addAction(add_playlist_action)

            edit_pron_action = QAction("Mispronounced -> Add Pronunciation...", self)
            edit_pron_action.triggered.connect(self.on_edit_pronunciation_selected)
            menu.addAction(edit_pron_action)
            bootstrap_pron_action = QAction(
                f"Pronunciation Bootstrap Selected ({len(selected_rows)} rows)...", self
            )
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
            mark_valid_bulk_action = QAction(
                f"вњ“ Mark Selected as Valid ({len(selected_rows)} rows)", self
            )
            mark_valid_bulk_action.triggered.connect(
                lambda: self.set_clusters_noise_status_bulk(False)
            )
            menu.addAction(mark_valid_bulk_action)

            mark_noise_bulk_action = QAction(
                f"вњ— Mark Selected as Noise ({len(selected_rows)} rows)", self
            )
            mark_noise_bulk_action.triggered.connect(
                lambda: self.set_clusters_noise_status_bulk(True)
            )
            menu.addAction(mark_noise_bulk_action)
        else:
            # Single row operation
            current_is_noise = cluster.is_noise == 1 if cluster.is_noise is not None else False

            if current_is_noise:
                mark_valid_action = QAction("вњ“ Mark as Valid (remove from noise)", self)
                mark_valid_action.triggered.connect(
                    lambda: self.set_cluster_noise_status(source_row, False)
                )
                menu.addAction(mark_valid_action)
            else:
                mark_noise_action = QAction("вњ— Mark as Noise", self)
                mark_noise_action.triggered.connect(
                    lambda: self.set_cluster_noise_status(source_row, True)
                )
                menu.addAction(mark_noise_action)

        # Show menu
        menu.exec(self.terms_table.viewport().mapToGlobal(pos))

    def on_add_selected_to_user_dictionary(self):
        """Add selected term clusters to a user dictionary."""
        selected_rows = self.terms_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        payloads = []
        for proxy_index in selected_rows:
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            cluster = self.terms_model.clusters[source_row]
            src_norm = normalize_for_tm("he", cluster.representative_he, "term_cluster").norm
            payloads.append(
                {
                    "kind": "term_cluster",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": cluster.representative_he,
                    "src_norm": src_norm,
                    "is_noise": 1 if cluster.is_noise == 1 else 0,
                    "noise_reason": cluster.noise_reason,
                    "origin_project_id": self.project_id,
                    "origin_entity_type": "term_cluster",
                    "origin_entity_id": cluster.cluster_id,
                    "origin_source_ref": "terms_view",
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

        progress = QProgressDialog(
            "Adding items to dictionary...", "Cancel", 0, len(prepared), self
        )
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
        show_error(self, "Add Failed", error_msg)
        self._user_dict_add_worker = None

    def show_why_dialog(self, row: int):
        """M7 P1: Show WhyTranslationDialog for a term cluster."""
        cluster = self.terms_model.clusters[row]

        # Get translation result from model
        translation_result = self.terms_model.translation_results.get(row)

        if not translation_result:
            # If no result yet, create a minimal one
            from app.services.translation_service import TranslationResult

            translation_result = TranslationResult(
                translation=cluster.translation or "(no translation)",
                source="unknown",
                status=cluster.translation_status or "unknown",
            )

        # Show dialog
        dialog = WhyTranslationDialog(translation_result, cluster.representative_he, self)
        dialog.exec()

    def set_cluster_noise_status(self, row: int, is_noise: bool):
        """Task 11: Manually override noise status for a term cluster."""
        cluster = self.terms_model.clusters[row]

        try:
            with self.db_service.get_session() as session:
                from sqlalchemy import update

                from app.infra.sa_models import TermCluster

                # Update is_noise field
                stmt = (
                    update(TermCluster)
                    .where(TermCluster.cluster_id == cluster.cluster_id)
                    .values(is_noise=1 if is_noise else 0)
                )
                session.execute(stmt)
                self.user_dict_service.sync_noise_from_term_clusters(session, [cluster.cluster_id])
                session.commit()

                # Update local model
                cluster.is_noise = 1 if is_noise else 0

                status = "noise" if is_noise else "valid"
                logger.info(f"Marked cluster '{cluster.representative_he}' as {status}")

                # Reload to apply filter if needed
                if self.hide_noise_checkbox.isChecked():
                    self.perform_search()

        except Exception as e:
            logger.exception(f"Failed to update noise status for cluster {cluster.cluster_id}")
            from app.ui.dialogs import show_error

            show_error(self, "Error", f"Failed to update noise status: {e}")

    def set_clusters_noise_status_bulk(self, is_noise: bool):
        """Task 11 + P0: Bulk operation - update noise status for multiple selected clusters.

        P0 Safety features:
        - Confirmation dialog for > 100 rows
        - Progress dialog + QThread for > 1000 rows
        - Cancel support for long operations
        """
        selected_rows = self.terms_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # Map proxy rows to source rows and get cluster IDs
        cluster_ids = []
        source_rows = []
        for proxy_index in selected_rows:
            source_row = self.proxy_model.map_to_source_row(proxy_index.row())
            cluster = self.terms_model.clusters[source_row]
            cluster_ids.append(cluster.cluster_id)
            source_rows.append(source_row)

        count = len(cluster_ids)
        status_text = "noise" if is_noise else "valid"

        # P0: Confirmation dialog for > 100 rows
        if count > 100:
            from PyQt6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Confirm Bulk Action",
                f"You are about to mark {count:,} term clusters as {status_text}.\n\n"
                f"This operation cannot be undone easily.\n\n"
                f"Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,  # Default to No for safety
            )
            if reply == QMessageBox.StandardButton.No:
                logger.info(f"User cancelled bulk noise update for {count} clusters")
                return

        # P0: Use background worker for > 1000 rows (prevents UI freeze)
        if count > 1000:
            self._run_bulk_update_worker(cluster_ids, source_rows, is_noise)
        else:
            # Fast path: direct update for <= 1000 rows
            self._run_bulk_update_direct(cluster_ids, source_rows, is_noise)

    def _run_bulk_update_direct(self, cluster_ids: list, source_rows: list, is_noise: bool):
        """Direct bulk update for small datasets (<= 1000 rows)."""
        try:
            with self.db_service.get_session() as session:
                from sqlalchemy import update

                from app.infra.sa_models import TermCluster

                # Bulk update using WHERE IN
                stmt = (
                    update(TermCluster)
                    .where(TermCluster.cluster_id.in_(cluster_ids))
                    .values(is_noise=1 if is_noise else 0)
                )
                session.execute(stmt)
                self.user_dict_service.sync_noise_from_term_clusters(session, cluster_ids)
                session.commit()

                # Update local model for all affected rows
                for source_row in source_rows:
                    self.terms_model.clusters[source_row].is_noise = 1 if is_noise else 0

                status = "noise" if is_noise else "valid"
                logger.info(f"Marked {len(cluster_ids)} clusters as {status}")

                # Show success message
                from app.ui.dialogs import show_info

                show_info(self, "Success", f"Marked {len(cluster_ids)} term clusters as {status}")

                # Reload to apply filter if needed
                if self.hide_noise_checkbox.isChecked():
                    self.perform_search()

        except Exception as e:
            logger.exception(f"Failed to bulk update noise status for {len(cluster_ids)} clusters")
            from app.ui.dialogs import show_error

            show_error(self, "Error", f"Failed to bulk update noise status: {e}")

    def _run_bulk_update_worker(self, cluster_ids: list, source_rows: list, is_noise: bool):
        """Background worker for large datasets (> 1000 rows) with progress dialog."""
        from PyQt6.QtWidgets import QProgressDialog

        from app.ui.workers import BulkNoiseUpdateWorker

        # Create progress dialog
        status_text = "noise" if is_noise else "valid"
        self.bulk_progress_dialog = QProgressDialog(
            f"Marking {len(cluster_ids):,} term clusters as {status_text}...",
            "Cancel",
            0,
            len(cluster_ids),
            self,
        )
        self.bulk_progress_dialog.setWindowTitle("Bulk Update")
        self.bulk_progress_dialog.setModal(True)
        self.bulk_progress_dialog.setMinimumDuration(0)
        self.bulk_progress_dialog.show()

        # Store source_rows for later model update
        self._pending_source_rows = source_rows
        self._pending_is_noise = is_noise
        self._pending_cluster_ids = list(cluster_ids)

        # Create and start worker
        self.bulk_worker = BulkNoiseUpdateWorker(
            model_class="TermCluster", item_ids=cluster_ids, is_noise=is_noise
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
        if hasattr(self, "bulk_progress_dialog") and self.bulk_progress_dialog:
            self.bulk_progress_dialog.setValue(current)
            self.bulk_progress_dialog.setLabelText(
                f"Updated {current:,} of {total:,} term clusters..."
            )

    def _on_bulk_complete(self, count: int):
        """Handle bulk update completion."""
        # Close progress dialog
        if hasattr(self, "bulk_progress_dialog") and self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        # Update local model for all affected rows
        for source_row in self._pending_source_rows:
            self.terms_model.clusters[source_row].is_noise = 1 if self._pending_is_noise else 0

        # Sync source noise -> User Dictionaries after worker commit.
        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.sync_noise_from_term_clusters(
                    session,
                    getattr(self, "_pending_cluster_ids", []),
                )
                session.commit()
        except Exception as e:
            logger.warning(
                "Failed to sync term noise to User Dictionaries after bulk update: %s", e
            )

        status = "noise" if self._pending_is_noise else "valid"
        logger.info(f"Bulk update completed: {count} clusters marked as {status}")

        # Show success message
        from app.ui.dialogs import show_info

        show_info(self, "Success", f"Marked {count:,} term clusters as {status}")

        # Reload to apply filter if needed
        if self.hide_noise_checkbox.isChecked():
            self.perform_search()

    def _on_bulk_error(self, error_msg: str):
        """Handle bulk update error."""
        # Close progress dialog
        if hasattr(self, "bulk_progress_dialog") and self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        logger.error(f"Bulk noise update failed: {error_msg}")

        from app.ui.dialogs import show_error

        show_error(self, "Error", f"Bulk update failed:\n{error_msg}")

    def _on_bulk_cancel(self):
        """Handle bulk update cancellation."""
        if hasattr(self, "bulk_worker") and self.bulk_worker and self.bulk_worker.isRunning():
            self.bulk_worker.cancel()
            logger.info("User cancelled bulk noise update")

    def on_selection_changed(self):
        """Enable/disable batch translate button based on selection."""
        selected_rows = self.terms_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        self.batch_translate_btn.setEnabled(has_selection)
        self.generate_audio_btn.setEnabled(has_selection)
        self.play_audio_btn.setEnabled(has_selection)
        self.pronunciation_bootstrap_btn.setEnabled(has_selection)

    def on_batch_translate(self):
        """Task 15: Handle batch translate with scope support."""
        from PyQt6.QtWidgets import QMessageBox

        from app.services.db_service import DBService
        from app.services.term_extraction_service import TermExtractionService
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import TranslateAllFilteredWorker

        selected_indexes = self.terms_table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        # Task 15: Compute filtered count for "All pages" scope
        filtered_count = 0
        term_service = TermExtractionService()
        try:
            db_service = DBService.get_instance()
            with db_service.get_session() as session:
                filtered_count = term_service.count_cluster_ids_for_translation(
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
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Match User Dictionaries behavior: recalculate total with chosen write_mode.
            total_for_scope = filtered_count
            try:
                with db_service.get_session() as session:
                    total_for_scope = term_service.count_cluster_ids_for_translation(
                        session, self.project_id, self.build_filters(), write_mode
                    )
            except Exception as e:
                logger.warning(f"Failed to recompute total_for_scope: {e}")

            # Create TranslateAllFilteredWorker for chunked translation
            logger.info(f"Starting TranslateAllFilteredWorker for {total_for_scope} term_clusters")
            progress_dialog = BatchProgressDialogV3(self, total=total_for_scope)
            progress_dialog.show()

            worker = TranslateAllFilteredWorker(
                entity_type="term_cluster",
                project_id=self.project_id,
                filters=self.build_filters(),
                provider_mode=provider_mode,
                write_mode=write_mode,
                id_fetch_chunk=200,  # Fetch 200 IDs from DB per iteration
                translation_chunk=1,  # Translate 1 item per commit (per-row semantics)
                src_lang="he",
                tgt_lang="ru",
            )

            # Connect signals
            worker.progress.connect(progress_dialog.update_progress)
            worker.stats_updated.connect(progress_dialog.update_counts)  # Direct connection
            worker.row_translated.connect(progress_dialog.add_recent_item)  # Direct connection
            worker.stage_updated.connect(progress_dialog.set_stage)  # PATCH-16-02: Stage updates
            worker.finished.connect(
                lambda result: self.on_batch_translate_finished(result, progress_dialog)
            )
            worker.error.connect(
                lambda error: self.on_batch_translate_error(error, progress_dialog)
            )
            progress_dialog.cancel_requested.connect(worker.cancel)
            progress_dialog.pause_requested.connect(worker.pause)
            progress_dialog.resume_requested.connect(worker.resume)

            # Disable translate button while worker runs
            self.batch_translate_btn.setEnabled(False)
            worker.finished.connect(lambda: self.batch_translate_btn.setEnabled(True))
            worker.error.connect(lambda: self.batch_translate_btn.setEnabled(True))

            # Start worker
            worker.start()
            self.batch_translate_worker = worker

        else:  # scope == "current_page" (original behavior)
            # Map proxy rows to source rows
            source_rows = [
                self.proxy_model.map_to_source_row(idx.row()) for idx in selected_indexes
            ]

            # Build items list
            items = []
            for source_row in source_rows:
                cluster = self.terms_model.clusters[source_row]
                items.append(
                    BatchTranslateItem(
                        entity_type="term_cluster",
                        entity_id=cluster.representative_he,
                        source_text=cluster.representative_he,
                        src_lang="he",
                        tgt_lang="ru",
                        current_translation=cluster.translation,
                        project_id=self.project_id,
                    )
                )

            # Build options
            options = BatchTranslateOptions(
                provider_mode=provider_mode,
                write_mode=write_mode,
                chunk_size=1,
            )

            # Show premium V3 progress dialog (parity with all_filtered/User Dictionaries)
            progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
            progress_dialog.show()

            # Create worker
            self.batch_translate_worker = BatchTranslateWorker(
                items=items, options=options, tab_type="terms"
            )

            # Connect signals
            self.batch_translate_worker.progress.connect(progress_dialog.update_progress)
            self.batch_translate_worker.stats_updated.connect(progress_dialog.update_counts)
            self.batch_translate_worker.row_translated.connect(progress_dialog.add_recent_item)
            self.batch_translate_worker.stage_updated.connect(progress_dialog.set_stage)
            self.batch_translate_worker.finished.connect(
                lambda result: self.on_batch_translate_finished(result, progress_dialog)
            )
            self.batch_translate_worker.error.connect(
                lambda error: self.on_batch_translate_error(error, progress_dialog)
            )
            progress_dialog.cancel_requested.connect(self.batch_translate_worker.cancel)
            progress_dialog.pause_requested.connect(self.batch_translate_worker.pause)
            progress_dialog.resume_requested.connect(self.batch_translate_worker.resume)

            self.batch_translate_btn.setEnabled(False)
            self.batch_translate_worker.finished.connect(self.on_selection_changed)
            self.batch_translate_worker.error.connect(self.on_selection_changed)

            # Start worker
            self.batch_translate_worker.start()

    def on_batch_translate_finished(self, result, progress_dialog):
        """Handle batch translate completion."""
        progress_dialog.set_completed()
        progress_dialog.update_counts(result.succeeded, result.skipped, result.failed)

        # Show summary
        msg = (
            "Translation completed.\n\n"
            f"Total: {result.total}\n"
            f"Succeeded: {result.succeeded}\n"
            f"Skipped: {result.skipped}\n"
            f"Failed: {result.failed}"
        )
        if result.failed > 0:
            show_error(self, "Translation Complete (with errors)", msg)
        else:
            show_info(self, "Translation Complete", msg)

        # Close progress dialog
        progress_dialog.accept()

        # Refresh table to show new translations
        self.refresh_current_page_after_operation()

        # Clean up worker
        if self.batch_translate_worker:
            self.batch_translate_worker.deleteLater()
            self.batch_translate_worker = None

    def on_batch_translate_error(self, error_msg: str, progress_dialog):
        """Handle batch translate error."""
        progress_dialog.reject()
        show_error(self, "Batch Translate Error", error_msg)

        # Clean up worker
        if self.batch_translate_worker:
            self.batch_translate_worker.deleteLater()
            self.batch_translate_worker = None

    def _update_last_extract_info(self, session):
        """Update label showing last extraction parameters (Migration 011)."""
        from app.infra.sa_models import DictProject

        project = session.get(DictProject, self.project_id)
        if not project:
            return

        # Check if extraction has been performed
        if project.last_extract_at:
            # Build parameter info string
            params_info = []

            if project.last_extract_include_np == 1:
                params_info.append("Include NP: Yes")
                if project.last_extract_np_max_len:
                    params_info.append(f"Max NP length: {project.last_extract_np_max_len}")
            else:
                params_info.append("Include NP: No")

            if project.last_extract_min_freq:
                params_info.append(f"Min freq: {project.last_extract_min_freq}")

            # Format timestamp
            from datetime import datetime

            try:
                extract_dt = datetime.fromisoformat(project.last_extract_at.replace("Z", "+00:00"))
                time_str = extract_dt.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = project.last_extract_at[:19]  # Fallback to first 19 chars

            info_text = f"Last extracted: {time_str} | {' | '.join(params_info)}"
            self.last_extract_label.setText(info_text)
        else:
            self.last_extract_label.setText("No terms extracted yet")

    def _format_extract_source_mix(self, report) -> str:
        snapshot_rows_used = int(getattr(report, "snapshot_rows_used", 0) or 0)
        reparsed_sentences = int(getattr(report, "reparsed_sentences", 0) or 0)
        reuse_pct = getattr(report, "snapshot_reuse_pct", None)
        if snapshot_rows_used <= 0 and reparsed_sentences <= 0:
            return ""

        reuse_text = f"{float(reuse_pct):.2f}%" if reuse_pct is not None else "n/a"
        return (
            "Last extraction source mix: "
            f"Snapshots used: {snapshot_rows_used:,} | "
            f"Reparsed: {reparsed_sentences:,} | "
            f"Reuse: {reuse_text}"
        )

    def _set_last_extract_source_mix(self, report) -> None:
        label = self.__dict__.get("last_extract_source_mix_label")
        if label is None:
            return
        text = self._format_extract_source_mix(report)
        label.setText(text)

    def eventFilter(self, obj, event):
        """Handle keyboard shortcuts: Enter (edit), Ctrl+Left/Right (pagination)."""
        if obj == self.terms_table and event.type() == event.Type.KeyPress:
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
                    current_index = self.terms_table.currentIndex()
                    if current_index.isValid():
                        # Map proxy index to source
                        source_index = self.proxy_model.mapToSource(current_index)
                        # Get Translation column (12) in source model
                        translation_source_index = self.terms_model.index(source_index.row(), 12)
                        # Map back to proxy
                        translation_proxy_index = self.proxy_model.mapFromSource(
                            translation_source_index
                        )
                        # Set current and edit
                        self.terms_table.setCurrentIndex(translation_proxy_index)
                        self.terms_table.edit(translation_proxy_index)
                        return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        """Handle widget close - ensure workers are stopped."""
        # Stop batch translate worker
        if self.batch_translate_worker and self.batch_translate_worker.isRunning():
            logger.info("Stopping batch translate worker on close")
            self.batch_translate_worker.cancel()
            self.batch_translate_worker.quit()
            self.batch_translate_worker.wait(1000)
            if self.batch_translate_worker.isRunning():
                self.batch_translate_worker.terminate()

        if self.batch_audio_worker and self.batch_audio_worker.isRunning():
            logger.info("Stopping batch audio worker on close")
            self.batch_audio_worker.cancel()
            self.batch_audio_worker.quit()
            self.batch_audio_worker.wait(1000)
            if self.batch_audio_worker.isRunning():
                self.batch_audio_worker.terminate()

        # M7 P1: Stop translation worker
        if self.translation_worker and self.translation_worker.isRunning():
            logger.info("Stopping translation worker on close")
            self.translation_worker.cancel()
            if not self.translation_worker.wait(100):
                logger.info("Terms translation worker will finish cooperatively after close")

        # Stop extraction worker
        self._stop_extract_worker()

        # Save header state (column order, widths, sort)
        self.table_layout_controller.save_now()

        super().closeEvent(event)
