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
    QMenu,
)
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtGui import QAction

from app.services.db_service import DBService
from app.services.translation_service import TranslationService
from app.domain.dto import LemmaStats
from app.ui.models_qt import LemmaTableModel
from app.ui.dialogs import show_error, WhyTranslationDialog
from app.ui.workers import TranslationResolveWorker

logger = logging.getLogger(__name__)


class DictionaryView(QWidget):
    """Dictionary view showing lemmas."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()
        self.translation_service = TranslationService()
        self.translation_worker: Optional[TranslationResolveWorker] = None

        self.init_ui()
        self.load_lemmas()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header with filters
        header_layout = QHBoxLayout()

        title = QLabel("Dictionary")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Top-N filter
        header_layout.addWidget(QLabel("Show top:"))
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(10, 10000)
        self.top_n_spin.setValue(100)
        self.top_n_spin.setSingleStep(10)
        self.top_n_spin.valueChanged.connect(self.load_lemmas)
        header_layout.addWidget(self.top_n_spin)

        # POS filter
        header_layout.addWidget(QLabel("POS:"))
        self.pos_filter = QComboBox()
        self.pos_filter.addItems(["All", "NOUN", "VERB", "ADJ", "ADV", "PROPN", "NUM"])
        self.pos_filter.currentTextChanged.connect(self.load_lemmas)
        header_layout.addWidget(self.pos_filter)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_lemmas)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter lemmas...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)

        # Lemma table
        self.lemma_model = LemmaTableModel()
        self.lemma_table = QTableView()
        self.lemma_table.setModel(self.lemma_model)
        self.lemma_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        # M7 P1: Enable editing for Translation column
        self.lemma_table.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.EditKeyPressed
        )
        self.lemma_table.setSortingEnabled(True)

        # M7 P1: Context menu for "Why?" action
        self.lemma_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lemma_table.customContextMenuRequested.connect(self.on_context_menu)

        # Auto-resize columns
        header = self.lemma_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Lemma
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Translation

        # M7 P1: Connect dataChanged to save handler
        self.lemma_model.dataChanged.connect(self.on_translation_edited)

        layout.addWidget(self.lemma_table)

        # Status bar
        self.status_label = QLabel("No lemmas")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

        # Store all lemmas for filtering
        self.all_lemmas = []

    def load_lemmas(self):
        """Load lemmas from database."""
        try:
            top_n = self.top_n_spin.value()
            pos_filter = self.pos_filter.currentText()

            with self.db_service.get_session() as session:
                from sqlalchemy import select
                from app.infra.sa_models import Lemma, LemmaProjectStat

                # Build query
                stmt = select(Lemma, LemmaProjectStat).join(
                    LemmaProjectStat,
                    Lemma.lemma_id == LemmaProjectStat.lemma_id
                ).where(
                    Lemma.project_id == self.project_id
                )

                # Apply POS filter
                if pos_filter != "All":
                    stmt = stmt.where(Lemma.pos == pos_filter)

                # Order by frequency
                stmt = stmt.order_by(LemmaProjectStat.freq_abs.desc())

                # Limit
                stmt = stmt.limit(top_n)

                results = session.execute(stmt).all()

                # Convert to DTOs
                lemmas = []
                for lemma, stat in results:
                    lemma_dto = LemmaStats(
                        lemma_id=lemma.lemma_id,
                        lemma_text=lemma.lemma_text,
                        pos=lemma.pos,
                        freq_abs=stat.freq_abs,
                        doc_freq=stat.doc_freq,
                        translation=None,  # M7 will add this
                        status='auto',
                    )
                    lemmas.append(lemma_dto)

                self.all_lemmas = lemmas
                self.apply_search_filter()

                self.status_label.setText(f"Showing {len(lemmas)} lemmas")

                # M7 P1: Start translation worker
                self.start_translation_worker(lemmas)

        except Exception as e:
            logger.exception("Failed to load lemmas")
            show_error(self, "Error", f"Failed to load lemmas: {e}")

    def on_search_changed(self, text: str):
        """Handle search text change."""
        self.apply_search_filter()

    def apply_search_filter(self):
        """Apply search filter to lemmas."""
        search_text = self.search_edit.text().strip().lower()

        if not search_text:
            # Show all
            self.lemma_model.update_lemmas(self.all_lemmas)
        else:
            # Filter
            filtered = [
                lemma for lemma in self.all_lemmas
                if search_text in lemma.lemma_text.lower()
            ]
            self.lemma_model.update_lemmas(filtered)

            self.status_label.setText(
                f"Showing {len(filtered)} of {len(self.all_lemmas)} lemmas"
            )

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

        if not new_translation or not new_translation.strip():
            return  # Don't save empty translations

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

                if existing:
                    # Update existing
                    existing.translation = new_translation.strip()
                    existing.status = "approved"  # User edit → approved
                    existing.origin = "user_edit"
                    existing.updated_at = datetime.now()
                else:
                    # Create new TM entry
                    tm_entry = TMEntry(
                        project_id=self.project_id,
                        kind="lemma",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text=lemma.lemma_text,
                        src_norm=normalized.norm,
                        translation=new_translation.strip(),
                        status="approved",  # User edit → approved
                        origin="user_edit",
                        source_ref="dictionary_view_inline_edit",
                    )
                    session.add(tm_entry)

                session.commit()

                # Update status in model to "approved"
                lemma.status = "approved"
                status_idx = self.lemma_model.index(row, 6)  # Status column
                self.lemma_model.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

                logger.info(f"Saved TM entry for lemma: {lemma.lemma_text} -> {new_translation.strip()}")

        except Exception as e:
            logger.exception("Failed to save TM entry")
            show_error(self, "Save Error", f"Failed to save translation: {e}")

    def on_context_menu(self, pos):
        """M7 P1: Show context menu with 'Why?' action."""
        index = self.lemma_table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        lemma = self.lemma_model.lemmas[row]

        # Create menu
        menu = QMenu(self)

        # "Why?" action - show explainability
        why_action = QAction("Why this translation?", self)
        why_action.triggered.connect(lambda: self.show_why_dialog(row))
        menu.addAction(why_action)

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

    def closeEvent(self, event):
        """M7 P1: Clean up translation worker on close."""
        if self.translation_worker and self.translation_worker.isRunning():
            logger.info("Stopping translation worker on close")
            self.translation_worker.quit()
            self.translation_worker.wait(1000)
            if self.translation_worker.isRunning():
                self.translation_worker.terminate()

        super().closeEvent(event)

    def refresh(self):
        """Refresh lemma data from database."""
        logger.info("Refreshing dictionary view")
        self.load_lemmas()
