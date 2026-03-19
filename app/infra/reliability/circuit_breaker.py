"""Circuit breaker implementation for MT providers.

Prevents cascading failures by stopping calls to failing providers.

States:
- CLOSED (normal): Allow all requests
- OPEN (failed): Block all requests
- HALF_OPEN (testing): Allow 1 test request

Transitions:
CLOSED --[failure_threshold reached]--> OPEN
OPEN --[cooldown_period expired]--> HALF_OPEN
HALF_OPEN --[test request succeeds]--> CLOSED
HALF_OPEN --[test request fails]--> OPEN
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerStatus:
    """Circuit breaker status for a provider."""

    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    last_failure_time: datetime | None = None
    last_state_change: datetime = field(default_factory=lambda: datetime.now(UTC))


class CircuitBreaker:
    """
    Circuit breaker implementation (in-memory, per provider).

    Usage:
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)

        # Before request
        if not breaker.is_request_allowed(provider_id):
            # Circuit OPEN → skip provider
            continue

        # After request
        result = provider.translate(...)
        if result.is_success:
            breaker.record_success(provider_id)
        else:
            breaker.record_failure(provider_id)
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: int = 60,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            cooldown_seconds: Cooldown period before transitioning OPEN → HALF_OPEN
        """
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._states: dict[str, CircuitBreakerStatus] = {}  # provider_id → status

    def get_state(self, provider_id: str) -> CircuitBreakerState:
        """
        Get current state for provider.

        Args:
            provider_id: Provider ID

        Returns:
            Current circuit breaker state
        """
        status = self._states.get(provider_id)
        if not status:
            # No state yet → default to CLOSED
            status = CircuitBreakerStatus()
            self._states[provider_id] = status

        # Check if OPEN should transition to HALF_OPEN
        if status.state == CircuitBreakerState.OPEN:
            time_since_change = datetime.now(UTC) - status.last_state_change
            if time_since_change > timedelta(seconds=self._cooldown_seconds):
                # Cooldown expired → transition to HALF_OPEN
                logger.info(f"Circuit breaker {provider_id}: OPEN → HALF_OPEN (cooldown expired)")
                status.state = CircuitBreakerState.HALF_OPEN
                status.last_state_change = datetime.now(UTC)
                self._states[provider_id] = status

        return status.state

    def is_request_allowed(self, provider_id: str) -> bool:
        """
        Check if request is allowed (not blocked by circuit breaker).

        Args:
            provider_id: Provider ID

        Returns:
            True if request allowed, False if blocked (circuit OPEN)
        """
        state = self.get_state(provider_id)
        return state in (CircuitBreakerState.CLOSED, CircuitBreakerState.HALF_OPEN)

    def record_success(self, provider_id: str) -> None:
        """
        Record successful request.

        Args:
            provider_id: Provider ID
        """
        status = self._states.get(provider_id, CircuitBreakerStatus())

        if status.state == CircuitBreakerState.HALF_OPEN:
            # Test request succeeded → transition to CLOSED
            logger.info(
                f"Circuit breaker {provider_id}: HALF_OPEN → CLOSED (test request succeeded)"
            )
            status.state = CircuitBreakerState.CLOSED
            status.failure_count = 0
            status.last_state_change = datetime.now(UTC)
        elif status.state == CircuitBreakerState.CLOSED:
            # Reset failure count on success
            if status.failure_count > 0:
                logger.debug(
                    f"Circuit breaker {provider_id}: Reset failure count (was {status.failure_count})"
                )
            status.failure_count = 0

        self._states[provider_id] = status

    def record_failure(self, provider_id: str) -> None:
        """
        Record failed request.

        Args:
            provider_id: Provider ID
        """
        status = self._states.get(provider_id, CircuitBreakerStatus())

        if status.state == CircuitBreakerState.HALF_OPEN:
            # Test request failed → back to OPEN
            logger.warning(f"Circuit breaker {provider_id}: HALF_OPEN → OPEN (test request failed)")
            status.state = CircuitBreakerState.OPEN
            status.last_failure_time = datetime.now(UTC)
            status.last_state_change = datetime.now(UTC)
        elif status.state == CircuitBreakerState.CLOSED:
            status.failure_count += 1
            status.last_failure_time = datetime.now(UTC)

            logger.debug(
                f"Circuit breaker {provider_id}: Failure count {status.failure_count}/{self._failure_threshold}"
            )

            if status.failure_count >= self._failure_threshold:
                # Threshold reached → transition to OPEN
                logger.error(
                    f"Circuit breaker {provider_id}: CLOSED → OPEN "
                    f"(failure threshold {self._failure_threshold} reached)"
                )
                status.state = CircuitBreakerState.OPEN
                status.last_state_change = datetime.now(UTC)

        self._states[provider_id] = status

    def get_status(self, provider_id: str) -> CircuitBreakerStatus:
        """
        Get full status for provider (for debugging/monitoring).

        Args:
            provider_id: Provider ID

        Returns:
            Circuit breaker status
        """
        return self._states.get(provider_id, CircuitBreakerStatus())

    def reset(self, provider_id: str) -> None:
        """
        Reset circuit breaker for provider (force CLOSED).

        Args:
            provider_id: Provider ID
        """
        logger.info(f"Circuit breaker {provider_id}: RESET → CLOSED")
        self._states[provider_id] = CircuitBreakerStatus()
