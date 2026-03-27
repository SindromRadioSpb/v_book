"""Regression tests for staged NLP engine readiness in DocumentsView."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtCore import QItemSelectionModel

from app.services.nlp_runtime import NlpRuntimeStatus
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

    monkeypatch.setattr(
        worker.probe,
        "probe_stanza",
        lambda **kwargs: NlpRuntimeStatus(
            configured_engine_id="stanza",
            effective_engine_id=None,
            package_installed=False,
            model_present=False,
            pipeline_init_ok=False,
            smoke_ok=False,
            cuda_available=False,
            runtime_mode="cpu",
            fallback_used=False,
            error_code="package_missing",
            error_detail="missing",
            remediation="install",
        ),
    )
    worker.result_ready.connect(
        lambda request_id, status: events.append(
            (request_id, status.error_code, status.cuda_available)
        )
    )

    worker.run()

    assert events == [(7, "package_missing", False)]


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
    assert view.diagnose_nlp_btn.isEnabled() is True
    assert view.open_nlp_setup_btn.isEnabled() is True
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
    DocumentsView.on_nlp_engine_readiness_loaded(
        view,
        1,
        NlpRuntimeStatus(
            configured_engine_id="stanza",
            effective_engine_id="stanza",
            package_installed=True,
            model_present=True,
            pipeline_init_ok=True,
            smoke_ok=True,
            cuda_available=True,
            runtime_mode="cpu",
            fallback_used=False,
        ),
    )

    assert view._nlp_engine_check_pending is True
    assert view.process_btn.isEnabled() is False

    DocumentsView.on_nlp_engine_readiness_loaded(
        view,
        2,
        NlpRuntimeStatus(
            configured_engine_id="stanza",
            effective_engine_id=None,
            package_installed=False,
            model_present=False,
            pipeline_init_ok=False,
            smoke_ok=False,
            cuda_available=False,
            runtime_mode="cpu",
            fallback_used=False,
            error_code="package_missing",
            error_detail="missing",
            remediation="install",
        ),
    )

    assert view._nlp_engine_check_pending is False
    assert view.stanza_available is False
    assert view.cuda_available is False
    assert view.process_btn.isEnabled() is True
    assert view.reprocess_btn.isEnabled() is False
    assert "explicit confirmation" in view.nlp_engine_status_label.text()
    assert "explicit Mock fallback confirmation" in view.process_btn.toolTip()
    assert view.gpu_checkbox.isHidden() is True
    assert "External runtime reason: package_missing" in view.nlp_engine_status_label.toolTip()
    assert "Remediation: install" in view.nlp_engine_status_label.toolTip()
    assert "Recommended route: Repair the external runtime dependency" in view.nlp_engine_status_label.toolTip()
    assert "Next action: Start with Health Check" in view.nlp_engine_status_label.toolTip()
    assert "Official setup action: Install / Repair NLP Runtime" in view.nlp_engine_status_label.toolTip()


def test_documents_view_open_nlp_setup_routes_to_resources_manager(monkeypatch, qtbot):
    view = _make_view(monkeypatch, qtbot)
    events = []

    monkeypatch.setattr(
        "app.ui.resources_manager_dialog.show_resources_manager",
        lambda parent=None: events.append(parent),
    )

    view.on_open_nlp_setup()

    assert events == [view]
