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
from app.ui.workers import TranslationResolveWorker, BatchTranslateWorker
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

        self.batch_translate_btn = QPushButton("Translate Selected...")
        self.batch_translate_btn.clicked.connect(self.on_batch_translate)
        self.batch_translate_btn.setEnabled(False)
        header_layout.addWidget(self.batch_translate_btn)

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

        # Hide noise filter (Task 11: Entity Classification)
        self.hide_noise_checkbox = QCheckBox("Hide noise")
        self.hide_noise_checkbox.setChecked(True)  # Default: hide noise
        self.hide_noise_checkbox.setToolTip("Hide numeric, symbolic, and other noisy terms")
        self.hide_noise_checkbox.stateChanged.connect(self.load_terms)
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
                    source_filter=source_filter,
                    hide_noise=self.hide_noise_checkbox.isChecked()
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
                    # Create new TM entry
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
                    self.load_terms()

        except Exception as e:
            logger.exception(f"Failed to update noise status for cluster {cluster.cluster_id}")
            from app.ui.dialogs import show_error
            show_error(self, "Error", f"Failed to update noise status: {e}")

    def on_selection_changed(self):
        """Enable/disable batch translate button based on selection."""
        selected_rows = self.terms_table.selectionModel().selectedRows()
        self.batch_translate_btn.setEnabled(len(selected_rows) > 0)

    def on_batch_translate(self):
        """Handle batch translate selected rows."""
        selected_indexes = self.terms_table.selectionModel().selectedRows()
        if not selected_indexes:
            return

        # Map proxy rows to source rows
        source_rows = [self.proxy_model.map_to_source_row(idx.row()) for idx in selected_indexes]

        # Build items list
        items = []
        for source_row in source_rows:
            cluster = self.terms_model.clusters[source_row]
            items.append(BatchTranslateItem(
                entity_type="term_cluster",
                entity_id=cluster.representative_he,  # Use representative as ID
                source_text=cluster.representative_he,
                src_lang="he",
                tgt_lang="ru",
                current_translation=cluster.translation,  # ClusterStats uses 'translation', not 'pinned_translation'
                project_id=self.project_id,
            ))

        # Show confirm dialog
        accepted, provider_mode, write_mode = show_batch_translate_dialog(
            parent=self,
            selected_count=len(items)
        )

        if not accepted:
            return

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
            tab_type="terms"  # FIXED: parameter is tab_type, not context
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

        # Connect cancel signal
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
        self.load_terms()

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
