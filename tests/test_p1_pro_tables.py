"""
Tests for P1 Pro Tables (MultiSortProxyModel).

Tests multi-column sorting, numeric awareness, proxy row mapping, and performance.
"""

import time
import pytest
from unittest.mock import MagicMock

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PyQt6.QtWidgets import QApplication

from app.ui.multi_sort_proxy import MultiSortProxyModel


class SimpleTableModel(QAbstractTableModel):
    """Simple table model for testing."""

    def __init__(self, data):
        super().__init__()
        self._data = data  # List of lists

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._data[0]) if self._data else 0

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return self._data[index.row()][index.column()]
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Support editing."""
        if role == Qt.ItemDataRole.EditRole:
            self._data[index.row()][index.column()] = value
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            return True
        return False

    def flags(self, index):
        """Make cells editable."""
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable


class TestMultiSortProxy:
    """Test MultiSortProxyModel."""

    def test_single_sort_ascending(self):
        """Test single column sort ascending."""
        data = [
            ["Charlie", 30],
            ["Alice", 25],
            ["Bob", 35],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Sort by name (column 0) ascending
        proxy.sort(0, Qt.SortOrder.AscendingOrder)

        # Verify order: Alice, Bob, Charlie
        assert proxy.data(proxy.index(0, 0)) == "Alice"
        assert proxy.data(proxy.index(1, 0)) == "Bob"
        assert proxy.data(proxy.index(2, 0)) == "Charlie"

    def test_single_sort_descending(self):
        """Test single column sort descending."""
        data = [
            ["Charlie", 30],
            ["Alice", 25],
            ["Bob", 35],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Sort by name (column 0) descending
        proxy.sort(0, Qt.SortOrder.DescendingOrder)

        # Verify order: Charlie, Bob, Alice
        assert proxy.data(proxy.index(0, 0)) == "Charlie"
        assert proxy.data(proxy.index(1, 0)) == "Bob"
        assert proxy.data(proxy.index(2, 0)) == "Alice"

    def test_multi_sort_two_keys(self):
        """Test multi-column sort with two keys."""
        data = [
            ["Bob", 30],
            ["Alice", 25],
            ["Bob", 20],
            ["Alice", 35],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Sort by name (column 0) ascending, then age (column 1) ascending
        proxy.set_sort_keys([(0, Qt.SortOrder.AscendingOrder), (1, Qt.SortOrder.AscendingOrder)])
        # Trigger sort (use first key for base sort)
        QSortFilterProxyModel.sort(proxy, 0, Qt.SortOrder.AscendingOrder)

        # Verify order: Alice 25, Alice 35, Bob 20, Bob 30
        assert proxy.data(proxy.index(0, 0)) == "Alice"
        assert proxy.data(proxy.index(0, 1)) == 25
        assert proxy.data(proxy.index(1, 0)) == "Alice"
        assert proxy.data(proxy.index(1, 1)) == 35
        assert proxy.data(proxy.index(2, 0)) == "Bob"
        assert proxy.data(proxy.index(2, 1)) == 20
        assert proxy.data(proxy.index(3, 0)) == "Bob"
        assert proxy.data(proxy.index(3, 1)) == 30

    def test_numeric_sort(self):
        """Test numeric sorting (123 < 45 when parsed as numbers)."""
        data = [
            ["123"],
            ["45"],
            ["9"],
            ["1000"],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Sort by number (column 0) ascending
        proxy.sort(0, Qt.SortOrder.AscendingOrder)

        # Verify numeric order: 9, 45, 123, 1000
        assert proxy.data(proxy.index(0, 0)) == "9"
        assert proxy.data(proxy.index(1, 0)) == "45"
        assert proxy.data(proxy.index(2, 0)) == "123"
        assert proxy.data(proxy.index(3, 0)) == "1000"

    def test_none_empty_to_bottom(self):
        """Test None/empty values sorted to bottom."""
        data = [
            ["Charlie"],
            [None],
            ["Alice"],
            [""],
            ["Bob"],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Sort ascending
        proxy.sort(0, Qt.SortOrder.AscendingOrder)

        # Verify None/empty at bottom: Alice, Bob, Charlie, empty, None
        assert proxy.data(proxy.index(0, 0)) == "Alice"
        assert proxy.data(proxy.index(1, 0)) == "Bob"
        assert proxy.data(proxy.index(2, 0)) == "Charlie"
        # Last two are None or ""
        assert proxy.data(proxy.index(3, 0)) in [None, ""]
        assert proxy.data(proxy.index(4, 0)) in [None, ""]

    def test_proxy_row_mapping(self):
        """Test map_to_source_row and map_from_source_row."""
        data = [
            ["Charlie"],
            ["Alice"],
            ["Bob"],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Sort ascending: Alice (source 1), Bob (source 2), Charlie (source 0)
        proxy.sort(0, Qt.SortOrder.AscendingOrder)

        # Proxy row 0 (Alice) should map to source row 1
        assert proxy.map_to_source_row(0) == 1
        # Proxy row 1 (Bob) should map to source row 2
        assert proxy.map_to_source_row(1) == 2
        # Proxy row 2 (Charlie) should map to source row 0
        assert proxy.map_to_source_row(2) == 0

        # Reverse mapping
        assert proxy.map_from_source_row(0) == 2  # Source 0 (Charlie) → proxy 2
        assert proxy.map_from_source_row(1) == 0  # Source 1 (Alice) → proxy 0
        assert proxy.map_from_source_row(2) == 1  # Source 2 (Bob) → proxy 1

    def test_edit_through_proxy(self):
        """Test setData works through proxy."""
        data = [
            ["Alice"],
            ["Bob"],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Edit through proxy
        proxy_index = proxy.index(0, 0)
        success = proxy.setData(proxy_index, "Charlie", Qt.ItemDataRole.EditRole)
        assert success is True

        # Verify source model changed
        assert proxy.data(proxy_index) == "Charlie"

    def test_flags_preserved(self):
        """Test flags (editable) preserved through proxy."""
        data = [["Alice"]]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Check flags
        proxy_index = proxy.index(0, 0)
        flags = proxy.flags(proxy_index)

        assert flags & Qt.ItemFlag.ItemIsEditable

    def test_sort_with_shift_modifier(self, qtbot):
        """Test Shift+Click adds sort key (multi-sort)."""
        data = [
            ["Bob", 30],
            ["Alice", 25],
        ]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # First sort: column 0
        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        assert len(proxy._sort_keys) == 1
        assert proxy._sort_keys[0] == (0, Qt.SortOrder.AscendingOrder)

        # Simulate Shift+Click on column 1
        QApplication.instance().setOverrideCursor(Qt.CursorShape.ArrowCursor)  # Ensure app exists
        try:
            # Mock keyboard modifiers
            from unittest.mock import patch

            with patch(
                "app.ui.multi_sort_proxy.QApplication.keyboardModifiers",
                return_value=Qt.KeyboardModifier.ShiftModifier,
            ):
                proxy.sort(1, Qt.SortOrder.AscendingOrder)
        finally:
            QApplication.restoreOverrideCursor()

        # Should have two sort keys now
        assert len(proxy._sort_keys) == 2
        assert proxy._sort_keys[0] == (0, Qt.SortOrder.AscendingOrder)
        assert proxy._sort_keys[1] == (1, Qt.SortOrder.AscendingOrder)


class TestPerformance:
    """Test sorting performance."""

    def test_1000_row_sort_performance(self):
        """Test 1000-row sort completes in <100ms."""
        import random

        # Generate 1000 rows
        data = [[f"Name{i}", random.randint(1, 1000)] for i in range(1000)]
        model = SimpleTableModel(data)
        proxy = MultiSortProxyModel()
        proxy.setSourceModel(model)

        # Measure sort time
        start = time.perf_counter()
        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        end = time.perf_counter()

        elapsed_ms = (end - start) * 1000
        print(f"\n1000-row sort time: {elapsed_ms:.2f}ms")

        assert elapsed_ms < 100, f"Sort took {elapsed_ms:.2f}ms, exceeds 100ms"
