"""Valuation orchestrator — routes to the appropriate model and cross-checks.

Replaces the old ``valuation_summary()`` with ``run_valuation()`` which:
1. Calls the router to pick the right model
2. Dispatches to the appropriate engine (SOTP, Financial, EV/Sales, FCFF, RI, ER)
3. Always runs relative valuation as a cross-check
4. Floors negative equity values at zero with intelligent fallback
5. Returns a unified ValuationResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from equity_research.analysis.comps import CompsResult
from equity_research.analysis.dcf import DCFResult, run_dcf
from equity_research.analysis.excess_return import ExcessReturnResult, run_excess_return
from equity_research.analysis.financial_sector import (
    FinancialValuationResult,
    run_financial_valuation,
)
from equity_research.analysis.relative_valuation import (
    RelativeRange,
    relative_valuation_range,
)
from equity_research.analysis.residual_income import RIResult, run_residual_income
from equity_research.analysis.sotp import (
    SOTPResult,
    parse_conglomerates_config,
    run_sotp,
)
from equity_research.analysis.india_valuation import (
    IndiaValuationResult,
    IndiaValuationEngine,
    build_india_inputs,
)
from equity_research.analysis.router import (
    ModelRoute,
    route_model,
)
from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider
from equity_research.utils.formatting import safe_divide

logger = logging.getLogger(__name__)


@dataclass
class PathToBreakevenResult:
    """Path-to-profitability metrics for loss-making startups."""

    cash_runway_quarters: float | None
    breakeven_revenue: float | None
    current_revenue: float | None
    gap_to_breakeven_pct: float | None
    gross_margin: float | None


@dataclass
class ValuationResult:
    """Unified valuation output from the model router."""

    # Routing info
    model_used: str                  # ModelRoute enum value
    route_reason: str                # Human-readable explanation
    confidence: str                  # Confidence enum value

    # Headline numbers
    intrinsic_value: float | None    # Per-share, floored at 0
    current_price: float | None
    market_divergence_pct: float | None
    diverges_materially: bool

    # Model-specific results (only one is populated)
    dcf_result: DCFResult | None = None
    ri_result: RIResult | None = None
    excess_return_result: ExcessReturnResult | None = None
    financial_result: FinancialValuationResult | None = None
    sotp_result: SOTPResult | None = None

    # Loss-making startup extras
    path_to_breakeven: PathToBreakevenResult | None = None

    # Relative valuation cross-check (always populated when peers available)
    relative: RelativeRange | None = None
    comps_result: CompsResult | None = None

    # Proprietary India valuation output
    india_result: IndiaValuationResult | None = None

    # Broker consensus (surfaced as a cross-check, never a convergence target)
    broker_target_price: float | None = None
    broker_target_median: float | None = None
    broker_target_low: float | None = None
    broker_target_high: float | None = None
    broker_recommendation: str | None = None
    broker_analyst_count: int | None = None
    broker_upside_pct: float | None = None
    model_vs_broker_pct: float | None = None

def _compute_path_to_breakeven(
    financials: dict[str, pd.DataFrame],
) -> PathToBreakevenResult | None:
    """Compute path-to-profitability metrics for loss-making companies."""
    try:
        income = financials.get("income", pd.DataFrame())
        balance = financials.get("balance_sheet", pd.DataFrame())
        cashflow = financials.get("cash_flow", pd.DataFrame())

        revenue = _latest(_col(income, "total_revenue"))
        gross_profit = _latest(_col(income, "gross_profit"))
        ebitda = _latest(_col(income, "ebitda"))
        ocf = _latest(_col(cashflow, "operating_cash_flow"))
        cash = _latest(_col(balance, "cash_and_equivalents"))

        gross_margin: float | None = None
        if revenue and revenue > 0 and gross_profit is not None:
            gross_margin = gross_profit / revenue

        # Cash runway = cash / quarterly burn
        cash_runway: float | None = None
        if cash and ocf is not None and ocf < 0:
            quarterly_burn = abs(ocf) / 4
            if quarterly_burn > 0:
                cash_runway = cash / quarterly_burn

        # Breakeven revenue: at current gross margin, what revenue = EBITDA breakeven?
        breakeven_rev: float | None = None
        if ebitda is not None and ebitda < 0 and gross_margin and gross_margin > 0:
            # Operating expenses above gross profit = |negative EBITDA| + gross_profit
            # Actually: breakeven_rev ≈ revenue × (1 + |EBITDA| / gross_profit)
            if gross_profit and gross_profit > 0:
                breakeven_rev = revenue * (1 + abs(ebitda) / gross_profit)

        gap_pct: float | None = None
        if breakeven_rev and revenue and revenue > 0:
            gap_pct = (breakeven_rev / revenue - 1.0)

        return PathToBreakevenResult(
            cash_runway_quarters=cash_runway,
            breakeven_revenue=breakeven_rev,
            current_revenue=revenue,
            gap_to_breakeven_pct=gap_pct,
            gross_margin=gross_margin,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Path-to-breakeven calculation failed: %s", exc)
        return None


def _ev_sales_valuation(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    relative: RelativeRange | None,
    comps_result: CompsResult | None,
) -> float | None:
    """Compute intrinsic value from EV/Sales for loss-making companies.

    Uses the peer-median EV/Sales multiple × company revenue - net debt.
    """
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())

    revenue = _latest(_col(income, "total_revenue"))
    if not revenue or revenue <= 0:
        return None

    # Get EV/Sales from relative valuation
    ev_sales_implied = None
    if relative and relative.implied_ev_sales is not None:
        ev_sales_implied = relative.implied_ev_sales

    # Fallback: use profile's enterprise_to_revenue if peer data unavailable
    if ev_sales_implied is None:
        etr = profile.get("enterprise_to_revenue")
        if etr and etr > 0:
            # Apply peer median multiple (approximate)
            shares = profile.get("shares_outstanding")
            if shares and shares > 0:
                ev_sales_implied = etr * revenue / shares
                # But this just gives us current price — not useful
                ev_sales_implied = None

    if ev_sales_implied is not None and ev_sales_implied > 0:
        return ev_sales_implied

    # Last resort: use a conservative 3× EV/Sales for high-growth startups
    shares = profile.get("shares_outstanding")
    if not shares or shares <= 0:
        mktcap = profile.get("market_cap")
        price = profile.get("current_price")
        if mktcap and price and price > 0:
            shares = mktcap / price
        else:
            return None

    debt = _latest(_col(balance, "total_debt"))
    cash = _latest(_col(balance, "cash_and_equivalents"))
    net_debt = (debt or 0.0) - (cash or 0.0)

    # Use 3× EV/Sales as conservative default for loss-making Indian startups
    implied_ev = revenue * 3.0
    equity = implied_ev - net_debt
    return max(0.0, equity / shares)


def run_valuation(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    provider: DataProvider,
    config: AppConfig,
) -> ValuationResult:
    """Run the full valuation pipeline: route → model → cross-check.

    This is the main entry point for valuation. Routes to the correct model
    for every company type: banks, conglomerates, startups, cyclicals, and
    standard operating companies.
    """
    current_price = profile.get("current_price")

    # --- Step 1: Route ---
    decision = route_model(profile, financials, config)
    logger.info(
        "Model router: %s → %s (confidence=%s, reason='%s')",
        profile.get("ticker", "?"), decision.model.value,
        decision.confidence.value, decision.reason,
    )

    # --- Step 2: Run intrinsic model ---
    dcf_result: DCFResult | None = None
    ri_result: RIResult | None = None
    er_result: ExcessReturnResult | None = None
    financial_result: FinancialValuationResult | None = None
    sotp_result: SOTPResult | None = None
    path_to_breakeven: PathToBreakevenResult | None = None
    intrinsic: float | None = None

    try:
        if decision.model == ModelRoute.SOTP:
            # Parse conglomerate config
            cong_configs = parse_conglomerates_config(config.conglomerates)
            ticker_base = profile.get("ticker", "").replace(".NS", "").upper()
            if ticker_base in cong_configs:
                cong_conf = cong_configs[ticker_base]
                sotp_result = run_sotp(profile, financials, config, cong_conf)
                intrinsic = sotp_result.intrinsic_value_per_share
            else:
                logger.warning("SOTP routed but no config for %s — falling back to FCFF", ticker_base)
                decision.model = ModelRoute.FCFF
                dcf_result = run_dcf(profile, financials, config)
                intrinsic = dcf_result.intrinsic_value_per_share

        elif decision.model == ModelRoute.FINANCIAL:
            financial_result = run_financial_valuation(profile, financials, config)
            intrinsic = financial_result.intrinsic_value_per_share

        elif decision.model == ModelRoute.EV_SALES:
            # EV/Sales needs relative valuation first — computed below
            path_to_breakeven = _compute_path_to_breakeven(financials)
            intrinsic = None  # will be set after relative valuation

        elif decision.model == ModelRoute.FCFF:
            dcf_result = run_dcf(profile, financials, config)
            intrinsic = dcf_result.intrinsic_value_per_share

        elif decision.model == ModelRoute.RESIDUAL_INCOME:
            ri_result = run_residual_income(profile, financials, config)
            intrinsic = ri_result.intrinsic_value_per_share

        elif decision.model == ModelRoute.EXCESS_RETURN:
            er_result = run_excess_return(profile, financials, config)
            intrinsic = er_result.intrinsic_value_per_share

        elif decision.model == ModelRoute.EV_EBITDA_RELATIVE:
            # No intrinsic model — will rely on relative valuation
            intrinsic = None

    except (ValueError, ZeroDivisionError) as exc:
        logger.warning(
            "Intrinsic model %s failed for %s: %s — falling back to relative only",
            decision.model.value, profile.get("ticker", "?"), exc,
        )
        intrinsic = None

    # --- Step 3: Relative valuation cross-check ---
    relative, comps_result = relative_valuation_range(
        profile, financials, provider, config,
    )

    # --- Step 3b: EV/Sales for loss-making startups ---
    if decision.model == ModelRoute.EV_SALES and intrinsic is None:
        intrinsic = _ev_sales_valuation(profile, financials, relative, comps_result)

    # --- Floor negative intrinsic at zero, or fallback to relative ---
    if intrinsic is not None and intrinsic <= 0:
        if relative and relative.median is not None and relative.median > 0:
            logger.info(
                "Intrinsic value %.2f is negative/zero. Falling back to relative median %.2f",
                intrinsic, relative.median
            )
            intrinsic = relative.median
            decision.reason += " (Note: Intrinsic model yielded negative value; fell back to Relative Median)."
            decision.model = ModelRoute.EV_EBITDA_RELATIVE
        else:
            logger.info(
                "Intrinsic value %.2f floored to 0 (equity can't be worth less than zero)",
                intrinsic,
            )
            intrinsic = 0.0

    # For EV_EBITDA_RELATIVE route, use the relative median as the "intrinsic"
    if decision.model == ModelRoute.EV_EBITDA_RELATIVE and (intrinsic is None or intrinsic <= 0):
        if relative and relative.median is not None:
            intrinsic = max(0.0, relative.median)

    # --- Step 4: Divergence check ---
    divergence_pct: float | None = None
    diverges = False
    if intrinsic is not None and current_price and current_price > 0:
        divergence_pct = (intrinsic - current_price) / current_price
        diverges = abs(divergence_pct) > 0.35

    # --- Step 5: India Valuation Adjustments ---
    # Skip India adjustments for SOTP (already has its own structural adjustments)
    india_res: IndiaValuationResult | None = None
    if intrinsic is not None and decision.model != ModelRoute.SOTP:
        try:
            # Extract wacc and terminal growth based on model used
            wacc = 0.10
            tg = config.dcf.terminal_growth_rate

            if dcf_result:
                wacc = dcf_result.wacc
                tg = dcf_result.terminal_growth
            elif ri_result:
                wacc = ri_result.cost_of_equity
                tg = ri_result.terminal_growth
            elif er_result:
                wacc = er_result.cost_of_equity
                tg = er_result.terminal_growth
            elif financial_result:
                wacc = financial_result.cost_of_equity
                tg = financial_result.terminal_growth

            inputs = build_india_inputs(
                ticker=profile.get("ticker", ""),
                profile=profile,
                financials=financials,
                dcf_equity_value_per_share=intrinsic,
                dcf_wacc=wacc,
                dcf_terminal_growth=tg,
            )
            india_res = IndiaValuationEngine(inputs).run()
            logger.info("India Valuation completed successfully: Blended=%.2f", india_res.blended_value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("India Valuation Engine failed: %s", exc)
            india_res = None

    # --- Step 6: Broker consensus comparison ---
    broker_target_price = profile.get("target_mean_price")
    broker_target_median = profile.get("target_median_price")
    broker_target_low = profile.get("target_low_price")
    broker_target_high = profile.get("target_high_price")
    broker_recommendation = profile.get("recommendation_key")
    broker_analyst_count = profile.get("number_of_analyst_opinions")
    
    broker_upside_pct: float | None = None
    if broker_target_price and current_price and current_price > 0:
        broker_upside_pct = (broker_target_price - current_price) / current_price
        
    model_vs_broker_pct: float | None = None
    final_val = india_res.blended_value if india_res else intrinsic
    if final_val is not None and broker_target_price and broker_target_price > 0:
        model_vs_broker_pct = (final_val - broker_target_price) / broker_target_price

    return ValuationResult(
        model_used=decision.model.value,
        route_reason=decision.reason,
        confidence=decision.confidence.value,
        intrinsic_value=intrinsic,
        current_price=current_price,
        market_divergence_pct=divergence_pct,
        diverges_materially=diverges,
        dcf_result=dcf_result,
        ri_result=ri_result,
        excess_return_result=er_result,
        financial_result=financial_result,
        sotp_result=sotp_result,
        path_to_breakeven=path_to_breakeven,
        relative=relative,
        comps_result=comps_result,
        india_result=india_res,
        broker_target_price=broker_target_price,
        broker_target_median=broker_target_median,
        broker_target_low=broker_target_low,
        broker_target_high=broker_target_high,
        broker_recommendation=broker_recommendation,
        broker_analyst_count=broker_analyst_count,
        broker_upside_pct=broker_upside_pct,
        model_vs_broker_pct=model_vs_broker_pct,
    )


@dataclass
class ValuationSummary:
    """Consolidated valuation output for the report's valuation section (for report builder backward-compatibility)."""

    current_price: float

    # DCF
    dcf_value: float | None
    dcf_upside_pct: float | None       # (dcf_value − price) / price

    # Comps-derived range
    comps_low: float | None
    comps_high: float | None
    comps_median: float | None
    comps_upside_pct: float | None     # (comps_median − price) / price


def valuation_summary(
    current_price: float,
    dcf_result: DCFResult | None,
    comps_result: CompsResult | None,
) -> ValuationSummary:
    """Combine DCF and comps outputs into a single summary with upside/downside.

    Backward compatibility helper for PDF report builder.
    """
    if current_price <= 0:
        logger.warning("current_price ≤ 0 — upside percentages will be None")

    dcf_value = dcf_result.intrinsic_value_per_share if dcf_result else None
    dcf_upside = safe_divide(
        (dcf_value - current_price) if dcf_value is not None else None,
        current_price if current_price > 0 else None,
    )

    comps_low = comps_result.implied_low if comps_result else None
    comps_high = comps_result.implied_high if comps_result else None
    comps_median = comps_result.implied_median if comps_result else None
    comps_upside = safe_divide(
        (comps_median - current_price) if comps_median is not None else None,
        current_price if current_price > 0 else None,
    )

    logger.info(
        "ValuationSummary: price=%.2f  DCF=%.2f (%.1f%%)  comps=[%.2f, %.2f] median=%.2f (%.1f%%)",
        current_price,
        dcf_value or 0,
        (dcf_upside or 0) * 100,
        comps_low or 0,
        comps_high or 0,
        comps_median or 0,
        (comps_upside or 0) * 100,
    )

    return ValuationSummary(
        current_price=current_price,
        dcf_value=dcf_value,
        dcf_upside_pct=dcf_upside,
        comps_low=comps_low,
        comps_high=comps_high,
        comps_median=comps_median,
        comps_upside_pct=comps_upside,
    )
