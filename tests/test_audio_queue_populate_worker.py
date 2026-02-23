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
        doc_id_filter=42,
        text_search="שלום",
        add_mode="append",
        current_position=7,
    )
    assert w.doc_id_filter == 42
    assert w.text_search == "שלום"
    assert w.current_position == 7


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

    class _FakeSession:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def execute(self, *a, **kw):
            return iter([])

    class _FakeDB:
        def get_session(self):
            return _FakeSession()

    monkeypatch.setattr(db_mod.DBService, "get_instance", staticmethod(lambda: _FakeDB()))

    import app.services.sentences_workspace_service as sws_mod

    class _FakeSWS:
        def get_all_filtered_sentence_ids(self, session, project_id, **kw):
            return []

    monkeypatch.setattr(
        sws_mod,
        "SentencesWorkspaceService",
        lambda: _FakeSWS(),
    )

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
