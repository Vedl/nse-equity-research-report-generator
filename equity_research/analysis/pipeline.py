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
from equity_research.analysis.cost_of_capital import (
    CostOfCapital,
    compute_cost_of_capital,
    weekly_regression_beta,
)
from equity_research.analysis.conviction import (
    ConvictionResult,
    assign_rating,
    blend_values,
    confidence_score,
)
from equity_research.analysis.earnings_quality import (
    EarningsQualityResult,
    assess_earnings_quality,
    sloan_accruals,
)
from equity_research.analysis.governance import GovernanceResult, governance_scorecard
from equity_research.analysis.narrative import (
    Narrative,
    build_narrative_payload,
    generate_narrative,
)
from equity_research.analysis.recommendation import Recommendation, decide_recommendation
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
from equity_research.analysis.router import _is_financial_sector
from equity_research.analysis.valuation_explain import (
    ValuationExplainability,
    explain_valuation,
)
from equity_research.analysis.valuation_scenarios import (
    ValuationScenarios,
    build_scenarios,
)
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
    cost_of_capital: CostOfCapital
    valuation_explainability: ValuationExplainability
    valuation_scenarios: ValuationScenarios
    piotroski: PiotroskiResult
    beneish: BeneishResult
    altman: AltmanResult
    accruals: AccrualsResult
    dupont: DuPontResult
    gross_profitability: GrossProfitabilityResult
    caq: CAQResult
    ccc: CCCResult
    governance: GovernanceResult
    earnings_quality: EarningsQualityResult
    value_driver: ValueDriverResult | None
    recommendation: Recommendation
    narrative: Narrative | None = None


def _sector_quality_samples(
    provider: DataProvider,
    ticker: str,
    *,
    cap: int = 6,
) -> tuple[list[float], list[float]]:
    """Best-effort accrual-ratio and F-score samples across NSE-sector peers.

    Used only to position the company within its sector (percentile context for
    the earnings-quality overlay).  Each peer fetch is isolated and skipped on
    failure; the provider's disk cache keeps this cheap after warmup.  Capped to
    bound per-request latency — a thin sample simply yields ``None`` percentiles.
    """
    accrual_samples: list[float] = []
    fscore_samples: list[float] = []
    try:
        peers = provider.get_peers(ticker) or []
    except Exception as exc:  # noqa: BLE001
        logger.info("Sector quality samples: peer lookup failed (%s)", exc)
        return accrual_samples, fscore_samples

    for pt in peers[:cap]:
        try:
            pf = provider.get_financials(pt)
            inc = pf.get("income", pd.DataFrame())
            bal = pf.get("balance_sheet", pd.DataFrame())
            cf = pf.get("cash_flow", pd.DataFrame())
            acc = sloan_accruals(inc, bal, cf)
            if acc.headline_ratio is not None:
                accrual_samples.append(acc.headline_ratio)
            pio = piotroski_f_score(inc, bal, cf)
            if pio.max_available >= 5:
                fscore_samples.append(float(pio.score))
        except Exception as exc:  # noqa: BLE001
            logger.info("Sector quality sample for %s skipped (%s)", pt, exc)
    return accrual_samples, fscore_samples


def _cost_of_capital_peer_samples(
    provider: DataProvider,
    ticker: str,
    *,
    cap: int = 5,
) -> list[tuple[float, float]]:
    """Best-effort (levered beta, D/E) pairs for the bottom-up beta.

    Each peer's levered beta is estimated by the SAME 2y-weekly regression used
    for the target — yfinance's vendor ``beta`` field is unreliable for Indian
    listings (often understated 3-5×), so it is not used.  D/E is book debt over
    market equity.  Peers whose regression is unavailable are skipped; a thin
    sample simply means the bottom-up beta is unavailable.
    """
    samples: list[tuple[float, float]] = []
    try:
        peers = provider.get_peers(ticker) or []
    except Exception as exc:  # noqa: BLE001
        logger.info("Cost-of-capital peer lookup failed (%s)", exc)
        return samples

    for pt in peers[:cap]:
        try:
            bl, n, _src = weekly_regression_beta(provider, pt)
            if bl is None or n < 1:
                continue
            pp = provider.get_profile(pt)
            mc = pp.get("market_cap")
            debt = pp.get("total_debt")
            if not (isinstance(mc, (int, float)) and float(mc) > 0):
                continue
            de = (
                float(debt) / float(mc)
                if isinstance(debt, (int, float)) and float(debt) > 0
                else 0.0
            )
            samples.append((float(bl), de))
        except Exception as exc:  # noqa: BLE001
            logger.info("Cost-of-capital peer %s skipped (%s)", pt, exc)
    return samples


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
    *,
    with_narrative: bool = False,
) -> ResearchBundle:
    """Run the complete analysis: beta → valuation → quality → conviction.

    ``with_narrative`` gates the deterministic narrative step (a pure function of
    the structured payload — no network, no key, no cost): the API layer enables
    it; most tests leave it off since the recommendation is produced regardless.
    """
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

    # --- Cost-of-capital decomposition (full WACC build-up) ---
    # Computed BEFORE valuation so the bottom-up beta (when peers are available)
    # becomes the single canonical beta the DCF discounts at; for data-poor names
    # with no peers it falls back to the 5y-monthly/sector beta above, leaving the
    # discount rate unchanged.
    raw_beta, raw_obs, raw_src = _safe(
        "weekly_regression_beta",
        lambda: weekly_regression_beta(provider, ticker),
        lambda: (None, 0, ""),
    )
    coc_peers = _safe(
        "cost_of_capital_peers",
        lambda: _cost_of_capital_peer_samples(provider, ticker),
        list,
    )
    coc_is_financial = _is_financial_sector(profile, config.router.financial_keywords)
    cost_of_capital = _safe(
        "cost_of_capital",
        lambda: compute_cost_of_capital(
            profile, income, balance, config,
            regression_beta=raw_beta,
            regression_beta_obs=raw_obs,
            regression_beta_source=raw_src,
            fallback_beta=beta_res.beta,
            peer_beta_de=coc_peers,
            is_financial=coc_is_financial,
        ),
        lambda: compute_cost_of_capital(
            profile, income, balance, config, fallback_beta=beta_res.beta,
            is_financial=coc_is_financial,
        ),
    )
    profile["beta"] = cost_of_capital.beta.beta_used
    logger.info(
        "Beta used for %s: %.2f (%s); WACC=%.4f",
        ticker, cost_of_capital.beta.beta_used,
        cost_of_capital.beta.beta_used_source, cost_of_capital.wacc,
    )

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

    # Earnings-quality / financial-reliability overlay (risk overlay only — NOT
    # fed into the discount rate). Sector samples are best-effort context.
    acc_samples, f_samples = _safe(
        "sector_quality_samples",
        lambda: _sector_quality_samples(provider, ticker),
        lambda: ([], []),
    )
    earnings_quality = _safe(
        "earnings_quality",
        lambda: assess_earnings_quality(
            income, balance, cashflow,
            sector=profile.get("sector"),
            accrual_peer_samples=acc_samples,
            fscore_peer_samples=f_samples,
        ),
        lambda: assess_earnings_quality(_empty, _empty, _empty),
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

    # --- Valuation explainability: rationale + bridge + plausibility guardrails ---
    base_ebitda = _col(income, "ebitda").dropna()
    base_ebitda_val = float(base_ebitda.iloc[-1]) if not base_ebitda.empty else None
    valuation_explainability = _safe(
        "valuation_explainability",
        lambda: explain_valuation(
            profile, val, cost_of_capital, config, base_ebitda=base_ebitda_val
        ),
        lambda: explain_valuation(profile, val, cost_of_capital, config),
    )

    # --- Sensitivity grid + tornado + base/bull/bear scenarios (model-aware) ---
    valuation_scenarios = _safe(
        "valuation_scenarios",
        lambda: build_scenarios(val, profile, config),
        lambda: ValuationScenarios(
            val.model_used, "—", None, [], [], note="scenarios unavailable"
        ),
    )

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

    # --- Guardrail-aware recommendation (deterministic; always computed) ---
    recommendation = _safe(
        "recommendation",
        lambda: decide_recommendation(
            upside_pct=upside,
            quality_verdict=earnings_quality.verdict,
            guardrail_fired=bool(valuation_explainability.diagnostics),
            has_critical=valuation_explainability.has_critical,
        ),
        lambda: decide_recommendation(
            upside_pct=None, quality_verdict="Unrated", guardrail_fired=False
        ),
    )

    # --- Deterministic narrative ("the why") — pure function of the payload ---
    # No external API, no key, no cost: composed entirely from the structured
    # numbers above (router rationale, bridge, tornado, sensitivity grid, WACC
    # build-up, earnings quality, guardrails, recommendation).
    narrative: Narrative | None = None
    if with_narrative:
        vs = valuation_scenarios
        sensitivity_payload = None
        if vs is not None and vs.sensitivity is not None:
            sg = vs.sensitivity
            sensitivity_payload = {
                "row_driver": sg.row_driver,
                "col_driver": sg.col_driver,
                "row_values": list(sg.row_values),
                "col_values": list(sg.col_values),
                "values": [list(r) for r in sg.values],
                "base_row": sg.base_row,
                "base_col": sg.base_col,
            }
        tornado_payload = [
            {"driver": t.driver, "low_input": t.low_input, "high_input": t.high_input,
             "low_value": t.low_value, "high_value": t.high_value,
             "base_value": t.base_value, "swing": t.swing}
            for t in (vs.tornado if vs is not None else [])
        ]
        narrative = _safe(
            "narrative",
            lambda: generate_narrative(build_narrative_payload(
                company={
                    "name": profile.get("long_name"),
                    "ticker": profile.get("ticker"),
                    "sector": profile.get("sector"),
                },
                recommendation=recommendation,
                quality_verdict=earnings_quality.verdict,
                quality_components=[
                    {"name": c.name, "flag": c.flag, "reason": c.reason}
                    for c in earnings_quality.components
                ],
                valuation_rationale=valuation_explainability.rationale.headline,
                bridge=[
                    {"label": s.label, "value": s.value}
                    for s in (valuation_explainability.bridge.steps
                              if valuation_explainability.bridge else [])
                ],
                wacc_build_up={
                    "wacc": cost_of_capital.wacc,
                    "cost_of_equity": cost_of_capital.cost_of_equity.capm_ke,
                    "beta_used": cost_of_capital.beta.beta_used,
                    "risk_free_rate": cost_of_capital.risk_free_rate,
                    "equity_risk_premium": cost_of_capital.equity_risk_premium,
                },
                guardrail_flags=[
                    {"code": d.code, "severity": d.severity, "message": d.message}
                    for d in valuation_explainability.diagnostics
                ],
                intrinsic_value=val.intrinsic_value,
                current_price=profile.get("current_price"),
                model=valuation_explainability.rationale.model,
                model_label=valuation_explainability.rationale.model_label,
                tornado=tornado_payload,
                sensitivity=sensitivity_payload,
                discount_driver=(vs.discount_driver if vs is not None else None),
                scenarios_note=(vs.note if vs is not None else None),
            )),
            lambda: None,
        )

    return ResearchBundle(
        valuation=val,
        conviction=conviction,
        beta=beta_res,
        cost_of_capital=cost_of_capital,
        valuation_explainability=valuation_explainability,
        valuation_scenarios=valuation_scenarios,
        piotroski=piotroski,
        beneish=beneish,
        altman=altman,
        accruals=accruals,
        dupont=dupont,
        gross_profitability=gpa,
        caq=caq,
        ccc=ccc,
        governance=governance,
        earnings_quality=earnings_quality,
        value_driver=value_driver,
        recommendation=recommendation,
        narrative=narrative,
    )
