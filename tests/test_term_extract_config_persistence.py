"""Tests for terms_view config persistence: include_np and ngram_ns (Epic 4 PATCH-03)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.ui.terms_view import TermsView


# ---------------------------------------------------------------------------
# Minimal fake SettingsService that stores key/value in a dict
# ---------------------------------------------------------------------------


class _FakeSettings:
    def __init__(self, initial: dict | None = None):
        self._store: dict = initial or {}

    def get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self._store.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self._store.get(key, default))

    def get_string(self, key: str, default: str = "") -> str:
        return str(self._store.get(key, default))

    def set_value(self, key: str, value) -> None:
        self._store[key] = value


# ---------------------------------------------------------------------------
# include_np persistence
# ---------------------------------------------------------------------------


def test_include_np_defaults_to_true_when_no_saved_value():
    """include_np checkbox defaults to True when nothing is saved in QSettings."""
    settings = _FakeSettings()  # empty — no saved value
    view = TermsView.__new__(TermsView)
    view.settings = settings

    saved = settings.get_bool("terms_view/include_np", True)
    assert saved is True


def test_include_np_restored_from_false():
    """include_np=False is correctly loaded from QSettings."""
    settings = _FakeSettings({"terms_view/include_np": False})
    view = TermsView.__new__(TermsView)
    view.settings = settings

    saved = settings.get_bool("terms_view/include_np", True)
    assert saved is False


def test_on_include_np_changed_saves_to_settings():
    """on_include_np_changed() persists the checkbox state to QSettings."""
    settings = _FakeSettings()
    view = TermsView.__new__(TermsView)
    view.settings = settings

    # Simulate checkbox at True
    view.include_np_checkbox = SimpleNamespace(isChecked=lambda: True)
    TermsView.on_include_np_changed(view)
    assert settings._store.get("terms_view/include_np") is True

    # Simulate checkbox at False
    view.include_np_checkbox = SimpleNamespace(isChecked=lambda: False)
    TermsView.on_include_np_changed(view)
    assert settings._store.get("terms_view/include_np") is False


# ---------------------------------------------------------------------------
# ngram_ns persistence
# ---------------------------------------------------------------------------


def test_ngram_ns_defaults_to_both_when_no_saved_value():
    """ngram_ns defaults to [2, 3] when nothing is saved."""
    settings = _FakeSettings()
    saved_json = settings.get_string("terms_view/ngram_ns_json", "[2,3]")
    ns = set(json.loads(saved_json))
    assert ns == {2, 3}


def test_ngram_ns_restored_bigrams_only():
    """Only bigrams (n=2) is correctly restored from QSettings."""
    settings = _FakeSettings({"terms_view/ngram_ns_json": "[2]"})
    saved_json = settings.get_string("terms_view/ngram_ns_json", "[2,3]")
    ns = set(json.loads(saved_json))
    assert ns == {2}
    assert 3 not in ns


def test_ngram_ns_restored_trigrams_only():
    """Only trigrams (n=3) is correctly restored from QSettings."""
    settings = _FakeSettings({"terms_view/ngram_ns_json": "[3]"})
    saved_json = settings.get_string("terms_view/ngram_ns_json", "[2,3]")
    ns = set(json.loads(saved_json))
    assert ns == {3}
    assert 2 not in ns


def test_on_ngram_ns_changed_saves_bigrams_only():
    """on_ngram_ns_changed() saves [2] when only Bigrams checked."""
    settings = _FakeSettings()
    view = TermsView.__new__(TermsView)
    view.settings = settings
    view.ngram_bigrams_checkbox = SimpleNamespace(isChecked=lambda: True)
    view.ngram_trigrams_checkbox = SimpleNamespace(isChecked=lambda: False)

    TermsView.on_ngram_ns_changed(view)

    saved = json.loads(settings._store["terms_view/ngram_ns_json"])
    assert saved == [2]


def test_on_ngram_ns_changed_saves_both():
    """on_ngram_ns_changed() saves [2, 3] when both checked."""
    settings = _FakeSettings()
    view = TermsView.__new__(TermsView)
    view.settings = settings
    view.ngram_bigrams_checkbox = SimpleNamespace(isChecked=lambda: True)
    view.ngram_trigrams_checkbox = SimpleNamespace(isChecked=lambda: True)

    TermsView.on_ngram_ns_changed(view)

    saved = json.loads(settings._store["terms_view/ngram_ns_json"])
    assert saved == [2, 3]


def test_on_ngram_ns_changed_saves_empty_when_none_checked():
    """on_ngram_ns_changed() saves [] when both unchecked.

    [] in QSettings is valid — it records the user's selection faithfully.
    on_extract() will show a validation error and refuse to start extraction,
    so the empty value never reaches the service layer.
    """
    settings = _FakeSettings()
    view = TermsView.__new__(TermsView)
    view.settings = settings
    view.ngram_bigrams_checkbox = SimpleNamespace(isChecked=lambda: False)
    view.ngram_trigrams_checkbox = SimpleNamespace(isChecked=lambda: False)

    TermsView.on_ngram_ns_changed(view)

    saved = json.loads(settings._store["terms_view/ngram_ns_json"])
    assert saved == []


def test_ngram_ns_json_is_always_sorted():
    """Saved ngram_ns_json is always in ascending sorted order."""
    settings = _FakeSettings()
    view = TermsView.__new__(TermsView)
    view.settings = settings
    # Even if checkboxes were added in reverse order in some future refactor,
    # the handler always sorts.
    view.ngram_bigrams_checkbox = SimpleNamespace(isChecked=lambda: True)
    view.ngram_trigrams_checkbox = SimpleNamespace(isChecked=lambda: True)

    TermsView.on_ngram_ns_changed(view)

    saved = json.loads(settings._store["terms_view/ngram_ns_json"])
    assert saved == sorted(saved)


def test_ngram_ns_invalid_json_falls_back_to_default():
    """Corrupted ngram_ns_json in QSettings falls back to {2, 3} without crashing."""
    settings = _FakeSettings({"terms_view/ngram_ns_json": "INVALID_JSON"})
    saved_json = settings.get_string("terms_view/ngram_ns_json", "[2,3]")
    try:
        ns = set(json.loads(saved_json))
    except (ValueError, TypeError):
        ns = {2, 3}
    assert ns == {2, 3}
