"""Batch Progress Dialog V3 - Premium detailed visualization.

Enhanced progress dialog with:
- ETA and speed metrics
- Detailed success/skip/fail statistics
- Recent activity log (last 5 translations)
- Pause/Resume/Cancel controls
- Elapsed time tracking
"""

import time
from collections import deque

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class BatchProgressDialogV3(QDialog):
    """Premium progress dialog for batch translation with detailed metrics."""

    cancel_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()

    def __init__(self, parent=None, total: int = 0):
        """Initialize dialog.

        Args:
            parent: Parent widget
            total: Total number of items to translate
        """
        super().__init__(parent)
        self.total = total
        self.completed = 0
        self.succeeded = 0
        self.skipped = 0
        self.failed = 0

        # Metrics
        self.start_time = time.time()
        self.paused_time = 0  # Total time spent paused
        self.pause_start = None  # When current pause started
        self.is_paused = False

        # PATCH-16-02: Heartbeat tracking
        self.last_activity_time = time.time()
        self.current_stage = "Initializing..."

        # Recent activity (last 5 items)
        self.recent_items = deque(maxlen=5)

        self.init_ui()

        # PATCH-16-02: Start heartbeat timer (updates elapsed/last activity every 500ms)
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._update_heartbeat)
        self.heartbeat_timer.start(500)  # 500ms updates

    def init_ui(self):
        """Initialize UI with premium layout."""
        self.setWindowTitle("Translate All Filtered - Batch Translation")
        self.setMinimumWidth(600)
        self.setMinimumHeight(450)
        self.setModal(True)

        # Disable close button (only Cancel/Pause buttons work)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint
        )

        layout = QVBoxLayout()

        # === Header with status ===
        header_layout = QHBoxLayout()
        self.status_label = QLabel("[*] Translating...")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2196F3;")
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # PATCH-16-02: Stage and Last Activity row
        stage_layout = QHBoxLayout()
        self.stage_label = QLabel("Stage: Initializing...")
        self.stage_label.setStyleSheet("color: #666; font-size: 12px;")
        stage_layout.addWidget(self.stage_label)

        stage_layout.addStretch()

        self.last_activity_label = QLabel("Last activity: 0s ago")
        self.last_activity_label.setStyleSheet("color: #666; font-size: 11px; font-style: italic;")
        stage_layout.addWidget(self.last_activity_label)

        layout.addLayout(stage_layout)

        # === Progress bar ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m (%p%)")
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #4caf50;
                border-radius: 3px;
            }
        """
        )
        layout.addWidget(self.progress_bar)

        # === Metrics row ===
        metrics_layout = QHBoxLayout()

        # Speed
        self.speed_label = QLabel("⚡ Speed: calculating...")
        self.speed_label.setStyleSheet("color: #666; font-size: 12px;")
        metrics_layout.addWidget(self.speed_label)

        metrics_layout.addStretch()

        # ETA
        self.eta_label = QLabel("⏱️ ETA: calculating...")
        self.eta_label.setStyleSheet("color: #666; font-size: 12px;")
        metrics_layout.addWidget(self.eta_label)

        layout.addLayout(metrics_layout)

        # === Time row ===
        time_layout = QHBoxLayout()
        self.elapsed_label = QLabel("Time: 0s elapsed")
        self.elapsed_label.setStyleSheet("color: #666; font-size: 11px;")
        time_layout.addWidget(self.elapsed_label)
        time_layout.addStretch()
        layout.addLayout(time_layout)

        # === Results group ===
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout()

        self.succeeded_label = QLabel("✅ Translated:  0  (0%)")
        self.succeeded_label.setStyleSheet("color: #4caf50; font-size: 13px;")
        results_layout.addWidget(self.succeeded_label)

        self.skipped_label = QLabel("⏭️ Skipped:  0  (already done)")
        self.skipped_label.setStyleSheet("color: #ff9800; font-size: 13px;")
        results_layout.addWidget(self.skipped_label)

        self.failed_label = QLabel("❌ Failed:  0  (errors)")
        self.failed_label.setStyleSheet("color: #f44336; font-size: 13px;")
        results_layout.addWidget(self.failed_label)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        # === Recent activity log ===
        activity_group = QGroupBox("Recent activity")
        activity_layout = QVBoxLayout()

        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumHeight(100)
        self.activity_log.setStyleSheet(
            """
            QTextEdit {
                background-color: #f5f5f5;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #ddd;
            }
        """
        )
        activity_layout.addWidget(self.activity_log)

        activity_group.setLayout(activity_layout)
        layout.addWidget(activity_group)

        # === Control buttons ===
        button_layout = QHBoxLayout()

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setMinimumWidth(80)
        self.pause_btn.clicked.connect(self.on_pause_resume)
        button_layout.addWidget(self.pause_btn)

        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumWidth(80)
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setStyleSheet("QPushButton { color: #f44336; }")
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def update_progress(self, completed: int, total: int):
        """Update progress bar and metrics.

        Args:
            completed: Number of completed items
            total: Total number of items
        """
        self.completed = completed
        self.total = total
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(completed)

        # Calculate metrics
        self._update_metrics()

        # PATCH-16-02: Mark activity
        self.mark_activity()

    def update_counts(self, succeeded: int, skipped: int, failed: int):
        """Update result counts with percentages.

        Args:
            succeeded: Number of succeeded translations
            skipped: Number of skipped rows
            failed: Number of failed translations
        """
        self.succeeded = succeeded
        self.skipped = skipped
        self.failed = failed

        total_processed = succeeded + skipped + failed

        # Update labels with percentages
        if total_processed > 0:
            succ_pct = int((succeeded / total_processed) * 100)
            self.succeeded_label.setText(f"[OK] Translated:  {succeeded}  ({succ_pct}%)")

            if skipped > 0:
                skip_pct = int((skipped / total_processed) * 100)
                self.skipped_label.setText(f"[SKIP] Skipped:  {skipped}  ({skip_pct}%)")

            if failed > 0:
                fail_pct = int((failed / total_processed) * 100)
                self.failed_label.setText(f"[FAIL] Failed:  {failed}  ({fail_pct}%)")
        else:
            self.succeeded_label.setText(f"[OK] Translated:  {succeeded}  (0%)")
            self.skipped_label.setText(f"[SKIP] Skipped:  {skipped}  (already done)")
            self.failed_label.setText(f"[FAIL] Failed:  {failed}  (errors)")

        # PATCH-16-02: Mark activity
        self.mark_activity()

    def add_recent_item(self, entity_id: str, translation: str, success: bool):
        """Add item to recent activity log.

        Args:
            entity_id: Source text
            translation: Translated text, skip reason, or error message
            success: True if succeeded, False if skipped/failed
        """
        if success:
            # OK event: successful translation
            icon = "[+]"
            color = "#4caf50"
            text = f"{entity_id} -> {translation}"
        else:
            # PATCH-17-04: Distinguish SKIP vs FAIL
            translation_lower = translation.lower()
            if (
                "already" in translation_lower
                or "skip" in translation_lower
                or "translated" in translation_lower
            ):
                # SKIP event: already translated
                icon = "[~]"
                color = "#ff9800"  # Orange for skip
                text = f"{entity_id} ({translation})"
            else:
                # FAIL event: error
                icon = "[x]"
                color = "#f44336"  # Red for fail
                text = f"{entity_id}: {translation}"

        # Add to deque
        self.recent_items.append((icon, text, color))

        # Update text edit
        html_lines = []
        for icon, txt, col in self.recent_items:
            html_lines.append(f'<span style="color: {col};">{icon} {txt}</span>')

        self.activity_log.setHtml("<br>".join(html_lines))

        # Scroll to bottom
        cursor = self.activity_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.activity_log.setTextCursor(cursor)

        # PATCH-16-02: Mark activity
        self.mark_activity()

    def _update_metrics(self):
        """Update speed and ETA labels."""
        if self.is_paused:
            return  # Don't update during pause

        # Calculate elapsed time (excluding paused time)
        elapsed = time.time() - self.start_time - self.paused_time
        if self.pause_start:
            elapsed -= time.time() - self.pause_start

        # Update elapsed label
        if elapsed < 60:
            self.elapsed_label.setText(f"Time: {int(elapsed)}s elapsed")
        else:
            mins = int(elapsed / 60)
            secs = int(elapsed % 60)
            self.elapsed_label.setText(f"Time: {mins}m {secs}s elapsed")

        if self.completed > 0 and elapsed > 0:
            # Calculate speed (items/sec)
            speed = self.completed / elapsed
            self.speed_label.setText(f"⚡ Speed: {speed:.1f} items/sec")

            # Calculate ETA
            remaining = self.total - self.completed
            if speed > 0:
                eta_seconds = remaining / speed

                if eta_seconds < 60:
                    self.eta_label.setText(f"⏱️ ETA: {int(eta_seconds)}s remaining")
                elif eta_seconds < 3600:
                    mins = int(eta_seconds / 60)
                    secs = int(eta_seconds % 60)
                    self.eta_label.setText(f"⏱️ ETA: {mins}m {secs}s remaining")
                else:
                    hours = int(eta_seconds / 3600)
                    mins = int((eta_seconds % 3600) / 60)
                    self.eta_label.setText(f"⏱️ ETA: {hours}h {mins}m remaining")
        else:
            self.speed_label.setText("⚡ Speed: calculating...")
            self.eta_label.setText("⏱️ ETA: calculating...")

    def on_pause_resume(self):
        """Handle pause/resume button click."""
        if self.is_paused:
            # Resume
            self.is_paused = False
            self.pause_btn.setText("Pause")
            self.status_label.setText("[*] Translating...")
            self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2196F3;")
            self.set_stage("Resuming...")  # PATCH-16-02

            # Track paused time
            if self.pause_start:
                self.paused_time += time.time() - self.pause_start
                self.pause_start = None

            self.resume_requested.emit()
        else:
            # Pause
            self.is_paused = True
            self.pause_btn.setText("Resume")
            self.status_label.setText("[||] Paused")
            self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ff9800;")
            self.set_stage("Paused")  # PATCH-16-02

            # Mark pause start
            self.pause_start = time.time()

            self.pause_requested.emit()

    def on_cancel(self):
        """Handle cancel button click."""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling...")
        self.pause_btn.setEnabled(False)
        self.status_label.setText("[X] Cancelling... (finishing current item)")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f44336;")
        self.set_stage("Cancelling...")  # PATCH-16-02
        self.cancel_requested.emit()

    def mark_activity(self):
        """PATCH-16-02: Mark that activity just happened (reset last activity timer)."""
        self.last_activity_time = time.time()

    def set_stage(self, stage: str):
        """PATCH-16-02: Update current stage label.

        Args:
            stage: Stage description (e.g. "Initializing...", "Translating batch 1/5", "Waiting provider response...")
        """
        self.current_stage = stage
        self.stage_label.setText(f"Stage: {stage}")
        self.mark_activity()

    def _update_heartbeat(self):
        """PATCH-16-02: Called by QTimer every 500ms to update elapsed/last activity."""
        # Update elapsed time label (already exists in _update_metrics, but force update here)
        if not self.is_paused:
            elapsed = time.time() - self.start_time - self.paused_time
            if self.pause_start:
                elapsed -= time.time() - self.pause_start

            if elapsed < 60:
                self.elapsed_label.setText(f"Time: {int(elapsed)}s elapsed")
            else:
                mins = int(elapsed / 60)
                secs = int(elapsed % 60)
                self.elapsed_label.setText(f"Time: {mins}m {secs}s elapsed")

        # Update last activity label
        seconds_ago = int(time.time() - self.last_activity_time)
        if seconds_ago < 60:
            self.last_activity_label.setText(f"Last activity: {seconds_ago}s ago")
        else:
            mins_ago = seconds_ago // 60
            self.last_activity_label.setText(f"Last activity: {mins_ago}m ago")

    def set_completed(self):
        """Mark translation as completed."""
        self.heartbeat_timer.stop()  # PATCH-16-02: Stop heartbeat timer
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.status_label.setText("[DONE] Translation complete!")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4caf50;")
        self.set_stage("Completed")  # PATCH-16-02

        # Update progress to 100%
        self.progress_bar.setValue(self.total)

        # Final metrics update
        self._update_metrics()

    def closeEvent(self, event):
        """Prevent closing via X button."""
        event.ignore()
