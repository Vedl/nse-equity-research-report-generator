"""DCF (FCFF) valuation engine.

Public entry point: ``run_dcf(profile, financials, config) -> DCFResult``

The individual functions (``compute_wacc``, ``compute_base_fcff``, etc.) are
also exported so they can be unit-tested in isolation and called by the report
builder when it needs individual pieces.

Methodology
-----------
* FCFF  = NOPAT + D&A + CapEx_cf + ΔNWC_cf
          (CapEx_cf and ΔNWC_cf are signed as in the cash-flow statement:
          both are negative when they represent cash outflows)
* NOPAT = EBIT × (1 − tax_rate)
* TV    = FCFF_final × (1 + g) / (WACC − g)   [Gordon growth]
* WACC  = (E/V) × Ke + (D/V) × Kd_after_tax
          Ke = Rf + β × ERP   (CAPM)
          Kd = interest_expense / total_debt   (clamped 1%–30%)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from equity_research.config import AppConfig
from equity_research.analysis.ratios import _cagr_series, _col, _latest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WACCComponents:
    """Decomposed WACC for the assumptions appendix."""

    cost_of_equity: float         # Ke = Rf + β × ERP
    cost_of_debt_pretax: float    # Kd = interest_expense / total_debt
    cost_of_debt_aftertax: float  # Kd × (1 − t)
    equity_weight: float          # E / (E + D)
    debt_weight: float            # D / (E + D)
    wacc: float


@dataclass
class DCFResult:
    """Full DCF output — inputs, intermediate steps, and final valuation."""

    # Assumptions used (printed in the appendix)
    base_fcff: float
    fcff_margin: float           # avg FCFF / Revenue over last 3 years
    growth_rate: float           # annual rate applied to projected FCFFs
    wacc: float
    terminal_growth: float
    net_debt: float
    shares_outstanding: float

    # Projections
    projected_fcff: list[float]
    pv_fcff: list[float]

    # Terminal value
    terminal_value_nominal: float
    pv_terminal_value: float

    # Valuation
    enterprise_value: float
    equity_value: float
    intrinsic_value_per_share: float

    # Detail
    wacc_components: WACCComponents
    sensitivity: pd.DataFrame    # WACC × terminal-growth → intrinsic value


# ---------------------------------------------------------------------------
# Pure math functions (all independently testable)
# ---------------------------------------------------------------------------


def terminal_value(fcff_final: float, wacc: float, g: float) -> float:
    """Gordon-growth terminal value for the last projected year's FCFF.

    TV = FCFF_final × (1 + g) / (WACC − g)

    Raises:
        ValueError: if WACC ≤ g (denominator ≤ 0).
    """
    if wacc <= g:
        raise ValueError(
            f"WACC ({wacc:.4f}) must be strictly greater than terminal growth g ({g:.4f})"
        )
    return fcff_final * (1.0 + g) / (wacc - g)


def pv_cashflows(cashflows: list[float], wacc: float) -> list[float]:
    """Present value of each cash flow, discounted at *wacc*.

    Cash flow at position t (0-indexed) is discounted as CF / (1 + wacc)^(t+1).
    """
    return [cf / (1.0 + wacc) ** (t + 1) for t, cf in enumerate(cashflows)]


def project_fcff(base_fcff: float, growth_rates: list[float]) -> list[float]:
    """Grow *base_fcff* year by year at the given rates.

    Args:
        base_fcff:    Starting FCFF (year 0, i.e., the base).
        growth_rates: One rate per projected year.

    Returns:
        list of projected FCFFs, length == len(growth_rates).
    """
    projected: list[float] = []
    fcff = base_fcff
    for g in growth_rates:
        fcff = fcff * (1.0 + g)
        projected.append(fcff)
    return projected


def dcf_equity_per_share(
    projected_fcff: list[float],
    tv: float,
    wacc: float,
    net_debt: float,
    shares: float,
) -> float:
    """Discount projected FCFFs and terminal value to equity value per share.

    EV     = Σ PV(FCFF_t) + PV(TV)
    Equity = EV − Net Debt
    Price  = Equity / Shares Outstanding
    """
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")
    n = len(projected_fcff)
    sum_pv_fcff = sum(pv_cashflows(projected_fcff, wacc))
    pv_tv = tv / (1.0 + wacc) ** n
    ev = sum_pv_fcff + pv_tv
    return (ev - net_debt) / shares


def build_sensitivity_table(
    projected_fcff: list[float],
    wacc_base: float,
    g_base: float,
    net_debt: float,
    shares: float,
    wacc_offsets: tuple[float, ...] = (-0.02, -0.01, 0.0, 0.01, 0.02),
    g_offsets: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
) -> pd.DataFrame:
    """Build a sensitivity table of intrinsic values across WACC × terminal-growth.

    Rows  : WACC values (wacc_base + each offset)
    Columns: terminal growth values (g_base + each offset)
    Cells  : intrinsic value per share; NaN where WACC ≤ g.
    """
    wacc_vals = [wacc_base + w for w in wacc_offsets]
    g_vals = [g_base + g for g in g_offsets]

    data: dict[str, list[float]] = {}
    for g in g_vals:
        col_label = f"{g * 100:.2f}%"
        col: list[float] = []
        for w in wacc_vals:
            if (w - g) < 1e-9 or w <= 0:   # strict gap; guards FP-equal pairs too
                col.append(float("nan"))
            else:
                try:
                    tv = terminal_value(projected_fcff[-1], w, g)
                    val = dcf_equity_per_share(projected_fcff, tv, w, net_debt, shares)
                    col.append(val)
                except Exception:  # noqa: BLE001
                    col.append(float("nan"))
        data[col_label] = col

    return pd.DataFrame(
        data,
        index=pd.Index([f"{w * 100:.2f}%" for w in wacc_vals], name="WACC"),
    )


# ---------------------------------------------------------------------------
# Data-driven helpers
# ---------------------------------------------------------------------------


def compute_wacc(
    profile: dict,
    income: pd.DataFrame,
    balance: pd.DataFrame,
    config: AppConfig,
) -> WACCComponents:
    """Compute WACC from profile, statements, and macro config.

    Raises:
        ValueError: if market_cap is missing or non-positive.
    """
    market_cap = profile.get("market_cap")
    if not market_cap or market_cap <= 0:
        raise ValueError("market_cap is missing or non-positive in profile")

    # Total debt from balance sheet (most recent year)
    debt_s = _col(balance, "total_debt")
    total_debt = max(0.0, _latest(debt_s) or 0.0)

    # Cost of equity — CAPM
    beta = profile.get("beta")
    if beta is None or (isinstance(beta, float) and math.isnan(beta)):
        beta = 1.0
        logger.warning("Beta missing — defaulting to 1.0 for CAPM")
    ke = config.market.risk_free_rate + float(beta) * config.market.equity_risk_premium

    # Cost of debt — interest expense / total debt, clamped
    ie_s = _col(income, "interest_expense")
    latest_ie = _latest(ie_s)
    if latest_ie is not None:
        latest_ie = abs(latest_ie)   # normalise sign
    if latest_ie and total_debt > 0:
        kd_pretax = max(0.01, min(0.30, latest_ie / total_debt))
    else:
        kd_pretax = config.market.risk_free_rate + 0.02
        logger.warning(
            "Cost of debt: no usable interest/debt data — using Rf + 2%% (%.3f)", kd_pretax
        )
    kd_after = kd_pretax * (1.0 - config.market.tax_rate)

    # Capital structure weights
    total_capital = float(market_cap) + total_debt
    eq_w = float(market_cap) / total_capital
    dbt_w = total_debt / total_capital

    wacc = eq_w * ke + dbt_w * kd_after

    logger.info(
        "WACC: Ke=%.4f  Kd(pre)=%.4f  Kd(post)=%.4f  E/V=%.4f  D/V=%.4f  WACC=%.4f",
        ke, kd_pretax, kd_after, eq_w, dbt_w, wacc,
    )

    return WACCComponents(
        cost_of_equity=ke,
        cost_of_debt_pretax=kd_pretax,
        cost_of_debt_aftertax=kd_after,
        equity_weight=eq_w,
        debt_weight=dbt_w,
        wacc=wacc,
    )


def compute_base_fcff(
    income: pd.DataFrame,
    cashflow: pd.DataFrame,
    tax_rate: float,
    n_avg_years: int = 5,
) -> tuple[float, float]:
    """Derive the normalised base-year FCFF and the implied FCFF/Revenue margin.

    FCFF = NOPAT + D&A + CapEx_cf + ΔNWC_cf
    (CapEx_cf < 0 and ΔNWC_cf typically < 0 in the cash-flow statement.)

    Normalisation strategy
    ----------------------
    We compute year-by-year FCFF over the last *n_avg_years* (default 5) and
    take the **median** as the base.  The median is robust to a single year of
    anomalously high capex or NWC swing.

    Negative-median fallback
    ~~~~~~~~~~~~~~~~~~~~~~~~
    For capex-heavy companies mid-investment-cycle (e.g. RELIANCE during Jio
    buildout), the median FCFF can be negative even though the company is
    clearly generating value.  In this case we fall back to the **mean of
    positive-FCFF years** in the window — this is still conservative but
    avoids projecting negative free cash flow into perpetuity.

    If *all* years in the window have negative FCFF, we return the least-
    negative year (i.e. max of negatives) and let the downstream
    ``diverges_materially`` flag handle frontend presentation.

    Returns:
        (base_fcff, fcff_margin) where fcff_margin = base_fcff / latest_revenue.

    Raises:
        ValueError: if there is not enough data to compute at least one year of FCFF.
    """
    rev = _col(income, "total_revenue")
    oi = _col(income, "operating_income")
    da = _col(cashflow, "depreciation_amortization")
    capex = _col(cashflow, "capital_expenditure")
    nwc = _col(cashflow, "change_in_working_capital")

    # Align to years present in both income and cashflow
    frame = pd.DataFrame(
        {"revenue": rev, "op_income": oi, "da": da, "capex": capex, "nwc": nwc}
    ).dropna(subset=["revenue", "op_income"])

    if frame.empty:
        raise ValueError(
            "Cannot compute base FCFF: income statement has no usable revenue/EBIT rows"
        )

    for col in ("da", "capex", "nwc"):
        n_missing = frame[col].isna().sum()
        if n_missing:
            logger.warning(
                "FCFF: '%s' has %d NaN rows — treating missing as 0 (conservative)", col, n_missing
            )
            frame[col] = frame[col].fillna(0.0)

    nopat = frame["op_income"] * (1.0 - tax_rate)
    frame["fcff"] = nopat + frame["da"] + frame["capex"] + frame["nwc"]

    n_use = min(n_avg_years, len(frame))
    recent_fcff = frame["fcff"].iloc[-n_use:]

    # Primary: median of last n_use years
    base_fcff = float(recent_fcff.median())

    # Fallback for negative median: use mean of positive-FCFF years
    if base_fcff <= 0:
        positive_fcff = recent_fcff[recent_fcff > 0]
        if not positive_fcff.empty:
            base_fcff = float(positive_fcff.mean())
            logger.warning(
                "Median FCFF is ≤ 0 — falling back to mean of %d positive-FCFF year(s): %.2f",
                len(positive_fcff), base_fcff,
            )
        else:
            # All years negative — use least-negative (closest to zero)
            base_fcff = float(recent_fcff.max())
            logger.warning(
                "All %d years have negative FCFF — using least-negative: %.2f",
                n_use, base_fcff,
            )

    latest_revenue = float(frame["revenue"].iloc[-1])
    fcff_margin = base_fcff / latest_revenue if latest_revenue else 0.0

    logger.info(
        "Base FCFF (median/%dY): latest_revenue=%.2f  fcff_margin=%.4f  base_fcff=%.2f",
        n_use, latest_revenue, fcff_margin, base_fcff,
    )
    return base_fcff, fcff_margin


def compute_growth_rates(
    income: pd.DataFrame,
    config: AppConfig,
) -> list[float]:
    """Return one growth rate per projection year.

    Source is determined by ``config.dcf.revenue_growth_source``:
    * ``'historical_cagr'`` — 3-year revenue CAGR (falls back to shorter spans,
      then to 8% if no history is available).
    * ``'manual'``          — ``config.dcf.revenue_growth_override`` (required).
    """
    horizon = config.dcf.projection_horizon

    if config.dcf.revenue_growth_source == "manual":
        if config.dcf.revenue_growth_override is None:
            raise ValueError(
                "revenue_growth_source='manual' but revenue_growth_override is not set in config"
            )
        g = float(config.dcf.revenue_growth_override)
        return [g] * horizon

    rev = _col(income, "total_revenue")
    g: float | None = _cagr_series(rev, 3) or _cagr_series(rev, 2) or _cagr_series(rev, 1)
    if g is None:
        g = 0.08
        logger.warning("Revenue CAGR unavailable — using 8%% as projection growth fallback")

    # Clamp to a plausible range for a 5-year DCF
    g = float(max(-0.30, min(0.50, g)))
    logger.info("Projection growth rate: %.2f%%", g * 100)
    return [g] * horizon


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_dcf(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
) -> DCFResult:
    """Run a full FCFF-based DCF and return a DCFResult.

    Args:
        profile:    Normalized company profile dict (from DataProvider.get_profile).
        financials: Dict with keys 'income', 'balance_sheet', 'cash_flow'.
        config:     Loaded AppConfig (macro assumptions + DCF horizon/growth source).

    Raises:
        ValueError: if critical inputs (market_cap, shares, revenue) are absent.
    """
    income = financials["income"]
    balance = financials["balance_sheet"]
    cashflow = financials["cash_flow"]

    wacc_comps = compute_wacc(profile, income, balance, config)
    base_fcff, fcff_margin = compute_base_fcff(income, cashflow, config.market.tax_rate)
    growth_rates = compute_growth_rates(income, config)
    projected = project_fcff(base_fcff, growth_rates)

    # Net debt = Total Debt − Cash
    debt_s = _col(balance, "total_debt")
    cash_s = _col(balance, "cash_and_equivalents")
    latest_debt = max(0.0, _latest(debt_s) or 0.0)
    latest_cash = max(0.0, _latest(cash_s) or 0.0)
    net_debt = latest_debt - latest_cash

    shares = profile.get("shares_outstanding")
    if not shares or shares <= 0:
        raise ValueError("shares_outstanding is missing or invalid in profile")
    shares = float(shares)

    wacc = wacc_comps.wacc
    g_terminal = config.dcf.terminal_growth_rate
    tv = terminal_value(projected[-1], wacc, g_terminal)

    pv_fcff_list = pv_cashflows(projected, wacc)
    n = len(projected)
    pv_tv = tv / (1.0 + wacc) ** n
    ev = sum(pv_fcff_list) + pv_tv
    equity_val = ev - net_debt
    intrinsic = equity_val / shares

    sensitivity = build_sensitivity_table(projected, wacc, g_terminal, net_debt, shares)

    logger.info(
        "DCF result: EV=%.2f  NetDebt=%.2f  EquityVal=%.2f  Intrinsic/share=%.2f",
        ev, net_debt, equity_val, intrinsic,
    )

    return DCFResult(
        base_fcff=base_fcff,
        fcff_margin=fcff_margin,
        growth_rate=growth_rates[0],
        wacc=wacc,
        terminal_growth=g_terminal,
        net_debt=net_debt,
        shares_outstanding=shares,
        projected_fcff=projected,
        pv_fcff=pv_fcff_list,
        terminal_value_nominal=tv,
        pv_terminal_value=pv_tv,
        enterprise_value=ev,
        equity_value=equity_val,
        intrinsic_value_per_share=intrinsic,
        wacc_components=wacc_comps,
        sensitivity=sensitivity,
    )
