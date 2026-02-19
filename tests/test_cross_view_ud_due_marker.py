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
            )
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*!"


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
            )
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*!"


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
            )
        ]
    )
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "*!"
