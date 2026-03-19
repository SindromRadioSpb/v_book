"""
MultiSortProxyModel - Multi-column sort with Shift+Click support.

Provides QSortFilterProxyModel with multi-column sorting:
- Click column header: sort by that column (reset to single sort)
- Shift+Click column header: add column to sort keys (multi-sort)
- Numeric awareness: "123" < "45" when parsed as numbers
- Null/empty handling: always sorted to bottom
"""

import logging

from PyQt6.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class MultiSortProxyModel(QSortFilterProxyModel):
    """
    Multi-column sort proxy model.

    Intercepts QTableView header clicks and supports:
    - Single-column sort (click)
    - Multi-column sort (Shift+Click)
    - Numeric-aware sorting
    - Null/empty always at bottom
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sort_keys: list[tuple[int, Qt.SortOrder]] = []

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        """
        Intercept QTableView header clicks.

        Args:
            column: Column index to sort by
            order: Sort order (ascending/descending)
        """
        # Check if Shift is pressed for multi-sort
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.add_sort_key(column, order)
        else:
            self.set_sort_keys([(column, order)])

        # Set sort column/order on base class and trigger re-sort
        self.setSortRole(Qt.ItemDataRole.DisplayRole)
        QSortFilterProxyModel.sort(self, column, order)

    def set_sort_keys(self, keys: list[tuple[int, Qt.SortOrder]]):
        """
        Set sort keys (replaces existing).

        Args:
            keys: List of (column, order) tuples
        """
        self._sort_keys = keys.copy()
        logger.debug(f"Sort keys set: {self._sort_keys}")

    def add_sort_key(self, column: int, order: Qt.SortOrder):
        """
        Add a sort key (multi-sort).

        Args:
            column: Column index
            order: Sort order
        """
        # Remove existing key for this column (replace)
        self._sort_keys = [(col, ord) for col, ord in self._sort_keys if col != column]
        # Add new key
        self._sort_keys.append((column, order))
        logger.debug(f"Sort key added: {self._sort_keys}")

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """
        Multi-key comparison with numeric awareness.

        Args:
            left: Left model index (source model)
            right: Right model index (source model)

        Returns:
            True if left < right
        """
        if not self._sort_keys:
            # No sort keys: fallback to default (first column ascending)
            return super().lessThan(left, right)

        # Multi-key comparison
        for column, order in self._sort_keys:
            # Get data from source model
            left_data = self.sourceModel().data(
                self.sourceModel().index(left.row(), column), Qt.ItemDataRole.DisplayRole
            )
            right_data = self.sourceModel().data(
                self.sourceModel().index(right.row(), column), Qt.ItemDataRole.DisplayRole
            )

            # Compare
            result = self._compare_values(left_data, right_data)

            if result != 0:
                # Not equal: return comparison result
                # Note: Base class handles order inversion, so always return ascending comparison
                return result < 0

        # All keys equal: maintain stable sort
        return left.row() < right.row()

    def _compare_values(self, left, right) -> int:
        """
        Compare two values with numeric awareness.

        Args:
            left: Left value
            right: Right value

        Returns:
            -1 if left < right, 0 if equal, 1 if left > right
        """
        # Handle None/empty (always to bottom)
        left_is_none = left is None or left == ""
        right_is_none = right is None or right == ""

        if left_is_none and right_is_none:
            return 0
        if left_is_none:
            return 1  # None/empty to bottom
        if right_is_none:
            return -1

        # Try numeric comparison first
        left_num = self._try_parse_number(left)
        right_num = self._try_parse_number(right)

        if left_num is not None and right_num is not None:
            # Both are numbers
            if left_num < right_num:
                return -1
            elif left_num > right_num:
                return 1
            else:
                return 0

        # Fallback to string comparison (case-insensitive)
        left_str = str(left).lower()
        right_str = str(right).lower()

        if left_str < right_str:
            return -1
        elif left_str > right_str:
            return 1
        else:
            return 0

    def _try_parse_number(self, value) -> float | None:
        """
        Try to parse value as number.

        Args:
            value: Value to parse

        Returns:
            Float if parseable, None otherwise
        """
        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            # Remove commas for thousands separator
            clean = value.replace(",", "")
            try:
                return float(clean)
            except ValueError:
                return None

        return None

    def map_to_source_row(self, proxy_row: int) -> int:
        """
        Map proxy row to source model row.

        Args:
            proxy_row: Row index in proxy model

        Returns:
            Row index in source model
        """
        proxy_index = self.index(proxy_row, 0)
        source_index = self.mapToSource(proxy_index)
        return source_index.row()

    def map_from_source_row(self, source_row: int) -> int:
        """
        Map source model row to proxy row.

        Args:
            source_row: Row index in source model

        Returns:
            Row index in proxy model
        """
        source_index = self.sourceModel().index(source_row, 0)
        proxy_index = self.mapFromSource(source_index)
        return proxy_index.row()
