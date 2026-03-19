"""Tests for Dictionary context menu audio actions."""

from types import SimpleNamespace

from app.domain.normalization.normalizer import normalize_for_tm
from app.ui.dictionary_view import DictionaryView


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


def _build_dictionary_view(selected_count: int):
    view = DictionaryView.__new__(DictionaryView)
    view.lemma_table = FakeTable(selected_count)
    view.proxy_model = FakeProxyModel()
    view.lemma_model = SimpleNamespace(lemmas=[SimpleNamespace(is_noise=0)])
    view.show_why_dialog = lambda _row: None
    view.set_lemmas_noise_status_bulk = lambda _is_noise: None
    view.set_lemma_noise_status = lambda _row, _is_noise: None

    state = {
        "translate": 0,
        "generate": 0,
        "play": 0,
        "playlist": 0,
        "add": 0,
        "edit_pron": 0,
        "bootstrap": 0,
    }
    view.on_batch_translate = lambda: state.__setitem__("translate", state["translate"] + 1)
    view.on_generate_audio_selected = lambda: state.__setitem__("generate", state["generate"] + 1)
    view.on_play_audio_selected = lambda: state.__setitem__("play", state["play"] + 1)
    view.on_add_selected_to_playlist = lambda: state.__setitem__("playlist", state["playlist"] + 1)
    view.on_add_selected_to_user_dictionary = lambda: state.__setitem__("add", state["add"] + 1)
    view.on_edit_pronunciation_selected = lambda: state.__setitem__(
        "edit_pron", state["edit_pron"] + 1
    )
    view.on_pronunciation_bootstrap_selected = lambda: state.__setitem__(
        "bootstrap", state["bootstrap"] + 1
    )
    return view, state


def test_dictionary_context_menu_includes_audio_actions(monkeypatch):
    monkeypatch.setattr("app.ui.dictionary_view.QMenu", FakeMenu)
    monkeypatch.setattr("app.ui.dictionary_view.QAction", FakeAction)

    view, state = _build_dictionary_view(selected_count=2)
    DictionaryView.on_context_menu(view, pos=(0, 0))

    assert FakeMenu.last is not None
    assert FakeMenu.last.actions[0].text == "Translate Selected (2 rows)..."
    assert FakeMenu.last.actions[1].text == "Generate Audio Selected (2 rows)..."
    assert FakeMenu.last.actions[2].text == "Play Audio Selected (2 rows)"
    assert FakeMenu.last.actions[3].text == "Add Selected to User Dictionary (2 rows)..."
    assert FakeMenu.last.actions[4].text == "Add Selected to Playlist (2 rows)..."
    assert FakeMenu.last.actions[5].text == "Mispronounced -> Add Pronunciation..."
    assert FakeMenu.last.actions[6].text == "Pronunciation Bootstrap Selected (2 rows)..."

    FakeMenu.last.actions[0].triggered.emit()
    FakeMenu.last.actions[1].triggered.emit()
    FakeMenu.last.actions[2].triggered.emit()
    FakeMenu.last.actions[3].triggered.emit()
    FakeMenu.last.actions[4].triggered.emit()
    FakeMenu.last.actions[5].triggered.emit()
    FakeMenu.last.actions[6].triggered.emit()

    assert state == {
        "translate": 1,
        "generate": 1,
        "play": 1,
        "playlist": 1,
        "add": 1,
        "edit_pron": 1,
        "bootstrap": 1,
    }


def test_dictionary_selected_pronunciation_items_use_surface_norm():
    view = DictionaryView.__new__(DictionaryView)
    view.lemma_table = FakeTable(selected_count=2)
    view.proxy_model = FakeProxyModel()
    view.lemma_model = SimpleNamespace(
        lemmas=[
            SimpleNamespace(lemma_id=1, lemma_text="בפלדה", norm_text="פלדה"),
            SimpleNamespace(lemma_id=2, lemma_text="לפלדה", norm_text="פלדה"),
        ]
    )

    items = DictionaryView._selected_pronunciation_items(view)

    assert len(items) == 2
    assert items[0]["src_norm"] == normalize_for_tm("he", "בפלדה", "surface").norm
    assert items[1]["src_norm"] == normalize_for_tm("he", "לפלדה", "surface").norm


def test_dictionary_bootstrap_refreshes_view_on_success(monkeypatch):
    view = DictionaryView.__new__(DictionaryView)
    view._selected_pronunciation_items = lambda: [
        {
            "src_lang": "he",
            "src_text": "בפלדה",
            "src_norm": normalize_for_tm("he", "בפלדה", "surface").norm,
        }
    ]
    state = {"search": 0}
    view.perform_search = lambda: state.__setitem__("search", state["search"] + 1)

    monkeypatch.setattr(
        "app.ui.dialogs.pronunciation_bootstrap_dialog.show_pronunciation_bootstrap_dialog",
        lambda **kwargs: True,
    )

    DictionaryView.on_pronunciation_bootstrap_selected(view)
    assert state["search"] == 1
