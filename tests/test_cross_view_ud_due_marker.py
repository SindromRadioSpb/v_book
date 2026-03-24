"""Cross-view UD marker tests for due-state rendering."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import LemmaTableModel, TermClusterTableModel, TranslationManagementTableModel


def test_dictionary_ud_marker_is_due_aware():
    model = LemmaTableModel(
        lemmas=[
            SimpleNamespace(
                in_user_dictionary_count=1,
                study_state="due",
                study_tooltip="x",
                lemma_text="alpha",
                pos=None,
                freq_abs=1,
                doc_freq=1,
                translation="",
                status="none",
                is_noise=0,
                last_grade="again",
            )
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*!"
    assert model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole) == "Again"
    brush = model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#ffd7d9"


def test_terms_ud_marker_is_due_aware():
    model = TermClusterTableModel(
        clusters=[
            SimpleNamespace(
                in_user_dictionary_count=1,
                study_state="due",
                study_tooltip="x",
                representative_he="term",
                representative_lemma=None,
                freq_abs=1,
                doc_freq=1,
                members_count=1,
                best_pmi=None,
                best_llr=None,
                best_dice=None,
                weirdness=None,
                keyness_llr=None,
                termhood_score=None,
                translation="",
                translation_source="none",
                translation_status="none",
                is_noise=0,
                last_grade="good",
            )
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*!"
    assert model.data(model.index(0, 17), Qt.ItemDataRole.DisplayRole) == "Good"
    brush = model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#cdeed1"


def test_tm_ud_marker_is_due_aware():
    model = TranslationManagementTableModel(
        entries=[
            SimpleNamespace(
                in_user_dictionary_count=1,
                study_state="due",
                study_tooltip="x",
                tm_id=1,
                kind="lemma",
                src_text="alpha",
                translation="",
                status="draft",
                project_id=None,
                origin="manual",
                source_ref=None,
                updated_at=None,
                is_noise=0,
                last_grade="hard",
            )
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*!"
    assert model.data(model.index(0, 11), Qt.ItemDataRole.DisplayRole) == "Hard"
    brush = model.data(model.index(0, 3), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#ffe3b8"


def test_row_not_highlighted_when_not_in_user_dictionary():
    model = LemmaTableModel(
        lemmas=[
            SimpleNamespace(
                in_user_dictionary_count=0,
                study_state=None,
                study_tooltip=None,
                lemma_text="alpha",
                pos=None,
                freq_abs=1,
                doc_freq=1,
                translation="",
                status="none",
                is_noise=0,
                last_grade=None,
            )
        ]
    )
    assert model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole) == ""
    assert model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole) is None
