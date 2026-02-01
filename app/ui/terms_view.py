"""Terms view - MWE extraction and clustering (M5+)."""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QSpinBox,
    QComboBox, QLineEdit, QHeaderView, QProgressBar
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

        extract_btn = QPushButton("Extract Terms")
        extract_btn.clicked.connect(self.on_extract)
        header_layout.addWidget(extract_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_terms)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Filters
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Top:"))
        self.top_n_spin = QSpinBox()
        self.top_n_spin.setRange(10, 10000)
        self.top_n_spin.setValue(500)
        self.top_n_spin.valueChanged.connect(self.load_terms)
        filter_layout.addWidget(self.top_n_spin)

        filter_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["freq", "strong", "balanced"])
        self.preset_combo.currentTextChanged.connect(self.load_terms)
        filter_layout.addWidget(self.preset_combo)

        filter_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter terms...")
        self.search_edit.textChanged.connect(self.load_terms)
        filter_layout.addWidget(self.search_edit)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Terms table
        self.terms_table = QTableWidget()
        self.terms_table.setColumnCount(8)
        self.terms_table.setHorizontalHeaderLabels([
            "Term", "Lemma", "Freq", "DocFreq", "Members", "PMI", "LLR", "Dice"
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

    def load_terms(self):
        """Load and display term clusters."""
        try:
            top_n = self.top_n_spin.value()
            preset = self.preset_combo.currentText()
            search = self.search_edit.text().strip() or None

            with self.db_service.get_session() as session:
                clusters = self.term_service.list_term_clusters(
                    session,
                    self.project_id,
                    top_n=top_n,
                    preset=preset,
                    search=search
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

                self.status_label.setText(f"Showing {len(clusters)} term clusters")

        except Exception as e:
            logger.exception("Failed to load terms")
            show_error(self, "Error", f"Failed to load terms: {e}")

    def on_extract(self):
        """Handle extract terms button."""
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Extract Terms",
            "Extract terms (n-grams + clustering) for this project?\n\n"
            "This may take a few minutes for large corpora.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # For now, run synchronously (can be converted to worker later)
        try:
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)  # Indeterminate

            with self.db_service.get_session() as session:
                report = self.term_service.extract_terms_for_project(
                    session,
                    self.project_id,
                    enable_ngrams=True,
                    min_freq=2,
                    ngram_ns=(2, 3),
                    overwrite=True
                )

            self.progress_bar.setVisible(False)

            if report.success:
                show_info(
                    self,
                    "Extraction Complete",
                    f"Term extraction successful!\n\n"
                    f"N-grams: {report.ngrams_extracted}\n"
                    f"Clusters: {report.clusters_created}"
                )
                self.load_terms()
            else:
                show_error(self, "Extraction Failed", report.error_message)

        except Exception as e:
            self.progress_bar.setVisible(False)
            logger.exception("Term extraction failed")
            show_error(self, "Error", f"Term extraction failed: {e}")
