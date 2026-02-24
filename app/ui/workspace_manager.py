"""
WorkspaceManager - premium workspace layout with collapsible sidebar.

Provides:
- Primary navigation sidebar (Projects / TM / User Dictionaries / Audio Player)
- Current project context card with deep links
- Project quick search + recent projects list
- Main content stack (QStackedWidget)
- Layout persistence (splitter + sidebar visibility + active workspace)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class SidebarWidget(QFrame):
    """Collapsible sidebar with primary navigation and workspace context."""

    action_triggered = pyqtSignal(str)
    section_state_changed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(210)
        self.setMaximumWidth(360)

        self._project_catalog: List[Dict[str, Any]] = []
        self._recent_project_ids: List[int] = []
        self._current_project_id: Optional[int] = None
        self._active_workspace: str = "workspace.projects"
        self._badge_values: Dict[str, Optional[int]] = {
            "workspace.audio": None,
            "workspace.tm": None,
            "workspace.user_dictionaries": None,
        }

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(self._apply_project_filter)

        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll_area, 1)

        content = QWidget()
        self.scroll_area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel("<b>Workspace</b>")
        layout.addWidget(header)

        nav_label = QLabel("<i>Primary Navigation</i>")
        nav_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(nav_label)

        self.projects_btn = self._make_nav_button(
            text="Projects",
            tooltip="Open Projects dashboard",
            action_id="workspace.projects",
        )
        layout.addWidget(self.projects_btn)

        # Backward-compatible alias for older tests/callers.
        self.dashboard_btn = self.projects_btn

        self.tm_btn = self._make_nav_button(
            text="Translation Management",
            tooltip="Open Translation Management (Ctrl+Shift+T)",
            action_id="workspace.tm",
        )
        layout.addWidget(self.tm_btn)

        self.user_dict_btn = self._make_nav_button(
            text="User Dictionaries",
            tooltip="Open User Dictionaries (Ctrl+Shift+U)",
            action_id="workspace.user_dictionaries",
        )
        layout.addWidget(self.user_dict_btn)

        self.audio_btn = self._make_nav_button(
            text="Audio Player",
            tooltip="Open Audio Player panel (Ctrl+Alt+L)",
            action_id="workspace.audio",
        )
        layout.addWidget(self.audio_btn)

        self._nav_buttons = {
            "workspace.projects": self.projects_btn,
            "workspace.tm": self.tm_btn,
            "workspace.user_dictionaries": self.user_dict_btn,
            "workspace.audio": self.audio_btn,
        }
        self.set_active_workspace("workspace.projects")

        layout.addSpacing(8)

        project_label = QLabel("<i>Current Project</i>")
        project_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(project_label)

        self.current_project_name_label = QLabel("Project: none")
        self.current_project_name_label.setWordWrap(True)
        layout.addWidget(self.current_project_name_label)

        self.current_project_scope_label = QLabel("Scope: All projects")
        self.current_project_scope_label.setStyleSheet("color: #666; font-size: 11px;")
        self.current_project_scope_label.setWordWrap(True)
        layout.addWidget(self.current_project_scope_label)

        self.open_current_project_btn = QPushButton("Open Project")
        self.open_current_project_btn.clicked.connect(
            lambda: self.action_triggered.emit("workspace.current_project.open")
        )
        layout.addWidget(self.open_current_project_btn)

        links_row_1 = QHBoxLayout()
        self.documents_link_btn = self._make_project_link_button("Documents", "documents")
        links_row_1.addWidget(self.documents_link_btn)
        self.sentences_link_btn = self._make_project_link_button("Sentences", "sentences")
        links_row_1.addWidget(self.sentences_link_btn)
        self.dictionary_link_btn = self._make_project_link_button("Dictionary", "dictionary")
        links_row_1.addWidget(self.dictionary_link_btn)
        layout.addLayout(links_row_1)

        links_row_2 = QHBoxLayout()
        self.terms_link_btn = self._make_project_link_button("Terms", "terms")
        links_row_2.addWidget(self.terms_link_btn)
        self.term_cards_link_btn = self._make_project_link_button("Term Cards", "term_cards")
        links_row_2.addWidget(self.term_cards_link_btn)
        self.export_link_btn = self._make_project_link_button("Export", "export")
        links_row_2.addWidget(self.export_link_btn)
        layout.addLayout(links_row_2)

        self._project_link_buttons = [
            self.documents_link_btn,
            self.sentences_link_btn,
            self.dictionary_link_btn,
            self.terms_link_btn,
            self.term_cards_link_btn,
            self.export_link_btn,
        ]

        layout.addSpacing(8)

        self.project_search_toggle_btn = QPushButton("Project Search [v]")
        self.project_search_toggle_btn.setCheckable(True)
        self.project_search_toggle_btn.setChecked(True)
        self.project_search_toggle_btn.clicked.connect(
            lambda: self._toggle_section("project_search", self.project_search_toggle_btn.isChecked())
        )
        layout.addWidget(self.project_search_toggle_btn)

        self.project_search_section = QWidget()
        project_search_layout = QVBoxLayout(self.project_search_section)
        project_search_layout.setContentsMargins(0, 0, 0, 0)
        project_search_layout.setSpacing(4)

        self.project_search_edit = QLineEdit()
        self.project_search_edit.setPlaceholderText("Type 2+ chars to search projects...")
        self.project_search_edit.textChanged.connect(lambda *_args: self._search_timer.start())
        self.project_search_edit.installEventFilter(self)
        project_search_layout.addWidget(self.project_search_edit)

        self.project_results_list = QListWidget()
        self.project_results_list.itemActivated.connect(self._on_project_result_activated)
        self.project_results_list.itemClicked.connect(self._on_project_result_clicked)
        project_search_layout.addWidget(self.project_results_list, 1)

        self.project_results_empty_label = QLabel("No projects found")
        self.project_results_empty_label.setStyleSheet("color: #666; font-size: 11px;")
        self.project_results_empty_label.setVisible(False)
        project_search_layout.addWidget(self.project_results_empty_label)
        layout.addWidget(self.project_search_section)

        layout.addSpacing(8)

        self.tools_toggle_btn = QPushButton("Tools [v]")
        self.tools_toggle_btn.setCheckable(True)
        self.tools_toggle_btn.setChecked(True)
        self.tools_toggle_btn.clicked.connect(
            lambda: self._toggle_section("tools", self.tools_toggle_btn.isChecked())
        )
        layout.addWidget(self.tools_toggle_btn)

        self.tools_section = QWidget()
        tools_layout = QVBoxLayout(self.tools_section)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(4)

        self.import_btn = QPushButton("Import Dictionary")
        self.import_btn.setToolTip("Import dictionary from CSV (Ctrl+Shift+I)")
        self.import_btn.clicked.connect(lambda: self.action_triggered.emit("tools.import_dictionary"))
        tools_layout.addWidget(self.import_btn)

        self.coverage_btn = QPushButton("QA / Coverage")
        self.coverage_btn.setToolTip("Open QA/Coverage (Ctrl+Shift+C)")
        self.coverage_btn.clicked.connect(lambda: self.action_triggered.emit("premium.coverage"))
        tools_layout.addWidget(self.coverage_btn)

        self.verify_btn = QPushButton("P1 Verification")
        self.verify_btn.setToolTip("Run P1 verification suite (Ctrl+Shift+V)")
        self.verify_btn.clicked.connect(lambda: self.action_triggered.emit("tools.verification"))
        tools_layout.addWidget(self.verify_btn)

        self.refresh_badges_btn = QPushButton("Refresh Counters")
        self.refresh_badges_btn.setToolTip("Refresh workspace counters")
        self.refresh_badges_btn.clicked.connect(lambda: self.action_triggered.emit("workspace.refresh_badges"))
        tools_layout.addWidget(self.refresh_badges_btn)
        layout.addWidget(self.tools_section)

        layout.addStretch(1)

        self.set_current_project(None, "", "All projects")
        self._apply_project_filter()
        self._configure_tab_order(content)

        logger.debug("Sidebar initialized")

    def _configure_tab_order(self, content: QWidget) -> None:
        QWidget.setTabOrder(self.projects_btn, self.tm_btn)
        QWidget.setTabOrder(self.tm_btn, self.user_dict_btn)
        QWidget.setTabOrder(self.user_dict_btn, self.audio_btn)
        QWidget.setTabOrder(self.audio_btn, self.open_current_project_btn)
        QWidget.setTabOrder(self.open_current_project_btn, self.documents_link_btn)
        QWidget.setTabOrder(self.documents_link_btn, self.sentences_link_btn)
        QWidget.setTabOrder(self.sentences_link_btn, self.dictionary_link_btn)
        QWidget.setTabOrder(self.dictionary_link_btn, self.terms_link_btn)
        QWidget.setTabOrder(self.terms_link_btn, self.term_cards_link_btn)
        QWidget.setTabOrder(self.term_cards_link_btn, self.export_link_btn)
        QWidget.setTabOrder(self.export_link_btn, self.project_search_toggle_btn)
        QWidget.setTabOrder(self.project_search_toggle_btn, self.project_search_edit)
        QWidget.setTabOrder(self.project_search_edit, self.project_results_list)
        QWidget.setTabOrder(self.project_results_list, self.tools_toggle_btn)
        QWidget.setTabOrder(self.tools_toggle_btn, self.import_btn)
        QWidget.setTabOrder(self.import_btn, self.coverage_btn)
        QWidget.setTabOrder(self.coverage_btn, self.verify_btn)
        QWidget.setTabOrder(self.verify_btn, self.refresh_badges_btn)
        QWidget.setTabOrder(self.refresh_badges_btn, self.projects_btn)

    def _toggle_section(self, section_key: str, expanded: bool) -> None:
        if section_key == "project_search":
            self.project_search_section.setVisible(bool(expanded))
            self.project_search_toggle_btn.setText(
                "Project Search [v]" if expanded else "Project Search [>]"
            )
        elif section_key == "tools":
            self.tools_section.setVisible(bool(expanded))
            self.tools_toggle_btn.setText("Tools [v]" if expanded else "Tools [>]")
        self.section_state_changed.emit(self.get_sections_state())

    def get_sections_state(self) -> Dict[str, bool]:
        return {
            "project_search_expanded": self.project_search_toggle_btn.isChecked(),
            "tools_expanded": self.tools_toggle_btn.isChecked(),
        }

    def set_sections_state(self, state: Dict[str, bool]) -> None:
        search_expanded = bool(state.get("project_search_expanded", True))
        tools_expanded = bool(state.get("tools_expanded", True))

        self.project_search_toggle_btn.blockSignals(True)
        self.project_search_toggle_btn.setChecked(search_expanded)
        self.project_search_toggle_btn.blockSignals(False)
        self._toggle_section("project_search", search_expanded)

        self.tools_toggle_btn.blockSignals(True)
        self.tools_toggle_btn.setChecked(tools_expanded)
        self.tools_toggle_btn.blockSignals(False)
        self._toggle_section("tools", tools_expanded)

    def _make_nav_button(self, *, text: str, tooltip: str, action_id: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self.action_triggered.emit(action_id))
        return btn

    def _make_project_link_button(self, text: str, tab_key: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setToolTip(f"Open {text} tab in current project")
        btn.clicked.connect(lambda: self.action_triggered.emit(f"workspace.project_tab.{tab_key}"))
        return btn

    @property
    def active_workspace(self) -> str:
        return self._active_workspace

    def set_active_workspace(self, workspace_key: str) -> None:
        if workspace_key == "workspace.ud":
            workspace_key = "workspace.user_dictionaries"
        if workspace_key not in self._nav_buttons:
            workspace_key = "workspace.projects"
        self._active_workspace = workspace_key
        for key, btn in self._nav_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(key == workspace_key)
            btn.blockSignals(False)

    def update_badges(
        self,
        *,
        queue_count: Optional[int] = None,
        ud_due_count: Optional[int] = None,
        tm_filtered_count: Optional[int] = None,
    ) -> None:
        if queue_count is not None:
            qv = int(queue_count)
            self._badge_values["workspace.audio"] = qv if qv < 0 else max(0, qv)
        if ud_due_count is not None:
            uv = int(ud_due_count)
            self._badge_values["workspace.user_dictionaries"] = uv if uv < 0 else max(0, uv)
        if tm_filtered_count is not None:
            tv = int(tm_filtered_count)
            self._badge_values["workspace.tm"] = tv if tv < 0 else max(0, tv)

        self.audio_btn.setText(self._with_badge("Audio Player", self._badge_values["workspace.audio"]))
        self.tm_btn.setText(
            self._with_badge("Translation Management", self._badge_values["workspace.tm"])
        )
        self.user_dict_btn.setText(
            self._with_badge("User Dictionaries", self._badge_values["workspace.user_dictionaries"])
        )

    @staticmethod
    def _with_badge(base: str, value: Optional[int]) -> str:
        if value is None:
            return base
        if int(value) < 0:
            return f"{base} (!)"
        return f"{base} ({value})"

    def set_current_project(
        self,
        project_id: Optional[int],
        project_name: str,
        scope_text: str = "Current Project",
    ) -> None:
        self._current_project_id = int(project_id) if project_id is not None else None

        if self._current_project_id is None:
            self.current_project_name_label.setText("Project: none")
            self.current_project_scope_label.setText(f"Scope: {scope_text}")
            self.open_current_project_btn.setText("Open Project...")
            self.open_current_project_btn.setEnabled(True)
            for btn in self._project_link_buttons:
                btn.setEnabled(False)
            return

        name = project_name.strip() or f"Project {self._current_project_id}"
        self.current_project_name_label.setText(f"Project: {name} (#{self._current_project_id})")
        self.current_project_scope_label.setText(f"Scope: {scope_text}")
        self.open_current_project_btn.setText(f"Open Project #{self._current_project_id}")
        self.open_current_project_btn.setEnabled(True)
        for btn in self._project_link_buttons:
            btn.setEnabled(True)

    def set_project_catalog(
        self,
        projects: Sequence[object],
        recent_ids: Optional[Iterable[int]] = None,
    ) -> None:
        normalized: List[Dict[str, Any]] = []
        for row in projects:
            project_id: Optional[int] = None
            name: str = ""
            if isinstance(row, dict):
                pid = row.get("project_id")
                pname = row.get("name")
            else:
                pid = getattr(row, "project_id", None)
                pname = getattr(row, "name", "")
            try:
                project_id = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                project_id = None
            if project_id is None:
                continue
            name = str(pname or "").strip() or f"Project {project_id}"
            normalized.append({"project_id": project_id, "name": name})

        normalized.sort(key=lambda item: item["name"].lower())
        self._project_catalog = normalized

        if recent_ids is not None:
            self.set_recent_project_ids(recent_ids)

        self._apply_project_filter()

    def set_recent_project_ids(self, recent_ids: Iterable[int]) -> None:
        seen: set[int] = set()
        ordered: List[int] = []
        for raw in recent_ids:
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                continue
            if pid in seen:
                continue
            seen.add(pid)
            ordered.append(pid)
        self._recent_project_ids = ordered[:12]
        if len(self.project_search_edit.text().strip()) < 2:
            self._apply_project_filter()

    def _on_project_result_clicked(self, item: QListWidgetItem) -> None:
        self.project_results_list.setCurrentItem(item)

    def _on_project_result_activated(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        try:
            project_id = int(pid)
        except (TypeError, ValueError):
            return
        self.action_triggered.emit(f"workspace.open_project:{project_id}")

    def _apply_project_filter(self) -> None:
        query = self.project_search_edit.text().strip()
        if len(query) < 2:
            rows = self._recent_rows()
            self._render_project_rows(rows, is_search=False)
            return
        rows = self._ranked_search_rows(query)
        self._render_project_rows(rows, is_search=True)

    def _recent_rows(self) -> List[Dict[str, Any]]:
        by_id = {int(row["project_id"]): row for row in self._project_catalog}
        rows: List[Dict[str, Any]] = []
        for pid in self._recent_project_ids:
            if pid in by_id:
                rows.append(by_id[pid])
        if not rows:
            rows = self._project_catalog[:8]
        return rows

    def _ranked_search_rows(self, query: str) -> List[Dict[str, Any]]:
        q = query.casefold()
        scored: List[tuple[int, str, Dict[str, Any]]] = []
        for row in self._project_catalog:
            name = str(row.get("name") or "")
            name_cf = name.casefold()
            if q not in name_cf:
                continue
            score = 0
            pid = int(row["project_id"])
            if pid in self._recent_project_ids:
                score += 400
            if name_cf == q:
                score += 300
            elif name_cf.startswith(q):
                score += 200
            else:
                score += 100
            scored.append((score, name_cf, row))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [row for _score, _name, row in scored[:20]]

    def _render_project_rows(self, rows: Sequence[Dict[str, Any]], *, is_search: bool) -> None:
        self.project_results_list.clear()

        for row in rows:
            pid = int(row["project_id"])
            name = str(row.get("name") or f"Project {pid}")
            text = f"{name}  [#{pid}]"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.project_results_list.addItem(item)

        has_rows = bool(rows)
        self.project_results_empty_label.setVisible(not has_rows)
        if not has_rows:
            self.project_results_empty_label.setText("No projects found" if is_search else "No recent projects")

        if has_rows:
            self.project_results_list.setCurrentRow(0)

    def eventFilter(self, watched: QObject, event: QEvent):  # type: ignore[override]
        if watched is self.project_search_edit and event.type() == QEvent.Type.KeyPress:
            key_event = event if isinstance(event, QKeyEvent) else None
            if key_event is None:
                return super().eventFilter(watched, event)

            key = key_event.key()
            if key == Qt.Key.Key_Down:
                if self.project_results_list.count() > 0:
                    row = max(0, self.project_results_list.currentRow())
                    self.project_results_list.setCurrentRow(min(row + 1, self.project_results_list.count() - 1))
                return True
            if key == Qt.Key.Key_Up:
                if self.project_results_list.count() > 0:
                    row = max(0, self.project_results_list.currentRow())
                    self.project_results_list.setCurrentRow(max(row - 1, 0))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.project_results_list.currentItem()
                if item is not None:
                    self._on_project_result_activated(item)
                    return True
            if key == Qt.Key.Key_Escape:
                if self.project_search_edit.text():
                    self.project_search_edit.clear()
                    return True
        return super().eventFilter(watched, event)


class WorkspaceManager(QWidget):
    """Premium workspace layout manager."""

    layout_changed = pyqtSignal()

    # v3: active workspace persisted in layout payload. Restore remains backward compatible.
    LAYOUT_SCHEMA_VERSION = 3

    def __init__(self):
        super().__init__()

        self.sidebar = SidebarWidget()
        self.stack = QStackedWidget()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)

        self.sidebar.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self.layout_changed.emit)

        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        logger.debug("WorkspaceManager initialized")

    def _on_splitter_moved(self):
        self._debounce_timer.start()

    def toggle_sidebar(self):
        if self.sidebar.isVisible():
            self.sidebar.hide()
            logger.debug("Sidebar hidden")
        else:
            self.sidebar.show()
            logger.debug("Sidebar shown")
        self.layout_changed.emit()

    def set_active_workspace(self, workspace_key: str) -> None:
        self.sidebar.set_active_workspace(workspace_key)
        self.layout_changed.emit()

    def save_layout(self) -> Dict[str, Any]:
        sizes = self.splitter.sizes()
        sidebar_width = int(sizes[0]) if sizes else 220
        return {
            "layout_schema_version": self.LAYOUT_SCHEMA_VERSION,
            "sidebar_visible": self.sidebar.isVisible(),
            "splitter_state": bytes(self.splitter.saveState()).hex(),
            "sidebar_width": sidebar_width,
            "active_workspace": self.sidebar.active_workspace,
        }

    def restore_layout(self, data: Dict[str, Any]) -> bool:
        try:
            version = int(data.get("layout_schema_version", 0))
            if version not in (1, 2, 3):
                logger.warning(
                    "Layout schema version mismatch: got %s, expected one of (1,2,3)",
                    version,
                )
                return False

            if "sidebar_visible" not in data or "splitter_state" not in data:
                logger.warning("Layout data missing required keys")
                return False

            if bool(data.get("sidebar_visible", False)):
                self.sidebar.show()
            else:
                self.sidebar.hide()

            splitter_state_hex = str(data.get("splitter_state") or "")
            if splitter_state_hex:
                splitter_state = bytes.fromhex(splitter_state_hex)
                if not self.splitter.restoreState(splitter_state):
                    logger.warning("Failed to restore splitter state")
                    return False

            # Optional width override for safer migration from old states.
            sidebar_width = data.get("sidebar_width")
            if sidebar_width is not None and self.sidebar.isVisible():
                try:
                    width = max(170, min(420, int(sidebar_width)))
                    total = max(sum(self.splitter.sizes()), width + 300)
                    self.splitter.setSizes([width, total - width])
                except (TypeError, ValueError):
                    pass

            active_workspace = str(data.get("active_workspace") or "workspace.projects")
            self.sidebar.set_active_workspace(active_workspace)

            logger.info("Layout restored successfully")
            return True
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Failed to restore layout: %s", e)
            return False

    def reset_to_default(self):
        self.sidebar.hide()
        self.splitter.setSizes([220, 980])
        self.sidebar.set_active_workspace("workspace.projects")
        logger.info("Layout reset to default")
