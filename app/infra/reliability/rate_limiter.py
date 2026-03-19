"""Rate limiter implementation for MT providers.

Uses token bucket algorithm to prevent hitting provider rate limits.

Strategy:
- Each provider has a bucket with tokens
- Each request consumes 1 token
- Tokens refill at configured rate (e.g., 60 req/min = 1 token/sec)
- If no tokens available, wait (up to max_wait_seconds) or fail
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""

    tokens: float = 60.0  # Current available tokens
    capacity: float = 60.0  # Max tokens (burst size)
    refill_rate: float = 1.0  # Tokens per second
    last_refill: datetime = field(default_factory=lambda: datetime.now(UTC))


class RateLimiter:
    """
    Token bucket rate limiter (in-memory, per provider).

    Usage:
        limiter = RateLimiter()
        limiter.configure_provider("deepl", requests_per_minute=60)

        # Before request
        if not limiter.acquire("deepl", max_wait_seconds=5.0):
            # Rate limit exceeded
            continue

        # Make request
        result = provider.translate(...)
    """

    def __init__(self):
        """Initialize rate limiter."""
        self._buckets: dict[str, TokenBucket] = {}  # provider_id → bucket

    def configure_provider(
        self,
        provider_id: str,
        requests_per_minute: int = 60,
    ) -> None:
        """
        Configure rate limit for provider.

        Args:
            provider_id: Provider ID
            requests_per_minute: Max requests per minute
        """
        refill_rate = requests_per_minute / 60.0  # tokens per second

        self._buckets[provider_id] = TokenBucket(
            tokens=float(requests_per_minute),
            capacity=float(requests_per_minute),
            refill_rate=refill_rate,
        )

        logger.debug(
            f"Rate limiter {provider_id}: Configured {requests_per_minute} req/min "
            f"({refill_rate:.2f} tokens/sec)"
        )

    def acquire(
        self,
        provider_id: str,
        max_wait_seconds: float = 5.0,
    ) -> bool:
        """
        Acquire token for request.

        Args:
            provider_id: Provider ID
            max_wait_seconds: Maximum time to wait for token (0 = no wait)

        Returns:
            True if token acquired, False if rate limit exceeded
        """
        bucket = self._buckets.get(provider_id)
        if not bucket:
            # No rate limit configured → allow
            return True

        # Refill tokens based on time elapsed
        now = datetime.now(UTC)
        elapsed = (now - bucket.last_refill).total_seconds()
        refill_amount = elapsed * bucket.refill_rate
        bucket.tokens = min(bucket.capacity, bucket.tokens + refill_amount)
        bucket.last_refill = now

        # Check if token available
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True

        # No tokens available → wait?
        if max_wait_seconds > 0:
            wait_time = (1.0 - bucket.tokens) / bucket.refill_rate
            if wait_time <= max_wait_seconds:
                logger.info(
                    f"Rate limiter {provider_id}: Waiting {wait_time:.2f}s for token "
                    f"(bucket: {bucket.tokens:.2f}/{bucket.capacity})"
                )
                time.sleep(wait_time)
                bucket.tokens = 0.0  # Consumed
                bucket.last_refill = datetime.now(UTC)
                return True

        # Rate limit exceeded
        logger.warning(
            f"Rate limiter {provider_id}: Rate limit exceeded "
            f"(bucket: {bucket.tokens:.2f}/{bucket.capacity}, "
            f"refill: {bucket.refill_rate:.2f} tokens/sec)"
        )
        return False

    def get_status(self, provider_id: str) -> dict[str, float]:
        """
        Get rate limiter status for provider (for debugging/monitoring).

        Args:
            provider_id: Provider ID

        Returns:
            Status dict with tokens, capacity, refill_rate
        """
        bucket = self._buckets.get(provider_id)
        if not bucket:
            return {"tokens": 0.0, "capacity": 0.0, "refill_rate": 0.0}

        # Update tokens before returning status
        now = datetime.now(UTC)
        elapsed = (now - bucket.last_refill).total_seconds()
        refill_amount = elapsed * bucket.refill_rate
        current_tokens = min(bucket.capacity, bucket.tokens + refill_amount)

        return {
            "tokens": current_tokens,
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
        }

    def reset(self, provider_id: str) -> None:
        """
        Reset rate limiter for provider (refill to capacity).

        Args:
            provider_id: Provider ID
        """
        bucket = self._buckets.get(provider_id)
        if bucket:
            bucket.tokens = bucket.capacity
            bucket.last_refill = datetime.now(UTC)
            logger.info(f"Rate limiter {provider_id}: RESET (tokens refilled to {bucket.capacity})")
