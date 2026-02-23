"""Premium Audio Player Panel — v2 (Task 25).

Layout:
  ┌── Now Playing bar (label + transport controls + Go to Source) ──┐
  ├── Playback controls (speed · repeat · auto-pause · gap · preset) ┤
  ├── [Queue] [Playlists] [History]       [Add All…] [⚙ Columns]   ┤
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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QInputDialog,
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
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate

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
                # Path("") serialises to "." which exists() — treat it as missing
                return "ready" if path and path != "." and os.path.exists(str(path)) else "missing"
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


# ── Source picker dialog (premium) ────────────────────────────────────────────


class AddAllToQueueDialog(QDialog):
    """Premium dialog — select source kind / project / documents / add mode.

    Self-sufficient: uses DBService.get_instance() directly so it works
    even when AudioPlayerPanel was created without a ``db=`` argument.

    Kinds supported:
      - Sentences  → filterable by document (multi-select with live search)
      - Lemmas (Dictionary) → project-wide, no document filter
      - Terms      → project-wide, no document filter
    """

    # Maps combo index → (worker kind string, show doc filter)
    _KIND_META = [
        ("sentence", True),
        ("lemma", False),
        ("term", False),
    ]

    def __init__(self, *, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add All to Queue")
        self.setMinimumWidth(460)
        self.setMinimumHeight(420)

        self._project_ids: List[int] = []
        self._db = None
        try:
            from app.services.db_service import DBService
            self._db = DBService.get_instance()
        except Exception as exc:
            logger.warning("AddAllToQueueDialog: no DBService: %s", exc)

        self._build_ui()
        self._load_projects()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── Top form ──────────────────────────────────────────────────
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["Sentences", "Lemmas (Dictionary)", "Terms"])
        form.addRow("Source kind:", self.kind_combo)

        self.project_combo = QComboBox()
        self.project_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        form.addRow("Project:", self.project_combo)

        root.addLayout(form)

        # ── Document filter group (Sentences only) ────────────────────
        self.doc_group = QGroupBox("Document filter  (leave empty = all documents)")
        doc_vl = QVBoxLayout(self.doc_group)
        doc_vl.setSpacing(4)

        # Search bar
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        search_lbl = QLabel("🔍")
        search_lbl.setFixedWidth(18)
        self.doc_search = QLineEdit()
        self.doc_search.setPlaceholderText("Type to filter documents…")
        self.doc_search.setClearButtonEnabled(True)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self.doc_search)
        doc_vl.addLayout(search_row)

        # Document list
        self.doc_list = QListWidget()
        self.doc_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.doc_list.setAlternatingRowColors(True)
        self.doc_list.setMinimumHeight(160)
        self.doc_list.setToolTip(
            "Select specific documents (Ctrl+Click for multi-select).\n"
            "Leave nothing selected to use all documents."
        )
        doc_vl.addWidget(self.doc_list, 1)

        # Buttons + count
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(80)
        self.clear_sel_btn = QPushButton("Clear")
        self.clear_sel_btn.setFixedWidth(60)
        self.doc_sel_label = QLabel("Selected: 0 / 0")
        self.doc_sel_label.setStyleSheet("color: gray; font-size: 11px;")
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.clear_sel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.doc_sel_label)
        doc_vl.addLayout(btn_row)
        root.addWidget(self.doc_group)

        # ── Add mode ──────────────────────────────────────────────────
        mode_form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Append", "After current", "Prepend"])
        mode_form.addRow("Add mode:", self.mode_combo)
        root.addLayout(mode_form)

        # ── Estimate label ────────────────────────────────────────────
        self.estimate_label = QLabel("(select a project to see estimate)")
        self.estimate_label.setStyleSheet("color: #555; font-style: italic;")
        self.estimate_label.setWordWrap(True)
        root.addWidget(self.estimate_label)

        root.addStretch()

        # ── Dialog buttons ────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Add to Queue")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # ── Connect signals ───────────────────────────────────────────
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        self.doc_search.textChanged.connect(self._filter_docs)
        self.select_all_btn.clicked.connect(self._select_all_docs)
        self.clear_sel_btn.clicked.connect(self.doc_list.clearSelection)
        self.doc_list.itemSelectionChanged.connect(self._update_sel_label)
        self.doc_list.itemSelectionChanged.connect(self._update_estimate)

        # Initial state
        self._on_kind_changed(0)

    # ── Data loading ──────────────────────────────────────────────────

    def _load_projects(self) -> None:
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self._project_ids = []
        if not self._db:
            self.project_combo.addItem("(no database connection)")
            self.project_combo.blockSignals(False)
            return
        try:
            from app.services.project_service import ProjectService
            with self._db.get_session() as session:
                projects = ProjectService().list_projects(session)
            for p in projects:
                name = getattr(p, "name", None) or f"Project {p.project_id}"
                self.project_combo.addItem(name)
                self._project_ids.append(p.project_id)
        except Exception as exc:
            logger.warning("AddAllToQueueDialog: load projects failed: %s", exc)
            self.project_combo.addItem("(error loading projects)")
        self.project_combo.blockSignals(False)
        self._on_project_changed(self.project_combo.currentIndex())

    def _load_documents(self, project_id: int) -> None:
        """Populate doc_list for the given project (sentences kind only)."""
        self.doc_list.clear()
        if not self._db or project_id < 0:
            return
        try:
            from sqlalchemy import select
            from app.infra.sa_models import SourceDocument, SourceCorpus
            with self._db.get_session() as session:
                stmt = (
                    select(
                        SourceDocument.doc_id,
                        SourceDocument.file_name,
                        SourceDocument.sentence_count,
                        SourceDocument.level,
                    )
                    .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                    .where(SourceCorpus.project_id == project_id)
                    .where(SourceDocument.status == "processed")
                    .order_by(SourceDocument.file_name.asc())
                )
                rows = session.execute(stmt).all()
            for doc_id, file_name, sent_count, level in rows:
                count_str = f"{sent_count:,}" if sent_count else "?"
                level_str = f"  [{level}]" if level else ""
                label = f"{file_name}    {count_str} sent.{level_str}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, doc_id)
                item.setToolTip(f"doc_id={doc_id}  •  {count_str} sentences{level_str}")
                self.doc_list.addItem(item)
        except Exception as exc:
            logger.warning("AddAllToQueueDialog: load docs failed: %s", exc)
        self._update_sel_label()

    # ── Slot handlers ─────────────────────────────────────────────────

    def _on_kind_changed(self, index: int) -> None:
        _, show_docs = self._KIND_META[index] if index < len(self._KIND_META) else ("sentence", True)
        self.doc_group.setVisible(show_docs)
        self._update_estimate()

    def _on_project_changed(self, index: int) -> None:
        pid = self._get_project_id(index)
        kind_idx = self.kind_combo.currentIndex()
        _, show_docs = self._KIND_META[kind_idx] if kind_idx < len(self._KIND_META) else ("sentence", True)
        if show_docs:
            self._load_documents(pid)
        self._update_estimate()

    def _filter_docs(self, text: str) -> None:
        """Live filter: hide items that don't match the search text."""
        lc = text.lower()
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            item.setHidden(lc not in item.text().lower())
        self._update_sel_label()

    def _select_all_docs(self) -> None:
        """Select all currently visible items."""
        self.doc_list.clearSelection()
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            if not item.isHidden():
                item.setSelected(True)

    def _update_sel_label(self) -> None:
        selected = len(self.doc_list.selectedItems())
        visible = sum(1 for i in range(self.doc_list.count()) if not self.doc_list.item(i).isHidden())
        total = self.doc_list.count()
        if total == 0:
            self.doc_sel_label.setText("No documents")
        elif selected == 0:
            self.doc_sel_label.setText(f"All {visible:,} shown  (none selected = all docs)")
        else:
            self.doc_sel_label.setText(f"Selected: {selected:,} / {visible:,} shown  ({total:,} total)")

    def _update_estimate(self) -> None:
        """Fast COUNT estimate shown in the dialog."""
        pid = self._get_project_id(self.project_combo.currentIndex())
        kind_idx = self.kind_combo.currentIndex()
        kind, _ = self._KIND_META[kind_idx] if kind_idx < len(self._KIND_META) else ("sentence", True)

        if pid < 0 or not self._db:
            self.estimate_label.setText("(select a project to see estimate)")
            return
        try:
            from sqlalchemy import select, func
            with self._db.get_session() as session:
                if kind == "sentence":
                    from app.infra.sa_models import DocumentSentence, SourceDocument, SourceCorpus
                    doc_ids = self.selected_doc_ids()
                    stmt = (
                        select(func.count(DocumentSentence.sentence_id))
                        .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
                        .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                        .where(SourceCorpus.project_id == pid)
                    )
                    if doc_ids:
                        stmt = stmt.where(DocumentSentence.doc_id.in_(doc_ids))
                    count = session.execute(stmt).scalar() or 0
                    src = f"{len(doc_ids)} document(s)" if doc_ids else "all documents"
                    self.estimate_label.setText(f"~{count:,} sentences from {src}")
                elif kind == "lemma":
                    from app.infra.sa_models import Lemma
                    count = session.execute(
                        select(func.count(Lemma.lemma_id))
                        .where(Lemma.project_id == pid)
                        .where(Lemma.is_noise == 0)
                    ).scalar() or 0
                    self.estimate_label.setText(f"~{count:,} lemmas (project-wide)")
                else:  # term
                    from app.infra.sa_models import TermCluster
                    count = session.execute(
                        select(func.count(TermCluster.cluster_id))
                        .where(TermCluster.project_id == pid)
                        .where(TermCluster.is_noise == 0)
                        .where(TermCluster.curation_status != "rejected")
                    ).scalar() or 0
                    self.estimate_label.setText(f"~{count:,} terms (project-wide)")
        except Exception as exc:
            logger.debug("AddAllToQueueDialog estimate failed: %s", exc)
            self.estimate_label.setText("(estimate unavailable)")

    # ── Public getters ────────────────────────────────────────────────

    def _get_project_id(self, combo_index: int) -> int:
        if combo_index < 0 or combo_index >= len(self._project_ids):
            return -1
        return self._project_ids[combo_index]

    def selected_kind(self) -> str:
        idx = self.kind_combo.currentIndex()
        kind, _ = self._KIND_META[idx] if idx < len(self._KIND_META) else ("sentence", True)
        return kind

    def selected_project_id(self) -> int:
        return self._get_project_id(self.project_combo.currentIndex())

    def selected_doc_ids(self) -> List[int]:
        """Return list of selected doc_ids, or [] for all documents."""
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.doc_list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole) is not None
        ]

    def selected_add_mode(self) -> str:
        idx = self.mode_combo.currentIndex()
        return ["append", "after_current", "prepend"][max(0, idx)]


# ── Panel ─────────────────────────────────────────────────────────────────────


class AudioPlayerPanel(QWidget):
    """Premium audio player dock panel (v2)."""

    go_to_source_requested = pyqtSignal(dict)
    data_changed = pyqtSignal(dict)

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
        self._selected_source_payload: Optional[Dict[str, Any]] = None
        self._selected_queue_row_count: int = 0
        self._refresh_in_progress: bool = False

        self._init_ui()
        self._connect_signals()
        self._restore_settings()
        self._refresh_queue()
        self._init_auto_refresh()

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

        self.add_all_btn = QPushButton("Add All…")
        self.add_all_btn.setToolTip("Add all items from a project source to the queue")
        self.add_all_btn.setFixedWidth(78)
        self.add_all_btn.clicked.connect(self._on_add_all_clicked)
        tab_header.addWidget(self.add_all_btn)

        self.refresh_queue_btn = QPushButton("↻")
        self.refresh_queue_btn.setToolTip("Refresh Niqqud / Translation / Source from DB")
        self.refresh_queue_btn.setFixedWidth(32)
        self.refresh_queue_btn.clicked.connect(self._refresh_display_contexts)
        tab_header.addWidget(self.refresh_queue_btn)

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
        self.queue_table.selectionModel().selectionChanged.connect(self._on_queue_selection_changed)

        # Play delegate on Status column: ▶ button for ready tracks
        self._queue_play_delegate = AudioPlayDelegate(
            self.queue_table,
            on_play_clicked=self._on_queue_play_cell_clicked,
        )
        self.queue_table.setItemDelegateForColumn(_COL_STATUS, self._queue_play_delegate)

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
        self.goto_source_btn.clicked.connect(self._on_goto_source_clicked)

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

    def _init_auto_refresh(self) -> None:
        """Periodic non-blocking queue overlay refresh.

        Keeps Niqqud/Translation/Source in sync with source tables when edits are
        performed outside Audio Player. Refresh button remains as explicit manual tool.
        """
        interval = int(self.settings.get_int("audio_player/auto_refresh_ms", 2500) or 2500)
        interval = max(1200, min(10000, interval))
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(interval)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_tick)
        self._auto_refresh_timer.start()

    def _on_auto_refresh_tick(self) -> None:
        if not self.isVisible():
            return
        if not self.player._tracks:  # noqa: SLF001 - bounded list in dock state
            return
        self._refresh_display_contexts()

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
        self._on_queue_selection_changed()

    def _queue_row_context(self, row: int) -> Optional[Dict[str, Any]]:
        snapshot = self.player.queue_snapshot()
        if row < 0 or row >= len(snapshot):
            return None
        payload = snapshot[row] if isinstance(snapshot[row], dict) else {}
        ctx = payload.get("context") or {}
        return ctx if isinstance(ctx, dict) else None

    def _source_payload_from_context(self, ctx: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not ctx:
            return None
        kind_raw = ctx.get("kind")
        if not kind_raw:
            return None
        kind = self._normalize_queue_kind(str(kind_raw))
        project_id = ctx.get("project_id")
        source_id = ctx.get("source_id")
        if source_id is not None:
            try:
                source_id_int = int(source_id)
            except (TypeError, ValueError):
                source_id_int = None
            if source_id_int is not None:
                return {
                    "kind": kind,
                    "source_id": source_id_int,
                    "project_id": project_id,
                }
        if kind in {"sentence", "surface"}:
            source_text = str(ctx.get("snapshot_hebrew") or ctx.get("source_text") or "").strip()
            if source_text and project_id is not None:
                return {
                    "kind": "sentence",
                    "project_id": project_id,
                    "source_text": source_text,
                }
        return None

    @staticmethod
    def _normalize_queue_kind(kind: str) -> str:
        raw = (kind or "").strip().lower()
        if raw in {"term_cluster", "terms"}:
            return "term"
        if raw in {"surface", "sentences"}:
            return "sentence"
        return raw

    def _on_queue_selection_changed(self, *_args) -> None:
        selected_rows = sorted({idx.row() for idx in self.queue_table.selectionModel().selectedRows()})
        self._selected_queue_row_count = len(selected_rows)
        if len(selected_rows) != 1:
            self._selected_source_payload = None
            self._update_goto_source_state()
            return
        self._selected_source_payload = self._source_payload_from_context(
            self._queue_row_context(selected_rows[0])
        )
        self._update_goto_source_state()

    def _update_goto_source_state(self) -> None:
        if self._selected_queue_row_count > 1:
            self.goto_source_btn.setEnabled(False)
            return
        if self._selected_source_payload is not None:
            self.goto_source_btn.setEnabled(True)
            return
        self.goto_source_btn.setEnabled(
            self._source_payload_from_context(self._current_track_context()) is not None
        )

    def _on_now_playing_changed(self, payload: object) -> None:
        if not payload:
            self.now_playing_label.setText("▶  (idle)")
            self._update_goto_source_state()
            return
        data = payload if isinstance(payload, dict) else {}
        label = str(data.get("label") or "(untitled)")
        ctx = data.get("context") or {}
        niqqud = ctx.get("snapshot_niqqud") or ctx.get("niqqud") or ""
        display = niqqud if niqqud and niqqud != "—" else label
        self.now_playing_label.setText(f"▶  {display}")
        self._update_goto_source_state()

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
        self._sync_play_stats_to_db(data)

    def _current_track_context(self) -> Optional[Dict[str, Any]]:
        idx = self.player.current_index
        if idx < 0:
            return None
        snapshot = self.player.queue_snapshot()
        if idx >= len(snapshot):
            return None
        payload = snapshot[idx] if isinstance(snapshot[idx], dict) else {}
        ctx = payload.get("context") or {}
        return ctx if isinstance(ctx, dict) else None

    def _on_goto_source_clicked(self) -> None:
        payload = self._selected_source_payload
        if payload is None:
            payload = self._source_payload_from_context(self._current_track_context())
        if payload is None:
            return
        self.go_to_source_requested.emit(payload)

    def _sync_play_stats_to_db(self, payload: Dict[str, Any]) -> None:
        """Best-effort sync of queue play counters/history for DB-backed queue rows."""
        from datetime import datetime, timezone

        ctx = payload.get("context") or {}
        if not isinstance(ctx, dict):
            return
        item_id = ctx.get("item_id")
        if item_id is None:
            return
        try:
            item_id_int = int(item_id)
        except (TypeError, ValueError):
            return

        try:
            from app.services.audio_queue_service import AudioQueueService
            from app.services.db_service import DBService

            with DBService.get_instance().get_session() as session:
                AudioQueueService().mark_played(
                    session,
                    item_id_int,
                    rate_used=float(self.player.get_playback_rate() or 1.0),
                )
                session.commit()
        except Exception as exc:
            logger.debug("Audio queue play sync skipped: %s", exc)
            return

        last_played_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for track in self.player._tracks:  # noqa: SLF001 - bounded list in dock state
            track_ctx = track.context if isinstance(track.context, dict) else None
            if not track_ctx:
                continue
            if track_ctx.get("item_id") == item_id_int:
                track_ctx["last_played_at"] = last_played_at
                break

    # ── Context menu ──────────────────────────────────────────────────────────

    def _on_add_all_clicked(self) -> None:
        """Open premium source picker dialog then launch AudioQueuePopulateWorker."""
        dlg = AddAllToQueueDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        project_id = dlg.selected_project_id()
        if project_id < 0:
            QMessageBox.warning(self, "Add All", "No project selected. Please open a project first.")
            return
        kind = dlg.selected_kind()
        add_mode = dlg.selected_add_mode()
        doc_ids = dlg.selected_doc_ids()  # [] = all documents
        current_pos = self.player.current_index

        try:
            from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
            from app.ui.workers import AudioQueuePopulateWorker
        except ImportError as exc:
            QMessageBox.critical(self, "Add All", f"Import error:\n{exc}")
            return

        # Use 1 as placeholder total; real total set by first progress signal
        progress_dialog = BatchProgressDialogV3(parent=self, total=1)
        progress_dialog.show()

        worker = AudioQueuePopulateWorker(
            kind=kind,
            project_id=project_id,
            doc_ids=doc_ids,
            add_mode=add_mode,
            current_position=current_pos,
        )
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda r: self._on_add_all_finished(r, progress_dialog))
        worker.error.connect(lambda e: self._on_add_all_error(e, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)

        self.add_all_btn.setEnabled(False)
        worker.finished.connect(lambda _: self.add_all_btn.setEnabled(True))
        worker.error.connect(lambda _: self.add_all_btn.setEnabled(True))
        worker.start()
        self._populate_worker = worker  # keep reference

    def _on_add_all_finished(self, result: dict, progress_dialog) -> None:
        progress_dialog.set_completed()
        progress_dialog.accept()
        added = result.get("added", 0)
        failed = result.get("failed", 0)
        cancelled = result.get("cancelled", False)
        add_mode = result.get("add_mode", "append")
        new_item_ids = result.get("new_item_ids", [])
        if added > 0 and new_item_ids:
            self._load_db_queue_to_player(add_mode, new_item_ids=new_item_ids)
            # Defer context refresh to next event loop tick (non-blocking)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._refresh_display_contexts)
        msg = f"Added {added:,} items to queue."
        if cancelled:
            msg += " (cancelled)"
        if failed:
            msg += f"\n{failed} items failed."
        QMessageBox.information(self, "Add All — Done", msg)
        self._refresh_queue()

    def _load_db_queue_to_player(self, add_mode: str = "append", *, new_item_ids: Optional[List[int]] = None) -> None:
        """Sync newly-added DB queue items into the in-memory AudioPlayerService queue.

        Only the specific rows whose item_ids are in *new_item_ids* (the rows
        just inserted by the current worker run) are candidates.  This prevents
        stale rows from previous sessions polluting the queue.

        Additionally deduplicates by (kind, source_id) so clicking "Add All"
        multiple times in a row never adds the same source content twice.
        """
        if not new_item_ids:
            return  # guard: no new rows to load (covers stale-DB and empty run)

        # ── Step 1: Load candidate DTOs from DB (fatal on failure) ───────────
        # get_queue() returns plain DTOs, safe to use after session closes.
        candidate_items: list = []
        try:
            from app.services.db_service import DBService
            from app.services.audio_queue_service import AudioQueueService
            db = DBService.get_instance()
            id_set = set(new_item_ids)
            with db.get_session() as session:
                all_db_items = AudioQueueService().get_queue(session)
            candidate_items = [item for item in all_db_items if item.item_id in id_set]
            logger.debug("_load_db_queue_to_player: %d candidates found", len(candidate_items))
        except Exception as exc:
            logger.warning("_load_db_queue_to_player: DB load failed: %s", exc, exc_info=True)
            return

        if not candidate_items:
            return

        # ── Step 2: Best-effort path resolution ──────────────────────────────────
        # Non-fatal: if this fails items are still added (just without a resolved path).
        # Path A: direct lookup by audio_asset_id (reliable — filled by worker _resolve_audio_assets)
        # Path B: norm_text lookup fallback for items without audio_asset_id
        resolved_paths: Dict[int, Path] = {}
        try:
            from app.services.db_service import DBService as _DBService
            from app.infra.sa_models import AudioAsset as _AudioAsset
            from app.services.audio_playback_service import _get_app_dir
            from sqlalchemy import select as _sa_select, desc as _sa_desc
            _db = _DBService.get_instance()
            app_dir = _get_app_dir()

            def _to_abs_path(rel_path_str):
                if not rel_path_str:
                    return None
                rel = Path(str(rel_path_str))
                if rel.is_absolute() or ".." in rel.parts:
                    return None
                abs_path = app_dir / rel
                return abs_path if abs_path.exists() else None

            # Path A: direct lookup by audio_asset_id
            items_with_aid = [(item.item_id, item.audio_asset_id)
                              for item in candidate_items if item.audio_asset_id]
            if items_with_aid:
                aid_to_item: Dict[int, int] = {aid: iid for iid, aid in items_with_aid}
                with _db.get_session() as _sess:
                    a_rows = _sess.execute(
                        _sa_select(_AudioAsset.asset_id, _AudioAsset.audio_rel_path)
                        .where(_AudioAsset.asset_id.in_(list(aid_to_item.keys())))
                        .where(_AudioAsset.asset_status == "ready")
                        .where(_AudioAsset.audio_rel_path.isnot(None))
                    ).all()
                for aid, rel_path in a_rows:
                    abs_path = _to_abs_path(rel_path)
                    if abs_path and aid in aid_to_item:
                        resolved_paths[aid_to_item[aid]] = abs_path

            # Path B: norm_text lookup for items without audio_asset_id (fallback)
            b_candidates = [item for item in candidate_items
                            if item.item_id not in resolved_paths and item.snapshot_hebrew]
            if b_candidates:
                _kind_map = {"lemma": "lemma", "term": "term_cluster", "sentence": "sentence"}
                item_norms: List[tuple] = []
                for item in b_candidates:
                    try:
                        from app.domain.normalization.normalizer import normalize_for_tm as _ntm
                        kind_str = _kind_map.get(item.kind, item.kind)
                        norm = _ntm("he", item.snapshot_hebrew, kind_str).norm or item.snapshot_hebrew
                    except Exception:
                        norm = item.snapshot_hebrew
                    if norm:
                        item_norms.append((item.item_id, norm))
                if item_norms:
                    all_norms = list({norm for _, norm in item_norms})
                    with _db.get_session() as _sess:
                        b_rows = _sess.execute(
                            _sa_select(_AudioAsset.norm_text, _AudioAsset.audio_rel_path)
                            .where(_AudioAsset.lang == "he")
                            .where(_AudioAsset.norm_text.in_(all_norms))
                            .where(_AudioAsset.asset_status == "ready")
                            .where(_AudioAsset.audio_rel_path.isnot(None))
                            .order_by(_sa_desc(_AudioAsset.updated_at))
                        ).all()
                    norm_to_path: Dict[str, Path] = {}
                    for norm_text, rel_path in b_rows:
                        if norm_text not in norm_to_path:
                            abs_path = _to_abs_path(rel_path)
                            if abs_path:
                                norm_to_path[norm_text] = abs_path
                    for item_id, norm in item_norms:
                        if norm in norm_to_path and item_id not in resolved_paths:
                            resolved_paths[item_id] = norm_to_path[norm]
        except Exception as path_exc:
            logger.warning("_load_db_queue_to_player: path resolution failed (%s)", path_exc, exc_info=True)

        logger.debug(
            "_load_db_queue_to_player: %d/%d candidates resolved to audio path",
            len(resolved_paths), len(candidate_items),
        )

        # ── Step 3: Dedup + in-place path upgrade ─────────────────────────────
        # Build a (kind, source_id) → existing AudioTrack map so that when the
        # same source re-appears in a new Add All run we can UPGRADE an old
        # unresolved track (path == ".") rather than silently skipping it.
        existing_track_map: Dict[tuple, Any] = {}
        for t in self.player._tracks:  # noqa: SLF001
            if isinstance(t.context, dict):
                k = (t.context.get("kind"), t.context.get("source_id"))
                if k[0] is not None and k[1] is not None:
                    existing_track_map[k] = t

        upgraded = 0
        new_items = []
        for item in candidate_items:
            key = (item.kind, item.source_id)
            existing = existing_track_map.get(key)
            if existing is None:
                new_items.append(item)
            elif str(existing.path) in ("", ".") and item.item_id in resolved_paths:
                # Old broken track — upgrade its path in-place so it becomes playable
                existing.path = resolved_paths[item.item_id]
                existing.context["audio_status"] = "ready"
                upgraded += 1
            # else: existing track already has a valid path → leave it

        if new_items:
            self.player.enqueue_from_db(new_items, mode=add_mode, resolved_paths=resolved_paths)
        if upgraded:
            self.player._emit_queue_changed()  # noqa: SLF001 — refresh Status column
        logger.debug(
            "_load_db_queue_to_player: added %d new items, upgraded %d existing unresolved tracks",
            len(new_items), upgraded,
        )

    def _on_add_all_error(self, msg: str, progress_dialog) -> None:
        progress_dialog.set_stage(f"Error: {msg[:80]}")
        progress_dialog.accept()
        QMessageBox.critical(self, "Add All — Error", msg)

    def _selected_queue_rows(self) -> List[int]:
        return sorted({idx.row() for idx in self.queue_table.selectionModel().selectedRows()})

    def _track_at_row(self, row: int) -> Optional[Dict[str, Any]]:
        snapshot = self.player.queue_snapshot()
        if row < 0 or row >= len(snapshot):
            return None
        track = snapshot[row]
        return track if isinstance(track, dict) else None

    def _track_ctx_at_row(self, row: int) -> Dict[str, Any]:
        track = self._track_at_row(row) or {}
        ctx = track.get("context") or {}
        return ctx if isinstance(ctx, dict) else {}

    def _queue_source_key_from_context(self, ctx: Dict[str, Any]) -> Optional[Tuple[str, int, Optional[int]]]:
        kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
        source_id = ctx.get("source_id")
        if not kind or source_id is None:
            return None
        try:
            source_id_int = int(source_id)
        except (TypeError, ValueError):
            return None
        project_id_raw = ctx.get("project_id")
        try:
            project_id = int(project_id_raw) if project_id_raw is not None else None
        except (TypeError, ValueError):
            project_id = None
        return (kind, source_id_int, project_id)

    def _mark_queue_sources_stale(self, source_keys: List[Tuple[str, int, Optional[int]]]) -> None:
        if not source_keys:
            return
        try:
            from app.services.audio_queue_service import AudioQueueService
            from app.services.db_service import DBService

            svc = AudioQueueService()
            with DBService.get_instance().get_session() as session:
                for kind, source_id, project_id in source_keys:
                    svc.mark_stale_by_source(
                        session,
                        kind=kind,
                        source_id=source_id,
                        project_id=project_id,
                    )
                session.commit()
        except Exception as exc:
            logger.debug("mark stale by source skipped: %s", exc)

        source_set = set(source_keys)
        for track in self.player._tracks:  # noqa: SLF001
            ctx = track.context if isinstance(track.context, dict) else None
            if not ctx:
                continue
            key = self._queue_source_key_from_context(ctx)
            if key in source_set:
                ctx["is_stale"] = True
                ctx["audio_status"] = "stale"
        self._refresh_queue()

    def _build_translate_items(self, rows: List[int]):
        from app.services.batch_mt_translate_service import BatchTranslateItem
        from app.services.db_service import DBService
        from app.services.project_service import ProjectService

        project_lang_map: Dict[int, Tuple[str, str]] = {}

        def _get_lang_pair(project_id: Optional[int]) -> Tuple[str, str]:
            if project_id is None:
                return ("he", "ru")
            if project_id in project_lang_map:
                return project_lang_map[project_id]
            src, tgt = "he", "ru"
            try:
                with DBService.get_instance().get_session() as session:
                    project = ProjectService().get_project(session, int(project_id))
                if project:
                    src = str(getattr(project, "src_lang", "") or src)
                    tgt = str(getattr(project, "tgt_lang", "") or tgt)
            except Exception:
                pass
            project_lang_map[int(project_id)] = (src, tgt)
            return src, tgt

        items = []
        for row in rows:
            track = self._track_at_row(row) or {}
            ctx = self._track_ctx_at_row(row)
            kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
            source_text = str(ctx.get("snapshot_hebrew") or track.get("label") or "").strip()
            if not source_text:
                continue
            project_id_raw = ctx.get("project_id")
            try:
                project_id = int(project_id_raw) if project_id_raw is not None else None
            except (TypeError, ValueError):
                project_id = None
            src_lang, tgt_lang = _get_lang_pair(project_id)
            source_id = ctx.get("source_id")
            entity_type = {
                "lemma": "lemma",
                "term": "term_cluster",
                "sentence": "surface",
            }.get(kind)
            if not entity_type:
                continue
            entity_id = str(source_id if source_id is not None else row)
            items.append(
                BatchTranslateItem(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    source_text=source_text,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    current_translation=str(ctx.get("snapshot_translation") or ""),
                    project_id=project_id,
                )
            )
        return items

    def _build_audio_generation_items(self, rows: List[int]) -> List[Dict[str, Any]]:
        from app.domain.normalization.normalizer import normalize_for_tm

        items: List[Dict[str, Any]] = []
        for row in rows:
            track = self._track_at_row(row) or {}
            ctx = self._track_ctx_at_row(row)
            kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
            if kind not in {"sentence", "lemma", "term"}:
                continue
            source_text = str(ctx.get("snapshot_hebrew") or track.get("label") or "").strip()
            if not source_text:
                continue
            src_lang = str(ctx.get("src_lang") or "he").strip() or "he"
            norm_kind = {"term": "term_cluster", "sentence": "surface"}.get(kind, kind)
            src_norm = normalize_for_tm(src_lang, source_text, norm_kind).norm
            if not src_norm:
                continue
            row_id = ctx.get("item_id") or ctx.get("source_id") or row
            items.append(
                {
                    "row_id": str(row_id),
                    "src_text": source_text,
                    "src_lang": src_lang,
                    "src_norm": src_norm,
                }
            )
        return items

    def _build_pronunciation_selected_items(self, rows: List[int]) -> List[Dict[str, str]]:
        from app.domain.normalization.normalizer import normalize_for_tm

        items: List[Dict[str, str]] = []
        for row in rows:
            track = self._track_at_row(row) or {}
            ctx = self._track_ctx_at_row(row)
            kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
            source_text = str(ctx.get("snapshot_hebrew") or track.get("label") or "").strip()
            if not source_text:
                continue
            src_lang = str(ctx.get("src_lang") or "he").strip() or "he"
            source_group = {
                "lemma": "lemmas",
                "term": "terms",
                "sentence": "sentences",
            }.get(kind)
            if source_group is None:
                continue
            src_norm = normalize_for_tm(src_lang, source_text, "surface").norm
            if not src_norm:
                continue
            items.append(
                {
                    "src_lang": src_lang,
                    "src_text": source_text,
                    "src_norm": src_norm,
                    "source_group": source_group,
                }
            )
        return items

    def _on_queue_context_menu(self, pos) -> None:
        rows = self._selected_queue_rows()
        if not rows:
            return

        first_ctx = self._track_ctx_at_row(rows[0])
        first_kind = self._normalize_queue_kind(str(first_ctx.get("kind") or ""))
        source_payload = self._source_payload_from_context(first_ctx) if len(rows) == 1 else None

        translate_items = self._build_translate_items(rows)
        audio_items = self._build_audio_generation_items(rows)
        pronunciation_items = self._build_pronunciation_selected_items(rows)

        menu = QMenu(self)

        play_act = menu.addAction("Play from here")
        play_act.setEnabled(len(rows) == 1)

        go_to_source_act = menu.addAction("Go to Source")
        go_to_source_act.setEnabled(len(rows) == 1 and source_payload is not None)

        remove_act = menu.addAction("Remove from Queue")
        menu.addSeparator()

        translate_act = menu.addAction(f"Translate Selected ({len(rows)})...")
        translate_act.setEnabled(len(translate_items) > 0)

        niqqud_act = menu.addAction(f"Niqqudize Selected ({len(rows)})...")
        niqqud_act.setEnabled(len(pronunciation_items) > 0)

        regen_audio_act = menu.addAction(f"Regenerate Audio Selected ({len(rows)})...")
        regen_audio_act.setEnabled(len(audio_items) > 0)

        edit_translation_act = menu.addAction("Edit Translation...")
        edit_translation_act.setEnabled(len(rows) == 1)
        clear_translation_act = menu.addAction(f"Clear Translation ({len(rows)})...")
        clear_translation_act.setEnabled(len(rows) > 0)

        edit_pron_act = menu.addAction("Mispronounced -> Edit Pronunciation...")
        edit_pron_act.setEnabled(len(rows) == 1 and first_kind in {"lemma", "term"})

        edit_sentence_act = menu.addAction("Edit Sentence Niqqud...")
        edit_sentence_act.setEnabled(len(rows) == 1 and first_kind == "sentence")

        menu.addSeparator()
        copy_heb_act = menu.addAction("Copy Hebrew")
        copy_niqqud_act = menu.addAction("Copy Niqqud")
        copy_transl_act = menu.addAction("Copy Translation")

        action = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == play_act and rows:
            self._play_from_row(rows[0])
        elif action == go_to_source_act and source_payload is not None:
            self.go_to_source_requested.emit(source_payload)
        elif action == remove_act:
            for r in reversed(rows):
                self.player.remove_queue_index(r)
        elif action == translate_act:
            self._on_queue_translate_selected(rows)
        elif action == niqqud_act:
            self._on_queue_niqqudize_selected(rows)
        elif action == regen_audio_act:
            self._on_queue_regenerate_audio_selected(rows)
        elif action == edit_translation_act and rows:
            self._on_queue_edit_translation(rows[0])
        elif action == clear_translation_act and rows:
            self._on_queue_clear_translation(rows)
        elif action == edit_pron_act and rows:
            self._on_queue_edit_pronunciation(rows[0])
        elif action == edit_sentence_act and rows:
            self._on_queue_edit_sentence_niqqud(rows[0])
        elif action == copy_heb_act:
            self._copy_cell(rows[0], _COL_HEBREW)
        elif action == copy_niqqud_act:
            self._copy_cell(rows[0], _COL_NIQQUD)
        elif action == copy_transl_act:
            self._copy_cell(rows[0], _COL_TRANSLATION)

    def _source_keys_from_rows(self, rows: List[int]) -> List[Tuple[str, int, Optional[int]]]:
        keys: List[Tuple[str, int, Optional[int]]] = []
        for row in rows:
            key = self._queue_source_key_from_context(self._track_ctx_at_row(row))
            if key is not None:
                keys.append(key)
        # Deduplicate while preserving stable order.
        return list(dict.fromkeys(keys))

    def _emit_data_changed(
        self,
        *,
        fields: List[str],
        source_keys: Optional[List[Tuple[str, int, Optional[int]]]] = None,
    ) -> None:
        """Broadcast cross-view refresh hint to AppWindow (best-effort)."""
        keys = list(source_keys or [])
        project_ids = sorted({int(pid) for _k, _sid, pid in keys if pid is not None})
        payload = {
            "fields": sorted({str(f).strip().lower() for f in (fields or []) if str(f).strip()}),
            "project_ids": project_ids,
            "source_keys": [
                {
                    "kind": kind,
                    "source_id": int(source_id),
                    "project_id": int(project_id) if project_id is not None else None,
                }
                for kind, source_id, project_id in keys
            ],
        }
        try:
            self.data_changed.emit(payload)
        except Exception as exc:
            logger.debug("AudioPlayerPanel data_changed emit skipped: %s", exc)

    def _rows_for_source_keys(self, source_keys: List[Tuple[str, int, Optional[int]]]) -> List[int]:
        if not source_keys:
            return []
        source_set = set(source_keys)
        rows: List[int] = []
        for idx, track in enumerate(self.player._tracks):  # noqa: SLF001
            ctx = track.context if isinstance(track.context, dict) else {}
            key = self._queue_source_key_from_context(ctx)
            if key is not None and key in source_set:
                rows.append(idx)
        return rows

    def _clear_queue_sources_stale(self, source_keys: List[Tuple[str, int, Optional[int]]]) -> None:
        if not source_keys:
            return
        try:
            from app.services.audio_queue_service import AudioQueueService
            from app.services.db_service import DBService

            svc = AudioQueueService()
            with DBService.get_instance().get_session() as session:
                for kind, source_id, project_id in source_keys:
                    item_ids = svc.find_stale_by_source(
                        session,
                        kind=kind,
                        source_id=source_id,
                        project_id=project_id,
                    )
                    for item_id in item_ids:
                        svc.update_item_snapshot(session, item_id, is_stale=False)
                session.commit()
        except Exception as exc:
            logger.debug("clear stale by source skipped: %s", exc)

        source_set = set(source_keys)
        for track in self.player._tracks:  # noqa: SLF001
            ctx = track.context if isinstance(track.context, dict) else None
            if not ctx:
                continue
            key = self._queue_source_key_from_context(ctx)
            if key in source_set:
                ctx["is_stale"] = False
                if ctx.get("audio_status") == "stale":
                    ctx["audio_status"] = "ready"

    def _refresh_audio_paths_for_rows(self, rows: List[int], *, clear_stale_if_ready: bool) -> int:
        if not rows:
            return 0
        try:
            from app.domain.normalization.normalizer import normalize_for_tm
            from app.services.audio_playback_service import AudioPlaybackService
            from app.services.db_service import DBService
        except Exception:
            return 0

        updated = 0
        unique_rows = sorted(set(rows))
        try:
            with DBService.get_instance().get_session() as session:
                for row in unique_rows:
                    if row < 0 or row >= len(self.player._tracks):  # noqa: SLF001
                        continue
                    track = self.player._tracks[row]  # noqa: SLF001
                    ctx = track.context if isinstance(track.context, dict) else {}

                    kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
                    if kind not in {"sentence", "lemma", "term"}:
                        continue

                    src_text = str(ctx.get("snapshot_hebrew") or track.label or "").strip()
                    if not src_text:
                        continue
                    src_lang = str(ctx.get("src_lang") or "he").strip() or "he"
                    norm_kind = {"term": "term_cluster", "sentence": "surface"}.get(kind, kind)
                    try:
                        src_norm = normalize_for_tm(src_lang, src_text, norm_kind).norm or ""
                    except Exception:
                        src_norm = ""
                    if not src_norm:
                        continue

                    ready_path = AudioPlaybackService.resolve_ready_path(
                        session,
                        lang=src_lang,
                        norm_text=src_norm,
                    )

                    changed = False
                    if ready_path:
                        if track.path != ready_path:
                            track.path = ready_path
                            changed = True
                        if ctx.get("audio_status") != "ready":
                            ctx["audio_status"] = "ready"
                            changed = True
                        if clear_stale_if_ready and bool(ctx.get("is_stale")):
                            ctx["is_stale"] = False
                            changed = True
                    else:
                        if str(track.path) not in ("", "."):
                            track.path = Path("")
                            changed = True
                        if ctx.get("audio_status") != "missing":
                            ctx["audio_status"] = "missing"
                            changed = True
                    if changed:
                        updated += 1
        except Exception as exc:
            logger.debug("refresh audio paths skipped: %s", exc)
            return 0

        if updated:
            self._refresh_queue()
        return updated

    def _on_queue_translate_selected(self, rows: List[int]) -> None:
        from app.services.batch_mt_translate_service import BatchTranslateOptions
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.dialogs.batch_translate_dialog import show_batch_translate_dialog
        from app.ui.workers import BatchTranslateWorker

        items = self._build_translate_items(rows)
        if not items:
            return

        accepted, provider_mode, write_mode, _scope = show_batch_translate_dialog(
            parent=self,
            selected_count=len(items),
            scope_enabled=False,
        )
        if not accepted:
            return

        options = BatchTranslateOptions(
            provider_mode=provider_mode,
            write_mode=write_mode,
        )
        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.setWindowTitle("Batch Translate Selected Rows")
        progress_dialog.show()

        worker = BatchTranslateWorker(
            items=items,
            options=options,
            tab_type="audio_player_queue",
        )
        self._queue_translate_worker = worker
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        source_keys = self._source_keys_from_rows(rows)
        worker.finished.connect(
            lambda result: self._on_queue_translate_finished(result, progress_dialog, source_keys)
        )
        worker.error.connect(lambda msg: self._on_queue_worker_error("Translation", msg, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)
        worker.start()

    def _on_queue_translate_finished(
        self,
        result: object,
        progress_dialog,
        source_keys: Optional[List[Tuple[str, int, Optional[int]]]] = None,
    ) -> None:
        progress_dialog.set_completed()
        progress_dialog.accept()
        try:
            succeeded = int(getattr(result, "succeeded", 0))
            skipped = int(getattr(result, "skipped", 0))
            failed = int(getattr(result, "failed", 0))
        except Exception:
            succeeded = skipped = failed = 0
        self._refresh_display_contexts()
        if source_keys and succeeded > 0:
            self._emit_data_changed(fields=["translation"], source_keys=source_keys)
        QMessageBox.information(
            self,
            "Translation Complete",
            f"Succeeded: {succeeded}\nSkipped: {skipped}\nFailed: {failed}",
        )
        worker = getattr(self, "_queue_translate_worker", None)
        if worker is not None:
            worker.deleteLater()
            self._queue_translate_worker = None

    def _on_queue_regenerate_audio_selected(self, rows: List[int]) -> None:
        from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import BatchGenerateAudioWorker

        items = self._build_audio_generation_items(rows)
        if not items:
            return

        accepted, provider_mode, write_mode, _scope = show_batch_audio_dialog(
            parent=self,
            selected_count=len(items),
            scope_enabled=False,
            filtered_count=len(items),
        )
        if not accepted:
            return

        source_keys = self._source_keys_from_rows(rows)
        success_source_keys: set[Tuple[str, int, Optional[int]]] = set()
        row_to_source: Dict[str, Tuple[str, int, Optional[int]]] = {}
        for row in rows:
            ctx = self._track_ctx_at_row(row)
            source_key = self._queue_source_key_from_context(ctx)
            if source_key is None:
                continue
            row_id = str(ctx.get("item_id") or ctx.get("source_id") or row)
            row_to_source[row_id] = source_key

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.setWindowTitle("Batch Generate Source Audio")
        progress_dialog.show()

        worker = BatchGenerateAudioWorker(
            items=items,
            provider_mode=provider_mode,
            write_mode=write_mode,
            audio_chunk=25,
        )
        self._queue_audio_worker = worker
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.stage_updated.connect(progress_dialog.set_stage)

        def _on_row_audio(entity_id: str, message: str, success: bool) -> None:
            progress_dialog.add_recent_item(entity_id, message, success)
            if success:
                source_key = row_to_source.get(str(entity_id))
                if source_key is not None:
                    success_source_keys.add(source_key)

        worker.row_translated.connect(_on_row_audio)
        worker.finished.connect(
            lambda result: self._on_queue_audio_finished(
                result,
                progress_dialog,
                source_keys,
                success_source_keys,
            )
        )
        worker.error.connect(lambda msg: self._on_queue_worker_error("Audio Generation", msg, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)
        worker.start()

    def _on_queue_audio_finished(
        self,
        result: dict,
        progress_dialog,
        source_keys: List[Tuple[str, int, Optional[int]]],
        success_source_keys: set[Tuple[str, int, Optional[int]]],
    ) -> None:
        progress_dialog.set_completed()
        progress_dialog.update_counts(
            int(result.get("succeeded", 0)),
            int(result.get("skipped", 0)),
            int(result.get("failed", 0)),
        )
        progress_dialog.accept()

        affected_rows = self._rows_for_source_keys(source_keys)
        self._refresh_audio_paths_for_rows(affected_rows, clear_stale_if_ready=False)
        if success_source_keys:
            self._clear_queue_sources_stale(list(success_source_keys))
        self._refresh_display_contexts()
        self._refresh_queue()
        if success_source_keys:
            self._emit_data_changed(fields=["audio"], source_keys=sorted(success_source_keys))

        QMessageBox.information(
            self,
            "Audio Generation Complete",
            f"Ready: {int(result.get('succeeded', 0))}\n"
            f"Skipped: {int(result.get('skipped', 0))}\n"
            f"Failed: {int(result.get('failed', 0))}",
        )

        worker = getattr(self, "_queue_audio_worker", None)
        if worker is not None:
            worker.deleteLater()
            self._queue_audio_worker = None

    def _on_queue_niqqudize_selected(self, rows: List[int]) -> None:
        from app.ui.dialogs.pronunciation_bootstrap_dialog import show_pronunciation_bootstrap_dialog
        from app.ui.dialogs.sentence_niqqud_bootstrap_dialog import show_sentence_niqqud_bootstrap_dialog

        sentence_ids: List[int] = []
        lexical_rows: List[int] = []
        sentence_lang = "he"
        for row in rows:
            ctx = self._track_ctx_at_row(row)
            kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
            if kind == "sentence":
                sid_raw = ctx.get("source_id")
                try:
                    sid = int(sid_raw)
                except (TypeError, ValueError):
                    continue
                sentence_ids.append(sid)
                sentence_lang = str(ctx.get("src_lang") or sentence_lang or "he").strip() or "he"
            elif kind in {"lemma", "term"}:
                lexical_rows.append(row)

        changed = False
        if lexical_rows:
            selected_items = self._build_pronunciation_selected_items(lexical_rows)
            if selected_items:
                changed = bool(
                    show_pronunciation_bootstrap_dialog(
                        parent=self,
                        selected_items=selected_items,
                    )
                ) or changed

        unique_sentence_ids = sorted(set(sentence_ids))
        if unique_sentence_ids:
            changed = bool(
                show_sentence_niqqud_bootstrap_dialog(
                    self,
                    selected_ids=unique_sentence_ids,
                    page_ids=unique_sentence_ids,
                    all_ids=unique_sentence_ids,
                    lang=sentence_lang,
                )
            ) or changed

        if changed:
            source_keys = self._source_keys_from_rows(rows)
            self._mark_queue_sources_stale(source_keys)
            self._refresh_display_contexts()
            self._emit_data_changed(fields=["pronunciation"], source_keys=source_keys)

    def _on_queue_edit_translation(self, row: int) -> None:
        ctx = self._track_ctx_at_row(row)
        source_key = self._queue_source_key_from_context(ctx)
        if source_key is None:
            return

        current_translation = str(ctx.get("snapshot_translation") or "").strip()
        new_translation, ok = QInputDialog.getText(
            self,
            "Edit Translation",
            "Translation:",
            text=current_translation,
        )
        if not ok:
            return

        translation_value = (new_translation or "").strip()
        if translation_value == current_translation:
            return

        if not self._save_source_translation(source_key, translation_value):
            return

        self._apply_queue_translation_snapshot(source_key, translation_value)
        self._refresh_display_contexts()
        self._refresh_queue()
        self._emit_data_changed(fields=["translation"], source_keys=[source_key])

    def _on_queue_clear_translation(self, rows: List[int]) -> None:
        source_keys = []
        for row in rows:
            key = self._queue_source_key_from_context(self._track_ctx_at_row(row))
            if key is not None:
                source_keys.append(key)
        if not source_keys:
            return
        unique_keys = sorted(set(source_keys))
        reply = QMessageBox.question(
            self,
            "Clear Translation",
            f"Clear translation for {len(unique_keys)} selected source row(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        success = 0
        failed = 0
        for source_key in unique_keys:
            if self._save_source_translation(source_key, ""):
                success += 1
                self._apply_queue_translation_snapshot(source_key, "")
            else:
                failed += 1

        self._refresh_display_contexts()
        self._refresh_queue()
        if success > 0:
            self._emit_data_changed(fields=["translation"], source_keys=unique_keys)
        if failed:
            QMessageBox.warning(
                self,
                "Clear Translation",
                f"Cleared: {success}\nFailed: {failed}",
            )

    def _save_source_translation(
        self,
        source_key: Tuple[str, int, Optional[int]],
        translation_value: str,
    ) -> bool:
        from datetime import datetime

        from sqlalchemy import select

        from app.domain.normalization.normalizer import normalize_for_tm
        from app.infra.db_retry import with_retry_on_locked
        from app.infra.sa_models import Lemma, TMEntry, TermCluster
        from app.services.db_service import DBService
        from app.services.project_service import ProjectService
        from app.services.tm_global_service import TMGlobalService

        kind, source_id, project_id = source_key
        row = next(iter(self._rows_for_source_keys([source_key])), None)
        if row is None:
            return False
        ctx = self._track_ctx_at_row(row)
        src_text = str(
            ctx.get("snapshot_hebrew") or (self._track_at_row(row) or {}).get("label") or ""
        ).strip()
        if not src_text:
            return False

        kind_tm = {"term": "term_cluster", "sentence": "surface", "lemma": "lemma"}.get(kind)
        if not kind_tm:
            return False

        with DBService.get_instance().get_session() as session:
            src_lang = str(ctx.get("src_lang") or "he").strip() or "he"
            tgt_lang = str(ctx.get("tgt_lang") or "ru").strip() or "ru"
            if project_id is not None:
                try:
                    project = ProjectService().get_project(session, int(project_id))
                except Exception:
                    project = None
                if project:
                    src_lang = str(getattr(project, "src_lang", "") or src_lang)
                    tgt_lang = str(getattr(project, "tgt_lang", "") or tgt_lang)

            src_norm = normalize_for_tm(src_lang, src_text, kind_tm).norm
            if not src_norm:
                return False

            stmt = select(TMEntry).where(
                TMEntry.project_id == project_id,
                TMEntry.kind == kind_tm,
                TMEntry.src_norm == src_norm,
            )
            existing = session.execute(stmt).scalar_one_or_none()

            tm_entry = existing
            if existing:
                existing.translation = translation_value
                existing.status = "approved"
                existing.origin = "user_edit"
                existing.updated_at = datetime.now()
            else:
                source_ref = {
                    "lemma": "audio_player_inline_edit",
                    "term_cluster": "audio_player_inline_edit",
                    "surface": f"sentence:{source_id}",
                }.get(kind_tm, "audio_player_inline_edit")
                lemma_id = source_id if kind_tm == "lemma" else None
                cluster_id = source_id if kind_tm == "term_cluster" else None
                is_noise = 0
                noise_reason = None
                if kind_tm == "lemma":
                    lemma = session.execute(
                        select(Lemma).where(Lemma.lemma_id == source_id)
                    ).scalar_one_or_none()
                    if lemma is not None:
                        is_noise = lemma.is_noise if lemma.is_noise is not None else 0
                        noise_reason = lemma.noise_reason
                elif kind_tm == "term_cluster":
                    cluster = session.execute(
                        select(TermCluster).where(TermCluster.cluster_id == source_id)
                    ).scalar_one_or_none()
                    if cluster is not None:
                        is_noise = cluster.is_noise if cluster.is_noise is not None else 0
                        noise_reason = cluster.noise_reason

                tm_entry = TMEntry(
                    project_id=project_id,
                    kind=kind_tm,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    src_text=src_text,
                    src_norm=src_norm,
                    translation=translation_value,
                    status="approved",
                    origin="user_edit",
                    source_ref=source_ref,
                    lemma_id=lemma_id,
                    cluster_id=cluster_id,
                    is_noise=is_noise,
                    noise_reason=noise_reason,
                )
                session.add(tm_entry)

            def _flush_and_propagate() -> None:
                session.flush()
                TMGlobalService().upsert_and_link(
                    session,
                    tm_entry,
                    force_global_update=(translation_value == ""),
                )
                session.commit()

            try:
                with_retry_on_locked(_flush_and_propagate, max_retries=3)
            except Exception as exc:
                logger.error("Failed to save translation from audio queue: %s", exc, exc_info=True)
                QMessageBox.warning(self, "Edit Translation", f"Failed to save translation:\n{exc}")
                return False

        return True

    def _apply_queue_translation_snapshot(
        self,
        source_key: Tuple[str, int, Optional[int]],
        translation_value: str,
    ) -> None:
        rows = self._rows_for_source_keys([source_key])
        for row in rows:
            if row < 0 or row >= len(self.player._tracks):  # noqa: SLF001
                continue
            track = self.player._tracks[row]  # noqa: SLF001
            ctx = track.context if isinstance(track.context, dict) else None
            if not ctx:
                continue
            ctx["snapshot_translation"] = translation_value

    def _on_queue_edit_pronunciation(self, row: int) -> None:
        from app.domain.normalization.normalizer import normalize_for_tm
        from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog

        ctx = self._track_ctx_at_row(row)
        kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
        if kind not in {"lemma", "term"}:
            return

        src_text = str(ctx.get("snapshot_hebrew") or (self._track_at_row(row) or {}).get("label") or "").strip()
        if not src_text:
            return
        src_lang = str(ctx.get("src_lang") or "he").strip() or "he"
        norm_kind = "term_cluster" if kind == "term" else "lemma"
        src_norm = normalize_for_tm(src_lang, src_text, norm_kind).norm
        if not src_norm:
            return

        changed = show_edit_pronunciation_dialog(
            parent=self,
            src_lang=src_lang,
            src_norm=src_norm,
            src_text=src_text,
        )
        if not changed:
            return

        source_key = self._queue_source_key_from_context(ctx)
        if source_key is not None:
            self._mark_queue_sources_stale([source_key])
        self._refresh_display_contexts()
        if source_key is not None:
            self._emit_data_changed(fields=["pronunciation"], source_keys=[source_key])

    def _on_queue_edit_sentence_niqqud(self, row: int) -> None:
        from app.ui.dialogs.edit_sentence_niqqud_dialog import show_edit_sentence_niqqud_dialog

        ctx = self._track_ctx_at_row(row)
        kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
        if kind != "sentence":
            return

        source_id_raw = ctx.get("source_id")
        try:
            sentence_id = int(source_id_raw)
        except (TypeError, ValueError):
            return

        source_text = str(ctx.get("snapshot_hebrew") or (self._track_at_row(row) or {}).get("label") or "").strip()
        current_niqqud = str(ctx.get("snapshot_niqqud") or ctx.get("niqqud") or "").strip()
        changed = show_edit_sentence_niqqud_dialog(
            self,
            sentence_id=sentence_id,
            sentence_text=source_text,
            current_niqqud=current_niqqud or None,
        )
        if not changed:
            return

        source_key = self._queue_source_key_from_context(ctx)
        if source_key is not None:
            self._mark_queue_sources_stale([source_key])
        self._refresh_display_contexts()
        if source_key is not None:
            self._emit_data_changed(fields=["pronunciation"], source_keys=[source_key])

    def _on_queue_worker_error(self, label: str, msg: str, progress_dialog) -> None:
        progress_dialog.set_stage(f"Error: {msg[:80]}")
        progress_dialog.accept()
        QMessageBox.warning(self, f"{label} Failed", msg)

        for attr in ("_queue_translate_worker", "_queue_audio_worker"):
            worker = getattr(self, attr, None)
            if worker is not None:
                worker.deleteLater()
                setattr(self, attr, None)

    def _on_queue_row_double_clicked(self, index: QModelIndex) -> None:
        self._play_from_row(index.row())

    def _on_queue_play_cell_clicked(self, index: QModelIndex) -> None:
        """AudioPlayDelegate ▶ callback on Status column: jump to and play this row."""
        self._play_from_row(index.row())

    def _play_from_row(self, row: int) -> None:
        """Set the cursor to 'row - 1' and call next_track so it plays row."""
        if row < 0 or row >= len(self.player._tracks):  # noqa: SLF001
            return

        ctx = self._track_ctx_at_row(row)
        if bool(ctx.get("is_stale")):
            self._refresh_audio_paths_for_rows([row], clear_stale_if_ready=True)
            ctx = self._track_ctx_at_row(row)
            if bool(ctx.get("is_stale")):
                QMessageBox.information(
                    self,
                    "Audio Stale",
                    "Audio is stale for this row. Regenerate audio to play the latest pronunciation.",
                )
                return

        track = self.player._tracks[row]  # noqa: SLF001
        path_ok = str(track.path) not in ("", ".") and Path(track.path).exists()
        if not path_ok:
            self._refresh_audio_paths_for_rows([row], clear_stale_if_ready=True)
            track = self.player._tracks[row]  # noqa: SLF001
            path_ok = str(track.path) not in ("", ".") and Path(track.path).exists()
        if not path_ok:
            QMessageBox.information(
                self,
                "Audio Missing",
                "No ready audio found for this row. Use 'Regenerate Audio' first.",
            )
            return

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

    def _refresh_display_contexts(self) -> None:
        """Batch-refresh Niqqud / Translation / Source for all queue tracks from DB.

        Groups tracks by kind and runs appropriate batch SELECTs (no per-row SQL).
        Updates track contexts in-place then calls _refresh_queue() to redraw.
        Non-fatal: any DB error is logged at DEBUG level and silently ignored.
        """
        if self.__dict__.get("_refresh_in_progress", False):
            return
        tracks = self.player._tracks  # noqa: SLF001
        if not tracks:
            return
        self.__dict__["_refresh_in_progress"] = True
        try:
            from app.services.db_service import DBService
            _db = DBService.get_instance()

            # Group by kind
            sentence_pairs: List[tuple] = []  # (track,)
            lemma_pairs: List[tuple] = []
            term_pairs: List[tuple] = []
            for t in tracks:
                ctx = t.context if isinstance(t.context, dict) else {}
                kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
                if kind == "sentence":
                    sentence_pairs.append(t)
                elif kind == "lemma":
                    lemma_pairs.append(t)
                elif kind == "term":
                    term_pairs.append(t)

            updated = 0
            with _db.get_session() as _sess:
                updated += self._refresh_sentence_display(_sess, sentence_pairs)
                updated += self._refresh_lemma_display(_sess, lemma_pairs)
                updated += self._refresh_term_display(_sess, term_pairs)

            if updated:
                logger.debug("_refresh_display_contexts: updated %d tracks", updated)
                self._refresh_queue()
        except Exception as exc:
            logger.debug("_refresh_display_contexts: non-fatal: %s", exc)
        finally:
            self.__dict__["_refresh_in_progress"] = False

    def _refresh_sentence_display(self, session, tracks: List) -> int:
        """Batch-refresh Source / Niqqud / Translation for sentence tracks."""
        if not tracks:
            return 0
        from sqlalchemy import select as _sel
        from app.infra.sa_models import DocumentSentence as _DS, SourceDocument as _SD

        track_rows: List[Tuple[Any, int]] = []
        for t in tracks:
            sid_raw = t.context.get("source_id") if isinstance(t.context, dict) else None
            try:
                sid = int(sid_raw)
            except (TypeError, ValueError):
                continue
            track_rows.append((t, sid))
        sids = [sid for _, sid in track_rows]
        if not sids:
            return 0

        # Fetch doc_id + text for source label and translation lookup
        sid_to_did: Dict[int, int] = {}
        sid_to_text: Dict[int, str] = {}
        try:
            for sid, txt, did in session.execute(
                _sel(_DS.sentence_id, _DS.text, _DS.doc_id).where(_DS.sentence_id.in_(sids))
            ).all():
                if did is not None:
                    sid_to_did[sid] = did
                sid_to_text[sid] = txt or ""
        except Exception:
            pass

        # Resolve document filenames
        doc_names: Dict[int, str] = {}
        try:
            unique_dids = list(set(sid_to_did.values()))
            if unique_dids:
                for did, fname in session.execute(
                    _sel(_SD.doc_id, _SD.file_name).where(_SD.doc_id.in_(unique_dids))
                ).all():
                    if fname:
                        doc_names[did] = fname
        except Exception:
            pass

        # Batch niqqud
        sid_to_niqqud: Dict[int, str] = {}
        try:
            from app.services.sentence_pronunciation_service import SentencePronunciationService
            overlays = SentencePronunciationService().bulk_get_niqqud(session, sids)
            for sid, overlay in overlays.items():
                if overlay and overlay.niqqud_text:
                    sid_to_niqqud[sid] = overlay.niqqud_text
        except Exception:
            pass

        # Batch translation (project-aware; queue may contain mixed projects)
        text_to_transl: Dict[Tuple[int, str], str] = {}
        try:
            from app.services.sentences_workspace_service import SentencesWorkspaceService
            svc = SentencesWorkspaceService()
            project_to_texts: Dict[int, List[str]] = {}
            sid_to_project: Dict[int, int] = {}
            for t, sid in track_rows:
                project_id = t.context.get("project_id") if isinstance(t.context, dict) else None
                if sid is None or project_id is None:
                    continue
                try:
                    project_id_int = int(project_id)
                except (TypeError, ValueError):
                    continue
                sid_to_project[sid] = project_id_int
            for sid, text in sid_to_text.items():
                if not text:
                    continue
                project_id = sid_to_project.get(sid)
                if project_id is None:
                    continue
                project_to_texts.setdefault(project_id, []).append(text)

            for project_id, texts in project_to_texts.items():
                raw = svc._batch_get_translations(session, project_id, "he", texts)
                for txt in texts:
                    norm = svc._norm("he", txt)
                    if norm in raw:
                        text_to_transl[(project_id, txt)] = raw[norm][0]
        except Exception:
            pass

        updated = 0
        for t, sid in track_rows:
            changed = False
            did = sid_to_did.get(sid)
            source = doc_names.get(did, "") if did else ""
            if source and t.context.get("snapshot_source_label") != source:
                t.context["snapshot_source_label"] = source
                changed = True
            niqqud = sid_to_niqqud.get(sid)
            if niqqud is not None and t.context.get("snapshot_niqqud") != niqqud:
                t.context["snapshot_niqqud"] = niqqud
                changed = True
            elif niqqud is None and (t.context.get("snapshot_niqqud") or "") != "":
                t.context["snapshot_niqqud"] = ""
                changed = True
            text = sid_to_text.get(sid, "")
            if text:
                project_id = t.context.get("project_id")
                transl_key = None
                try:
                    if project_id is not None:
                        transl_key = (int(project_id), text)
                except (TypeError, ValueError):
                    transl_key = None
                transl = text_to_transl.get(transl_key) if transl_key else None
                if transl_key in text_to_transl:
                    if t.context.get("snapshot_translation") != transl:
                        t.context["snapshot_translation"] = transl
                        changed = True
                elif (t.context.get("snapshot_translation") or "") != "":
                    t.context["snapshot_translation"] = ""
                    changed = True
            if changed:
                updated += 1
        return updated

    def _refresh_lemma_display(self, session, tracks: List) -> int:
        """Batch-refresh Source / Niqqud / Translation for lemma tracks."""
        if not tracks:
            return 0
        from sqlalchemy import select as _sel
        from app.infra.sa_models import Lemma as _Lemma

        track_rows: List[Tuple[Any, int, Optional[int]]] = []
        for t in tracks:
            ctx = t.context if isinstance(t.context, dict) else {}
            sid_raw = ctx.get("source_id")
            pid_raw = ctx.get("project_id")
            try:
                sid = int(sid_raw)
            except (TypeError, ValueError):
                continue
            try:
                pid = int(pid_raw) if pid_raw is not None else None
            except (TypeError, ValueError):
                pid = None
            track_rows.append((t, sid, pid))
        if not track_rows:
            return 0

        lemma_rows = session.execute(
            _sel(_Lemma.lemma_id, _Lemma.lemma_text, _Lemma.norm_text)
            .where(_Lemma.lemma_id.in_([sid for _, sid, _ in track_rows]))
        ).all()
        lid_to_db: Dict[int, Tuple[str, str]] = {
            int(lid): (str(txt or ""), str(norm or ""))
            for lid, txt, norm in lemma_rows
        }

        lid_to_pron_norm: Dict[int, str] = {}
        lid_to_tm_norm: Dict[int, str] = {}
        try:
            from app.domain.normalization.normalizer import normalize_for_tm as _ntm
            for t, lid, _pid in track_rows:
                db_text, db_norm = lid_to_db.get(lid, ("", ""))
                text = (db_text or str(t.context.get("snapshot_hebrew") or "")).strip()
                if not text and not db_norm:
                    continue
                try:
                    pron_norm = _ntm("he", text, "surface").norm if text else ""
                except Exception:
                    pron_norm = ""
                try:
                    tm_norm = _ntm("he", text, "lemma").norm if text else ""
                except Exception:
                    tm_norm = ""
                lid_to_pron_norm[lid] = (pron_norm or db_norm or text).strip()
                lid_to_tm_norm[lid] = (tm_norm or db_norm or text).strip()
        except Exception:
            pass

        # Batch niqqud
        norm_to_niqqud: Dict[str, str] = {}
        try:
            from app.services.pronunciation_service import PronunciationService
            all_pron_norms = sorted({n for n in lid_to_pron_norm.values() if n})
            if all_pron_norms:
                bulk = PronunciationService().bulk_lookup(session, lang="he", src_norms=all_pron_norms)
                norm_to_niqqud = {n: dto.niqqud_text for n, dto in bulk.items() if dto.niqqud_text}
        except Exception:
            pass

        # Batch translation from TMEntry (project-aware)
        norm_to_transl: Dict[Tuple[int, str], str] = {}
        try:
            from app.infra.sa_models import TMEntry as _TM
            project_ids = sorted({pid for _, _sid, pid in track_rows if pid is not None})
            all_tm_norms = sorted({n for n in lid_to_tm_norm.values() if n})
            if all_tm_norms and project_ids:
                tm_rows = session.execute(
                    _sel(_TM.project_id, _TM.src_norm, _TM.translation)
                    .where(_TM.kind == "lemma")
                    .where(_TM.src_lang == "he")
                    .where(_TM.src_norm.in_(all_tm_norms))
                    .where(_TM.project_id.in_(project_ids))
                    .where(_TM.status.in_(["draft", "approved"]))
                    .order_by(_TM.status.desc())
                ).all()
                for project_id, norm, transl in tm_rows:
                    key = (int(project_id), str(norm or ""))
                    if key not in norm_to_transl:
                        norm_to_transl[key] = str(transl or "")
        except Exception:
            pass

        updated = 0
        for t, lid, pid in track_rows:
            db_text, _db_norm = lid_to_db.get(lid, ("", ""))
            pron_norm = lid_to_pron_norm.get(lid, "")
            tm_norm = lid_to_tm_norm.get(lid, "")
            changed = False
            if t.context.get("snapshot_source_label") != "Dictionary":
                t.context["snapshot_source_label"] = "Dictionary"
                changed = True
            if db_text and t.context.get("snapshot_hebrew") != db_text:
                t.context["snapshot_hebrew"] = db_text
                changed = True
            niqqud = norm_to_niqqud.get(pron_norm)
            if niqqud is not None and t.context.get("snapshot_niqqud") != niqqud:
                t.context["snapshot_niqqud"] = niqqud
                changed = True
            elif niqqud is None and (t.context.get("snapshot_niqqud") or "") != "":
                t.context["snapshot_niqqud"] = ""
                changed = True
            transl_key = (pid, tm_norm) if pid is not None and tm_norm else None
            transl = norm_to_transl.get(transl_key) if transl_key else None
            if transl_key is not None and transl_key in norm_to_transl:
                if t.context.get("snapshot_translation") != transl:
                    t.context["snapshot_translation"] = transl
                    changed = True
            elif (t.context.get("snapshot_translation") or "") != "":
                t.context["snapshot_translation"] = ""
                changed = True
            if changed:
                updated += 1
        return updated

    def _refresh_term_display(self, session, tracks: List) -> int:
        """Batch-refresh Source / Niqqud / Translation for term tracks."""
        if not tracks:
            return 0
        from sqlalchemy import select as _sel
        from app.infra.sa_models import TermCluster as _TermCluster

        track_rows: List[Tuple[Any, int, Optional[int]]] = []
        for t in tracks:
            ctx = t.context if isinstance(t.context, dict) else {}
            sid_raw = ctx.get("source_id")
            pid_raw = ctx.get("project_id")
            try:
                sid = int(sid_raw)
            except (TypeError, ValueError):
                continue
            try:
                pid = int(pid_raw) if pid_raw is not None else None
            except (TypeError, ValueError):
                pid = None
            track_rows.append((t, sid, pid))
        if not track_rows:
            return 0

        term_rows = session.execute(
            _sel(_TermCluster.cluster_id, _TermCluster.representative_he, _TermCluster.norm_text)
            .where(_TermCluster.cluster_id.in_([sid for _, sid, _ in track_rows]))
        ).all()
        cid_to_db: Dict[int, Tuple[str, str]] = {
            int(cid): (str(txt or ""), str(norm or ""))
            for cid, txt, norm in term_rows
        }

        cid_to_pron_norm: Dict[int, str] = {}
        cid_to_tm_norm: Dict[int, str] = {}
        try:
            from app.domain.normalization.normalizer import normalize_for_tm as _ntm
            for t, cid, _pid in track_rows:
                db_text, db_norm = cid_to_db.get(cid, ("", ""))
                text = (db_text or str(t.context.get("snapshot_hebrew") or "")).strip()
                if not text and not db_norm:
                    continue
                try:
                    pron_norm = _ntm("he", text, "surface").norm if text else ""
                except Exception:
                    pron_norm = ""
                try:
                    tm_norm = _ntm("he", text, "term_cluster").norm if text else ""
                except Exception:
                    tm_norm = ""
                cid_to_pron_norm[cid] = (pron_norm or db_norm or text).strip()
                cid_to_tm_norm[cid] = (tm_norm or db_norm or text).strip()
        except Exception:
            pass

        norm_to_niqqud: Dict[str, str] = {}
        try:
            from app.services.pronunciation_service import PronunciationService
            all_pron_norms = sorted({n for n in cid_to_pron_norm.values() if n})
            if all_pron_norms:
                bulk = PronunciationService().bulk_lookup(session, lang="he", src_norms=all_pron_norms)
                norm_to_niqqud = {n: dto.niqqud_text for n, dto in bulk.items() if dto.niqqud_text}
        except Exception:
            pass

        norm_to_transl: Dict[Tuple[int, str], str] = {}
        try:
            from app.infra.sa_models import TMEntry as _TM
            project_ids = sorted({pid for _, _sid, pid in track_rows if pid is not None})
            all_tm_norms = sorted({n for n in cid_to_tm_norm.values() if n})
            if all_tm_norms and project_ids:
                tm_rows = session.execute(
                    _sel(_TM.project_id, _TM.src_norm, _TM.translation)
                    .where(_TM.kind == "term_cluster")
                    .where(_TM.src_lang == "he")
                    .where(_TM.src_norm.in_(all_tm_norms))
                    .where(_TM.project_id.in_(project_ids))
                    .where(_TM.status.in_(["draft", "approved"]))
                    .order_by(_TM.status.desc())
                ).all()
                for project_id, norm, transl in tm_rows:
                    key = (int(project_id), str(norm or ""))
                    if key not in norm_to_transl:
                        norm_to_transl[key] = str(transl or "")
        except Exception:
            pass

        updated = 0
        for t, cid, pid in track_rows:
            db_text, _db_norm = cid_to_db.get(cid, ("", ""))
            pron_norm = cid_to_pron_norm.get(cid, "")
            tm_norm = cid_to_tm_norm.get(cid, "")
            changed = False
            if t.context.get("snapshot_source_label") != "Terms":
                t.context["snapshot_source_label"] = "Terms"
                changed = True
            if db_text and t.context.get("snapshot_hebrew") != db_text:
                t.context["snapshot_hebrew"] = db_text
                changed = True
            niqqud = norm_to_niqqud.get(pron_norm)
            if niqqud is not None and t.context.get("snapshot_niqqud") != niqqud:
                t.context["snapshot_niqqud"] = niqqud
                changed = True
            elif niqqud is None and (t.context.get("snapshot_niqqud") or "") != "":
                t.context["snapshot_niqqud"] = ""
                changed = True
            transl_key = (pid, tm_norm) if pid is not None and tm_norm else None
            transl = norm_to_transl.get(transl_key) if transl_key else None
            if transl_key is not None and transl_key in norm_to_transl:
                if t.context.get("snapshot_translation") != transl:
                    t.context["snapshot_translation"] = transl
                    changed = True
            elif (t.context.get("snapshot_translation") or "") != "":
                t.context["snapshot_translation"] = ""
                changed = True
            if changed:
                updated += 1
        return updated

