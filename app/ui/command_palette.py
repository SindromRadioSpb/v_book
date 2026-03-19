"""
Command Palette - Keyboard-first action launcher with fuzzy search.

Provides a Ctrl+P command palette for quick access to all application actions
with lightweight fuzzy search (no external dependencies).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

logger = logging.getLogger(__name__)


@dataclass
class ActionSpec:
    """
    Specification for a registerable action.

    Attributes:
        action_id: Unique identifier (e.g., "import.dictionary")
        title: Human-readable title (e.g., "Import Dictionary")
        keywords: Search keywords (e.g., ["import", "dict", "csv"])
        shortcut: Keyboard shortcut (e.g., "Ctrl+Shift+I", "" if none)
        callback: Function to execute when action is triggered
        enabled_check: Optional function to check if action is enabled (None = always enabled)
        category: Category for grouping (e.g., "Tools", "Premium", "Navigate")
    """

    action_id: str
    title: str
    keywords: list[str]
    shortcut: str
    callback: Callable
    enabled_check: Callable[[], bool] | None = None
    category: str = "General"
    _search_text: str = field(init=False, repr=False)

    def __post_init__(self):
        """Pre-compute search text for fast matching."""
        parts = [
            self.title.lower(),
            " ".join(self.keywords).lower(),
            self.shortcut.lower(),
            self.category.lower(),
        ]
        self._search_text = " ".join(parts)

    def is_enabled(self) -> bool:
        """Check if action is currently enabled."""
        if self.enabled_check is None:
            return True
        try:
            return self.enabled_check()
        except Exception as e:
            logger.error(f"Error checking enabled state for '{self.action_id}': {e}")
            return False


class ActionsRegistry:
    """
    Singleton registry for all application actions.

    Manages action registration, search, and execution.
    """

    _instance: Optional["ActionsRegistry"] = None

    def __init__(self):
        self._actions: dict[str, ActionSpec] = {}

    @classmethod
    def get_instance(cls) -> "ActionsRegistry":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton instance (for tests)."""
        cls._instance = None

    def register(self, spec: ActionSpec):
        """Register an action."""
        self._actions[spec.action_id] = spec
        logger.debug(f"Registered action: {spec.action_id}")

    def unregister(self, action_id: str):
        """Unregister an action."""
        if action_id in self._actions:
            del self._actions[action_id]
            logger.debug(f"Unregistered action: {action_id}")

    def get_all(self) -> list[ActionSpec]:
        """Get all registered actions."""
        return list(self._actions.values())

    def get_enabled(self) -> list[ActionSpec]:
        """Get all currently enabled actions."""
        return [spec for spec in self._actions.values() if spec.is_enabled()]

    def execute(self, action_id: str) -> bool:
        """
        Execute an action by ID.

        Returns:
            True if executed successfully, False if action not found or disabled
        """
        spec = self._actions.get(action_id)
        if spec is None:
            logger.warning(f"Action not found: {action_id}")
            return False

        if not spec.is_enabled():
            logger.warning(f"Action disabled: {action_id}")
            return False

        try:
            spec.callback()
            logger.info(f"Executed action: {action_id}")
            return True
        except Exception as e:
            logger.error(f"Error executing action '{action_id}': {e}")
            return False

    def search(self, query: str) -> list[tuple[ActionSpec, int]]:
        """
        Search actions with lightweight scoring.

        Args:
            query: Search query string

        Returns:
            List of (ActionSpec, score) tuples, sorted by score descending
        """
        if not query:
            # Empty query: return all enabled actions
            return [(spec, 0) for spec in self.get_enabled()]

        query_lower = query.lower()
        query_words = query_lower.split()

        results = []
        for spec in self.get_enabled():
            score = self._score_action(spec, query_lower, query_words)
            if score > 0:
                results.append((spec, score))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _score_action(self, spec: ActionSpec, query_lower: str, query_words: list[str]) -> int:
        """
        Score an action against a query.

        Scoring:
        - Title exact match: +100
        - Title starts with query: +50
        - Title contains query: +30
        - Each keyword contains query word: +10
        - All query words found somewhere: +20
        - Each query word found: +5
        """
        score = 0
        title_lower = spec.title.lower()
        search_text = spec._search_text

        # Title matching (highest priority)
        if title_lower == query_lower:
            score += 100
        elif title_lower.startswith(query_lower):
            score += 50
        elif query_lower in title_lower:
            score += 30

        # Keyword matching
        for keyword in spec.keywords:
            keyword_lower = keyword.lower()
            for word in query_words:
                if word in keyword_lower:
                    score += 10

        # Multi-word matching
        words_found = sum(1 for word in query_words if word in search_text)
        if words_found == len(query_words):
            score += 20  # All words found
        score += words_found * 5  # Each word found

        return score


class CommandPaletteDialog(QDialog):
    """
    Frameless command palette dialog.

    Positioned at top-center of parent window, provides fuzzy search over actions.
    """

    action_selected = pyqtSignal(str)  # Emits action_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setMinimumWidth(600)
        self.setMaximumHeight(400)

        self.registry = ActionsRegistry.get_instance()
        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search actions... (type to filter, ↑↓ to navigate, Enter to execute)"
        )
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        # Results list
        self.results_list = QListWidget()
        self.results_list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.results_list)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        # Initial search (show all)
        self._perform_search("")

    def showEvent(self, event):
        """Position dialog at top-center of parent when shown."""
        super().showEvent(event)

        # Position at top-center of parent
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.x() + (parent_rect.width() - self.width()) // 2
            y = parent_rect.y() + 50  # 50px from top
            self.move(x, y)

        # Focus search input
        self.search_input.setFocus()
        self.search_input.selectAll()

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard navigation."""
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._execute_selected()
        elif event.key() == Qt.Key.Key_Up:
            current_row = self.results_list.currentRow()
            if current_row > 0:
                self.results_list.setCurrentRow(current_row - 1)
        elif event.key() == Qt.Key.Key_Down:
            current_row = self.results_list.currentRow()
            if current_row < self.results_list.count() - 1:
                self.results_list.setCurrentRow(current_row + 1)
        else:
            super().keyPressEvent(event)

    def _on_search_changed(self, query: str):
        """Handle search query changes."""
        self._perform_search(query)

    def _perform_search(self, query: str):
        """Perform search and update results list."""
        results = self.registry.search(query)

        self.results_list.clear()

        if not results:
            self.status_label.setText("No actions found")
            return

        for spec, score in results:
            # Format: "Title (Shortcut) - Category"
            shortcut_part = f" ({spec.shortcut})" if spec.shortcut else ""
            item_text = f"{spec.title}{shortcut_part} — {spec.category}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, spec.action_id)
            self.results_list.addItem(item)

        # Auto-select first result
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)

        self.status_label.setText(f"{len(results)} action(s)")

    def _on_item_activated(self, item: QListWidgetItem):
        """Handle item activation (double-click or Enter)."""
        action_id = item.data(Qt.ItemDataRole.UserRole)
        self.action_selected.emit(action_id)
        self.accept()

    def _execute_selected(self):
        """Execute currently selected action."""
        current_item = self.results_list.currentItem()
        if current_item:
            action_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.action_selected.emit(action_id)
            self.accept()
