"""Cross-view Niqqud column rendering smoke tests."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import Qt

from app.ui.models_qt import (
    LemmaTableModel,
    TermCardTableModel,
    TermClusterTableModel,
    TranslationManagementTableModel,
    UserDictionaryItemsTableModel,
)


def _lemma() -> SimpleNamespace:
    return SimpleNamespace(
        lemma_id=1,
        lemma_text="Ч”ЧЄЧ—Ч Ч” Ч”Ч‘ЧђЧ”",
        pos="NOUN",
        freq_abs=10,
        doc_freq=4,
        translation="",
        status="draft",
        is_noise=0,
        in_user_dictionary_count=1,
        study_state="learning",
        last_grade="good",
        audio_status="ready",
        study_tooltip="tooltip",
        pronunciation_text="Ч”Ц·ЧЄЦ·ЦјЧ—ЦІЧ ЦёЧ” Ч”Ц·Ч‘ЦёЦјЧђЦёЧ”",
        pronunciation_source="manual",
        pronunciation_confidence=1.0,
        pronunciation_qc="ok",
    )


def _cluster() -> SimpleNamespace:
    return SimpleNamespace(
        cluster_id=1,
        representative_he="ЧћЧ™Ч©Ч•ЧЁ Ч”ЧћЧ©Ч•Ч¤Чў",
        representative_lemma="ЧћЧ™Ч©Ч•ЧЁ ЧћЧ©Ч•Ч¤Чў",
        freq_abs=5,
        doc_freq=2,
        members_count=1,
        best_pmi=None,
        best_llr=None,
        best_dice=None,
        weirdness=None,
        keyness_llr=None,
        termhood_score=None,
        translation="",
        translation_source="none",
        translation_status="draft",
        is_noise=0,
        in_user_dictionary_count=1,
        study_state="learning",
        last_grade="hard",
        audio_status="ready",
        study_tooltip="tooltip",
        pronunciation_text="ЧћЦґЧ™Ч©ЧЃЧ•Ц№ЧЁ Ч”Ц·ЧћЦјЦ°Ч©ЧЃЦ»Ч¤ЦјЦёЧў",
        pronunciation_source="auto_phonikud",
        pronunciation_confidence=0.8,
        pronunciation_qc="auto_fixed",
    )


def _tm_entry() -> SimpleNamespace:
    return SimpleNamespace(
        tm_id=1,
        kind="lemma",
        src_text="Ч”ЧЄЧ—Ч Ч” Ч”Ч‘ЧђЧ”",
        translation="",
        status="draft",
        project_id=1,
        origin="user_edit",
        source_ref="tm",
        updated_at="2026-02-20T00:00:00Z",
        is_noise=0,
        in_user_dictionary_count=1,
        last_grade="again",
        audio_status="failed",
        study_tooltip="tooltip",
        pronunciation_text="Ч”Ц·ЧЄЦ·ЦјЧ—ЦІЧ ЦёЧ” Ч”Ц·Ч‘ЦёЦјЧђЦёЧ”",
        pronunciation_source="manual",
        pronunciation_confidence=1.0,
        pronunciation_qc="ok",
    )


def _term_card() -> SimpleNamespace:
    return SimpleNamespace(
        cluster_id=1,
        representative_he="ЧћЧ™Ч©Ч•ЧЁ Ч”ЧћЧ©Ч•Ч¤Чў",
        representative_lemma="ЧћЧ™Ч©Ч•ЧЁ ЧћЧ©Ч•Ч¤Чў",
        freq_abs=4,
        doc_freq=2,
        curation_status="approved",
        pinned_translation="",
        aliases=[],
        is_stopword=False,
        in_user_dictionary_count=1,
        last_grade="easy",
        audio_status="ready",
        study_tooltip="tooltip",
        pronunciation_text="ЧћЦґЧ™Ч©ЧЃЧ•Ц№ЧЁ Ч”Ц·ЧћЦјЦ°Ч©ЧЃЦ»Ч¤ЦјЦёЧў",
        pronunciation_source="auto_phonikud",
        pronunciation_confidence=0.8,
        pronunciation_qc="auto_fixed",
    )


def _ud_item() -> SimpleNamespace:
    return SimpleNamespace(
        kind="lemma",
        src_text="Ч”ЧЄЧ—Ч Ч” Ч”Ч‘ЧђЧ”",
        translation="",
        translation_tier="missing",
        audio_status="ready",
        is_noise=0,
        computed_study_state="learning",
        origin_kind="manual",
        status_tooltip="status tooltip",
        last_grade="good",
        last_graded_at="2026-02-20T00:00:00Z",
        study_review_count=2,
        study_due_at="2026-02-21T00:00:00Z",
        is_suspended=0,
        origin_project_id=7,
        origin_project_name="Project 7",
        pronunciation_text="Ч”Ц·ЧЄЦ·ЦјЧ—ЦІЧ ЦёЧ” Ч”Ц·Ч‘ЦёЦјЧђЦёЧ”",
        pronunciation_source="manual",
        pronunciation_confidence=1.0,
        pronunciation_qc="ok",
    )


def test_dictionary_model_has_niqqud_column():
    model = LemmaTableModel([_lemma()])
    assert model.headerData(10, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Niqqud"
    assert model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole) == "Ч”Ц·ЧЄЦ·ЦјЧ—ЦІЧ ЦёЧ” Ч”Ц·Ч‘ЦёЦјЧђЦёЧ”"
    tooltip = model.data(model.index(0, 10), Qt.ItemDataRole.ToolTipRole)
    assert "Source: manual" in tooltip


def test_terms_model_has_niqqud_column():
    model = TermClusterTableModel([_cluster()])
    assert model.headerData(17, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Niqqud"
    assert model.data(model.index(0, 17), Qt.ItemDataRole.DisplayRole) == "ЧћЦґЧ™Ч©ЧЃЧ•Ц№ЧЁ Ч”Ц·ЧћЦјЦ°Ч©ЧЃЦ»Ч¤ЦјЦёЧў"


def test_tm_model_has_niqqud_column():
    model = TranslationManagementTableModel([_tm_entry()])
    assert model.headerData(12, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Niqqud"
    assert model.data(model.index(0, 12), Qt.ItemDataRole.DisplayRole) == "Ч”Ц·ЧЄЦ·ЦјЧ—ЦІЧ ЦёЧ” Ч”Ц·Ч‘ЦёЦјЧђЦёЧ”"


def test_term_card_model_has_niqqud_column():
    model = TermCardTableModel([_term_card()])
    assert model.headerData(10, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Niqqud"
    assert model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole) == "ЧћЦґЧ™Ч©ЧЃЧ•Ц№ЧЁ Ч”Ц·ЧћЦјЦ°Ч©ЧЃЦ»Ч¤ЦјЦёЧў"


def test_user_dictionary_model_has_niqqud_column():
    model = UserDictionaryItemsTableModel([_ud_item()])
    assert model.headerData(10, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Niqqud"
    assert model.data(model.index(0, 10), Qt.ItemDataRole.DisplayRole) == "Ч”Ц·ЧЄЦ·ЦјЧ—ЦІЧ ЦёЧ” Ч”Ц·Ч‘ЦёЦјЧђЦёЧ”"


def test_user_dictionary_model_has_project_metadata_columns():
    model = UserDictionaryItemsTableModel([_ud_item()])
    assert model.headerData(7, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Project ID"
    assert model.headerData(8, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Project"
    assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "7"
    assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == "Project 7"

