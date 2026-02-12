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
    QHeaderView,
    QComboBox,
    QCheckBox,
    QMenu,
)
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtGui import QAction

from app.infra.settings import SettingsService
from app.services.db_service import DBService
from app.services.translation_service import TranslationService
from app.domain.dto import LemmaStats
from app.ui.models_qt import LemmaTableModel
from app.ui.multi_sort_proxy import MultiSortProxyModel
from app.ui.dialogs import show_error, WhyTranslationDialog
from app.ui.workers import TranslationResolveWorker, DictionarySearchWorker

logger = logging.getLogger(__name__)


class DictionaryView(QWidget):
    """Dictionary view showing lemmas."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()
        self.translation_service = TranslationService()
        self.translation_worker: Optional[TranslationResolveWorker] = None
        self.settings = SettingsService.get_instance()

        # Pagination state
        self.current_page = 1
        self.page_size = self.settings.get_int("dictionary_view/page_size", 100)
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
        self.pos_filter = QComboBox()
        self.pos_filter.addItems(["All", "NOUN", "VERB", "ADJ", "ADV", "PROPN", "NUM"])
        self.pos_filter.currentTextChanged.connect(self.on_filter_changed)
        header_layout.addWidget(self.pos_filter)

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

        layout.addLayout(header_layout)

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
        self.lemma_table.setSortingEnabled(True)

        # Install event filter for Enter key editing and keyboard shortcuts
        self.lemma_table.installEventFilter(self)

        # M7 P1: Context menu for "Why?" action
        self.lemma_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lemma_table.customContextMenuRequested.connect(self.on_context_menu)

        # Auto-resize columns
        header = self.lemma_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Lemma
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Translation
        header.setSectionsMovable(True)  # Enable column reorder

        # Restore header state
        self.settings.restore_header_state("dictionary_view", header)

        # M7 P1: Connect dataChanged to save handler
        self.lemma_model.dataChanged.connect(self.on_translation_edited)

        # PATCH-UI-BATCH-T02: Connect selection changed to update button state
        self.lemma_table.selectionModel().selectionChanged.connect(self.on_selection_changed)

        layout.addWidget(self.lemma_table)

        # Status bar
        self.status_label = QLabel("No lemmas")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def build_filters(self) -> dict:
        """Build filters dict for search."""
        return {
            "pos": self.pos_filter.currentText(),
            "hide_noise": self.hide_noise_checkbox.isChecked(),
            "search": self.search_edit.text().strip(),
        }

    def on_filter_changed(self):
        """Handle filter change - reset to page 1 and search."""
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
        self.search_worker = DictionarySearchWorker(
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

    def on_search_results(self, rows: list, total_count: int):
        """Handle search results from worker."""
        # Update total count
        self.total_count = total_count

        # Convert rows to LemmaStats DTOs
        lemmas = []
        for row in rows:
            lemma_dto = LemmaStats(
                lemma_id=row["lemma_id"],
                lemma_text=row["lemma_text"],
                pos=row["pos"],
                freq_abs=row["freq_abs"],
                doc_freq=row["doc_freq"],
                translation=None,  # Will be filled by TranslationResolveWorker
                status='auto',
                entity_class=row.get("entity_class"),
                is_noise=row.get("is_noise"),
                noise_reason=row.get("noise_reason"),
                norm_text=row.get("norm_text"),
            )
            lemmas.append(lemma_dto)

        # Update model
        self.lemma_model.update_lemmas(lemmas)

        # Update status
        if total_count == 0:
            self.status_label.setText("No lemmas found")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + len(lemmas), total_count)
            self.status_label.setText(f"Showing {start}–{end} of {total_count:,} lemmas")

        # Update pagination controls
        self.update_pagination_controls()

        # Start translation worker
        self.start_translation_worker(lemmas)

        # Clean up worker
        if self.search_worker:
            self.search_worker.deleteLater()
            self.search_worker = None

    def on_search_error(self, error_msg: str):
        """Handle search error."""
        logger.error(f"Search error: {error_msg}")
        show_error(self, "Search Error", f"Failed to search lemmas: {error_msg}")
        self.status_label.setText("Search failed")

        # Clean up worker
        if self.search_worker:
            self.search_worker.deleteLater()
            self.search_worker = None

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
        """Handle page size change."""
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
            self.range_label.setText("Showing 0–0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}–{end} of {self.total_count:,}")

    def start_translation_worker(self, lemmas: List[LemmaStats]):
        """M7 P1: Start worker to resolve translations."""
        if not lemmas:
            return

        # Cancel previous worker if running
        if self.translation_worker and self.translation_worker.isRunning():
            self.translation_worker.quit()
            self.translation_worker.wait(1000)

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

        self.translation_worker.results_ready.connect(self.on_translation_results)
        self.translation_worker.error.connect(self.on_translation_error)
        self.translation_worker.start()

        logger.info(f"Started translation worker for {len(items)} lemmas")

    def on_translation_results(self, results: dict):
        """M7 P1: Handle translation results from worker."""
        logger.info(f"Received {len(results)} translation results")

        # Update model with results
        self.lemma_model.update_translations(results)

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
        # Check if Translation column was edited (col 4)
        if top_left.column() != 4:
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
                    existing.status = "approved"  # User edit → approved
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
                        status="approved",  # User edit → approved
                        origin="user_edit",
                        source_ref="dictionary_view_inline_edit",
                        lemma_id=lemma.lemma_id,  # Link to source for is_noise sync
                        is_noise=lemma.is_noise if lemma.is_noise is not None else 0,
                        noise_reason=lemma.noise_reason,
                    )
                    session.add(tm_entry)

                session.commit()

                # Update status in model to "approved"
                lemma.status = "approved"
                status_idx = self.lemma_model.index(row, 6)  # Status column
                self.lemma_model.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

                logger.info(f"Saved TM entry for lemma: {lemma.lemma_text} -> {translation_value}")

        except Exception as e:
            logger.exception("Failed to save TM entry")
            show_error(self, "Save Error", f"Failed to save translation: {e}")

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
            mark_valid_bulk_action = QAction(f"✓ Mark Selected as Valid ({len(selected_rows)} rows)", self)
            mark_valid_bulk_action.triggered.connect(lambda: self.set_lemmas_noise_status_bulk(False))
            menu.addAction(mark_valid_bulk_action)

            mark_noise_bulk_action = QAction(f"✗ Mark Selected as Noise ({len(selected_rows)} rows)", self)
            mark_noise_bulk_action.triggered.connect(lambda: self.set_lemmas_noise_status_bulk(True))
            menu.addAction(mark_noise_bulk_action)
        else:
            # Single row operation
            current_is_noise = lemma.is_noise == 1 if lemma.is_noise is not None else False

            if current_is_noise:
                mark_valid_action = QAction("✓ Mark as Valid (remove from noise)", self)
                mark_valid_action.triggered.connect(lambda: self.set_lemma_noise_status(source_row, False))
                menu.addAction(mark_valid_action)
            else:
                mark_noise_action = QAction("✗ Mark as Noise", self)
                mark_noise_action.triggered.connect(lambda: self.set_lemma_noise_status(source_row, True))
                menu.addAction(mark_noise_action)

        # Show menu
        menu.exec(self.lemma_table.viewport().mapToGlobal(pos))

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
                result = session.execute(stmt)
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
        self.batch_translate_btn.setEnabled(len(selected_rows) > 0)

    def on_batch_translate(self):
        """PATCH-UI-BATCH-T02: Handle batch translate action."""
        from PyQt6.QtWidgets import QMessageBox
        from app.ui.dialogs import show_batch_translate_dialog, BatchProgressDialog
        from app.ui.workers import BatchTranslateWorker
        from app.services.batch_mt_translate_service import (
            BatchTranslateItem,
            BatchTranslateOptions,
        )

        # Get selected rows
        selected_indexes = self.lemma_table.selectionModel().selectedRows()
        if not selected_indexes:
            return

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
                src_lang="he",  # Hardcoded for Hebrew
                tgt_lang="ru",  # Hardcoded for Russian
                current_translation=lemma.translation,
                project_id=self.project_id,
            )
            items.append(item)

        # Show confirm dialog
        accepted, provider_mode, write_mode = show_batch_translate_dialog(
            parent=self,
            selected_count=len(items),
        )

        if not accepted:
            return

        # Create options
        options = BatchTranslateOptions(
            provider_mode=provider_mode,
            write_mode=write_mode,
            chunk_size=50,
            stop_on_error=False,
        )

        # Show progress dialog
        progress_dialog = BatchProgressDialog(parent=self, total=len(items))
        progress_dialog.show()

        # Create worker
        worker = BatchTranslateWorker(
            items=items,
            options=options,
            tab_type="dictionary",
        )

        # Connect signals
        worker.progress.connect(progress_dialog.update_progress)
        worker.finished.connect(lambda result: self.on_batch_translate_finished(result, progress_dialog))
        worker.error.connect(lambda error: self.on_batch_translate_error(error, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)

        # Start worker
        worker.start()

        # Keep reference to prevent GC
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

        # Clean up worker
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

        # Clean up worker
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
                        # Start editing Translation column (column 4 in source model)
                        # Map proxy index to source index
                        source_index = self.proxy_model.mapToSource(current_index)
                        # Create translation column index in source model
                        translation_source_index = self.lemma_model.index(source_index.row(), 4)
                        # Map back to proxy
                        translation_proxy_index = self.proxy_model.mapFromSource(translation_source_index)
                        self.lemma_table.setCurrentIndex(translation_proxy_index)
                        self.lemma_table.edit(translation_proxy_index)
                        return True  # Event handled

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        """M7 P1: Clean up translation worker on close."""
        if self.translation_worker and self.translation_worker.isRunning():
            logger.info("Stopping translation worker on close")
            self.translation_worker.quit()
            self.translation_worker.wait(1000)
            if self.translation_worker.isRunning():
                self.translation_worker.terminate()

        # Save header state (column order, widths, sort)
        self.settings.save_header_state("dictionary_view", self.lemma_table.horizontalHeader())

        super().closeEvent(event)

    def refresh(self):
        """Refresh lemma data from database."""
        logger.info("Refreshing dictionary view")
        self.perform_search()
