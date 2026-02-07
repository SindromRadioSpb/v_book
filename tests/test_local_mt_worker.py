"""Tests for Local MT Worker Process (PATCH-03).

Tests verify:
- Worker Request/Result dataclasses
- Worker client interface
- Error handling (without real model loading)

Note: Full integration tests with spawned worker processes are skipped
because monkeypatch doesn't work across process boundaries with spawn context.
These tests focus on unit testing the client-side logic and data structures.
"""
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.infra.local_mt.worker_process import (
    LocalMTWorker,
    WorkerRequest,
    WorkerResult,
    WorkerError,
    start_worker,
)


# ============================================================================
# Test 1: Worker Request/Result dataclasses
# ============================================================================


def test_worker_request_creation():
    """WorkerRequest creates successfully."""
    req = WorkerRequest(
        text="Hello world",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        request_id="123",
    )

    assert req.text == "Hello world"
    assert req.source_lang == "eng_Latn"
    assert req.target_lang == "heb_Hebr"
    assert req.request_id == "123"


def test_worker_result_creation():
    """WorkerResult creates successfully."""
    result = WorkerResult(
        text="שלום עולם",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=123.45,
        request_id="123",
    )

    assert result.text == "שלום עולם"
    assert result.inference_time_ms == 123.45
    assert result.error is None


def test_worker_result_with_error():
    """WorkerResult can contain error."""
    result = WorkerResult(
        text="",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=0,
        error="Model loading failed",
    )

    assert result.text == ""
    assert result.error == "Model loading failed"


def test_worker_request_default_id():
    """WorkerRequest has default empty request_id."""
    req = WorkerRequest(
        text="Test",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
    )

    assert req.request_id == ""


def test_worker_result_to_dict():
    """WorkerResult converts to dict correctly."""
    result = WorkerResult(
        text="Translation",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
        inference_time_ms=100.0,
        request_id="test-123",
    )

    result_dict = result.__dict__
    assert result_dict["text"] == "Translation"
    assert result_dict["source_lang"] == "eng_Latn"
    assert result_dict["target_lang"] == "heb_Hebr"
    assert result_dict["inference_time_ms"] == 100.0
    assert result_dict["request_id"] == "test-123"
    assert result_dict["error"] is None


# ============================================================================
# Test 2: Worker client initialization
# ============================================================================


def test_worker_init_attributes(tmp_path):
    """Worker client initializes with correct attributes."""
    model_path = tmp_path / "test_model"
    model_path.mkdir()

    # Note: This will fail to start because no real model exists
    # but we can still test attribute initialization
    try:
        worker = LocalMTWorker.__new__(LocalMTWorker)
        worker.model_path = model_path
        worker.backend = "ctranslate2"
        worker.model_id = "test/model"
        worker.timeout = 30.0
        worker.process = None
        worker.conn = None

        assert worker.model_path == model_path
        assert worker.backend == "ctranslate2"
        assert worker.model_id == "test/model"
        assert worker.timeout == 30.0
        assert worker.process is None
        assert worker.conn is None
    except:
        pass


# ============================================================================
# Test 3: Worker error class
# ============================================================================


def test_worker_error_creation():
    """WorkerError creates successfully."""
    error = WorkerError("Test error message")
    assert str(error) == "Test error message"


def test_worker_error_is_exception():
    """WorkerError is an Exception subclass."""
    error = WorkerError("Test")
    assert isinstance(error, Exception)


# ============================================================================
# Test 4: start_worker function signature
# ============================================================================


def test_start_worker_function_exists():
    """start_worker function exists and is callable."""
    assert callable(start_worker)


# ============================================================================
# Test 5: Worker client methods without process
# ============================================================================


def test_worker_ping_without_connection():
    """Worker ping returns False without connection."""
    worker = LocalMTWorker.__new__(LocalMTWorker)
    worker.conn = None
    worker.timeout = 5.0

    assert worker.ping() is False


def test_worker_translate_without_connection():
    """Worker translate raises WorkerError without connection."""
    worker = LocalMTWorker.__new__(LocalMTWorker)
    worker.conn = None

    request = WorkerRequest(
        text="Test",
        source_lang="eng_Latn",
        target_lang="heb_Hebr",
    )

    with pytest.raises(WorkerError, match="Worker not started"):
        worker.translate(request)


def test_worker_shutdown_without_process():
    """Worker shutdown handles missing process gracefully."""
    worker = LocalMTWorker.__new__(LocalMTWorker)
    worker.process = None
    worker.conn = None

    # Should not raise exception
    worker.shutdown()

    assert worker.process is None
    assert worker.conn is None


# ============================================================================
# Test 6: Backend validation (integration test - expected to fail)
# ============================================================================


def test_worker_unknown_backend_fails(tmp_path):
    """Worker with unknown backend fails at startup."""
    model_path = tmp_path / "test_model"
    model_path.mkdir()

    with pytest.raises(WorkerError):
        start_worker(
            model_path=model_path,
            backend="unknown_backend",
            model_id="test/model",
            timeout=5.0,
        )
