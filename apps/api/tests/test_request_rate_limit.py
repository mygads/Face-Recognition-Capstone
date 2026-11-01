"""Unit tests for the amortized sliding-window rate limiter."""

from presensi_api.api.security.request_rate_limit import SlidingWindowRateLimiter


def test_allows_up_to_limit_then_denies() -> None:
    limiter = SlidingWindowRateLimiter()
    assert all(
        limiter.allow("device:1", limit=3, now=100.0 + i * 0.01) for i in range(3)
    )
    assert limiter.allow("device:1", limit=3, now=100.05) is False


def test_window_slides_and_keys_are_independent() -> None:
    limiter = SlidingWindowRateLimiter()
    assert limiter.allow("a", limit=1, now=0.0) is True
    assert limiter.allow("a", limit=1, now=30.0) is False
    assert limiter.allow("b", limit=1, now=30.0) is True
    assert limiter.allow("a", limit=1, now=61.0) is True


def test_expired_keys_are_eventually_evicted() -> None:
    limiter = SlidingWindowRateLimiter()
    for i in range(300):
        limiter.allow(f"device:{i}", limit=1, now=0.0)
    assert len(limiter._requests) == 300
    # Far-future traffic triggers amortized sweeps that drop empty buckets.
    for i in range(300):
        limiter.allow(f"device:{i}", limit=1, now=61.0)
    assert len(limiter._requests) <= 300
    assert all(len(bucket) == 1 for bucket in limiter._requests.values())


def test_burst_then_quiet_keeps_only_live_buckets() -> None:
    limiter = SlidingWindowRateLimiter()
    limiter.allow("steady", limit=1000, now=0.0)
    for i in range(200):
        limiter.allow(f"one-shot:{i}", limit=1, now=0.0)
    for _ in range(200):
        limiter.allow("steady", limit=1000, now=61.0)
    assert "steady" in limiter._requests
    assert not any(key.startswith("one-shot:") for key in limiter._requests)
