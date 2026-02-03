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

from app.services.term_extraction_service import TermExtractionService
from app.services.translation_service import TranslationService
from app.ui.dialogs import show_error, show_info, WhyTranslationDialog
from app.ui.models_qt import TermClusterTableModel
from app.ui.workers import TranslationResolveWorker
from app.services.db_service import DBService

logger = logging.getLogger(__name__)


class TermsView(QWidget):
    """Terms view showing extracted MWEs and clusters (M5)."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.term_service = TermExtractionService()
        self.db_service = DBService.get_instance()
        self.translation_service = TranslationService()
        self.extract_worker = None
        self.translation_worker: Optional[TranslationResolveWorker] = None

        self.init_ui()
        self.load_terms()

    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Terms (MWE + Clustering)")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.extract_btn = QPushButton("Extract Terms")
        self.extract_btn.clicked.connect(self.on_extract)
        header_layout.addWidget(self.extract_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_terms)
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
        self.np_max_len_spin.setValue(5)
        extract_controls_layout.addWidget(self.np_max_len_spin)

        extract_controls_layout.addWidget(QLabel("Min freq:"))
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(1, 100)
        self.min_freq_spin.setValue(2)
        extract_controls_layout.addWidget(self.min_freq_spin)

        extract_controls_layout.addStretch()
        layout.addLayout(extract_controls_layout)

        # Filters
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(["All", "N-grams", "NP"])
        self.source_combo.currentTextChanged.connect(self.load_terms)
        filter_layout.addWidget(self.source_combo)

        filter_layout.addWidget(QLabel("Top:"))
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(10, 10000)
        self.top_n_spin.setValue(500)
        self.top_n_spin.valueChanged.connect(self.load_terms)
        filter_layout.addWidget(self.top_n_spin)

        filter_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["freq", "strong", "balanced", "termhood"])
        self.preset_combo.currentTextChanged.connect(self.load_terms)
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
        self.search_edit.textChanged.connect(self.load_terms)
        filter_layout.addWidget(self.search_edit)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Terms table (M7 P1: converted to QTableView + TermClusterTableModel)
        self.terms_model = TermClusterTableModel()
        self.terms_table = QTableView()
        self.terms_table.setModel(self.terms_model)
        self.terms_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        # M7 P1: Enable editing for Translation column
        self.terms_table.setEditTriggers(
            QTableView.EditTrigger.DoubleClicked | QTableView.EditTrigger.EditKeyPressed
        )
        self.terms_table.setSortingEnabled(True)

        # M7 P1: Context menu for "Why?" action
        self.terms_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.terms_table.customContextMenuRequested.connect(self.on_context_menu)

        header = self.terms_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Term
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Lemma
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)  # Translation

        # M7 P1: Connect dataChanged to save handler
        self.terms_model.dataChanged.connect(self.on_translation_edited)

        layout.addWidget(self.terms_table)

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
            self.load_terms()

        except Exception as e:
            logger.exception("Failed to set reference project")
            show_error(self, "Error", f"Failed to set reference project: {e}")

    def load_terms(self):
        """Load and display term clusters."""
        try:
            top_n = self.top_n_spin.value()
            preset = self.preset_combo.currentText()
            search = self.search_edit.text().strip() or None

            # Map source combo to filter value (M5.3)
            source_text = self.source_combo.currentText()
            source_filter = None
            if source_text == "N-grams":
                source_filter = "ngram"
            elif source_text == "NP":
                source_filter = "np"

            with self.db_service.get_session() as session:
                clusters = self.term_service.list_term_clusters(
                    session,
                    self.project_id,
                    top_n=top_n,
                    preset=preset,
                    search=search,
                    source_filter=source_filter
                )

                # M7 P1: Update model with clusters
                self.terms_model.update_clusters(clusters)

                self.status_label.setText(f"Showing {len(clusters)} term clusters")

                # M7 P1: Start translation worker
                self.start_translation_worker(clusters)

        except Exception as e:
            logger.exception("Failed to load terms")
            show_error(self, "Error", f"Failed to load terms: {e}")

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
            self.load_terms()
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

        if not new_translation or not new_translation.strip():
            return  # Don't save empty translations

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

                # Check if TM entry exists
                stmt = select(TMEntry).where(
                    TMEntry.project_id == self.project_id,
                    TMEntry.kind == "term_cluster",
                    TMEntry.src_norm == src_norm,
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
                        kind="term_cluster",
                        src_lang="he",
                        tgt_lang="ru",
                        src_text=cluster.representative_he,
                        src_norm=src_norm,
                        translation=new_translation.strip(),
                        status="approved",  # User edit → approved
                        origin="user_edit",
                        source_ref="terms_view_inline_edit",
                    )
                    session.add(tm_entry)

                session.commit()

                # Update status in model to "approved"
                cluster.translation_status = "approved"
                status_idx = self.terms_model.index(row, 13)  # Status column
                self.terms_model.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

                logger.info(f"Saved TM entry for term: {cluster.representative_he} -> {new_translation.strip()}")

        except Exception as e:
            logger.exception("Failed to save TM entry")
            show_error(self, "Save Error", f"Failed to save translation: {e}")

    def on_context_menu(self, pos):
        """M7 P1: Show context menu with 'Why?' action."""
        index = self.terms_table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        cluster = self.terms_model.clusters[row]

        # Create menu
        menu = QMenu(self)

        # "Why?" action - show explainability
        why_action = QAction("Why this translation?", self)
        why_action.triggered.connect(lambda: self.show_why_dialog(row))
        menu.addAction(why_action)

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

    def closeEvent(self, event):
        """Handle widget close - ensure workers are stopped."""
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

        super().closeEvent(event)
