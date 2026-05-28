"""CFA-aligned ratio analysis.

All scalar outputs are ``float | None``. ``None`` means the required input
data was missing or the result was undefined (e.g. division by zero).
Callers are responsible for formatting; nothing is rounded here.
"""

from __future__ import annotations

import logging

import pandas as pd

from equity_research.utils.formatting import cagr, safe_divide

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return a float Series for *name*, or an empty Series if absent."""
    if name in df.columns:
        return df[name].astype(float)
    logger.warning("Ratio computation: column '%s' not found", name)
    return pd.Series(dtype=float, name=name)


def _latest(s: pd.Series) -> float | None:
    """Most recent non-NaN value, or None."""
    valid = s.dropna()
    return float(valid.iloc[-1]) if not valid.empty else None


def _prev(s: pd.Series) -> float | None:
    """Second-most-recent non-NaN value, or None."""
    valid = s.dropna()
    return float(valid.iloc[-2]) if len(valid) >= 2 else None


def _avg_last_two(s: pd.Series) -> float | None:
    """Average of the two most recent non-NaN values; falls back to the latest alone."""
    a = _latest(s)
    b = _prev(s)
    if a is None:
        return None
    return (a + b) / 2 if b is not None else a


def _cagr_series(s: pd.Series, n_years: int) -> float | None:
    """CAGR over the last *n_years* of *s*.

    If fewer than n_years+1 data points exist, computes over the full
    available span and logs a warning.
    """
    valid = s.dropna()
    if len(valid) < 2:
        return None

    if len(valid) >= n_years + 1:
        start = float(valid.iloc[-(n_years + 1)])
        end = float(valid.iloc[-1])
        years = n_years
    else:
        start = float(valid.iloc[0])
        end = float(valid.iloc[-1])
        try:
            years = int(valid.index[-1]) - int(valid.index[0])
        except (TypeError, ValueError):
            years = len(valid) - 1
        if years <= 0:
            return None
        logger.warning(
            "Requested %d-year CAGR but only %d years available — using %d-year span",
            n_years,
            len(valid) - 1,
            years,
        )

    return cagr(start, end, years)


# ---------------------------------------------------------------------------
# CFA ratio groups
# ---------------------------------------------------------------------------


def _profitability(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    tax_rate: float,
) -> dict[str, float | None]:
    rev = _col(income, "total_revenue")
    gp = _col(income, "gross_profit")
    oi = _col(income, "operating_income")
    ni = _col(income, "net_income")
    eq = _col(balance, "stockholders_equity")
    debt = _col(balance, "total_debt")

    gross_margin = safe_divide(_latest(gp), _latest(rev))
    operating_margin = safe_divide(_latest(oi), _latest(rev))
    net_margin = safe_divide(_latest(ni), _latest(rev))

    # ROE = Net Income / Average Stockholders' Equity
    roe = safe_divide(_latest(ni), _avg_last_two(eq))

    # ROIC = NOPAT / Average Invested Capital
    # NOPAT  = EBIT × (1 − tax_rate)
    # IC     = Equity + Total Debt
    nopat: float | None = None
    latest_oi = _latest(oi)
    if latest_oi is not None:
        nopat = latest_oi * (1.0 - tax_rate)

    ic = eq.add(debt)   # NaN propagates if either leg is NaN
    roic = safe_divide(nopat, _avg_last_two(ic))

    return {
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "roe": roe,
        "roic": roic,
    }


def _liquidity(balance: pd.DataFrame) -> dict[str, float | None]:
    ca = _col(balance, "current_assets")
    cl = _col(balance, "current_liabilities")
    inv = _col(balance, "inventory")

    current_ratio = safe_divide(_latest(ca), _latest(cl))

    # Quick ratio excludes inventory
    latest_ca = _latest(ca)
    latest_inv = _latest(inv)
    latest_cl = _latest(cl)

    if latest_ca is not None and latest_inv is not None:
        quick_assets = latest_ca - latest_inv
    elif latest_ca is not None:
        logger.warning("Inventory missing — quick ratio uses current assets only")
        quick_assets = latest_ca
    else:
        quick_assets = None

    quick_ratio = safe_divide(quick_assets, latest_cl)

    return {
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
    }


def _solvency(
    income: pd.DataFrame,
    balance: pd.DataFrame,
) -> dict[str, float | None]:
    oi = _col(income, "operating_income")
    ie = _col(income, "interest_expense")
    eq = _col(balance, "stockholders_equity")
    debt = _col(balance, "total_debt")

    debt_to_equity = safe_divide(_latest(debt), _latest(eq))

    # Interest coverage = EBIT / Interest Expense
    # yfinance stores interest expense as a positive value in the income statement
    latest_ie = _latest(ie)
    if latest_ie is not None and latest_ie < 0:
        latest_ie = abs(latest_ie)   # normalise sign if stored as outflow
    interest_coverage = safe_divide(_latest(oi), latest_ie)

    return {
        "debt_to_equity": debt_to_equity,
        "interest_coverage": interest_coverage,
    }


def _efficiency(
    income: pd.DataFrame,
    balance: pd.DataFrame,
) -> dict[str, float | None]:
    rev = _col(income, "total_revenue")
    ta = _col(balance, "total_assets")

    # Asset Turnover = Revenue / Average Total Assets
    asset_turnover = safe_divide(_latest(rev), _avg_last_two(ta))

    return {"asset_turnover": asset_turnover}


def _cagr(income: pd.DataFrame) -> dict[str, float | None]:
    rev = _col(income, "total_revenue")
    eps = _col(income, "basic_eps")

    return {
        "revenue_3y": _cagr_series(rev, 3),
        "revenue_5y": _cagr_series(rev, 5),
        "eps_3y": _cagr_series(eps, 3),
        "eps_5y": _cagr_series(eps, 5),
    }


def _annual_series(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    tax_rate: float,
) -> pd.DataFrame:
    """Return a DataFrame of key ratios by year for trend tables and charts."""
    rev = _col(income, "total_revenue")
    gp = _col(income, "gross_profit")
    oi = _col(income, "operating_income")
    ni = _col(income, "net_income")
    eq = _col(balance, "stockholders_equity")

    result = pd.DataFrame(index=income.index)
    result["gross_margin"] = gp / rev
    result["operating_margin"] = oi / rev
    result["net_margin"] = ni / rev

    # Annual ROE uses the equity of the same year (point-in-time, not averaged)
    # — consistent with how yfinance/Bloomberg report annual ROE
    ni_aligned = ni.reindex(eq.index)
    result["roe"] = ni_aligned / eq

    return result.dropna(how="all")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_ratios(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    tax_rate: float = 0.25,
) -> dict:
    """Compute a full set of CFA-aligned financial ratios.

    Args:
        income:    Normalized income statement (from DataProvider.get_financials).
        balance:   Normalized balance sheet.
        cashflow:  Normalized cash flow statement (reserved for future ratios).
        tax_rate:  Effective corporate tax rate used for NOPAT and ROIC.

    Returns:
        dict with keys:
            'profitability' — gross/operating/net margin, ROE, ROIC
            'liquidity'     — current ratio, quick ratio
            'solvency'      — debt/equity, interest coverage
            'efficiency'    — asset turnover
            'cagr'          — revenue and EPS CAGR (3Y and 5Y)
            'annual'        — pd.DataFrame of annual margins/ROE for charting
    """
    if income.empty:
        logger.warning("compute_ratios: income statement is empty — most ratios will be None")
    if balance.empty:
        logger.warning("compute_ratios: balance sheet is empty — balance-based ratios will be None")

    return {
        "profitability": _profitability(income, balance, tax_rate),
        "liquidity": _liquidity(balance),
        "solvency": _solvency(income, balance),
        "efficiency": _efficiency(income, balance),
        "cagr": _cagr(income),
        "annual": _annual_series(income, balance, tax_rate),
    }
