"""Progress dialog for staged NLP processing."""

from __future__ import annotations

import time
from collections import deque

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


class NLPProcessProgressDialog(QDialog):
    """Modal progress dialog for resumable NLP processing."""

    cancel_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()

    def __init__(self, parent=None, total_docs: int = 0, operation_label: str = "Processing"):
        super().__init__(parent)
        self.total_docs = max(0, int(total_docs or 0))
        self.operation_label = str(operation_label or "Processing")
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
        self.setWindowTitle(f"{self.operation_label} with NLP")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )

        layout = QVBoxLayout(self)

        self.status_label = QLabel(f"{self.operation_label} documents with NLP...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1f6fb2;")
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
            label.setStyleSheet("color: #666; font-size: 12px;")
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
        self.activity_log.setStyleSheet(
            "QTextEdit { background-color: #f5f5f5; font-family: Consolas, monospace; font-size: 11px; }"
        )
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
            if phase == "completed":
                self.status_label.setText(f"{self.operation_label} completed")
                self.status_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #2e7d32;"
                )
            elif phase == "cancelled":
                self.status_label.setText(f"{self.operation_label} cancelled")
                self.status_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #b42318;"
                )
            else:
                self.status_label.setText(f"{self.operation_label} documents with NLP...")
                self.status_label.setStyleSheet(
                    "font-size: 14px; font-weight: bold; color: #1f6fb2;"
                )

        if phase in {"completed", "cancelled"}:
            self.pause_btn.setEnabled(False)
            if self.is_paused:
                self.is_paused = False
                self.pause_btn.setText("Pause")

        self.last_activity_at = time.time()

    def on_pause_resume(self) -> None:
        if self.is_paused:
            self.is_paused = False
            self.pause_btn.setText("Pause")
            self.status_label.setText(f"{self.operation_label} documents with NLP...")
            self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #1f6fb2;")
            if self.pause_started_at is not None:
                self.paused_time += time.time() - self.pause_started_at
                self.pause_started_at = None
            self.resume_requested.emit()
        else:
            self.is_paused = True
            self.pause_btn.setText("Resume")
            self.status_label.setText("Paused after current document checkpoint")
            self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #b26a00;")
            self.pause_started_at = time.time()
            self.pause_requested.emit()

    def on_cancel(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.status_label.setText("Cancelling after current document checkpoint...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #b42318;")
        self.cancel_requested.emit()

    def set_completed(self) -> None:
        self.heartbeat_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(f"{self.operation_label} completed")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2e7d32;")
        if self.progress_bar.maximum() > 0:
            self.progress_bar.setValue(self.progress_bar.maximum())

    def set_cancelled(self) -> None:
        self.heartbeat_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(f"{self.operation_label} cancelled")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #b42318;")

    def set_failed(self, error_message: str) -> None:
        self.heartbeat_timer.stop()
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(f"{self.operation_label} failed")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #b42318;")
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
