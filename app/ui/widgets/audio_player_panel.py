"""Premium Audio Player Panel — v2 (Task 25).

Layout:
  ┌── Now Playing bar (label + transport controls + Go to Source) ──┐
  ├── Playback controls (speed · repeat · auto-pause · gap · preset) ┤
  ├── [Queue] [Playlists] [History]              [⚙ Columns]        ┤
  └── Table/list for the active tab                                   ┘

Hotkeys (WidgetWithChildrenShortcut — active when panel has focus):
  Space        → play / pause
  J            → previous track
  K            → next track
  +            → speed up 0.1×
  -            → speed down 0.1×
  R            → cycle repeat mode (none → one → all → none)
  Esc          → stop (keep queue)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.infra.settings import SettingsService
from app.services.audio_player_service import AudioPlayerService

logger = logging.getLogger(__name__)


# ── Table model ───────────────────────────────────────────────────────────────

_COL_NUM = 0
_COL_HEBREW = 1
_COL_NIQQUD = 2
_COL_TRANSLATION = 3
_COL_SOURCE = 4
_COL_STATUS = 5
_COL_PLAYS = 6

_COLUMNS = ["#", "Hebrew", "Niqqud", "Translation", "Source", "Status", "Plays"]
_COLUMN_KEYS = ["num", "hebrew", "niqqud", "translation", "source", "status", "plays"]

_CURRENT_BG = QColor(210, 240, 210)
_STALE_BG = QColor(255, 240, 200)


class AudioQueueTableModel(QAbstractTableModel):
    """Table model backed by AudioPlayerService queue (payload list)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []
        self._current_index: int = -1
        self._visible_cols: List[bool] = [True] * len(_COLUMNS)

    def load(self, rows: List[Dict[str, Any]], current_index: int) -> None:
        self.beginResetModel()
        self._rows = rows
        self._current_index = current_index
        self.endResetModel()

    def set_column_visible(self, col: int, visible: bool) -> None:
        if 0 <= col < len(self._visible_cols):
            self._visible_cols[col] = visible

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows) if not parent.isValid() else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS) if not parent.isValid() else 0

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(_COLUMNS):
                return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row >= len(self._rows):
            return None
        track = self._rows[row]
        ctx = track.get("context") or {}
        is_current = row == self._current_index

        if role == Qt.ItemDataRole.DisplayRole:
            if col == _COL_NUM:
                return "▶" if is_current else str(row + 1)
            if col == _COL_HEBREW:
                return track.get("label") or "—"
            if col == _COL_NIQQUD:
                return ctx.get("snapshot_niqqud") or ctx.get("niqqud") or "—"
            if col == _COL_TRANSLATION:
                return ctx.get("snapshot_translation") or ctx.get("translation") or "—"
            if col == _COL_SOURCE:
                return ctx.get("snapshot_source_label") or ctx.get("source_label") or "—"
            if col == _COL_STATUS:
                path = track.get("path", "")
                is_stale = ctx.get("is_stale", False)
                if is_stale:
                    return "stale"
                return "ready" if path and os.path.exists(str(path)) else "missing"
            if col == _COL_PLAYS:
                return str(ctx.get("play_count", "—"))
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            ctx = track.get("context") or {}
            if ctx.get("is_stale"):
                return _STALE_BG
            if is_current:
                return _CURRENT_BG
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == _COL_HEBREW:
                return track.get("label") or ""
            if col == _COL_NIQQUD:
                return ctx.get("snapshot_niqqud") or ctx.get("niqqud") or ""
            if col == _COL_TRANSLATION:
                return ctx.get("snapshot_translation") or ctx.get("translation") or ""
            return None

        if role == Qt.ItemDataRole.UserRole:
            return row

        return None


# ── Panel ─────────────────────────────────────────────────────────────────────


class AudioPlayerPanel(QWidget):
    """Premium audio player dock panel (v2)."""

    PRESETS = {
        "Normal": (200, 550, 300),
        "Study": (300, 800, 450),
        "Fast": (100, 250, 120),
    }

    REPEAT_MODES = ["Off", "One", "All"]
    _REPEAT_MAP = {"Off": "none", "One": "one", "All": "all"}
    _REPEAT_RMAP = {v: k for k, v in _REPEAT_MAP.items()}

    def __init__(
        self,
        *,
        player: Optional[AudioPlayerService] = None,
        db: Optional[Any] = None,  # db manager, used for playlists/history later
        parent=None,
    ):
        super().__init__(parent)
        self.settings = SettingsService.get_instance()
        self.player = player or AudioPlayerService.get_instance()
        self._db = db
        self._queue_model = AudioQueueTableModel(self)
        self._col_visible: List[bool] = [True] * len(_COLUMNS)
        self._col_visible[_COL_NUM] = True  # always shown
        self._history_entries: List[str] = []

        self._init_ui()
        self._connect_signals()
        self._restore_settings()
        self._refresh_queue()

    # ── UI construction ───────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        root.addWidget(self._build_now_playing_bar())
        root.addWidget(self._build_controls_row())
        root.addWidget(self._build_tab_area(), 1)

    def _build_now_playing_bar(self) -> QWidget:
        bar = QWidget()
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)

        self.now_playing_label = QLabel("▶  (idle)")
        self.now_playing_label.setWordWrap(False)
        self.now_playing_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(self.now_playing_label, 1)

        self.prev_btn = QPushButton("⏮")
        self.prev_btn.setFixedWidth(32)
        self.prev_btn.setToolTip("Previous track  [J]")
        self.prev_btn.setAccessibleName("Previous track")

        self.play_pause_btn = QPushButton("▶")
        self.play_pause_btn.setFixedWidth(36)
        self.play_pause_btn.setToolTip("Play / Pause  [Space]")
        self.play_pause_btn.setAccessibleName("Play / Pause")

        self.next_btn = QPushButton("⏭")
        self.next_btn.setFixedWidth(32)
        self.next_btn.setToolTip("Next track  [K]")
        self.next_btn.setAccessibleName("Next track")

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedWidth(32)
        self.stop_btn.setToolTip("Stop (keep queue)  [Esc]")
        self.stop_btn.setAccessibleName("Stop")

        self.goto_source_btn = QPushButton("Go to Source")
        self.goto_source_btn.setToolTip("Navigate to the source row in the table")
        self.goto_source_btn.setEnabled(False)

        for w in (self.prev_btn, self.play_pause_btn, self.next_btn, self.stop_btn):
            hl.addWidget(w)
        hl.addWidget(self.goto_source_btn)
        return bar

    def _build_controls_row(self) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)

        # Speed
        hl.addWidget(QLabel("Speed:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.25, 4.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSuffix("×")
        self.speed_spin.setFixedWidth(72)
        self.speed_spin.setToolTip("Playback rate (on-the-fly, persisted)  [+/-]")
        self.speed_spin.setAccessibleName("Playback speed")
        hl.addWidget(self.speed_spin)

        # Repeat
        hl.addWidget(QLabel("Repeat:"))
        self.repeat_combo = QComboBox()
        self.repeat_combo.addItems(self.REPEAT_MODES)
        self.repeat_combo.setFixedWidth(60)
        self.repeat_combo.setToolTip("Repeat mode  [R]")
        self.repeat_combo.setAccessibleName("Repeat mode")
        hl.addWidget(self.repeat_combo)

        self.repeat_count_spin = QSpinBox()
        self.repeat_count_spin.setRange(0, 99)
        self.repeat_count_spin.setValue(0)
        self.repeat_count_spin.setSpecialValueText("∞")
        self.repeat_count_spin.setFixedWidth(48)
        self.repeat_count_spin.setToolTip("Times to repeat (0 = infinite)")
        self.repeat_count_spin.setEnabled(False)
        hl.addWidget(self.repeat_count_spin)

        # Auto-pause
        self.auto_pause_cb = QCheckBox("Auto-pause")
        self.auto_pause_cb.setToolTip("Pause automatically after each item")
        hl.addWidget(self.auto_pause_cb)

        # Gap
        hl.addWidget(QLabel("Gap:"))
        self.gap_spin = QSpinBox()
        self.gap_spin.setRange(0, 3000)
        self.gap_spin.setSingleStep(50)
        self.gap_spin.setValue(550)
        self.gap_spin.setSuffix(" ms")
        self.gap_spin.setFixedWidth(76)
        self.gap_spin.setToolTip("Gap between items (ms)")
        hl.addWidget(self.gap_spin)

        # Cadence preset
        hl.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self.PRESETS.keys()))
        self.preset_combo.setFixedWidth(72)
        self.preset_combo.setAccessibleName("Cadence preset")
        hl.addWidget(self.preset_combo)

        hl.addStretch()
        return row

    def _build_tab_area(self) -> QWidget:
        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        # Tab bar + gear button in same row
        tab_header = QHBoxLayout()
        self.tab_widget = QTabWidget()
        tab_header.addWidget(self.tab_widget, 1)

        self.columns_btn = QToolButton()
        self.columns_btn.setText("⚙")
        self.columns_btn.setToolTip("Toggle visible columns")
        self.columns_btn.setAccessibleName("Column visibility")
        self.columns_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._columns_menu = QMenu(self)
        self._col_actions = []
        for i, col_name in enumerate(_COLUMNS):
            if i == _COL_NUM:
                continue  # # is always visible
            act = self._columns_menu.addAction(col_name)
            act.setCheckable(True)
            act.setChecked(True)
            act.setData(i)
            act.toggled.connect(self._on_column_toggled)
            self._col_actions.append(act)
        self.columns_btn.setMenu(self._columns_menu)
        tab_header.addWidget(self.columns_btn)

        vl.addLayout(tab_header)

        # ── Queue tab ────────────────────────────────────────────────────────
        self.queue_table = QTableView()
        self.queue_table.setModel(self._queue_model)
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.queue_table.horizontalHeader().setStretchLastSection(True)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self._on_queue_context_menu)
        self.queue_table.doubleClicked.connect(self._on_queue_row_double_clicked)

        # Restore column widths
        hdr = self.queue_table.horizontalHeader()
        default_widths = [30, 200, 180, 160, 120, 70, 45]
        for i, w in enumerate(default_widths):
            hdr.resizeSection(i, w)

        self.tab_widget.addTab(self.queue_table, "Queue")

        # ── Playlists tab ────────────────────────────────────────────────────
        playlists_widget = self._build_playlists_tab()
        self.tab_widget.addTab(playlists_widget, "Playlists")

        # ── History tab ──────────────────────────────────────────────────────
        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab_widget.addTab(self.history_list, "History")

        return container

    def _build_playlists_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: playlist list
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        lv.addWidget(QLabel("Playlists"))
        self.playlists_list = QListWidget()
        self.playlists_list.setMaximumWidth(180)
        lv.addWidget(self.playlists_list, 1)

        pl_btns = QHBoxLayout()
        self.new_playlist_btn = QPushButton("New")
        self.new_playlist_btn.setToolTip("Create a new playlist")
        self.load_pl_btn = QPushButton("→ Queue")
        self.load_pl_btn.setToolTip("Load selected playlist to queue")
        pl_btns.addWidget(self.new_playlist_btn)
        pl_btns.addWidget(self.load_pl_btn)
        lv.addLayout(pl_btns)
        splitter.addWidget(left)

        # Right: playlist entries (placeholder)
        right = QLabel("Select a playlist to view its entries.\nPlaylist persistence requires DB session.")
        right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.setWordWrap(True)
        splitter.addWidget(right)
        splitter.setSizes([160, 400])

        return splitter

    # ── Signals ───────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Transport
        self.prev_btn.clicked.connect(self.player.previous_track)
        self.play_pause_btn.clicked.connect(self.player.toggle_pause)
        self.next_btn.clicked.connect(self.player.next_track)
        self.stop_btn.clicked.connect(lambda: self.player.stop(clear_queue=False))

        # Speed
        self.speed_spin.valueChanged.connect(self._on_speed_changed)

        # Repeat
        self.repeat_combo.currentTextChanged.connect(self._on_repeat_changed)
        self.repeat_count_spin.valueChanged.connect(self._on_repeat_count_changed)

        # Auto-pause
        self.auto_pause_cb.toggled.connect(self._on_auto_pause_changed)

        # Gap
        self.gap_spin.valueChanged.connect(self._on_gap_changed)

        # Cadence preset
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)

        # Player signals
        self.player.queue_changed.connect(self._on_queue_changed)
        self.player.now_playing_changed.connect(self._on_now_playing_changed)
        self.player.playback_state_changed.connect(self._on_state_changed)
        self.player.playback_error.connect(self._on_playback_error)
        self.player.track_finished.connect(self._on_track_finished)

        # Hotkeys
        self._add_shortcut("Space", self.player.toggle_pause)
        self._add_shortcut("J", self.player.previous_track)
        self._add_shortcut("K", self.player.next_track)
        self._add_shortcut("+", self._speed_up)
        self._add_shortcut("=", self._speed_up)   # US keyboard + without shift
        self._add_shortcut("-", self._speed_down)
        self._add_shortcut("R", self._cycle_repeat)
        self._add_shortcut("Esc", lambda: self.player.stop(clear_queue=False))

    def _add_shortcut(self, key: str, slot: Callable) -> None:
        sc = QShortcut(QKeySequence(key), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(slot)

    # ── Settings restore/save ─────────────────────────────────────────────────

    def _restore_settings(self) -> None:
        s = self.settings

        # Speed
        try:
            rate = float(s.get_string("audio/playback/rate", "1.0"))
        except (ValueError, TypeError):
            rate = 1.0
        self.speed_spin.blockSignals(True)
        self.speed_spin.setValue(max(0.25, min(4.0, rate)))
        self.speed_spin.blockSignals(False)

        # Repeat
        repeat_mode = s.get_string("audio/playback/repeat_mode", "none")
        label = self._REPEAT_RMAP.get(repeat_mode, "Off")
        self.repeat_combo.blockSignals(True)
        self.repeat_combo.setCurrentText(label)
        self.repeat_combo.blockSignals(False)
        self.repeat_count_spin.setEnabled(label == "One")

        # Auto-pause
        auto_pause = s.get_bool("audio/playback/auto_pause", False)
        self.auto_pause_cb.blockSignals(True)
        self.auto_pause_cb.setChecked(auto_pause)
        self.auto_pause_cb.blockSignals(False)

        # Gap
        gap = s.get_int("audio/playback/gap_ms", 550)
        self.gap_spin.blockSignals(True)
        self.gap_spin.setValue(max(0, min(3000, gap)))
        self.gap_spin.blockSignals(False)

        # Cadence preset
        pre = s.get_int("audio/playback/pre_roll_ms", 200)
        gap_v = s.get_int("audio/playback/gap_ms", 550)
        post = s.get_int("audio/playback/post_roll_ms", 300)
        for name, values in self.PRESETS.items():
            if values == (pre, gap_v, post):
                self.preset_combo.blockSignals(True)
                self.preset_combo.setCurrentText(name)
                self.preset_combo.blockSignals(False)
                break

        # Column visibility
        col_vis = s.get_json("audio_player/columns_visible", None)
        if isinstance(col_vis, list) and len(col_vis) == len(_COLUMNS):
            for i, visible in enumerate(col_vis):
                self._col_visible[i] = bool(visible)
            for act in self._col_actions:
                col_idx = act.data()
                act.blockSignals(True)
                act.setChecked(bool(col_vis[col_idx]))
                act.blockSignals(False)
        self._apply_column_visibility()

        # Apply to player service
        self.player.set_playback_rate(self.speed_spin.value())
        mode_key = self._REPEAT_MAP.get(self.repeat_combo.currentText(), "none")
        self.player.set_repeat_mode(mode_key)
        self.player.set_auto_pause(self.auto_pause_cb.isChecked())

    def _save_col_settings(self) -> None:
        self.settings.set_json("audio_player/columns_visible", self._col_visible)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_speed_changed(self, value: float) -> None:
        self.player.set_playback_rate(value)

    def _on_repeat_changed(self, text: str) -> None:
        mode_key = self._REPEAT_MAP.get(text, "none")
        self.player.set_repeat_mode(mode_key)
        self.repeat_count_spin.setEnabled(text == "One")
        self.settings.set_value("audio/playback/repeat_mode", mode_key)
        self.settings.sync()

    def _on_repeat_count_changed(self, value: int) -> None:
        self.player.set_repeat_count(value)

    def _on_auto_pause_changed(self, checked: bool) -> None:
        self.player.set_auto_pause(checked)
        self.settings.set_value("audio/playback/auto_pause", checked)
        self.settings.sync()

    def _on_gap_changed(self, value: int) -> None:
        self.player.gap_ms = value
        self.settings.set_value("audio/playback/gap_ms", value)
        self.settings.sync()

    def _on_preset_changed(self, name: str) -> None:
        values = self.PRESETS.get(name)
        if not values:
            return
        pre, gap, post = values
        self.settings.set_value("audio/playback/pre_roll_ms", pre)
        self.settings.set_value("audio/playback/gap_ms", gap)
        self.settings.set_value("audio/playback/post_roll_ms", post)
        self.settings.sync()
        self.player.set_cadence(pre_roll_ms=pre, gap_ms=gap, post_roll_ms=post)
        self.gap_spin.blockSignals(True)
        self.gap_spin.setValue(gap)
        self.gap_spin.blockSignals(False)

    def _on_column_toggled(self, checked: bool) -> None:
        act = self.sender()
        if act is None:
            return
        col_idx = act.data()
        if col_idx is None:
            return
        self._col_visible[col_idx] = checked
        self._apply_column_visibility()
        self._save_col_settings()

    def _apply_column_visibility(self) -> None:
        for col, visible in enumerate(self._col_visible):
            if col == _COL_NUM:
                self.queue_table.showColumn(col)
            elif visible:
                self.queue_table.showColumn(col)
            else:
                self.queue_table.hideColumn(col)

    def _on_queue_changed(self, queue_payload: list) -> None:
        self._queue_model.load(queue_payload, self.player.current_index)
        tab = self.tab_widget.tabBar().tabText(self.tab_widget.currentIndex())
        count = len(queue_payload)
        self.tab_widget.setTabText(0, f"Queue ({count})")
        # Scroll to current row
        idx = self.player.current_index
        if 0 <= idx < count:
            model_idx = self._queue_model.index(idx, 0)
            self.queue_table.scrollTo(model_idx, QAbstractItemView.ScrollHint.EnsureVisible)

    def _on_now_playing_changed(self, payload: object) -> None:
        if not payload:
            self.now_playing_label.setText("▶  (idle)")
            self.goto_source_btn.setEnabled(False)
            return
        data = payload if isinstance(payload, dict) else {}
        label = str(data.get("label") or "(untitled)")
        ctx = data.get("context") or {}
        niqqud = ctx.get("snapshot_niqqud") or ctx.get("niqqud") or ""
        display = niqqud if niqqud and niqqud != "—" else label
        self.now_playing_label.setText(f"▶  {display}")
        has_source = bool(ctx.get("source_id") or ctx.get("kind"))
        self.goto_source_btn.setEnabled(has_source)

    def _on_state_changed(self, state: str) -> None:
        if state == "playing":
            self.play_pause_btn.setText("⏸")
            self.play_pause_btn.setToolTip("Pause  [Space]")
        elif state == "paused":
            self.play_pause_btn.setText("▶")
            self.play_pause_btn.setToolTip("Resume  [Space]")
        else:
            self.play_pause_btn.setText("▶")
            self.play_pause_btn.setToolTip("Play  [Space]")

    def _on_playback_error(self, message: str, _payload: object) -> None:
        logger.warning("Audio playback error: %s", message)

    def _on_track_finished(self, payload: object) -> None:
        """Append to History tab."""
        data = payload if isinstance(payload, dict) else {}
        label = str(data.get("label") or "(untitled)")
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}]  {label}"
        self._history_entries.insert(0, entry)
        if len(self._history_entries) > 200:
            self._history_entries = self._history_entries[:200]
        self.history_list.insertItem(0, QListWidgetItem(entry))
        if self.history_list.count() > 200:
            self.history_list.takeItem(200)

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_queue_context_menu(self, pos) -> None:
        rows = sorted({idx.row() for idx in self.queue_table.selectedIndexes()})
        if not rows:
            return
        menu = QMenu(self)

        play_act = menu.addAction("▶ Play from here")
        play_act.setEnabled(len(rows) == 1)

        remove_act = menu.addAction("Remove from Queue")
        menu.addSeparator()
        copy_heb_act = menu.addAction("Copy Hebrew")
        copy_niqqud_act = menu.addAction("Copy Niqqud")
        copy_transl_act = menu.addAction("Copy Translation")

        action = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == play_act and rows:
            self._play_from_row(rows[0])
        elif action == remove_act:
            # Remove in reverse order to preserve indices
            for r in reversed(rows):
                self.player.remove_queue_index(r)
        elif action == copy_heb_act:
            self._copy_cell(rows[0], _COL_HEBREW)
        elif action == copy_niqqud_act:
            self._copy_cell(rows[0], _COL_NIQQUD)
        elif action == copy_transl_act:
            self._copy_cell(rows[0], _COL_TRANSLATION)

    def _on_queue_row_double_clicked(self, index: QModelIndex) -> None:
        self._play_from_row(index.row())

    def _play_from_row(self, row: int) -> None:
        """Set the cursor to 'row - 1' and call next_track so it plays row."""
        self.player._current_index = row - 1  # noqa: SLF001 — internal
        saved_mode = self.player._repeat_mode  # noqa: SLF001
        self.player._repeat_mode = "none"  # noqa: SLF001
        self.player._stop_all_timers()  # noqa: SLF001
        self.player._stop_backend_only()  # noqa: SLF001
        self.player._current = None  # noqa: SLF001
        self.player._item_play_count = 0  # noqa: SLF001
        self.player._repeat_mode = saved_mode  # noqa: SLF001
        self.player._start_next_track()  # noqa: SLF001

    def _copy_cell(self, row: int, col: int) -> None:
        try:
            from PyQt6.QtWidgets import QApplication
            idx = self._queue_model.index(row, col)
            text = str(self._queue_model.data(idx, Qt.ItemDataRole.DisplayRole) or "")
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    # ── Speed hotkeys ─────────────────────────────────────────────────────────

    def _speed_up(self) -> None:
        new_val = round(min(4.0, self.speed_spin.value() + 0.1), 2)
        self.speed_spin.setValue(new_val)

    def _speed_down(self) -> None:
        new_val = round(max(0.25, self.speed_spin.value() - 0.1), 2)
        self.speed_spin.setValue(new_val)

    def _cycle_repeat(self) -> None:
        idx = self.REPEAT_MODES.index(self.repeat_combo.currentText())
        next_idx = (idx + 1) % len(self.REPEAT_MODES)
        self.repeat_combo.setCurrentText(self.REPEAT_MODES[next_idx])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _refresh_queue(self) -> None:
        """Populate queue table from current player state."""
        snapshot = self.player.queue_snapshot()
        self._queue_model.load(snapshot, self.player.current_index)
        self.tab_widget.setTabText(0, f"Queue ({len(snapshot)})")
