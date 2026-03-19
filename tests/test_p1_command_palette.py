"""
Tests for P1 Command Palette.

Tests ActionsRegistry, search scoring, execution, and performance.
"""

import time
import pytest
from unittest.mock import MagicMock

from PyQt6.QtCore import Qt

from app.ui.command_palette import ActionsRegistry, ActionSpec, CommandPaletteDialog


@pytest.fixture
def registry():
    """Create fresh registry for each test."""
    ActionsRegistry.reset_instance()
    reg = ActionsRegistry.get_instance()
    yield reg
    ActionsRegistry.reset_instance()


class TestActionsRegistry:
    """Test actions registry."""

    def test_singleton_pattern(self):
        """Test registry is singleton."""
        ActionsRegistry.reset_instance()
        reg1 = ActionsRegistry.get_instance()
        reg2 = ActionsRegistry.get_instance()
        assert reg1 is reg2

    def test_register_and_get_all(self, registry):
        """Test registering actions."""
        callback = MagicMock()
        spec = ActionSpec(
            action_id="test.action",
            title="Test Action",
            keywords=["test", "action"],
            shortcut="Ctrl+T",
            callback=callback,
            category="Test",
        )

        registry.register(spec)
        actions = registry.get_all()

        assert len(actions) == 1
        assert actions[0].action_id == "test.action"

    def test_unregister(self, registry):
        """Test unregistering actions."""
        callback = MagicMock()
        spec = ActionSpec(
            action_id="test.action",
            title="Test Action",
            keywords=["test"],
            shortcut="",
            callback=callback,
            category="Test",
        )

        registry.register(spec)
        assert len(registry.get_all()) == 1

        registry.unregister("test.action")
        assert len(registry.get_all()) == 0

    def test_get_enabled_excludes_disabled(self, registry):
        """Test get_enabled excludes disabled actions."""
        enabled_callback = MagicMock()
        disabled_callback = MagicMock()

        registry.register(
            ActionSpec(
                action_id="enabled",
                title="Enabled Action",
                keywords=["enabled"],
                shortcut="",
                callback=enabled_callback,
                enabled_check=lambda: True,
                category="Test",
            )
        )

        registry.register(
            ActionSpec(
                action_id="disabled",
                title="Disabled Action",
                keywords=["disabled"],
                shortcut="",
                callback=disabled_callback,
                enabled_check=lambda: False,
                category="Test",
            )
        )

        enabled = registry.get_enabled()
        assert len(enabled) == 1
        assert enabled[0].action_id == "enabled"

    def test_execute_success(self, registry):
        """Test executing action."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="test.action",
                title="Test Action",
                keywords=["test"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        success = registry.execute("test.action")
        assert success is True
        callback.assert_called_once()

    def test_execute_not_found(self, registry):
        """Test executing non-existent action."""
        success = registry.execute("nonexistent")
        assert success is False

    def test_execute_disabled(self, registry):
        """Test executing disabled action fails."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="disabled",
                title="Disabled Action",
                keywords=["disabled"],
                shortcut="",
                callback=callback,
                enabled_check=lambda: False,
                category="Test",
            )
        )

        success = registry.execute("disabled")
        assert success is False
        callback.assert_not_called()


class TestSearchScoring:
    """Test search scoring algorithm."""

    def test_empty_query_returns_all_enabled(self, registry):
        """Test empty query returns all enabled actions."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="action1",
                title="Action 1",
                keywords=["one"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        registry.register(
            ActionSpec(
                action_id="action2",
                title="Action 2",
                keywords=["two"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("")
        assert len(results) == 2

    def test_exact_title_match(self, registry):
        """Test exact title match scores highest."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="exact",
                title="import",
                keywords=[],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        registry.register(
            ActionSpec(
                action_id="contains",
                title="Import Dictionary",
                keywords=[],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("import")
        assert len(results) == 2
        assert results[0][0].action_id == "exact"  # Exact match first

    def test_title_prefix_beats_contains(self, registry):
        """Test title prefix scores higher than contains."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="prefix",
                title="Import Dictionary",
                keywords=[],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        registry.register(
            ActionSpec(
                action_id="contains",
                title="Dictionary Import Tool",
                keywords=[],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("import")
        assert len(results) == 2
        assert results[0][0].action_id == "prefix"  # Prefix first

    def test_keyword_matching(self, registry):
        """Test keyword matching."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="with_keyword",
                title="Translation Management",
                keywords=["tm", "translate", "memory"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("tm")
        assert len(results) == 1
        assert results[0][0].action_id == "with_keyword"
        assert results[0][1] > 0  # Has score

    def test_no_match(self, registry):
        """Test no match returns empty."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="action",
                title="Test Action",
                keywords=["test"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("nonexistent")
        assert len(results) == 0

    def test_multi_word_query(self, registry):
        """Test multi-word query matching."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="import_dict",
                title="Import Dictionary",
                keywords=["csv", "load"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("import csv")
        assert len(results) == 1
        assert results[0][0].action_id == "import_dict"

    def test_case_insensitive(self, registry):
        """Test search is case insensitive."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="action",
                title="Import Dictionary",
                keywords=["CSV"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        results = registry.search("IMPORT")
        assert len(results) == 1

        results = registry.search("csv")
        assert len(results) == 1


class TestPerformance:
    """Test search performance."""

    def test_1000_actions_search_performance(self, registry):
        """Test search on 1000 actions completes in <50ms p95."""
        callback = MagicMock()

        # Register 1000 actions
        for i in range(1000):
            registry.register(
                ActionSpec(
                    action_id=f"action_{i}",
                    title=f"Action {i}",
                    keywords=[f"keyword{i}", f"tag{i % 10}"],
                    shortcut=f"Ctrl+{i % 10}",
                    callback=callback,
                    category=f"Category{i % 5}",
                )
            )

        # Measure search times
        times = []
        queries = ["action", "keyword", "tag5", "Category", "ctrl"]

        for query in queries:
            for _ in range(10):  # 10 runs per query
                start = time.perf_counter()
                results = registry.search(query)
                end = time.perf_counter()
                times.append((end - start) * 1000)  # Convert to ms

        # Calculate p95
        times.sort()
        p95_index = int(len(times) * 0.95)
        p95_time = times[p95_index]

        print(f"\nSearch performance on 1000 actions:")
        print(f"  Median: {times[len(times)//2]:.2f}ms")
        print(f"  P95: {p95_time:.2f}ms")
        print(f"  Max: {max(times):.2f}ms")

        assert p95_time < 50, f"P95 search time {p95_time:.2f}ms exceeds 50ms"


class TestCommandPaletteDialog:
    """Test command palette dialog."""

    def test_dialog_shows_all_actions(self, registry, qtbot):
        """Test dialog shows all enabled actions."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="action1",
                title="Action 1",
                keywords=["one"],
                shortcut="Ctrl+1",
                callback=callback,
                category="Test",
            )
        )

        registry.register(
            ActionSpec(
                action_id="action2",
                title="Action 2",
                keywords=["two"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        dialog = CommandPaletteDialog()
        qtbot.addWidget(dialog)

        # Should show both actions
        assert dialog.results_list.count() == 2

    def test_dialog_filters_on_search(self, registry, qtbot):
        """Test dialog filters results on search."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="import",
                title="Import Dictionary",
                keywords=["csv"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        registry.register(
            ActionSpec(
                action_id="export",
                title="Export Data",
                keywords=["save"],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        dialog = CommandPaletteDialog()
        qtbot.addWidget(dialog)

        # Type "import"
        dialog.search_input.setText("import")

        # Should show only import action
        assert dialog.results_list.count() == 1
        item = dialog.results_list.item(0)
        assert "Import Dictionary" in item.text()

    def test_dialog_auto_selects_first_result(self, registry, qtbot):
        """Test dialog auto-selects first result."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="action",
                title="Action",
                keywords=[],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        dialog = CommandPaletteDialog()
        qtbot.addWidget(dialog)

        assert dialog.results_list.currentRow() == 0

    def test_dialog_emits_action_selected(self, registry, qtbot):
        """Test dialog emits action_selected on Enter."""
        callback = MagicMock()
        registry.register(
            ActionSpec(
                action_id="test.action",
                title="Test Action",
                keywords=[],
                shortcut="",
                callback=callback,
                category="Test",
            )
        )

        dialog = CommandPaletteDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.action_selected, timeout=1000) as blocker:
            dialog._execute_selected()

        assert blocker.args[0] == "test.action"
