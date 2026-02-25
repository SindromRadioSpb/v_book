"""Database retry utilities for handling transient SQLite lock windows."""

import logging
import time
from functools import wraps
from typing import Any, Callable, Optional, Sequence, TypeVar

from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Retry delays produce 5 attempts total: first try + 4 retries.
DEFAULT_BACKOFF_SCHEDULE: tuple[float, ...] = (0.2, 0.5, 1.0, 2.0)


def _is_locked_operational_error(exc: OperationalError) -> bool:
    msg = str(exc).lower()
    return (
        "database is locked" in msg
        or "database table is locked" in msg
        or "sqlite_busy" in msg
        or "database is busy" in msg
    )


def _rollback_from_callable(
    func: Callable[..., Any],
    rollback_callback: Optional[Callable[[], None]],
) -> None:
    rollback_fn = rollback_callback
    if rollback_fn is None:
        bound_obj = getattr(func, "__self__", None)
        candidate = getattr(bound_obj, "rollback", None) if bound_obj is not None else None
        if callable(candidate):
            rollback_fn = candidate

    if rollback_fn is None:
        return

    try:
        rollback_fn()
    except Exception:
        logger.warning("Rollback after database lock failed", exc_info=True)


def _build_backoff_schedule(
    *,
    retries: int,
    backoff_schedule: Optional[Sequence[float]],
    initial_delay: Optional[float],
    backoff_factor: float,
    max_delay: float,
) -> tuple[float, ...]:
    if backoff_schedule is not None:
        values = tuple(float(v) for v in backoff_schedule if float(v) >= 0.0)
        if values:
            return values

    if initial_delay is None:
        return DEFAULT_BACKOFF_SCHEDULE

    delay = max(0.0, float(initial_delay))
    factor = max(1.0, float(backoff_factor))
    cap = max(0.0, float(max_delay))
    values = []
    for _ in range(max(1, retries)):
        values.append(min(delay, cap))
        delay = min(delay * factor, cap)
    return tuple(values) if values else DEFAULT_BACKOFF_SCHEDULE


def retry_on_db_locked(
    max_retries: int = 4,
    backoff_schedule: Optional[Sequence[float]] = None,
    initial_delay: Optional[float] = None,
    backoff_factor: float = 2.0,
    max_delay: float = 2.0,
) -> Callable:
    """Decorator: retry function on transient SQLite lock errors.

    Args:
        max_retries: Number of retries after initial attempt.
        backoff_schedule: Delay schedule in seconds (last value repeats).
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            rollback_cb = None
            if args:
                candidate = getattr(args[0], "rollback", None)
                if callable(candidate):
                    rollback_cb = candidate
            schedule = _build_backoff_schedule(
                retries=max(0, int(max_retries)),
                backoff_schedule=backoff_schedule,
                initial_delay=initial_delay,
                backoff_factor=backoff_factor,
                max_delay=max_delay,
            )
            return with_retry_on_locked(
                func,
                *args,
                max_retries=max_retries,
                backoff_schedule=schedule,
                rollback_callback=rollback_cb,
                **kwargs,
            )

        return wrapper

    return decorator


def with_retry_on_locked(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 4,
    backoff_schedule: Optional[Sequence[float]] = None,
    initial_delay: Optional[float] = None,
    backoff_factor: float = 2.0,
    max_delay: float = 2.0,
    rollback_callback: Optional[Callable[[], None]] = None,
    retry_callback: Optional[Callable[[int, int, float, str], None]] = None,
    **kwargs: Any,
) -> T:
    """Execute function with retry/backoff for transient SQLite lock windows.

    Args:
        func: Function to execute.
        max_retries: Number of retries after initial attempt.
        backoff_schedule: Delay schedule in seconds (last value repeats).
        rollback_callback: Optional callback invoked after lock errors.
        retry_callback: Optional callback(attempt, total_attempts, delay, error).
    """

    retries = max(0, int(max_retries))
    total_attempts = retries + 1
    schedule = _build_backoff_schedule(
        retries=retries,
        backoff_schedule=backoff_schedule,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor,
        max_delay=max_delay,
    )

    last_exception: Optional[OperationalError] = None

    for attempt_idx in range(total_attempts):
        try:
            return func(*args, **kwargs)
        except OperationalError as exc:
            if not _is_locked_operational_error(exc):
                raise

            last_exception = exc
            _rollback_from_callable(func, rollback_callback)

            if attempt_idx >= retries:
                logger.error("Database lock persisted after %s attempt(s)", total_attempts)
                raise

            delay = schedule[min(attempt_idx, len(schedule) - 1)]
            attempt_no = attempt_idx + 1
            logger.warning(
                "Database busy, retrying %s/%s after %.2fs",
                attempt_no,
                total_attempts,
                delay,
            )
            if retry_callback:
                try:
                    retry_callback(attempt_no, total_attempts, delay, str(exc))
                except Exception:
                    logger.debug("Retry callback failed", exc_info=True)

            time.sleep(delay)

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")
