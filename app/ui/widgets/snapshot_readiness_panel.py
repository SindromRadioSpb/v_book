"""Read-only snapshot readiness card for DocumentsView."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.dto import SnapshotReadinessSummaryDTO


class SnapshotReadinessPanel(QWidget):
    """Compact non-modal snapshot readiness surface."""

    refresh_requested = pyqtSignal()
    copy_cli_requested = pyqtSignal()
    open_runbook_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary: Optional[SnapshotReadinessSummaryDTO] = None
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("snapshotReadinessCard")
        card.setStyleSheet(
            """
            QFrame#snapshotReadinessCard {
                border: 1px solid #cfd8dc;
                border-radius: 8px;
                background: #f8fafc;
            }
            QLabel[metricCaption="true"] {
                color: #607d8b;
                font-size: 11px;
            }
            QLabel[metricValue="true"] {
                color: #0f172a;
                font-size: 16px;
                font-weight: 600;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        title = QLabel("Snapshot Readiness")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #0f172a;")
        header_layout.addWidget(title)

        self.badge_label = QLabel("Observing")
        self.badge_label.setStyleSheet(self._badge_style("no_snapshot_coverage"))
        header_layout.addWidget(self.badge_label)
        header_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        header_layout.addWidget(self.refresh_btn)

        self.copy_cli_btn = QPushButton("Copy Coverage CLI")
        self.copy_cli_btn.clicked.connect(self.copy_cli_requested.emit)
        header_layout.addWidget(self.copy_cli_btn)

        self.runbook_btn = QPushButton("Open Runbook")
        self.runbook_btn.clicked.connect(self.open_runbook_requested.emit)
        header_layout.addWidget(self.runbook_btn)
        card_layout.addLayout(header_layout)

        self.subtitle_label = QLabel("Full-scale validation deferred")
        self.subtitle_label.setStyleSheet("color: #475569;")
        self.subtitle_label.setWordWrap(True)
        card_layout.addWidget(self.subtitle_label)

        metrics_layout = QGridLayout()
        metrics_layout.setHorizontalSpacing(24)
        metrics_layout.setVerticalSpacing(6)
        self.doc_coverage_value = self._make_metric_value(metrics_layout, 0, 0, "Doc coverage")
        self.sentence_coverage_value = self._make_metric_value(metrics_layout, 0, 1, "Sentence coverage")
        self.fully_covered_value = self._make_metric_value(metrics_layout, 1, 0, "Fully covered docs")
        self.remaining_value = self._make_metric_value(metrics_layout, 1, 1, "Remaining uncovered")
        card_layout.addLayout(metrics_layout)

        self.meta_label = QLabel("Latest backfill: n/a")
        self.meta_label.setStyleSheet("color: #334155;")
        self.meta_label.setWordWrap(True)
        card_layout.addWidget(self.meta_label)

        self.note_label = QLabel(
            "Observational only. This panel does not approve production rollout or start backfill."
        )
        self.note_label.setStyleSheet("color: #64748b;")
        self.note_label.setWordWrap(True)
        card_layout.addWidget(self.note_label)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label)

        root.addWidget(card)

    def _make_metric_value(self, layout: QGridLayout, row: int, col: int, caption: str) -> QLabel:
        caption_label = QLabel(caption)
        caption_label.setProperty("metricCaption", True)
        value_label = QLabel("—")
        value_label.setProperty("metricValue", True)
        container = QVBoxLayout()
        container.setSpacing(2)
        container.addWidget(caption_label)
        container.addWidget(value_label)
        layout.addLayout(container, row, col)
        return value_label

    def _badge_style(self, contract_state: str) -> str:
        palettes = {
            "bounded_validated": ("#264b7d", "#dbeafe", "#93c5fd"),
            "fully_covered": ("#0f766e", "#ccfbf1", "#99f6e4"),
            "partial_coverage": ("#92400e", "#fef3c7", "#fcd34d"),
            "no_processed_docs": ("#475569", "#e2e8f0", "#cbd5e1"),
            "no_snapshot_coverage": ("#7c2d12", "#ffedd5", "#fdba74"),
        }
        fg, bg, border = palettes.get(contract_state, palettes["no_snapshot_coverage"])
        return (
            f"color: {fg};"
            f"background: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 10px;"
            "padding: 2px 10px;"
            "font-weight: 600;"
        )

    def _badge_text(self, contract_state: str) -> str:
        mapping = {
            "bounded_validated": "Bounded validated",
            "fully_covered": "Fully covered",
            "partial_coverage": "Partial coverage",
            "no_processed_docs": "No processed docs",
            "no_snapshot_coverage": "No snapshot coverage",
        }
        return mapping.get(contract_state, "Observing")

    def set_loading(self, message: str = "Refreshing snapshot readiness...") -> None:
        self.refresh_btn.setEnabled(False)
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.status_label.setText(str(message or "Refreshing snapshot readiness..."))

    def set_error(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_label.setStyleSheet("color: #b91c1c; font-size: 11px;")
        self.status_label.setText(str(message or "Failed to load snapshot readiness"))

    def set_summary(self, summary: SnapshotReadinessSummaryDTO) -> None:
        self._summary = summary
        self.refresh_btn.setEnabled(True)
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")

        self.badge_label.setText(self._badge_text(summary.contract_state))
        self.badge_label.setStyleSheet(self._badge_style(summary.contract_state))

        subtitle = "Full-scale validation deferred"
        if summary.contract_state == "fully_covered":
            subtitle = "Coverage is complete for currently processed documents"
        elif summary.contract_state == "no_processed_docs":
            subtitle = "No processed documents available yet"
        self.subtitle_label.setText(subtitle)

        self.doc_coverage_value.setText(self._format_pct(summary.doc_coverage_pct))
        self.sentence_coverage_value.setText(self._format_pct(summary.sentence_coverage_pct))
        self.fully_covered_value.setText(
            f"{summary.fully_covered_docs:,} / {summary.processed_docs:,}"
        )
        self.remaining_value.setText(f"{summary.remaining_uncovered_docs:,}")

        latest_bits = []
        if summary.latest_backfill_run_id is not None:
            latest_bits.append(f"Run #{summary.latest_backfill_run_id}")
        if summary.latest_backfill_status:
            latest_bits.append(summary.latest_backfill_status)
        if summary.latest_backfill_stage:
            latest_bits.append(summary.latest_backfill_stage)
        if summary.latest_backfill_last_doc_id is not None:
            latest_bits.append(f"last doc {summary.latest_backfill_last_doc_id}")
        if summary.latest_backfill_finished_at:
            latest_bits.append(f"finished {self._format_timestamp(summary.latest_backfill_finished_at)}")
        if summary.latest_backfill_docs_total:
            latest_bits.append(
                f"docs {summary.latest_backfill_docs_processed:,}/{summary.latest_backfill_docs_total:,}"
            )
        self.meta_label.setText(
            "Latest backfill: " + (" | ".join(latest_bits) if latest_bits else "n/a")
        )

        note_lines = []
        if summary.contract_note:
            note_lines.append(summary.contract_note)
        if summary.summary_note:
            note_lines.append(summary.summary_note)
        self.note_label.setText("\n".join(note_lines) if note_lines else "")
        self.refresh_staleness()

    def refresh_staleness(self, now: Optional[datetime] = None) -> None:
        if self._summary is None:
            return
        refreshed_text = self._format_relative_refresh(self._summary.last_refreshed_at, now=now)
        self.status_label.setText(refreshed_text)

    @staticmethod
    def _format_pct(value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"{float(value):.2f}%"

    @staticmethod
    def _parse_utc_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    @classmethod
    def _format_timestamp(cls, value: Optional[str]) -> str:
        parsed = cls._parse_utc_timestamp(value)
        if parsed is None:
            return str(value or "n/a")
        return parsed.strftime("%Y-%m-%d %H:%M UTC")

    @classmethod
    def _format_relative_refresh(
        cls,
        value: Optional[str],
        *,
        now: Optional[datetime] = None,
    ) -> str:
        parsed = cls._parse_utc_timestamp(value)
        if parsed is None:
            return "Refreshed: n/a"
        current = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
        delta_seconds = max(int((current - parsed).total_seconds()), 0)
        if delta_seconds < 10:
            rel = "just now"
        elif delta_seconds < 60:
            rel = f"{delta_seconds}s ago"
        elif delta_seconds < 3600:
            rel = f"{delta_seconds // 60}m ago"
        else:
            rel = f"{delta_seconds // 3600}h ago"
        return f"Refreshed {rel} ({parsed.strftime('%Y-%m-%d %H:%M UTC')})"
