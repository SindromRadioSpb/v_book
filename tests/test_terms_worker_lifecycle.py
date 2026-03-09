"""Regression tests for TermsView translation worker lifecycle."""

from types import SimpleNamespace

from app.ui.terms_view import TermsView


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


def test_terms_start_translation_worker_defers_when_previous_busy():
    """Busy translation worker should be kept alive and latest clusters queued."""
    view = TermsView.__new__(TermsView)
    busy_worker = _FakeWorker(running=True, wait_returns=False)
    view.translation_worker = busy_worker
    view._pending_translation_clusters = None

    clusters = [SimpleNamespace(representative_he="alpha")]
    TermsView.start_translation_worker(view, clusters)

    assert busy_worker.cancel_called is True
    assert view.translation_worker is busy_worker
    assert view._pending_translation_clusters == clusters


def test_terms_translation_worker_finished_triggers_queued_request(monkeypatch):
    """Queued translation request should restart after worker shutdown."""
    view = TermsView.__new__(TermsView)
    worker = _FakeWorker(running=False, wait_returns=True)
    view.translation_worker = worker
    view._pending_translation_clusters = [SimpleNamespace(representative_he="next")]

    calls = {"clusters": None}
    view.start_translation_worker = lambda clusters: calls.__setitem__("clusters", clusters)
    monkeypatch.setattr("app.ui.terms_view.QTimer.singleShot", lambda _ms, fn: fn())

    TermsView._on_translation_worker_finished(view, worker, 1)

    assert worker.deleted is True
    assert view.translation_worker is None
    assert calls["clusters"] is not None
    assert calls["clusters"][0].representative_he == "next"
    assert view._pending_translation_clusters is None


def test_terms_ignore_stale_translation_results():
    """Stale term translation results must not mutate current model."""
    view = TermsView.__new__(TermsView)
    view._active_translation_seq = 2
    calls = {"count": 0}
    view.terms_model = SimpleNamespace(
        update_translations=lambda _results: calls.__setitem__("count", calls["count"] + 1)
    )

    TermsView.on_translation_results(view, {("a", "term_cluster"): "x"}, request_seq=1)

    assert calls["count"] == 0
