"""Tests for Term Card queue context menu audio actions."""

from app.ui.term_card_view import TermCardView


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


class FakeMenu:
    last = None

    def __init__(self, parent):
        self.parent = parent
        self.actions = []
        self.separators = 0
        FakeMenu.last = self

    def addAction(self, action):
        self.actions.append(action)

    def addSeparator(self):
        self.separators += 1

    def exec(self, _pos):
        return None


class FakeIndex:
    def __init__(self, row):
        self._row = row

    def row(self):
        return self._row


class FakeSelectionModel:
    def __init__(self, selected_count):
        self._selected_count = selected_count

    def selectedRows(self, *_args):
        return [FakeIndex(i) for i in range(self._selected_count)]


class FakeViewport:
    def mapToGlobal(self, pos):
        return pos


class FakeTable:
    def __init__(self, selected_count):
        self._selection_model = FakeSelectionModel(selected_count)
        self._viewport = FakeViewport()

    def selectionModel(self):
        return self._selection_model

    def viewport(self):
        return self._viewport


def _build_term_card_view(selected_count: int):
    view = TermCardView.__new__(TermCardView)
    view.queue_table = FakeTable(selected_count)
    state = {"generate": 0, "play": 0, "add": 0, "edit_pron": 0}
    view.on_generate_audio_selected = lambda: state.__setitem__("generate", state["generate"] + 1)
    view.on_play_audio_selected = lambda: state.__setitem__("play", state["play"] + 1)
    view.on_add_selected_to_user_dictionary = lambda: state.__setitem__("add", state["add"] + 1)
    view.on_edit_pronunciation_selected = lambda: state.__setitem__("edit_pron", state["edit_pron"] + 1)
    return view, state


def test_term_card_context_menu_includes_audio_actions(monkeypatch):
    monkeypatch.setattr("app.ui.term_card_view.QMenu", FakeMenu)
    monkeypatch.setattr("app.ui.term_card_view.QAction", FakeAction)

    view, state = _build_term_card_view(selected_count=3)
    TermCardView.on_queue_context_menu(view, pos=(0, 0))

    assert FakeMenu.last is not None
    assert FakeMenu.last.actions[0].text == "Generate Audio Selected (3 rows)..."
    assert FakeMenu.last.actions[1].text == "Play Audio Selected (3 rows)"
    assert FakeMenu.last.actions[2].text == "Add Selected to User Dictionary (3 rows)..."
    assert FakeMenu.last.actions[3].text == "Edit Pronunciation..."

    FakeMenu.last.actions[0].triggered.emit()
    FakeMenu.last.actions[1].triggered.emit()
    FakeMenu.last.actions[2].triggered.emit()
    FakeMenu.last.actions[3].triggered.emit()

    assert state == {"generate": 1, "play": 1, "add": 1, "edit_pron": 1}
