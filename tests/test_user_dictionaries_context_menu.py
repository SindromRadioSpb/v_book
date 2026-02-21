"""Tests for User Dictionaries context menu actions."""

from types import SimpleNamespace

from app.domain.normalization.normalizer import normalize_for_tm
from app.ui.user_dictionaries_view import UserDictionariesView


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


def _build_view(selected_count: int):
    view = UserDictionariesView.__new__(UserDictionariesView)
    view.items_table = FakeTable(selected_count)
    state = {
        "translate_called": 0,
        "audio_called": 0,
        "play_called": 0,
        "edit_pron_called": 0,
        "bootstrap_called": 0,
        "noise_flags": [],
        "suspended_flags": [],
        "due_called": 0,
    }
    view.on_translate_selected = lambda: state.__setitem__("translate_called", state["translate_called"] + 1)
    view.on_generate_audio_selected = lambda: state.__setitem__("audio_called", state["audio_called"] + 1)
    view.on_play_audio_selected = lambda: state.__setitem__("play_called", state["play_called"] + 1)
    view.on_edit_pronunciation_selected = lambda: state.__setitem__("edit_pron_called", state["edit_pron_called"] + 1)
    view.on_pronunciation_bootstrap_selected = lambda: state.__setitem__("bootstrap_called", state["bootstrap_called"] + 1)
    view.set_selected_noise_status = lambda flag: state["noise_flags"].append(flag)
    view.set_selected_suspension = lambda flag: state["suspended_flags"].append(flag)
    view.set_selected_due_now = lambda: state.__setitem__("due_called", state["due_called"] + 1)
    return view, state


def test_user_dict_context_menu_includes_translate_and_noise_actions(monkeypatch):
    monkeypatch.setattr("app.ui.user_dictionaries_view.QMenu", FakeMenu)
    monkeypatch.setattr("app.ui.user_dictionaries_view.QAction", FakeAction)

    view, state = _build_view(selected_count=3)
    UserDictionariesView.on_context_menu(view, pos=(0, 0))

    assert FakeMenu.last is not None
    assert len(FakeMenu.last.actions) == 10
    assert FakeMenu.last.actions[0].text == "Translate Selected (3 rows)..."
    assert FakeMenu.last.actions[1].text == "Generate Audio Selected (3 rows)..."
    assert FakeMenu.last.actions[2].text == "Play Audio Selected (3 rows)"
    assert FakeMenu.last.actions[3].text == "Mispronounced -> Add Pronunciation..."
    assert FakeMenu.last.actions[4].text == "Pronunciation Bootstrap Selected (3 rows)..."
    assert FakeMenu.last.actions[5].text == "Mark Selected as Noise (3 rows)"
    assert FakeMenu.last.actions[6].text == "Mark Selected as Valid (3 rows)"
    assert FakeMenu.last.actions[7].text == "Mark Selected as Due now (3 rows)"
    assert FakeMenu.last.actions[8].text == "Suspend Selected (3 rows)"
    assert FakeMenu.last.actions[9].text == "Resume Selected (3 rows)"

    FakeMenu.last.actions[0].triggered.emit()
    FakeMenu.last.actions[1].triggered.emit()
    FakeMenu.last.actions[2].triggered.emit()
    FakeMenu.last.actions[3].triggered.emit()
    FakeMenu.last.actions[4].triggered.emit()
    FakeMenu.last.actions[5].triggered.emit()
    FakeMenu.last.actions[6].triggered.emit()
    FakeMenu.last.actions[7].triggered.emit()
    FakeMenu.last.actions[8].triggered.emit()
    FakeMenu.last.actions[9].triggered.emit()

    assert state["translate_called"] == 1
    assert state["audio_called"] == 1
    assert state["play_called"] == 1
    assert state["edit_pron_called"] == 1
    assert state["bootstrap_called"] == 1
    assert state["noise_flags"] == [True, False]
    assert state["due_called"] == 1
    assert state["suspended_flags"] == [True, False]


def test_user_dict_selected_pronunciation_items_use_surface_norm():
    view = UserDictionariesView.__new__(UserDictionariesView)
    view.items_table = FakeTable(2)
    rows = [
        SimpleNamespace(src_lang="he", src_text="בפלדה", src_norm="פלדה", kind="lemma"),
        SimpleNamespace(src_lang="he", src_text="לפלדה", src_norm="פלדה", kind="lemma"),
    ]
    view.items_model = SimpleNamespace(get_item=lambda idx: rows[idx])

    items = UserDictionariesView._selected_pronunciation_items(view)

    assert len(items) == 2
    assert items[0]["src_norm"] == normalize_for_tm("he", "בפלדה", "surface").norm
    assert items[1]["src_norm"] == normalize_for_tm("he", "לפלדה", "surface").norm


def test_user_dict_edit_pronunciation_uses_surface_norm(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.ui.user_dictionaries_view.show_edit_pronunciation_dialog",
        lambda **kwargs: captured.update(kwargs) or False,
    )

    view = UserDictionariesView.__new__(UserDictionariesView)
    view._selected_item_ids = lambda: [1]
    view.items_table = FakeTable(1)
    row = SimpleNamespace(
        src_lang="he",
        src_text="הפרק הזמן",
        src_norm=normalize_for_tm("he", "הפרק הזמן", "term_cluster").norm,
        kind="term_cluster",
    )
    view.items_model = SimpleNamespace(get_item=lambda _idx: row)

    UserDictionariesView.on_edit_pronunciation_selected(view)

    assert captured["src_norm"] == normalize_for_tm("he", "הפרק הזמן", "surface").norm
