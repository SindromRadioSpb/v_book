"""Tests for PERF-SCALE PATCH-K: PipelineThrottler.

Covers:
- is_slot_free() returns True when no heavy ops running
- is_slot_free() returns False when slot is occupied
- check_and_warn() returns True when slot free (no dialog)
- check_and_warn() returns False when slot occupied (dialog suppressed in test)
- format_blocked_reason() returns correct label
- Throttler does not interfere with non-heavy categories
- After unregister, slot becomes free again
"""

from __future__ import annotations

import pytest

from app.services.operations_center import OperationsCenter
from app.services.pipeline_throttler import PipelineThrottler


@pytest.fixture(autouse=True)
def reset():
    OperationsCenter.reset_for_tests()
    PipelineThrottler.reset_for_tests()
    yield
    OperationsCenter.reset_for_tests()
    PipelineThrottler.reset_for_tests()


# ---------------------------------------------------------------------------
# is_slot_free
# ---------------------------------------------------------------------------


def test_slot_free_when_idle():
    t = PipelineThrottler.instance()
    assert t.is_slot_free("nlp_process") is True
    assert t.is_slot_free("ingest") is True
    assert t.is_slot_free("term_extract") is True


def test_slot_blocked_when_occupied():
    t = PipelineThrottler.instance()
    op_id = OperationsCenter.instance().register("NLP run", "nlp_process")
    assert t.is_slot_free("nlp_process") is False
    OperationsCenter.instance().unregister(op_id)
    assert t.is_slot_free("nlp_process") is True


def test_different_heavy_categories_share_global_slot():
    t = PipelineThrottler.instance()
    op_id = OperationsCenter.instance().register("Ingest run", "ingest")
    assert t.is_slot_free("ingest") is False
    # nlp_process is blocked by the same global heavy slot
    assert t.is_slot_free("nlp_process") is False
    OperationsCenter.instance().unregister(op_id)


def test_non_heavy_category_always_free():
    t = PipelineThrottler.instance()
    # Fill non-heavy category
    for i in range(10):
        OperationsCenter.instance().register(f"search {i}", "search")
    assert t.is_slot_free("search") is True


# ---------------------------------------------------------------------------
# check_and_warn (no Qt parent — falls back to logger, returns bool)
# ---------------------------------------------------------------------------


def test_check_and_warn_returns_true_when_free():
    t = PipelineThrottler.instance()
    result = t.check_and_warn("nlp_process", parent=None, operation_label="Test Op")
    assert result is True


def test_check_and_warn_returns_false_when_blocked():
    t = PipelineThrottler.instance()
    op_id = OperationsCenter.instance().register("Current NLP run", "nlp_process")
    result = t.check_and_warn("nlp_process", parent=None, operation_label="New NLP Op")
    assert result is False
    OperationsCenter.instance().unregister(op_id)


# ---------------------------------------------------------------------------
# format_blocked_reason
# ---------------------------------------------------------------------------


def test_format_blocked_reason_empty_when_idle():
    t = PipelineThrottler.instance()
    assert t.format_blocked_reason("nlp_process") == ""


def test_format_blocked_reason_shows_running_op():
    t = PipelineThrottler.instance()
    op_id = OperationsCenter.instance().register("Big NLP batch", "nlp_process")
    reason = t.format_blocked_reason("nlp_process")
    assert "Big NLP batch" in reason
    OperationsCenter.instance().unregister(op_id)


def test_format_blocked_reason_uses_other_heavy_category_name():
    t = PipelineThrottler.instance()
    op_id = OperationsCenter.instance().register("Large Import", "project_import")
    reason = t.format_blocked_reason("nlp_process")
    assert reason == "Busy: Large Import"
    OperationsCenter.instance().unregister(op_id)


# ---------------------------------------------------------------------------
# Singleton identity
# ---------------------------------------------------------------------------


def test_singleton_same_instance():
    a = PipelineThrottler.instance()
    b = PipelineThrottler.instance()
    assert a is b
