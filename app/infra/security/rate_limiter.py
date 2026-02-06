"""Rate limiting for HDLE Premium.

Implements token bucket algorithm for rate limiting import/export operations.
"""

import time
import threading
from typing import Optional
from contextlib import contextmanager

from .policy import MAX_IMPORTS_PER_MINUTE, MAX_EXPORTS_PER_MINUTE
from .errors import ValidationError


class RateLimiter:
    """
    Token bucket rate limiter.

    Limits operations to a maximum rate per minute using token bucket algorithm.

    Usage:
        limiter = RateLimiter(max_rate=100, window_seconds=60)

        # Check if operation allowed
        if limiter.is_allowed():
            perform_operation()
        else:
            raise Exception("Rate limit exceeded")

        # Or use context manager
        with limiter.check_limit("import"):
            perform_import()
    """

    def __init__(self, max_rate: int, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_rate: Maximum operations per window
            window_seconds: Time window in seconds (default: 60)
        """
        self.max_rate = max_rate
        self.window_seconds = window_seconds
        self.tokens = max_rate  # Start with full bucket
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def _refill_tokens(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        # Calculate tokens to add (proportional to elapsed time)
        tokens_to_add = (elapsed / self.window_seconds) * self.max_rate

        # Refill tokens (cap at max_rate)
        self.tokens = min(self.max_rate, self.tokens + tokens_to_add)
        self.last_refill = now

    def is_allowed(self, tokens: int = 1) -> bool:
        """
        Check if operation is allowed (non-blocking).

        Args:
            tokens: Number of tokens to consume (default: 1)

        Returns:
            True if operation allowed, False if rate limit exceeded
        """
        with self._lock:
            self._refill_tokens()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    def wait_if_needed(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """
        Wait until operation is allowed (blocking with timeout).

        Args:
            tokens: Number of tokens to consume (default: 1)
            timeout: Maximum wait time in seconds (None = wait indefinitely)

        Returns:
            True if operation allowed, False if timeout exceeded

        Raises:
            ValidationError: If timeout exceeded
        """
        start_time = time.time()

        while True:
            if self.is_allowed(tokens):
                return True

            # Check timeout
            if timeout is not None and (time.time() - start_time) >= timeout:
                raise ValidationError(
                    f"Rate limit exceeded: max {self.max_rate} operations per {self.window_seconds}s",
                    field="rate_limit",
                )

            # Sleep briefly before retry
            time.sleep(0.1)

    @contextmanager
    def check_limit(self, operation: str = "operation", tokens: int = 1):
        """
        Context manager for rate limiting.

        Args:
            operation: Operation name for error messages
            tokens: Number of tokens to consume (default: 1)

        Yields:
            None

        Raises:
            ValidationError: If rate limit exceeded

        Usage:
            with limiter.check_limit("import"):
                perform_import()
        """
        if not self.is_allowed(tokens):
            raise ValidationError(
                f"Rate limit exceeded for {operation}: "
                f"max {self.max_rate} operations per {self.window_seconds}s. "
                f"Please wait before retrying.",
                field="rate_limit",
            )

        yield

    def reset(self):
        """Reset rate limiter (refill all tokens)."""
        with self._lock:
            self.tokens = self.max_rate
            self.last_refill = time.time()


# Global rate limiters for import/export operations
_import_limiter: Optional[RateLimiter] = None
_export_limiter: Optional[RateLimiter] = None


def get_import_limiter() -> RateLimiter:
    """Get global import rate limiter (singleton)."""
    global _import_limiter
    if _import_limiter is None:
        _import_limiter = RateLimiter(max_rate=MAX_IMPORTS_PER_MINUTE, window_seconds=60)
    return _import_limiter


def get_export_limiter() -> RateLimiter:
    """Get global export rate limiter (singleton)."""
    global _export_limiter
    if _export_limiter is None:
        _export_limiter = RateLimiter(max_rate=MAX_EXPORTS_PER_MINUTE, window_seconds=60)
    return _export_limiter
