"""Tests for TM panel results label wording and project-lemma context."""

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
