"""Regression tests for staged term extraction progress wiring."""

from __future__ import annotations

from types import SimpleNamespace

from app.ui.terms_view import TermsView
from app.ui.workers import ProjectTermExtractionWorker


class _FakeToggle:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = value


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = value


class _FakeProgressBar:
    def __init__(self):
        self.visible = None
        self.range = None
        self.value = None

    def setVisible(self, value):
        self.visible = value

    def setRange(self, minimum, maximum):
        self.range = (minimum, maximum)

    def setValue(self, value):
        self.value = value


class _FakeDialog:
    def __init__(self):
        self.states = []
        self.messages = []
        self.completed = False
        self.cancelled = False
        self.failed = None
        self.accepted = False
        self.rejected = False
        self.deleted = False

    def append_activity(self, message):
        self.messages.append(message)

    def update_state(self, state):
        self.states.append(state)

    def set_completed(self):
        self.completed = True

    def set_cancelled(self):
        self.cancelled = True

    def set_failed(self, message):
        self.failed = message

    def accept(self):
        self.accepted = True

    def reject(self):
        self.rejected = True

    def deleteLater(self):
        self.deleted = True


class _FakeWorker:
    def __init__(self, running=True, wait_result=True):
        self._running = running
        self._wait_result = wait_result
        self.cancel_called = False
        self.deleted = False
        self.wait_calls = []

    def isRunning(self):
        return self._running

    def cancel(self):
        self.cancel_called = True

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return self._wait_result

    def deleteLater(self):
        self.deleted = True


def test_project_term_extraction_worker_emits_structured_state(monkeypatch):
    progress_messages = []
    states = []
    finished_reports = []

    class _FakeSessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeDBService:
        def get_session(self):
            return _FakeSessionContext()

    class _FakeOpsCenter:
        def register(self, *_args, **_kwargs):
            return "op-1"

        def unregister(self, _op_id):
            return None

    def _fake_extract(self, session, project_id, **kwargs):
        assert project_id == 11
        assert session is not None
        kwargs["progress_callback"]("Collecting batch 1/3")
        kwargs["state_callback"](
            {
                "message": "Collecting batch 1/3",
                "stage": "Collecting batch 1/3",
                "phase": "collect",
                "run_id": 77,
                "docs_processed": 10,
                "docs_total": 30,
                "chunks_completed": 1,
                "chunks_total": 3,
                "last_doc_id": 100,
            }
        )
        return SimpleNamespace(success=True, cancelled=False)

    from app.services.db_service import DBService
    from app.services.operations_center import OperationsCenter
    from app.services.term_extraction_service import TermExtractionService

    monkeypatch.setattr(DBService, "get_instance", classmethod(lambda cls: _FakeDBService()))
    monkeypatch.setattr(OperationsCenter, "instance", classmethod(lambda cls: _FakeOpsCenter()))
    monkeypatch.setattr(TermExtractionService, "extract_terms_for_project", _fake_extract)

    worker = ProjectTermExtractionWorker(project_id=11)
    worker.progress.connect(progress_messages.append)
    worker.state_changed.connect(states.append)
    worker.finished.connect(finished_reports.append)

    worker.run()

    assert progress_messages == ["Collecting batch 1/3"]
    assert states[0]["run_id"] == 77
    assert states[0]["docs_processed"] == 10
    assert len(finished_reports) == 1
    assert finished_reports[0].success is True


def test_terms_extract_state_updates_progress_ui():
    view = TermsView.__new__(TermsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.extract_progress_dialog = _FakeDialog()

    TermsView.on_extract_state(
        view,
        {
            "message": "Collecting batch 2/4",
            "stage": "Collecting batch 2/4",
            "docs_processed": 25,
            "docs_total": 100,
            "chunks_completed": 2,
            "chunks_total": 4,
            "run_id": 15,
        },
    )

    assert view.progress_bar.visible is True
    assert view.progress_bar.range == (0, 100)
    assert view.progress_bar.value == 25
    assert view.status_label.text == "Collecting batch 2/4"
    assert view.extract_progress_dialog.states[0]["run_id"] == 15


def test_terms_extract_finished_success_cleans_dialog_and_refreshes(monkeypatch):
    view = TermsView.__new__(TermsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.extract_btn = _FakeToggle()
    view.refresh_btn = _FakeToggle()
    view.extract_progress_dialog = _FakeDialog()
    view.extract_worker = _FakeWorker(running=False)
    refreshed = {"count": 0}
    info_calls = []
    view.perform_search = lambda: refreshed.__setitem__("count", refreshed["count"] + 1)
    monkeypatch.setattr("app.ui.terms_view.show_info", lambda *args: info_calls.append(args))

    report = SimpleNamespace(
        success=True,
        cancelled=False,
        ngrams_extracted=12,
        np_chunks_extracted=3,
        clusters_created=4,
    )

    TermsView.on_extract_finished(view, report)

    assert view.progress_bar.visible is False
    assert view.extract_btn.enabled is True
    assert view.refresh_btn.enabled is True
    assert view.status_label.text == "Extraction complete"
    assert refreshed["count"] == 1
    assert info_calls
    assert view.extract_worker is None


def test_terms_extract_finished_cancelled_marks_dialog(monkeypatch):
    view = TermsView.__new__(TermsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.extract_btn = _FakeToggle()
    view.refresh_btn = _FakeToggle()
    dialog = _FakeDialog()
    view.extract_progress_dialog = dialog
    view.extract_worker = _FakeWorker(running=False)
    info_calls = []
    view.perform_search = lambda: None
    monkeypatch.setattr("app.ui.terms_view.show_info", lambda *args: info_calls.append(args))

    report = SimpleNamespace(
        success=False,
        cancelled=True,
        docs_processed=50,
        docs_total=120,
        error_message="Cancelled by user",
    )

    TermsView.on_extract_finished(view, report)

    assert dialog.cancelled is True
    assert dialog.accepted is True
    assert view.status_label.text == "Extraction cancelled"
    assert info_calls
    assert view.extract_worker is None


def test_terms_stop_extract_worker_uses_cancel_only():
    view = TermsView.__new__(TermsView)
    view.extract_progress_dialog = _FakeDialog()
    view.extract_worker = _FakeWorker(running=True, wait_result=False)

    TermsView._stop_extract_worker(view)

    assert view.extract_worker.cancel_called is True
    assert view.extract_worker.wait_calls == [100]
    assert "View is closing" in view.extract_progress_dialog.messages[0]
