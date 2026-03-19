"""Process-local write serialization gate for high-contention SQLite flows."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_WRITE_LOCK = threading.RLock()
_STATE_LOCK = threading.Lock()
_WAITING_WRITERS = 0


def get_waiting_writer_count() -> int:
    """Return number of threads currently waiting to enter serialized write section."""
    with _STATE_LOCK:
        return int(_WAITING_WRITERS)


@contextmanager
def serialized_db_write(
    operation: str,
    *,
    warn_wait_ms: float = 250.0,
    warn_hold_ms: float = 2000.0,
) -> Iterator[None]:
    """Serialize write windows and emit wait/hold telemetry."""
    global _WAITING_WRITERS

    wait_started = time.perf_counter()
    with _STATE_LOCK:
        queued_before = _WAITING_WRITERS
        _WAITING_WRITERS += 1

    _WRITE_LOCK.acquire()
    acquired_at = time.perf_counter()

    with _STATE_LOCK:
        _WAITING_WRITERS = max(0, _WAITING_WRITERS - 1)

    wait_ms = (acquired_at - wait_started) * 1000.0
    if wait_ms >= warn_wait_ms:
        logger.warning(
            "write_gate_wait operation=%s wait_ms=%.1f queued_before=%s thread=%s",
            operation,
            wait_ms,
            queued_before,
            threading.current_thread().name,
        )
    else:
        logger.debug(
            "write_gate_wait operation=%s wait_ms=%.1f queued_before=%s",
            operation,
            wait_ms,
            queued_before,
        )

    try:
        yield
    finally:
        released_at = time.perf_counter()
        hold_ms = (released_at - acquired_at) * 1000.0
        if hold_ms >= warn_hold_ms:
            logger.warning(
                "write_gate_hold operation=%s hold_ms=%.1f thread=%s",
                operation,
                hold_ms,
                threading.current_thread().name,
            )
        else:
            logger.debug("write_gate_hold operation=%s hold_ms=%.1f", operation, hold_ms)
        _WRITE_LOCK.release()


def run_serialized_db_write(
    operation: str,
    callback: Callable[[], T],
    *,
    warn_wait_ms: float = 250.0,
    warn_hold_ms: float = 2000.0,
) -> T:
    """Run callback under serialized_db_write and return callback result."""
    with serialized_db_write(
        operation,
        warn_wait_ms=warn_wait_ms,
        warn_hold_ms=warn_hold_ms,
    ):
        return callback()
