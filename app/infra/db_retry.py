"""Database retry utilities for handling transient SQLite errors."""
import logging
import time
from functools import wraps
from typing import Callable, TypeVar, Any

from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

T = TypeVar('T')


def retry_on_db_locked(
    max_retries: int = 3,
    initial_delay: float = 0.1,
    backoff_factor: float = 2.0,
    max_delay: float = 2.0
) -> Callable:
    """Decorator to retry database operations on 'database is locked' errors.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds before first retry (default: 0.1)
        backoff_factor: Multiplier for delay between retries (default: 2.0)
        max_delay: Maximum delay between retries in seconds (default: 2.0)

    Usage:
        @retry_on_db_locked(max_retries=3)
        def my_db_operation(session):
            # ... database operations ...
            session.commit()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            delay = initial_delay

            for attempt in range(max_retries + 1):  # +1 for initial attempt
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    # Check if it's a 'database is locked' error
                    if 'database is locked' in str(e).lower():
                        last_exception = e

                        if attempt < max_retries:
                            # Log retry attempt
                            logger.warning(
                                f"{func.__name__}: Database locked, retry {attempt + 1}/{max_retries} "
                                f"after {delay:.2f}s delay"
                            )

                            # Sleep before retry
                            time.sleep(delay)

                            # Increase delay for next retry (exponential backoff)
                            delay = min(delay * backoff_factor, max_delay)
                        else:
                            # Max retries exceeded
                            logger.error(
                                f"{func.__name__}: Database locked after {max_retries} retries, giving up"
                            )
                            raise
                    else:
                        # Different OperationalError, don't retry
                        raise
                except Exception:
                    # Other exceptions, don't retry
                    raise

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__}: Unexpected retry loop exit")

        return wrapper
    return decorator


def with_retry_on_locked(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    **kwargs: Any
) -> T:
    """Execute a function with retry on database locked errors.

    Non-decorator version for use in contexts where decorators aren't convenient.

    Args:
        func: Function to execute
        *args: Positional arguments for func
        max_retries: Maximum number of retry attempts
        **kwargs: Keyword arguments for func

    Returns:
        Result of func(*args, **kwargs)

    Usage:
        result = with_retry_on_locked(session.commit, max_retries=3)
    """
    delay = 0.1
    backoff_factor = 2.0
    max_delay = 2.0
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except OperationalError as e:
            if 'database is locked' in str(e).lower():
                last_exception = e

                if attempt < max_retries:
                    logger.warning(
                        f"Database locked, retry {attempt + 1}/{max_retries} "
                        f"after {delay:.2f}s delay"
                    )
                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)
                else:
                    logger.error(f"Database locked after {max_retries} retries")
                    raise
            else:
                raise
        except Exception:
            raise

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")
