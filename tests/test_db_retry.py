"""Tests for database retry mechanism."""
import pytest
from unittest.mock import Mock, call
from sqlalchemy.exc import OperationalError

from app.infra.db_retry import retry_on_db_locked, with_retry_on_locked


def test_retry_on_db_locked_success():
    """Test: Function succeeds on first attempt."""
    mock_func = Mock(return_value="success")

    @retry_on_db_locked(max_retries=3)
    def test_function():
        return mock_func()

    result = test_function()

    assert result == "success"
    assert mock_func.call_count == 1


def test_retry_on_db_locked_retry_once():
    """Test: Function fails once with database locked, then succeeds."""
    mock_func = Mock(side_effect=[
        OperationalError("statement", "params", "database is locked"),
        "success"
    ])

    @retry_on_db_locked(max_retries=3, initial_delay=0.01)
    def test_function():
        return mock_func()

    result = test_function()

    assert result == "success"
    assert mock_func.call_count == 2


def test_retry_on_db_locked_max_retries():
    """Test: Function fails with database locked until max retries, then raises."""
    mock_func = Mock(side_effect=OperationalError("statement", "params", "database is locked"))

    @retry_on_db_locked(max_retries=2, initial_delay=0.01)
    def test_function():
        return mock_func()

    with pytest.raises(OperationalError) as exc_info:
        test_function()

    assert "database is locked" in str(exc_info.value)
    assert mock_func.call_count == 3  # Initial + 2 retries


def test_retry_on_db_locked_non_lock_error():
    """Test: Other OperationalErrors are not retried."""
    mock_func = Mock(side_effect=OperationalError("statement", "params", "syntax error"))

    @retry_on_db_locked(max_retries=3)
    def test_function():
        return mock_func()

    with pytest.raises(OperationalError) as exc_info:
        test_function()

    assert "syntax error" in str(exc_info.value)
    assert mock_func.call_count == 1  # No retries


def test_retry_on_db_locked_other_exception():
    """Test: Other exceptions are not retried."""
    mock_func = Mock(side_effect=ValueError("test error"))

    @retry_on_db_locked(max_retries=3)
    def test_function():
        return mock_func()

    with pytest.raises(ValueError) as exc_info:
        test_function()

    assert "test error" in str(exc_info.value)
    assert mock_func.call_count == 1  # No retries


def test_with_retry_on_locked_success():
    """Test: with_retry_on_locked succeeds on first attempt."""
    mock_func = Mock(return_value="success")

    result = with_retry_on_locked(mock_func, max_retries=3)

    assert result == "success"
    assert mock_func.call_count == 1


def test_with_retry_on_locked_retry_once():
    """Test: with_retry_on_locked retries once."""
    mock_func = Mock(side_effect=[
        OperationalError("statement", "params", "database is locked"),
        "success"
    ])

    result = with_retry_on_locked(mock_func, max_retries=3)

    assert result == "success"
    assert mock_func.call_count == 2


def test_with_retry_on_locked_with_args():
    """Test: with_retry_on_locked passes arguments correctly."""
    mock_func = Mock(return_value="success")

    result = with_retry_on_locked(mock_func, "arg1", "arg2", kwarg1="value1", max_retries=3)

    assert result == "success"
    mock_func.assert_called_once_with("arg1", "arg2", kwarg1="value1")
