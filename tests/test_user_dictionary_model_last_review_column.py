"""Tests for Last Review column rendering in user dictionary table model."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import UserDictionaryItemsTableModel


def _item(*, grade: str | None, review_count: int, graded_at: str | None = None):
    return SimpleNamespace(
        kind="lemma",
        src_text="alpha",
        translation="",
        translation_tier="missing",
        audio_status="missing",
        is_noise=0,
        computed_study_state="new",
        origin_kind="manual",
        status_tooltip="status tooltip",
        last_grade=grade,
        last_graded_at=graded_at,
        study_review_count=review_count,
        study_due_at="2026-02-20T00:00:00.000000Z",
        is_suspended=0,
    )


def test_last_review_column_label_and_values():
    model = UserDictionaryItemsTableModel(
        items=[_item(grade=None, review_count=0), _item(grade="good", review_count=3)]
    )
    assert (
        model.headerData(6, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Last Review"
    )
    assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "Added"
    assert model.data(model.index(1, 6), Qt.ItemDataRole.DisplayRole) == "Good"


def test_last_review_uses_grade_even_when_review_count_zero_after_again():
    model = UserDictionaryItemsTableModel(items=[_item(grade="again", review_count=0)])
    assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "Again"


def test_background_role_applies_only_to_last_review_column():
    model = UserDictionaryItemsTableModel(items=[_item(grade="hard", review_count=2)])
    last_review_brush = model.data(model.index(0, 6), Qt.ItemDataRole.BackgroundRole)
    source_brush = model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert last_review_brush is not None
    assert last_review_brush.color().name().lower() == "#ffe3b8"
    assert source_brush is None


def test_last_review_tooltip_contains_grade_metadata():
    model = UserDictionaryItemsTableModel(
        items=[_item(grade="again", review_count=5, graded_at="2026-02-19T12:30:00.000000Z")]
    )
    tooltip = model.data(model.index(0, 6), Qt.ItemDataRole.ToolTipRole)
    assert "Last review: Again" in tooltip
    assert "Last graded at: 2026-02-19T12:30:00.000000Z" in tooltip
    assert "Review count: 5" in tooltip
