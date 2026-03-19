from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import QItemSelectionModel, QPoint
from PyQt6.QtWidgets import QListWidget, QTableView

from app.services.ingest_service import IngestService
from app.ui.documents_view import DeleteDocumentsConfirmDialog, DocumentsView


def _make_doc(doc_id: int, file_name: str, *, status: str = "imported") -> SimpleNamespace:
    return SimpleNamespace(
        doc_id=int(doc_id),
        file_name=file_name,
        file_size_bytes=1024,
        status=status,
        sentence_count=0,
        token_count=0,
        imported_at="2026-03-08T00:00:00Z",
        file_path=f"/tmp/{file_name}",
        tag="",
        link_url="",
        level="",
        topic="",
    )


def _make_view(monkeypatch, qtbot) -> DocumentsView:
    monkeypatch.setattr(
        "app.ui.documents_view.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.services.ingest_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(DocumentsView, "load_corpus", lambda self: setattr(self, "corpus_id", 1))
    monkeypatch.setattr(DocumentsView, "load_documents", lambda self: None)
    monkeypatch.setattr(DocumentsView, "start_nlp_engine_readiness_check", lambda self: None)
    view = DocumentsView(project_id=1)
    qtbot.addWidget(view)
    return view


def test_documents_view_uses_extended_row_selection(monkeypatch, qtbot):
    view = _make_view(monkeypatch, qtbot)

    assert view.docs_table.selectionBehavior() == QTableView.SelectionBehavior.SelectRows
    assert view.docs_table.selectionMode() == QTableView.SelectionMode.ExtendedSelection


def test_delete_button_uses_all_selected_documents(monkeypatch, qtbot):
    view = _make_view(monkeypatch, qtbot)
    view._render_documents_rows(
        [
            _make_doc(10, "alpha.txt"),
            _make_doc(20, "beta.txt"),
            _make_doc(30, "gamma.txt"),
        ]
    )

    captured = []
    monkeypatch.setattr(view, "_confirm_delete_documents", lambda names: True)
    monkeypatch.setattr(
        view,
        "_start_delete_documents",
        lambda doc_ids, doc_names: captured.append((doc_ids, doc_names)),
    )

    selection_model = view.docs_table.selectionModel()
    for row in (0, 2):
        selection_model.select(
            view._docs_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )

    view.on_delete()

    assert captured == [([10, 30], ["alpha.txt", "gamma.txt"])]


def test_context_menu_exposes_delete_action(monkeypatch, qtbot):
    view = _make_view(monkeypatch, qtbot)
    view._render_documents_rows([_make_doc(10, "alpha.txt")])
    view.docs_table.selectionModel().select(
        view._docs_model.index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    menu_actions = []

    class _FakeSignal:
        def connect(self, _callback):
            return None

    class _FakeAction:
        def __init__(self, text: str):
            self.text = text
            self.triggered = _FakeSignal()

        def setEnabled(self, _value):
            return None

        def setToolTip(self, _value):
            return None

    class _FakeMenu:
        def __init__(self, _parent):
            pass

        def addAction(self, text: str):
            menu_actions.append(text)
            return _FakeAction(text)

        def addSeparator(self):
            return None

        def exec(self, _pos):
            return None

    monkeypatch.setattr("app.ui.documents_view.QMenu", _FakeMenu)
    monkeypatch.setattr(view, "_sync_context_selection", lambda _position: None)

    view.show_context_menu(QPoint(0, 0))

    assert "Delete" in menu_actions


def test_delete_confirmation_dialog_lists_all_file_names(qtbot):
    dialog = DeleteDocumentsConfirmDialog(["alpha.txt", "beta.txt"])
    qtbot.addWidget(dialog)

    names_list = dialog.findChild(QListWidget)
    assert names_list is not None
    assert names_list.count() == 2
    assert [names_list.item(i).text() for i in range(names_list.count())] == [
        "alpha.txt",
        "beta.txt",
    ]


def test_ingest_bulk_delete_does_not_call_single_delete_path(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingest_service.DBService.get_instance",
        lambda: SimpleNamespace(),
    )
    ingest = IngestService()
    docs = [_make_doc(1, "alpha.txt"), _make_doc(2, "beta.txt")]

    monkeypatch.setattr(ingest, "_load_documents_for_delete", lambda session, doc_ids: docs)
    monkeypatch.setattr(
        ingest,
        "_delete_documents_atomic",
        lambda session, loaded_docs, progress_callback=None: (len(loaded_docs), 0),
    )
    monkeypatch.setattr(
        ingest,
        "delete_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("single delete path must not be used")
        ),
    )

    success_count, error_count = ingest.bulk_delete(SimpleNamespace(), [1, 2])

    assert success_count == 2
    assert error_count == 0
