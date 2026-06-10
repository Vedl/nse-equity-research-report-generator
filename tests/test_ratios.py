"""Pytest tests for analysis/ratios.py.

Every expected value is derived by hand from the synthetic fixtures in
conftest.py.  Key fixture parameters (2024 values, tax_rate=0.25):

  Revenue    1464.10 Cr  (10% YoY growth from 1000 Cr in 2020)
  Gross GP   30% of rev  →  439.23 Cr
  Op. Inc.   15% of rev  →  219.615 Cr
  Net Inc.   10% of rev  →  146.41 Cr
  Int. Exp.   2% of rev  →   29.282 Cr
  Dep/Amort   5% of rev  →   73.205 Cr

  Total Assets 2024    2928.20 Cr,   2023    2662.00 Cr
  Curr Assets  2024     732.05 Cr
  Inventory    2024     219.615 Cr
  Curr Liab    2024     439.23 Cr
  Total Debt   2024     585.64 Cr,   2023     532.40 Cr
  Equity       2024    1171.28 Cr,   2023    1064.80 Cr

All values here are in units of Crores (÷ 1e7) for readability, but the
fixture stores full INR so the ratios are dimensionless.
"""

from __future__ import annotations

import pandas as pd
import pytest

from equity_research.analysis.ratios import (
    compute_ratios,
    _avg_last_two,
    _cagr_series,
    _latest,
    _prev,
)

TAX_RATE = 0.25

# ---------------------------------------------------------------------------
# Helper: run compute_ratios once against the synthetic fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ratios(
    synthetic_income: pd.DataFrame,
    synthetic_balance: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> dict:
    return compute_ratios(
        synthetic_income, synthetic_balance, synthetic_cashflow, tax_rate=TAX_RATE
    )


# ---------------------------------------------------------------------------
# Profitability
# ---------------------------------------------------------------------------


def test_gross_margin(ratios: dict) -> None:
    # Gross Profit / Revenue = 30%
    assert ratios["profitability"]["gross_margin"] == pytest.approx(0.30, rel=1e-4)


def test_operating_margin(ratios: dict) -> None:
    # Operating Income / Revenue = 15%
    assert ratios["profitability"]["operating_margin"] == pytest.approx(0.15, rel=1e-4)


def test_net_margin(ratios: dict) -> None:
    # Net Income / Revenue = 10%
    assert ratios["profitability"]["net_margin"] == pytest.approx(0.10, rel=1e-4)


def test_roe(ratios: dict) -> None:
    # ROE = Net Income 2024 / Avg(Equity 2023, Equity 2024)
    # = 146.41e7 / avg(1064.80e7, 1171.28e7)
    # = 146.41 / 1118.04 ≈ 0.13095
    ni = 1_464.1e7 * 0.10
    avg_eq = (1_064.8e7 + 1_171.28e7) / 2
    expected = ni / avg_eq
    assert ratios["profitability"]["roe"] == pytest.approx(expected, rel=1e-4)


def test_roic(ratios: dict) -> None:
    # NOPAT = Operating Income 2024 × (1 − 0.25) = 219.615e7 × 0.75 = 164.71125e7
    # IC 2024 = Equity + Debt = 1171.28e7 + 585.64e7 = 1756.92e7
    # IC 2023 = 1064.80e7 + 532.40e7 = 1597.20e7
    # Avg IC = (1756.92 + 1597.20) / 2 × 1e7 = 1677.06e7
    # ROIC = 164.71125e7 / 1677.06e7 ≈ 0.09822
    nopat = 1_464.1e7 * 0.15 * 0.75
    ic_2024 = 1_171.28e7 + 585.64e7
    ic_2023 = 1_064.8e7 + 532.4e7
    avg_ic = (ic_2024 + ic_2023) / 2
    expected = nopat / avg_ic
    assert ratios["profitability"]["roic"] == pytest.approx(expected, rel=1e-4)


def test_profitability_all_keys_present(ratios: dict) -> None:
    expected_keys = {"gross_margin", "operating_margin", "net_margin", "roe", "roic"}
    assert expected_keys == set(ratios["profitability"].keys())


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------


def test_current_ratio(ratios: dict) -> None:
    # Current Assets / Current Liabilities = 732.05 / 439.23 ≈ 1.6668
    expected = 732.05e7 / 439.23e7
    assert ratios["liquidity"]["current_ratio"] == pytest.approx(expected, rel=1e-4)


def test_quick_ratio(ratios: dict) -> None:
    # (Current Assets − Inventory) / Current Liabilities
    # = (732.05 − 219.615) / 439.23 ≈ 1.1667
    expected = (732.05e7 - 219.615e7) / 439.23e7
    assert ratios["liquidity"]["quick_ratio"] == pytest.approx(expected, rel=1e-3)


def test_liquidity_keys_present(ratios: dict) -> None:
    assert {"current_ratio", "quick_ratio"} == set(ratios["liquidity"].keys())


# ---------------------------------------------------------------------------
# Solvency
# ---------------------------------------------------------------------------


def test_debt_to_equity(ratios: dict) -> None:
    # Debt / Equity = 585.64 / 1171.28 = 0.50
    expected = 585.64e7 / 1171.28e7
    assert ratios["solvency"]["debt_to_equity"] == pytest.approx(expected, rel=1e-4)


def test_interest_coverage(ratios: dict) -> None:
    # EBIT / Interest Expense = 219.615 / 29.282 = 7.50
    oi = 1_464.1e7 * 0.15
    ie = 1_464.1e7 * 0.02
    expected = oi / ie
    assert ratios["solvency"]["interest_coverage"] == pytest.approx(expected, rel=1e-4)


def test_solvency_keys_present(ratios: dict) -> None:
    assert {"debt_to_equity", "interest_coverage"} == set(ratios["solvency"].keys())


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------


def test_asset_turnover(ratios: dict) -> None:
    # Revenue / Avg(Total Assets 2023, 2024)
    # = 1464.10 / avg(2662, 2928.2) = 1464.10 / 2795.10 ≈ 0.5238
    expected = 1_464.1e7 / ((2_662e7 + 2_928.2e7) / 2)
    assert ratios["efficiency"]["asset_turnover"] == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------


def test_revenue_cagr_3y(ratios: dict) -> None:
    # Revenue 2021 → 2024: 1100 → 1464.1 over 3 years = 10%
    # (1464.1 / 1100) ^ (1/3) − 1 = 1.331^(1/3) − 1 = 0.10
    assert ratios["cagr"]["revenue_3y"] == pytest.approx(0.10, rel=1e-4)


def test_revenue_cagr_5y(ratios: dict) -> None:
    # Fixture only has 4 years of growth (2020–2024), so 5Y falls back to 4Y.
    # (1464.1 / 1000) ^ (1/4) − 1 = 1.4641^0.25 − 1 = 0.10
    assert ratios["cagr"]["revenue_5y"] == pytest.approx(0.10, rel=1e-4)


def test_eps_cagr_3y(ratios: dict) -> None:
    # EPS 2021 → 2024: 11.0 → 14.641 over 3 years = 10%
    assert ratios["cagr"]["eps_3y"] == pytest.approx(0.10, rel=1e-4)


def test_eps_cagr_5y(ratios: dict) -> None:
    # 4-year fallback: EPS 2020 → 2024: 10.0 → 14.641 over 4 years = 10%
    assert ratios["cagr"]["eps_5y"] == pytest.approx(0.10, rel=1e-4)


def test_cagr_keys_present(ratios: dict) -> None:
    assert {"revenue_3y", "revenue_5y", "eps_3y", "eps_5y"} == set(ratios["cagr"].keys())


# ---------------------------------------------------------------------------
# Annual time-series
# ---------------------------------------------------------------------------


def test_annual_series_shape(ratios: dict) -> None:
    annual = ratios["annual"]
    assert isinstance(annual, pd.DataFrame)
    assert len(annual) == 5
    assert {"gross_margin", "operating_margin", "net_margin", "roe"}.issubset(
        annual.columns
    )


def test_annual_gross_margin_all_years(ratios: dict) -> None:
    # Every year has 30% gross margin in the synthetic fixture
    gm = ratios["annual"]["gross_margin"].dropna()
    assert len(gm) == 5
    for val in gm:
        assert val == pytest.approx(0.30, rel=1e-4)


def test_annual_net_margin_all_years(ratios: dict) -> None:
    nm = ratios["annual"]["net_margin"].dropna()
    assert len(nm) == 5
    for val in nm:
        assert val == pytest.approx(0.10, rel=1e-4)


# ---------------------------------------------------------------------------
# Missing-data handling
# ---------------------------------------------------------------------------


def test_missing_revenue_returns_none_margins(
    synthetic_income: pd.DataFrame,
    synthetic_balance: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> None:
    bad_income = synthetic_income.copy()
    bad_income["total_revenue"] = float("nan")
    r = compute_ratios(bad_income, synthetic_balance, synthetic_cashflow)
    assert r["profitability"]["gross_margin"] is None
    assert r["profitability"]["operating_margin"] is None
    assert r["profitability"]["net_margin"] is None
    assert r["cagr"]["revenue_3y"] is None
    assert r["cagr"]["revenue_5y"] is None


def test_missing_equity_returns_none_roe_roic(
    synthetic_income: pd.DataFrame,
    synthetic_balance: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> None:
    bad_balance = synthetic_balance.copy()
    bad_balance["stockholders_equity"] = float("nan")
    r = compute_ratios(synthetic_income, bad_balance, synthetic_cashflow)
    assert r["profitability"]["roe"] is None
    assert r["profitability"]["roic"] is None


def test_missing_current_liabilities_returns_none_liquidity(
    synthetic_income: pd.DataFrame,
    synthetic_balance: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> None:
    bad_balance = synthetic_balance.copy()
    bad_balance["current_liabilities"] = float("nan")
    r = compute_ratios(synthetic_income, bad_balance, synthetic_cashflow)
    assert r["liquidity"]["current_ratio"] is None
    assert r["liquidity"]["quick_ratio"] is None


def test_zero_interest_expense_returns_none_coverage(
    synthetic_income: pd.DataFrame,
    synthetic_balance: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> None:
    bad_income = synthetic_income.copy()
    bad_income["interest_expense"] = 0.0
    r = compute_ratios(bad_income, synthetic_balance, synthetic_cashflow)
    assert r["solvency"]["interest_coverage"] is None


def test_empty_income_returns_none_ratios(
    synthetic_balance: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> None:
    empty = pd.DataFrame()
    r = compute_ratios(empty, synthetic_balance, synthetic_cashflow)
    assert r["profitability"]["gross_margin"] is None
    assert r["profitability"]["net_margin"] is None
    assert r["efficiency"]["asset_turnover"] is None
    assert r["cagr"]["revenue_3y"] is None


def test_empty_balance_returns_none_balance_ratios(
    synthetic_income: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
) -> None:
    empty = pd.DataFrame()
    r = compute_ratios(synthetic_income, empty, synthetic_cashflow)
    assert r["liquidity"]["current_ratio"] is None
    assert r["solvency"]["debt_to_equity"] is None
    assert r["profitability"]["roe"] is None


# ---------------------------------------------------------------------------
# Private helper unit tests
# ---------------------------------------------------------------------------


def test_latest_returns_last_nonnan() -> None:
    s = pd.Series([1.0, float("nan"), 3.0], index=[2021, 2022, 2023])
    assert _latest(s) == 3.0


def test_latest_all_nan_returns_none() -> None:
    s = pd.Series([float("nan"), float("nan")])
    assert _latest(s) is None


def test_prev_returns_second_last() -> None:
    s = pd.Series([1.0, 2.0, 3.0], index=[2021, 2022, 2023])
    assert _prev(s) == 2.0


def test_avg_last_two_normal() -> None:
    s = pd.Series([10.0, 20.0], index=[2022, 2023])
    assert _avg_last_two(s) == pytest.approx(15.0)


def test_avg_last_two_single_value_returns_that_value() -> None:
    s = pd.Series([42.0], index=[2023])
    assert _avg_last_two(s) == pytest.approx(42.0)


def test_cagr_series_known_answer() -> None:
    # 100 → 133.1 over 3 years = 10%
    s = pd.Series(
        [100.0, 110.0, 121.0, 133.1],
        index=pd.Index([2020, 2021, 2022, 2023], name="year"),
    )
    result = _cagr_series(s, 3)
    assert result == pytest.approx(0.10, rel=1e-4)


def test_cagr_series_fallback_to_available_span() -> None:
    # Only 2 data points → 1-year CAGR
    s = pd.Series([100.0, 110.0], index=pd.Index([2022, 2023], name="year"))
    result = _cagr_series(s, 5)
    assert result == pytest.approx(0.10, rel=1e-4)


def test_cagr_series_single_point_returns_none() -> None:
    s = pd.Series([100.0], index=pd.Index([2023], name="year"))
    assert _cagr_series(s, 3) is None
