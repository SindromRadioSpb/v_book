"""Regression tests for staged NLP processing progress wiring."""

from __future__ import annotations

from app.ui.documents_view import DocumentsView
from app.ui.workers import ProcessWorker
from app.services.operations_center import OperationsCenterBusyError, OperationEntry


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
        self.maximum = None
        self.value = None

    def setVisible(self, value):
        self.visible = value

    def setMaximum(self, value):
        self.maximum = value

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


class _FakeSignal:
    def __init__(self):
        self.calls = 0

    def emit(self):
        self.calls += 1


def test_process_worker_emits_structured_state_and_finished_report(monkeypatch):
    progress_events = []
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

    def _fake_batch(self, session, doc_ids, **kwargs):
        assert session is not None
        assert doc_ids == [11, 12]
        kwargs["progress_callback"](1, 2, "doc_1.txt")
        kwargs["state_callback"](
            {
                "phase": "processing",
                "run_id": 500,
                "status": "running",
                "stage": "processing",
                "docs_total": 2,
                "docs_processed": 1,
                "docs_failed": 0,
                "chunks_total": 2,
                "chunks_completed": 1,
                "last_doc_id": 11,
                "message": "Processed doc_1.txt",
            }
        )
        kwargs["state_callback"](
            {
                "phase": "completed",
                "run_id": 500,
                "status": "ok",
                "stage": "completed",
                "docs_total": 2,
                "docs_processed": 2,
                "docs_failed": 0,
                "chunks_total": 2,
                "chunks_completed": 2,
                "last_doc_id": 12,
                "message": "NLP batch run completed",
            }
        )
        return 2, 0

    from app.services.db_service import DBService
    from app.services.operations_center import OperationsCenter
    from app.services.process_service import ProcessService

    monkeypatch.setattr(DBService, "get_instance", classmethod(lambda cls: _FakeDBService()))
    monkeypatch.setattr(OperationsCenter, "instance", classmethod(lambda cls: _FakeOpsCenter()))
    monkeypatch.setattr(ProcessService, "process_documents_batch", _fake_batch)

    worker = ProcessWorker(doc_ids=[11, 12], use_mock=True)
    worker.progress.connect(
        lambda current, total, doc_name: progress_events.append((current, total, doc_name))
    )
    worker.state_changed.connect(states.append)
    worker.finished.connect(finished_reports.append)

    worker.run()

    assert progress_events == [(1, 2, "doc_1.txt")]
    assert states[0]["run_id"] == 500
    assert finished_reports[0]["success_count"] == 2
    assert finished_reports[0]["cancelled"] is False


def test_process_worker_reports_busy_when_global_heavy_slot_taken(monkeypatch):
    errors = []

    class _FakeOpsCenter:
        def register(self, *_args, **_kwargs):
            raise OperationsCenterBusyError(
                "nlp_process",
                [OperationEntry(op_id="op-1", name="Import bundle", category="project_import")],
            )

        def unregister(self, _op_id):
            return None

    from app.services.operations_center import OperationsCenter

    monkeypatch.setattr(OperationsCenter, "instance", classmethod(lambda cls: _FakeOpsCenter()))

    worker = ProcessWorker(doc_ids=[11, 12], use_mock=True)
    worker.error.connect(errors.append)
    worker.run()

    assert errors
    assert "NLP Process" in errors[0]
    assert "Import bundle" in errors[0]


def test_documents_process_state_updates_progress_ui():
    view = DocumentsView.__new__(DocumentsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.process_progress_dialog = _FakeDialog()

    DocumentsView.on_process_state(
        view,
        {
            "message": "Processed doc_2.txt",
            "stage": "processing",
            "docs_processed": 2,
            "docs_failed": 1,
            "docs_total": 5,
            "chunks_completed": 1,
            "chunks_total": 3,
            "run_id": 91,
        },
    )

    assert view.progress_bar.maximum == 5
    assert view.progress_bar.value == 3
    assert view.progress_bar.visible is True
    assert view.status_label.text == "Processed doc_2.txt"
    assert view.process_progress_dialog.states[0]["run_id"] == 91


def test_documents_process_progress_appends_dialog_activity():
    view = DocumentsView.__new__(DocumentsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.process_progress_dialog = _FakeDialog()

    DocumentsView.on_process_progress(view, 1, 2, "doc_1.txt")

    assert view.progress_bar.maximum == 2
    assert view.progress_bar.value == 1
    assert view.status_label.text == "Starting 1/2: doc_1.txt"
    assert view.process_progress_dialog.messages == ["Starting 1/2: doc_1.txt"]


def test_documents_process_finished_cancelled_cleans_dialog_and_refreshes(monkeypatch):
    view = DocumentsView.__new__(DocumentsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.process_btn = _FakeToggle()
    view.reprocess_btn = _FakeToggle()
    view.delete_btn = _FakeToggle()
    view.process_progress_dialog = _FakeDialog()
    view.process_worker = _FakeWorker(running=False)
    view._process_worker_active = True
    view.on_selection_changed = lambda: None
    view.processing_completed = _FakeSignal()

    refreshed = {"count": 0}
    info_calls = []
    view.load_documents = lambda: refreshed.__setitem__("count", refreshed["count"] + 1)
    monkeypatch.setattr("app.ui.documents_view.show_info", lambda *args: info_calls.append(args))

    DocumentsView.on_process_finished(
        view,
        {
            "success_count": 1,
            "error_count": 0,
            "cancelled": True,
        },
    )

    assert view.progress_bar.visible is False
    assert view.status_label.text == "Processing cancelled: 1 succeeded, 0 failed"
    assert view.process_progress_dialog is None
    assert view.process_worker is None
    assert refreshed["count"] == 1
    assert info_calls


def test_documents_stop_process_worker_uses_cancel_only():
    view = DocumentsView.__new__(DocumentsView)
    view.process_progress_dialog = _FakeDialog()
    view.process_worker = _FakeWorker(running=True, wait_result=False)

    DocumentsView._stop_process_worker(view)

    assert view.process_worker.cancel_called is True
    assert view.process_worker.wait_calls == [100]
    assert "cooperative cancellation" in view.process_progress_dialog.messages[0]
