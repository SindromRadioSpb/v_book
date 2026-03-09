"""Shared staged progress dialog foundation for long-running operations."""

from __future__ import annotations

import time
from collections import deque
from typing import Mapping

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
)

_STATUS_STYLE_BLUE = "font-size: 14px; font-weight: bold; color: #1f6fb2;"
_STATUS_STYLE_GREEN = "font-size: 14px; font-weight: bold; color: #2e7d32;"
_STATUS_STYLE_RED = "font-size: 14px; font-weight: bold; color: #b42318;"
_STATUS_STYLE_AMBER = "font-size: 14px; font-weight: bold; color: #b26a00;"
_META_LABEL_STYLE = "color: #666; font-size: 12px;"
_ACTIVITY_LOG_STYLE = (
    "QTextEdit { background-color: #f5f5f5; font-family: Consolas, monospace; "
    "font-size: 11px; }"
)


class StagedOperationProgressDialog(QDialog):
    """Shared modal dialog for resumable document-batch operations."""

    cancel_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        total_docs: int = 0,
        window_title: str,
        initial_status_text: str,
        running_status_text: str,
        paused_status_text: str,
        cancel_pending_status_text: str,
        completed_status_text: str,
        cancelled_status_text: str,
        failed_status_text: str,
        phase_status_overrides: Mapping[str, str] | None = None,
        disable_pause_phases: set[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.total_docs = max(0, int(total_docs or 0))
        self.window_title_text = str(window_title or "Operation Progress")
        self.initial_status_text = str(initial_status_text or "Initializing...")
        self.running_status_text = str(running_status_text or "Running...")
        self.paused_status_text = str(paused_status_text or "Paused after current checkpoint")
        self.cancel_pending_status_text = str(
            cancel_pending_status_text or "Cancelling after current checkpoint..."
        )
        self.completed_status_text = str(completed_status_text or "Completed")
        self.cancelled_status_text = str(cancelled_status_text or "Cancelled")
        self.failed_status_text = str(failed_status_text or "Failed")
        self.phase_status_overrides = dict(phase_status_overrides or {})
        self.disable_pause_phases = set(disable_pause_phases or {"completed", "cancelled"})
        self.is_paused = False
        self.start_time = time.time()
        self.paused_time = 0.0
        self.pause_started_at: float | None = None
        self.last_activity_at = time.time()
        self.recent_messages = deque(maxlen=8)

        self._build_ui()

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._update_heartbeat)
        self.heartbeat_timer.start(500)

    def _build_ui(self) -> None:
        self.setWindowTitle(self.window_title_text)
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )

        layout = QVBoxLayout(self)

        self.status_label = QLabel(self.initial_status_text)
        self.status_label.setStyleSheet(_STATUS_STYLE_BLUE)
        layout.addWidget(self.status_label)

        self.stage_label = QLabel("Stage: Initializing...")
        self.run_label = QLabel("Run ID: -")
        self.docs_label = QLabel("Docs: 0 / 0")
        self.chunks_label = QLabel("Chunks: 0 / 0")
        self.last_doc_label = QLabel("Last doc ID: -")
        self.elapsed_label = QLabel("Elapsed: 0s")
        self.last_activity_label = QLabel("Last activity: 0s ago")
        for label in (
            self.stage_label,
            self.run_label,
            self.docs_label,
            self.chunks_label,
            self.last_doc_label,
            self.elapsed_label,
            self.last_activity_label,
        ):
            label.setStyleSheet(_META_LABEL_STYLE)
            layout.addWidget(label)

        self.progress_bar = QProgressBar()
        if self.total_docs > 0:
            self.progress_bar.setRange(0, self.total_docs)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%v / %m docs (%p%)")
        else:
            self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumHeight(140)
        self.activity_log.setStyleSheet(_ACTIVITY_LOG_STYLE)
        layout.addWidget(self.activity_log)

        button_layout = QHBoxLayout()
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.on_pause_resume)
        button_layout.addWidget(self.pause_btn)

        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setStyleSheet("QPushButton { color: #b42318; }")
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

    def _set_status_text(self, text: str, *, style: str) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(style)

    def _status_text_for_phase(self, phase: str) -> str:
        if phase == "completed":
            return self.completed_status_text
        if phase == "cancelled":
            return self.cancelled_status_text
        if phase == "paused":
            return self.paused_status_text
        return self.phase_status_overrides.get(phase, self.running_status_text)

    def _status_style_for_phase(self, phase: str) -> str:
        if phase == "completed":
            return _STATUS_STYLE_GREEN
        if phase in {"cancelled", "failed"}:
            return _STATUS_STYLE_RED
        if phase == "paused":
            return _STATUS_STYLE_AMBER
        return _STATUS_STYLE_BLUE

    def append_activity(self, message: str) -> None:
        self.recent_messages.append(str(message))
        self.activity_log.setPlainText("\n".join(self.recent_messages))
        cursor = self.activity_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.activity_log.setTextCursor(cursor)
        self.last_activity_at = time.time()

    def update_state(self, state: dict) -> None:
        stage = str(state.get("stage") or state.get("message") or "Working...")
        phase = str(state.get("phase") or "")
        run_id = state.get("run_id")
        docs_processed = max(0, int(state.get("docs_processed") or 0))
        docs_failed = max(0, int(state.get("docs_failed") or 0))
        docs_total = max(0, int(state.get("docs_total") or 0))
        chunks_completed = max(0, int(state.get("chunks_completed") or 0))
        chunks_total = max(0, int(state.get("chunks_total") or 0))
        last_doc_id = state.get("last_doc_id")
        message = str(state.get("message") or "")

        self.stage_label.setText(f"Stage: {stage}")
        self.run_label.setText(f"Run ID: {run_id if run_id is not None else '-'}")
        self.docs_label.setText(f"Docs: {docs_processed + docs_failed} / {docs_total}")
        self.chunks_label.setText(f"Chunks: {chunks_completed} / {chunks_total}")
        self.last_doc_label.setText(
            f"Last doc ID: {last_doc_id if last_doc_id is not None else '-'}"
        )

        if docs_total > 0:
            if self.progress_bar.maximum() != docs_total:
                self.progress_bar.setRange(0, docs_total)
                self.progress_bar.setFormat("%v / %m docs (%p%)")
            self.progress_bar.setValue(min(docs_processed + docs_failed, docs_total))
        else:
            self.progress_bar.setRange(0, 0)

        if message:
            self.append_activity(message)

        if not self.is_paused:
            status_phase = phase or "running"
            self._set_status_text(
                self._status_text_for_phase(status_phase),
                style=self._status_style_for_phase(status_phase),
            )

        if phase in self.disable_pause_phases:
            self.pause_btn.setEnabled(False)
            if self.is_paused:
                self.is_paused = False
                self.pause_btn.setText("Pause")

        self.last_activity_at = time.time()

    def on_pause_resume(self) -> None:
        if self.is_paused:
            self.is_paused = False
            self.pause_btn.setText("Pause")
            self._set_status_text(self.running_status_text, style=_STATUS_STYLE_BLUE)
            if self.pause_started_at is not None:
                self.paused_time += time.time() - self.pause_started_at
                self.pause_started_at = None
            self.resume_requested.emit()
        else:
            self.is_paused = True
            self.pause_btn.setText("Resume")
            self._set_status_text(self.paused_status_text, style=_STATUS_STYLE_AMBER)
            self.pause_started_at = time.time()
            self.pause_requested.emit()

    def on_cancel(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self._set_status_text(self.cancel_pending_status_text, style=_STATUS_STYLE_RED)
        self.cancel_requested.emit()

    def set_completed(self) -> None:
        self.heartbeat_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._set_status_text(self.completed_status_text, style=_STATUS_STYLE_GREEN)
        if self.progress_bar.maximum() > 0:
            self.progress_bar.setValue(self.progress_bar.maximum())

    def set_cancelled(self) -> None:
        self.heartbeat_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._set_status_text(self.cancelled_status_text, style=_STATUS_STYLE_RED)

    def set_failed(self, error_message: str) -> None:
        self.heartbeat_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._set_status_text(self.failed_status_text, style=_STATUS_STYLE_RED)
        self.append_activity(f"ERROR: {error_message}")

    def _update_heartbeat(self) -> None:
        elapsed = time.time() - self.start_time - self.paused_time
        if self.pause_started_at is not None:
            elapsed -= time.time() - self.pause_started_at
        elapsed = max(0.0, elapsed)
        self.elapsed_label.setText(f"Elapsed: {int(elapsed)}s")

        idle = max(0, int(time.time() - self.last_activity_at))
        self.last_activity_label.setText(f"Last activity: {idle}s ago")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
