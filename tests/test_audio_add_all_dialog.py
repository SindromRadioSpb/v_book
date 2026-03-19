from __future__ import annotations

from types import SimpleNamespace

from app.ui.widgets.audio_player_panel import AddAllToQueueDialog


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self._callbacks):
            callback(*args)


class _FakeSession:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDBService:
    def get_read_session(self):
        return _FakeSession()


class _FakeProjectService:
    def list_projects(self, session):
        return [SimpleNamespace(project_id=7, name="Project Seven")]


def _install_dialog_env(monkeypatch):
    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance",
        lambda: _FakeDBService(),
    )
    monkeypatch.setattr(
        "app.services.project_service.ProjectService",
        lambda: _FakeProjectService(),
    )
    monkeypatch.setattr(
        AddAllToQueueDialog,
        "_query_project_estimate",
        lambda self, project_id, kind: {"sentence": 1234, "lemma": 55, "term": 9}[kind],
    )


def test_add_all_dialog_init_defers_document_loading(monkeypatch, qtbot):
    _install_dialog_env(monkeypatch)

    class _FakeWorker:
        created = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.rows_loaded = _Signal()
            self.count_loaded = _Signal()
            self.error = _Signal()
            self.status = _Signal()
            _FakeWorker.created.append(self)

        def isRunning(self):
            return False

        def cancel(self):
            return None

        def wait(self, _ms):
            return True

        def start(self):
            raise AssertionError("worker must not start on blank init")

    monkeypatch.setattr("app.ui.widgets.audio_player_panel.ProjectDocumentsPageWorker", _FakeWorker)

    dlg = AddAllToQueueDialog()
    qtbot.addWidget(dlg)

    assert _FakeWorker.created == []
    assert dlg.doc_list.count() == 0
    assert dlg.doc_sel_label.text() == "All project documents (none selected)"
    assert dlg.doc_status_label.text() == "Type to search project documents for specific selection."
    assert dlg.estimate_label.text() == "~1,234 sentences from all documents"


def test_add_all_dialog_search_selection_persists_across_queries(monkeypatch, qtbot):
    _install_dialog_env(monkeypatch)

    class _FakeWorker:
        created = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.rows_loaded = _Signal()
            self.count_loaded = _Signal()
            self.error = _Signal()
            self.status = _Signal()
            _FakeWorker.created.append(self)

        def isRunning(self):
            return False

        def cancel(self):
            return None

        def wait(self, _ms):
            return True

        def start(self):
            request_id = int(self.kwargs["request_id"])
            query = self.kwargs["search_query"]
            rows = {
                "alpha": [
                    SimpleNamespace(
                        doc_id=11, file_name="alpha.txt", sentence_count=5, level="aleph"
                    ),
                ],
                "beta": [
                    SimpleNamespace(doc_id=22, file_name="beta.txt", sentence_count=7, level="bet"),
                ],
            }[query]
            self.status.emit(request_id, "Loading documents...")
            self.rows_loaded.emit(request_id, rows)
            self.count_loaded.emit(request_id, len(rows))

    monkeypatch.setattr("app.ui.widgets.audio_player_panel.ProjectDocumentsPageWorker", _FakeWorker)

    dlg = AddAllToQueueDialog()
    qtbot.addWidget(dlg)

    dlg.doc_search.setText("alpha")
    dlg._reload_doc_matches()

    assert _FakeWorker.created[-1].kwargs["status_filter"] == "processed"
    assert _FakeWorker.created[-1].kwargs["include_frequent_tags"] is False
    assert dlg.doc_list.count() == 1

    dlg.doc_list.item(0).setSelected(True)
    assert dlg.selected_doc_ids() == [11]
    assert dlg.estimate_label.text() == "~5 sentences from 1 selected document(s)"

    dlg.doc_search.setText("beta")
    dlg._reload_doc_matches()
    assert dlg.doc_list.count() == 1
    dlg.doc_list.item(0).setSelected(True)

    assert dlg.selected_doc_ids() == [11, 22]
    assert dlg.estimate_label.text() == "~12 sentences from 2 selected document(s)"

    dlg._clear_doc_selection()
    assert dlg.selected_doc_ids() == []
    assert dlg.estimate_label.text() == "~1,234 sentences from all documents"


def test_add_all_dialog_ignores_stale_search_results(monkeypatch, qtbot):
    _install_dialog_env(monkeypatch)
    dlg = AddAllToQueueDialog()
    qtbot.addWidget(dlg)

    stale_row = SimpleNamespace(doc_id=1, file_name="stale.txt", sentence_count=1, level=None)
    fresh_row = SimpleNamespace(doc_id=2, file_name="fresh.txt", sentence_count=2, level=None)

    dlg._doc_request_id = 2

    dlg._on_doc_rows_loaded(1, [stale_row])
    assert dlg.doc_list.count() == 0

    dlg._on_doc_rows_loaded(2, [fresh_row])
    assert dlg.doc_list.count() == 1
    assert dlg.doc_list.item(0).data(dlg._DOC_ROLE_ID) == 2

    dlg._on_doc_count_loaded(1, 99)
    assert dlg._doc_total_matches == 0

    dlg._on_doc_count_loaded(2, 1)
    assert dlg._doc_total_matches == 1
    assert dlg.doc_status_label.text() == "Showing 1 matching processed documents."
