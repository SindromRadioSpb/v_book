"""Tests for TM panel results label wording and project-lemma context."""

from types import SimpleNamespace

from app.ui.workers import TMSearchWorker
from app.ui.translation_management_panel import TranslationManagementPanel


def _panel_without_initial_search(monkeypatch, project_id=1):
    monkeypatch.setattr(TranslationManagementPanel, "load_initial_data", lambda self: None)
    monkeypatch.setattr(TranslationManagementPanel, "perform_search", lambda self: None)
    return TranslationManagementPanel(project_id=project_id)


def test_tm_results_label_uses_tm_entries_wording(monkeypatch, qtbot):
    panel = _panel_without_initial_search(monkeypatch, project_id=77)
    qtbot.addWidget(panel)

    panel.selected_kinds = None
    text = panel._build_results_label(page_count=10, total_count=120)

    assert text == "TM entries: 10 of 120"


def test_tm_results_label_shows_project_lemma_context(monkeypatch, qtbot):
    panel = _panel_without_initial_search(monkeypatch, project_id=77)
    qtbot.addWidget(panel)

    panel.scope_mode = "current_project"
    panel.selected_project_ids = [77]
    panel.selected_kinds = ["lemma"]
    panel.search_edit.clear()
    panel.source_ref_edit.clear()
    panel.status_combo.setCurrentText("All")
    panel.origin_combo.setCurrentText("All")
    monkeypatch.setattr(panel, "_count_project_lemmas_cached", lambda: 2000)

    text = panel._build_results_label(page_count=100, total_count=464)

    assert "TM entries: 100 of 464" in text
    assert "Dictionary lemmas: 2,000" in text
    assert "Coverage: 23.200%" in text


def test_tm_results_label_shows_dictionary_lemma_total_in_project_scope(monkeypatch, qtbot):
    panel = _panel_without_initial_search(monkeypatch, project_id=77)
    qtbot.addWidget(panel)

    panel.scope_mode = "current_project"
    panel.selected_project_ids = [77]
    panel.selected_kinds = ["lemma", "term_cluster", "ngram"]
    monkeypatch.setattr(panel, "_count_project_lemmas_cached", lambda: 2071947)

    text = panel._build_results_label(page_count=100, total_count=781)

    assert "TM entries: 100 of 781" in text
    assert "Dictionary lemmas: 2,071,947" in text
    assert "Coverage:" not in text


def test_tm_search_worker_emits_page_before_count(monkeypatch, qtbot):
    class _FakeSession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeDBService:
        def get_read_session(self):
            return _FakeSession()

    class _FakeAdminService:
        def search_tm_entries(self, session, **kwargs):
            return [SimpleNamespace(tm_id=1)]

        def count_tm_entries(self, session, **kwargs):
            return 42

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance",
        lambda: _FakeDBService(),
    )
    monkeypatch.setattr(
        "app.services.translation_admin_service.TranslationAdminService",
        lambda: _FakeAdminService(),
    )

    worker = TMSearchWorker(filters={"project_ids": [1]})
    events = []
    worker.page_ready.connect(lambda entries: events.append(("page", len(entries))))
    worker.count_ready.connect(lambda total: events.append(("count", total)))
    worker.results_ready.connect(lambda entries, total: events.append(("legacy", total)))

    worker.run()

    assert events == [("page", 1), ("count", 42), ("legacy", 42)]


def test_tm_panel_request_seq_stages_rows_before_count(monkeypatch, qtbot):
    panel = _panel_without_initial_search(monkeypatch, project_id=77)
    qtbot.addWidget(panel)

    monkeypatch.setattr(panel, "on_selection_changed", lambda: None)

    entry = SimpleNamespace(
        tm_id=1,
        kind="lemma",
        src_text="alpha",
        translation="beta",
        status="approved",
        project_id=77,
        origin="user_edit",
        source_ref="ui_test",
        updated_at="2026-03-13T00:00:00Z",
        is_noise=0,
        pronunciation_text=None,
        pronunciation_source=None,
        pronunciation_confidence=None,
        pronunciation_qc=None,
        audio_status=None,
        last_review=None,
    )

    panel._active_search_seq = 2
    panel.on_search_results([entry], request_seq=1)
    assert panel.model.rowCount() == 0

    panel.on_search_results([entry], request_seq=2)
    assert panel.model.rowCount() == 1
    assert panel.total_count == 0
    assert "counting total" in panel.status_label.text().lower()
    assert "counting total" in panel.results_label.text().lower()

    panel.on_search_count_ready(99, request_seq=1)
    assert panel.total_count == 0

    panel.on_search_count_ready(99, request_seq=2)
    assert panel.total_count == 99
    assert panel.results_label.text().startswith("TM entries: 1 of 99")
