"""Sentences -> User Dictionary refresh contract tests."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QWidget

from app.ui.sentences_view import SentencesView


class _ParentWithUserDict(QWidget):
    def __init__(self):
        super().__init__()
        self.refresh_calls = 0
        self.user_dictionaries_view = SimpleNamespace(load_dictionaries=self._refresh_user_dicts)

    def _refresh_user_dicts(self):
        self.refresh_calls += 1


def test_sentences_add_to_user_dict_refreshes_linked_views(monkeypatch, qtbot):
    reload_calls = []
    info_calls = []

    monkeypatch.setattr("app.ui.sentences_view.DBService.get_instance", lambda: SimpleNamespace())
    monkeypatch.setattr(SentencesView, "_reload", lambda self: reload_calls.append(True))
    monkeypatch.setattr(
        "app.ui.sentences_view.show_info",
        lambda *args, **kwargs: info_calls.append((args, kwargs)),
    )

    view = SentencesView(project_id=1)
    qtbot.addWidget(view)
    reload_calls.clear()  # init triggers initial load

    parent = _ParentWithUserDict()
    qtbot.addWidget(parent)
    view.setParent(parent)

    close_calls = []
    progress_dialog = SimpleNamespace(close=lambda: close_calls.append(True))
    view._user_dict_add_worker = object()
    view._user_dict_target_dictionary_id = 42

    view._on_user_dict_add_finished({"added": 3, "skipped": 1, "failed": 0}, progress_dialog)

    assert close_calls == [True]
    assert reload_calls == [True]
    assert parent.refresh_calls == 1
    assert info_calls
    assert view._user_dict_add_worker is None
    assert view._user_dict_target_dictionary_id is None

