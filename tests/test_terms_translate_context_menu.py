"""Tests for Terms context menu batch-translate action label and wiring."""

from types import SimpleNamespace

from app.ui.terms_view import TermsView


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

    def isValid(self):
        return True

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

    def indexAt(self, _pos):
        return FakeIndex(0)

    def selectionModel(self):
        return self._selection_model

    def viewport(self):
        return self._viewport


class FakeProxyModel:
    def map_to_source_row(self, row):
        return row


def _build_terms_view(selected_count: int):
    view = TermsView.__new__(TermsView)
    view.terms_table = FakeTable(selected_count)
    view.proxy_model = FakeProxyModel()
    view.terms_model = SimpleNamespace(clusters=[SimpleNamespace(is_noise=0)])
    view.show_why_dialog = lambda _row: None
    view.set_clusters_noise_status_bulk = lambda _is_noise: None
    view.set_cluster_noise_status = lambda _row, _is_noise: None

    state = {"translate_called": 0, "generate_called": 0, "play_called": 0, "add_called": 0, "edit_pron_called": 0}
    view.on_batch_translate = lambda: state.__setitem__("translate_called", state["translate_called"] + 1)
    view.on_generate_audio_selected = lambda: state.__setitem__("generate_called", state["generate_called"] + 1)
    view.on_play_audio_selected = lambda: state.__setitem__("play_called", state["play_called"] + 1)
    view.on_add_selected_to_user_dictionary = lambda: state.__setitem__("add_called", state["add_called"] + 1)
    view.on_edit_pronunciation_selected = lambda: state.__setitem__("edit_pron_called", state["edit_pron_called"] + 1)
    return view, state


def test_terms_context_menu_translate_selected_single_row(monkeypatch):
    monkeypatch.setattr("app.ui.terms_view.QMenu", FakeMenu)
    monkeypatch.setattr("app.ui.terms_view.QAction", FakeAction)

    view, state = _build_terms_view(selected_count=1)
    TermsView.on_context_menu(view, pos=(0, 0))

    assert FakeMenu.last is not None
    assert FakeMenu.last.actions[0].text == "Translate selected (1 rows)..."
    assert FakeMenu.last.actions[1].text == "Generate Audio Selected (1 rows)..."
    assert FakeMenu.last.actions[2].text == "Play Audio Selected (1 rows)"
    assert FakeMenu.last.actions[3].text == "Add Selected to User Dictionary (1 rows)..."
    assert FakeMenu.last.actions[4].text == "Mispronounced -> Add Pronunciation..."

    FakeMenu.last.actions[0].triggered.emit()
    assert state["translate_called"] == 1
    FakeMenu.last.actions[1].triggered.emit()
    assert state["generate_called"] == 1
    FakeMenu.last.actions[2].triggered.emit()
    assert state["play_called"] == 1
    FakeMenu.last.actions[3].triggered.emit()
    assert state["add_called"] == 1
    FakeMenu.last.actions[4].triggered.emit()
    assert state["edit_pron_called"] == 1


def test_terms_context_menu_translate_selected_multiple_rows(monkeypatch):
    monkeypatch.setattr("app.ui.terms_view.QMenu", FakeMenu)
    monkeypatch.setattr("app.ui.terms_view.QAction", FakeAction)

    view, state = _build_terms_view(selected_count=4)
    TermsView.on_context_menu(view, pos=(0, 0))

    assert FakeMenu.last is not None
    assert FakeMenu.last.actions[0].text == "Translate selected (4 rows)..."
    assert FakeMenu.last.actions[1].text == "Generate Audio Selected (4 rows)..."
    assert FakeMenu.last.actions[2].text == "Play Audio Selected (4 rows)"
    assert FakeMenu.last.actions[3].text == "Add Selected to User Dictionary (4 rows)..."
    assert FakeMenu.last.actions[4].text == "Mispronounced -> Add Pronunciation..."

    FakeMenu.last.actions[0].triggered.emit()
    assert state["translate_called"] == 1
    FakeMenu.last.actions[1].triggered.emit()
    assert state["generate_called"] == 1
    FakeMenu.last.actions[2].triggered.emit()
    assert state["play_called"] == 1
    FakeMenu.last.actions[3].triggered.emit()
    assert state["add_called"] == 1
    FakeMenu.last.actions[4].triggered.emit()
    assert state["edit_pron_called"] == 1
