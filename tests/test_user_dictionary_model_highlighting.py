"""Tests for UserDictionaryItemsTableModel study-status highlighting."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import UserDictionaryItemsTableModel


def _item(study_state: str):
    return SimpleNamespace(
        kind="lemma",
        src_text="alpha",
        translation="",
        translation_tier="missing",
        audio_status="missing",
        is_noise=0,
        computed_study_state=study_state,
        origin_kind="manual",
        status_tooltip="x",
    )


def test_user_dictionary_model_has_study_status_column_label():
    model = UserDictionaryItemsTableModel(items=[_item("new")])
    assert model.headerData(5, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Study Status"


def test_row_background_uses_due_semantic_color():
    model = UserDictionaryItemsTableModel(items=[_item("due")])
    brush = model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#fff3e0"
