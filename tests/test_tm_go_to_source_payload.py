from __future__ import annotations

from types import SimpleNamespace

from app.ui.translation_management_panel import TranslationManagementPanel


def _entry(**kwargs):
    base = {
        "project_id": 7,
        "kind": "lemma",
        "lemma_id": None,
        "cluster_id": None,
        "source_ref": None,
        "src_text": "",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_build_source_payload_for_lemma():
    payload = TranslationManagementPanel._build_source_payload_for_entry(
        _entry(kind="lemma", lemma_id=42)
    )
    assert payload == {"kind": "lemma", "source_id": 42, "project_id": 7}


def test_build_source_payload_for_term_cluster():
    payload = TranslationManagementPanel._build_source_payload_for_entry(
        _entry(kind="term_cluster", cluster_id=314)
    )
    assert payload == {"kind": "term_cluster", "source_id": 314, "project_id": 7}


def test_build_source_payload_for_surface_sentence_ref():
    payload = TranslationManagementPanel._build_source_payload_for_entry(
        _entry(kind="surface", source_ref="sentence:9001", src_text="sentence text")
    )
    assert payload == {
        "kind": "sentence",
        "project_id": 7,
        "source_id": 9001,
        "source_text": "sentence text",
    }


def test_build_source_payload_for_surface_with_text_only():
    payload = TranslationManagementPanel._build_source_payload_for_entry(
        _entry(kind="surface", source_ref="batch_translate", src_text="sentence text")
    )
    assert payload == {"kind": "sentence", "project_id": 7, "source_text": "sentence text"}


def test_build_source_payload_returns_none_for_global_rows():
    payload = TranslationManagementPanel._build_source_payload_for_entry(
        _entry(project_id=None, kind="lemma", lemma_id=42)
    )
    assert payload is None
