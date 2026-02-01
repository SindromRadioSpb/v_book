"""Dictionary view - lemmas and MWE list."""
import logging
from typing import List

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
)
from PyQt6.QtCore import Qt

from app.services.db_service import DBService
from app.domain.dto import LemmaStats
from app.ui.models_qt import LemmaTableModel
from app.ui.dialogs import show_error

logger = logging.getLogger(__name__)


class DictionaryView(QWidget):
    """Dictionary view showing lemmas."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()

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
        self.lemma_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.lemma_table.setSortingEnabled(True)

        # Auto-resize columns
        header = self.lemma_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Lemma
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Translation

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

    def refresh(self):
        """Refresh lemma data from database."""
        logger.info("Refreshing dictionary view")
        self.load_lemmas()
