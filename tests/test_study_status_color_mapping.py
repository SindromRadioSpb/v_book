"""Color and marker mapping tests for study/status UI helpers."""

from app.ui.study_status_ui import (
    audio_status_brush,
    origin_brush,
    study_brush,
    translation_tier_brush,
    ud_indicator_brush,
    ud_indicator_text,
)


def test_ud_indicator_text_due_and_non_due():
    assert ud_indicator_text(0, "due") == ""
    assert ud_indicator_text(1, "learning") == "*"
    assert ud_indicator_text(1, "due") == "*!"


def test_study_due_uses_due_color():
    brush = study_brush("due")
    assert brush.color().name().lower() == "#ef6c00"


def test_translation_tier_and_audio_colors_are_stable():
    assert translation_tier_brush("approved").color().name().lower() == "#2e7d32"
    assert translation_tier_brush("deprecated").color().name().lower() == "#c62828"
    assert audio_status_brush("failed").color().name().lower() == "#c62828"
    assert audio_status_brush("ready").color().name().lower() == "#2e7d32"


def test_origin_and_ud_indicator_brushes():
    assert origin_brush("project").color().name().lower() == "#1565c0"
    assert ud_indicator_brush(0, "due") is None
    assert ud_indicator_brush(1, "due").color().name().lower() == "#ef6c00"
