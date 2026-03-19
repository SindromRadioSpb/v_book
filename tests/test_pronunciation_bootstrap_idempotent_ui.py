"""Worker-level tests for UI pronunciation bootstrap flow."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.operations_center import OperationEntry, OperationsCenterBusyError
from app.ui.workers import PronunciationBootstrapWorker


class _DummySession:
    def __init__(self):
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


class _DummySessionCtx:
    def __init__(self, session: _DummySession):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyDB:
    def __init__(self, session: _DummySession):
        self._session = session

    def get_session(self):
        return _DummySessionCtx(self._session)


class _DummyGenerator:
    def __init__(self, *args, **kwargs):
        _ = args
        _ = kwargs

    @dataclass
    class _Health:
        mode: str = "fallback"
        status: str = "fallback"
        latency_ms: int = 1
        cancelled: bool = False

    def health_check(self, *_, **__):
        return self._Health()


@dataclass
class _DummyBootstrapResult:
    total_candidates: int = 2
    generated_candidates: int = 2
    updated: int = 0
    skipped: int = 2
    failed: int = 0
    cancelled: bool = False
    generator_mode: str = "fallback"


class _DummyBootstrapService:
    def __init__(self, generator=None):
        self.generator = generator

    def bootstrap(self, session, **kwargs):
        _ = session
        _ = kwargs
        return _DummyBootstrapResult()


def test_bootstrap_worker_dry_run_rolls_back(monkeypatch):
    session = _DummySession()
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _DummyDB(session))
    monkeypatch.setattr(
        "app.services.pronunciation_bootstrap_service.PhonikudPronunciationGenerator",
        _DummyGenerator,
    )
    monkeypatch.setattr(
        "app.services.pronunciation_bootstrap_service.PronunciationBootstrapService",
        _DummyBootstrapService,
    )

    worker = PronunciationBootstrapWorker(
        lang="he",
        model_path="",
        enabled=True,
        chunk_size=100,
        dry_run=True,
    )
    result = {}
    worker.finished.connect(lambda payload: result.update(payload))
    worker.run()

    assert session.rollback_calls == 1
    assert session.commit_calls == 0
    assert result["dry_run"] is True
    assert result["updated"] == 0


def test_bootstrap_worker_commit_when_not_dry_run(monkeypatch):
    session = _DummySession()
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _DummyDB(session))
    monkeypatch.setattr(
        "app.services.pronunciation_bootstrap_service.PhonikudPronunciationGenerator",
        _DummyGenerator,
    )
    monkeypatch.setattr(
        "app.services.pronunciation_bootstrap_service.PronunciationBootstrapService",
        _DummyBootstrapService,
    )

    worker = PronunciationBootstrapWorker(
        lang="he",
        model_path="",
        enabled=True,
        chunk_size=100,
        dry_run=False,
    )
    worker.run()

    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_bootstrap_worker_finishes_cancelled_when_health_check_is_cancelled(monkeypatch):
    session = _DummySession()
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: _DummyDB(session))

    class _CancelledGenerator(_DummyGenerator):
        @dataclass
        class _Health:
            mode: str = "error"
            status: str = "error"
            latency_ms: int = 1
            cancelled: bool = True

    monkeypatch.setattr(
        "app.services.pronunciation_bootstrap_service.PhonikudPronunciationGenerator",
        _CancelledGenerator,
    )
    monkeypatch.setattr(
        "app.services.pronunciation_bootstrap_service.PronunciationBootstrapService",
        _DummyBootstrapService,
    )

    worker = PronunciationBootstrapWorker(
        lang="he",
        model_path="",
        enabled=True,
        chunk_size=100,
        dry_run=False,
    )
    result = {}
    worker.finished.connect(lambda payload: result.update(payload))
    worker.cancel()
    worker.run()

    assert result["cancelled"] is True
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


def test_bootstrap_worker_reports_busy_when_heavy_slot_taken(monkeypatch):
    class _FakeOpsCenter:
        def register(self, *_args, **_kwargs):
            raise OperationsCenterBusyError(
                "pronunciation_bootstrap",
                [
                    OperationEntry(
                        op_id="op-1", name="NLP Process (42 docs)", category="nlp_process"
                    )
                ],
            )

        def unregister(self, _op_id):
            return None

    from app.services.operations_center import OperationsCenter

    monkeypatch.setattr(OperationsCenter, "instance", classmethod(lambda cls: _FakeOpsCenter()))

    worker = PronunciationBootstrapWorker(
        lang="he",
        model_path="",
        enabled=True,
        chunk_size=100,
        dry_run=False,
    )
    errors = []
    worker.error.connect(errors.append)
    worker.run()

    assert errors
    assert "Pronunciation Bootstrap" in errors[0]
    assert "NLP Process (42 docs)" in errors[0]
