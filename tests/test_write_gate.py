"""Tests for process-local write serialization gate."""

from __future__ import annotations

import threading
import time

from app.infra.write_gate import run_serialized_db_write, serialized_db_write


def test_run_serialized_db_write_serializes_threads() -> None:
    intervals: dict[str, tuple[float, float]] = {}
    active_writers = 0
    max_parallel_writers = 0
    state_lock = threading.Lock()
    start_barrier = threading.Barrier(3)

    def worker(name: str, hold_seconds: float) -> None:
        nonlocal active_writers, max_parallel_writers
        start_barrier.wait()

        def _critical_write() -> None:
            nonlocal active_writers, max_parallel_writers
            started_at = time.perf_counter()
            with state_lock:
                active_writers += 1
                max_parallel_writers = max(max_parallel_writers, active_writers)

            time.sleep(hold_seconds)

            ended_at = time.perf_counter()
            with state_lock:
                active_writers -= 1
                intervals[name] = (started_at, ended_at)

        run_serialized_db_write(
            f"test.{name}",
            _critical_write,
            warn_wait_ms=0.0,
            warn_hold_ms=10_000.0,
        )

    t1 = threading.Thread(target=worker, args=("writer_a", 0.12), daemon=True)
    t2 = threading.Thread(target=worker, args=("writer_b", 0.12), daemon=True)
    t1.start()
    t2.start()
    start_barrier.wait()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert max_parallel_writers == 1
    assert len(intervals) == 2

    a_start, a_end = intervals["writer_a"]
    b_start, b_end = intervals["writer_b"]
    assert (a_end <= b_start) or (b_end <= a_start)


def test_serialized_db_write_allows_reentrant_nesting_same_thread() -> None:
    with serialized_db_write("test.outer"):
        with serialized_db_write("test.inner"):
            pass


def test_run_serialized_db_write_returns_callback_result() -> None:
    value = run_serialized_db_write("test.return", lambda: 42)
    assert value == 42

