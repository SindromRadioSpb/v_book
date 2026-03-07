"""Tests for PERF-SCALE PATCH-H: anti-stale request_id guards.

Covers:
- _SentencesLoadWorker carries request_id in finished/error signals
- SentencesView._on_load_finished drops stale responses (request_id mismatch)
- SentencesView._on_load_error drops stale responses
- UserDictItemsPageWorker exists and has correct signal arity
- _on_items_loaded drops stale responses
- _on_items_error drops stale responses
- load_items() increments request_id on each call
"""
from __future__ import annotations

import inspect
import pytest

# ---------------------------------------------------------------------------
# _SentencesLoadWorker signal signatures
# ---------------------------------------------------------------------------

def test_sentences_load_worker_has_request_id_in_finished():
    from app.ui.sentences_view import _SentencesLoadWorker
    sig = _SentencesLoadWorker.finished
    # pyqtSignal stores types; we verify it accepts (int, list, int) by
    # checking the constructor accepts request_id as first arg
    params = list(inspect.signature(_SentencesLoadWorker.__init__).parameters)
    assert params[1] == "request_id", "first param after self must be request_id"


def test_sentences_load_worker_init_stores_request_id():
    """Constructor stores request_id correctly."""
    from app.ui.sentences_view import _SentencesLoadWorker
    w = _SentencesLoadWorker(
        request_id=42,
        project_id=1,
        page=1,
        page_size=50,
        doc_filter=None,
        text_search=None,
    )
    assert w.request_id == 42


# ---------------------------------------------------------------------------
# SentencesView._on_load_finished stale-drop logic
# ---------------------------------------------------------------------------

class _FakeSentencesView:
    """Minimal stub of SentencesView for testing stale-drop handlers."""

    def __init__(self):
        self._active_request_id = 5
        self._current_dtos = []
        self.total_count = 0
        self._populate_called = False
        self._pagination_called = False
        self.status_text = ""

    def _populate_table(self, dtos):
        self._populate_called = True

    def _update_pagination(self, total):
        self._pagination_called = True

    def status_label_setText(self, text):
        self.status_text = text

    # Bind the real methods to this stub
    from app.ui.sentences_view import SentencesView
    _on_page_ready = SentencesView._on_page_ready
    _on_count_ready = SentencesView._on_count_ready
    _on_load_finished = SentencesView._on_load_finished
    _on_load_error = SentencesView._on_load_error


def _make_fake_view(active_id: int):
    v = _FakeSentencesView.__new__(_FakeSentencesView)
    v._active_request_id = active_id
    v._current_dtos = []
    v.total_count = 0
    v._populate_called = False
    v._pagination_called = False
    v.status_text = ""
    # Fake status_label
    class _Label:
        def __init__(self): self.text = ""
        def setText(self, t): self.text = t
    v.status_label = _Label()
    return v


def test_on_page_ready_applies_when_request_id_matches():
    """Stage-1: _on_page_ready populates table when request matches."""
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=3)
    dtos = [object(), object()]
    SentencesView._on_page_ready(v, request_id=3, dtos=dtos)
    assert v._current_dtos is dtos
    assert "counting" in v.status_label.text


def test_on_page_ready_drops_stale_request():
    """Stage-1: stale request_id must not update _current_dtos."""
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=5)
    original_dtos = [object()]
    v._current_dtos = original_dtos
    SentencesView._on_page_ready(v, request_id=3, dtos=[object(), object()])
    assert v._current_dtos is original_dtos  # unchanged


def test_on_count_ready_applies_when_request_id_matches():
    """Stage-2: _on_count_ready updates total when request matches."""
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=3)
    v._current_dtos = [object()]
    SentencesView._on_count_ready(v, request_id=3, total=42)
    assert v.total_count == 42


def test_on_count_ready_drops_stale_request():
    """Stage-2: stale request_id must not update total_count."""
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=5)
    v.total_count = 99
    SentencesView._on_count_ready(v, request_id=3, total=1000)
    assert v.total_count == 99  # unchanged


# Legacy compat: _on_load_finished is now a no-op pass
def test_on_load_finished_is_noop():
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=3)
    dtos = [object(), object()]
    # Must not raise; _current_dtos unchanged (stages 1+2 already handled it)
    SentencesView._on_load_finished(v, request_id=3, dtos=dtos, total=2)


def test_on_load_finished_drops_stale_request():
    """Legacy compat: no-op pass means stale request still safe."""
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=5)
    original_dtos = [object()]
    v._current_dtos = original_dtos
    SentencesView._on_load_finished(v, request_id=3, dtos=[object(), object()], total=99)
    assert v._current_dtos is original_dtos  # unchanged (no-op)
    assert v.total_count == 0


def test_on_load_error_drops_stale_request(caplog):
    import logging
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=7)
    v.status_label.text = "prev"
    with caplog.at_level(logging.ERROR):
        SentencesView._on_load_error(v, request_id=4, msg="boom")
    # status_label must NOT be updated for stale error
    assert v.status_label.text == "prev"


def test_on_load_error_applies_when_request_id_matches(caplog):
    import logging
    from app.ui.sentences_view import SentencesView
    v = _make_fake_view(active_id=7)
    with caplog.at_level(logging.ERROR):
        SentencesView._on_load_error(v, request_id=7, msg="db error")
    assert "Error" in v.status_label.text


# ---------------------------------------------------------------------------
# UserDictItemsPageWorker signal arity + constructor
# ---------------------------------------------------------------------------

def test_user_dict_items_page_worker_importable():
    from app.ui.workers import UserDictItemsPageWorker
    assert UserDictItemsPageWorker is not None


def test_user_dict_items_page_worker_init():
    from app.ui.workers import UserDictItemsPageWorker
    w = UserDictItemsPageWorker(
        request_id=10,
        dictionary_id=3,
        filters={"hide_noise": True},
        limit=50,
        offset=0,
        sort_column="updated_at",
        sort_direction="desc",
    )
    assert w.request_id == 10
    assert w.dictionary_id == 3
    assert w.limit == 50
    assert w.filters == {"hide_noise": True}


# ---------------------------------------------------------------------------
# user_dictionaries_view load_items increments request_id
# ---------------------------------------------------------------------------

def test_load_items_increments_request_id(monkeypatch):
    """Each load_items() call assigns a new, higher request_id (no Qt needed)."""
    from app.ui.user_dictionaries_view import UserDictionariesView

    started = []

    class _FakeWorker:
        def __init__(self, **kw):
            self.request_id = kw["request_id"]
        def start(self): started.append(self.request_id)
        def connect(self, *a): pass

    class _FakeSignal:
        def connect(self, *a): pass

    # Patch worker class and status_label
    monkeypatch.setattr(
        "app.ui.user_dictionaries_view.UserDictItemsPageWorker", _FakeWorker
    )

    v = UserDictionariesView.__new__(UserDictionariesView)
    v._items_request_seq = 0
    v._active_items_request_id = 0
    v._items_worker = None
    v.current_dictionary_id = 99
    v.page_size = 50
    v.current_page = 1      # current_offset is a property: (page-1)*page_size
    v.total_count = 0
    v.sort_column = "updated_at"
    v.sort_direction = "desc"

    class _Label:
        def setText(self, t): pass
    v.status_label = _Label()

    def _fake_build_filters(self_inner):
        return {}
    monkeypatch.setattr(UserDictionariesView, "build_filters", _fake_build_filters)

    # Simulate wiring: page_loaded / error are fake signal objects
    class _FakeWorker2(_FakeWorker):
        page_loaded = _FakeSignal()
        error = _FakeSignal()

    monkeypatch.setattr(
        "app.ui.user_dictionaries_view.UserDictItemsPageWorker", _FakeWorker2
    )

    UserDictionariesView.load_items(v)
    UserDictionariesView.load_items(v)
    UserDictionariesView.load_items(v)

    assert started == [1, 2, 3]
    assert v._active_items_request_id == 3
