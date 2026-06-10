"""Excess-return / DDM valuation model for financial institutions.

Banks and NBFCs cannot be valued with FCFF because they lack meaningful
operating income and their "debt" is a core operating input (deposits),
not financing.  This module implements a simplified excess-return model:

    Excess_Return_t = (ROE - Ke) × BV_{t-1}
    Intrinsic = BV_0 + Σ PV(ER_t) + PV(TV)
    TV = ER_n × (1 + g) / (Ke - g)

Falls back to P/B × book_value_per_share if ROE data is insufficient.

Public entry point: ``run_excess_return(profile, financials, config) -> ExcessReturnResult``
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

from equity_research.analysis.ratios import _col, _latest, _avg_last_two
from equity_research.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class ExcessReturnResult:
    """Excess-return model output."""

    book_value_per_share: float
    cost_of_equity: float           # Ke from CAPM
    roe: float                      # trailing average ROE
    sustainable_growth: float       # ROE × (1 - payout)
    terminal_growth: float
    shares_outstanding: float

    projected_excess_return: list[float]
    projected_book_value: list[float]
    pv_excess_return: list[float]

    terminal_er: float
    pv_terminal_er: float

    intrinsic_value_per_share: float
    equity_value: float

    # Whether we fell back to P/B-based valuation
    is_pb_fallback: bool


def _compute_ke(profile: dict, config: AppConfig) -> float:
    """Compute cost of equity from CAPM.  Ke = Rf + β × ERP."""
    beta = profile.get("beta")
    if beta is None or (isinstance(beta, float) and math.isnan(beta)):
        beta = 1.0
        logger.warning("Beta missing for financial — defaulting to 1.0")
    return config.market.risk_free_rate + float(beta) * config.market.equity_risk_premium


def _pv_cashflows(cashflows: list[float], rate: float) -> list[float]:
    """Present value of each cash flow discounted at *rate*."""
    return [cf / (1.0 + rate) ** (t + 1) for t, cf in enumerate(cashflows)]


def run_excess_return(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
) -> ExcessReturnResult:
    """Run an excess-return valuation for a financial institution.

    Args:
        profile:    Normalized company profile dict.
        financials: Dict with keys 'income', 'balance_sheet'.
        config:     Loaded AppConfig.

    Raises:
        ValueError: if shares_outstanding is missing.
    """
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())

    # --- Shares ---
    shares = profile.get("shares_outstanding")
    if not shares or shares <= 0:
        raise ValueError("shares_outstanding is missing or invalid")
    shares = float(shares)

    # --- Cost of equity ---
    ke = _compute_ke(profile, config)

    # --- Book value ---
    equity_s = _col(balance, "stockholders_equity")
    bv_latest = _latest(equity_s)

    if bv_latest is None or bv_latest <= 0:
        # Attempt from profile
        pb = profile.get("price_to_book")
        price = profile.get("current_price")
        if pb and pb > 0 and price and price > 0:
            bv_per_share = price / pb
            bv_latest = bv_per_share * shares
        else:
            raise ValueError("Book value unavailable for excess-return model")

    bv_per_share = bv_latest / shares

    # --- ROE ---
    ni_s = _col(income, "net_income")
    ni_latest = _latest(ni_s)

    # Try to compute ROE from financial statements
    roe: float | None = None
    if ni_latest is not None and bv_latest > 0:
        # Use average of available ROE values for stability
        eq_series = _col(balance, "stockholders_equity")
        ni_series = _col(income, "net_income")
        if not eq_series.empty and not ni_series.empty:
            # Align on shared years
            common = eq_series.index.intersection(ni_series.index)
            if len(common) >= 2:
                roe_vals = ni_series.loc[common] / eq_series.loc[common]
                valid_roe = roe_vals.dropna()
                valid_roe = valid_roe[valid_roe.between(-0.5, 0.5)]  # filter outliers
                if not valid_roe.empty:
                    roe = float(valid_roe.mean())

        # Fallback to latest-year ROE
        if roe is None:
            roe = ni_latest / bv_latest

    # Fallback to profile ROE
    if roe is None:
        roe_profile = profile.get("return_on_equity")
        if roe_profile is not None and math.isfinite(roe_profile):
            roe = float(roe_profile)

    # If we still have no ROE, fall back to P/B-based valuation
    if roe is None or not math.isfinite(roe):
        return _pb_fallback(profile, bv_per_share, ke, shares, config)

    # Clamp ROE to plausible range
    roe = max(-0.30, min(0.50, roe))

    # --- Payout ratio & sustainable growth ---
    div_yield = profile.get("dividend_yield")
    price = profile.get("current_price")
    if div_yield and price and price > 0 and ni_latest and ni_latest > 0:
        total_dividends = div_yield * price * shares
        payout_ratio = min(0.90, max(0.0, total_dividends / ni_latest))
    else:
        payout_ratio = 0.30  # banks typically pay ~30%
    retention = 1.0 - payout_ratio
    sustainable_g = roe * retention

    horizon = config.dcf.projection_horizon
    g_terminal = config.dcf.terminal_growth_rate

    # --- Project excess returns ---
    projected_er: list[float] = []
    projected_bv: list[float] = []
    pv_er: list[float] = []

    bv = bv_latest
    for t in range(horizon):
        er_t = (roe - ke) * bv
        projected_er.append(er_t)
        projected_bv.append(bv)
        # Book value grows at sustainable growth rate
        bv = bv * (1.0 + sustainable_g)

    # --- Terminal excess return ---
    if ke <= g_terminal:
        terminal_er = 0.0
        pv_terminal = 0.0
    else:
        er_final = projected_er[-1]
        terminal_er = er_final * (1.0 + g_terminal) / (ke - g_terminal)
        pv_terminal = terminal_er / (1.0 + ke) ** horizon

    pv_er = _pv_cashflows(projected_er, ke)
    sum_pv_er = sum(pv_er)

    # --- Intrinsic value ---
    equity_value = bv_latest + sum_pv_er + pv_terminal
    intrinsic = max(0.0, equity_value / shares)  # Floor at zero

    logger.info(
        "Excess-return: BV/share=%.2f  ROE=%.4f  Ke=%.4f  spread=%.4f  "
        "intrinsic/share=%.2f",
        bv_per_share, roe, ke, roe - ke, intrinsic,
    )

    return ExcessReturnResult(
        book_value_per_share=bv_per_share,
        cost_of_equity=ke,
        roe=roe,
        sustainable_growth=sustainable_g,
        terminal_growth=g_terminal,
        shares_outstanding=shares,
        projected_excess_return=projected_er,
        projected_book_value=projected_bv,
        pv_excess_return=pv_er,
        terminal_er=terminal_er,
        pv_terminal_er=pv_terminal,
        intrinsic_value_per_share=intrinsic,
        equity_value=equity_value,
        is_pb_fallback=False,
    )


def _pb_fallback(
    profile: dict,
    bv_per_share: float,
    ke: float,
    shares: float,
    config: AppConfig,
) -> ExcessReturnResult:
    """P/B-based fallback when ROE data is insufficient."""
    pb = profile.get("price_to_book")
    if pb and pb > 0:
        intrinsic = bv_per_share * pb  # assume fair P/B = current P/B
    else:
        intrinsic = bv_per_share  # P/B = 1× as last resort

    logger.warning(
        "Insufficient ROE data — using P/B fallback: BV/share=%.2f  P/B=%.1f  "
        "intrinsic=%.2f",
        bv_per_share, pb or 1.0, intrinsic,
    )

    horizon = config.dcf.projection_horizon
    return ExcessReturnResult(
        book_value_per_share=bv_per_share,
        cost_of_equity=ke,
        roe=0.0,
        sustainable_growth=0.0,
        terminal_growth=config.dcf.terminal_growth_rate,
        shares_outstanding=shares,
        projected_excess_return=[0.0] * horizon,
        projected_book_value=[bv_per_share * shares] * horizon,
        pv_excess_return=[0.0] * horizon,
        terminal_er=0.0,
        pv_terminal_er=0.0,
        intrinsic_value_per_share=max(0.0, intrinsic),
        equity_value=max(0.0, intrinsic * shares),
        is_pb_fallback=True,
    )
