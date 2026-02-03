"""P2 QA/Coverage Panel - Premium UI for translation coverage metrics.

Displays:
- Lemma coverage percentage
- Term cluster coverage percentage
- Untranslated items ranked by frequency/termhood
"""

import logging
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QProgressBar,
    QComboBox,
    QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from app.services.db_service import DBService
from app.ui.workers import CoverageWorker
from app.domain.dto import CoverageMetrics, LemmaCoverageRow, TermClusterCoverageRow

logger = logging.getLogger(__name__)


class CoveragePanel(QWidget):
    """P2 Coverage Panel."""

    back_requested = pyqtSignal()

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.worker: Optional[CoverageWorker] = None
        self.init_ui()
        self.load_coverage()

    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("QA / Coverage")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.on_back)
        header_layout.addWidget(back_btn)

        layout.addLayout(header_layout)

        # Options
        options_layout = QHBoxLayout()
        self.include_draft_check = QCheckBox("Include Draft TM in Coverage")
        self.include_draft_check.setChecked(False)
        self.include_draft_check.stateChanged.connect(self.on_options_changed)
        options_layout.addWidget(self.include_draft_check)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.load_coverage)
        options_layout.addWidget(refresh_btn)

        self.cancel_btn = QPushButton("✕ Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.on_cancel_coverage)
        options_layout.addWidget(self.cancel_btn)

        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Coverage Metrics
        metrics_group = QGroupBox("Coverage Metrics")
        metrics_layout = QHBoxLayout()

        # Lemma coverage
        lemma_box = QVBoxLayout()
        lemma_box.addWidget(QLabel("Lemma Coverage"))

        self.lemma_pct_label = QLabel("0%")
        self.lemma_pct_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #2196f3;")
        self.lemma_pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lemma_box.addWidget(self.lemma_pct_label)

        self.lemma_progress = QProgressBar()
        self.lemma_progress.setRange(0, 100)
        self.lemma_progress.setValue(0)
        lemma_box.addWidget(self.lemma_progress)

        self.lemma_detail_label = QLabel("0 / 0")
        self.lemma_detail_label.setStyleSheet("color: #666; font-size: 11px;")
        self.lemma_detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lemma_box.addWidget(self.lemma_detail_label)

        metrics_layout.addLayout(lemma_box)

        # Separator
        metrics_layout.addSpacing(40)

        # Term cluster coverage
        cluster_box = QVBoxLayout()
        cluster_box.addWidget(QLabel("Term Cluster Coverage"))

        self.cluster_pct_label = QLabel("0%")
        self.cluster_pct_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #4caf50;")
        self.cluster_pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cluster_box.addWidget(self.cluster_pct_label)

        self.cluster_progress = QProgressBar()
        self.cluster_progress.setRange(0, 100)
        self.cluster_progress.setValue(0)
        cluster_box.addWidget(self.cluster_progress)

        self.cluster_detail_label = QLabel("0 / 0")
        self.cluster_detail_label.setStyleSheet("color: #666; font-size: 11px;")
        self.cluster_detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cluster_box.addWidget(self.cluster_detail_label)

        metrics_layout.addLayout(cluster_box)

        metrics_group.setLayout(metrics_layout)
        layout.addWidget(metrics_group)

        # Untranslated Items Tabs
        tabs = QTabWidget()

        # Lemmas tab
        lemmas_tab = QWidget()
        lemmas_layout = QVBoxLayout()

        # Controls
        lemmas_controls = QHBoxLayout()
        lemmas_controls.addWidget(QLabel("Order by:"))
        self.lemma_order_combo = QComboBox()
        self.lemma_order_combo.addItems(["freq", "alpha"])
        self.lemma_order_combo.currentTextChanged.connect(self.on_lemma_order_changed)
        lemmas_controls.addWidget(self.lemma_order_combo)
        lemmas_controls.addStretch()
        lemmas_layout.addLayout(lemmas_controls)

        # Table
        self.lemmas_table = QTableWidget()
        self.lemmas_table.setColumnCount(4)
        self.lemmas_table.setHorizontalHeaderLabels(["Lemma", "POS", "Frequency", "Doc Freq"])
        self.lemmas_table.setAlternatingRowColors(True)
        self.lemmas_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.lemmas_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lemmas_layout.addWidget(self.lemmas_table)

        lemmas_tab.setLayout(lemmas_layout)
        tabs.addTab(lemmas_tab, "Untranslated Lemmas")

        # Term clusters tab
        clusters_tab = QWidget()
        clusters_layout = QVBoxLayout()

        # Controls
        clusters_controls = QHBoxLayout()
        clusters_controls.addWidget(QLabel("Order by:"))
        self.cluster_order_combo = QComboBox()
        self.cluster_order_combo.addItems(["termhood", "freq", "alpha"])
        self.cluster_order_combo.currentTextChanged.connect(self.on_cluster_order_changed)
        clusters_controls.addWidget(self.cluster_order_combo)
        clusters_controls.addStretch()
        clusters_layout.addLayout(clusters_controls)

        # Table
        self.clusters_table = QTableWidget()
        self.clusters_table.setColumnCount(4)
        self.clusters_table.setHorizontalHeaderLabels(["Term", "Canonical", "Termhood", "Frequency"])
        self.clusters_table.setAlternatingRowColors(True)
        self.clusters_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.clusters_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        clusters_layout.addWidget(self.clusters_table)

        clusters_tab.setLayout(clusters_layout)
        tabs.addTab(clusters_tab, "Untranslated Term Clusters")

        layout.addWidget(tabs)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-size: 11px; padding: 4px;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def on_options_changed(self):
        """Handle options change."""
        self.load_coverage()

    def on_lemma_order_changed(self):
        """Handle lemma order change."""
        self.load_coverage()

    def on_cluster_order_changed(self):
        """Handle cluster order change."""
        self.load_coverage()

    def load_coverage(self):
        """Load coverage metrics and untranslated lists."""
        if self.worker and self.worker.isRunning():
            logger.warning("Coverage calculation already in progress")
            return

        self.status_label.setText("Loading coverage data...")
        self.cancel_btn.setEnabled(True)

        include_draft = self.include_draft_check.isChecked()
        lemma_order = self.lemma_order_combo.currentText()
        cluster_order = self.cluster_order_combo.currentText()

        self.worker = CoverageWorker(
            project_id=self.project_id,
            include_draft=include_draft,
            lemma_order=lemma_order,
            cluster_order=cluster_order,
        )
        self.worker.results_ready.connect(self.on_coverage_results)
        self.worker.error.connect(self.on_coverage_error)
        self.worker.finished.connect(lambda: self.cancel_btn.setEnabled(False))
        self.worker.start()

    def on_coverage_results(self, results: dict):
        """Handle coverage results."""
        # Update lemma metrics
        lemma_metrics: CoverageMetrics = results["lemma_metrics"]
        self.lemma_pct_label.setText(f"{lemma_metrics.coverage_pct:.1f}%")
        self.lemma_progress.setValue(int(lemma_metrics.coverage_pct))
        self.lemma_detail_label.setText(
            f"{lemma_metrics.covered} / {lemma_metrics.total} "
            f"({lemma_metrics.uncovered} untranslated)"
        )

        # Update cluster metrics
        cluster_metrics: CoverageMetrics = results["cluster_metrics"]
        self.cluster_pct_label.setText(f"{cluster_metrics.coverage_pct:.1f}%")
        self.cluster_progress.setValue(int(cluster_metrics.coverage_pct))
        self.cluster_detail_label.setText(
            f"{cluster_metrics.covered} / {cluster_metrics.total} "
            f"({cluster_metrics.uncovered} untranslated)"
        )

        # Update untranslated lemmas table
        lemmas: List[LemmaCoverageRow] = results["untranslated_lemmas"]
        self.lemmas_table.setRowCount(len(lemmas))
        for row_idx, lemma in enumerate(lemmas):
            self.lemmas_table.setItem(row_idx, 0, QTableWidgetItem(lemma.lemma_text))
            self.lemmas_table.setItem(row_idx, 1, QTableWidgetItem(lemma.pos or ""))
            self.lemmas_table.setItem(row_idx, 2, QTableWidgetItem(str(lemma.freq_abs)))
            self.lemmas_table.setItem(row_idx, 3, QTableWidgetItem(str(lemma.doc_freq)))

        self.lemmas_table.resizeColumnsToContents()

        # Update untranslated clusters table
        clusters: List[TermClusterCoverageRow] = results["untranslated_clusters"]
        self.clusters_table.setRowCount(len(clusters))
        for row_idx, cluster in enumerate(clusters):
            self.clusters_table.setItem(row_idx, 0, QTableWidgetItem(cluster.representative_he))
            self.clusters_table.setItem(row_idx, 1, QTableWidgetItem(cluster.canonical_key or ""))
            termhood_str = f"{cluster.termhood_score:.3f}" if cluster.termhood_score is not None else "N/A"
            self.clusters_table.setItem(row_idx, 2, QTableWidgetItem(termhood_str))
            self.clusters_table.setItem(row_idx, 3, QTableWidgetItem(str(cluster.freq_abs)))

        self.clusters_table.resizeColumnsToContents()

        self.status_label.setText("Ready")
        logger.info("Coverage data loaded successfully")

    def on_coverage_error(self, error_msg: str):
        """Handle coverage error."""
        self.status_label.setText(f"Error: {error_msg}")
        logger.error(f"Coverage error: {error_msg}")

    def on_cancel_coverage(self):
        """Cancel ongoing coverage calculation."""
        if self.worker and self.worker.isRunning():
            logger.info("Canceling coverage worker")
            self.worker.terminate()
            self.worker.wait()
            self.worker = None
            self.status_label.setText("Coverage calculation canceled")
            self.cancel_btn.setEnabled(False)

    def closeEvent(self, event):
        """Handle panel close - stop workers."""
        if self.worker and self.worker.isRunning():
            logger.info("Stopping coverage worker on panel close")
            self.worker.terminate()
            self.worker.wait()
        event.accept()

    def on_back(self):
        """Handle back button click."""
        self.back_requested.emit()
