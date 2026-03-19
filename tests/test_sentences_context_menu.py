"""Tests for Sentences context-menu actions."""

from types import SimpleNamespace

from app.ui.sentences_view import SentencesView


class DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self):
        for callback in self._callbacks:
            callback()


class FakeAction:
    def __init__(self, text, parent):
        self.text = text
        self.parent = parent
        self.triggered = DummySignal()
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)


class FakeMenu:
    last = None

    def __init__(self, parent):
        self.parent = parent
        self.actions = []
        self.separators = 0
        FakeMenu.last = self

    def addAction(self, arg, *args, **kwargs):
        if isinstance(arg, FakeAction):
            action = arg
        else:
            action = FakeAction(str(arg), self.parent)
        self.actions.append(action)
        return action

    def addSeparator(self):
        self.separators += 1

    def exec(self, _pos):
        return None


class FakeViewport:
    def mapToGlobal(self, pos):
        return pos


class FakeTable:
    def viewport(self):
        return FakeViewport()


def test_sentences_context_menu_includes_add_selected_to_playlist(monkeypatch):
    monkeypatch.setattr("app.ui.sentences_view.QMenu", FakeMenu)

    view = SentencesView.__new__(SentencesView)
    view.table = FakeTable()
    view._get_selected_dtos = lambda: [
        SimpleNamespace(sentence_id=1, text="a"),
        SimpleNamespace(sentence_id=2, text="b"),
    ]

    state = {
        "translate": 0,
        "edit_translation": 0,
        "clear_translation": 0,
        "generate_audio": 0,
        "play_audio": 0,
        "add_playlist": 0,
        "add_user_dict": 0,
        "bootstrap": 0,
    }
    view.on_batch_translate = lambda: state.__setitem__("translate", state["translate"] + 1)
    view.on_edit_translation_selected = lambda: state.__setitem__(
        "edit_translation", state["edit_translation"] + 1
    )
    view.on_clear_translation_selected = lambda: state.__setitem__(
        "clear_translation", state["clear_translation"] + 1
    )
    view.on_generate_audio = lambda: state.__setitem__(
        "generate_audio", state["generate_audio"] + 1
    )
    view.on_play_audio = lambda: state.__setitem__("play_audio", state["play_audio"] + 1)
    view.on_add_selected_to_playlist = lambda: state.__setitem__(
        "add_playlist", state["add_playlist"] + 1
    )
    view.on_add_selected_to_user_dictionary = lambda: state.__setitem__(
        "add_user_dict", state["add_user_dict"] + 1
    )
    view.on_pronunciation_bootstrap = lambda: state.__setitem__("bootstrap", state["bootstrap"] + 1)
    view.on_niqqud_bootstrap_selected = lambda: None
    view.on_edit_niqqud_selected = lambda: None
    view.on_clear_niqqud_selected = lambda: None
    view.on_edit_pronunciation_selected = lambda: None

    SentencesView._show_context_menu(view, pos=(0, 0))

    assert FakeMenu.last is not None
    actions = [a.text for a in FakeMenu.last.actions]
    assert "Add Selected to Playlist (2)..." in actions
    assert "Add Selected to User Dictionary (2)..." in actions

    next(a for a in FakeMenu.last.actions if a.text == "Translate Selected (2)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Edit Translation...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Clear Translation (2)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Generate Audio (2)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if "Play Audio Selected (2)" in a.text).triggered.emit()
    next(
        a for a in FakeMenu.last.actions if a.text == "Add Selected to Playlist (2)..."
    ).triggered.emit()
    next(
        a for a in FakeMenu.last.actions if a.text == "Add Selected to User Dictionary (2)..."
    ).triggered.emit()
    next(
        a for a in FakeMenu.last.actions if a.text == "Pronunciation Bootstrap Selected (2)..."
    ).triggered.emit()

    assert state["translate"] == 1
    assert state["edit_translation"] == 1
    assert state["clear_translation"] == 1
    assert state["generate_audio"] == 1
    assert state["play_audio"] == 1
    assert state["add_playlist"] == 1
    assert state["add_user_dict"] == 1
    assert state["bootstrap"] == 1
