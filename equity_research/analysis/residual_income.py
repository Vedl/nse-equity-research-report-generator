"""Residual Income (RI) valuation model.

Intrinsic Value = Book Value + Σ PV(Residual Income_t) + PV(Terminal RI)

Where:
    RI_t  = Net_Income_t − (Ke × BV_{t-1})
    TV_RI = RI_n × (1 + g) / (Ke − g)

This model is suitable for companies with meaningful book value but
volatile or negative free cash flow (e.g. capex-heavy industrials
mid-investment-cycle).

Public entry point: ``run_residual_income(profile, financials, config) -> RIResult``
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

from equity_research.analysis.dcf import compute_wacc, compute_growth_rates
from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class RIResult:
    """Residual Income model output."""

    book_value_per_share: float
    cost_of_equity: float           # Ke from CAPM
    growth_rate: float              # projection growth rate
    terminal_growth: float
    shares_outstanding: float

    projected_net_income: list[float]
    projected_book_value: list[float]
    projected_ri: list[float]
    pv_ri: list[float]

    terminal_ri: float
    pv_terminal_ri: float

    intrinsic_value_per_share: float
    equity_value: float


def _pv_cashflows(cashflows: list[float], rate: float) -> list[float]:
    """Present value of each cash flow discounted at *rate*."""
    return [cf / (1.0 + rate) ** (t + 1) for t, cf in enumerate(cashflows)]


def run_residual_income(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
) -> RIResult:
    """Run a Residual Income valuation.

    Args:
        profile:    Normalized company profile dict.
        financials: Dict with keys 'income', 'balance_sheet', 'cash_flow'.
        config:     Loaded AppConfig.

    Raises:
        ValueError: if critical inputs are missing.
    """
    income = financials["income"]
    balance = financials["balance_sheet"]

    # --- Shares ---
    shares = profile.get("shares_outstanding")
    if not shares or shares <= 0:
        raise ValueError("shares_outstanding is missing or invalid")
    shares = float(shares)

    # --- Cost of equity (Ke) from CAPM ---
    wacc_comps = compute_wacc(profile, income, balance, config)
    ke = wacc_comps.cost_of_equity

    # --- Book value ---
    equity_s = _col(balance, "stockholders_equity")
    bv_latest = _latest(equity_s)
    if bv_latest is None or bv_latest <= 0:
        raise ValueError("Stockholders equity is missing or non-positive")
    bv_per_share = bv_latest / shares

    # --- Net income ---
    ni_s = _col(income, "net_income")
    ni_latest = _latest(ni_s)
    if ni_latest is None:
        raise ValueError("Net income is missing")

    # --- Growth rates ---
    growth_rates = compute_growth_rates(income, config)
    g = growth_rates[0] if growth_rates else 0.08
    horizon = config.dcf.projection_horizon
    g_terminal = config.dcf.terminal_growth_rate

    # --- Dividend payout ratio estimate ---
    div_yield = profile.get("dividend_yield")
    price = profile.get("current_price")
    if div_yield and price and price > 0 and ni_latest > 0:
        total_dividends = div_yield * price * shares
        payout_ratio = min(1.0, max(0.0, total_dividends / ni_latest))
    else:
        payout_ratio = 0.30  # conservative default
    retention = 1.0 - payout_ratio

    # --- Project net income and book value ---
    projected_ni: list[float] = []
    projected_bv: list[float] = []
    projected_ri: list[float] = []

    ni = ni_latest
    bv = bv_latest

    for t in range(horizon):
        ni = ni * (1.0 + g)
        ri_t = ni - (ke * bv)
        projected_ni.append(ni)
        projected_ri.append(ri_t)
        projected_bv.append(bv)
        # Book value grows by retained earnings
        bv = bv + ni * retention

    # --- Terminal RI ---
    if ke <= g_terminal:
        # Can't compute terminal value; use sum of projected RI only
        logger.warning("Ke (%.4f) <= terminal growth (%.4f) — no terminal RI", ke, g_terminal)
        terminal_ri = 0.0
        pv_terminal = 0.0
    else:
        ri_final = projected_ri[-1]
        terminal_ri = ri_final * (1.0 + g_terminal) / (ke - g_terminal)
        pv_terminal = terminal_ri / (1.0 + ke) ** horizon

    # --- Present values ---
    pv_ri_list = _pv_cashflows(projected_ri, ke)
    sum_pv_ri = sum(pv_ri_list)

    # --- Intrinsic value ---
    equity_value = bv_latest + sum_pv_ri + pv_terminal
    intrinsic = max(0.0, equity_value / shares)  # Floor at zero

    logger.info(
        "RI result: BV=%.2f  Ke=%.4f  sum_pv_ri=%.2f  pv_terminal=%.2f  "
        "equity=%.2f  intrinsic/share=%.2f",
        bv_latest, ke, sum_pv_ri, pv_terminal, equity_value, intrinsic,
    )

    return RIResult(
        book_value_per_share=bv_per_share,
        cost_of_equity=ke,
        growth_rate=g,
        terminal_growth=g_terminal,
        shares_outstanding=shares,
        projected_net_income=projected_ni,
        projected_book_value=projected_bv,
        projected_ri=projected_ri,
        pv_ri=pv_ri_list,
        terminal_ri=terminal_ri,
        pv_terminal_ri=pv_terminal,
        intrinsic_value_per_share=intrinsic,
        equity_value=equity_value,
    )
