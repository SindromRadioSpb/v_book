"""Worker-level regressions for translation session usage and cancellation."""

from types import SimpleNamespace

from app.ui.workers import SingleTextTranslateWorker, TranslationResolveWorker


def test_translation_resolve_worker_uses_read_session(monkeypatch):
    calls = []

    class _FakeSessionCtx:
        def __enter__(self):
            calls.append("read_enter")
            return "READ_SESSION"

        def __exit__(self, exc_type, exc, tb):
            calls.append("read_exit")
            return False

    class _FakeDB:
        def get_read_session(self):
            return _FakeSessionCtx()

        def get_session(self):
            raise AssertionError("write session should not be used for overlay translation")

    class _FakeTranslationService:
        def bulk_resolve(self, session, items, **_kwargs):
            calls.append(("bulk_resolve", session, list(items)))
            return {}

    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _FakeDB())
    monkeypatch.setattr("app.services.translation_service.TranslationService", _FakeTranslationService)

    worker = TranslationResolveWorker(items=[("alpha", "lemma")], project_id=1)
    worker.run()

    assert calls[0] == "read_enter"
    assert calls[1] == ("bulk_resolve", "READ_SESSION", [("alpha", "lemma")])


def test_single_text_translate_worker_cancel_suppresses_result(monkeypatch, qtbot):
    class _FakeSessionCtx:
        def __enter__(self):
            return "WRITE_SESSION"

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeDB:
        def get_session(self):
            return _FakeSessionCtx()

    class _FakeTranslationService:
        def resolve_translation(self, *_args, **_kwargs):
            return SimpleNamespace(translation="done", source="mt", provider="fake")

    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _FakeDB())
    monkeypatch.setattr("app.services.translation_service.TranslationService", _FakeTranslationService)

    worker = SingleTextTranslateWorker(text="hello", src_lang="en", tgt_lang="ru")
    captured = []
    worker.result_ready.connect(lambda result: captured.append(result))

    worker.cancel()
    worker.run()
    qtbot.wait(0)

    assert captured == []
