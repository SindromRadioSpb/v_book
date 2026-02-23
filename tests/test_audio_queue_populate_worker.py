"""Tests for AudioQueuePopulateWorker (PATCH-04)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.workers import AudioQueuePopulateWorker


def test_worker_instantiates():
    """Worker can be created with required args."""
    w = AudioQueuePopulateWorker(kind="sentence", project_id=1)
    assert w.kind == "sentence"
    assert w.project_id == 1
    assert w.add_mode == "append"
    assert w.current_position == 0
    assert not w._cancel_requested


def test_worker_cancel_sets_flag():
    w = AudioQueuePopulateWorker(kind="lemma", project_id=2)
    w.cancel()
    assert w._cancel_requested is True


def test_worker_lemma_kind():
    w = AudioQueuePopulateWorker(kind="lemma", project_id=5, add_mode="prepend")
    assert w.kind == "lemma"
    assert w.add_mode == "prepend"


def test_worker_all_modes():
    for mode in ("append", "prepend", "after_current"):
        w = AudioQueuePopulateWorker(kind="sentence", project_id=1, add_mode=mode)
        assert w.add_mode == mode


def test_worker_doc_filter_and_search():
    w = AudioQueuePopulateWorker(
        kind="sentence",
        project_id=3,
        doc_ids=[42, 99],
        text_search="שלום",
        add_mode="append",
        current_position=7,
    )
    assert w.doc_ids == [42, 99]
    assert w.text_search == "שלום"
    assert w.current_position == 7


def test_worker_term_kind():
    w = AudioQueuePopulateWorker(kind="term", project_id=5)
    assert w.kind == "term"
    assert w.doc_ids == []


def test_worker_doc_ids_empty_list():
    w = AudioQueuePopulateWorker(kind="sentence", project_id=1, doc_ids=[])
    assert w.doc_ids == []


def test_worker_doc_ids_none():
    w = AudioQueuePopulateWorker(kind="sentence", project_id=1, doc_ids=None)
    assert w.doc_ids == []


def test_worker_signals_defined():
    """Worker has all V3-compatible signals."""
    w = AudioQueuePopulateWorker(kind="sentence", project_id=1)
    assert hasattr(w, "progress")
    assert hasattr(w, "stats_updated")
    assert hasattr(w, "row_translated")
    assert hasattr(w, "stage_updated")
    assert hasattr(w, "finished")
    assert hasattr(w, "error")


def test_worker_empty_ids_finishes_immediately(tmp_path, monkeypatch):
    """Worker finishes immediately when no IDs are found."""
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication.instance() or QApplication(sys.argv)

    w = AudioQueuePopulateWorker(kind="sentence", project_id=999)

    finished_payloads = []
    w.finished.connect(finished_payloads.append)

    # Monkeypatch DBService and SentencesWorkspaceService to return 0 IDs
    import app.services.db_service as db_mod

    class _FakeResult:
        def all(self):
            return []

    class _FakeSession:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def execute(self, *a, **kw):
            return _FakeResult()

    class _FakeDB:
        def get_session(self):
            return _FakeSession()

    monkeypatch.setattr(db_mod.DBService, "get_instance", staticmethod(lambda: _FakeDB()))

    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    w.finished.connect(lambda _: loop.quit())
    w.error.connect(lambda _: loop.quit())
    w.start()
    QTimer.singleShot(3000, loop.quit)  # safety timeout
    loop.exec()

    assert finished_payloads, "finished signal not emitted"
    assert finished_payloads[0]["added"] == 0
    assert finished_payloads[0]["total"] == 0
    assert "new_item_ids" in finished_payloads[0], "new_item_ids must be present in finished payload"
    assert finished_payloads[0]["new_item_ids"] == []


# -- _resolve_audio_assets: fills audio_asset_id for matching norms ----------


def test_resolve_audio_assets_fills_asset_id():
    """_resolve_audio_assets sets audio_asset_id + audio_status for matching specs."""
    from unittest.mock import MagicMock, patch
    from app.ui.workers import AudioQueuePopulateWorker
    from app.services.audio_queue_service import AudioItemSpec

    w = AudioQueuePopulateWorker(kind="lemma", project_id=1)
    specs = [
        AudioItemSpec(kind="lemma", source_id=10, snapshot_hebrew="שלום", audio_status="unknown"),
        AudioItemSpec(kind="lemma", source_id=11, snapshot_hebrew="עולם", audio_status="unknown"),
    ]

    # normalize_for_tm: "שלום" → norm "n_shalom", "עולם" → "n_olam"
    def fake_ntm(lang, text, kind):
        result = MagicMock()
        result.norm = f"n_{text}"
        return result

    mock_session = MagicMock()
    # Only "n_שלום" has a ready asset in DB
    mock_session.execute.return_value.all.return_value = [("n_שלום", 42)]

    with patch("app.domain.normalization.normalizer.normalize_for_tm", side_effect=fake_ntm):
        w._resolve_audio_assets(mock_session, specs)

    assert specs[0].audio_asset_id == 42
    assert specs[0].audio_status == "ready"
    assert specs[1].audio_asset_id is None
    assert specs[1].audio_status == "unknown"


def test_resolve_audio_assets_skips_already_set():
    """_resolve_audio_assets skips specs that already have audio_asset_id."""
    from unittest.mock import MagicMock, patch
    from app.ui.workers import AudioQueuePopulateWorker
    from app.services.audio_queue_service import AudioItemSpec

    w = AudioQueuePopulateWorker(kind="lemma", project_id=1)
    specs = [
        AudioItemSpec(kind="lemma", source_id=10, snapshot_hebrew="שלום",
                      audio_asset_id=99, audio_status="ready"),
    ]

    mock_session = MagicMock()
    # Even if DB returns a row, the spec already has asset_id set — should not overwrite
    mock_session.execute.return_value.all.return_value = [("n_שלום", 777)]

    def fake_ntm(lang, text, kind):
        result = MagicMock()
        result.norm = f"n_{text}"
        return result

    with patch("app.domain.normalization.normalizer.normalize_for_tm", side_effect=fake_ntm):
        w._resolve_audio_assets(mock_session, specs)

    # spec already had asset_id=99; must not be overwritten to 777
    assert specs[0].audio_asset_id == 99


def test_resolve_audio_assets_nonfatal_on_exception():
    """_resolve_audio_assets silently ignores exceptions (non-fatal)."""
    from unittest.mock import MagicMock
    from app.ui.workers import AudioQueuePopulateWorker
    from app.services.audio_queue_service import AudioItemSpec

    w = AudioQueuePopulateWorker(kind="lemma", project_id=1)
    specs = [
        AudioItemSpec(kind="lemma", source_id=10, snapshot_hebrew="שלום", audio_status="unknown"),
    ]

    mock_session = MagicMock()
    mock_session.execute.side_effect = RuntimeError("DB error")

    # Should not raise
    w._resolve_audio_assets(mock_session, specs)

    # Spec unchanged
    assert specs[0].audio_asset_id is None
    assert specs[0].audio_status == "unknown"


# -- _build_sentence_specs: source label uses document filename ---------------


def test_build_sentence_specs_source_label_uses_doc_filename():
    """_build_sentence_specs stores document filename as snapshot_source_label."""
    from unittest.mock import MagicMock, patch
    from app.ui.workers import AudioQueuePopulateWorker

    w = AudioQueuePopulateWorker(kind="sentence", project_id=1)

    mock_session = MagicMock()

    # DocumentSentence query: sentence_id=10, text="שלום", doc_id=5
    # SourceDocument query: doc_id=5, file_name="chapter01.docx"
    call_count = [0]

    def fake_execute(stmt, *args, **kwargs):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:  # DocumentSentence query
            result.all.return_value = [(10, "שלום", 5)]
        elif call_count[0] == 2:  # SourceDocument.file_name query
            result.all.return_value = [(5, "chapter01.docx")]
        else:
            result.all.return_value = []
        return result

    mock_session.execute.side_effect = fake_execute

    # Patch out SentencePronunciationService and SentencesWorkspaceService
    with patch("app.services.sentence_pronunciation_service.SentencePronunciationService"), \
         patch("app.services.sentences_workspace_service.SentencesWorkspaceService"):
        specs = w._build_sentence_specs(mock_session, [10])

    assert len(specs) == 1
    assert specs[0].snapshot_source_label == "chapter01.docx"


def test_build_sentence_specs_source_label_fallback_on_missing_doc():
    """Falls back to 'sentence:{id}' when doc filename is unavailable."""
    from unittest.mock import MagicMock, patch
    from app.ui.workers import AudioQueuePopulateWorker

    w = AudioQueuePopulateWorker(kind="sentence", project_id=1)
    mock_session = MagicMock()

    call_count = [0]

    def fake_execute(stmt, *args, **kwargs):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:  # DocumentSentence: sentence_id=99, doc_id=None
            result.all.return_value = [(99, "בית", None)]
        else:
            result.all.return_value = []
        return result

    mock_session.execute.side_effect = fake_execute

    with patch("app.services.sentence_pronunciation_service.SentencePronunciationService"), \
         patch("app.services.sentences_workspace_service.SentencesWorkspaceService"):
        specs = w._build_sentence_specs(mock_session, [99])

    assert specs[0].snapshot_source_label == "sentence:99"


# -- _build_lemma_specs: enriched with translation + niqqud ------------------


def test_build_lemma_specs_source_label_is_dictionary():
    """_build_lemma_specs uses 'Dictionary' as snapshot_source_label."""
    from unittest.mock import MagicMock, patch
    from app.ui.workers import AudioQueuePopulateWorker

    w = AudioQueuePopulateWorker(kind="lemma", project_id=1)
    mock_session = MagicMock()

    def fake_execute(stmt, *args, **kwargs):
        result = MagicMock()
        result.all.return_value = [(1, "שלום")]  # Lemma row
        return result

    mock_session.execute.side_effect = fake_execute

    with patch("app.domain.normalization.normalizer.normalize_for_tm") as ntm, \
         patch("app.services.pronunciation_service.PronunciationService"), \
         patch("app.infra.sa_models.TMEntry"):
        ntm.return_value.norm = "shalom"
        specs = w._build_lemma_specs(mock_session, [1])

    assert len(specs) == 1
    assert specs[0].snapshot_source_label == "Dictionary"


def test_build_lemma_specs_niqqud_and_translation_populated():
    """_build_lemma_specs populates niqqud and translation when DB has them."""
    from unittest.mock import MagicMock, patch
    from app.ui.workers import AudioQueuePopulateWorker
    from app.services.pronunciation_service import PronunciationService

    w = AudioQueuePopulateWorker(kind="lemma", project_id=1)
    mock_session = MagicMock()

    # Lemma query returns one row
    lemma_execute_result = MagicMock()
    lemma_execute_result.all.return_value = [(10, "שָׁלוֹם")]

    # TMEntry query returns one row
    tm_execute_result = MagicMock()
    tm_execute_result.all.return_value = [("shalom_norm", "peace")]

    execute_calls = [lemma_execute_result, tm_execute_result]
    mock_session.execute.side_effect = lambda *a, **kw: execute_calls.pop(0) if execute_calls else MagicMock()

    # PronunciationService.bulk_lookup returns niqqud for "shalom_norm"
    mock_niqqud_dto = MagicMock()
    mock_niqqud_dto.niqqud_text = "שָׁלוֹם"
    mock_pron_svc = MagicMock()
    mock_pron_svc.return_value.bulk_lookup.return_value = {"shalom_norm": mock_niqqud_dto}

    def fake_ntm(lang, text, kind):
        r = MagicMock()
        r.norm = "shalom_norm"
        return r

    with patch("app.domain.normalization.normalizer.normalize_for_tm", side_effect=fake_ntm), \
         patch("app.services.pronunciation_service.PronunciationService", mock_pron_svc):
        specs = w._build_lemma_specs(mock_session, [10])

    assert len(specs) == 1
    assert specs[0].snapshot_niqqud == "שָׁלוֹם"
    assert specs[0].snapshot_translation == "peace"


# -- _build_term_specs: source label is "Terms" --------------------------------


def test_build_term_specs_source_label_is_terms():
    """_build_term_specs uses 'Terms' as snapshot_source_label."""
    from unittest.mock import MagicMock
    from app.ui.workers import AudioQueuePopulateWorker

    w = AudioQueuePopulateWorker(kind="term", project_id=1)
    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = [(5, "שלום", "peace")]

    specs = w._build_term_specs(mock_session, [5])

    assert len(specs) == 1
    assert specs[0].snapshot_source_label == "Terms"
