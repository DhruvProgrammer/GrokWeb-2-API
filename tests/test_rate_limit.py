"""Tests for the per-IP rate limiter."""

from __future__ import annotations

import time

from grok_web_to_api.rate_limit import RateLimiter


def test_allows_under_limit():
    rl = RateLimiter(window_seconds=60, max_requests=5)
    for _ in range(5):
        ok, retry = rl.check("1.1.1.1")
        assert ok is True
        assert retry == 0


def test_blocks_at_limit():
    rl = RateLimiter(window_seconds=60, max_requests=3)
    for _ in range(3):
        ok, _ = rl.check("1.1.1.1")
        assert ok is True
    ok, retry = rl.check("1.1.1.1")
    assert ok is False
    assert retry > 0
    assert retry <= 60


def test_separate_ips_have_separate_buckets():
    rl = RateLimiter(window_seconds=60, max_requests=2)
    for _ in range(2):
        ok, _ = rl.check("1.1.1.1")
        assert ok is True
    # 1.1.1.1 is now exhausted.
    ok, _ = rl.check("1.1.1.1")
    assert ok is False
    # But 2.2.2.2 has a fresh budget.
    ok, _ = rl.check("2.2.2.2")
    assert ok is True


def test_window_expires():
    """After the window passes, requests should be allowed again."""
    rl = RateLimiter(window_seconds=1, max_requests=1)
    ok, _ = rl.check("1.1.1.1")
    assert ok is True
    ok, _ = rl.check("1.1.1.1")
    assert ok is False
    time.sleep(1.1)
    ok, _ = rl.check("1.1.1.1")
    assert ok is True


def test_concurrent_calls_respect_limit():
    """Even under load, no IP should exceed max_requests."""
    import threading

    rl = RateLimiter(window_seconds=60, max_requests=10)
    allowed = []
    lock = threading.Lock()

    def hammer():
        for _ in range(20):
            ok, _ = rl.check("1.1.1.1")
            with lock:
                allowed.append(ok)

    threads = [threading.Thread(target=hammer) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 5 threads × 20 attempts = 100 calls, but only 10 should be allowed.
    assert sum(allowed) == 10
    assert sum(not x for x in allowed) == 90