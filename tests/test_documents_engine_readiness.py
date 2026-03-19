"""Regression tests for staged NLP engine readiness in DocumentsView."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import QItemSelectionModel

from app.ui.documents_view import DocumentsView
from app.ui.workers import NLPEngineReadinessWorker


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
    monkeypatch.setattr(DocumentsView, "load_corpus", lambda self: setattr(self, "corpus_id", 1))
    monkeypatch.setattr(DocumentsView, "load_documents", lambda self: None)
    monkeypatch.setattr(DocumentsView, "start_nlp_engine_readiness_check", lambda self: None)
    view = DocumentsView(project_id=1)
    qtbot.addWidget(view)
    return view


def test_nlp_engine_readiness_worker_skips_cuda_when_stanza_missing(monkeypatch):
    worker = NLPEngineReadinessWorker(request_id=7)
    events = []

    monkeypatch.setattr(worker, "_probe_stanza_available", lambda: False)
    monkeypatch.setattr(
        worker,
        "_probe_cuda_available",
        lambda: (_ for _ in ()).throw(AssertionError("CUDA probe must be skipped")),
    )
    worker.result_ready.connect(
        lambda request_id, stanza_available, cuda_available: events.append(
            (request_id, stanza_available, cuda_available)
        )
    )

    worker.run()

    assert events == [(7, False, False)]


def test_documents_view_keeps_nlp_actions_disabled_while_engine_check_pending(monkeypatch, qtbot):
    view = _make_view(monkeypatch, qtbot)
    view._render_documents_rows([_make_doc(10, "alpha.txt", status="imported")])
    view.docs_table.selectionModel().select(
        view._docs_model.index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    view.on_selection_changed()

    assert view._nlp_engine_check_pending is True
    assert view.process_btn.isEnabled() is False
    assert view.reprocess_btn.isEnabled() is False
    assert "Checking NLP engine readiness" in view.nlp_engine_status_label.text()
    assert "Checking NLP engine readiness" in view.process_btn.toolTip()


def test_documents_view_applies_latest_nlp_engine_readiness_result(monkeypatch, qtbot):
    view = _make_view(monkeypatch, qtbot)
    view._render_documents_rows([_make_doc(10, "alpha.txt", status="imported")])
    view.docs_table.selectionModel().select(
        view._docs_model.index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    view._active_nlp_engine_request_id = 2
    DocumentsView.on_nlp_engine_readiness_loaded(view, 1, True, True)

    assert view._nlp_engine_check_pending is True
    assert view.process_btn.isEnabled() is False

    DocumentsView.on_nlp_engine_readiness_loaded(view, 2, False, False)

    assert view._nlp_engine_check_pending is False
    assert view.stanza_available is False
    assert view.cuda_available is False
    assert view.process_btn.isEnabled() is True
    assert view.reprocess_btn.isEnabled() is False
    assert "Mock engine" in view.nlp_engine_status_label.text()
    assert "Mock engine" in view.process_btn.toolTip()
    assert view.gpu_checkbox.isHidden() is True
