"""Terms view - MWE extraction and clustering (M5+)."""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QSpinBox,
    QComboBox, QLineEdit, QHeaderView, QProgressBar, QCheckBox
)
from PyQt6.QtCore import Qt

from app.services.term_extraction_service import TermExtractionService
from app.ui.dialogs import show_error, show_info
from app.services.db_service import DBService

logger = logging.getLogger(__name__)


class TermsView(QWidget):
    """Terms view showing extracted MWEs and clusters (M5)."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.term_service = TermExtractionService()
        self.db_service = DBService.get_instance()
        self.extract_worker = None

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

        # Terms table (M5.4: added Weirdness, Keyness, Termhood)
        self.terms_table = QTableWidget()
        self.terms_table.setColumnCount(11)
        self.terms_table.setHorizontalHeaderLabels([
            "Term", "Lemma", "Freq", "DocFreq", "Members", "PMI", "LLR", "Dice",
            "Weirdness", "Keyness", "Termhood"
        ])
        self.terms_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.terms_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        header = self.terms_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

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

                self.terms_table.setRowCount(len(clusters))

                for row, cluster in enumerate(clusters):
                    self.terms_table.setItem(row, 0, QTableWidgetItem(cluster.representative_he))
                    self.terms_table.setItem(row, 1, QTableWidgetItem(cluster.representative_lemma or ""))
                    self.terms_table.setItem(row, 2, QTableWidgetItem(str(cluster.freq_abs)))
                    self.terms_table.setItem(row, 3, QTableWidgetItem(str(cluster.doc_freq)))
                    self.terms_table.setItem(row, 4, QTableWidgetItem(str(cluster.members_count)))

                    pmi_text = f"{cluster.best_pmi:.2f}" if cluster.best_pmi else "N/A"
                    llr_text = f"{cluster.best_llr:.2f}" if cluster.best_llr else "N/A"
                    dice_text = f"{cluster.best_dice:.3f}" if cluster.best_dice else "N/A"

                    self.terms_table.setItem(row, 5, QTableWidgetItem(pmi_text))
                    self.terms_table.setItem(row, 6, QTableWidgetItem(llr_text))
                    self.terms_table.setItem(row, 7, QTableWidgetItem(dice_text))

                    # M5.4: Termhood columns
                    weirdness_text = f"{cluster.weirdness:.2f}" if cluster.weirdness else "N/A"
                    keyness_text = f"{cluster.keyness_llr:.2f}" if cluster.keyness_llr else "N/A"
                    termhood_text = f"{cluster.termhood_score:.2f}" if cluster.termhood_score else "N/A"

                    self.terms_table.setItem(row, 8, QTableWidgetItem(weirdness_text))
                    self.terms_table.setItem(row, 9, QTableWidgetItem(keyness_text))
                    self.terms_table.setItem(row, 10, QTableWidgetItem(termhood_text))

                self.status_label.setText(f"Showing {len(clusters)} term clusters")

        except Exception as e:
            logger.exception("Failed to load terms")
            show_error(self, "Error", f"Failed to load terms: {e}")

    def on_extract(self):
        """Handle extract terms button."""
        from PyQt6.QtWidgets import QMessageBox
        from app.ui.workers import TermExtractionWorker

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
        self.extract_worker = TermExtractionWorker(
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
