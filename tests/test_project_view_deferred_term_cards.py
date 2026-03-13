from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from app.ui.project_view import ProjectView
from app.ui.term_card_view import TermCardView


class _StubDocumentsView(QWidget):
    processing_completed = pyqtSignal()

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)
        self.highlight_calls = []

    def highlight_document(self, doc_id: int, sentence_id: int) -> None:
        self.highlight_calls.append((int(doc_id), int(sentence_id)))


class _StubDictionaryView(QWidget):
    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)
        self.refresh_calls = 0

    def refresh(self) -> None:
        self.refresh_calls += 1


class _StubTermsView(QWidget):
    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)


class _StubConcordanceView(QWidget):
    navigate_to_document = pyqtSignal(int, int)

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)


class _StubUserDictionariesView(QWidget):
    open_translation_management_requested = pyqtSignal()

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)


class _StubSentencesView(QWidget):
    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)
        self.reload_calls = 0

    def _reload(self) -> None:
        self.reload_calls += 1


class _StubExportView(QWidget):
    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)


class _StubTermCardView(QWidget):
    def __init__(self, project_id: int, *, defer_initial_load: bool = False):
        super().__init__()
        self.project_id = int(project_id)
        self.defer_initial_load = bool(defer_initial_load)
        self.ensure_calls = 0
        self.loaded = False

    def ensure_review_queue_loaded(self) -> None:
        if self.loaded:
            return
        self.loaded = True
        self.ensure_calls += 1


def _patch_project_children(monkeypatch) -> None:
    monkeypatch.setattr("app.ui.project_view.ProjectService", lambda: object())
    monkeypatch.setattr(ProjectView, "load_project", lambda self: None)
    monkeypatch.setattr("app.ui.project_view.DocumentsView", _StubDocumentsView)
    monkeypatch.setattr("app.ui.project_view.DictionaryView", _StubDictionaryView)
    monkeypatch.setattr("app.ui.project_view.TermsView", _StubTermsView)
    monkeypatch.setattr("app.ui.project_view.ConcordanceView", _StubConcordanceView)
    monkeypatch.setattr("app.ui.project_view.TermCardView", _StubTermCardView)
    monkeypatch.setattr("app.ui.project_view.UserDictionariesView", _StubUserDictionariesView)
    monkeypatch.setattr("app.ui.project_view.SentencesView", _StubSentencesView)
    monkeypatch.setattr("app.ui.project_view.ExportView", _StubExportView)


def test_project_view_defers_hidden_term_card_load_until_tab_activation(monkeypatch, qtbot):
    _patch_project_children(monkeypatch)

    view = ProjectView(7)
    qtbot.addWidget(view)

    assert view.tabs.currentWidget() is view.documents_view
    assert view.term_card_view.defer_initial_load is True
    assert view.term_card_view.ensure_calls == 0

    view.tabs.setCurrentWidget(view.term_card_view)

    assert view.term_card_view.ensure_calls == 1


def test_project_view_focus_tab_triggers_term_card_load_once(monkeypatch, qtbot):
    _patch_project_children(monkeypatch)

    view = ProjectView(9)
    qtbot.addWidget(view)

    assert view.focus_tab("term_cards") is True
    assert view.term_card_view.ensure_calls == 1

    assert view.focus_tab("term_cards") is True
    assert view.term_card_view.ensure_calls == 1


def test_term_card_view_ensure_queue_load_is_idempotent():
    view = TermCardView.__new__(TermCardView)
    view._review_queue_loaded = False
    calls = []

    def _load_queue() -> None:
        calls.append("load")
        view._review_queue_loaded = True

    view.load_review_queue = _load_queue

    TermCardView.ensure_review_queue_loaded(view)
    TermCardView.ensure_review_queue_loaded(view)

    assert calls == ["load"]
