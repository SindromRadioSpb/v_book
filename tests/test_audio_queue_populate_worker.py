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
