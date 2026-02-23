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
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
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

        self.add_all_btn = QPushButton("Add All…")
        self.add_all_btn.setToolTip("Add all items from a project source to the queue")
        self.add_all_btn.setFixedWidth(78)
        self.add_all_btn.clicked.connect(self._on_add_all_clicked)
        tab_header.addWidget(self.add_all_btn)

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
            logger.debug("_load_db_queue_to_player: path resolution skipped (%s)", path_exc)

        # ── Step 3: Dedup + enqueue (always runs if candidates exist) ─────────
        # Dedup by (kind, source_id) — prevents same source content appearing twice
        # when "Add All" is clicked multiple times.
        existing_source_keys: set = {
            (t.context.get("kind"), t.context.get("source_id"))
            for t in self.player._tracks  # noqa: SLF001
            if isinstance(t.context, dict)
            and t.context.get("kind") is not None
            and t.context.get("source_id") is not None
        }
        new_items = [
            item for item in candidate_items
            if (item.kind, item.source_id) not in existing_source_keys
        ]
        if new_items:
            self.player.enqueue_from_db(new_items, mode=add_mode, resolved_paths=resolved_paths)
            logger.debug(
                "_load_db_queue_to_player: loaded %d/%d items (%d with audio path)",
                len(new_items), len(candidate_items), len(resolved_paths),
            )

    def _on_add_all_error(self, msg: str, progress_dialog) -> None:
        progress_dialog.set_stage(f"Error: {msg[:80]}")
        progress_dialog.accept()
        QMessageBox.critical(self, "Add All — Error", msg)

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

    def _on_queue_play_cell_clicked(self, index: QModelIndex) -> None:
        """AudioPlayDelegate ▶ callback on Status column: jump to and play this row."""
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
