"""Financial sector valuation — Justified P/B via ROE Spread.

The correct model for banks, NBFCs, insurance, and financial services:

    Justified P/B = (ROE − g) / (Ke − g)

Where:
    ROE = trailing Return on Equity
    g   = sustainable growth rate = ROE × retention ratio
    Ke  = cost of equity via CAPM (Rf + β × ERP)

This is CFA Level 2, Equity Valuation (Reading 25).

Public entry point: ``run_financial_valuation(profile, financials, config) -> FinancialValuationResult``
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class BankMetrics:
    """Additional bank-specific metrics for the report."""

    net_interest_margin: float | None   # NIM = Net Interest Income / Avg Earning Assets
    gross_npa_ratio: float | None       # GNPA % (from profile or derived)
    credit_cost: float | None           # Provisions / Avg Loans
    casa_ratio: float | None            # Current + Savings / Total Deposits
    tier1_ratio: float | None           # Tier 1 Capital ratio (regulatory)


@dataclass
class FinancialValuationResult:
    """Financial sector valuation output."""

    # Core model outputs
    justified_pb: float
    intrinsic_value_per_share: float
    equity_value: float

    # Model inputs
    book_value_per_share: float
    cost_of_equity: float               # Ke from CAPM
    roe: float                          # trailing ROE used
    growth_rate: float                  # sustainable growth
    terminal_growth: float
    shares_outstanding: float
    retention_ratio: float

    # Spread analysis
    roe_ke_spread: float                # ROE − Ke (positive = value creation)

    # Sensitivity: justified P/B at different ROE and Ke assumptions
    sensitivity_roe_labels: list[float]
    sensitivity_ke_labels: list[float]
    sensitivity_pb: list[list[float]]   # [roe_idx][ke_idx]

    # Bank-specific metrics (may be partially None)
    bank_metrics: BankMetrics

    # Whether we had to use fallback data
    is_fallback: bool
    fallback_note: str

    # H-Model DDM (CFA L2 Equity, Reading 23: Discounted Dividend Valuation)
    ddm_value_per_share: float | None = None
    ddm_dps0: float | None = None       # current DPS used as D0
    ddm_g_short: float | None = None    # near-term growth gS
    ddm_g_long: float | None = None     # terminal growth gL
    ddm_h: float | None = None          # half-life of the fade (years)
    pb_model_value: float | None = None # pure Justified P/B value (pre-blend)


def h_model_ddm(
    dps0: float,
    g_short: float,
    g_long: float,
    half_life: float,
    cost_of_equity: float,
) -> float:
    """H-Model: V = [D0×(1+gL) + D0×H×(gS−gL)] / (r − gL).

    # CFA L2 Equity, Reading 23: Discounted Dividend Valuation — H-Model.
    Growth fades linearly from g_short to g_long over 2H years.

    Raises:
        ValueError: if cost_of_equity ≤ g_long (undefined perpetuity).
    """
    if cost_of_equity <= g_long:
        raise ValueError(
            f"Ke ({cost_of_equity:.2%}) must exceed long-run growth ({g_long:.2%})"
        )
    return (dps0 * (1.0 + g_long) + dps0 * half_life * (g_short - g_long)) / (
        cost_of_equity - g_long
    )


def justified_pb(roe: float, growth: float, cost_of_equity: float) -> float:
    """CFA L2 Equity — justified P/B via residual income theory.

    Returns the theoretically justified price-to-book multiple.
    Handles edge case where Ke == g (prevents division by zero).
    """
    if abs(cost_of_equity - growth) < 1e-6:
        return 1.0  # no spread → fair value is book value
    pb = (roe - growth) / (cost_of_equity - growth)
    # Clamp to plausible range [0.1, 10.0] to avoid extreme outliers
    return max(0.1, min(10.0, pb))


def _compute_ke(profile: dict, config: AppConfig) -> float:
    """Compute cost of equity from CAPM. Ke = Rf + β × ERP."""
    beta = profile.get("beta")
    if beta is None or (isinstance(beta, float) and math.isnan(beta)):
        beta = 1.0
        logger.warning("Beta missing for financial — defaulting to 1.0")
    return config.market.risk_free_rate + float(beta) * config.market.equity_risk_premium


def _extract_bank_metrics(
    profile: dict,
    financials: dict[str, pd.DataFrame],
) -> BankMetrics:
    """Extract bank-specific metrics from profile and financials.

    Most of these are not directly available from yfinance for Indian banks,
    so we derive what we can and leave the rest as None.
    """
    income = financials.get("income", pd.DataFrame())

    # NIM: approximate from (operating_income / total_assets) if available
    nim: float | None = None
    oi = _latest(_col(income, "operating_income"))
    balance = financials.get("balance_sheet", pd.DataFrame())
    total_assets = _latest(_col(balance, "total_assets"))
    if oi is not None and total_assets is not None and total_assets > 0:
        nim = oi / total_assets
        # NIM should be in 1-8% range for Indian banks
        if nim < 0 or nim > 0.15:
            nim = None

    # GNPA, CASA, Tier1 are not available from yfinance — leave as None
    # These would need a premium data source like CMIE Prowess
    return BankMetrics(
        net_interest_margin=nim,
        gross_npa_ratio=None,
        credit_cost=None,
        casa_ratio=None,
        tier1_ratio=None,
    )


def _build_sensitivity(
    growth: float,
    cost_of_equity: float,
    roe: float,
) -> tuple[list[float], list[float], list[list[float]]]:
    """Build a sensitivity table: justified P/B at different ROE and Ke."""
    roe_range = [
        max(0.01, roe - 0.04),
        max(0.01, roe - 0.02),
        roe,
        roe + 0.02,
        roe + 0.04,
    ]
    ke_range = [
        max(0.04, cost_of_equity - 0.02),
        max(0.04, cost_of_equity - 0.01),
        cost_of_equity,
        cost_of_equity + 0.01,
        cost_of_equity + 0.02,
    ]

    table: list[list[float]] = []
    for r in roe_range:
        row: list[float] = []
        for k in ke_range:
            # Use a modest growth rate assumption for sensitivity
            g = min(r * 0.7, growth)  # 70% retention × ROE
            g = min(g, k - 0.005)    # ensure g < ke
            pb = justified_pb(r, g, k)
            row.append(round(pb, 2))
        table.append(row)

    return (
        [round(r, 4) for r in roe_range],
        [round(k, 4) for k in ke_range],
        table,
    )


def run_financial_valuation(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
) -> FinancialValuationResult:
    """Run a Justified P/B valuation for a financial institution.

    Args:
        profile:    Normalized company profile dict.
        financials: Dict with keys 'income', 'balance_sheet'.
        config:     Loaded AppConfig.

    Raises:
        ValueError: if shares_outstanding and book value are both unavailable.
    """
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())

    # --- Shares outstanding (with fallback chain) ---
    shares = profile.get("shares_outstanding")
    fallback_note = ""
    is_fallback = False

    if not shares or shares <= 0:
        # Fallback: market_cap / price
        mktcap = profile.get("market_cap")
        price = profile.get("current_price")
        if mktcap and price and price > 0:
            shares = mktcap / price
            fallback_note = "Shares derived from market_cap / price. "
            is_fallback = True
            logger.info("Shares fallback: market_cap / price = %.0f", shares)
        else:
            raise ValueError("shares_outstanding unavailable and cannot be derived")

    shares = float(shares)

    # --- Cost of equity ---
    ke = _compute_ke(profile, config)

    # --- Book value ---
    equity_s = _col(balance, "stockholders_equity")
    bv_latest = _latest(equity_s)

    if bv_latest is None or bv_latest <= 0:
        # Attempt from profile P/B
        pb = profile.get("price_to_book")
        price = profile.get("current_price")
        if pb and pb > 0 and price and price > 0:
            bv_per_share = price / pb
            bv_latest = bv_per_share * shares
            fallback_note += "Book value derived from price / P/B. "
            is_fallback = True
        else:
            raise ValueError("Book value unavailable for financial valuation")

    bv_per_share = bv_latest / shares

    # --- ROE ---
    roe: float | None = None

    # Method 1: multi-year average from statements
    eq_series = _col(balance, "stockholders_equity")
    ni_series = _col(income, "net_income")
    if not eq_series.empty and not ni_series.empty:
        common = eq_series.index.intersection(ni_series.index)
        if len(common) >= 2:
            roe_vals = ni_series.loc[common] / eq_series.loc[common]
            valid_roe = roe_vals.dropna()
            valid_roe = valid_roe[valid_roe.between(-0.5, 0.5)]
            if not valid_roe.empty:
                roe = float(valid_roe.mean())

    # Method 2: latest year
    if roe is None:
        ni_latest = _latest(ni_series)
        if ni_latest is not None and bv_latest > 0:
            roe = ni_latest / bv_latest

    # Method 3: profile
    if roe is None:
        roe_profile = profile.get("return_on_equity")
        if roe_profile is not None and math.isfinite(roe_profile):
            roe = float(roe_profile)

    # Method 4: absolute fallback
    if roe is None or not math.isfinite(roe):
        roe = ke + 0.02  # assume marginal value creator
        fallback_note += "ROE unavailable — assumed Ke + 2%. "
        is_fallback = True

    # Clamp ROE to [-5%, 40%]
    roe = max(-0.05, min(0.40, roe))

    # --- Payout ratio & sustainable growth ---
    div_yield = profile.get("dividend_yield")
    price = profile.get("current_price")
    ni_latest = _latest(ni_series) if not ni_series.empty else None
    if div_yield and price and price > 0 and ni_latest and ni_latest > 0:
        total_dividends = div_yield * price * shares
        payout_ratio = min(0.90, max(0.0, total_dividends / ni_latest))
    else:
        payout_ratio = 0.30  # banks typically pay ~30%
    retention = 1.0 - payout_ratio
    sustainable_g = roe * retention

    # Cap growth at Rf + 2% to avoid absurd terminal value
    sustainable_g = min(sustainable_g, config.market.risk_free_rate + 0.02)
    # Ensure growth < cost of equity
    sustainable_g = min(sustainable_g, ke - 0.005)

    # --- Justified P/B ---
    pb_justified = justified_pb(roe, sustainable_g, ke)
    pb_value = pb_justified * bv_per_share

    # --- H-Model DDM (blended 50/50 with Justified P/B when DPS available) ---
    # # CFA L2 Equity, Reading 23: H-Model — growth fades from gS to gL over 2H years
    ddm_value: float | None = None
    dps0: float | None = None
    g_long = min(config.dcf.terminal_growth_rate, ke - 0.01)
    h_half_life = 5.0   # 10-year linear fade
    # Guard: a dividend yield above ~25% is implausible (a mis-scaled feed); skip
    # the DDM blend rather than let an exploded DPS0 inflate the intrinsic value.
    if div_yield and price and price > 0 and float(div_yield) <= 0.25:
        dps0 = float(div_yield) * float(price)
        if dps0 > 0 and ke > g_long:
            try:
                ddm_value = h_model_ddm(dps0, sustainable_g, g_long, h_half_life, ke)
                if ddm_value <= 0:
                    ddm_value = None
            except ValueError as exc:
                logger.warning("H-Model DDM failed: %s", exc)
                ddm_value = None

    if ddm_value is not None:
        intrinsic = 0.5 * pb_value + 0.5 * ddm_value
        logger.info(
            "Bank intrinsic: 50/50 blend of Justified P/B (%.2f) and H-Model DDM (%.2f)",
            pb_value, ddm_value,
        )
    else:
        intrinsic = pb_value
    equity_value = intrinsic * shares

    # --- Sensitivity table ---
    sens_roe, sens_ke, sens_pb = _build_sensitivity(sustainable_g, ke, roe)

    # --- Bank-specific metrics ---
    bank_metrics = _extract_bank_metrics(profile, financials)

    logger.info(
        "Financial valuation: ROE=%.4f Ke=%.4f spread=%.4f justified_P/B=%.2f "
        "BV/share=%.2f intrinsic=%.2f",
        roe, ke, roe - ke, pb_justified, bv_per_share, intrinsic,
    )

    return FinancialValuationResult(
        justified_pb=pb_justified,
        intrinsic_value_per_share=max(0.0, intrinsic),
        equity_value=max(0.0, equity_value),
        book_value_per_share=bv_per_share,
        cost_of_equity=ke,
        roe=roe,
        growth_rate=sustainable_g,
        terminal_growth=config.dcf.terminal_growth_rate,
        shares_outstanding=shares,
        retention_ratio=retention,
        roe_ke_spread=roe - ke,
        sensitivity_roe_labels=sens_roe,
        sensitivity_ke_labels=sens_ke,
        sensitivity_pb=sens_pb,
        bank_metrics=bank_metrics,
        is_fallback=is_fallback,
        fallback_note=fallback_note,
        ddm_value_per_share=ddm_value,
        ddm_dps0=dps0,
        ddm_g_short=sustainable_g,
        ddm_g_long=g_long,
        ddm_h=h_half_life,
        pb_model_value=pb_value,
    )
