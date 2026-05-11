from __future__ import annotations

import pytest

from csgo2cs2.utils.retry import RetryPolicy, call_with_retry, retry_until


class _Boom(Exception):
    pass


def test_call_with_retry_succeeds_first_try() -> None:
    calls = {"n": 0}

    def f():
        calls["n"] += 1
        return "ok"

    policy = RetryPolicy(attempts=3, base_delay=0.0, jitter=False)
    result = call_with_retry(f, policy=policy, sleep=lambda _d: None)
    assert result == "ok"
    assert calls["n"] == 1


def test_call_with_retry_retries_and_succeeds() -> None:
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom("not yet")
        return "ok"

    policy = RetryPolicy(attempts=5, base_delay=0.0, jitter=False, retryable=(_Boom,))
    delays: list = []
    result = call_with_retry(flaky, policy=policy, sleep=delays.append)
    assert result == "ok"
    assert calls["n"] == 3
    # we slept twice (between attempts 1->2 and 2->3)
    assert len(delays) == 2


def test_call_with_retry_exhausts_attempts() -> None:
    def always_fail():
        raise _Boom("nope")

    policy = RetryPolicy(attempts=3, base_delay=0.0, jitter=False, retryable=(_Boom,))
    with pytest.raises(_Boom):
        call_with_retry(always_fail, policy=policy, sleep=lambda _d: None)


def test_call_with_retry_on_retry_callback() -> None:
    seen = []

    def flaky():
        if len(seen) < 2:
            raise _Boom(f"attempt {len(seen) + 1}")
        return "ok"

    def on_retry(attempt: int, exc: Exception, delay: float) -> None:
        seen.append((attempt, str(exc), delay))

    policy = RetryPolicy(attempts=5, base_delay=0.5, factor=2.0, jitter=False, retryable=(_Boom,))
    result = call_with_retry(flaky, policy=policy, on_retry=on_retry, sleep=lambda _d: None)
    assert result == "ok"
    assert len(seen) == 2
    # exponential backoff: 0.5, 1.0
    assert seen[0][2] == pytest.approx(0.5)
    assert seen[1][2] == pytest.approx(1.0)


def test_call_with_retry_max_delay_caps_backoff() -> None:
    def f():
        raise _Boom("x")

    seen_delays: list = []
    policy = RetryPolicy(
        attempts=5,
        base_delay=1.0,
        factor=10.0,
        max_delay=3.0,
        jitter=False,
        retryable=(_Boom,),
    )
    with pytest.raises(_Boom):
        call_with_retry(f, policy=policy, sleep=seen_delays.append)
    # base_delay grows 1, 10, 100, 1000 -- all capped to 3
    # there should be 4 sleeps (between 5 attempts), all <= 3
    assert seen_delays
    assert all(d <= 3.0 + 1e-9 for d in seen_delays)


def test_retry_until_predicate_eventually_true() -> None:
    attempts = {"n": 0}

    def fn():
        attempts["n"] += 1
        return attempts["n"]

    def good_enough(value):
        return value >= 3

    policy = RetryPolicy(attempts=10, base_delay=0.0, jitter=False)
    result = retry_until(fn, predicate=good_enough, policy=policy, sleep=lambda _d: None)
    assert result == 3
    assert attempts["n"] == 3


def test_retry_until_predicate_never_true_returns_last() -> None:
    def fn():
        return 0

    policy = RetryPolicy(attempts=3, base_delay=0.0, jitter=False)
    result = retry_until(fn, predicate=lambda _v: False, policy=policy, sleep=lambda _d: None)
    # we got the last call's return value, even though the predicate
    # never said yes
    assert result == 0


def test_retry_policy_non_retryable_exception_propagates() -> None:
    class NotRetryable(Exception):
        pass

    def f():
        raise NotRetryable("dont retry me")

    policy = RetryPolicy(attempts=5, base_delay=0.0, jitter=False, retryable=(_Boom,))
    with pytest.raises(NotRetryable):
        call_with_retry(f, policy=policy, sleep=lambda _d: None)
