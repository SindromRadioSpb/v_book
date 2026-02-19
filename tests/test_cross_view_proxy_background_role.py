"""Ensure proxy models propagate BackgroundRole for cross-view row highlighting."""

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import LemmaTableModel, TermClusterTableModel
from app.ui.multi_sort_proxy import MultiSortProxyModel


def test_dictionary_proxy_preserves_background_role():
    source = LemmaTableModel(
        lemmas=[
            SimpleNamespace(
                in_user_dictionary_count=1,
                study_state="learning",
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
    proxy = MultiSortProxyModel()
    proxy.setSourceModel(source)
    brush = proxy.data(proxy.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#ffd7d9"


def test_terms_proxy_preserves_background_role():
    source = TermClusterTableModel(
        clusters=[
            SimpleNamespace(
                in_user_dictionary_count=1,
                study_state="learning",
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
    proxy = MultiSortProxyModel()
    proxy.setSourceModel(source)
    brush = proxy.data(proxy.index(0, 1), Qt.ItemDataRole.BackgroundRole)
    assert brush is not None
    assert brush.color().name().lower() == "#cdeed1"
