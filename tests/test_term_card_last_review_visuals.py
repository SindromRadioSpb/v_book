"""Cross-view Last Review visuals for Term Card table model."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import TermCardTableModel


def test_term_card_last_review_column_and_row_highlight():
    model = TermCardTableModel(
        cards=[
            SimpleNamespace(
                cluster_id=1,
                representative_he="term",
                representative_lemma="lemma",
                freq_abs=3,
                doc_freq=2,
                curation_status="auto",
                pinned_translation="",
                aliases=[],
                is_stopword=False,
                in_user_dictionary_count=1,
                study_state="learning",
                study_tooltip="x",
                last_grade="easy",
            )
        ]
    )

    assert model.headerData(9, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Last Review"
    assert model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole) == "Easy"
    brush = model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#c3e8e4"


def test_term_card_no_ud_no_highlight():
    model = TermCardTableModel(
        cards=[
            SimpleNamespace(
                cluster_id=2,
                representative_he="term2",
                representative_lemma="lemma2",
                freq_abs=1,
                doc_freq=1,
                curation_status="auto",
                pinned_translation="",
                aliases=[],
                is_stopword=False,
                in_user_dictionary_count=0,
                study_state=None,
                study_tooltip=None,
                last_grade=None,
            )
        ]
    )
    assert model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole) == ""
    assert model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole) is None
