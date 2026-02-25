"""Regression tests for SQLite lock retry/rollback hygiene."""

import pytest
from sqlalchemy.exc import OperationalError

from app.infra.db_retry import with_retry_on_locked


def _locked_error() -> OperationalError:
    return OperationalError(
        "UPDATE tm_entry SET translation = :translation",
        {"translation": "x"},
        Exception("database is locked"),
    )


def test_sqlite_busy_retry_succeeds():
    attempts = {"count": 0}
    rollbacks = {"count": 0}
    retries = []

    def _op():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _locked_error()
        return "ok"

    def _rollback():
        rollbacks["count"] += 1

    def _retry(attempt: int, total_attempts: int, _delay: float, _error: str):
        retries.append((attempt, total_attempts))

    out = with_retry_on_locked(
        _op,
        max_retries=4,
        backoff_schedule=(0.0, 0.0, 0.0, 0.0),
        rollback_callback=_rollback,
        retry_callback=_retry,
    )

    assert out == "ok"
    assert attempts["count"] == 3
    assert rollbacks["count"] == 2
    assert retries == [(1, 5), (2, 5)]


def test_session_rollback_on_flush_error():
    attempts = {"count": 0}
    rollbacks = {"count": 0}

    def _always_locked():
        attempts["count"] += 1
        raise _locked_error()

    def _rollback():
        rollbacks["count"] += 1

    with pytest.raises(OperationalError):
        with_retry_on_locked(
            _always_locked,
            max_retries=1,
            backoff_schedule=(0.0,),
            rollback_callback=_rollback,
        )

    # Initial attempt + 1 retry.
    assert attempts["count"] == 2
    # Rollback happens for every lock failure, including final give-up.
    assert rollbacks["count"] == 2
