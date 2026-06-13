"""Full research pipeline — valuation, quality screens, governance, conviction.

Single orchestration point used by both the FastAPI layer and the PDF report
builder, so the API JSON and the PDF always present identical numbers.

    bundle = run_research_pipeline(profile, financials, provider, config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, TypeVar

import pandas as pd

from equity_research.analysis.beta import BetaResult, regression_beta
from equity_research.analysis.conviction import (
    ConvictionResult,
    assign_rating,
    blend_values,
    confidence_score,
)
from equity_research.analysis.governance import GovernanceResult, governance_scorecard
from equity_research.analysis.quality import (
    AccrualsResult,
    AltmanResult,
    BeneishResult,
    CAQResult,
    CCCResult,
    DuPontResult,
    GrossProfitabilityResult,
    PiotroskiResult,
    accruals_analysis,
    altman_z_score,
    beneish_m_score,
    capital_allocation_score,
    cash_conversion_cycle,
    dupont_decomposition,
    gross_profitability,
    piotroski_f_score,
    roic_series,
)
from equity_research.analysis.ratios import _col
from equity_research.analysis.residual_income import run_residual_income
from equity_research.analysis.valuation import ValuationResult, run_valuation
from equity_research.analysis.value_driver import ValueDriverResult, run_value_driver
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _safe(label: str, fn: Callable[[], _T], fallback: Callable[[], _T]) -> _T:
    """Run a best-effort analysis stage in isolation.

    Quality/governance screens are supplementary: a single one raising on a
    malformed or missing yfinance field for one company must NOT take down the
    whole research report (it previously propagated out and 500'd the
    ``/api/research`` endpoint).  On failure we log and return the stage's own
    empty-input result, so that section simply renders as "unavailable".
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Research stage '%s' failed (%s) — section marked unavailable", label, exc
        )
        return fallback()


@dataclass
class ResearchBundle:
    """Everything the report and API need, computed once."""

    valuation: ValuationResult
    conviction: ConvictionResult
    beta: BetaResult
    piotroski: PiotroskiResult
    beneish: BeneishResult
    altman: AltmanResult
    accruals: AccrualsResult
    dupont: DuPontResult
    gross_profitability: GrossProfitabilityResult
    caq: CAQResult
    ccc: CCCResult
    governance: GovernanceResult
    value_driver: ValueDriverResult | None


def _clean_data_years(income: pd.DataFrame) -> int:
    """Years with both revenue and net income present."""
    rev = _col(income, "total_revenue")
    ni = _col(income, "net_income")
    frame = pd.concat([rev, ni], axis=1, join="inner").dropna()
    return len(frame)


def _extract_wacc(val: ValuationResult, config: AppConfig) -> float:
    """Best-available discount rate from whichever model ran."""
    if val.dcf_result:
        return val.dcf_result.wacc
    if val.ri_result:
        return val.ri_result.cost_of_equity
    if val.financial_result:
        return val.financial_result.cost_of_equity
    return config.market.risk_free_rate + config.market.equity_risk_premium


def _secondary_value(
    val: ValuationResult,
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
) -> tuple[str | None, float | None]:
    """Pick and run the secondary model for the routed primary.

    FCFF → Residual Income (anchors to book value — robust when FCF volatile);
    all other primaries → relative-valuation median as the cross-check.
    """
    if val.model_used == "fcff":
        try:
            ri = run_residual_income(profile, financials, config)
            if ri.intrinsic_value_per_share and ri.intrinsic_value_per_share > 0:
                return "Residual Income (Penman)", ri.intrinsic_value_per_share
        except (ValueError, ZeroDivisionError) as exc:
            logger.info("Secondary RI model unavailable: %s", exc)
    if val.relative and val.relative.median and val.relative.median > 0:
        return "Peer-multiple median", val.relative.median
    return None, None


def run_research_pipeline(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    provider: DataProvider,
    config: AppConfig,
) -> ResearchBundle:
    """Run the complete analysis: beta → valuation → quality → conviction."""
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())
    cashflow = financials.get("cash_flow", pd.DataFrame())
    ticker = profile.get("ticker", "?")

    # --- Beta: regression vs Nifty 50, fallbacks documented ---
    beta_res = regression_beta(
        provider, ticker,
        sector=profile.get("sector"),
        provider_beta=profile.get("beta"),
    )
    profile = dict(profile)
    profile["beta"] = beta_res.beta   # CAPM downstream uses the estimated beta
    logger.info("Beta for %s: %.2f (%s)", ticker, beta_res.beta, beta_res.source)

    # --- Primary valuation (router + intrinsic + relative cross-check) ---
    val = run_valuation(profile, financials, provider, config)

    # --- Secondary model ---
    secondary_model, secondary_value = _secondary_value(val, profile, financials, config)

    # --- Quality screens (each best-effort: one failure must not 500 the report) ---
    is_financial = val.model_used in ("financial", "excess_return")
    _empty = pd.DataFrame()
    piotroski = _safe(
        "piotroski",
        lambda: piotroski_f_score(income, balance, cashflow),
        lambda: piotroski_f_score(_empty, _empty, _empty),
    )
    beneish = _safe(
        "beneish",
        lambda: beneish_m_score(income, balance, cashflow),
        lambda: beneish_m_score(_empty, _empty, _empty),
    )
    altman = _safe(
        "altman",
        lambda: altman_z_score(income, balance, is_financial=is_financial),
        lambda: altman_z_score(_empty, _empty, is_financial=is_financial),
    )
    accruals = _safe(
        "accruals",
        lambda: accruals_analysis(income, balance, cashflow),
        lambda: accruals_analysis(_empty, _empty, _empty),
    )
    dupont = _safe(
        "dupont",
        lambda: dupont_decomposition(income, balance),
        lambda: dupont_decomposition(_empty, _empty),
    )
    gpa = _safe(
        "gross_profitability",
        lambda: gross_profitability(income, balance),
        lambda: gross_profitability(_empty, _empty),
    )
    ccc = _safe(
        "cash_conversion_cycle",
        lambda: cash_conversion_cycle(income, balance),
        lambda: cash_conversion_cycle(_empty, _empty),
    )
    governance = _safe(
        "governance",
        lambda: governance_scorecard(profile),
        lambda: governance_scorecard({}),
    )

    wacc = _extract_wacc(val, config)
    roics = _safe(
        "roic_series",
        lambda: roic_series(income, balance, config.market.tax_rate),
        list,
    )
    caq = _safe(
        "capital_allocation",
        lambda: capital_allocation_score(income, balance, cashflow, roics, wacc),
        lambda: capital_allocation_score(_empty, _empty, _empty, [], wacc),
    )

    # Value-driver cross-check (skip for financials — IC undefined for banks)
    value_driver: ValueDriverResult | None = None
    if not is_financial:
        try:
            value_driver = run_value_driver(
                income, balance, profile, wacc,
                config.dcf.terminal_growth_rate, config.market.tax_rate,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Value-driver cross-check failed: %s", exc)

    # --- Blending + conviction + rating ---
    primary_value = val.intrinsic_value
    blended = blend_values(primary_value, secondary_value)

    # Apply India-engine adjustments on top of the blend when available
    final_value = blended
    if val.india_result and val.india_result.blended_value and blended:
        # India engine already starts from the primary intrinsic; rescale its
        # adjustment factor onto the two-model blend.
        if primary_value and primary_value > 0:
            adjustment_factor = val.india_result.blended_value / primary_value
            final_value = blended * adjustment_factor

    current_price = profile.get("current_price")
    upside = None
    if final_value is not None and current_price and current_price > 0:
        upside = final_value / current_price - 1.0

    # Earnings-quality verdict for the confidence rubric
    eq_high: bool | None = None
    if accruals.cfo_ebitda is not None or accruals.cfo_ni_latest is not None:
        eq_high = (
            (accruals.cfo_ebitda is None or accruals.cfo_ebitda >= 0.65)
            and (accruals.cfo_ni_latest is None or accruals.cfo_ni_latest >= 0.8)
        )

    negative_fcff = bool(val.dcf_result and val.dcf_result.base_fcff < 0)
    high_accruals = (
        accruals.accruals_ratio_cf is not None and accruals.accruals_ratio_cf > 0.10
    )

    score, score_components, agree = confidence_score(
        primary_value=primary_value,
        secondary_value=secondary_value,
        clean_data_years=_clean_data_years(income),
        peer_count=len(val.comps_result.peers) if val.comps_result else 0,
        beta_months=beta_res.months if beta_res.source == "regression" else 0,
        has_analyst_consensus=val.broker_target_price is not None,
        earnings_quality_high=eq_high,
        negative_base_fcff=negative_fcff,
        high_accruals=high_accruals,
        beneish_flagged=bool(beneish.flagged),
    )

    # Scenario band: prefer DCF scenarios; otherwise ±15% on the final value
    bear = bull = None
    if val.dcf_result and final_value and primary_value and primary_value > 0:
        scale = final_value / primary_value
        if val.dcf_result.bear_value:
            bear = val.dcf_result.bear_value * scale
        if val.dcf_result.bull_value:
            bull = val.dcf_result.bull_value * scale
    if bear is None and final_value is not None:
        bear = final_value * 0.85
    if bull is None and final_value is not None:
        bull = final_value * 1.15

    conviction = ConvictionResult(
        primary_model=val.model_used,
        primary_value=primary_value,
        secondary_model=secondary_model,
        secondary_value=secondary_value,
        blended_value=blended,
        bear_value=bear,
        bull_value=bull,
        target_price=final_value,
        upside_pct=upside,
        rating=assign_rating(upside),
        confidence_score=score,
        confidence_components=score_components,
        models_agree=agree,
    )

    return ResearchBundle(
        valuation=val,
        conviction=conviction,
        beta=beta_res,
        piotroski=piotroski,
        beneish=beneish,
        altman=altman,
        accruals=accruals,
        dupont=dupont,
        gross_profitability=gpa,
        caq=caq,
        ccc=ccc,
        governance=governance,
        value_driver=value_driver,
    )
