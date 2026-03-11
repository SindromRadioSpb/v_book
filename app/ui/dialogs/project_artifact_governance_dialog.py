"""On-demand read-only governance dialog for heavy derived project artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.domain.dto import (
    DerivedArtifactGovernanceSummaryDTO,
    DerivedArtifactMetricDTO,
)


class ProjectArtifactGovernanceDialog(QDialog):
    """Background-loaded read-only summary for heavy derived project artifacts."""

    def __init__(self, project_id: int, project_name: str, parent=None, *, auto_refresh: bool = True):
        super().__init__(parent)
        self.project_id = int(project_id)
        self.project_name = str(project_name or f"Project {int(project_id)}")
        self._summary: Optional[DerivedArtifactGovernanceSummaryDTO] = None
        self._worker = None
        self._request_seq = 0
        self._active_request_id = 0
        self._refresh_pending = False
        self._init_ui()
        if auto_refresh:
            self.refresh_summary()

    def _init_ui(self) -> None:
        self.setWindowTitle(f"Derived Data Governance - {self.project_name}")
        self.setModal(False)
        self.resize(920, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header_layout = QHBoxLayout()
        title = QLabel(f"Derived Data Governance - {self.project_name}")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0f172a;")
        header_layout.addWidget(title)

        self.badge_label = QLabel("Observational only")
        self.badge_label.setStyleSheet(self._badge_style("observational"))
        header_layout.addWidget(self.badge_label)
        header_layout.addStretch()
        root.addLayout(header_layout)

        self.subtitle_label = QLabel(
            "Project-owned derived data and telemetry overview. No cleanup or heavy validation starts from this dialog."
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet("color: #475569;")
        root.addWidget(self.subtitle_label)

        metrics_layout = QGridLayout()
        metrics_layout.setHorizontalSpacing(24)
        metrics_layout.setVerticalSpacing(8)
        self.total_docs_value = self._make_metric_value(metrics_layout, 0, 0, "Total docs")
        self.processed_docs_value = self._make_metric_value(metrics_layout, 0, 1, "Processed docs")
        self.snapshot_coverage_value = self._make_metric_value(metrics_layout, 1, 0, "Sentence coverage")
        self.run_error_value = self._make_metric_value(metrics_layout, 1, 1, "Run errors")
        root.addLayout(metrics_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area = scroll_area

        container = QWidget()
        self._cards_layout = QVBoxLayout(container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addStretch()
        scroll_area.setWidget(container)
        root.addWidget(scroll_area, 1)

        self.note_label = QLabel("")
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #64748b;")
        root.addWidget(self.note_label)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        root.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_summary)
        buttons_layout.addWidget(self.refresh_btn)

        self.copy_btn = QPushButton("Copy Summary")
        self.copy_btn.clicked.connect(self.copy_summary_to_clipboard)
        buttons_layout.addWidget(self.copy_btn)

        self.docs_btn = QPushButton("Open Lifecycle Contract")
        self.docs_btn.clicked.connect(self.open_lifecycle_contract)
        buttons_layout.addWidget(self.docs_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        buttons_layout.addWidget(close_btn)
        root.addLayout(buttons_layout)

    def _make_metric_value(self, layout: QGridLayout, row: int, col: int, caption: str) -> QLabel:
        caption_label = QLabel(caption)
        caption_label.setStyleSheet("color: #607d8b; font-size: 11px;")
        value_label = QLabel("—")
        value_label.setStyleSheet("color: #0f172a; font-size: 16px; font-weight: 600;")
        block = QVBoxLayout()
        block.setSpacing(2)
        block.addWidget(caption_label)
        block.addWidget(value_label)
        layout.addLayout(block, row, col)
        return value_label

    @staticmethod
    def _badge_style(status: str) -> str:
        palettes = {
            "observational": ("#264b7d", "#dbeafe", "#93c5fd"),
            "expected_large": ("#475569", "#e2e8f0", "#cbd5e1"),
            "coverage_partial": ("#92400e", "#fef3c7", "#fcd34d"),
            "fully_covered": ("#0f766e", "#ccfbf1", "#99f6e4"),
            "retention_watch": ("#7c2d12", "#ffedd5", "#fdba74"),
            "low_volume": ("#0f766e", "#ecfdf5", "#86efac"),
            "no_snapshot_coverage": ("#7c2d12", "#ffedd5", "#fdba74"),
        }
        fg, bg, border = palettes.get(status, palettes["observational"])
        return (
            f"color: {fg};"
            f"background: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 10px;"
            "padding: 2px 10px;"
            "font-weight: 600;"
        )

    @staticmethod
    def _badge_text(status: str) -> str:
        mapping = {
            "observational": "Observational only",
            "expected_large": "Expected large",
            "coverage_partial": "Coverage partial",
            "fully_covered": "Fully covered",
            "retention_watch": "Retention watch",
            "low_volume": "Low volume",
            "no_snapshot_coverage": "No snapshot coverage",
        }
        return mapping.get(status, "Observational only")

    def refresh_summary(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._refresh_pending = True
            self.set_loading("Refresh queued; current governance summary stays visible...")
            return

        from app.ui.workers import DerivedArtifactGovernanceWorker

        self._request_seq += 1
        request_id = int(self._request_seq)
        self._active_request_id = request_id
        self._refresh_pending = False
        self.set_loading("Refreshing derived artifact governance...")

        worker = DerivedArtifactGovernanceWorker(request_id=request_id, project_id=self.project_id)
        self._worker = worker
        worker.status.connect(self.on_worker_status)
        worker.summary_ready.connect(self.on_summary_ready)
        worker.error.connect(self.on_error)
        worker.finished.connect(lambda current=worker: self._on_worker_finished(current))
        worker.start()

    def set_loading(self, message: str) -> None:
        self.refresh_btn.setEnabled(False)
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.status_label.setText(str(message or "Refreshing derived artifact governance..."))

    def set_error(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_label.setStyleSheet("color: #b91c1c; font-size: 11px;")
        self.status_label.setText(str(message or "Derived artifact governance unavailable"))

    def set_summary(self, summary: DerivedArtifactGovernanceSummaryDTO) -> None:
        self._summary = summary
        self.refresh_btn.setEnabled(True)

        self.total_docs_value.setText(f"{int(summary.total_docs):,}")
        self.processed_docs_value.setText(f"{int(summary.processed_docs):,}")

        metric_map = {metric.artifact_key: metric for metric in summary.artifacts}
        run_error_metric = metric_map.get("run_error")
        self.snapshot_coverage_value.setText(self._format_pct(summary.snapshot_sentence_coverage_pct))
        self.run_error_value.setText(
            f"{int(run_error_metric.quantity_value):,}" if run_error_metric is not None else "—"
        )

        self.note_label.setText(
            "\n".join(
                line
                for line in (
                    summary.storage_note,
                    summary.lifecycle_note,
                    summary.snapshot_contract_note,
                    summary.observability_note,
                )
                if line
            )
        )
        self._rebuild_cards(summary.artifacts)
        self._refresh_status_text()

    def _rebuild_cards(self, metrics: list[DerivedArtifactMetricDTO]) -> None:
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        insert_at = 0
        for metric in metrics:
            self._cards_layout.insertWidget(insert_at, self._build_metric_card(metric))
            insert_at += 1

    def _build_metric_card(self, metric: DerivedArtifactMetricDTO) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            """
            QFrame {
                border: 1px solid #cfd8dc;
                border-radius: 8px;
                background: #f8fafc;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        title = QLabel(metric.display_name)
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #0f172a;")
        header_layout.addWidget(title)

        badge = QLabel(self._badge_text(metric.status))
        badge.setStyleSheet(self._badge_style(metric.status))
        header_layout.addWidget(badge)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        primary = QLabel(f"{int(metric.quantity_value):,} {metric.quantity_unit}")
        primary.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        layout.addWidget(primary)

        meta = QLabel(f"{metric.ownership} | {metric.quantity_basis}")
        meta.setStyleSheet("color: #475569;")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        summary = QLabel(metric.summary)
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #334155;")
        layout.addWidget(summary)

        if metric.detail_lines:
            details = QLabel("\n".join(f"- {line}" for line in metric.detail_lines))
            details.setWordWrap(True)
            details.setStyleSheet("color: #64748b;")
            details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(details)

        return card

    def on_worker_status(self, request_id: int, message: str) -> None:
        if int(request_id) != self._active_request_id:
            return
        self.set_loading(message)

    def on_summary_ready(self, request_id: int, summary: DerivedArtifactGovernanceSummaryDTO) -> None:
        if int(request_id) != self._active_request_id:
            return
        self.set_summary(summary)

    def on_error(self, request_id: int, message: str) -> None:
        if int(request_id) != self._active_request_id:
            return
        self.set_error(f"Derived artifact governance unavailable: {message}")

    def _on_worker_finished(self, worker) -> None:
        if worker is self._worker:
            self._worker = None
        worker.deleteLater()
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_summary()

    def _refresh_status_text(self) -> None:
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        if self._summary is None:
            self.status_label.setText("Ready")
            return
        self.status_label.setText(self._format_relative_refresh(self._summary.last_refreshed_at))

    def copy_summary_to_clipboard(self) -> None:
        if self._summary is None:
            return
        app = QApplication.instance()
        if app is None:
            return
        metric_lines = []
        for metric in self._summary.artifacts:
            metric_lines.append(
                f"{metric.display_name}: {int(metric.quantity_value):,} {metric.quantity_unit} "
                f"({metric.quantity_basis}; {metric.ownership})"
            )
            metric_lines.append(f"  {metric.summary}")
            for line in metric.detail_lines:
                metric_lines.append(f"  - {line}")

        text = "\n".join(
            [
                f"Derived Data Governance - {self._summary.project_name} (#{int(self._summary.project_id)})",
                f"Total docs: {int(self._summary.total_docs):,}",
                f"Processed docs: {int(self._summary.processed_docs):,}",
                "",
                *metric_lines,
                "",
                self._summary.storage_note,
                self._summary.lifecycle_note or "",
                self._summary.snapshot_contract_note or "",
                self._summary.observability_note,
            ]
        ).strip()
        app.clipboard().setText(text)
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.status_label.setText("Governance summary copied to clipboard.")

    def open_lifecycle_contract(self) -> None:
        docs_path = Path(__file__).resolve().parents[3] / "docs" / "PROJECT_DATA_CACHE_LIFECYCLE_CONTRACT.md"
        if not docs_path.exists():
            self.set_error(f"Open manually: {docs_path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(docs_path))):
            self.set_error(f"Open manually: {docs_path}")

    @staticmethod
    def _parse_utc_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    @classmethod
    def _format_relative_refresh(cls, value: Optional[str]) -> str:
        parsed = cls._parse_utc_timestamp(value)
        if parsed is None:
            return "Refreshed: n/a"
        now = datetime.now(timezone.utc)
        delta_seconds = max(int((now - parsed).total_seconds()), 0)
        if delta_seconds < 10:
            rel = "just now"
        elif delta_seconds < 60:
            rel = f"{delta_seconds}s ago"
        elif delta_seconds < 3600:
            rel = f"{delta_seconds // 60}m ago"
        else:
            rel = f"{delta_seconds // 3600}h ago"
        return f"Refreshed {rel} ({parsed.strftime('%Y-%m-%d %H:%M UTC')})"

    @staticmethod
    def _format_pct(value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"{float(value):.2f}%"

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(100)
        super().closeEvent(event)
