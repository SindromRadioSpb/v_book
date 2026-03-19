"""Tests for audio play delegate cell click wiring."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QTableView

from app.ui.delegates.audio_play_delegate import AudioPlayDelegate


def test_delegate_emits_play_callback_for_ready_cell(qtbot):
    model = QStandardItemModel(1, 1)
    model.setData(model.index(0, 0), "ready")

    clicked = []
    view = QTableView()
    qtbot.addWidget(view)
    delegate = AudioPlayDelegate(
        on_play_clicked=lambda idx: clicked.append((idx.row(), idx.column()))
    )
    view.setModel(model)
    view.setItemDelegateForColumn(0, delegate)
    view.resize(140, 40)
    view.show()

    rect = view.visualRect(model.index(0, 0))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert clicked == [(0, 0)]


def test_delegate_ignores_click_for_missing_audio(qtbot):
    model = QStandardItemModel(1, 1)
    model.setData(model.index(0, 0), "missing")

    clicked = []
    view = QTableView()
    qtbot.addWidget(view)
    delegate = AudioPlayDelegate(
        on_play_clicked=lambda idx: clicked.append((idx.row(), idx.column()))
    )
    view.setModel(model)
    view.setItemDelegateForColumn(0, delegate)
    view.resize(140, 40)
    view.show()

    rect = view.visualRect(model.index(0, 0))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert clicked == []
