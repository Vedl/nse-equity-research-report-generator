"""Dividend-yield normalization — yfinance returns this field inconsistently.

The provider must hand downstream a consistent *fraction* (0.0082 for 0.82%),
resolved once. These cases are the exact live values that triggered the bank
DDM blow-up (ICICI 0.82 read as 82%).
"""

from __future__ import annotations

import pytest

from equity_research.data.yfinance_provider import _normalize_dividend_yield


def test_trailing_yield_preferred_when_fractional():
    # ICICI: dividendYield=0.82 (pct-points), trailing=0.0089 (fraction) → trailing wins.
    assert _normalize_dividend_yield(0.82, 0.0089, 11.0, 1342.9) == pytest.approx(0.0089)


def test_all_live_bank_cases_resolve_to_fraction():
    cases = {  # ticker: (dividendYield, trailing, dps, price, expected)
        "ICICI": (0.82, 0.0089, 11.0, 1342.9, 0.0089),
        "KOTAK": (0.12, 0.00161, 0.65, 405.35, 0.00161),
        "SBIN": (1.71, 0.01706, 17.35, 1025.75, 0.01706),
        "RELIANCE": (0.46, 0.00464, 6.0, 1314.2, 0.00464),
    }
    for name, (dy, tr, dps, px, exp) in cases.items():
        got = _normalize_dividend_yield(dy, tr, dps, px)
        assert got == pytest.approx(exp), name
        assert 0.0 < got < 0.05, f"{name} not a sane fraction: {got}"


def test_dps_price_disambiguates_without_trailing():
    # No trailing yield → DPS/price confirms 0.82 is percentage-points → 0.0082
    # (it returns the normalized dy/100, using DPS/price only as the arbiter).
    assert _normalize_dividend_yield(0.82, None, 11.0, 1342.9) == pytest.approx(0.0082)


def test_percentage_points_fallback_without_ground_truth():
    # No trailing, no DPS/price → assume percentage points and rescale.
    assert _normalize_dividend_yield(5.74, None, None, None) == pytest.approx(0.0574)


def test_legacy_fraction_left_untouched():
    # An already-fractional legacy value (≤ 0.2) with no ground truth is kept.
    assert _normalize_dividend_yield(0.03, None, None, None) == pytest.approx(0.03)


def test_none_and_zero():
    assert _normalize_dividend_yield(None, None, None, None) is None
    assert _normalize_dividend_yield(0.0, None, None, None) == pytest.approx(0.0)
