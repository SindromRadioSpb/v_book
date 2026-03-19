"""P2 QA/Coverage Panel - Premium UI for translation coverage metrics.

Displays:
- Lemma coverage percentage
- Term cluster coverage percentage
- Untranslated items ranked by frequency/termhood
"""

import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.domain.dto import CoverageMetrics, LemmaCoverageRow, TermClusterCoverageRow
from app.ui.workers import CoverageWorker

logger = logging.getLogger(__name__)


class CoveragePanel(QWidget):
    """P2 Coverage Panel."""

    back_requested = pyqtSignal()

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.worker: CoverageWorker | None = None
        self._coverage_request_seq = 0
        self._active_coverage_seq = 0
        self._coverage_retry_pending = False
        self._coverage_cancel_requested = False
        self._last_lemma_metrics: CoverageMetrics | None = None
        self._last_cluster_metrics: CoverageMetrics | None = None
        self._last_untranslated_lemmas: list[LemmaCoverageRow] = []
        self._last_untranslated_clusters: list[TermClusterCoverageRow] = []
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

        self.copy_report_btn = QPushButton("Copy Report")
        self.copy_report_btn.setEnabled(False)
        self.copy_report_btn.clicked.connect(self.copy_report_to_clipboard)
        options_layout.addWidget(self.copy_report_btn)

        self.export_report_btn = QPushButton("Export Report...")
        self.export_report_btn.setEnabled(False)
        self.export_report_btn.clicked.connect(self.export_report)
        options_layout.addWidget(self.export_report_btn)

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
        self.clusters_table.setHorizontalHeaderLabels(
            ["Term", "Canonical", "Termhood", "Frequency"]
        )
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
            logger.info("Coverage calculation already in progress; queueing refresh")
            self._coverage_retry_pending = True
            self._coverage_cancel_requested = False
            self.worker.cancel()
            self.status_label.setText("Coverage refresh queued...")
            return

        self._coverage_request_seq += 1
        request_seq = self._coverage_request_seq
        self._active_coverage_seq = request_seq
        self._coverage_retry_pending = False
        self._coverage_cancel_requested = False

        self.status_label.setText("Loading coverage data...")
        self.cancel_btn.setEnabled(True)
        self._set_lemma_metrics_pending()

        include_draft = self.include_draft_check.isChecked()
        lemma_order = self.lemma_order_combo.currentText()
        cluster_order = self.cluster_order_combo.currentText()

        self.worker = CoverageWorker(
            project_id=self.project_id,
            include_draft=include_draft,
            lemma_order=lemma_order,
            cluster_order=cluster_order,
        )
        self.worker.partial_ready.connect(
            lambda results, seq=request_seq: self.on_coverage_partial_results(results, seq)
        )
        self.worker.lemma_metrics_ready.connect(
            lambda metrics, seq=request_seq: self.on_lemma_metrics_ready(metrics, seq)
        )
        self.worker.error.connect(
            lambda error_msg, seq=request_seq: self.on_coverage_error(error_msg, seq)
        )
        self.worker.finished.connect(
            lambda seq=request_seq, worker=self.worker: self._on_coverage_worker_finished(
                worker, seq
            )
        )
        self.worker.start()

    def _set_lemma_metrics_pending(self) -> None:
        self._last_lemma_metrics = None
        self.lemma_pct_label.setText("...")
        self.lemma_progress.setRange(0, 0)
        self.lemma_detail_label.setText("Counting exact coverage...")

    def _apply_lemma_metrics(self, lemma_metrics: CoverageMetrics) -> None:
        self._last_lemma_metrics = lemma_metrics
        self.lemma_progress.setRange(0, 100)
        self.lemma_pct_label.setText(f"{lemma_metrics.coverage_pct:.1f}%")
        self.lemma_progress.setValue(int(lemma_metrics.coverage_pct))
        self.lemma_detail_label.setText(
            f"{lemma_metrics.covered} / {lemma_metrics.total} "
            f"({lemma_metrics.uncovered} untranslated)"
        )

    def _apply_cluster_metrics(self, cluster_metrics: CoverageMetrics) -> None:
        self._last_cluster_metrics = cluster_metrics
        self.cluster_pct_label.setText(f"{cluster_metrics.coverage_pct:.1f}%")
        self.cluster_progress.setValue(int(cluster_metrics.coverage_pct))
        self.cluster_detail_label.setText(
            f"{cluster_metrics.covered} / {cluster_metrics.total} "
            f"({cluster_metrics.uncovered} untranslated)"
        )

    def _apply_untranslated_lemmas(self, lemmas: list[LemmaCoverageRow]) -> None:
        self._last_untranslated_lemmas = list(lemmas)
        self.lemmas_table.setRowCount(len(lemmas))
        for row_idx, lemma in enumerate(lemmas):
            self.lemmas_table.setItem(row_idx, 0, QTableWidgetItem(lemma.lemma_text))
            self.lemmas_table.setItem(row_idx, 1, QTableWidgetItem(lemma.pos or ""))
            self.lemmas_table.setItem(row_idx, 2, QTableWidgetItem(str(lemma.freq_abs)))
            self.lemmas_table.setItem(row_idx, 3, QTableWidgetItem(str(lemma.doc_freq)))

        self.lemmas_table.resizeColumnsToContents()

    def _apply_untranslated_clusters(self, clusters: list[TermClusterCoverageRow]) -> None:
        self._last_untranslated_clusters = list(clusters)
        self.clusters_table.setRowCount(len(clusters))
        for row_idx, cluster in enumerate(clusters):
            self.clusters_table.setItem(row_idx, 0, QTableWidgetItem(cluster.representative_he))
            self.clusters_table.setItem(row_idx, 1, QTableWidgetItem(cluster.canonical_key or ""))
            termhood_str = (
                f"{cluster.termhood_score:.3f}" if cluster.termhood_score is not None else "N/A"
            )
            self.clusters_table.setItem(row_idx, 2, QTableWidgetItem(termhood_str))
            self.clusters_table.setItem(row_idx, 3, QTableWidgetItem(str(cluster.freq_abs)))

        self.clusters_table.resizeColumnsToContents()

    def _set_report_actions_enabled(self, enabled: bool) -> None:
        self.copy_report_btn.setEnabled(enabled)
        self.export_report_btn.setEnabled(enabled)

    def _has_report_data(self) -> bool:
        return (
            self._last_cluster_metrics is not None
            or self._last_lemma_metrics is not None
            or bool(self._last_untranslated_lemmas)
            or bool(self._last_untranslated_clusters)
        )

    def _format_metrics_line(self, title: str, metrics: CoverageMetrics | None) -> str:
        if metrics is None:
            return f"- {title}: still loading exact metrics"
        return (
            f"- {title}: {metrics.coverage_pct:.1f}% "
            f"({metrics.covered} / {metrics.total}, {metrics.uncovered} untranslated)"
        )

    def _build_report_text(self) -> str:
        lines = [
            "# Coverage Report",
            "",
            f"- Project ID: {self.project_id}",
            f"- Include Draft TM: {'yes' if self.include_draft_check.isChecked() else 'no'}",
            f"- Lemma order: {self.lemma_order_combo.currentText()}",
            f"- Cluster order: {self.cluster_order_combo.currentText()}",
            f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Metrics",
            self._format_metrics_line("Lemma Coverage", self._last_lemma_metrics),
            self._format_metrics_line("Term Cluster Coverage", self._last_cluster_metrics),
            "",
            "## Untranslated Lemmas",
        ]

        if self._last_untranslated_lemmas:
            for row in self._last_untranslated_lemmas:
                lines.append(
                    f"- {row.lemma_text} | POS={row.pos or ''} | freq={row.freq_abs} | doc_freq={row.doc_freq}"
                )
        else:
            lines.append("- none in current panel state")

        lines.extend(["", "## Untranslated Term Clusters"])
        if self._last_untranslated_clusters:
            for row in self._last_untranslated_clusters:
                termhood = f"{row.termhood_score:.3f}" if row.termhood_score is not None else "N/A"
                lines.append(
                    f"- {row.representative_he} | canonical={row.canonical_key or ''} | "
                    f"termhood={termhood} | freq={row.freq_abs}"
                )
        else:
            lines.append("- none in current panel state")

        return "\n".join(lines)

    def copy_report_to_clipboard(self) -> None:
        if not self._has_report_data():
            self.status_label.setText("Coverage report is not available yet.")
            return
        app = QApplication.instance()
        if app is None:
            self.status_label.setText("Coverage report copy failed: no QApplication.")
            return
        app.clipboard().setText(self._build_report_text())
        self.status_label.setText("Coverage report copied to clipboard.")

    def export_report(self) -> None:
        if not self._has_report_data():
            self.status_label.setText("Coverage report is not available yet.")
            return
        default_name = f"coverage_report_project_{self.project_id}.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Coverage Report",
            str(Path.home() / default_name),
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return
        try:
            Path(file_path).write_text(self._build_report_text(), encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(f"Coverage report export failed: {exc}")
            logger.exception("Coverage report export failed")
            return
        self.status_label.setText(f"Coverage report exported: {file_path}")

    def on_coverage_partial_results(self, results: dict, request_seq: int | None = None):
        """Render the fast coverage layers before lemma coverage is ready."""
        if request_seq is not None and request_seq != self._active_coverage_seq:
            logger.debug(
                "Ignoring stale coverage partial results: seq=%s, active=%s",
                request_seq,
                self._active_coverage_seq,
            )
            return

        cluster_metrics: CoverageMetrics = results["cluster_metrics"]
        lemmas: list[LemmaCoverageRow] = results["untranslated_lemmas"]
        clusters: list[TermClusterCoverageRow] = results["untranslated_clusters"]

        self._apply_cluster_metrics(cluster_metrics)
        self._apply_untranslated_lemmas(lemmas)
        self._apply_untranslated_clusters(clusters)
        self._set_report_actions_enabled(self._has_report_data())
        self._set_lemma_metrics_pending()
        self.status_label.setText("Coverage tables ready. Counting lemma coverage...")

    def on_lemma_metrics_ready(
        self, lemma_metrics: CoverageMetrics, request_seq: int | None = None
    ):
        """Apply the expensive lemma metric after the panel is already usable."""
        if request_seq is not None and request_seq != self._active_coverage_seq:
            logger.debug(
                "Ignoring stale lemma coverage metrics: seq=%s, active=%s",
                request_seq,
                self._active_coverage_seq,
            )
            return

        self._apply_lemma_metrics(lemma_metrics)
        self._set_report_actions_enabled(self._has_report_data())
        self.status_label.setText("Ready")
        logger.info("Coverage data loaded successfully")

    def on_coverage_error(self, error_msg: str, request_seq: int | None = None):
        """Handle coverage error."""
        if request_seq is not None and request_seq != self._active_coverage_seq:
            logger.debug(
                "Ignoring stale coverage error: seq=%s, active=%s",
                request_seq,
                self._active_coverage_seq,
            )
            return

        self.status_label.setText(f"Error: {error_msg}")
        logger.error(f"Coverage error: {error_msg}")

    def _on_coverage_worker_finished(self, worker: CoverageWorker | None, request_seq: int) -> None:
        if self.worker is worker:
            self.worker = None

        self.cancel_btn.setEnabled(False)

        if request_seq != self._active_coverage_seq:
            return

        if self._coverage_retry_pending:
            self._coverage_retry_pending = False
            QTimer.singleShot(0, self.load_coverage)
            return

        if self._coverage_cancel_requested:
            self._coverage_cancel_requested = False
            self.status_label.setText("Coverage calculation canceled")

    def on_cancel_coverage(self):
        """Cancel ongoing coverage calculation."""
        if self.worker and self.worker.isRunning():
            logger.info("Canceling coverage worker")
            self._coverage_retry_pending = False
            self._coverage_cancel_requested = True
            self.worker.cancel()
            self.status_label.setText("Canceling coverage calculation...")
            self.cancel_btn.setEnabled(False)

    def closeEvent(self, event):
        """Handle panel close - stop workers."""
        if self.worker and self.worker.isRunning():
            logger.info("Stopping coverage worker on panel close")
            self.worker.cancel()
            if not self.worker.wait(200):
                self.worker.terminate()
                self.worker.wait()
        event.accept()

    def on_back(self):
        """Handle back button click."""
        self.back_requested.emit()
