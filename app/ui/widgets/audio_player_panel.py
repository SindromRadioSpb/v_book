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
from app.ui.workers import ProjectDocumentsPageWorker

logger = logging.getLogger(__name__)


# ── Table model ───────────────────────────────────────────────────────────────

_COL_NUM = 0
_COL_HEBREW = 1
_COL_NIQQUD = 2
_COL_TRANSLATION = 3
_COL_SOURCE = 4
_COL_STATUS = 5
_COL_PLAYS = 6
_COL_PROJECT = 7
_COL_DOCUMENT = 8
_COL_SOURCE_ID = 9

_COLUMNS = [
    "#",
    "Hebrew",
    "Niqqud",
    "Translation",
    "Source",
    "Status",
    "Plays",
    "Project",
    "Document",
    "Source ID",
]
_COLUMN_KEYS = [
    "num",
    "hebrew",
    "niqqud",
    "translation",
    "source",
    "status",
    "plays",
    "project",
    "document",
    "source_id",
]

_PL_COL_NUM = 0
_PL_COL_HEBREW = 1
_PL_COL_NIQQUD = 2
_PL_COL_TRANSLATION = 3
_PL_COL_SOURCE = 4
_PL_COL_STATUS = 5
_PL_COL_PROJECT = 6
_PL_COL_DOCUMENT = 7
_PL_COL_SOURCE_ID = 8

_PLAYLIST_COLUMNS = [
    "#",
    "Hebrew",
    "Niqqud",
    "Translation",
    "Source",
    "Status",
    "Project",
    "Document",
    "Source ID",
]

_HIST_COL_NUM = 0
_HIST_COL_HEBREW = 1
_HIST_COL_NIQQUD = 2
_HIST_COL_TRANSLATION = 3
_HIST_COL_SOURCE = 4
_HIST_COL_STATUS = 5
_HIST_COL_PLAYED_AT = 6
_HIST_COL_RATE = 7
_HIST_COL_PROJECT = 8
_HIST_COL_DOCUMENT = 9
_HIST_COL_SOURCE_ID = 10

_HISTORY_COLUMNS = [
    "#",
    "Hebrew",
    "Niqqud",
    "Translation",
    "Source",
    "Status",
    "Played At",
    "Rate",
    "Project",
    "Document",
    "Source ID",
]

_CURRENT_BG = QColor(210, 240, 210)
_STALE_BG = QColor(255, 240, 200)


def _normalize_status_token(raw_status: Any) -> str:
    token = str(raw_status or "").strip().lower()
    if token in {"ready", "missing", "stale", "generating", "failed", "error", "unknown"}:
        return token
    return "unknown"


def _status_tooltip_text(raw_status: Any) -> str:
    status = _normalize_status_token(raw_status)
    if status == "ready":
        return "Playable"
    if status == "missing":
        return "No audio asset found. Generate audio to enable playback."
    if status == "stale":
        return "Audio is stale after edits. Regenerate audio."
    if status in {"generating"}:
        return "Audio generation is in progress."
    if status in {"failed", "error"}:
        return "Audio generation failed. Regenerate audio."
    return "Audio availability is unknown."


def _status_unavailable_message(raw_status: Any) -> str:
    status = _normalize_status_token(raw_status)
    if status == "stale":
        return "Audio is stale after edits. Please regenerate."
    if status == "missing":
        return "Audio not generated yet. Use Generate/Regenerate Audio."
    if status == "generating":
        return "Audio generation is in progress. Try again after completion."
    if status in {"failed", "error"}:
        return "Last audio generation failed. Regenerate audio."
    return "Audio is unavailable for playback."


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
                if path and path != "." and os.path.exists(str(path)):
                    return "ready"
                status_hint = _normalize_status_token(ctx.get("audio_status"))
                if status_hint in {"generating", "failed", "error"}:
                    return status_hint
                return "missing"
            if col == _COL_PLAYS:
                return str(ctx.get("play_count", "—"))
            if col == _COL_PROJECT:
                return ctx.get("snapshot_project_name") or "—"
            if col == _COL_DOCUMENT:
                return ctx.get("snapshot_document_name") or "—"
            if col == _COL_SOURCE_ID:
                source_id = ctx.get("source_id")
                return str(source_id) if source_id is not None else "—"
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
            if col == _COL_SOURCE:
                return ctx.get("snapshot_source_label") or ""
            if col == _COL_STATUS:
                status = self.data(index, Qt.ItemDataRole.DisplayRole)
                return _status_tooltip_text(status)
            if col == _COL_PROJECT:
                return ctx.get("snapshot_project_name") or ""
            if col == _COL_DOCUMENT:
                return ctx.get("snapshot_document_name") or ""
            return None

        if role == Qt.ItemDataRole.UserRole:
            return row

        return None


class AudioPlaylistEntriesTableModel(QAbstractTableModel):
    """Read-only table model for playlist entries."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def load(self, entries: List[Any]) -> None:
        rows: List[Dict[str, Any]] = []
        for entry in entries:
            rows.append(
                {
                    "entry_id": getattr(entry, "entry_id", None),
                    "position": int(getattr(entry, "position", len(rows))),
                    "snapshot_hebrew": getattr(entry, "snapshot_hebrew", None),
                    "snapshot_niqqud": getattr(entry, "snapshot_niqqud", None),
                    "snapshot_translation": getattr(entry, "snapshot_translation", None),
                    "snapshot_source_label": getattr(entry, "snapshot_source_label", None),
                    "audio_status": getattr(entry, "audio_status", "unknown"),
                    "kind": getattr(entry, "kind", ""),
                    "source_id": getattr(entry, "source_id", None),
                    "project_id": getattr(entry, "project_id", None),
                    "snapshot_project_name": getattr(entry, "snapshot_project_name", None),
                    "snapshot_document_name": getattr(entry, "snapshot_document_name", None),
                    "resolved_path": getattr(entry, "resolved_path", None),
                }
            )
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def load_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows) if not parent.isValid() else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_PLAYLIST_COLUMNS) if not parent.isValid() else 0

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(_PLAYLIST_COLUMNS):
                return _PLAYLIST_COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._rows):
            return None
        payload = self._rows[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == _PL_COL_NUM:
                return str(int(payload.get("position", row)) + 1)
            if col == _PL_COL_HEBREW:
                return payload.get("snapshot_hebrew") or "—"
            if col == _PL_COL_NIQQUD:
                return payload.get("snapshot_niqqud") or "—"
            if col == _PL_COL_TRANSLATION:
                return payload.get("snapshot_translation") or "—"
            if col == _PL_COL_SOURCE:
                return payload.get("snapshot_source_label") or "—"
            if col == _PL_COL_STATUS:
                status = str(payload.get("audio_status") or "unknown").strip().lower()
                resolved = str(payload.get("resolved_path") or "")
                if resolved and resolved != "." and os.path.exists(resolved):
                    return "ready"
                if status == "stale":
                    return "stale"
                if status in {"ready", "missing", "failed", "generating", "unknown"}:
                    return status
                return "unknown"
            if col == _PL_COL_PROJECT:
                return payload.get("snapshot_project_name") or "—"
            if col == _PL_COL_DOCUMENT:
                return payload.get("snapshot_document_name") or "—"
            if col == _PL_COL_SOURCE_ID:
                source_id = payload.get("source_id")
                return str(source_id) if source_id is not None else "—"
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col in (
                _PL_COL_HEBREW,
                _PL_COL_NIQQUD,
                _PL_COL_TRANSLATION,
                _PL_COL_SOURCE,
                _PL_COL_PROJECT,
                _PL_COL_DOCUMENT,
            ):
                key = {
                    _PL_COL_HEBREW: "snapshot_hebrew",
                    _PL_COL_NIQQUD: "snapshot_niqqud",
                    _PL_COL_TRANSLATION: "snapshot_translation",
                    _PL_COL_SOURCE: "snapshot_source_label",
                    _PL_COL_PROJECT: "snapshot_project_name",
                    _PL_COL_DOCUMENT: "snapshot_document_name",
                }[col]
                return payload.get(key) or ""
            if col == _PL_COL_STATUS:
                status = self.data(index, Qt.ItemDataRole.DisplayRole)
                return _status_tooltip_text(status)
            return None

        return None

    def entry_id_at(self, row: int) -> Optional[int]:
        if row < 0 or row >= len(self._rows):
            return None
        value = self._rows[row].get("entry_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def entry_count(self) -> int:
        return len(self._rows)

    def entry_ids_in_order(self) -> List[int]:
        result: List[int] = []
        for row in range(len(self._rows)):
            entry_id = self.entry_id_at(row)
            if entry_id is not None:
                result.append(entry_id)
        return result

    def row_payload(self, row: int) -> Optional[Dict[str, Any]]:
        if row < 0 or row >= len(self._rows):
            return None
        return dict(self._rows[row])


class AudioHistoryTableModel(QAbstractTableModel):
    """Read-only table model for DB-backed audio history rows."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def load(self, entries: List[Any]) -> None:
        rows: List[Dict[str, Any]] = []
        for entry in entries:
            rows.append(
                {
                    "history_id": getattr(entry, "history_id", None),
                    "kind": getattr(entry, "kind", ""),
                    "source_id": getattr(entry, "source_id", None),
                    "project_id": getattr(entry, "project_id", None),
                    "snapshot_hebrew": getattr(entry, "snapshot_hebrew", None),
                    "snapshot_niqqud": None,
                    "snapshot_translation": None,
                    "snapshot_source_label": None,
                    "snapshot_project_name": None,
                    "snapshot_document_name": None,
                    "audio_status": "unknown",
                    "resolved_path": None,
                    "rate_used": getattr(entry, "rate_used", 1.0),
                    "played_at": getattr(entry, "played_at", None),
                }
            )
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def load_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows) if not parent.isValid() else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_HISTORY_COLUMNS) if not parent.isValid() else 0

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(_HISTORY_COLUMNS):
                return _HISTORY_COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._rows):
            return None
        payload = self._rows[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == _HIST_COL_NUM:
                return str(row + 1)
            if col == _HIST_COL_HEBREW:
                return payload.get("snapshot_hebrew") or "—"
            if col == _HIST_COL_NIQQUD:
                return payload.get("snapshot_niqqud") or "—"
            if col == _HIST_COL_TRANSLATION:
                return payload.get("snapshot_translation") or "—"
            if col == _HIST_COL_SOURCE:
                return payload.get("snapshot_source_label") or "—"
            if col == _HIST_COL_STATUS:
                status = str(payload.get("audio_status") or "unknown").strip().lower()
                resolved = str(payload.get("resolved_path") or "")
                if resolved and resolved != "." and os.path.exists(resolved):
                    return "ready"
                if status in {"ready", "missing", "failed", "generating", "stale", "unknown"}:
                    return status
                return "unknown"
            if col == _HIST_COL_PLAYED_AT:
                return payload.get("played_at") or "—"
            if col == _HIST_COL_RATE:
                try:
                    rate = float(payload.get("rate_used") or 1.0)
                    return f"{rate:.2f}x"
                except (TypeError, ValueError):
                    return "1.00x"
            if col == _HIST_COL_PROJECT:
                return payload.get("snapshot_project_name") or "—"
            if col == _HIST_COL_DOCUMENT:
                return payload.get("snapshot_document_name") or "—"
            if col == _HIST_COL_SOURCE_ID:
                source_id = payload.get("source_id")
                return str(source_id) if source_id is not None else "—"
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col in (
                _HIST_COL_HEBREW,
                _HIST_COL_NIQQUD,
                _HIST_COL_TRANSLATION,
                _HIST_COL_SOURCE,
                _HIST_COL_PROJECT,
                _HIST_COL_DOCUMENT,
            ):
                key = {
                    _HIST_COL_HEBREW: "snapshot_hebrew",
                    _HIST_COL_NIQQUD: "snapshot_niqqud",
                    _HIST_COL_TRANSLATION: "snapshot_translation",
                    _HIST_COL_SOURCE: "snapshot_source_label",
                    _HIST_COL_PROJECT: "snapshot_project_name",
                    _HIST_COL_DOCUMENT: "snapshot_document_name",
                }[col]
                return payload.get(key) or ""
            if col == _HIST_COL_STATUS:
                status = self.data(index, Qt.ItemDataRole.DisplayRole)
                return _status_tooltip_text(status)
            if col == _HIST_COL_PLAYED_AT:
                return payload.get("played_at") or ""
            return None

        return None

    def row_payload(self, row: int) -> Optional[Dict[str, Any]]:
        if row < 0 or row >= len(self._rows):
            return None
        return dict(self._rows[row])

    def entry_count(self) -> int:
        return len(self._rows)

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
    _DOC_ROLE_ID = Qt.ItemDataRole.UserRole
    _DOC_ROLE_NAME = Qt.ItemDataRole.UserRole + 1
    _DOC_ROLE_SENTENCES = Qt.ItemDataRole.UserRole + 2
    _DOC_PAGE_SIZE = 200

    def __init__(self, *, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add All to Queue")
        self.setMinimumWidth(460)
        self.setMinimumHeight(420)

        self._project_ids: List[int] = []
        self._estimate_cache: Dict[Tuple[int, str], int] = {}
        self._selected_doc_meta: Dict[int, Tuple[str, int]] = {}
        self._doc_request_id = 0
        self._doc_worker: Optional[ProjectDocumentsPageWorker] = None
        self._doc_count_pending = False
        self._doc_total_matches = 0
        self._doc_rows: List[Any] = []
        self._db = None
        try:
            from app.services.db_service import DBService
            self._db = DBService.get_instance()
        except Exception as exc:
            logger.warning("AddAllToQueueDialog: no DBService: %s", exc)

        self._doc_search_timer = QTimer(self)
        self._doc_search_timer.setSingleShot(True)
        self._doc_search_timer.setInterval(250)
        self._doc_search_timer.timeout.connect(self._reload_doc_matches)

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
        search_lbl = QLabel("Search")
        search_lbl.setFixedWidth(42)
        self.doc_search = QLineEdit()
        self.doc_search.setPlaceholderText("Type to search project documents...")
        self.doc_search.setClearButtonEnabled(True)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self.doc_search)
        doc_vl.addLayout(search_row)

        self.doc_hint_label = QLabel(
            "Type to search specific processed documents. Leave search empty and "
            "selection empty to use all project documents."
        )
        self.doc_hint_label.setWordWrap(True)
        self.doc_hint_label.setStyleSheet("color: #666; font-size: 11px;")
        doc_vl.addWidget(self.doc_hint_label)

        # Document list
        self.doc_list = QListWidget()
        self.doc_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.doc_list.setAlternatingRowColors(True)
        self.doc_list.setMinimumHeight(160)
        self.doc_list.setToolTip(
            "Search loads processed documents for selection.\n"
            "Leave nothing selected to use all project documents."
        )
        doc_vl.addWidget(self.doc_list, 1)

        # Buttons + count
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select Results")
        self.select_all_btn.setFixedWidth(96)
        self.clear_sel_btn = QPushButton("Clear")
        self.clear_sel_btn.setFixedWidth(60)
        self.doc_sel_label = QLabel("All project documents (none selected)")
        self.doc_sel_label.setStyleSheet("color: gray; font-size: 11px;")
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.clear_sel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.doc_sel_label)
        doc_vl.addLayout(btn_row)
        self.doc_status_label = QLabel("Type to search project documents for specific selection.")
        self.doc_status_label.setWordWrap(True)
        self.doc_status_label.setStyleSheet("color: #666; font-size: 11px;")
        doc_vl.addWidget(self.doc_status_label)
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
        self.doc_search.textChanged.connect(self._on_doc_search_text_changed)
        self.select_all_btn.clicked.connect(self._select_all_docs)
        self.clear_sel_btn.clicked.connect(self._clear_doc_selection)
        self.doc_list.itemSelectionChanged.connect(self._on_doc_selection_changed)

        # Initial state
        self._on_kind_changed(0)

    # ── Data loading ──────────────────────────────────────────────────

    def _session_scope(self):
        if not self._db:
            raise RuntimeError("database unavailable")
        get_read_session = getattr(self._db, "get_read_session", None)
        if callable(get_read_session):
            return get_read_session()
        return self._db.get_session()

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
            with self._session_scope() as session:
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

    def _clear_doc_results(self, status_text: str) -> None:
        self._doc_search_timer.stop()
        self._doc_rows = []
        self._doc_total_matches = 0
        self._doc_count_pending = False
        self.doc_list.clear()
        self.doc_status_label.setText(status_text)
        self._update_sel_label()

    def _cancel_doc_worker(self) -> None:
        self._doc_search_timer.stop()
        worker = self._doc_worker
        if worker and worker.isRunning():
            worker.cancel()
            worker.wait(200)
        self._doc_worker = None

    # ── Slot handlers ─────────────────────────────────────────────────

    def _on_kind_changed(self, index: int) -> None:
        _, show_docs = self._KIND_META[index] if index < len(self._KIND_META) else ("sentence", True)
        self.doc_group.setVisible(show_docs)
        if show_docs:
            self._clear_doc_results("Type to search project documents for specific selection.")
            if self.doc_search.text().strip():
                self._schedule_doc_search(immediate=True)
        else:
            self._cancel_doc_worker()
            self._selected_doc_meta.clear()
            self.doc_search.blockSignals(True)
            self.doc_search.clear()
            self.doc_search.blockSignals(False)
            self._clear_doc_results("Document filter is available for Sentences only.")
        self._update_estimate()

    def _on_project_changed(self, index: int) -> None:
        pid = self._get_project_id(index)
        kind_idx = self.kind_combo.currentIndex()
        _, show_docs = self._KIND_META[kind_idx] if kind_idx < len(self._KIND_META) else ("sentence", True)
        if show_docs:
            self._cancel_doc_worker()
            self._selected_doc_meta.clear()
            if pid < 0:
                self._clear_doc_results("Select a project to search documents.")
            elif self.doc_search.text().strip():
                self._schedule_doc_search(immediate=True)
            else:
                self._clear_doc_results("Type to search project documents for specific selection.")
        self._update_estimate()

    def _on_doc_search_text_changed(self, _text: str) -> None:
        if self.selected_kind() != "sentence":
            return
        if not self.doc_search.text().strip():
            self._cancel_doc_worker()
            self._clear_doc_results("Search cleared. Leave selection empty to use all project documents.")
            return
        self._schedule_doc_search()

    def _schedule_doc_search(self, *, immediate: bool = False) -> None:
        if self.selected_kind() != "sentence":
            return
        if self.selected_project_id() < 0:
            self._clear_doc_results("Select a project to search documents.")
            return
        if not self.doc_search.text().strip():
            self._clear_doc_results("Type to search project documents for specific selection.")
            return
        self.doc_status_label.setText("Searching processed documents...")
        if immediate:
            self._doc_search_timer.stop()
            self._reload_doc_matches()
            return
        self._doc_search_timer.start()

    def _reload_doc_matches(self) -> None:
        if self.selected_kind() != "sentence":
            return
        pid = self.selected_project_id()
        query = self.doc_search.text().strip()
        if pid < 0 or not query:
            return

        self._doc_request_id += 1
        request_id = self._doc_request_id
        self._cancel_doc_worker()
        self._doc_count_pending = True
        self.doc_status_label.setText("Loading matching processed documents...")

        worker = ProjectDocumentsPageWorker(
            request_id=request_id,
            project_id=pid,
            search_query=query,
            status_filter="processed",
            page_size=self._DOC_PAGE_SIZE,
            page_index=1,
            include_frequent_tags=False,
        )
        worker.status.connect(self._on_doc_worker_status)
        worker.rows_loaded.connect(self._on_doc_rows_loaded)
        worker.count_loaded.connect(self._on_doc_count_loaded)
        worker.error.connect(self._on_doc_error)
        self._doc_worker = worker
        worker.start()

    def _on_doc_worker_status(self, request_id: int, text: str) -> None:
        if int(request_id) != self._doc_request_id:
            return
        self.doc_status_label.setText(text)

    def _on_doc_rows_loaded(self, request_id: int, rows: list) -> None:
        if int(request_id) != self._doc_request_id:
            return
        self._doc_rows = list(rows or [])
        self.doc_list.blockSignals(True)
        self.doc_list.clear()
        for doc in self._doc_rows:
            count_str = f"{int(doc.sentence_count or 0):,}" if doc.sentence_count is not None else "?"
            level_str = f"  [{doc.level}]" if getattr(doc, "level", None) else ""
            label = f"{doc.file_name}    {count_str} sent.{level_str}"
            item = QListWidgetItem(label)
            doc_id = int(doc.doc_id)
            item.setData(self._DOC_ROLE_ID, doc_id)
            item.setData(self._DOC_ROLE_NAME, doc.file_name or f"Document #{doc_id}")
            item.setData(self._DOC_ROLE_SENTENCES, int(doc.sentence_count or 0))
            item.setToolTip(f"doc_id={doc_id}  |  {count_str} sentences{level_str}")
            self.doc_list.addItem(item)
            if doc_id in self._selected_doc_meta:
                item.setSelected(True)
        self.doc_list.blockSignals(False)
        self._update_sel_label()
        if not self._doc_rows:
            self.doc_status_label.setText("No matching processed documents on this page; calculating total...")
            return
        self.doc_status_label.setText(
            f"Loaded {len(self._doc_rows):,} matching processed documents; calculating total..."
        )

    def _on_doc_count_loaded(self, request_id: int, total_count: int) -> None:
        if int(request_id) != self._doc_request_id:
            return
        self._doc_total_matches = int(total_count or 0)
        self._doc_count_pending = False
        self._update_sel_label()
        if self._doc_total_matches <= 0:
            self.doc_status_label.setText("No matching processed documents.")
            return
        shown = len(self._doc_rows)
        if shown and self._doc_total_matches > shown:
            self.doc_status_label.setText(
                f"Showing first {shown:,} of {self._doc_total_matches:,} matching processed documents."
            )
            return
        self.doc_status_label.setText(
            f"Showing {max(shown, self._doc_total_matches):,} matching processed documents."
        )

    def _on_doc_error(self, request_id: int, message: str) -> None:
        if int(request_id) != self._doc_request_id:
            return
        self._doc_count_pending = False
        logger.error("AddAllToQueueDialog document search failed: %s", message)
        self.doc_status_label.setText(f"Document search failed: {message}")

    def _select_all_docs(self) -> None:
        self.doc_list.clearSelection()
        for i in range(self.doc_list.count()):
            self.doc_list.item(i).setSelected(True)

    def _clear_doc_selection(self) -> None:
        self._selected_doc_meta.clear()
        self.doc_list.clearSelection()
        self._update_sel_label()
        self._update_estimate()

    def _on_doc_selection_changed(self) -> None:
        for i in range(self.doc_list.count()):
            item = self.doc_list.item(i)
            doc_id = int(item.data(self._DOC_ROLE_ID))
            if item.isSelected():
                self._selected_doc_meta[doc_id] = (
                    str(item.data(self._DOC_ROLE_NAME) or f"Document #{doc_id}"),
                    int(item.data(self._DOC_ROLE_SENTENCES) or 0),
                )
            else:
                self._selected_doc_meta.pop(doc_id, None)
        self._update_sel_label()
        self._update_estimate()

    def _update_sel_label(self) -> None:
        selected = len(self._selected_doc_meta)
        query = self.doc_search.text().strip()
        shown = len(self._doc_rows)
        if selected:
            self.doc_sel_label.setText(f"Selected: {selected:,} document(s)")
            return
        if not query:
            self.doc_sel_label.setText("All project documents (none selected)")
            return
        if self._doc_count_pending:
            if shown:
                self.doc_sel_label.setText(
                    f"No selection. Showing {shown:,} matching docs; none selected = all docs."
                )
            else:
                self.doc_sel_label.setText("Searching processed documents...")
            return
        if self._doc_total_matches <= 0:
            self.doc_sel_label.setText("No matching processed documents")
            return
        if self._doc_total_matches > shown:
            self.doc_sel_label.setText(
                f"No selection. Showing first {shown:,} of {self._doc_total_matches:,} matches; none selected = all docs."
            )
            return
        self.doc_sel_label.setText(
            f"No selection. {self._doc_total_matches:,} matches; none selected = all docs."
        )

    def _get_cached_project_estimate(self, project_id: int, kind: str) -> int:
        cache_key = (int(project_id), str(kind))
        if cache_key not in self._estimate_cache:
            self._estimate_cache[cache_key] = self._query_project_estimate(project_id, kind)
        return int(self._estimate_cache[cache_key])

    def _query_project_estimate(self, project_id: int, kind: str) -> int:
        from sqlalchemy import func, select

        with self._session_scope() as session:
            if kind == "sentence":
                from app.infra.sa_models import SourceCorpus, SourceDocument

                stmt = (
                    select(func.coalesce(func.sum(SourceDocument.sentence_count), 0))
                    .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                    .where(SourceCorpus.project_id == int(project_id))
                )
            elif kind == "lemma":
                from app.infra.sa_models import Lemma

                stmt = (
                    select(func.count(Lemma.lemma_id))
                    .where(Lemma.project_id == int(project_id))
                    .where(Lemma.is_noise == 0)
                )
            else:
                from app.infra.sa_models import TermCluster

                stmt = (
                    select(func.count(TermCluster.cluster_id))
                    .where(TermCluster.project_id == int(project_id))
                    .where(TermCluster.is_noise == 0)
                    .where(TermCluster.curation_status != "rejected")
                )
            return int(session.execute(stmt).scalar() or 0)

    def _update_estimate(self) -> None:
        pid = self._get_project_id(self.project_combo.currentIndex())
        kind_idx = self.kind_combo.currentIndex()
        kind, _ = self._KIND_META[kind_idx] if kind_idx < len(self._KIND_META) else ("sentence", True)

        if pid < 0 or not self._db:
            self.estimate_label.setText("(select a project to see estimate)")
            return
        try:
            if kind == "sentence":
                doc_ids = self.selected_doc_ids()
                if doc_ids:
                    count = sum(int(meta[1] or 0) for meta in self._selected_doc_meta.values())
                    self.estimate_label.setText(
                        f"~{count:,} sentences from {len(doc_ids):,} selected document(s)"
                    )
                else:
                    count = self._get_cached_project_estimate(pid, kind)
                    self.estimate_label.setText(f"~{count:,} sentences from all documents")
            elif kind == "lemma":
                count = self._get_cached_project_estimate(pid, kind)
                self.estimate_label.setText(f"~{count:,} lemmas (project-wide)")
            else:
                count = self._get_cached_project_estimate(pid, kind)
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
        """Return selected doc_ids across searches, or [] for all documents."""
        return sorted(int(doc_id) for doc_id in self._selected_doc_meta)

    def selected_add_mode(self) -> str:
        idx = self.mode_combo.currentIndex()
        return ["append", "after_current", "prepend"][max(0, idx)]

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel_doc_worker()
        super().closeEvent(event)


class AddQueueToPlaylistDialog(QDialog):
    """Queue -> playlist picker with dedup preview and add mode."""
    playlist_created = pyqtSignal(int)

    def __init__(
        self,
        *,
        parent: Optional[QWidget],
        db_manager: Any,
        selected_count: int,
        source_keys: Optional[List[Tuple[Optional[int], str, Optional[int]]]] = None,
        default_playlist_id: Optional[int] = None,
        default_after_entry_id: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Selected Queue Rows to Playlist")
        self.setMinimumWidth(460)
        self.setMinimumHeight(360)
        self._db = db_manager
        self._selected_count = int(selected_count)
        self._source_keys: List[Tuple[Optional[int], str, Optional[int]]] = list(source_keys or [])
        self._default_playlist_id = default_playlist_id
        self._default_after_entry_id = default_after_entry_id
        self._playlist_ids: List[int] = []

        root = QVBoxLayout(self)
        root.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("🔍"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search playlists…")
        self.search_edit.setClearButtonEnabled(True)
        search_row.addWidget(self.search_edit, 1)
        self.new_btn = QPushButton("New…")
        self.new_btn.setToolTip("Create a new playlist")
        search_row.addWidget(self.new_btn)
        root.addLayout(search_row)

        self.playlists_list = QListWidget()
        self.playlists_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.playlists_list.setAlternatingRowColors(True)
        root.addWidget(self.playlists_list, 1)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Add mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Append", "Prepend", "After selected entry"])
        options_row.addWidget(self.mode_combo)
        options_row.addStretch(1)
        self.dedup_cb = QCheckBox("Deduplicate by (project, kind, source_id)")
        self.dedup_cb.setChecked(True)
        options_row.addWidget(self.dedup_cb)
        root.addLayout(options_row)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #555;")
        root.addWidget(self.preview_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("Add")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self.search_edit.textChanged.connect(self._filter_playlists)
        self.new_btn.clicked.connect(self._on_new_playlist_clicked)
        self.playlists_list.itemSelectionChanged.connect(self._update_preview)
        self.mode_combo.currentTextChanged.connect(self._update_preview)
        self.dedup_cb.toggled.connect(self._update_preview)

        self._load_playlists()

    def _load_playlists(self, select_playlist_id: Optional[int] = None) -> None:
        self.playlists_list.blockSignals(True)
        self.playlists_list.clear()
        self._playlist_ids.clear()
        selected_row = -1
        if self._db is not None:
            try:
                from app.services.audio_queue_service import AudioQueueService

                with self._db.get_session() as session:
                    playlists = AudioQueueService().get_playlists(session)
            except Exception:
                playlists = []
        else:
            playlists = []
        target = select_playlist_id if select_playlist_id is not None else self._default_playlist_id
        for idx, playlist in enumerate(playlists):
            item = QListWidgetItem(f"{playlist.name} ({playlist.entry_count})")
            item.setData(Qt.ItemDataRole.UserRole, int(playlist.playlist_id))
            self.playlists_list.addItem(item)
            self._playlist_ids.append(int(playlist.playlist_id))
            if target is not None and int(playlist.playlist_id) == int(target):
                selected_row = idx
        if selected_row >= 0:
            self.playlists_list.setCurrentRow(selected_row)
        elif self.playlists_list.count() > 0:
            self.playlists_list.setCurrentRow(0)
        self.playlists_list.blockSignals(False)
        self._update_preview()

    def _filter_playlists(self, text: str) -> None:
        query = (text or "").strip().lower()
        for idx in range(self.playlists_list.count()):
            item = self.playlists_list.item(idx)
            item.setHidden(query not in item.text().lower())

    def _on_new_playlist_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "New Playlist", "Playlist name:")
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            return
        if self._db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return
        try:
            from app.services.audio_queue_service import AudioQueueService

            with self._db.get_session() as session:
                playlist_id = AudioQueueService().create_playlist(session, name)
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to create playlist:\n{exc}")
            return
        self._load_playlists(select_playlist_id=playlist_id)
        try:
            self.playlist_created.emit(int(playlist_id))
        except Exception:
            pass

    def selected_playlist_id(self) -> Optional[int]:
        item = self.playlists_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def selected_add_mode(self) -> str:
        label = str(self.mode_combo.currentText())
        return {
            "Append": "append",
            "Prepend": "prepend",
            "After selected entry": "after_selected",
        }.get(label, "append")

    def dedup_enabled(self) -> bool:
        return bool(self.dedup_cb.isChecked())

    def selected_after_entry_id(self) -> Optional[int]:
        if self.selected_add_mode() != "after_selected":
            return None
        return self._default_after_entry_id

    def _update_preview(self) -> None:
        playlist_id = self.selected_playlist_id()
        if playlist_id is None:
            self.preview_label.setText("Select a playlist.")
            return
        mode = self.selected_add_mode()
        dedup = self.dedup_enabled()
        mode_hint = {
            "append": "append",
            "prepend": "prepend",
            "after_selected": "after selected",
        }.get(mode, "append")
        text = f"Selected: {self._selected_count} rows ({mode_hint})."
        if dedup and self._db is not None and self._source_keys:
            try:
                from app.services.audio_queue_service import AudioQueueService

                with self._db.get_session() as session:
                    entries = AudioQueueService().get_playlist_entries(session, playlist_id)
                existing_keys = {
                    (
                        entry.project_id,
                        str(entry.kind or "").strip().lower(),
                        entry.source_id,
                    )
                    for entry in entries
                }
                duplicate_count = sum(
                    1
                    for key in self._source_keys
                    if (
                        key[0],
                        str(key[1] or "").strip().lower(),
                        key[2],
                    )
                    in existing_keys
                )
                new_count = max(0, self._selected_count - duplicate_count)
                text = (
                    f"Will add {self._selected_count} selected rows "
                    f"({new_count} new, {duplicate_count} duplicates)."
                )
            except Exception:
                text += " Duplicates will be skipped."
        elif dedup:
            text += " Duplicates will be skipped."
        if mode == "after_selected" and self._default_after_entry_id is None:
            text += " No selected playlist entry found; fallback to append."
        self.preview_label.setText(text)


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
        self._playlist_entries_model = AudioPlaylistEntriesTableModel(self)
        self._history_model = AudioHistoryTableModel(self)
        self._col_visible: List[bool] = [True] * len(_COLUMNS)
        self._col_visible[_COL_NUM] = True  # always shown
        self._col_visible[_COL_SOURCE_ID] = False
        self._playlist_col_visible: List[bool] = [True] * len(_PLAYLIST_COLUMNS)
        self._playlist_col_visible[_PL_COL_NUM] = True  # always shown
        self._playlist_col_visible[_PL_COL_SOURCE_ID] = False
        self._selected_source_payload: Optional[Dict[str, Any]] = None
        self._selected_queue_row_count: int = 0
        self._selected_history_row_count: int = 0
        self._selected_playlist_id: Optional[int] = None
        self._refresh_in_progress: bool = False

        self._init_ui()
        self._connect_signals()
        self._restore_settings()
        self._refresh_queue()
        self._refresh_playlists()
        self._refresh_history_entries()
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

        # Top row: tabs only. Queue actions are rendered inside Queue tab header.
        tab_header = QHBoxLayout()
        self.tab_widget = QTabWidget()
        tab_header.addWidget(self.tab_widget, 1)

        self.add_all_btn = QPushButton("Add All…")
        self.add_all_btn.setToolTip("Add all items from a project source to the queue")
        self.add_all_btn.setFixedWidth(78)
        self.add_all_btn.clicked.connect(self._on_add_all_clicked)

        self.add_queue_to_playlist_btn = QPushButton("Add to Playlist…")
        self.add_queue_to_playlist_btn.setToolTip("Copy selected Queue rows into a playlist")
        self.add_queue_to_playlist_btn.setFixedWidth(104)
        self.add_queue_to_playlist_btn.setEnabled(False)
        self.add_queue_to_playlist_btn.clicked.connect(self._on_add_queue_selected_to_playlist_clicked)

        self.refresh_queue_btn = QPushButton("↻")
        self.refresh_queue_btn.setToolTip("Refresh Niqqud / Translation / Source from DB")
        self.refresh_queue_btn.setFixedWidth(32)
        self.refresh_queue_btn.clicked.connect(self._refresh_display_contexts)

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
        default_widths = [30, 200, 180, 160, 120, 70, 45, 130, 170, 90]
        for i, w in enumerate(default_widths):
            hdr.resizeSection(i, w)

        queue_widget = QWidget()
        queue_layout = QVBoxLayout(queue_widget)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(4)

        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("Queue"))
        queue_header.addStretch(1)
        queue_header.addWidget(self.add_all_btn)
        queue_header.addWidget(self.add_queue_to_playlist_btn)
        queue_header.addWidget(self.refresh_queue_btn)
        queue_header.addWidget(self.columns_btn)
        queue_layout.addLayout(queue_header)
        queue_layout.addWidget(self.queue_table, 1)

        self.tab_widget.addTab(queue_widget, "Queue")

        # ── Playlists tab ────────────────────────────────────────────────────
        playlists_widget = self._build_playlists_tab()
        self.playlists_tab_widget = playlists_widget
        self.tab_widget.addTab(playlists_widget, "Playlists")

        # ── History tab ──────────────────────────────────────────────────────
        history_widget = self._build_history_tab()
        self.history_tab_widget = history_widget
        self.tab_widget.addTab(history_widget, "History")

        return container

    def _build_playlists_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: playlist list
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        lv.addWidget(QLabel("Playlists"))
        self.playlists_list = QListWidget()
        self.playlists_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.playlists_list.setMaximumWidth(180)
        lv.addWidget(self.playlists_list, 1)

        pl_btns = QHBoxLayout()
        self.new_playlist_btn = QPushButton("New")
        self.new_playlist_btn.setToolTip("Create a new playlist")
        self.rename_playlist_btn = QPushButton("Rename")
        self.rename_playlist_btn.setToolTip("Rename selected playlist")
        self.delete_playlist_btn = QPushButton("Delete")
        self.delete_playlist_btn.setToolTip("Delete selected playlist")
        self.refresh_playlists_btn = QPushButton("↻")
        self.refresh_playlists_btn.setToolTip("Refresh playlists from DB")
        self.load_pl_btn = QPushButton("→ Queue")
        self.load_pl_btn.setToolTip("Load selected playlist to queue")
        pl_btns.addWidget(self.new_playlist_btn)
        pl_btns.addWidget(self.rename_playlist_btn)
        pl_btns.addWidget(self.delete_playlist_btn)
        pl_btns.addWidget(self.load_pl_btn)
        pl_btns.addWidget(self.refresh_playlists_btn)
        lv.addLayout(pl_btns)
        splitter.addWidget(left)

        # Right: playlist entries table
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Entries"))
        header_row.addStretch(1)
        self.play_playlist_btn = QPushButton("Play")
        self.play_playlist_btn.setToolTip("Play playlist from first entry (append to Queue)")
        header_row.addWidget(self.play_playlist_btn)
        self.play_playlist_selected_btn = QPushButton("Play Selected")
        self.play_playlist_selected_btn.setToolTip("Play from selected playlist entry")
        header_row.addWidget(self.play_playlist_selected_btn)
        self.add_playlist_to_queue_btn = QPushButton("Add to Queue")
        self.add_playlist_to_queue_btn.setToolTip("Append playlist entries to Queue")
        header_row.addWidget(self.add_playlist_to_queue_btn)
        self.add_queue_selected_to_playlist_btn = QPushButton("Add Queue Selected")
        self.add_queue_selected_to_playlist_btn.setToolTip("Copy selected Queue rows to this playlist")
        header_row.addWidget(self.add_queue_selected_to_playlist_btn)
        self.refresh_playlist_entries_btn = QPushButton("↻")
        self.refresh_playlist_entries_btn.setToolTip("Refresh Niqqud / Translation / Source from DB")
        self.refresh_playlist_entries_btn.setFixedWidth(32)
        header_row.addWidget(self.refresh_playlist_entries_btn)
        self.playlist_columns_btn = QToolButton()
        self.playlist_columns_btn.setText("⚙")
        self.playlist_columns_btn.setToolTip("Toggle playlist columns")
        self.playlist_columns_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._playlist_columns_menu = QMenu(self)
        self._playlist_col_actions = []
        for idx, col_name in enumerate(_PLAYLIST_COLUMNS):
            if idx == _PL_COL_NUM:
                continue
            act = self._playlist_columns_menu.addAction(col_name)
            act.setCheckable(True)
            act.setChecked(True)
            act.setData(idx)
            act.toggled.connect(self._on_playlist_column_toggled)
            self._playlist_col_actions.append(act)
        self.playlist_columns_btn.setMenu(self._playlist_columns_menu)
        header_row.addWidget(self.playlist_columns_btn)
        rv.addLayout(header_row)

        self.playlist_entries_table = QTableView()
        self.playlist_entries_table.setModel(self._playlist_entries_model)
        self.playlist_entries_table.setAlternatingRowColors(True)
        self.playlist_entries_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.playlist_entries_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.playlist_entries_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.playlist_entries_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.playlist_entries_table.horizontalHeader().setStretchLastSection(True)
        self.playlist_entries_table.verticalHeader().setVisible(False)
        self.playlist_entries_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_entries_table.installEventFilter(self)
        self.playlist_entries_table.viewport().installEventFilter(self)
        playlist_widths = [30, 220, 190, 180, 140, 70, 130, 170, 90]
        for idx, width in enumerate(playlist_widths):
            self.playlist_entries_table.horizontalHeader().resizeSection(idx, width)
        rv.addWidget(self.playlist_entries_table, 1)

        self._playlist_play_delegate = AudioPlayDelegate(
            self.playlist_entries_table,
            on_play_clicked=self._on_playlist_play_cell_clicked,
        )
        self.playlist_entries_table.setItemDelegateForColumn(_PL_COL_STATUS, self._playlist_play_delegate)

        entry_btns = QHBoxLayout()
        self.playlist_move_up_btn = QPushButton("↑")
        self.playlist_move_up_btn.setToolTip("Move selected entry up")
        self.playlist_move_up_btn.setFixedWidth(34)
        self.playlist_move_down_btn = QPushButton("↓")
        self.playlist_move_down_btn.setToolTip("Move selected entry down")
        self.playlist_move_down_btn.setFixedWidth(34)
        self.remove_playlist_entries_btn = QPushButton("Remove Selected")
        self.remove_playlist_entries_btn.setToolTip("Remove selected entries from playlist")
        entry_btns.addWidget(self.playlist_move_up_btn)
        entry_btns.addWidget(self.playlist_move_down_btn)
        entry_btns.addWidget(self.remove_playlist_entries_btn)
        entry_btns.addStretch(1)
        rv.addLayout(entry_btns)

        splitter.addWidget(right)
        splitter.setSizes([160, 400])

        return splitter

    def _build_history_tab(self) -> QWidget:
        root = QWidget()
        vl = QVBoxLayout(root)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("History"))
        header.addStretch(1)

        self.play_history_selected_btn = QPushButton("Play Selected")
        self.play_history_selected_btn.setToolTip("Play selected history rows")
        header.addWidget(self.play_history_selected_btn)

        self.add_history_to_queue_btn = QPushButton("Add to Queue")
        self.add_history_to_queue_btn.setToolTip("Append selected history rows to Queue")
        header.addWidget(self.add_history_to_queue_btn)

        self.refresh_history_btn = QPushButton("↻")
        self.refresh_history_btn.setToolTip("Refresh history rows from DB")
        self.refresh_history_btn.setFixedWidth(32)
        header.addWidget(self.refresh_history_btn)
        vl.addLayout(header)

        self.history_table = QTableView()
        self.history_table.setModel(self._history_model)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.installEventFilter(self)
        self.history_table.viewport().installEventFilter(self)
        history_widths = [30, 220, 190, 180, 140, 70, 170, 70, 130, 170, 90]
        for idx, width in enumerate(history_widths):
            self.history_table.horizontalHeader().resizeSection(idx, width)
        vl.addWidget(self.history_table, 1)

        self._history_play_delegate = AudioPlayDelegate(
            self.history_table,
            on_play_clicked=self._on_history_play_cell_clicked,
        )
        self.history_table.setItemDelegateForColumn(_HIST_COL_STATUS, self._history_play_delegate)

        return root

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
        self._add_shortcut("Space", self._on_space_shortcut)
        self._add_shortcut("J", self.player.previous_track)
        self._add_shortcut("K", self.player.next_track)
        self._add_shortcut("+", self._speed_up)
        self._add_shortcut("=", self._speed_up)   # US keyboard + without shift
        self._add_shortcut("-", self._speed_down)
        self._add_shortcut("R", self._cycle_repeat)
        self._add_shortcut("Esc", lambda: self.player.stop(clear_queue=False))

        # Playlists tab
        self.new_playlist_btn.clicked.connect(self._on_new_playlist_clicked)
        self.rename_playlist_btn.clicked.connect(self._on_rename_playlist_clicked)
        self.delete_playlist_btn.clicked.connect(self._on_delete_playlist_clicked)
        self.refresh_playlists_btn.clicked.connect(self._refresh_playlists)
        self.load_pl_btn.clicked.connect(self._on_load_playlist_to_queue_clicked)
        self.add_playlist_to_queue_btn.clicked.connect(self._on_add_playlist_to_queue_clicked)
        self.play_playlist_btn.clicked.connect(self._on_play_playlist_clicked)
        self.play_playlist_selected_btn.clicked.connect(self._on_play_playlist_selected_clicked)
        self.add_queue_selected_to_playlist_btn.clicked.connect(self._on_add_queue_selected_to_playlist_clicked)
        self.remove_playlist_entries_btn.clicked.connect(self._on_remove_playlist_entries_clicked)
        self.playlist_move_up_btn.clicked.connect(lambda: self._on_move_playlist_entry(-1))
        self.playlist_move_down_btn.clicked.connect(lambda: self._on_move_playlist_entry(1))
        self.refresh_playlist_entries_btn.clicked.connect(self._refresh_playlist_display_contexts)
        self.playlists_list.itemSelectionChanged.connect(self._on_playlist_selection_changed)
        self.playlist_entries_table.customContextMenuRequested.connect(self._on_playlist_context_menu)
        self.playlist_entries_table.doubleClicked.connect(self._on_playlist_double_clicked)
        self.queue_table.clicked.connect(self._on_queue_table_clicked)
        self.playlist_entries_table.clicked.connect(self._on_playlist_table_clicked)
        self.history_table.clicked.connect(self._on_history_table_clicked)
        self.playlist_entries_table.selectionModel().selectionChanged.connect(
            self._on_playlist_entries_selection_changed
        )
        self.tab_widget.currentChanged.connect(lambda *_args: self._update_goto_source_state())

        # History tab
        self.play_history_selected_btn.clicked.connect(self._on_play_history_selected_clicked)
        self.add_history_to_queue_btn.clicked.connect(self._on_add_history_to_queue_clicked)
        self.refresh_history_btn.clicked.connect(self._refresh_history_entries)
        self.history_table.customContextMenuRequested.connect(self._on_history_context_menu)
        self.history_table.doubleClicked.connect(self._on_history_double_clicked)
        self.history_table.selectionModel().selectionChanged.connect(self._on_history_selection_changed)

        queue_header = self.queue_table.horizontalHeader()
        queue_header.sectionResized.connect(
            lambda *_args: self._save_header_state(self.queue_table, "audio_player/queue/header_state")
        )
        queue_header.sectionMoved.connect(
            lambda *_args: self._save_header_state(self.queue_table, "audio_player/queue/header_state")
        )
        playlist_header = self.playlist_entries_table.horizontalHeader()
        playlist_header.sectionResized.connect(
            lambda *_args: self._save_header_state(
                self.playlist_entries_table,
                "audio_player/playlist/header_state",
            )
        )
        playlist_header.sectionMoved.connect(
            lambda *_args: self._save_header_state(
                self.playlist_entries_table,
                "audio_player/playlist/header_state",
            )
        )
        history_header = self.history_table.horizontalHeader()
        history_header.sectionResized.connect(
            lambda *_args: self._save_header_state(
                self.history_table,
                "audio_player/history/header_state",
            )
        )
        history_header.sectionMoved.connect(
            lambda *_args: self._save_header_state(
                self.history_table,
                "audio_player/history/header_state",
            )
        )

    def _on_playlist_shortcut_play_selected(self) -> None:
        if not self._selected_playlist_entry_rows():
            return
        self._on_play_playlist_selected_clicked()

    def _on_playlist_shortcut_remove_selected(self) -> None:
        if not self._selected_playlist_entry_rows():
            return
        self._on_remove_playlist_entries_clicked()

    def eventFilter(self, watched, event):  # type: ignore[override]
        if watched in (self.playlist_entries_table, self.playlist_entries_table.viewport()):
            if event.type() == event.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    self._on_playlist_shortcut_play_selected()
                    return True
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._on_playlist_shortcut_remove_selected()
                    return True
        history_table = getattr(self, "history_table", None)
        if history_table is not None and watched in (history_table, history_table.viewport()):
            if event.type() == event.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    self._on_play_history_selected_clicked()
                    return True
        return super().eventFilter(watched, event)

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

    def _on_space_shortcut(self) -> None:
        fw = self.focusWidget()
        in_playlist_table = (
            fw is self.playlist_entries_table
            or fw is self.playlist_entries_table.viewport()
            or (fw is not None and self.playlist_entries_table.isAncestorOf(fw))
        )
        if in_playlist_table and self._selected_playlist_entry_rows():
            self._on_playlist_shortcut_play_selected()
            return
        history_table = getattr(self, "history_table", None)
        in_history_table = bool(
            history_table is not None
            and (
                fw is history_table
                or fw is history_table.viewport()
                or (fw is not None and history_table.isAncestorOf(fw))
            )
        )
        if in_history_table and self._selected_history_rows():
            self._on_play_history_selected_clicked()
            return
        self.player.toggle_pause()

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

        # Queue column visibility (with backward compatibility key)
        col_vis = s.get_json("audio_player/queue/columns_visible", None)
        if col_vis is None:
            col_vis = s.get_json("audio_player/columns_visible", None)
        if isinstance(col_vis, list) and len(col_vis) == len(_COLUMNS):
            for i, visible in enumerate(col_vis):
                self._col_visible[i] = bool(visible)
        for act in self._col_actions:
            col_idx = act.data()
            act.blockSignals(True)
            act.setChecked(bool(self._col_visible[col_idx]))
            act.blockSignals(False)
        self._apply_column_visibility()

        # Playlist column visibility
        pl_col_vis = s.get_json("audio_player/playlist/columns_visible", None)
        if isinstance(pl_col_vis, list) and len(pl_col_vis) == len(_PLAYLIST_COLUMNS):
            for i, visible in enumerate(pl_col_vis):
                self._playlist_col_visible[i] = bool(visible)
        for act in self._playlist_col_actions:
            col_idx = act.data()
            act.blockSignals(True)
            act.setChecked(bool(self._playlist_col_visible[col_idx]))
            act.blockSignals(False)
        self._apply_playlist_column_visibility()

        # Header states
        self._restore_header_state(self.queue_table, "audio_player/queue/header_state")
        self._restore_header_state(self.playlist_entries_table, "audio_player/playlist/header_state")
        self._restore_header_state(self.history_table, "audio_player/history/header_state")

        # Apply to player service
        self.player.set_playback_rate(self.speed_spin.value())
        mode_key = self._REPEAT_MAP.get(self.repeat_combo.currentText(), "none")
        self.player.set_repeat_mode(mode_key)
        self.player.set_auto_pause(self.auto_pause_cb.isChecked())

    def _save_col_settings(self) -> None:
        self.settings.set_json("audio_player/queue/columns_visible", self._col_visible)
        self.settings.set_json("audio_player/playlist/columns_visible", self._playlist_col_visible)
        self.settings.sync()

    def _save_header_state(self, table: QTableView, key: str) -> None:
        try:
            state = bytes(table.horizontalHeader().saveState())
        except Exception:
            return
        self.settings.set_value(key, state)
        self.settings.sync()

    def _restore_header_state(self, table: QTableView, key: str) -> None:
        try:
            state = self.settings.get_bytes(key, b"")
            if state:
                table.horizontalHeader().restoreState(state)
        except Exception:
            return

    # ── Playlists tab DB wiring ───────────────────────────────────────────────

    def _get_db_manager(self):
        if self._db is not None:
            return self._db
        try:
            from app.services.db_service import DBService

            return DBService.get_instance()
        except Exception:
            return None

    def _refresh_playlists(self, select_playlist_id: Optional[int] = None) -> None:
        db = self._get_db_manager()
        if db is None:
            self.playlists_list.clear()
            self._playlist_entries_model.load([])
            self._selected_playlist_id = None
            self._update_playlist_action_state()
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                playlists = AudioQueueService().get_playlists(session)
        except Exception as exc:
            logger.debug("refresh playlists skipped: %s", exc)
            playlists = []

        previous_id = self._selected_playlist_id
        target_id = select_playlist_id if select_playlist_id is not None else previous_id
        self.playlists_list.blockSignals(True)
        self.playlists_list.clear()
        selected_row = -1
        for idx, playlist in enumerate(playlists):
            label = f"{playlist.name} ({playlist.entry_count})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(playlist.playlist_id))
            item.setData(Qt.ItemDataRole.UserRole + 1, str(playlist.name))
            self.playlists_list.addItem(item)
            if target_id is not None and int(playlist.playlist_id) == int(target_id):
                selected_row = idx
        if selected_row >= 0:
            self.playlists_list.setCurrentRow(selected_row)
        elif self.playlists_list.count() > 0:
            self.playlists_list.setCurrentRow(0)
        self.playlists_list.blockSignals(False)

        self.tab_widget.setTabText(1, f"Playlists ({len(playlists)})")
        self._on_playlist_selection_changed()

    def refresh_playlists_view(self, *, select_playlist_id: Optional[int] = None) -> None:
        """Public refresh hook for external views that modify playlists."""
        self._refresh_playlists(select_playlist_id=select_playlist_id)

    def _on_playlist_selection_changed(self) -> None:
        current = self.playlists_list.currentItem()
        playlist_id = None
        if current is not None:
            value = current.data(Qt.ItemDataRole.UserRole)
            try:
                playlist_id = int(value) if value is not None else None
            except (TypeError, ValueError):
                playlist_id = None
        self._selected_playlist_id = playlist_id
        self._refresh_playlist_entries()
        self._update_playlist_action_state()
        self._update_goto_source_state()

    def _refresh_playlist_entries(self) -> None:
        playlist_id = self._selected_playlist_id
        if playlist_id is None:
            self._playlist_entries_model.load([])
            self._update_playlist_action_state()
            self._update_goto_source_state()
            return

        db = self._get_db_manager()
        if db is None:
            self._playlist_entries_model.load([])
            self._update_playlist_action_state()
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                entries = AudioQueueService().get_playlist_entries(session, playlist_id)
        except Exception as exc:
            logger.debug("refresh playlist entries skipped: %s", exc)
            entries = []

        self._playlist_entries_model.load(entries)
        QTimer.singleShot(0, self._refresh_playlist_display_contexts)
        self._update_playlist_action_state()
        self._update_goto_source_state()

    class _CtxTrackProxy:
        __slots__ = ("context",)

        def __init__(self, context: Dict[str, Any]) -> None:
            self.context = context

    def _refresh_playlist_display_contexts(self) -> None:
        """Batch refresh playlist Niqqud/Translation/Source/Project/Document."""
        rows = [self._playlist_entries_model.row_payload(i) for i in range(self._playlist_entries_model.entry_count())]
        payloads = [row for row in rows if row]
        if not payloads:
            self._update_playlist_action_state()
            return

        proxies = [self._CtxTrackProxy(row) for row in payloads]
        sentence_proxies: List[Any] = []
        lemma_proxies: List[Any] = []
        term_proxies: List[Any] = []
        for proxy in proxies:
            kind = self._normalize_playlist_kind(str(proxy.context.get("kind") or ""))
            if kind == "sentence":
                sentence_proxies.append(proxy)
            elif kind == "lemma":
                lemma_proxies.append(proxy)
            elif kind == "term":
                term_proxies.append(proxy)

        try:
            db = self._get_db_manager()
            if db is None:
                self._update_playlist_action_state()
                return
            updated = 0
            with db.get_session() as session:
                updated += self._refresh_sentence_display(session, sentence_proxies)
                updated += self._refresh_lemma_display(session, lemma_proxies)
                updated += self._refresh_term_display(session, term_proxies)
        except Exception as exc:
            logger.warning("Playlist display refresh failed: %s", exc)
            self._update_playlist_action_state()
            return

        # Batch resolve ready audio paths for status/play button.
        try:
            ready_paths, _, _, source_rows = self._resolve_playlist_row_paths(list(range(len(payloads))))
            row_to_path = {
                source_rows[idx]: str(path)
                for idx, path in enumerate(ready_paths)
                if idx < len(source_rows)
            }
            for row_idx, payload in enumerate(payloads):
                resolved = row_to_path.get(row_idx)
                payload["resolved_path"] = resolved or ""
                payload["audio_status"] = "ready" if resolved else (payload.get("audio_status") or "missing")
        except Exception as exc:
            logger.warning("Playlist path refresh failed: %s", exc)

        if updated or payloads:
            self._playlist_entries_model.load_rows(payloads)
        self._update_playlist_action_state()

    def _on_playlist_entries_selection_changed(self, *_args) -> None:
        self._apply_action_policy()

    def _refresh_history_entries(self) -> None:
        db = self._get_db_manager()
        if db is None:
            self._history_model.load([])
            self.tab_widget.setTabText(2, "History (0)")
            self._update_history_action_state()
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            limit = int(self.settings.get_int("audio_player/history_limit", 200) or 200)
            limit = max(50, min(2000, limit))
            with db.get_session() as session:
                entries = AudioQueueService().get_history(session, limit=limit)
        except Exception as exc:
            logger.warning("History refresh failed: %s", exc)
            entries = []

        self._history_model.load(entries)
        self.tab_widget.setTabText(2, f"History ({len(entries)})")
        QTimer.singleShot(0, self._refresh_history_display_contexts)
        self._update_history_action_state()
        self._update_goto_source_state()

    def _refresh_history_display_contexts(self) -> None:
        rows = [self._history_model.row_payload(i) for i in range(self._history_model.entry_count())]
        payloads = [row for row in rows if row]
        if not payloads:
            self._update_history_action_state()
            return

        proxies = [self._CtxTrackProxy(row) for row in payloads]
        sentence_proxies: List[Any] = []
        lemma_proxies: List[Any] = []
        term_proxies: List[Any] = []
        for proxy in proxies:
            kind = self._normalize_playlist_kind(str(proxy.context.get("kind") or ""))
            if kind == "sentence":
                sentence_proxies.append(proxy)
            elif kind == "lemma":
                lemma_proxies.append(proxy)
            elif kind == "term":
                term_proxies.append(proxy)

        try:
            db = self._get_db_manager()
            if db is None:
                self._update_history_action_state()
                return
            with db.get_session() as session:
                self._refresh_sentence_display(session, sentence_proxies)
                self._refresh_lemma_display(session, lemma_proxies)
                self._refresh_term_display(session, term_proxies)
        except Exception as exc:
            logger.warning("History display refresh failed: %s", exc)
            self._update_history_action_state()
            return

        try:
            ready_paths, _, _, source_rows = self._resolve_history_row_paths(list(range(len(payloads))))
            row_to_path = {
                source_rows[idx]: str(path)
                for idx, path in enumerate(ready_paths)
                if idx < len(source_rows)
            }
            for row_idx, payload in enumerate(payloads):
                resolved = row_to_path.get(row_idx)
                payload["resolved_path"] = resolved or ""
                payload["audio_status"] = "ready" if resolved else (payload.get("audio_status") or "missing")
        except Exception as exc:
            logger.warning("History path refresh failed: %s", exc)

        self._history_model.load_rows(payloads)
        self._update_history_action_state()
        self._update_goto_source_state()

    def _selected_history_rows(self) -> List[int]:
        sel = self.history_table.selectionModel()
        if sel is None:
            return []
        return sorted({idx.row() for idx in sel.selectedRows()})

    def _on_history_selection_changed(self, *_args) -> None:
        self._selected_history_row_count = len(self._selected_history_rows())
        self._apply_action_policy()

    def _update_history_action_state(self) -> None:
        self._apply_action_policy()

    def _selected_playlist_entry_rows(self) -> List[int]:
        sel = self.playlist_entries_table.selectionModel()
        if sel is None:
            return []
        return sorted({idx.row() for idx in sel.selectedRows()})

    def _selected_playlist_entry_ids(self) -> List[int]:
        ids: List[int] = []
        for row in self._selected_playlist_entry_rows():
            entry_id = self._playlist_entries_model.entry_id_at(row)
            if entry_id is not None:
                ids.append(entry_id)
        return ids

    def _update_playlist_action_state(self) -> None:
        self._apply_action_policy()

    def _on_new_playlist_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "New Playlist", "Playlist name:")
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            return

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                playlist_id = AudioQueueService().create_playlist(session, name)
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to create playlist:\n{exc}")
            return

        self._refresh_playlists(select_playlist_id=playlist_id)

    def _on_rename_playlist_clicked(self) -> None:
        item = self.playlists_list.currentItem()
        playlist_id = self._selected_playlist_id
        if playlist_id is None or item is None:
            return
        current_name = str(item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
        new_name, ok = QInputDialog.getText(self, "Rename Playlist", "New name:", text=current_name)
        if not ok:
            return
        new_name = str(new_name or "").strip()
        if not new_name or new_name == current_name:
            return

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                AudioQueueService().rename_playlist(session, playlist_id, new_name)
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to rename playlist:\n{exc}")
            return

        self._refresh_playlists(select_playlist_id=playlist_id)

    def _on_delete_playlist_clicked(self) -> None:
        item = self.playlists_list.currentItem()
        playlist_id = self._selected_playlist_id
        if playlist_id is None or item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole + 1) or "selected playlist")
        answer = QMessageBox.question(
            self,
            "Delete Playlist",
            f"Delete playlist '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                AudioQueueService().delete_playlist(session, playlist_id)
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to delete playlist:\n{exc}")
            return

        self._refresh_playlists()

    def _build_playlist_specs_from_queue_rows(self, rows: List[int]) -> List[Any]:
        from app.services.audio_queue_service import AudioItemSpec

        specs: List[AudioItemSpec] = []
        for row in rows:
            track = self._track_at_row(row) or {}
            ctx = self._track_ctx_at_row(row)
            kind = self._normalize_queue_kind(str(ctx.get("kind") or "sentence"))
            source_id_raw = ctx.get("source_id")
            project_id_raw = ctx.get("project_id")
            audio_asset_id_raw = ctx.get("audio_asset_id")
            try:
                source_id = int(source_id_raw) if source_id_raw is not None else None
            except (TypeError, ValueError):
                source_id = None
            try:
                project_id = int(project_id_raw) if project_id_raw is not None else None
            except (TypeError, ValueError):
                project_id = None
            try:
                audio_asset_id = int(audio_asset_id_raw) if audio_asset_id_raw is not None else None
            except (TypeError, ValueError):
                audio_asset_id = None
            snapshot_hebrew = str(
                ctx.get("snapshot_hebrew") or track.get("label") or ""
            ).strip() or None
            snapshot_niqqud = str(ctx.get("snapshot_niqqud") or "").strip() or None
            snapshot_translation = str(ctx.get("snapshot_translation") or "").strip() or None
            snapshot_source_label = str(ctx.get("snapshot_source_label") or "").strip() or None
            audio_status = str(ctx.get("audio_status") or "unknown").strip() or "unknown"
            specs.append(
                AudioItemSpec(
                    kind=kind,
                    source_id=source_id,
                    project_id=project_id,
                    snapshot_hebrew=snapshot_hebrew,
                    snapshot_niqqud=snapshot_niqqud,
                    snapshot_translation=snapshot_translation,
                    snapshot_source_label=snapshot_source_label,
                    audio_asset_id=audio_asset_id,
                    audio_status=audio_status,
                )
            )
        return specs

    def _on_add_queue_selected_to_playlist_clicked(self) -> None:
        rows = self._selected_queue_rows()
        if not rows:
            QMessageBox.information(self, "Playlists", "Select Queue rows first.")
            return
        specs = self._build_playlist_specs_from_queue_rows(rows)
        if not specs:
            return

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        after_entry_id = None
        selected_playlist_rows = self._selected_playlist_entry_rows()
        if len(selected_playlist_rows) == 1:
            after_entry_id = self._playlist_entries_model.entry_id_at(selected_playlist_rows[0])

        dialog = AddQueueToPlaylistDialog(
            parent=self,
            db_manager=db,
            selected_count=len(specs),
            source_keys=[(spec.project_id, spec.kind, spec.source_id) for spec in specs],
            default_playlist_id=self._selected_playlist_id,
            default_after_entry_id=after_entry_id,
        )
        try:
            dialog.playlist_created.connect(
                lambda playlist_id: self.refresh_playlists_view(
                    select_playlist_id=int(playlist_id) if playlist_id is not None else None
                )
            )
        except Exception:
            pass
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        playlist_id = dialog.selected_playlist_id()
        if playlist_id is None:
            QMessageBox.warning(self, "Playlists", "Select a playlist.")
            return
        add_mode = dialog.selected_add_mode()
        dedup = dialog.dedup_enabled()
        after_selected_id = dialog.selected_after_entry_id()

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                added_count, skipped_count = AudioQueueService().add_items_to_playlist(
                    session,
                    playlist_id,
                    specs,
                    add_mode=add_mode,
                    after_entry_id=after_selected_id,
                    dedup_by_source=dedup,
                )
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to add entries:\n{exc}")
            return

        self._refresh_playlists(select_playlist_id=playlist_id)
        QTimer.singleShot(0, self._refresh_playlist_display_contexts)
        QMessageBox.information(
            self,
            "Playlists",
            f"Added: {added_count}\nSkipped duplicates: {skipped_count}",
        )

    def _on_load_playlist_to_queue_clicked(self) -> None:
        playlist_id = self._selected_playlist_id
        if playlist_id is None:
            return
        total_entries = self._playlist_entries_model.entry_count()
        if total_entries <= 0:
            QMessageBox.information(self, "Playlists", "Selected playlist is empty.")
            return
        answer = QMessageBox.question(
            self,
            "Load Playlist to Queue",
            f"Replace current Queue with {total_entries} playlist entries?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                AudioQueueService().clear_queue(session)
                new_item_ids = AudioQueueService().load_playlist_to_queue_ids(
                    session,
                    playlist_id,
                    mode="append",
                    current_position=0,
                )
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to load playlist:\n{exc}")
            return

        self.player.clear_queue()
        if new_item_ids:
            self._load_db_queue_to_player("append", new_item_ids=new_item_ids)
            QTimer.singleShot(0, self._refresh_display_contexts)
            self._refresh_queue()

        QMessageBox.information(self, "Playlists", f"Loaded {len(new_item_ids)} entries to Queue.")

    def _on_add_playlist_to_queue_clicked(self, rows: Optional[List[int]] = None) -> None:
        """Append playlist rows to Queue without clearing existing queue."""
        playlist_id = self._selected_playlist_id
        if playlist_id is None:
            return
        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        selected_rows = sorted(set(rows or []))
        if selected_rows:
            specs = []
            for row in selected_rows:
                payload = self._playlist_entries_model.row_payload(row)
                if not payload:
                    continue
                from app.services.audio_queue_service import AudioItemSpec

                specs.append(
                    AudioItemSpec(
                        kind=self._normalize_playlist_kind(str(payload.get("kind") or "sentence")),
                        source_id=payload.get("source_id"),
                        project_id=payload.get("project_id"),
                        snapshot_hebrew=payload.get("snapshot_hebrew"),
                        snapshot_niqqud=payload.get("snapshot_niqqud"),
                        snapshot_translation=payload.get("snapshot_translation"),
                        snapshot_source_label=payload.get("snapshot_source_label"),
                        audio_asset_id=payload.get("audio_asset_id"),
                        audio_status=payload.get("audio_status") or "unknown",
                    )
                )
            if not specs:
                return
            try:
                from app.services.audio_queue_service import AudioQueueService

                with db.get_session() as session:
                    new_item_ids = AudioQueueService().add_to_queue(
                        session,
                        specs,
                        mode="append",
                        current_position=self.player.current_index,
                    )
                    session.commit()
            except Exception as exc:
                QMessageBox.warning(self, "Playlists", f"Failed to append selected entries:\n{exc}")
                return
            if new_item_ids:
                self._load_db_queue_to_player("append", new_item_ids=new_item_ids)
                QTimer.singleShot(0, self._refresh_display_contexts)
                self._refresh_queue()
            QMessageBox.information(self, "Playlists", f"Appended {len(new_item_ids)} selected entries to Queue.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                new_item_ids = AudioQueueService().load_playlist_to_queue_ids(
                    session,
                    playlist_id,
                    mode="append",
                    current_position=self.player.current_index,
                )
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to append playlist:\n{exc}")
            return
        if new_item_ids:
            self._load_db_queue_to_player("append", new_item_ids=new_item_ids)
            QTimer.singleShot(0, self._refresh_display_contexts)
            self._refresh_queue()
        QMessageBox.information(self, "Playlists", f"Appended {len(new_item_ids)} entries to Queue.")

    def _selected_playlist_row_indices(self) -> List[int]:
        return self._selected_playlist_entry_rows()

    def _playlist_rows_for_play(self, selected_only: bool) -> List[int]:
        if selected_only:
            rows = self._selected_playlist_row_indices()
            return rows
        return list(range(self._playlist_entries_model.entry_count()))

    @staticmethod
    def _normalize_playlist_kind(kind: str) -> str:
        raw = (kind or "").strip().lower()
        if raw in {"term_cluster", "terms"}:
            return "term"
        if raw in {"surface", "sentences"}:
            return "sentence"
        return raw

    def _resolve_playlist_row_paths(
        self,
        rows: List[int],
    ) -> Tuple[List[Path], List[str], List[Dict[str, Any]], List[int]]:
        row_payload_pairs: List[Tuple[int, Dict[str, Any]]] = []
        for row in rows:
            payload = self._playlist_entries_model.row_payload(row)
            if payload:
                row_payload_pairs.append((row, payload))
        return self._resolve_row_payload_paths(row_payload_pairs)

    def _resolve_history_row_paths(
        self,
        rows: List[int],
    ) -> Tuple[List[Path], List[str], List[Dict[str, Any]], List[int]]:
        row_payload_pairs: List[Tuple[int, Dict[str, Any]]] = []
        for row in rows:
            payload = self._history_model.row_payload(row)
            if payload:
                row_payload_pairs.append((row, payload))
        return self._resolve_row_payload_paths(row_payload_pairs)

    def _resolve_row_payload_paths(
        self,
        row_payload_pairs: List[Tuple[int, Dict[str, Any]]],
    ) -> Tuple[List[Path], List[str], List[Dict[str, Any]], List[int]]:
        if not row_payload_pairs:
            return ([], [], [], [])
        db = self._get_db_manager()
        if db is None:
            return ([], [], [], [])

        from app.domain.normalization.normalizer import normalize_for_tm

        ready_by_asset: Dict[int, Path] = {}
        ready_by_norm: Dict[str, Path] = {}
        row_to_norm: Dict[int, str] = {}

        asset_ids = sorted(
            {
                int(payload["audio_asset_id"])
                for _row, payload in row_payload_pairs
                if payload.get("audio_asset_id") is not None
                and str(payload.get("audio_asset_id")).strip().isdigit()
            }
        )
        norm_list: List[str] = []
        kind_to_norm_kind = {"term": "term_cluster", "sentence": "surface", "lemma": "lemma"}
        for row, payload in row_payload_pairs:
            kind = self._normalize_playlist_kind(str(payload.get("kind") or ""))
            src_text = str(payload.get("snapshot_hebrew") or "").strip()
            if not src_text:
                continue
            norm_kind = kind_to_norm_kind.get(kind, "surface")
            try:
                norm = normalize_for_tm("he", src_text, norm_kind).norm
            except Exception:
                norm = ""
            if norm:
                row_to_norm[row] = norm
                norm_list.append(norm)

        try:
            from sqlalchemy import desc as _sa_desc
            from sqlalchemy import select as _sa_select

            from app.infra.sa_models import AudioAsset as _AudioAsset

            with db.get_session() as session:
                if asset_ids:
                    rows_asset = session.execute(
                        _sa_select(_AudioAsset.asset_id, _AudioAsset.audio_rel_path)
                        .where(_AudioAsset.asset_id.in_(asset_ids))
                        .where(_AudioAsset.asset_status == "ready")
                        .where(_AudioAsset.audio_rel_path.isnot(None))
                    ).all()
                    for asset_id, rel in rows_asset:
                        if rel:
                            abs_path = self._to_abs_audio_path(rel)
                            if abs_path:
                                ready_by_asset[int(asset_id)] = abs_path
                unique_norms = sorted(set(norm_list))
                if unique_norms:
                    rows_norm = session.execute(
                        _sa_select(_AudioAsset.norm_text, _AudioAsset.audio_rel_path)
                        .where(_AudioAsset.lang == "he")
                        .where(_AudioAsset.norm_text.in_(unique_norms))
                        .where(_AudioAsset.asset_status == "ready")
                        .where(_AudioAsset.audio_rel_path.isnot(None))
                        .order_by(_sa_desc(_AudioAsset.updated_at), _sa_desc(_AudioAsset.asset_id))
                    ).all()
                    for norm, rel in rows_norm:
                        if norm in ready_by_norm:
                            continue
                        abs_path = self._to_abs_audio_path(rel)
                        if abs_path:
                            ready_by_norm[str(norm)] = abs_path
        except Exception as exc:
            logger.warning("Audio path resolver failed: %s", exc)

        ready_paths: List[Path] = []
        labels: List[str] = []
        contexts: List[Dict[str, Any]] = []
        source_rows: List[int] = []
        for row, payload in row_payload_pairs:
            path = None
            asset_raw = payload.get("audio_asset_id")
            if asset_raw is not None:
                try:
                    path = ready_by_asset.get(int(asset_raw))
                except (TypeError, ValueError):
                    path = None
            if path is None:
                norm = row_to_norm.get(row)
                if norm:
                    path = ready_by_norm.get(norm)
            if path is None or str(path) in ("", ".") or not Path(path).exists():
                continue

            ready_paths.append(Path(path))
            labels.append(str(payload.get("snapshot_hebrew") or Path(path).stem))
            contexts.append(
                {
                    "snapshot_hebrew": str(payload.get("snapshot_hebrew") or ""),
                    "snapshot_niqqud": str(payload.get("snapshot_niqqud") or ""),
                    "snapshot_translation": str(payload.get("snapshot_translation") or ""),
                    "snapshot_source_label": str(payload.get("snapshot_source_label") or ""),
                    "snapshot_project_name": str(payload.get("snapshot_project_name") or ""),
                    "snapshot_document_name": str(payload.get("snapshot_document_name") or ""),
                    "kind": payload.get("kind"),
                    "source_id": payload.get("source_id"),
                    "project_id": payload.get("project_id"),
                    "audio_status": "ready",
                }
            )
            source_rows.append(row)
        return (ready_paths, labels, contexts, source_rows)

    @staticmethod
    def _to_abs_audio_path(rel_path: Any) -> Optional[Path]:
        try:
            rel = Path(str(rel_path))
            if rel.is_absolute() or ".." in rel.parts:
                return None
            from app.infra.resource_paths import ResourcePaths

            base = ResourcePaths.resolve_data_root(create=True)
            abs_path = base / rel
            if abs_path.exists():
                return abs_path
        except Exception:
            return None
        return None

    def _play_playlist_rows(self, rows: List[int]) -> None:
        if not rows:
            return
        ready_paths, labels, contexts, _ = self._resolve_playlist_row_paths(rows)
        if not ready_paths:
            status = "missing"
            for row in rows:
                payload = self._playlist_entries_model.row_payload(row)
                if not payload:
                    continue
                candidate = self._payload_row_status(payload)
                if candidate != "ready":
                    status = candidate
                    break
            self._show_play_unavailable(status)
            return
        try:
            from app.services.audio_playback_service import AudioPlaybackService

            AudioPlaybackService.launch_audio_files(
                ready_paths,
                labels=labels,
                play_mode="enqueue",
                contexts=contexts,
                start_immediately=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Playback Error", f"Failed to play playlist entries:\n{exc}")
            return
        self._refresh_queue()

    def _history_rows_for_play(self, selected_only: bool = True) -> List[int]:
        if selected_only:
            return self._selected_history_rows()
        return list(range(self._history_model.entry_count()))

    def _play_history_rows(self, rows: List[int]) -> None:
        if not rows:
            return
        ready_paths, labels, contexts, _ = self._resolve_history_row_paths(rows)
        if not ready_paths:
            status = "missing"
            for row in rows:
                payload = self._history_model.row_payload(row)
                if not payload:
                    continue
                candidate = self._payload_row_status(payload)
                if candidate != "ready":
                    status = candidate
                    break
            self._show_play_unavailable(status)
            return
        try:
            from app.services.audio_playback_service import AudioPlaybackService

            AudioPlaybackService.launch_audio_files(
                ready_paths,
                labels=labels,
                play_mode="enqueue",
                contexts=contexts,
                start_immediately=True,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Playback Error", f"Failed to play history rows:\n{exc}")
            return
        self._refresh_queue()

    def _on_play_history_selected_clicked(self) -> None:
        info = self._build_selection_info("history")
        state = self._compute_action_state(
            "history",
            info,
            has_current_source=self._source_payload_from_context(self._current_track_context()) is not None,
        )["history_play_selected"]
        if not bool(state.get("enabled")):
            self._show_status_message(str(state.get("reason") or "No playable rows selected."))
            return
        rows = self._history_rows_for_play(selected_only=True)
        self._play_history_rows(rows)

    def _on_add_history_to_queue_clicked(self, rows: Optional[List[int]] = None) -> None:
        selected_rows = sorted(set(rows or self._selected_history_rows()))
        if not selected_rows:
            self._show_status_message("Select one or more history rows.")
            return
        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "History", "Database connection is unavailable.")
            return
        try:
            from app.services.audio_queue_service import AudioItemSpec, AudioQueueService

            specs = []
            for row in selected_rows:
                payload = self._history_model.row_payload(row)
                if not payload:
                    continue
                specs.append(
                    AudioItemSpec(
                        kind=self._normalize_playlist_kind(str(payload.get("kind") or "sentence")),
                        source_id=payload.get("source_id"),
                        project_id=payload.get("project_id"),
                        snapshot_hebrew=payload.get("snapshot_hebrew"),
                        snapshot_niqqud=payload.get("snapshot_niqqud"),
                        snapshot_translation=payload.get("snapshot_translation"),
                        snapshot_source_label=payload.get("snapshot_source_label"),
                        audio_asset_id=payload.get("audio_asset_id"),
                        audio_status=payload.get("audio_status") or "unknown",
                    )
                )
            if not specs:
                return
            with db.get_session() as session:
                new_item_ids = AudioQueueService().add_to_queue(
                    session,
                    specs,
                    mode="append",
                    current_position=self.player.current_index,
                )
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "History", f"Failed to append selected entries:\n{exc}")
            return

        if new_item_ids:
            self._load_db_queue_to_player("append", new_item_ids=new_item_ids)
            QTimer.singleShot(0, self._refresh_display_contexts)
            self._refresh_queue()

    def _on_history_double_clicked(self, index: QModelIndex) -> None:
        self._play_history_rows([index.row()])

    def _on_history_play_cell_clicked(self, index: QModelIndex) -> None:
        self._play_history_rows([index.row()])

    def _copy_history_cell(self, row: int, col: int) -> None:
        try:
            from PyQt6.QtWidgets import QApplication

            idx = self._history_model.index(row, col)
            text = str(self._history_model.data(idx, Qt.ItemDataRole.DisplayRole) or "")
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _on_play_playlist_clicked(self) -> None:
        info = self._build_selection_info("playlist")
        state = self._compute_action_state(
            "playlist",
            info,
            has_current_source=self._source_payload_from_context(self._current_track_context()) is not None,
            has_playlist=self._selected_playlist_id is not None,
            playlist_entry_count=self._playlist_entries_model.entry_count(),
            playlist_any_ready=self._playlist_has_any_ready(),
            queue_selection_count=len(self._selected_queue_rows()),
        )["playlist_play_all"]
        if not bool(state.get("enabled")):
            self._show_status_message(str(state.get("reason") or "No playable rows in selected playlist."))
            return
        rows = self._playlist_rows_for_play(selected_only=False)
        self._play_playlist_rows(rows)

    def _on_play_playlist_selected_clicked(self) -> None:
        info = self._build_selection_info("playlist")
        state = self._compute_action_state(
            "playlist",
            info,
            has_current_source=self._source_payload_from_context(self._current_track_context()) is not None,
            has_playlist=self._selected_playlist_id is not None,
            playlist_entry_count=self._playlist_entries_model.entry_count(),
            playlist_any_ready=self._playlist_has_any_ready(),
            queue_selection_count=len(self._selected_queue_rows()),
        )["playlist_play_selected"]
        if not bool(state.get("enabled")):
            self._show_status_message(str(state.get("reason") or "No playable rows selected."))
            return
        rows = self._playlist_rows_for_play(selected_only=True)
        self._play_playlist_rows(rows)

    def _on_remove_playlist_entries_clicked(self) -> None:
        playlist_id = self._selected_playlist_id
        entry_ids = self._selected_playlist_entry_ids()
        if playlist_id is None or not entry_ids:
            return

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                AudioQueueService().remove_from_playlist(session, playlist_id, entry_ids)
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to remove entries:\n{exc}")
            return

        self._refresh_playlists(select_playlist_id=playlist_id)

    def _on_move_playlist_entry(self, delta: int) -> None:
        playlist_id = self._selected_playlist_id
        rows = self._selected_playlist_entry_rows()
        if playlist_id is None or len(rows) != 1:
            return
        row = rows[0]
        target = row + int(delta)
        entry_ids = self._playlist_entries_model.entry_ids_in_order()
        if row < 0 or row >= len(entry_ids) or target < 0 or target >= len(entry_ids):
            return
        entry_ids[row], entry_ids[target] = entry_ids[target], entry_ids[row]

        db = self._get_db_manager()
        if db is None:
            QMessageBox.warning(self, "Playlists", "Database connection is unavailable.")
            return

        try:
            from app.services.audio_queue_service import AudioQueueService

            with db.get_session() as session:
                AudioQueueService().reorder_playlist_entries(session, playlist_id, entry_ids)
                session.commit()
        except Exception as exc:
            QMessageBox.warning(self, "Playlists", f"Failed to reorder entries:\n{exc}")
            return

        self._refresh_playlists(select_playlist_id=playlist_id)
        if 0 <= target < self.playlist_entries_table.model().rowCount():
            self.playlist_entries_table.selectRow(target)
        self._update_playlist_action_state()

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
        self._save_header_state(self.queue_table, "audio_player/queue/header_state")

    def _on_playlist_column_toggled(self, checked: bool) -> None:
        act = self.sender()
        if act is None:
            return
        col_idx = act.data()
        if col_idx is None:
            return
        self._playlist_col_visible[col_idx] = checked
        self._apply_playlist_column_visibility()
        self._save_col_settings()
        self._save_header_state(self.playlist_entries_table, "audio_player/playlist/header_state")

    def _apply_column_visibility(self) -> None:
        for col, visible in enumerate(self._col_visible):
            if col == _COL_NUM:
                self.queue_table.showColumn(col)
            elif visible:
                self.queue_table.showColumn(col)
            else:
                self.queue_table.hideColumn(col)

    def _apply_playlist_column_visibility(self) -> None:
        for col, visible in enumerate(self._playlist_col_visible):
            if col == _PL_COL_NUM:
                self.playlist_entries_table.showColumn(col)
            elif visible:
                self.playlist_entries_table.showColumn(col)
            else:
                self.playlist_entries_table.hideColumn(col)

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

    def _show_status_message(self, message: str, timeout_ms: int = 4500) -> None:
        text = str(message or "").strip()
        if not text:
            return
        status_bar = None
        win = self.window()
        if win is not None and hasattr(win, "statusBar"):
            try:
                status_bar = win.statusBar()
            except Exception:
                status_bar = None
        if status_bar is not None:
            try:
                status_bar.showMessage(text, int(timeout_ms))
                return
            except Exception:
                pass
        logger.info("Audio Player: %s", text)

    def _show_play_unavailable(self, raw_status: Any) -> None:
        self._show_status_message(_status_unavailable_message(raw_status))

    def _queue_row_status(self, row: int) -> str:
        track = self._track_at_row(row) or {}
        ctx = self._track_ctx_at_row(row)
        if bool(ctx.get("is_stale")):
            return "stale"
        path_raw = track.get("path")
        path = str(path_raw or "")
        if path and path != "." and Path(path).exists():
            return "ready"
        hint = _normalize_status_token(ctx.get("audio_status"))
        if hint in {"generating", "failed", "error"}:
            return hint
        return "missing"

    @staticmethod
    def _payload_row_status(payload: Dict[str, Any]) -> str:
        resolved = str(payload.get("resolved_path") or "")
        if resolved and resolved != "." and Path(resolved).exists():
            return "ready"
        return _normalize_status_token(payload.get("audio_status"))

    def _build_selection_info(self, tab_key: str) -> Dict[str, Any]:
        infos: List[Dict[str, Any]] = []
        if tab_key == "queue":
            rows = self._selected_queue_rows()
            for row in rows:
                ctx = self._track_ctx_at_row(row)
                kind = self._normalize_queue_kind(str(ctx.get("kind") or ""))
                status = self._queue_row_status(row)
                infos.append(
                    {
                        "row": row,
                        "kind": kind,
                        "status": status,
                        "has_source_payload": self._source_payload_from_context(ctx) is not None,
                    }
                )
        elif tab_key == "playlist":
            rows = self._selected_playlist_entry_rows()
            for row in rows:
                payload = self._playlist_entries_model.row_payload(row) or {}
                kind = self._normalize_playlist_kind(str(payload.get("kind") or ""))
                status = self._payload_row_status(payload)
                infos.append(
                    {
                        "row": row,
                        "kind": kind,
                        "status": status,
                        "has_source_payload": self._source_payload_from_context(payload) is not None,
                    }
                )
        elif tab_key == "history":
            rows = self._selected_history_rows()
            for row in rows:
                payload = self._history_model.row_payload(row) or {}
                kind = self._normalize_playlist_kind(str(payload.get("kind") or ""))
                status = self._payload_row_status(payload)
                infos.append(
                    {
                        "row": row,
                        "kind": kind,
                        "status": status,
                        "has_source_payload": self._source_payload_from_context(payload) is not None,
                    }
                )
        else:
            rows = []

        count = len(infos)
        single_info = infos[0] if count == 1 else None
        return {
            "rows": rows,
            "infos": infos,
            "count": count,
            "has_selection": count > 0,
            "single": count == 1,
            "multi": count > 1,
            "single_info": single_info,
            "single_kind": single_info.get("kind") if single_info else None,
            "single_status": single_info.get("status") if single_info else None,
            "single_has_source_payload": bool(single_info.get("has_source_payload")) if single_info else False,
            "any_ready": any(info.get("status") == "ready" for info in infos),
            "any_stale": any(info.get("status") == "stale" for info in infos),
            "any_missing": any(info.get("status") in {"missing", "failed", "error", "unknown"} for info in infos),
        }

    @staticmethod
    def _state(enabled: bool, reason: str = "") -> Dict[str, Any]:
        return {"enabled": bool(enabled), "reason": str(reason or "")}

    def _compute_action_state(
        self,
        tab_key: str,
        selection_info: Dict[str, Any],
        *,
        has_current_source: bool,
        has_playlist: bool = False,
        playlist_entry_count: int = 0,
        playlist_any_ready: bool = False,
        queue_selection_count: int = 0,
    ) -> Dict[str, Dict[str, Any]]:
        states: Dict[str, Dict[str, Any]] = {}
        single_status = str(selection_info.get("single_status") or "")
        single_kind = str(selection_info.get("single_kind") or "")

        if selection_info.get("multi"):
            states["go_to_source"] = self._state(False, "Select exactly one row to open source.")
        elif selection_info.get("single"):
            if selection_info.get("single_has_source_payload"):
                states["go_to_source"] = self._state(True)
            else:
                states["go_to_source"] = self._state(False, "Source link is unavailable for selected row.")
        else:
            states["go_to_source"] = self._state(
                has_current_source,
                "" if has_current_source else "Select one row or start playback first.",
            )

        if tab_key == "queue":
            has_selection = bool(selection_info.get("has_selection"))
            single = bool(selection_info.get("single"))
            states["queue_add_to_playlist"] = self._state(
                has_selection,
                "" if has_selection else "Select queue rows first.",
            )
            states["queue_play_single"] = self._state(
                single and single_status == "ready",
                "" if single and single_status == "ready" else _status_unavailable_message(single_status)
                if single
                else "Select exactly one row.",
            )
            states["queue_edit_translation"] = self._state(single, "" if single else "Select exactly one row.")
            states["queue_clear_translation"] = self._state(
                has_selection,
                "" if has_selection else "Select one or more rows.",
            )
            states["queue_edit_pronunciation"] = self._state(
                single and single_kind in {"lemma", "term"},
                "" if single and single_kind in {"lemma", "term"} else "Available for one lemma/term row.",
            )
            states["queue_edit_sentence_niqqud"] = self._state(
                single and single_kind == "sentence",
                "" if single and single_kind == "sentence" else "Available for one sentence row.",
            )

        if tab_key == "playlist":
            has_selection = bool(selection_info.get("has_selection"))
            single = bool(selection_info.get("single"))
            single_row = selection_info.get("single_info", {}).get("row") if single else None
            states["playlist_rename"] = self._state(has_playlist, "" if has_playlist else "Select a playlist.")
            states["playlist_delete"] = self._state(has_playlist, "" if has_playlist else "Select a playlist.")
            states["playlist_load_to_queue"] = self._state(
                has_playlist and playlist_entry_count > 0,
                "" if has_playlist and playlist_entry_count > 0 else "Selected playlist is empty.",
            )
            states["playlist_add_to_queue"] = self._state(
                has_playlist and playlist_entry_count > 0,
                "" if has_playlist and playlist_entry_count > 0 else "Selected playlist is empty.",
            )
            states["playlist_play_all"] = self._state(
                has_playlist and playlist_any_ready,
                "" if has_playlist and playlist_any_ready else "No ready audio in selected playlist.",
            )
            states["playlist_play_selected"] = self._state(
                has_playlist and has_selection and bool(selection_info.get("any_ready")),
                ""
                if has_playlist and has_selection and bool(selection_info.get("any_ready"))
                else "Select at least one playable row.",
            )
            states["playlist_add_queue_selected"] = self._state(
                has_playlist and queue_selection_count > 0,
                "" if has_playlist and queue_selection_count > 0 else "Select queue rows first.",
            )
            states["playlist_refresh_entries"] = self._state(
                has_playlist,
                "" if has_playlist else "Select a playlist.",
            )
            states["playlist_remove_selected"] = self._state(
                has_playlist and has_selection,
                "" if has_playlist and has_selection else "Select one or more playlist rows.",
            )
            states["playlist_move_up"] = self._state(
                has_playlist and single and int(single_row) > 0 if single_row is not None else False,
                "Select one row that is not first.",
            )
            states["playlist_move_down"] = self._state(
                has_playlist and single and int(single_row) < (playlist_entry_count - 1)
                if single_row is not None
                else False,
                "Select one row that is not last.",
            )

        if tab_key == "history":
            has_selection = bool(selection_info.get("has_selection"))
            states["history_play_selected"] = self._state(
                has_selection and bool(selection_info.get("any_ready")),
                "" if has_selection and bool(selection_info.get("any_ready")) else "Select at least one playable row.",
            )
            states["history_add_to_queue"] = self._state(
                has_selection,
                "" if has_selection else "Select one or more history rows.",
            )
            states["history_refresh"] = self._state(True)

        return states

    def _is_playable_payload(self, payload: Optional[Dict[str, Any]]) -> bool:
        if not payload:
            return False
        return self._payload_row_status(payload) == "ready"

    def _playlist_has_any_ready(self) -> bool:
        for row in range(self._playlist_entries_model.entry_count()):
            payload = self._playlist_entries_model.row_payload(row)
            if self._is_playable_payload(payload):
                return True
        return False

    def _history_has_any_ready_selected(self) -> bool:
        for row in self._selected_history_rows():
            payload = self._history_model.row_payload(row)
            if self._is_playable_payload(payload):
                return True
        return False

    def _apply_action_state_to_button(self, button: QPushButton, state: Dict[str, Any]) -> None:
        enabled = bool(state.get("enabled"))
        reason = str(state.get("reason") or "")
        button.setEnabled(enabled)
        if reason and not enabled:
            button.setToolTip(reason)

    def _apply_action_state_to_menu_action(self, action, state: Dict[str, Any]) -> None:
        enabled = bool(state.get("enabled"))
        reason = str(state.get("reason") or "")
        action.setEnabled(enabled)
        if reason and not enabled:
            try:
                action.setToolTip(reason)
                action.setStatusTip(reason)
                action.setWhatsThis(reason)
            except Exception:
                pass

    def _apply_action_policy(self) -> None:
        queue_info = self._build_selection_info("queue")
        playlist_info = self._build_selection_info("playlist")
        history_info = self._build_selection_info("history")
        has_current_source = self._source_payload_from_context(self._current_track_context()) is not None
        has_playlist = self._selected_playlist_id is not None
        playlist_entry_count = self._playlist_entries_model.entry_count()
        queue_selection_count = int(queue_info.get("count") or 0)

        queue_states = self._compute_action_state("queue", queue_info, has_current_source=has_current_source)
        playlist_states = self._compute_action_state(
            "playlist",
            playlist_info,
            has_current_source=has_current_source,
            has_playlist=has_playlist,
            playlist_entry_count=playlist_entry_count,
            playlist_any_ready=self._playlist_has_any_ready(),
            queue_selection_count=queue_selection_count,
        )
        history_states = self._compute_action_state(
            "history",
            history_info,
            has_current_source=has_current_source,
        )

        self._apply_action_state_to_button(self.add_queue_to_playlist_btn, queue_states["queue_add_to_playlist"])

        self._apply_action_state_to_button(self.rename_playlist_btn, playlist_states["playlist_rename"])
        self._apply_action_state_to_button(self.delete_playlist_btn, playlist_states["playlist_delete"])
        self._apply_action_state_to_button(self.load_pl_btn, playlist_states["playlist_load_to_queue"])
        self._apply_action_state_to_button(self.add_playlist_to_queue_btn, playlist_states["playlist_add_to_queue"])
        self._apply_action_state_to_button(self.play_playlist_btn, playlist_states["playlist_play_all"])
        self._apply_action_state_to_button(self.play_playlist_selected_btn, playlist_states["playlist_play_selected"])
        self._apply_action_state_to_button(
            self.add_queue_selected_to_playlist_btn,
            playlist_states["playlist_add_queue_selected"],
        )
        self._apply_action_state_to_button(
            self.refresh_playlist_entries_btn,
            playlist_states["playlist_refresh_entries"],
        )
        self._apply_action_state_to_button(
            self.remove_playlist_entries_btn,
            playlist_states["playlist_remove_selected"],
        )
        self._apply_action_state_to_button(self.playlist_move_up_btn, playlist_states["playlist_move_up"])
        self._apply_action_state_to_button(self.playlist_move_down_btn, playlist_states["playlist_move_down"])

        self._apply_action_state_to_button(
            self.play_history_selected_btn,
            history_states["history_play_selected"],
        )
        self._apply_action_state_to_button(
            self.add_history_to_queue_btn,
            history_states["history_add_to_queue"],
        )
        self._apply_action_state_to_button(self.refresh_history_btn, history_states["history_refresh"])

        active_idx = self.tab_widget.currentIndex()
        if active_idx == 0:
            go_state = queue_states["go_to_source"]
        elif active_idx == 1:
            go_state = playlist_states["go_to_source"]
        else:
            go_state = history_states["go_to_source"]
        self.goto_source_btn.setEnabled(bool(go_state.get("enabled")))
        reason = str(go_state.get("reason") or "")
        if reason and not bool(go_state.get("enabled")):
            self.goto_source_btn.setToolTip(reason)
        elif bool(go_state.get("enabled")):
            self.goto_source_btn.setToolTip("Navigate to the source row in the table")

    def _on_queue_selection_changed(self, *_args) -> None:
        selected_rows = sorted({idx.row() for idx in self.queue_table.selectionModel().selectedRows()})
        self._selected_queue_row_count = len(selected_rows)
        if len(selected_rows) != 1:
            self._selected_source_payload = None
            self._apply_action_policy()
            return
        self._selected_source_payload = self._source_payload_from_context(
            self._queue_row_context(selected_rows[0])
        )
        self._apply_action_policy()

    def _source_payload_from_playlist_selection(self) -> Optional[Dict[str, Any]]:
        rows = self._selected_playlist_entry_rows()
        if len(rows) != 1:
            return None
        payload = self._playlist_entries_model.row_payload(rows[0])
        if not payload:
            return None
        return self._source_payload_from_context(payload)

    def _source_payload_from_history_selection(self) -> Optional[Dict[str, Any]]:
        rows = self._selected_history_rows()
        if len(rows) != 1:
            return None
        payload = self._history_model.row_payload(rows[0])
        if not payload:
            return None
        return self._source_payload_from_context(payload)

    def _active_tab_source_payload(self) -> Tuple[Optional[Dict[str, Any]], bool]:
        idx = self.tab_widget.currentIndex()
        if idx == 0:
            if self._selected_queue_row_count > 1:
                return (None, True)
            if self._selected_queue_row_count == 1:
                return (self._selected_source_payload, False)
            return (self._source_payload_from_context(self._current_track_context()), False)
        if idx == 1:
            rows = self._selected_playlist_entry_rows()
            if len(rows) > 1:
                return (None, True)
            if len(rows) == 1:
                return (self._source_payload_from_playlist_selection(), False)
            return (self._source_payload_from_context(self._current_track_context()), False)
        if idx == 2:
            rows = self._selected_history_rows()
            if len(rows) > 1:
                return (None, True)
            if len(rows) == 1:
                return (self._source_payload_from_history_selection(), False)
            return (self._source_payload_from_context(self._current_track_context()), False)
        return (self._source_payload_from_context(self._current_track_context()), False)

    def _update_goto_source_state(self) -> None:
        self._apply_action_policy()

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
        """Persist play stats/history and refresh DB-backed History tab."""
        data = payload if isinstance(payload, dict) else {}
        self._sync_play_stats_to_db(data)
        QTimer.singleShot(0, self._refresh_history_entries)

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
        payload, blocked_multi = self._active_tab_source_payload()
        if blocked_multi:
            self._show_status_message("Select exactly one row to open source.")
            return
        if payload is None:
            self._show_status_message("Source link is unavailable for current selection.")
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
        source_payload = self._source_payload_from_context(first_ctx) if len(rows) == 1 else None
        queue_info = self._build_selection_info("queue")
        queue_states = self._compute_action_state(
            "queue",
            queue_info,
            has_current_source=self._source_payload_from_context(self._current_track_context()) is not None,
        )

        translate_items = self._build_translate_items(rows)
        audio_items = self._build_audio_generation_items(rows)
        pronunciation_items = self._build_pronunciation_selected_items(rows)

        menu = QMenu(self)

        play_act = menu.addAction("Play from here")
        self._apply_action_state_to_menu_action(play_act, queue_states["queue_play_single"])

        go_to_source_act = menu.addAction("Go to Source")
        self._apply_action_state_to_menu_action(go_to_source_act, queue_states["go_to_source"])

        remove_act = menu.addAction("Remove from Queue")
        menu.addSeparator()

        translate_act = menu.addAction(f"Translate Selected ({len(rows)})...")
        translate_act.setEnabled(len(translate_items) > 0)

        niqqud_act = menu.addAction(f"Niqqudize Selected ({len(rows)})...")
        niqqud_act.setEnabled(len(pronunciation_items) > 0)

        regen_audio_act = menu.addAction(f"Regenerate Audio Selected ({len(rows)})...")
        regen_audio_act.setEnabled(len(audio_items) > 0)
        add_to_playlist_act = menu.addAction(f"Add selected to Playlist ({len(rows)})...")
        self._apply_action_state_to_menu_action(add_to_playlist_act, queue_states["queue_add_to_playlist"])

        edit_translation_act = menu.addAction("Edit Translation...")
        self._apply_action_state_to_menu_action(edit_translation_act, queue_states["queue_edit_translation"])
        clear_translation_act = menu.addAction(f"Clear Translation ({len(rows)})...")
        self._apply_action_state_to_menu_action(clear_translation_act, queue_states["queue_clear_translation"])

        edit_pron_act = menu.addAction("Mispronounced -> Edit Pronunciation...")
        self._apply_action_state_to_menu_action(edit_pron_act, queue_states["queue_edit_pronunciation"])

        edit_sentence_act = menu.addAction("Edit Sentence Niqqud...")
        self._apply_action_state_to_menu_action(edit_sentence_act, queue_states["queue_edit_sentence_niqqud"])

        menu.addSeparator()
        copy_heb_act = menu.addAction("Copy Hebrew")
        copy_niqqud_act = menu.addAction("Copy Niqqud")
        copy_transl_act = menu.addAction("Copy Translation")

        action = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == play_act and rows:
            self._play_from_row(rows[0])
        elif action == go_to_source_act:
            if source_payload is not None:
                self.go_to_source_requested.emit(source_payload)
            else:
                self._show_status_message(str(queue_states["go_to_source"].get("reason") or "Source link unavailable."))
        elif action == remove_act:
            for r in reversed(rows):
                self.player.remove_queue_index(r)
        elif action == translate_act:
            self._on_queue_translate_selected(rows)
        elif action == niqqud_act:
            self._on_queue_niqqudize_selected(rows)
        elif action == regen_audio_act:
            self._on_queue_regenerate_audio_selected(rows)
        elif action == add_to_playlist_act:
            self._on_add_queue_selected_to_playlist_clicked()
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

    def _on_playlist_context_menu(self, pos) -> None:
        rows = self._selected_playlist_entry_rows()
        if not rows:
            return
        source_payload = self._source_payload_from_playlist_selection() if len(rows) == 1 else None
        playlist_info = self._build_selection_info("playlist")
        playlist_states = self._compute_action_state(
            "playlist",
            playlist_info,
            has_current_source=self._source_payload_from_context(self._current_track_context()) is not None,
            has_playlist=self._selected_playlist_id is not None,
            playlist_entry_count=self._playlist_entries_model.entry_count(),
            playlist_any_ready=self._playlist_has_any_ready(),
            queue_selection_count=len(self._selected_queue_rows()),
        )
        menu = QMenu(self)
        play_selected_act = menu.addAction("Play selected")
        self._apply_action_state_to_menu_action(play_selected_act, playlist_states["playlist_play_selected"])
        go_to_source_act = menu.addAction("Go to Source")
        self._apply_action_state_to_menu_action(go_to_source_act, playlist_states["go_to_source"])
        add_to_queue_act = menu.addAction("Add selected to Queue")
        self._apply_action_state_to_menu_action(add_to_queue_act, playlist_states["playlist_remove_selected"])
        remove_act = menu.addAction("Remove selected from Playlist")
        self._apply_action_state_to_menu_action(remove_act, playlist_states["playlist_remove_selected"])
        move_up_act = menu.addAction("Move up")
        self._apply_action_state_to_menu_action(move_up_act, playlist_states["playlist_move_up"])
        move_down_act = menu.addAction("Move down")
        self._apply_action_state_to_menu_action(move_down_act, playlist_states["playlist_move_down"])
        copy_hebrew_act = menu.addAction("Copy Hebrew")
        copy_niqqud_act = menu.addAction("Copy Niqqud")
        copy_translation_act = menu.addAction("Copy Translation")

        action = menu.exec(self.playlist_entries_table.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action == play_selected_act:
            self._on_play_playlist_selected_clicked()
        elif action == go_to_source_act:
            if source_payload is not None:
                self.go_to_source_requested.emit(source_payload)
            else:
                self._show_status_message(
                    str(playlist_states["go_to_source"].get("reason") or "Source link unavailable.")
                )
        elif action == add_to_queue_act:
            self._on_add_playlist_to_queue_clicked(rows)
        elif action == remove_act:
            self._on_remove_playlist_entries_clicked()
        elif action == move_up_act:
            self._on_move_playlist_entry(-1)
        elif action == move_down_act:
            self._on_move_playlist_entry(1)
        elif action == copy_hebrew_act:
            self._copy_playlist_cell(rows[0], _PL_COL_HEBREW)
        elif action == copy_niqqud_act:
            self._copy_playlist_cell(rows[0], _PL_COL_NIQQUD)
        elif action == copy_translation_act:
            self._copy_playlist_cell(rows[0], _PL_COL_TRANSLATION)

    def _on_history_context_menu(self, pos) -> None:
        rows = self._selected_history_rows()
        if not rows:
            return
        source_payload = self._source_payload_from_history_selection() if len(rows) == 1 else None
        history_info = self._build_selection_info("history")
        history_states = self._compute_action_state(
            "history",
            history_info,
            has_current_source=self._source_payload_from_context(self._current_track_context()) is not None,
        )
        menu = QMenu(self)
        play_selected_act = menu.addAction("Play selected")
        self._apply_action_state_to_menu_action(play_selected_act, history_states["history_play_selected"])
        go_to_source_act = menu.addAction("Go to Source")
        self._apply_action_state_to_menu_action(go_to_source_act, history_states["go_to_source"])
        add_to_queue_act = menu.addAction("Add selected to Queue")
        self._apply_action_state_to_menu_action(add_to_queue_act, history_states["history_add_to_queue"])
        copy_hebrew_act = menu.addAction("Copy Hebrew")
        copy_niqqud_act = menu.addAction("Copy Niqqud")
        copy_translation_act = menu.addAction("Copy Translation")
        action = menu.exec(self.history_table.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action == play_selected_act:
            self._on_play_history_selected_clicked()
        elif action == go_to_source_act:
            if source_payload is not None:
                self.go_to_source_requested.emit(source_payload)
            else:
                self._show_status_message(str(history_states["go_to_source"].get("reason") or "Source link unavailable."))
        elif action == add_to_queue_act:
            self._on_add_history_to_queue_clicked(rows)
        elif action == copy_hebrew_act:
            self._copy_history_cell(rows[0], _HIST_COL_HEBREW)
        elif action == copy_niqqud_act:
            self._copy_history_cell(rows[0], _HIST_COL_NIQQUD)
        elif action == copy_translation_act:
            self._copy_history_cell(rows[0], _HIST_COL_TRANSLATION)

    def _on_playlist_double_clicked(self, index: QModelIndex) -> None:
        self._play_playlist_rows([index.row()])

    def _on_playlist_table_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != _PL_COL_STATUS:
            return
        payload = self._playlist_entries_model.row_payload(index.row()) or {}
        status = self._payload_row_status(payload)
        if status != "ready":
            self._show_play_unavailable(status)

    def _on_playlist_play_cell_clicked(self, index: QModelIndex) -> None:
        self._play_playlist_rows([index.row()])

    def _on_history_table_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != _HIST_COL_STATUS:
            return
        payload = self._history_model.row_payload(index.row()) or {}
        status = self._payload_row_status(payload)
        if status != "ready":
            self._show_play_unavailable(status)

    def _copy_playlist_cell(self, row: int, col: int) -> None:
        try:
            from PyQt6.QtWidgets import QApplication

            idx = self._playlist_entries_model.index(row, col)
            text = str(self._playlist_entries_model.data(idx, Qt.ItemDataRole.DisplayRole) or "")
            QApplication.clipboard().setText(text)
        except Exception:
            pass

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
                        svc.update_snapshot(session, item_id, is_stale=False)
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
                        source_text=src_text or None,
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
                with_retry_on_locked(
                    _flush_and_propagate,
                    max_retries=4,
                    rollback_callback=session.rollback,
                )
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

    def _on_queue_table_clicked(self, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != _COL_STATUS:
            return
        status = self._queue_row_status(index.row())
        if status != "ready":
            self._show_play_unavailable(status)

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
                self._show_play_unavailable("stale")
                return

        track = self.player._tracks[row]  # noqa: SLF001
        path_ok = str(track.path) not in ("", ".") and Path(track.path).exists()
        if not path_ok:
            self._refresh_audio_paths_for_rows([row], clear_stale_if_ready=True)
            track = self.player._tracks[row]  # noqa: SLF001
            path_ok = str(track.path) not in ("", ".") and Path(track.path).exists()
        if not path_ok:
            self._show_play_unavailable(self._queue_row_status(row))
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
        self._apply_action_policy()

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
        from app.infra.sa_models import (
            DictProject as _Project,
            DocumentSentence as _DS,
            SourceCorpus as _SC,
            SourceDocument as _SD,
        )

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
        doc_project_names: Dict[int, str] = {}
        try:
            unique_dids = list(set(sid_to_did.values()))
            if unique_dids:
                for did, fname in session.execute(
                    _sel(_SD.doc_id, _SD.file_name).where(_SD.doc_id.in_(unique_dids))
                ).all():
                    if fname:
                        doc_names[did] = fname
                for did, pname in session.execute(
                    _sel(_SD.doc_id, _Project.name)
                    .join(_SC, _SD.corpus_id == _SC.corpus_id)
                    .join(_Project, _SC.project_id == _Project.project_id)
                    .where(_SD.doc_id.in_(unique_dids))
                ).all():
                    if pname:
                        doc_project_names[int(did)] = str(pname)
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
            project_name = doc_project_names.get(did, "") if did else ""
            if source and t.context.get("snapshot_source_label") != source:
                t.context["snapshot_source_label"] = source
                changed = True
            if source and t.context.get("snapshot_document_name") != source:
                t.context["snapshot_document_name"] = source
                changed = True
            if project_name and t.context.get("snapshot_project_name") != project_name:
                t.context["snapshot_project_name"] = project_name
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
        from app.infra.sa_models import DictProject as _Project, Lemma as _Lemma

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
        project_name_by_id: Dict[int, str] = {}
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
                project_rows = session.execute(
                    _sel(_Project.project_id, _Project.name).where(_Project.project_id.in_(project_ids))
                ).all()
                project_name_by_id = {int(pid): str(name or "") for pid, name in project_rows}
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
            if (t.context.get("snapshot_document_name") or "") != "":
                t.context["snapshot_document_name"] = ""
                changed = True
            project_name = project_name_by_id.get(pid, "") if pid is not None else ""
            if project_name and t.context.get("snapshot_project_name") != project_name:
                t.context["snapshot_project_name"] = project_name
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
        from app.infra.sa_models import DictProject as _Project, TermCluster as _TermCluster

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
        project_name_by_id: Dict[int, str] = {}
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
                project_rows = session.execute(
                    _sel(_Project.project_id, _Project.name).where(_Project.project_id.in_(project_ids))
                ).all()
                project_name_by_id = {int(pid): str(name or "") for pid, name in project_rows}
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
            if (t.context.get("snapshot_document_name") or "") != "":
                t.context["snapshot_document_name"] = ""
                changed = True
            project_name = project_name_by_id.get(pid, "") if pid is not None else ""
            if project_name and t.context.get("snapshot_project_name") != project_name:
                t.context["snapshot_project_name"] = project_name
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

