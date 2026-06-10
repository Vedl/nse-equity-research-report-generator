"""Rule-based valuation model router.

Picks the appropriate valuation methodology for a company based on
observable financial characteristics.  This is a pure decision function —
no ML, no black box.  Every routing decision can be explained by a
human-readable ``route_reason``.

Routing priority (first match wins):
1. Conglomerate (SOTP)          — config-driven ticker list
2. Financial sector (FINANCIAL) — P/B + ROE spread
3. Loss-making (EV_SALES)       — EV/Revenue for pre-profit companies
4. High-capex cyclical (RI)     — Residual Income model
5. Negative FCFF + leveraged    — EV/EBITDA relative
6. Negative median FCFF         — Residual Income
7. Default                      — FCFF DCF

Public entry point: ``route_model(profile, financials, config) -> RouteDecision``
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig

logger = logging.getLogger(__name__)


class ModelRoute(str, Enum):
    """Valuation model identifier."""

    SOTP = "sotp"                         # Conglomerate — Sum-of-the-Parts
    FINANCIAL = "financial"               # Banks / NBFCs — Justified P/B
    EV_SALES = "ev_sales"                 # Loss-making startups — EV/Revenue
    FCFF = "fcff"                         # Stable, positive-FCF operating company
    RESIDUAL_INCOME = "ri"                # Profitable but volatile/negative FCF
    EXCESS_RETURN = "excess_return"       # Legacy banks path (fallback)
    EV_EBITDA_RELATIVE = "ev_ebitda"      # Infra/utilities mid-capex-cycle


# Confidence level for the selected model
class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class RouteDecision:
    """Result of the model routing decision."""

    model: ModelRoute
    reason: str            # Human-readable explanation of why this route was picked
    confidence: Confidence


# Sectors that should use the financial model
_FINANCIAL_SECTORS = {
    "banks", "non-banking financial", "diversified financial services",
    "insurance", "housing finance", "capital markets",
    "financial services", "credit services",
}


def _is_financial_sector(profile: dict, keywords: list[str]) -> bool:
    """Check if the company is in the financial sector based on industry keywords."""
    industry = (profile.get("industry") or "").lower()
    sector = (profile.get("sector") or "").lower()
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in industry or kw_lower in sector:
            return True
    # Also check against the hardcoded set
    if industry in _FINANCIAL_SECTORS or sector in _FINANCIAL_SECTORS:
        return True
    return False


def _has_operating_income(income: pd.DataFrame) -> bool:
    """Check if the income statement has any usable operating income data."""
    oi = _col(income, "operating_income")
    if oi.empty:
        return False
    valid = oi.dropna()
    if valid.empty:
        return False
    # If all values are zero, treat as missing (common for financials)
    if (valid == 0).all():
        return False
    return True


def _compute_features(
    profile: dict,
    financials: dict[str, pd.DataFrame],
) -> dict:
    """Extract observable features used by the routing decision tree.

    Returns a dict of floats / bools; all values are None-safe.
    """
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())
    cashflow = financials.get("cash_flow", pd.DataFrame())

    # --- FCFF-related ---
    rev = _latest(_col(income, "total_revenue"))
    ebitda = _latest(_col(income, "ebitda"))
    oi = _latest(_col(income, "operating_income"))

    capex_raw = _latest(_col(cashflow, "capital_expenditure"))
    capex_abs = abs(capex_raw) if capex_raw is not None else None

    fcf = _latest(_col(cashflow, "free_cash_flow"))

    # Operating cash flow for capex ratio
    ocf = _latest(_col(cashflow, "operating_cash_flow"))

    # capex intensity = |capex| / revenue
    capex_intensity: float | None = None
    if capex_abs is not None and rev is not None and rev > 0:
        capex_intensity = capex_abs / rev

    # capex / OCF ratio (for high-capex cyclical detection)
    capex_ocf_ratio: float | None = None
    if capex_abs is not None and ocf is not None and abs(ocf) > 0:
        capex_ocf_ratio = capex_abs / abs(ocf)

    # EBIT margin
    ebit_margin: float | None = None
    if oi is not None and rev is not None and rev > 0:
        ebit_margin = oi / rev

    # net_debt / EBITDA (leverage)
    debt = _latest(_col(balance, "total_debt"))
    cash = _latest(_col(balance, "cash_and_equivalents"))
    net_debt = (debt or 0.0) - (cash or 0.0)
    leverage: float | None = None
    if ebitda is not None and ebitda > 0:
        leverage = net_debt / ebitda

    # Book value
    equity = _latest(_col(balance, "stockholders_equity"))

    # Net income
    ni = _latest(_col(income, "net_income"))

    # Median FCFF over available years (replicates compute_base_fcff logic)
    tax_rate = 0.25  # approximate; exact doesn't matter for routing
    oi_series = _col(income, "operating_income")
    da_series = _col(cashflow, "depreciation_amortization")
    capex_series = _col(cashflow, "capital_expenditure")
    nwc_series = _col(cashflow, "change_in_working_capital")

    frame = pd.DataFrame({
        "oi": oi_series, "da": da_series, "capex": capex_series, "nwc": nwc_series,
    }).dropna(subset=["oi"])

    median_fcff: float | None = None
    if not frame.empty:
        for c in ("da", "capex", "nwc"):
            frame[c] = frame[c].fillna(0.0)
        nopat = frame["oi"] * (1.0 - tax_rate)
        fcff_series = nopat + frame["da"] + frame["capex"] + frame["nwc"]
        recent = fcff_series.iloc[-min(5, len(fcff_series)):]
        median_fcff = float(recent.median())

    has_oi = _has_operating_income(income)

    return {
        "has_operating_income": has_oi,
        "trailing_fcf": fcf,
        "median_fcff": median_fcff,
        "capex_intensity": capex_intensity,
        "capex_ocf_ratio": capex_ocf_ratio,
        "ebit_margin": ebit_margin,
        "leverage": leverage,
        "book_value": equity,
        "revenue": rev,
        "ebitda": ebitda,
        "net_debt": net_debt,
        "net_income": ni,
    }


def route_model(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
) -> RouteDecision:
    """Route a company to the appropriate valuation model.

    Decision tree (evaluated top-to-bottom, first match wins):

    1. Conglomerate (from config.yaml)               → SOTP
    2. Financial sector keyword match                → FINANCIAL
    3. No operating income (banks without statements)→ FINANCIAL
    4. Loss-making (negative EBITDA)                 → EV_SALES
    5. High-capex cyclical (capex/OCF > 1.5, EBIT+) → RESIDUAL_INCOME
    6. Negative trailing FCF + capex-heavy + leveraged→ EV_EBITDA_RELATIVE
    7. Negative median FCFF + positive book value    → RESIDUAL_INCOME
    8. Default                                       → FCFF
    """
    features = _compute_features(profile, financials)
    kw = config.router.financial_keywords

    industry = profile.get("industry", "unknown")
    sector = profile.get("sector", "unknown")
    ticker = profile.get("ticker", "UNKNOWN")
    ticker_base = ticker.replace(".NS", "").upper()

    # --- Rule 1: Conglomerate (config-driven) ---
    conglomerates = config.conglomerates or {}
    if ticker_base in conglomerates:
        cong_conf = conglomerates[ticker_base]
        if isinstance(cong_conf, dict) and not cong_conf.get("_use_financial_model", False):
            if cong_conf.get("segments"):
                return RouteDecision(
                    model=ModelRoute.SOTP,
                    reason=(
                        f"Conglomerate detected ({ticker_base}). "
                        "Using Sum-of-the-Parts valuation with segment-specific multiples."
                    ),
                    confidence=Confidence.HIGH,
                )

    # --- Rule 2: Financial sector keyword ---
    if _is_financial_sector(profile, kw):
        return RouteDecision(
            model=ModelRoute.FINANCIAL,
            reason=(
                f"Financial sector detected ({industry}). "
                "Using Justified P/B via ROE spread model."
            ),
            confidence=Confidence.HIGH,
        )

    # --- Rule 3: No operating income (banks without statement data) ---
    if not features["has_operating_income"]:
        return RouteDecision(
            model=ModelRoute.FINANCIAL,
            reason=(
                f"No operating income data available ({sector} / {industry}). "
                "Using Justified P/B model suitable for financial institutions."
            ),
            confidence=Confidence.MEDIUM,
        )

    # --- Rule 4: Loss-making — negative EBITDA ---
    ebitda = features["ebitda"]
    if ebitda is not None and ebitda < 0:
        return RouteDecision(
            model=ModelRoute.EV_SALES,
            reason=(
                f"Negative EBITDA detected (₹{ebitda / 1e7:,.0f} Cr). "
                "Pre-profit company — using EV/Revenue relative valuation."
            ),
            confidence=Confidence.MEDIUM,
        )

    # --- Rule 5: High-capex cyclical ---
    capex_ocf = features["capex_ocf_ratio"]
    ebit_margin = features["ebit_margin"]
    if (
        capex_ocf is not None and capex_ocf > 1.5
        and ebit_margin is not None and ebit_margin > 0.05
        and ebitda is not None and ebitda > 0
    ):
        return RouteDecision(
            model=ModelRoute.RESIDUAL_INCOME,
            reason=(
                f"High-capex cyclical detected (CapEx/OCF = {capex_ocf:.1f}×, "
                f"EBIT margin = {ebit_margin:.1%}). "
                "Using Residual Income model to avoid capex-cycle distortion."
            ),
            confidence=Confidence.MEDIUM,
        )

    # --- Rule 6: Infra / utilities mid-capex-cycle ---
    capex_thresh = config.router.capex_intensity_threshold
    lev_thresh = config.router.leverage_threshold

    fcf = features["trailing_fcf"]
    capex_int = features["capex_intensity"]
    leverage = features["leverage"]

    if (
        fcf is not None and fcf < 0
        and capex_int is not None and capex_int > capex_thresh
        and leverage is not None and leverage > lev_thresh
    ):
        return RouteDecision(
            model=ModelRoute.EV_EBITDA_RELATIVE,
            reason=(
                f"Negative trailing FCF with high capex intensity "
                f"({capex_int:.0%} > {capex_thresh:.0%}) and leverage "
                f"({leverage:.1f}× > {lev_thresh:.1f}×). "
                "Using EV/EBITDA relative valuation."
            ),
            confidence=Confidence.LOW,
        )

    # --- Rule 7: Negative median FCFF but profitable with book value ---
    median_fcff = features["median_fcff"]
    bv = features["book_value"]

    if median_fcff is not None and median_fcff <= 0 and bv is not None and bv > 0:
        return RouteDecision(
            model=ModelRoute.RESIDUAL_INCOME,
            reason=(
                "Median trailing FCFF is negative or zero, but company has "
                f"positive book value (₹{bv / 1e7:,.0f} Cr). "
                "Using residual income model."
            ),
            confidence=Confidence.MEDIUM,
        )

    # --- Rule 8: Default → FCFF ---
    return RouteDecision(
        model=ModelRoute.FCFF,
        reason="Stable positive free cash flow — standard FCFF DCF model.",
        confidence=Confidence.HIGH,
    )
