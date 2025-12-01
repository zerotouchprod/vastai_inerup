"""Retry utilities with exponential backoff."""

import time
import random
from typing import Callable, TypeVar, Optional, Type, Tuple
from functools import wraps

T = TypeVar('T')


def retry_with_backoff(
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    exponential: bool = True,
    jitter: bool = True,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Decorator for retrying a function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts
        backoff_seconds: Initial backoff time in seconds
        exponential: Use exponential backoff (2^attempt * backoff_seconds)
        jitter: Add random jitter to backoff time
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Decorated function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        # Last attempt failed, re-raise
                        raise

                    # Calculate backoff time
                    if exponential:
                        wait_time = backoff_seconds * (2 ** (attempt - 1))
                    else:
                        wait_time = backoff_seconds * attempt

                    # Add jitter if enabled
                    if jitter:
                        wait_time = wait_time * (0.5 + random.random())

                    time.sleep(wait_time)

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError("Retry logic failed unexpectedly")

        return wrapper
    return decorator


class RetryStrategy:
    """Configurable retry strategy."""

    def __init__(
        self,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        exponential: bool = True,
        jitter: bool = True,
        max_backoff: float = 60.0
    ):
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.exponential = exponential
        self.jitter = jitter
        self.max_backoff = max_backoff

    def execute(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """
        Execute a function with retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Function result

        Raises:
            Last exception if all attempts fail
        """
        last_exception: Optional[Exception] = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt == self.max_attempts:
                    raise

                wait_time = self._calculate_backoff(attempt)
                time.sleep(wait_time)

        if last_exception:
            raise last_exception
        raise RuntimeError("Retry logic failed unexpectedly")

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time for given attempt number."""
        if self.exponential:
            wait_time = self.backoff_seconds * (2 ** (attempt - 1))
        else:
            wait_time = self.backoff_seconds * attempt

        # Cap at max_backoff
        wait_time = min(wait_time, self.max_backoff)

        # Add jitter
        if self.jitter:
            wait_time = wait_time * (0.5 + random.random())

        return wait_time

