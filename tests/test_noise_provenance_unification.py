"""PATCH-07 — Noise provenance unification tests.

Covers:
1. TermClusterTableModel Noise column shows "(auto)"/"(manual)" suffix
2. TranslationManagementTableModel Noise column shows suffix
3. Noise tooltip uses noise_source for provenance
4. ClusterStats + TMEntryDTO have noise_source field
5. TM FilterDialog (renamed) has Kind + Noise sections
6. TermsFilterDialog has Kind + Noise sections
7. FilterDialog.get_selected_noise() returns correct values
"""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt

from app.domain.dto import ClusterStats, TMEntryDTO
from app.ui.models_qt import TermClusterTableModel, TranslationManagementTableModel


def _cluster(is_noise=1, noise_source="auto"):
    return SimpleNamespace(
        cluster_id=1,
        representative_he="term",
        representative_lemma="term",
        freq_abs=1,
        doc_freq=1,
        members_count=1,
        source_kinds="ngram",
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
        is_noise=is_noise,
        noise_source=noise_source,
        noise_reason=None,
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


def _tm_entry(is_noise=1, noise_source="auto"):
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
        is_noise=is_noise,
        noise_source=noise_source,
        noise_reason=None,
        in_user_dictionary_count=0,
        study_state=None,
        last_grade=None,
        audio_status=None,
        study_tooltip=None,
        pronunciation_text=None,
        pronunciation_source=None,
        pronunciation_confidence=None,
        pronunciation_qc=None,
        source_status="linked",
        promoted_from_cluster_id=None,
        promoted_at_params_hash=None,
    )


def test_terms_noise_auto():
    model = TermClusterTableModel([_cluster(is_noise=1, noise_source="auto")])
    val = model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole)
    assert val == "Noise (auto)"


def test_terms_noise_manual():
    model = TermClusterTableModel([_cluster(is_noise=1, noise_source="manual")])
    val = model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole)
    assert val == "Noise (manual)"


def test_terms_valid_auto():
    model = TermClusterTableModel([_cluster(is_noise=0, noise_source="auto")])
    val = model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole)
    assert val == "Valid (auto)"


def test_terms_valid_manual():
    model = TermClusterTableModel([_cluster(is_noise=0, noise_source="manual")])
    val = model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole)
    assert val == "Valid (manual)"


def test_terms_unclassified():
    model = TermClusterTableModel([_cluster(is_noise=None, noise_source=None)])
    val = model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole)
    assert val == ""


def test_terms_legacy_no_suffix():
    """Legacy rows (noise_source=None) show no suffix."""
    model = TermClusterTableModel([_cluster(is_noise=1, noise_source=None)])
    val = model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole)
    assert val == "Noise"


def test_terms_noise_tooltip_uses_noise_source():
    model = TermClusterTableModel([_cluster(is_noise=1, noise_source="auto")])
    tt = model.data(model.index(0, 16), Qt.ItemDataRole.ToolTipRole)
    assert tt is not None
    assert "auto" in tt.lower() or "automatically" in tt.lower()


def test_tm_noise_auto():
    model = TranslationManagementTableModel([_tm_entry(is_noise=1, noise_source="auto")])
    val = model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole)
    assert val == "Noise (auto)"


def test_tm_noise_manual():
    model = TranslationManagementTableModel([_tm_entry(is_noise=1, noise_source="manual")])
    val = model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole)
    assert val == "Noise (manual)"


def test_tm_valid_auto():
    model = TranslationManagementTableModel([_tm_entry(is_noise=0, noise_source="auto")])
    val = model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole)
    assert val == "Valid (auto)"


def test_tm_valid_manual():
    model = TranslationManagementTableModel([_tm_entry(is_noise=0, noise_source="manual")])
    val = model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole)
    assert val == "Valid (manual)"


def test_cluster_stats_has_noise_source():
    cs = ClusterStats(
        cluster_id=1,
        canonical_key="k",
        representative_he="h",
        representative_lemma=None,
        freq_abs=1,
        doc_freq=1,
        members_count=1,
        best_pmi=None,
        best_llr=None,
        best_dice=None,
        best_tscore=None,
        noise_source="auto",
    )
    assert cs.noise_source == "auto"


def test_tm_entry_dto_has_noise_source():
    dto = TMEntryDTO(
        tm_id=1,
        project_id=1,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="t",
        src_norm="t",
        translation="",
        translation_norm=None,
        pos=None,
        domain=None,
        notes=None,
        status="draft",
        confidence=None,
        origin="user_edit",
        source_ref=None,
        created_at="2026-01-01",
        updated_at="2026-01-01",
        approved_at=None,
        approved_by=None,
        is_noise=0,
        noise_reason=None,
        norm_text=None,
        lemma_id=None,
        cluster_id=None,
        ngram_id=None,
        noise_source="manual",
    )
    assert dto.noise_source == "manual"


def test_filter_dialog_kind_and_noise_sections(qtbot):
    from app.ui.translation_management_panel import FilterDialog

    dlg = FilterDialog(["lemma"], ["noise_auto"], parent=None)
    qtbot.addWidget(dlg)
    assert dlg.get_selected_kinds() == ["lemma"]
    assert dlg.get_selected_noise() == ["noise_auto"]


def test_filter_dialog_all_selected_returns_none(qtbot):
    from app.ui.translation_management_panel import FilterDialog

    all_kinds = FilterDialog.ALL_KINDS
    all_noise = FilterDialog.ALL_NOISE
    dlg = FilterDialog(all_kinds, all_noise, parent=None)
    qtbot.addWidget(dlg)
    assert dlg.get_selected_kinds() is None
    assert dlg.get_selected_noise() is None


def test_terms_filter_dialog_exists(qtbot):
    from app.ui.terms_view import TermsFilterDialog

    dlg = TermsFilterDialog(["ngram"], ["valid_auto"], parent=None)
    qtbot.addWidget(dlg)
    assert dlg.get_selected_kinds() == ["ngram"]
    assert dlg.get_selected_noise() == ["valid_auto"]
