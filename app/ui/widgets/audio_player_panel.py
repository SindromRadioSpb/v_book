"""Mini audio player panel (Now Playing + queue + controls)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.infra.settings import SettingsService
from app.services.audio_player_service import AudioPlayerService

logger = logging.getLogger(__name__)


class AudioPlayerPanel(QWidget):
    """Compact premium playback panel with queue controls."""

    PRESETS = {
        "Normal": (200, 550, 300),
        "Study": (300, 800, 450),
        "Fast": (100, 250, 120),
    }

    def __init__(self, *, player: Optional[AudioPlayerService] = None, parent=None):
        super().__init__(parent)
        self.settings = SettingsService.get_instance()
        self.player = player or AudioPlayerService.get_instance()
        self._init_ui()
        self._connect_signals()
        self._reload_from_settings()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title = QLabel("<b>Audio Player</b>")
        root.addWidget(title)

        self.now_playing_label = QLabel("Now playing: (idle)")
        self.now_playing_label.setWordWrap(True)
        root.addWidget(self.now_playing_label)

        controls = QHBoxLayout()
        self.play_pause_btn = QPushButton("Play/Pause")
        self.stop_btn = QPushButton("Stop")
        self.next_btn = QPushButton("Next")
        self.clear_btn = QPushButton("Clear Queue")
        controls.addWidget(self.play_pause_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.clear_btn)
        controls.addStretch()
        root.addLayout(controls)

        cadence_row = QHBoxLayout()
        cadence_row.addWidget(QLabel("Cadence preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self.PRESETS.keys()))
        cadence_row.addWidget(self.preset_combo)
        cadence_row.addStretch()
        root.addLayout(cadence_row)

        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(120)
        self.queue_list.setAlternatingRowColors(True)
        self.queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        root.addWidget(self.queue_list, 1)

    def _connect_signals(self) -> None:
        self.play_pause_btn.clicked.connect(self.player.toggle_pause)
        self.stop_btn.clicked.connect(lambda: self.player.stop(clear_queue=False))
        self.next_btn.clicked.connect(self.player.next_track)
        self.clear_btn.clicked.connect(self.player.clear_queue)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)

        self.queue_list.itemDoubleClicked.connect(self._on_queue_item_double_clicked)

        self.player.queue_changed.connect(self._on_queue_changed)
        self.player.now_playing_changed.connect(self._on_now_playing_changed)
        self.player.playback_state_changed.connect(self._on_state_changed)
        self.player.playback_error.connect(self._on_playback_error)

        # Local keyboard accessibility (active when panel has focus/context).
        self.space_shortcut = QShortcut(QKeySequence("Space"), self)
        self.space_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.space_shortcut.activated.connect(self.player.toggle_pause)
        self.stop_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.stop_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.stop_shortcut.activated.connect(lambda: self.player.stop(clear_queue=False))

    def _reload_from_settings(self) -> None:
        pre = int(self.settings.get_int("audio/playback/pre_roll_ms", 200))
        gap = int(self.settings.get_int("audio/playback/gap_ms", 550))
        post = int(self.settings.get_int("audio/playback/post_roll_ms", 300))
        for name, values in self.PRESETS.items():
            if values == (pre, gap, post):
                self.preset_combo.setCurrentText(name)
                return
        self.preset_combo.setCurrentText("Normal")

    def _on_queue_changed(self, queue_payload: List[Dict[str, str]]) -> None:
        self.queue_list.clear()
        for idx, track in enumerate(queue_payload, start=1):
            label = str(track.get("label") or "(untitled)")
            item = QListWidgetItem(f"{idx}. {label}")
            item.setData(Qt.ItemDataRole.UserRole, idx - 1)
            self.queue_list.addItem(item)

    def _on_now_playing_changed(self, payload: object) -> None:
        if not payload:
            self.now_playing_label.setText("Now playing: (idle)")
            return
        data = payload if isinstance(payload, dict) else {}
        label = str(data.get("label") or "(untitled)")
        self.now_playing_label.setText(f"Now playing: {label}")

    def _on_state_changed(self, state: str) -> None:
        if state == "playing":
            self.play_pause_btn.setText("Pause")
        elif state == "paused":
            self.play_pause_btn.setText("Resume")
        else:
            self.play_pause_btn.setText("Play/Pause")

    def _on_playback_error(self, message: str, _payload: object) -> None:
        logger.warning("Audio playback warning: %s", message)

    def _on_queue_item_double_clicked(self, item: QListWidgetItem) -> None:
        queue_index = int(item.data(Qt.ItemDataRole.UserRole) or -1)
        if queue_index < 0:
            return
        # Reorder by removing items before selected index and skipping current track interrupt.
        removed = 0
        while removed < queue_index:
            if not self.player.remove_queue_index(0):
                break
            removed += 1
        self.player.next_track()

    def _on_preset_changed(self, preset_name: str) -> None:
        values = self.PRESETS.get(preset_name)
        if not values:
            return
        pre, gap, post = values
        self.settings.set_value("audio/playback/pre_roll_ms", pre)
        self.settings.set_value("audio/playback/gap_ms", gap)
        self.settings.set_value("audio/playback/post_roll_ms", post)
        self.settings.sync()
        self.player.set_cadence(pre_roll_ms=pre, gap_ms=gap, post_roll_ms=post)
