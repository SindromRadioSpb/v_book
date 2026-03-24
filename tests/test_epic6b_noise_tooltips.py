"""Epic 6B PATCH-02: Semantic tooltip tests — noise provenance + NER class.

Two semantic axes kept strictly separate:
  - Noise column tooltip  = who set noise/valid state (noise provenance)
  - source_lifecycle      = corpus link state (not mixed into noise tooltip)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt

from app.ui.models_qt import (
    LemmaTableModel,
    TranslationManagementTableModel,
    _entity_class_tooltip,
    _noise_provenance_tooltip,
    _tm_noise_tooltip,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions (axis isolation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "is_noise, noise_source, noise_updated_at, expected_fragment",
    [
        # auto-classified
        (1, "auto", "2026-03-20T10:00:00Z", "Automatically classified as noise by NLP pipeline"),
        (0, "auto", "2026-03-20T10:00:00Z", "Automatically classified as valid by NLP pipeline"),
        # manual
        (1, "manual", "2026-03-19T08:00:00Z", "Manually marked as noise"),
        (0, "manual", "2026-03-19T08:00:00Z", "Manually confirmed as valid"),
        # legacy (noise_source=None)
        (1, None, None, "Noise — source unknown (legacy data)"),
        (0, None, None, "Valid — source unknown (legacy data)"),
        # unclassified (is_noise=None)
        (None, None, None, "Not yet classified"),
    ],
)
def test_noise_provenance_tooltip_text(is_noise, noise_source, noise_updated_at, expected_fragment):
    obj = SimpleNamespace(
        is_noise=is_noise, noise_source=noise_source, noise_updated_at=noise_updated_at
    )
    result = _noise_provenance_tooltip(obj)
    assert expected_fragment in result, f"Expected {expected_fragment!r} in {result!r}"


def test_noise_provenance_tooltip_includes_date_when_available():
    obj = SimpleNamespace(is_noise=1, noise_source="auto", noise_updated_at="2026-03-20T10:00:00Z")
    result = _noise_provenance_tooltip(obj)
    assert "2026-03-20" in result


def test_noise_provenance_tooltip_no_date_for_legacy():
    obj = SimpleNamespace(is_noise=1, noise_source=None, noise_updated_at=None)
    result = _noise_provenance_tooltip(obj)
    assert "Date" not in result


def test_noise_provenance_tooltip_no_date_when_missing():
    obj = SimpleNamespace(is_noise=0, noise_source="manual", noise_updated_at=None)
    result = _noise_provenance_tooltip(obj)
    assert "Date" not in result


@pytest.mark.parametrize(
    "entity_class, expected_fragment",
    [
        ("GPE", "Geo-Political Entity"),
        ("PER", "Person name"),
        ("ORG", "Organization"),
        ("LOC", "Location"),
        ("MISC", "Miscellaneous"),
        ("UNKNOWN_CLASS", "Named entity class: UNKNOWN_CLASS"),
    ],
)
def test_entity_class_tooltip_known_and_unknown(entity_class, expected_fragment):
    result = _entity_class_tooltip(entity_class)
    assert expected_fragment in result, f"Expected {expected_fragment!r} in {result!r}"


def test_entity_class_tooltip_none_returns_none():
    assert _entity_class_tooltip(None) is None
    assert _entity_class_tooltip("") is None


@pytest.mark.parametrize(
    "is_noise, noise_reason, expected_fragment",
    [
        (1, "NOISE_PUNCT_ONLY", "punctuation only"),
        (1, "NOISE_NUMBER_ONLY", "number only"),
        # noise_source=None (legacy) → "Source unknown (legacy data)"
        (0, None, "Valid"),
        (1, None, "Noise"),
        (None, None, "Not yet classified"),
    ],
)
def test_tm_noise_tooltip(is_noise, noise_reason, expected_fragment):
    obj = SimpleNamespace(is_noise=is_noise, noise_reason=noise_reason)
    result = _tm_noise_tooltip(obj)
    assert expected_fragment in result, f"Expected {expected_fragment!r} in {result!r}"


# ---------------------------------------------------------------------------
# Integration: LemmaTableModel col 8 (Noise) tooltip
# ---------------------------------------------------------------------------


def _lemma(is_noise=1, noise_source="auto", noise_updated_at="2026-03-20T10:00:00Z"):
    return SimpleNamespace(
        lemma_id=1,
        lemma_text="test",
        pos="NOUN",
        freq_abs=1,
        doc_freq=1,
        translation="",
        status="draft",
        is_noise=is_noise,
        noise_source=noise_source,
        noise_updated_at=noise_updated_at,
        in_user_dictionary_count=0,
        study_state=None,
        last_grade=None,
        study_tooltip=None,
        entity_class=None,
        pronunciation_text=None,
        pronunciation_source=None,
        pronunciation_confidence=None,
        pronunciation_qc=None,
        audio_status=None,
    )


def test_lemma_noise_col_tooltip_auto():
    model = LemmaTableModel([_lemma(is_noise=1, noise_source="auto")])
    tip = model.data(model.index(0, 8), Qt.ItemDataRole.ToolTipRole)
    assert "Automatically" in tip
    assert "NLP pipeline" in tip
    assert "2026-03-20" in tip


def test_lemma_noise_col_tooltip_manual_valid():
    model = LemmaTableModel([_lemma(is_noise=0, noise_source="manual")])
    tip = model.data(model.index(0, 8), Qt.ItemDataRole.ToolTipRole)
    assert "Manually confirmed as valid" in tip


def test_lemma_noise_col_tooltip_legacy():
    model = LemmaTableModel([_lemma(is_noise=1, noise_source=None, noise_updated_at=None)])
    tip = model.data(model.index(0, 8), Qt.ItemDataRole.ToolTipRole)
    assert "legacy data" in tip


def test_lemma_noise_col_tooltip_unclassified():
    model = LemmaTableModel([_lemma(is_noise=None, noise_source=None, noise_updated_at=None)])
    tip = model.data(model.index(0, 8), Qt.ItemDataRole.ToolTipRole)
    assert "Not yet classified" in tip


# ---------------------------------------------------------------------------
# Integration: LemmaTableModel col 9 (Entity Class) tooltip
# ---------------------------------------------------------------------------


def test_lemma_entity_class_tooltip_known():
    lemma = _lemma()
    lemma.entity_class = "GPE"
    model = LemmaTableModel([lemma])
    tip = model.data(model.index(0, 9), Qt.ItemDataRole.ToolTipRole)
    assert "Geo-Political Entity" in tip


def test_lemma_entity_class_tooltip_none_returns_none():
    model = LemmaTableModel([_lemma()])
    tip = model.data(model.index(0, 9), Qt.ItemDataRole.ToolTipRole)
    assert tip is None


# ---------------------------------------------------------------------------
# Integration: TranslationManagementTableModel col 10 (Noise) tooltip
# ---------------------------------------------------------------------------


def _tm_entry(is_noise=1, noise_reason="NOISE_PUNCT_ONLY"):
    return SimpleNamespace(
        tm_id=1,
        kind="lemma",
        src_text="test",
        translation="",
        status="draft",
        project_id=1,
        origin="user_edit",
        source_ref=None,
        updated_at="2026-03-20T00:00:00Z",
        is_noise=is_noise,
        noise_reason=noise_reason,
        in_user_dictionary_count=0,
        study_state=None,
        last_grade=None,
        study_tooltip=None,
        audio_status=None,
        pronunciation_text=None,
        pronunciation_source=None,
        pronunciation_confidence=None,
        pronunciation_qc=None,
    )


def test_tm_noise_col_tooltip_with_reason():
    model = TranslationManagementTableModel(
        [_tm_entry(is_noise=1, noise_reason="NOISE_PUNCT_ONLY")]
    )
    tip = model.data(model.index(0, 10), Qt.ItemDataRole.ToolTipRole)
    assert "punctuation only" in tip


def test_tm_noise_col_tooltip_without_reason():
    # noise_source=None (legacy) → shows provenance "Source unknown (legacy data)"
    model = TranslationManagementTableModel([_tm_entry(is_noise=0, noise_reason=None)])
    tip = model.data(model.index(0, 10), Qt.ItemDataRole.ToolTipRole)
    assert "Valid" in tip
    assert "legacy" in tip.lower() or "source unknown" in tip.lower()


# ---------------------------------------------------------------------------
# Axis isolation: noise tooltip does NOT mention source_lifecycle vocabulary
# ---------------------------------------------------------------------------


def test_noise_tooltip_axis_isolation_no_lifecycle_terms():
    """Noise column tooltip must not bleed source_lifecycle vocabulary."""
    obj = SimpleNamespace(is_noise=1, noise_source="auto", noise_updated_at="2026-03-20T10:00:00Z")
    tip = _noise_provenance_tooltip(obj)
    for lifecycle_term in ("linked", "source_missing", "auto_only", "corpus", "cluster"):
        assert (
            lifecycle_term not in tip.lower()
        ), f"Noise tooltip must not mention source_lifecycle term {lifecycle_term!r}"
