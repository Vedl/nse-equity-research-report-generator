"""Phase 3B-i Commit 1 — tangible-book correction.

The financial (justified-P/B) model must value banks off TANGIBLE common equity:
acquisition goodwill/intangibles earn no return, so both the book/share and the
ROE denominator use tangible equity (ROTE / P-TBV).  Clean names with no goodwill
line are unchanged.
"""

from __future__ import annotations

import pandas as pd
import pytest

from equity_research.analysis.financial_sector import (
    _tangible_equity_series,
    run_financial_valuation,
)
from equity_research.config import load_config

_CFG = load_config()
_YEARS = [2023, 2024, 2025]


def _balance(**cols) -> pd.DataFrame:
    return pd.DataFrame(cols, index=_YEARS)


def _income(net_income) -> pd.DataFrame:
    return pd.DataFrame({"net_income": net_income}, index=_YEARS)


def _profile(**over) -> dict:
    p = {"shares_outstanding": 100.0, "current_price": 10.0, "beta": 1.0,
         "dividend_yield": 0.02, "market_cap": 1000.0, "sector": "Financial Services"}
    p.update(over)
    return p


# --- _tangible_equity_series resolution order ----------------------------------


def test_prefers_reported_tangible_book_value():
    bal = _balance(
        stockholders_equity=[800, 900, 1000],
        goodwill_and_intangibles=[300, 300, 300],
        tangible_book_value=[500, 600, 700],
    )
    series, basis = _tangible_equity_series(bal)
    assert basis == "tangible_reported"
    assert series.iloc[-1] == 700


def test_derives_tangible_when_only_goodwill_present():
    bal = _balance(
        stockholders_equity=[800, 900, 1000],
        goodwill_and_intangibles=[300, 300, 300],
    )
    series, basis = _tangible_equity_series(bal)
    assert basis == "tangible_derived"
    assert series.iloc[-1] == 700        # 1000 − 300


def test_falls_back_to_total_when_no_goodwill_data():
    bal = _balance(stockholders_equity=[800, 900, 1000])
    series, basis = _tangible_equity_series(bal)
    assert basis == "total_no_goodwill_data"
    assert series.iloc[-1] == 1000


# --- run_financial_valuation uses tangible book + ROTE -------------------------


def test_book_and_roe_denominator_are_tangible():
    # total equity 1000, goodwill 300 → tangible 700 (per 100 shares: ₹7 vs ₹10).
    bal = _balance(
        stockholders_equity=[800, 900, 1000],
        goodwill_and_intangibles=[300, 300, 300],
        tangible_book_value=[500, 600, 700],
    )
    inc = _income([70, 80, 100])
    r = run_financial_valuation(_profile(), {"income": inc, "balance_sheet": bal}, _CFG)

    assert r.book_basis == "tangible_reported"
    assert r.book_value_per_share == pytest.approx(7.0)        # tangible
    assert r.total_book_value_per_share == pytest.approx(10.0)  # total (pre-tangible)

    # ROE is ROTE: mean of NI/tangible (≈0.139), NOT NI/total (≈0.092).
    rote = ((70 / 500) + (80 / 600) + (100 / 700)) / 3
    roe_total = ((70 / 800) + (80 / 900) + (100 / 1000)) / 3
    assert r.roe == pytest.approx(rote, abs=1e-3)
    assert abs(r.roe - roe_total) > 0.03


def test_clean_bank_unchanged_when_no_goodwill():
    bal = _balance(stockholders_equity=[800, 900, 1000])
    inc = _income([70, 80, 100])
    r = run_financial_valuation(_profile(), {"income": inc, "balance_sheet": bal}, _CFG)
    assert r.book_basis == "total_no_goodwill_data"
    assert r.book_value_per_share == pytest.approx(10.0)
    assert r.total_book_value_per_share == pytest.approx(10.0)


def test_terminal_g_stays_below_ke():
    bal = _balance(
        stockholders_equity=[800, 900, 1000],
        tangible_book_value=[500, 600, 700],
    )
    inc = _income([70, 80, 100])
    r = run_financial_valuation(_profile(), {"income": inc, "balance_sheet": bal}, _CFG)
    assert r.growth_rate < r.cost_of_equity
