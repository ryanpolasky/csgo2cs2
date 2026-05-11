# Retry + exponential backoff helper.
#
# Wraps a callable so transient failures (network blips, JVM startup
# flakes, Steam throttling) retry automatically instead of bubbling up
# to the user as a fatal error.

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Tuple, Type, TypeVar

T = TypeVar("T")

# Default exception types worth retrying on. Callers can override.
DEFAULT_RETRYABLE: Tuple[Type[BaseException], ...] = (OSError,)


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 1.5  # seconds
    max_delay: float = 30.0
    factor: float = 2.0
    jitter: float = 0.0  # +/- this fraction; 0 = deterministic
    retryable: Tuple[Type[BaseException], ...] = DEFAULT_RETRYABLE


def _sleep_for_attempt(policy: RetryPolicy, attempt: int) -> float:
    # attempt is 1-based: 1st retry sleeps base_delay, 2nd sleeps
    # base_delay * factor, etc.
    delay = policy.base_delay * (policy.factor ** (attempt - 1))
    return min(delay, policy.max_delay)


def call_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy | None = None,
    *,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `fn()` with retries. Returns its result on first success.

    Raises the last exception when all attempts are exhausted.
    """
    pol = policy or RetryPolicy()
    last_exc: BaseException | None = None
    for i in range(1, pol.attempts + 1):
        try:
            return fn()
        except pol.retryable as exc:
            last_exc = exc
            if i == pol.attempts:
                break
            delay = _sleep_for_attempt(pol, i)
            if on_retry is not None:
                on_retry(i, exc, delay)
            sleep(delay)
    # all attempts exhausted -- re-raise the last exception
    assert last_exc is not None
    raise last_exc


def retry_until(
    fn: Callable[[], T],
    *,
    predicate: Callable[[T], bool],
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, T, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `fn()` repeatedly until `predicate(result)` is true.

    Useful for things that don't raise on failure but return a result
    we can inspect (e.g. a subprocess.CompletedProcess whose returncode
    indicates failure).
    """
    pol = policy or RetryPolicy()
    last_result: T | None = None
    for i in range(1, pol.attempts + 1):
        last_result = fn()
        if predicate(last_result):
            return last_result
        if i == pol.attempts:
            break
        delay = _sleep_for_attempt(pol, i)
        if on_retry is not None:
            on_retry(i, last_result, delay)
        sleep(delay)
    assert last_result is not None
    return last_result
