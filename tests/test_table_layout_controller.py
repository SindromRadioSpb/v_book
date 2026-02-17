"""Tests for shared table layout controller."""

import pytest

from PyQt6.QtWidgets import QTableWidget

from app.infra.settings import SettingsService
from app.ui.table_layout_controller import TableLayoutController


@pytest.fixture
def settings():
    """Fresh SettingsService for each test."""
    SettingsService.reset_instance()
    service = SettingsService.get_instance()
    service._settings.clear()
    service.sync()
    yield service
    SettingsService.reset_instance()


def _create_table(qtbot, headers: list[str]) -> QTableWidget:
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    qtbot.addWidget(table)
    table.show()
    return table


def test_install_applies_default_widths(qtbot, settings):
    table = _create_table(qtbot, ["A", "B", "C"])
    controller = TableLayoutController(
        settings=settings,
        table_id="test/table/defaults",
        table=table,
        default_widths={0: 120, 1: 180, 2: 240},
        save_debounce_ms=50,
    )

    restored = controller.install()

    assert restored is False
    assert table.columnWidth(0) == 120
    assert table.columnWidth(1) == 180
    assert table.columnWidth(2) == 240


def test_resize_persists_and_restores_widths(qtbot, settings):
    table1 = _create_table(qtbot, ["A", "B", "C"])
    controller1 = TableLayoutController(
        settings=settings,
        table_id="test/table/roundtrip",
        table=table1,
        default_widths={0: 110, 1: 110, 2: 110},
        save_debounce_ms=50,
    )
    controller1.install()

    table1.setColumnWidth(1, 275)
    qtbot.wait(120)  # debounce save

    table2 = _create_table(qtbot, ["A", "B", "C"])
    controller2 = TableLayoutController(
        settings=settings,
        table_id="test/table/roundtrip",
        table=table2,
        default_widths={0: 110, 1: 110, 2: 110},
        save_debounce_ms=50,
    )
    restored = controller2.install()

    assert restored is True
    assert table2.columnWidth(1) == 275


def test_schema_mismatch_skips_restore(qtbot, settings):
    table1 = _create_table(qtbot, ["A", "B", "C"])
    controller1 = TableLayoutController(
        settings=settings,
        table_id="test/table/schema",
        table=table1,
        default_widths={0: 140, 1: 150, 2: 160},
        save_debounce_ms=50,
    )
    controller1.install()
    table1.setColumnWidth(2, 333)
    controller1.save_now()

    table2 = _create_table(qtbot, ["A", "B", "C", "D"])
    controller2 = TableLayoutController(
        settings=settings,
        table_id="test/table/schema",
        table=table2,
        default_widths={0: 90, 1: 90, 2: 90, 3: 90},
        save_debounce_ms=50,
    )
    restored = controller2.install()

    assert restored is False
    assert table2.columnWidth(2) == 90


def test_reset_to_defaults(qtbot, settings):
    table = _create_table(qtbot, ["A", "B", "C"])
    controller = TableLayoutController(
        settings=settings,
        table_id="test/table/reset",
        table=table,
        default_widths={0: 130, 1: 170, 2: 210},
        save_debounce_ms=50,
    )
    controller.install()

    table.setColumnWidth(0, 320)
    controller.reset_to_defaults()

    assert table.columnWidth(0) == 130
    assert table.columnWidth(1) == 170
    assert table.columnWidth(2) == 210
