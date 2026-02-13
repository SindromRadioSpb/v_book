"""Terms view - MWE extraction and clustering (M5+)."""
import logging
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableView, QLabel, QSpinBox,
    QComboBox, QLineEdit, QHeaderView, QProgressBar, QCheckBox, QMenu
)
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtGui import QAction

from app.infra.settings import SettingsService
from app.services.term_extraction_service import TermExtractionService
from app.services.translation_service import TranslationService
from app.ui.dialogs import show_error, show_info, WhyTranslationDialog
from app.ui.dialogs import show_batch_translate_dialog, BatchProgressDialog
from app.ui.models_qt import TermClusterTableModel
from app.ui.multi_sort_proxy import MultiSortProxyModel
from app.ui.workers import TranslationResolveWorker, BatchTranslateWorker, TermsSearchWorker
from app.services.db_service import DBService
from app.services.batch_mt_translate_service import BatchTranslateItem, BatchTranslateOptions

logger = logging.getLogger(__name__)


class TermsView(QWidget):
    """Terms view showing extracted MWEs and clusters (M5)."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.term_service = TermExtractionService()
        self.db_service = DBService.get_instance()
        self.translation_service = TranslationService()
        self.settings = SettingsService.get_instance()
        self.extract_worker = None
        self.translation_worker: Optional[TranslationResolveWorker] = None
        self.batch_translate_worker: Optional[BatchTranslateWorker] = None

        # Pagination state
        self.current_page = 1
        self.page_size = self.settings.get_int("terms_view/page_size", 100)
        self.total_count = 0
        self.search_worker = None  # Track worker for cancellation

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
        self.include_np_checkbox.setChecked(True)
        extract_controls_layout.addWidget(self.include_np_checkbox)

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

        extract_controls_layout.addStretch()
        layout.addLayout(extract_controls_layout)

        # Migration 011: Last extraction parameters info
        self.last_extract_label = QLabel("")
        self.last_extract_label.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        layout.addWidget(self.last_extract_label)

        # Filters
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["All", "N-grams", "NP"])
        self.source_combo.currentTextChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.source_combo)

        filter_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["freq", "strong", "balanced", "termhood"])
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

        # Terms table with proxy model for sorting (M7 P1: converted to QTableView + TermClusterTableModel)
        self.terms_model = TermClusterTableModel()
        self.proxy_model = MultiSortProxyModel()
        self.proxy_model.setSourceModel(self.terms_model)

        self.terms_table = QTableView()
        self.terms_table.setModel(self.proxy_model)  # Use proxy model
        self.terms_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.terms_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)  # Bulk selection
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

        header = self.terms_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Term
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Lemma
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)  # Translation
        header.setSectionsMovable(True)  # Enable column reorder

        # Restore header state
        self.settings.restore_header_state("terms_view", header)

        # M7 P1: Connect dataChanged to save handler
        self.terms_model.dataChanged.connect(self.on_translation_edited)

        layout.addWidget(self.terms_table)

        # Pagination bar
        pagination_layout = QHBoxLayout()

        # First/Prev buttons
        self.first_btn = QPushButton("«")
        self.first_btn.setToolTip("First page")
        self.first_btn.setMaximumWidth(40)
        self.first_btn.clicked.connect(self.on_first_page)
        pagination_layout.addWidget(self.first_btn)

        self.prev_btn = QPushButton("‹")
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
        self.next_btn = QPushButton("›")
        self.next_btn.setToolTip("Next page (Ctrl+Right)")
        self.next_btn.setMaximumWidth(40)
        self.next_btn.clicked.connect(self.on_next_page)
        pagination_layout.addWidget(self.next_btn)

        self.last_btn = QPushButton("»")
        self.last_btn.setToolTip("Last page")
        self.last_btn.setMaximumWidth(40)
        self.last_btn.clicked.connect(self.on_last_page)
        pagination_layout.addWidget(self.last_btn)

        pagination_layout.addSpacing(20)

        # Range label
        self.range_label = QLabel("Showing 0–0 of 0")
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
                        self.term_service.set_reference_project(session, self.project_id, default_ref_id)
                        current_ref = default_ref_id
                        logger.info(f"Auto-assigned default reference corpus (ID: {default_ref_id}) to project {self.project_id}")

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

        except Exception as e:
            logger.exception("Failed to load reference projects")

    def on_reference_changed(self, index: int):
        """Handle reference project selection change (M5.4)."""
        try:
            reference_id = self.reference_combo.currentData()

            with self.db_service.get_session() as session:
                self.term_service.set_reference_project(
                    session,
                    self.project_id,
                    reference_id
                )

            # Refresh terms table
            self.current_page = 1
            self.perform_search()

        except Exception as e:
            logger.exception("Failed to set reference project")
            show_error(self, "Error", f"Failed to set reference project: {e}")

    def on_np_max_len_changed(self):
        """Handle Max NP length change - save setting (no reload needed, used only during extraction)."""
        self.settings.set_value("terms_view/np_max_len", self.np_max_len_spin.value())

    def on_min_freq_changed(self):
        """Handle Min freq change - save setting (no reload needed, used only during extraction)."""
        self.settings.set_value("terms_view/min_freq", self.min_freq_spin.value())

    def build_filters(self) -> dict:
        """Build filters dict for search."""
        return {
            "search": self.search_edit.text().strip(),
            "preset": self.preset_combo.currentText().lower(),
            "source_filter": self._get_source_filter(),
            "min_freq": self.min_freq_spin.value() if self.min_freq_spin.value() > 1 else None,
            "hide_noise": self.hide_noise_checkbox.isChecked(),
        }

    def _get_source_filter(self) -> Optional[str]:
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
        self.perform_search()

    def perform_search(self):
        """Perform search with current filters and pagination."""
        # Cancel previous worker if running
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.quit()
            self.search_worker.wait(1000)

        # Build filters
        filters = self.build_filters()

        # Create and start worker
        self.search_worker = TermsSearchWorker(
            project_id=self.project_id,
            filters=filters,
            limit=self.page_size,
            offset=self.current_offset,
        )

        self.search_worker.results_ready.connect(self.on_search_results)
        self.search_worker.error.connect(self.on_search_error)
        self.search_worker.start()

        # Update status
        self.status_label.setText("Searching...")

    def on_search_results(self, clusters: list, total_count: int):
        """Handle search results from worker."""
        # Update total count
        self.total_count = total_count

        # Update model with clusters
        self.terms_model.update_clusters(clusters)

        # Update status
        if total_count == 0:
            self.status_label.setText("No term clusters found")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + len(clusters), total_count)
            self.status_label.setText(f"Showing {start}–{end} of {total_count:,} term clusters")

        # Update pagination controls
        self.update_pagination_controls()

        # Load last extraction info (only need session briefly)
        try:
            with self.db_service.get_session() as session:
                self._update_last_extract_info(session)
        except Exception as e:
            logger.exception("Failed to load last extraction info")

        # Start translation worker
        self.start_translation_worker(clusters)

        # Clean up worker
        if self.search_worker:
            self.search_worker.deleteLater()
            self.search_worker = None

    def on_search_error(self, error_msg: str):
        """Handle search error."""
        logger.error(f"Search error: {error_msg}")
        show_error(self, "Search Error", f"Failed to search term clusters: {error_msg}")
        self.status_label.setText("Search failed")

        # Clean up worker
        if self.search_worker:
            self.search_worker.deleteLater()
            self.search_worker = None

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
            self.settings.set_value("terms_view/page_size", self.page_size)
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
            self.range_label.setText("Showing 0–0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}–{end} of {self.total_count:,}")

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

    def on_extract(self):
        """Handle extract terms button."""
        from PyQt6.QtWidgets import QMessageBox
        from app.ui.workers import ProjectTermExtractionWorker

        reply = QMessageBox.question(
            self,
            "Extract Terms",
            "Extract terms (n-grams + NP chunks + clustering) for this project?\n\n"
            "This may take a few minutes for large corpora.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Get extraction parameters from UI
        include_np = self.include_np_checkbox.isChecked()
        np_max_len = self.np_max_len_spin.value()
        min_freq = self.min_freq_spin.value()

        # Disable UI during extraction (prevent QThread lifecycle issues)
        self.extract_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText("Extracting terms...")

        # Create and start worker (keep strong reference to prevent GC)
        self.extract_worker = ProjectTermExtractionWorker(
            project_id=self.project_id,
            enable_ngrams=True,
            include_np=include_np,
            min_freq=min_freq,
            ngram_ns=(2, 3),
            np_max_len=np_max_len,
            overwrite=True,
        )

        self.extract_worker.progress.connect(self.on_extract_progress)
        self.extract_worker.finished.connect(self.on_extract_finished)
        self.extract_worker.error.connect(self.on_extract_error)

        self.extract_worker.start()

    def on_extract_progress(self, message: str):
        """Handle extraction progress updates."""
        self.status_label.setText(message)

    def on_extract_finished(self, report):
        """Handle extraction completion."""
        self.progress_bar.setVisible(False)

        # Re-enable UI
        self.extract_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

        # Clean up worker properly
        if self.extract_worker:
            self.extract_worker.deleteLater()
            self.extract_worker = None

        if report.success:
            msg = f"Term extraction successful!\n\n"
            msg += f"N-grams: {report.ngrams_extracted}\n"
            msg += f"NP chunks: {report.np_chunks_extracted}\n"
            msg += f"Clusters: {report.clusters_created}"

            show_info(self, "Extraction Complete", msg)
            self.perform_search()
        else:
            show_error(self, "Extraction Failed", report.error_message)

    def on_extract_error(self, error_msg: str):
        """Handle extraction error."""
        self.progress_bar.setVisible(False)

        # Re-enable UI
        self.extract_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

        # Clean up worker properly
        if self.extract_worker:
            self.extract_worker.deleteLater()
            self.extract_worker = None

        show_error(self, "Error", error_msg)

    def start_translation_worker(self, clusters: list):
        """M7 P1: Start worker to resolve translations for term clusters."""
        if not clusters:
            return

        # Cancel previous worker if running
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.quit()
            self.translation_worker.wait(1000)

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

        self.translation_worker.results_ready.connect(self.on_translation_results)
        self.translation_worker.error.connect(self.on_translation_error)
        self.translation_worker.start()

        logger.info(f"Started translation worker for {len(items)} term clusters")

    def on_translation_results(self, results: dict):
        """M7 P1: Handle translation results from worker."""
        logger.info(f"Received {len(results)} translation results")

        # Update model with results
        self.terms_model.update_translations(results)

        # Clean up worker
        if self.translation_worker:
            self.translation_worker.deleteLater()
            self.translation_worker = None

    def on_translation_error(self, error_msg: str):
        """M7 P1: Handle translation worker error."""
        logger.error(f"Translation worker error: {error_msg}")
        show_error(self, "Translation Error", f"Failed to load translations: {error_msg}")

        # Clean up worker
        if self.translation_worker:
            self.translation_worker.deleteLater()
            self.translation_worker = None

    def on_translation_edited(self, top_left: QModelIndex, bottom_right: QModelIndex, roles):
        """M7 P1: Handle inline edit of translation - save to TM."""
        # Check if Translation column was edited (col 11)
        if top_left.column() != 11:
            return

        row = top_left.row()
        cluster = self.terms_model.clusters[row]

        # Get new translation value
        new_translation = cluster.translation

        # Allow empty translations (user can delete translation)
        try:
            with self.db_service.get_session() as session:
                # Save to TM
                from app.infra.sa_models import TMEntry, TermCluster
                from datetime import datetime
                from sqlalchemy import select

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
                    existing.status = "approved"  # User edit → approved
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
                        status="approved",  # User edit → approved
                        origin="user_edit",
                        source_ref="terms_view_inline_edit",
                        cluster_id=cluster.cluster_id,  # Link to source for is_noise sync
                        is_noise=cluster.is_noise if cluster.is_noise is not None else 0,
                        noise_reason=cluster.noise_reason,
                    )
                    session.add(tm_entry)

                session.commit()

                # Update status in model to "approved"
                cluster.translation_status = "approved"
                status_idx = self.terms_model.index(row, 13)  # Status column
                self.terms_model.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

                logger.info(f"Saved TM entry for term: {cluster.representative_he} -> {translation_value}")

        except Exception as e:
            logger.exception("Failed to save TM entry")
            show_error(self, "Save Error", f"Failed to save translation: {e}")

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

        # "Why?" action - show explainability
        why_action = QAction("Why this translation?", self)
        why_action.triggered.connect(lambda: self.show_why_dialog(source_row))
        menu.addAction(why_action)

        # Batch translate action
        selected_rows = self.terms_table.selectionModel().selectedRows()
        if len(selected_rows) > 1:
            menu.addSeparator()
            batch_action = QAction(f"Translate {len(selected_rows)} selected rows...", self)
            batch_action.triggered.connect(self.on_batch_translate)
            menu.addAction(batch_action)

        # Task 11: Manual noise override actions
        menu.addSeparator()

        # Check if multiple rows selected
        if len(selected_rows) > 1:
            # Bulk operations
            mark_valid_bulk_action = QAction(f"✓ Mark Selected as Valid ({len(selected_rows)} rows)", self)
            mark_valid_bulk_action.triggered.connect(lambda: self.set_clusters_noise_status_bulk(False))
            menu.addAction(mark_valid_bulk_action)

            mark_noise_bulk_action = QAction(f"✗ Mark Selected as Noise ({len(selected_rows)} rows)", self)
            mark_noise_bulk_action.triggered.connect(lambda: self.set_clusters_noise_status_bulk(True))
            menu.addAction(mark_noise_bulk_action)
        else:
            # Single row operation
            current_is_noise = cluster.is_noise == 1 if cluster.is_noise is not None else False

            if current_is_noise:
                mark_valid_action = QAction("✓ Mark as Valid (remove from noise)", self)
                mark_valid_action.triggered.connect(lambda: self.set_cluster_noise_status(source_row, False))
                menu.addAction(mark_valid_action)
            else:
                mark_noise_action = QAction("✗ Mark as Noise", self)
                mark_noise_action.triggered.connect(lambda: self.set_cluster_noise_status(source_row, True))
                menu.addAction(mark_noise_action)

        # Show menu
        menu.exec(self.terms_table.viewport().mapToGlobal(pos))

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
                stmt = update(TermCluster).where(
                    TermCluster.cluster_id == cluster.cluster_id
                ).values(
                    is_noise=1 if is_noise else 0
                )
                session.execute(stmt)
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
                'Confirm Bulk Action',
                f'You are about to mark {count:,} term clusters as {status_text}.\n\n'
                f'This operation cannot be undone easily.\n\n'
                f'Continue?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No  # Default to No for safety
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
                stmt = update(TermCluster).where(
                    TermCluster.cluster_id.in_(cluster_ids)
                ).values(
                    is_noise=1 if is_noise else 0
                )
                result = session.execute(stmt)
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
            self
        )
        self.bulk_progress_dialog.setWindowTitle("Bulk Update")
        self.bulk_progress_dialog.setModal(True)
        self.bulk_progress_dialog.setMinimumDuration(0)
        self.bulk_progress_dialog.show()

        # Store source_rows for later model update
        self._pending_source_rows = source_rows
        self._pending_is_noise = is_noise

        # Create and start worker
        self.bulk_worker = BulkNoiseUpdateWorker(
            model_class="TermCluster",
            item_ids=cluster_ids,
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
                f"Updated {current:,} of {total:,} term clusters..."
            )

    def _on_bulk_complete(self, count: int):
        """Handle bulk update completion."""
        # Close progress dialog
        if hasattr(self, 'bulk_progress_dialog') and self.bulk_progress_dialog:
            self.bulk_progress_dialog.close()
            self.bulk_progress_dialog = None

        # Update local model for all affected rows
        for source_row in self._pending_source_rows:
            self.terms_model.clusters[source_row].is_noise = 1 if self._pending_is_noise else 0

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
        """Enable/disable batch translate button based on selection."""
        selected_rows = self.terms_table.selectionModel().selectedRows()
        self.batch_translate_btn.setEnabled(len(selected_rows) > 0)

    def on_batch_translate(self):
        """Task 15: Handle batch translate with scope support."""
        from PyQt6.QtWidgets import QMessageBox
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import TranslateAllFilteredWorker
        from app.services.db_service import DBService
        from app.services.term_extraction_service import TermExtractionService

        selected_indexes = self.terms_table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        # Task 15: Compute filtered count for "All pages" scope
        filtered_count = 0
        try:
            db_service = DBService.get_instance()
            term_service = TermExtractionService()
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
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Create TranslateAllFilteredWorker for chunked translation
            logger.info(f"Starting TranslateAllFilteredWorker for {filtered_count} term_clusters")
            progress_dialog = BatchProgressDialogV3(self, total=filtered_count)
            progress_dialog.show()

            worker = TranslateAllFilteredWorker(
                entity_type="term_cluster",
                project_id=self.project_id,
                filters=self.build_filters(),
                provider_mode=provider_mode,
                write_mode=write_mode,
                id_fetch_chunk=200,      # Fetch 200 IDs from DB per iteration
                translation_chunk=25,     # Translate 25 items before commit (dynamic UX)
                src_lang="he",
                tgt_lang="ru",
            )

            # Connect signals
            worker.progress.connect(progress_dialog.update_progress)
            worker.stats_updated.connect(progress_dialog.update_counts)  # Direct connection
            worker.row_translated.connect(progress_dialog.add_recent_item)  # Direct connection
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
            self.batch_translate_worker = worker

        else:  # scope == "current_page" (original behavior)
            # Map proxy rows to source rows
            source_rows = [self.proxy_model.map_to_source_row(idx.row()) for idx in selected_indexes]

            # Build items list
            items = []
            for source_row in source_rows:
                cluster = self.terms_model.clusters[source_row]
                items.append(BatchTranslateItem(
                    entity_type="term_cluster",
                    entity_id=cluster.representative_he,
                    source_text=cluster.representative_he,
                    src_lang="he",
                    tgt_lang="ru",
                    current_translation=cluster.translation,
                    project_id=self.project_id,
                ))

            # Build options
            options = BatchTranslateOptions(
                provider_mode=provider_mode,
                write_mode=write_mode,
                chunk_size=50,
            )

            # Show progress dialog
            progress_dialog = BatchProgressDialog(self, total=len(items))
            progress_dialog.show()

            # Create worker
            self.batch_translate_worker = BatchTranslateWorker(
                items=items,
                options=options,
                tab_type="terms"
            )

            # Connect signals
            self.batch_translate_worker.progress.connect(progress_dialog.update_progress)
            self.batch_translate_worker.row_completed.connect(
                lambda entity_id, success: progress_dialog.update_counts(
                    self.batch_translate_worker.succeeded,
                    self.batch_translate_worker.skipped,
                    self.batch_translate_worker.failed
                )
            )
            self.batch_translate_worker.finished.connect(
                lambda result: self.on_batch_translate_finished(result, progress_dialog)
            )
            self.batch_translate_worker.error.connect(
                lambda error: self.on_batch_translate_error(error, progress_dialog)
            )
            progress_dialog.cancel_requested.connect(self.batch_translate_worker.cancel)

            # Start worker
            self.batch_translate_worker.start()

    def on_batch_translate_finished(self, result, progress_dialog: BatchProgressDialog):
        """Handle batch translate completion."""
        progress_dialog.set_completed()

        # Show summary
        msg = f"Batch translation complete!\n\n"
        msg += f"Total: {result.total}\n"
        msg += f"Succeeded: {result.succeeded}\n"
        msg += f"Skipped: {result.skipped}\n"
        msg += f"Failed: {result.failed}"

        show_info(self, "Batch Translate Complete", msg)

        # Close progress dialog
        progress_dialog.accept()

        # Refresh table to show new translations
        self.perform_search()

        # Clean up worker
        if self.batch_translate_worker:
            self.batch_translate_worker.deleteLater()
            self.batch_translate_worker = None

    def on_batch_translate_error(self, error_msg: str, progress_dialog: BatchProgressDialog):
        """Handle batch translate error."""
        progress_dialog.close()
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
                extract_dt = datetime.fromisoformat(project.last_extract_at.replace('Z', '+00:00'))
                time_str = extract_dt.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = project.last_extract_at[:19]  # Fallback to first 19 chars

            info_text = f"Last extracted: {time_str} | {' | '.join(params_info)}"
            self.last_extract_label.setText(info_text)
        else:
            self.last_extract_label.setText("No terms extracted yet")

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
                        # Get Translation column (11) in source model
                        translation_source_index = self.terms_model.index(source_index.row(), 11)
                        # Map back to proxy
                        translation_proxy_index = self.proxy_model.mapFromSource(translation_source_index)
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

        # M7 P1: Stop translation worker
        if self.translation_worker and self.translation_worker.isRunning():
            logger.info("Stopping translation worker on close")
            self.translation_worker.quit()
            self.translation_worker.wait(1000)
            if self.translation_worker.isRunning():
                self.translation_worker.terminate()

        # Stop extraction worker
        if self.extract_worker and self.extract_worker.isRunning():
            logger.info("Stopping term extraction worker on close")
            self.extract_worker.quit()
            self.extract_worker.wait(1000)  # Wait up to 1 second
            if self.extract_worker.isRunning():
                self.extract_worker.terminate()

        # Save header state (column order, widths, sort)
        self.settings.save_header_state("terms_view", self.terms_table.horizontalHeader())

        super().closeEvent(event)
