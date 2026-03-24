"""PATCH-05 — Semantic surfacing column contract tests.

Covers:
1. TermClusterTableModel Kind column (col 6): header, display, tooltip
2. TermClusterTableModel header tooltips: all P1 columns present
3. TranslationManagementTableModel col 3 renamed "Source" → "Term"
4. TranslationManagementTableModel header tooltips: P1 columns present
5. source_kinds flows from ClusterStats DTO to Kind column
6. Column count increased by 1 (Kind added)
"""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import TermClusterTableModel, TranslationManagementTableModel


def _cluster(source_kinds: str | None = "ngram") -> SimpleNamespace:
    return SimpleNamespace(
        cluster_id=1,
        representative_he="term",
        representative_lemma="term",
        freq_abs=3,
        doc_freq=2,
        members_count=1,
        source_kinds=source_kinds,
        best_pmi=None,
        best_llr=None,
        best_dice=None,
        weirdness=None,
        best_keyness=None,
        keyness_llr=None,
        termhood_score=None,
        translation="",
        translation_source="none",
        translation_status="none",
        is_noise=0,
        in_user_dictionary_count=0,
        study_state=None,
        last_grade=None,
        audio_status=None,
        study_tooltip=None,
        pronunciation_text=None,
        pronunciation_source=None,
        pronunciation_confidence=None,
        pronunciation_qc=None,
    )


def _tm_entry() -> SimpleNamespace:
    return SimpleNamespace(
        tm_id=1,
        kind="lemma",
        src_text="term",
        translation="",
        status="draft",
        project_id=1,
        origin="user_edit",
        source_ref=None,
        updated_at=None,
        is_noise=0,
        in_user_dictionary_count=0,
        last_grade=None,
        audio_status=None,
        study_state=None,
        study_tooltip=None,
        pronunciation_text=None,
        pronunciation_source=None,
        pronunciation_confidence=None,
        pronunciation_qc=None,
        source_status="linked",
        promoted_from_cluster_id=None,
        promoted_at_params_hash=None,
    )


# ---------------------------------------------------------------------------
# TermClusterTableModel — Kind column
# ---------------------------------------------------------------------------


def test_terms_kind_column_header():
    model = TermClusterTableModel()
    assert model.headerData(6, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Kind"


def test_terms_kind_column_display_ngram():
    model = TermClusterTableModel([_cluster("ngram")])
    assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "ngram"


def test_terms_kind_column_display_np():
    model = TermClusterTableModel([_cluster("np")])
    assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "np"


def test_terms_kind_column_display_both():
    model = TermClusterTableModel([_cluster("ngram,np")])
    assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "ngram,np"


def test_terms_kind_column_display_none_fallback():
    """source_kinds=None renders as '?' not empty string."""
    model = TermClusterTableModel([_cluster(None)])
    assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "?"


def test_terms_kind_column_tooltip():
    model = TermClusterTableModel([_cluster()])
    tooltip = model.data(model.index(0, 6), Qt.ItemDataRole.ToolTipRole)
    assert tooltip is not None
    assert "ngram" in tooltip
    assert "np" in tooltip


def test_terms_column_count_is_20():
    """Adding Kind column means 20 columns total (was 19)."""
    model = TermClusterTableModel()
    assert model.columnCount() == 20


# ---------------------------------------------------------------------------
# TermClusterTableModel — header tooltips for P1 columns
# ---------------------------------------------------------------------------


def test_terms_header_tooltips_p1_present():
    """P1 header tooltips: Kind, Translation Source, Translation Status, Noise."""
    model = TermClusterTableModel()
    H = Qt.Orientation.Horizontal
    T = Qt.ItemDataRole.ToolTipRole

    # Kind (col 6)
    tt = model.headerData(6, H, T)
    assert tt is not None, "Kind column must have a header tooltip"
    assert "ngram" in tt

    # Translation Source (col 14)
    tt = model.headerData(14, H, T)
    assert tt is not None, "Source column must have a header tooltip"
    assert "tm" in tt or "translation" in tt.lower()

    # Translation Status (col 15)
    tt = model.headerData(15, H, T)
    assert tt is not None, "Status column must have a header tooltip"
    assert "approved" in tt or "draft" in tt

    # Noise (col 16)
    tt = model.headerData(16, H, T)
    assert tt is not None, "Noise column must have a header tooltip"
    assert "noise" in tt.lower() or "Noise" in tt


def test_terms_header_tooltips_stats_columns():
    """PMI, LLR, Dice columns have header tooltips."""
    model = TermClusterTableModel()
    H = Qt.Orientation.Horizontal
    T = Qt.ItemDataRole.ToolTipRole

    assert model.headerData(7, H, T) is not None, "PMI must have tooltip"
    assert model.headerData(8, H, T) is not None, "LLR must have tooltip"
    assert model.headerData(9, H, T) is not None, "Dice must have tooltip"


# ---------------------------------------------------------------------------
# TranslationManagementTableModel — col 3 renamed "Source" → "Term"
# ---------------------------------------------------------------------------


def test_tm_col3_header_is_term():
    """TM col 3 must be 'Term', not 'Source' (source name collision fix)."""
    model = TranslationManagementTableModel()
    header = model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
    assert (
        header == "Term"
    ), f"TM col 3 must be 'Term' to disambiguate from translation source. Got: '{header}'"


def test_tm_col3_source_string_not_in_headers():
    """'Source' header must not exist at position 3 any more."""
    model = TranslationManagementTableModel()
    headers = [
        model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for i in range(model.columnCount())
    ]
    assert headers[3] != "Source", "Col 3 renamed from 'Source' to 'Term'"


# ---------------------------------------------------------------------------
# TranslationManagementTableModel — header tooltips
# ---------------------------------------------------------------------------


def test_tm_header_tooltips_p1_present():
    """P1 TM header tooltips: Kind, Term, Scope, Origin."""
    model = TranslationManagementTableModel()
    H = Qt.Orientation.Horizontal
    T = Qt.ItemDataRole.ToolTipRole

    # Kind (col 2)
    tt = model.headerData(2, H, T)
    assert tt is not None, "TM Kind column must have a header tooltip"
    assert "lemma" in tt or "ngram" in tt

    # Term / src_text (col 3)
    tt = model.headerData(3, H, T)
    assert tt is not None, "TM Term column must have a header tooltip"
    assert "Hebrew" in tt or "source" in tt.lower() or "term" in tt.lower()

    # Scope (col 6)
    tt = model.headerData(6, H, T)
    assert tt is not None, "TM Scope column must have a header tooltip"

    # Origin (col 7)
    tt = model.headerData(7, H, T)
    assert tt is not None, "TM Origin column must have a header tooltip"


# ---------------------------------------------------------------------------
# source_kinds DTO contract
# ---------------------------------------------------------------------------


def test_cluster_stats_has_source_kinds_field():
    """ClusterStats DTO must have source_kinds field."""
    from app.domain.dto import ClusterStats

    cs = ClusterStats(
        cluster_id=1,
        canonical_key="key",
        representative_he="he",
        representative_lemma="lemma",
        freq_abs=1,
        doc_freq=1,
        members_count=1,
        best_pmi=None,
        best_llr=None,
        best_dice=None,
        best_tscore=None,
        source_kinds="ngram",
    )
    assert cs.source_kinds == "ngram"


def test_cluster_stats_source_kinds_defaults_none():
    """source_kinds defaults to None for backward compatibility."""
    from app.domain.dto import ClusterStats

    cs = ClusterStats(
        cluster_id=1,
        canonical_key="key",
        representative_he="he",
        representative_lemma=None,
        freq_abs=1,
        doc_freq=1,
        members_count=1,
        best_pmi=None,
        best_llr=None,
        best_dice=None,
        best_tscore=None,
    )
    assert cs.source_kinds is None
