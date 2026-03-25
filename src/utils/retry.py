"""Retry and backoff utilities for external API calls.

Provides:
- ``resilient_session`` — a ``requests.Session`` pre-configured with urllib3
  retry/backoff on transient HTTP status codes.
- ``@with_retry`` — a decorator for arbitrary callables (e.g. Stripe SDK calls)
  that retries on specified exception types with exponential backoff.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def resilient_session(
    retries: int = 3,
    backoff_factor: float = 1.0,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    """Return a ``requests.Session`` with automatic retry on transient errors.

    Args:
        retries: Maximum number of retry attempts.
        backoff_factor: Multiplier for exponential backoff between retries.
        status_forcelist: HTTP status codes that trigger a retry.

    Returns:
        A configured ``requests.Session``.
    """
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def with_retry(
    max_attempts: int = 3,
    backoff_factor: float = 1.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Decorator that retries a function on specified exceptions with exponential backoff.

    Args:
        max_attempts: Total number of attempts (including the first call).
        backoff_factor: Base sleep time in seconds; actual sleep is
            ``backoff_factor * (2 ** (attempt - 1))``.
        retryable_exceptions: Exception types that should trigger a retry.

    Returns:
        A decorator wrapping the target function.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__qualname__,
                            max_attempts,
                            exc,
                        )
                        raise
                    sleep_time = backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        "%s attempt %d/%d failed (%s), retrying in %.1fs",
                        func.__qualname__,
                        attempt,
                        max_attempts,
                        exc,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
            # Should not reach here, but satisfy type checker
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
