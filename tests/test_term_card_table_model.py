"""Tests for TermCardTableModel UD column and header sorting."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import TermCardTableModel


def _card(
    *,
    cluster_id: int,
    term: str,
    lemma: str,
    freq: int,
    doc_freq: int,
    status: str = "auto",
    pinned_translation: str = "",
    aliases=None,
    is_stopword: bool = False,
    in_ud_count: int = 0,
    tooltip: str | None = None,
):
    return SimpleNamespace(
        cluster_id=cluster_id,
        representative_he=term,
        representative_lemma=lemma,
        freq_abs=freq,
        doc_freq=doc_freq,
        curation_status=status,
        pinned_translation=pinned_translation,
        aliases=aliases or [],
        is_stopword=is_stopword,
        in_user_dictionary_count=in_ud_count,
        study_tooltip=tooltip,
    )


def test_ud_indicator_is_in_dedicated_column():
    model = TermCardTableModel(
        cards=[
            _card(cluster_id=1, term="beta", lemma="beta", freq=10, doc_freq=4, in_ud_count=1),
            _card(cluster_id=2, term="alpha", lemma="alpha", freq=2, doc_freq=2, in_ud_count=0),
        ]
    )

    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "UD"
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*"
    assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "beta"
    assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == ""
    assert model.data(model.index(1, 1), Qt.ItemDataRole.DisplayRole) == "alpha"


def test_header_sorting_works_for_numeric_and_ud_columns():
    model = TermCardTableModel(
        cards=[
            _card(cluster_id=1, term="beta", lemma="beta", freq=10, doc_freq=4, in_ud_count=0),
            _card(cluster_id=2, term="alpha", lemma="alpha", freq=2, doc_freq=2, in_ud_count=1),
        ]
    )

    model.sort(3, Qt.SortOrder.AscendingOrder)  # Freq
    assert model.get_card(0).representative_he == "alpha"
    assert model.get_card(1).representative_he == "beta"

    model.sort(0, Qt.SortOrder.DescendingOrder)  # UD count
    assert model.get_card(0).representative_he == "alpha"
    assert model.get_card(1).representative_he == "beta"


def test_tooltip_visible_only_for_ud_members():
    model = TermCardTableModel(
        cards=[
            _card(cluster_id=1, term="saved", lemma="saved", freq=1, doc_freq=1, in_ud_count=1, tooltip="saved tooltip"),
            _card(cluster_id=2, term="not_saved", lemma="not_saved", freq=1, doc_freq=1, in_ud_count=0, tooltip="hidden tooltip"),
        ]
    )

    assert model.data(model.index(0, 1), Qt.ItemDataRole.ToolTipRole) == "saved tooltip"
    assert model.data(model.index(1, 1), Qt.ItemDataRole.ToolTipRole) is None
