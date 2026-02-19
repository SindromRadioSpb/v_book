"""Legacy smoke tests for UserDictionaryItemsTableModel last-review highlighting."""

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
        last_grade="hard",
        last_graded_at=None,
        study_review_count=0,
        study_due_at=None,
        is_suspended=0,
    )


def test_user_dictionary_model_has_study_status_column_label():
    model = UserDictionaryItemsTableModel(items=[_item("new")])
    assert model.headerData(5, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Study Status"


def test_last_review_cell_has_background_only_for_review_column():
    model = UserDictionaryItemsTableModel(items=[_item("due")])
    review_brush = model.data(model.index(0, 6), Qt.ItemDataRole.BackgroundRole)
    source_brush = model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert review_brush is not None
    assert source_brush is None
