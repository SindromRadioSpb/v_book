"""Tests for global heavy-operation governance in OperationsCenter.

Covers:
- register() returns unique op_id; entry appears in active_ops()
- unregister() removes entry; no-op for unknown id
- active_count() / heavy_count() track correctly
- is_slot_available() enforces the global heavy-operation slot
- is_slot_available() always True for non-heavy categories
- Concurrent register/unregister is thread-safe
- reset_for_tests() clears state between tests
"""
from __future__ import annotations

import threading
import time

import pytest

from app.services.operations_center import (
    HEAVY_CATEGORIES,
    MAX_HEAVY_CONCURRENT,
    OperationsCenter,
    OperationsCenterBusyError,
)


@pytest.fixture(autouse=True)
def reset_center():
    """Reset singleton before and after every test."""
    OperationsCenter.reset_for_tests()
    yield
    OperationsCenter.reset_for_tests()


# ---------------------------------------------------------------------------
# Basic register / unregister
# ---------------------------------------------------------------------------


def test_register_returns_unique_ids():
    center = OperationsCenter.instance()
    id1 = center.register("op A", "ingest")
    id2 = center.register("op B", "ingest")
    assert id1 != id2


def test_register_adds_to_active_ops():
    center = OperationsCenter.instance()
    assert center.active_count() == 0
    op_id = center.register("Test op", "nlp_process")
    assert center.active_count() == 1
    ops = center.active_ops()
    assert len(ops) == 1
    assert ops[0].op_id == op_id
    assert ops[0].name == "Test op"
    assert ops[0].category == "nlp_process"


def test_unregister_removes_entry():
    center = OperationsCenter.instance()
    op_id = center.register("to remove", "ingest")
    assert center.active_count() == 1
    center.unregister(op_id)
    assert center.active_count() == 0


def test_unregister_unknown_id_is_noop():
    center = OperationsCenter.instance()
    center.unregister("nonexistent-id")  # must not raise


def test_active_ops_snapshot_is_copy():
    center = OperationsCenter.instance()
    center.register("A", "ingest")
    snap1 = center.active_ops()
    center.register("B", "ingest")
    snap2 = center.active_ops()
    assert len(snap1) == 1
    assert len(snap2) == 2


# ---------------------------------------------------------------------------
# heavy_count
# ---------------------------------------------------------------------------


def test_heavy_count_counts_heavy_categories():
    center = OperationsCenter.instance()
    center.register("nlp op", "nlp_process")
    center.register("ingest op", "ingest")
    center.register("light op", "search")  # non-heavy
    assert center.heavy_count() == 2


def test_heavy_count_category_filter():
    center = OperationsCenter.instance()
    center.register("nlp op", "nlp_process")
    center.register("ingest op", "ingest")
    assert center.heavy_count("nlp_process") == 1
    assert center.heavy_count("ingest") == 1
    assert center.heavy_count("term_extract") == 0


# ---------------------------------------------------------------------------
# is_slot_available
# ---------------------------------------------------------------------------


def test_slot_available_before_any_heavy_op():
    center = OperationsCenter.instance()
    assert center.is_slot_available("nlp_process") is True
    assert center.is_slot_available("ingest") is True


def test_slot_unavailable_when_limit_reached():
    center = OperationsCenter.instance()
    # Fill up to MAX_HEAVY_CONCURRENT
    ids = [center.register(f"op {i}", "nlp_process") for i in range(MAX_HEAVY_CONCURRENT)]
    assert center.is_slot_available("nlp_process") is False
    # Unregistering one frees a slot
    center.unregister(ids[0])
    assert center.is_slot_available("nlp_process") is True


def test_slot_available_for_non_heavy_category():
    center = OperationsCenter.instance()
    # Even with many concurrent non-heavy ops, slot is always available
    for i in range(10):
        center.register(f"search {i}", "search")
    assert center.is_slot_available("search") is True


def test_different_heavy_categories_share_global_slot():
    """Any active heavy op blocks starting another heavy category."""
    center = OperationsCenter.instance()
    for _ in range(MAX_HEAVY_CONCURRENT):
        center.register("ingest op", "ingest")
    # ingest is blocked
    assert center.is_slot_available("ingest") is False
    # nlp_process is blocked by the same global heavy slot
    assert center.is_slot_available("nlp_process") is False


def test_register_enforce_limit_raises_when_heavy_slot_busy():
    center = OperationsCenter.instance()
    center.register("Existing ingest", "ingest")

    with pytest.raises(OperationsCenterBusyError) as exc_info:
        center.register("New NLP", "nlp_process", enforce_limit=True)

    assert exc_info.value.category == "nlp_process"
    assert [op.name for op in exc_info.value.active_ops] == ["Existing ingest"]


def test_blocking_ops_returns_all_active_heavy_ops_for_heavy_category():
    center = OperationsCenter.instance()
    center.register("Import", "project_import")
    center.register("NLP", "nlp_process")
    center.register("Search", "search")

    blocking = center.blocking_ops("term_extract")

    assert [op.name for op in blocking] == ["Import", "NLP"]


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_register_unregister_thread_safe():
    """Many threads registering and unregistering simultaneously must not corrupt state."""
    center = OperationsCenter.instance()
    errors: list[Exception] = []
    completed: list[int] = []

    def worker(n: int):
        try:
            op_id = center.register(f"thread op {n}", "search")
            time.sleep(0.001)
            center.unregister(op_id)
            completed.append(n)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
    assert len(completed) == 50
    assert center.active_count() == 0


# ---------------------------------------------------------------------------
# Singleton identity
# ---------------------------------------------------------------------------


def test_instance_returns_same_object():
    a = OperationsCenter.instance()
    b = OperationsCenter.instance()
    assert a is b
