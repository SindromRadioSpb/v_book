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
        self.enabled = True

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


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
        "playlist_called": 0,
        "edit_pron_called": 0,
        "bootstrap_called": 0,
        "niqqud_called": 0,
        "noise_flags": [],
        "suspended_flags": [],
        "due_called": 0,
    }
    view.on_translate_selected = lambda: state.__setitem__("translate_called", state["translate_called"] + 1)
    view.on_generate_audio_selected = lambda: state.__setitem__("audio_called", state["audio_called"] + 1)
    view.on_play_audio_selected = lambda: state.__setitem__("play_called", state["play_called"] + 1)
    view.on_add_selected_to_playlist = lambda: state.__setitem__("playlist_called", state["playlist_called"] + 1)
    view.on_edit_pronunciation_selected = lambda: state.__setitem__("edit_pron_called", state["edit_pron_called"] + 1)
    view.on_pronunciation_bootstrap_selected = lambda: state.__setitem__("bootstrap_called", state["bootstrap_called"] + 1)
    view.on_sentence_niqqud_bootstrap_selected = lambda: state.__setitem__("niqqud_called", state["niqqud_called"] + 1)
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
    actions = [action.text for action in FakeMenu.last.actions]
    assert len(actions) == 12
    assert actions[0] == "Translate Selected (3 rows)..."
    assert actions[1] == "Generate Audio Selected (3 rows)..."
    assert actions[2] == "Play Audio Selected (3 rows)"
    assert "Add Selected to Playlist (3 rows)..." in actions
    assert "Mispronounced -> Add Pronunciation..." in actions
    assert "Pronunciation Bootstrap Selected (3 rows)..." in actions
    assert "Niqqud Selected - Sentence Niqqud Bootstrap" in actions
    assert "Mark Selected as Noise (3 rows)" in actions
    assert "Mark Selected as Valid (3 rows)" in actions
    assert "Mark Selected as Due now (3 rows)" in actions
    assert "Suspend Selected (3 rows)" in actions
    assert "Resume Selected (3 rows)" in actions

    next(a for a in FakeMenu.last.actions if a.text == "Translate Selected (3 rows)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Generate Audio Selected (3 rows)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Play Audio Selected (3 rows)").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Add Selected to Playlist (3 rows)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Mispronounced -> Add Pronunciation...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Pronunciation Bootstrap Selected (3 rows)...").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Niqqud Selected - Sentence Niqqud Bootstrap").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Mark Selected as Noise (3 rows)").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Mark Selected as Valid (3 rows)").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Mark Selected as Due now (3 rows)").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Suspend Selected (3 rows)").triggered.emit()
    next(a for a in FakeMenu.last.actions if a.text == "Resume Selected (3 rows)").triggered.emit()

    assert state["translate_called"] == 1
    assert state["audio_called"] == 1
    assert state["play_called"] == 1
    assert state["playlist_called"] == 1
    assert state["edit_pron_called"] == 1
    assert state["bootstrap_called"] == 1
    assert state["niqqud_called"] == 1
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

def test_user_dict_selected_pronunciation_items_skip_sentence_rows():
    view = UserDictionariesView.__new__(UserDictionariesView)
    view.items_table = FakeTable(3)
    rows = [
        SimpleNamespace(src_lang="he", src_text="alpha", src_norm="alpha", kind="lemma"),
        SimpleNamespace(src_lang="he", src_text="beta", src_norm="beta", kind="surface"),
        SimpleNamespace(src_lang="he", src_text="gamma", src_norm="gamma", kind="term_cluster"),
    ]
    view.items_model = SimpleNamespace(get_item=lambda idx: rows[idx])

    items = UserDictionariesView._selected_pronunciation_items(view)
    source_groups = [item["source_group"] for item in items]
    assert source_groups == ["lemmas", "terms"]


def test_user_dict_selected_sentence_ids_for_niqqud_uses_sentence_origin():
    view = UserDictionariesView.__new__(UserDictionariesView)
    view.items_table = FakeTable(4)
    rows = [
        SimpleNamespace(origin_entity_type="sentence", origin_entity_id="200", src_lang="he"),
        SimpleNamespace(origin_entity_type="lemma", origin_entity_id="2", src_lang="he"),
        SimpleNamespace(origin_entity_type="sentences", origin_entity_id="201", src_lang="he"),
        SimpleNamespace(origin_entity_type="sentence", origin_entity_id="bad", src_lang="he"),
    ]
    view.items_model = SimpleNamespace(get_item=lambda idx: rows[idx])

    sentence_ids, lang = UserDictionariesView._selected_sentence_ids_for_niqqud(view)
    assert sentence_ids == [200, 201]
    assert lang == "he"
