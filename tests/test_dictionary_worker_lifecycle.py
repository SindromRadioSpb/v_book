"""Regression tests for DictionaryView worker lifecycle safety."""

from types import SimpleNamespace

from app.ui.dictionary_view import DictionaryView


class _FakeWorker:
    def __init__(self, running=True, wait_returns=False):
        self._running = running
        self._wait_returns = wait_returns
        self.cancel_called = False
        self.deleted = False

    def isRunning(self):
        return self._running

    def cancel(self):
        self.cancel_called = True

    def wait(self, _timeout):
        return self._wait_returns

    def deleteLater(self):
        self.deleted = True


def test_perform_search_queues_when_search_worker_busy():
    """Do not replace/destroy running search worker; queue retry instead."""
    view = DictionaryView.__new__(DictionaryView)
    busy_worker = _FakeWorker(running=True, wait_returns=False)
    view.search_worker = busy_worker
    view._search_retry_pending = False

    DictionaryView.perform_search(view)

    assert busy_worker.cancel_called is True
    assert view.search_worker is busy_worker
    assert view._search_retry_pending is True


def test_search_worker_finished_triggers_queued_search(monkeypatch):
    """Queued search should run after running worker finishes."""
    view = DictionaryView.__new__(DictionaryView)
    worker = _FakeWorker(running=False, wait_returns=True)
    view.search_worker = worker
    view._search_retry_pending = True

    calls = {"count": 0}
    view.perform_search = lambda: calls.__setitem__("count", calls["count"] + 1)
    monkeypatch.setattr("app.ui.dictionary_view.QTimer.singleShot", lambda _ms, fn: fn())

    DictionaryView._on_search_worker_finished(view, worker, 1)

    assert worker.deleted is True
    assert view.search_worker is None
    assert calls["count"] == 1
    assert view._search_retry_pending is False


def test_start_translation_worker_defers_when_previous_busy():
    """When previous translation worker is still running, keep it and queue latest lemmas."""
    view = DictionaryView.__new__(DictionaryView)
    busy_worker = _FakeWorker(running=True, wait_returns=False)
    view.translation_worker = busy_worker
    view._pending_translation_lemmas = None

    lemmas = [SimpleNamespace(lemma_text="alpha")]
    DictionaryView.start_translation_worker(view, lemmas)

    assert busy_worker.cancel_called is True
    assert view.translation_worker is busy_worker
    assert view._pending_translation_lemmas == lemmas


def test_ignore_stale_translation_results():
    """Stale translation results must not mutate current page model."""
    view = DictionaryView.__new__(DictionaryView)
    view._active_translation_seq = 2
    calls = {"count": 0}
    view.lemma_model = SimpleNamespace(
        update_translations=lambda _results: calls.__setitem__("count", calls["count"] + 1)
    )

    DictionaryView.on_translation_results(view, {("a", "lemma"): "x"}, request_seq=1)

    assert calls["count"] == 0
