"""Regression beta vs the Nifty index.

β = Cov(r_i, r_m) / Var(r_m) on monthly returns over up to 60 months.

Benchmark note: Yahoo Finance carries no Nifty 50 *Total Return* index series,
so ^NSEI (price index) is used and labelled as such in the report. Because
dividend drift is close to constant month-to-month, the slope coefficient is
practically indistinguishable from a TRI-based beta; the limitation is
disclosed rather than hidden.

If fewer than 24 monthly observations are available, the sector-median beta
is used instead (documented approximations of Indian sector medians).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from equity_research.data.provider import DataProvider

logger = logging.getLogger(__name__)

BENCHMARK = "^NSEI"   # Nifty 50 price index (TRI unavailable via yfinance)
MIN_MONTHS = 24

# Approximate Indian sector-median betas (fallback when return history < 24 months)
SECTOR_MEDIAN_BETA: dict[str, float] = {
    "Financial Services": 1.00,
    "Technology": 0.85,
    "Consumer Defensive": 0.60,
    "Healthcare": 0.70,
    "Energy": 1.00,
    "Utilities": 0.80,
    "Basic Materials": 1.20,
    "Industrials": 1.10,
    "Consumer Cyclical": 1.10,
    "Communication Services": 0.90,
    "Real Estate": 1.30,
}
DEFAULT_BETA = 1.0


@dataclass
class BetaResult:
    """Outcome of the beta estimation."""

    beta: float
    months: int           # observations used (0 when sector median applied)
    source: str           # "regression" / "sector_median" / "provider" / "default"
    note: str


def _monthly_returns(prices: pd.DataFrame) -> pd.Series:
    """Month-end close-to-close returns from a daily OHLCV frame."""
    if prices.empty or "Close" not in prices.columns:
        return pd.Series(dtype=float)
    monthly = prices["Close"].resample("ME").last().dropna()
    return monthly.pct_change().dropna()


def regression_beta(
    provider: DataProvider,
    ticker: str,
    sector: str | None = None,
    provider_beta: float | None = None,
) -> BetaResult:
    """Estimate beta from 60 months of returns vs ^NSEI, with fallbacks.

    Fallback chain: regression (≥24 months) → sector median → provider beta
    → 1.0. Every path is labelled in ``source`` for the assumptions appendix.
    """
    try:
        stock = provider.get_prices(ticker, period="5y")
        bench = provider.get_prices(BENCHMARK, period="5y")
        r_i = _monthly_returns(stock)
        r_m = _monthly_returns(bench)
        joined = pd.concat([r_i.rename("i"), r_m.rename("m")], axis=1, join="inner").dropna()
        n = len(joined)
        if n >= MIN_MONTHS:
            var_m = float(joined["m"].var())
            if var_m > 0:
                beta = float(joined["i"].cov(joined["m"]) / var_m)
                beta = max(0.1, min(3.0, beta))   # clamp implausible estimates
                return BetaResult(
                    beta=beta, months=n, source="regression",
                    note=f"OLS on {n} monthly returns vs Nifty 50 (^NSEI, price index)",
                )
        logger.warning("Beta regression for %s: only %d months — using fallback", ticker, n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Beta regression failed for %s: %s", ticker, exc)

    if sector and sector in SECTOR_MEDIAN_BETA:
        return BetaResult(
            beta=SECTOR_MEDIAN_BETA[sector], months=0, source="sector_median",
            note=f"Sector-median beta for {sector} (return history < {MIN_MONTHS} months)",
        )
    if provider_beta is not None and 0.0 < provider_beta < 3.5:
        return BetaResult(
            beta=float(provider_beta), months=0, source="provider",
            note="Provider (Yahoo) 5Y monthly beta",
        )
    return BetaResult(beta=DEFAULT_BETA, months=0, source="default",
                      note="No beta source available — defaulted to 1.0")
