"""Tests for the yfinance retry/backoff helper (BUG 3 — rate-limit resilience)."""

from __future__ import annotations

import pytest

from equity_research.data import yfinance_provider as yp


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make backoff instant so tests don't actually wait."""
    monkeypatch.setattr(yp.time, "sleep", lambda *_: None)


def test_returns_immediately_on_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return 42

    assert yp._with_retries(fn, what="x") == 42
    assert calls["n"] == 1


def test_retries_transient_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("connection reset by peer")  # 'connection' is transient
        return "ok"

    assert yp._with_retries(fn, what="x", attempts=3, base_delay=0.0) == "ok"
    assert calls["n"] == 3


def test_does_not_retry_permanent_error():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("symbol does not exist")  # no transient marker → fail fast

    with pytest.raises(ValueError):
        yp._with_retries(fn, what="x", attempts=3, base_delay=0.0)
    assert calls["n"] == 1  # only one attempt — no wasted retries on a permanent error


def test_rate_limit_message_is_treated_as_transient():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RuntimeError("429 Too Many Requests")  # rate limit → retryable

    with pytest.raises(RuntimeError):
        yp._with_retries(fn, what="x", attempts=2, base_delay=0.0)
    assert calls["n"] == 2  # retried up to the attempt budget


def test_invalid_result_is_retried_then_degraded():
    """yfinance signals rate-limits with an empty payload (no exception)."""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return {}  # always empty/sparse

    result = yp._with_retries(
        fn, what="x", is_valid=lambda d: len(d) > 0, attempts=3, base_delay=0.0
    )
    assert result == {}        # degrades to the last result rather than raising
    assert calls["n"] == 3     # exhausted the retry budget
