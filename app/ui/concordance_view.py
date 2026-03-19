"""Concordance view - KWIC search (M6)."""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.infra.security import QueryComplexityError, validate_query_complexity
from app.services.db_service import DBService
from app.ui.dialogs import show_error
from app.ui.workers import ConcordanceSearchWorker

logger = logging.getLogger(__name__)


class ConcordanceView(QWidget):
    """Concordance/KWIC search view."""

    # Signal to navigate to document (emitted on double-click)
    navigate_to_document = pyqtSignal(int, int)  # doc_id, sentence_id

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()
        self.search_worker = None
        self.current_results = []

        self.init_ui()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Concordance (KWIC Search)")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Search controls
        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Search:"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter word or phrase...")
        self.search_input.returnPressed.connect(self.on_search)
        search_layout.addWidget(self.search_input, stretch=1)

        self.phrase_checkbox = QCheckBox("Exact phrase")
        self.phrase_checkbox.setToolTip("Match exact phrase (no article normalization)")
        search_layout.addWidget(self.phrase_checkbox)

        self.normalize_checkbox = QCheckBox("Normalize")
        self.normalize_checkbox.setChecked(True)
        self.normalize_checkbox.setToolTip(
            "Find article variants (e.g., 'בית ספר' finds 'בית הספר')"
        )
        search_layout.addWidget(self.normalize_checkbox)

        search_layout.addWidget(QLabel("Limit:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 1000)
        self.limit_spin.setValue(100)
        search_layout.addWidget(self.limit_spin)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.on_search)
        search_layout.addWidget(self.search_btn)

        layout.addLayout(search_layout)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(
            ["Document", "Left Context", "Match", "Right Context", "ID"]
        )

        # Set column behavior
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        # Make table read-only and enable row selection
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # Connect double-click to navigation
        self.results_table.doubleClicked.connect(self.on_result_double_click)

        layout.addWidget(self.results_table)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("Enter a search query to begin")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def on_search(self):
        """Handle search button click or Enter key."""
        query = self.search_input.text().strip()

        if not query:
            show_error(self, "Search Error", "Please enter a search query")
            return

        # UI-layer validation: Check query complexity before starting search
        try:
            validate_query_complexity(query)
        except QueryComplexityError as e:
            # Show user-friendly error message
            error_messages = {
                "LENGTH_EXCEEDED": "Query is too long (max 500 characters).\n\nPlease shorten your search query.",
                "WILDCARD_LIMIT": "Too many wildcards (*) in query (max 5).\n\nPlease reduce the number of wildcards.",
                "OPERATOR_LIMIT": "Too many search operators (AND/OR/NOT/NEAR) in query (max 10).\n\nPlease simplify your query.",
                "PARENTHESES_DEPTH": "Query has too many nested parentheses (max 10 levels).\n\nPlease simplify the query structure.",
                "UNBALANCED_PARENTHESES": "Parentheses are not balanced.\n\nPlease check that every '(' has a matching ')'.",
            }

            error_msg = error_messages.get(
                e.reason, f"Query is too complex: {e.reason}\n\nPlease simplify your search."
            )

            show_error(self, "Query Validation Error", error_msg)
            logger.warning(f"Query validation failed: {e.reason}, query_length={len(query)}")
            return

        # Get parameters
        limit = self.limit_spin.value()
        is_phrase = self.phrase_checkbox.isChecked()
        normalize = self.normalize_checkbox.isChecked()

        # Disable UI during search
        self.search_btn.setEnabled(False)
        self.search_input.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Searching for '{query}'...")

        # Start worker
        self.search_worker = ConcordanceSearchWorker(
            project_id=self.project_id,
            query=query,
            limit=limit,
            offset=0,
            is_phrase=is_phrase,
            normalize=normalize,
        )

        self.search_worker.results_ready.connect(self.on_search_results)
        self.search_worker.error.connect(self.on_search_error)
        self.search_worker.finished.connect(self.on_worker_finished)

        self.search_worker.start()

    def on_search_results(self, results):
        """Handle search results from worker."""
        self.current_results = results

        # Clear table
        self.results_table.setRowCount(0)

        # Populate table
        self.results_table.setRowCount(len(results))

        for row, result in enumerate(results):
            # Document name
            self.results_table.setItem(row, 0, QTableWidgetItem(result.doc_name))

            # Left context
            self.results_table.setItem(row, 1, QTableWidgetItem(result.left_context))

            # Match (highlighted)
            match_item = QTableWidgetItem(result.match)
            match_item.setBackground(Qt.GlobalColor.yellow)
            self.results_table.setItem(row, 2, match_item)

            # Right context
            self.results_table.setItem(row, 3, QTableWidgetItem(result.right_context))

            # Sentence ID
            self.results_table.setItem(row, 4, QTableWidgetItem(str(result.sentence_id)))

        # Update status
        if results:
            self.status_label.setText(f"Found {len(results)} results")
        else:
            self.status_label.setText("No results found")

    def on_search_error(self, error_msg: str):
        """Handle search error from worker."""
        logger.error(f"Concordance search error: {error_msg}")
        show_error(self, "Search Error", error_msg)
        self.status_label.setText("Search failed")

    def on_worker_finished(self):
        """Handle worker completion (cleanup)."""
        # Re-enable UI
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self.progress_bar.setVisible(False)

        # Clean up worker
        if self.search_worker:
            self.search_worker.deleteLater()
            self.search_worker = None

    def on_result_double_click(self, index):
        """Handle double-click on result row to navigate to document."""
        row = index.row()

        if 0 <= row < len(self.current_results):
            result = self.current_results[row]

            # Emit signal to navigate to document
            logger.info(f"Navigating to doc_id={result.doc_id}, sentence_id={result.sentence_id}")
            self.navigate_to_document.emit(result.doc_id, result.sentence_id)

    def closeEvent(self, event):
        """Handle widget close - ensure worker is stopped."""
        if self.search_worker and self.search_worker.isRunning():
            logger.info("Stopping concordance search worker on close")
            self.search_worker.quit()
            self.search_worker.wait(1000)  # Wait up to 1 second
            if self.search_worker.isRunning():
                self.search_worker.terminate()

        super().closeEvent(event)
