"""Cost-of-capital decomposition (Phase 2B).

Fully decomposes WACC and exposes *every* input so the report can explain what
drives the discount rate, rather than presenting a single opaque number.

All market-level inputs (India 10Y G-Sec ``risk_free_rate``, India equity risk
premium ``equity_risk_premium``, marginal ``tax_rate``) come from the refreshable
``market`` config block — nothing macro is hard-coded here.

Cost of equity (Ke) — two independent estimates shown side by side:

  1. CAPM with a BOTTOM-UP beta (Damodaran).  Each peer's levered beta is
     unlevered  βu = βl / (1 + (1−t)·D/E),  the unlevered betas are averaged,
     then relevered at the target's own D/E.  Ke = Rf + βl·ERP (+ size premium).
     The raw 2y-weekly regression beta and the Blume-adjusted beta
     (0.67·raw + 0.33) are reported alongside for comparison.
  2. IMPLIED Ke — the discount rate the current price implies.  Gordon inversion
     (Ke = D1/P + g) for dividend payers and a single-stage residual-income
     inversion  r = [ROE + (P/B − 1)·g] / (P/B)  as the general method.  The gap
     versus the CAPM Ke is reported.

Cost of debt (Kd) — both methods, with the one used flagged:
  (a) interest expense / average total debt;
  (b) synthetic Kd = Rf + spread implied by the interest-coverage ratio
      (Damodaran's coverage→spread table).

WACC = (E/V)·Ke + (D/V)·Kd·(1−t), with E = market cap and D = market value of
debt (book value as a documented fallback).  Weights are shown explicitly.

Nothing here is fed into the *quality* overlay and nothing fabricates data: every
sub-estimate degrades to ``None`` when its inputs are missing.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from equity_research.analysis.dcf import size_premium
from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider

logger = logging.getLogger(__name__)

# Nifty 500 (broad) preferred for the raw regression beta; Nifty 50 price index
# is the documented fallback when the broad series is unavailable via yfinance.
NIFTY500 = "^CRSLDX"
NIFTY50 = "^NSEI"
_MIN_WEEKLY_OBS = 60          # ~ 1.2y of weekly returns minimum for a usable slope
_BETA_CLAMP = (0.1, 3.0)
_BETA_DIVERGENCE = 0.35       # max |bottom_up − Blume| before distrusting bottom-up


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_num(v: float | None) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _avg_tail(series: pd.Series, n: int = 3) -> float | None:
    """Mean of the latest ``n`` non-null values (multi-year average)."""
    valid = series.dropna()
    if valid.empty:
        return None
    return float(valid.tail(n).mean())


# ---------------------------------------------------------------------------
# Pure beta math (unit-tested directly)
# ---------------------------------------------------------------------------


def unlever_beta(levered: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada unlever: βu = βl / (1 + (1 − t)·D/E)."""
    return levered / (1.0 + (1.0 - tax_rate) * debt_to_equity)


def relever_beta(unlevered: float, debt_to_equity: float, tax_rate: float) -> float:
    """Hamada relever: βl = βu · (1 + (1 − t)·D/E)."""
    return unlevered * (1.0 + (1.0 - tax_rate) * debt_to_equity)


def blume_adjust(raw: float) -> float:
    """Blume (1971) shrink toward the market: 0.67·raw + 0.33."""
    return 0.67 * raw + 0.33


# Damodaran synthetic-rating table: interest-coverage ratio → default spread
# (large-cap; upper bound exclusive). Spread is added to the risk-free rate.
_COVERAGE_SPREAD: list[tuple[float, float]] = [
    (8.50, 0.0075),   # AAA
    (6.50, 0.0100),   # AA
    (5.50, 0.0125),
    (4.25, 0.0150),   # A
    (3.00, 0.0200),   # BBB
    (2.50, 0.0300),
    (2.00, 0.0400),   # BB
    (1.50, 0.0550),   # B
    (1.25, 0.0650),
    (0.80, 0.0850),   # CCC
    (0.50, 0.1000),
]
_SPREAD_DISTRESS = 0.1400      # coverage < 0.5 (or negative EBIT)


def synthetic_spread(interest_coverage: float | None) -> float:
    """Default spread implied by EBIT interest coverage (Damodaran-style)."""
    if not _is_num(interest_coverage):
        return 0.02            # no coverage signal → investment-grade-ish default
    for floor, spread in _COVERAGE_SPREAD:
        if interest_coverage >= floor:
            return spread
    return _SPREAD_DISTRESS


def gordon_implied_ke(dividend_yield: float | None, growth: float | None) -> float | None:
    """Implied Ke from the Gordon growth model: Ke = D1/P + g = y·(1+g) + g."""
    if not (_is_num(dividend_yield) and _is_num(growth)) or dividend_yield <= 0:
        return None
    return dividend_yield * (1.0 + growth) + growth


def rim_implied_ke(
    price_to_book: float | None, roe: float | None, growth: float | None
) -> float | None:
    """Implied Ke from the single-stage residual-income / justified-P/B identity.

    P/B = 1 + (ROE − r)/(r − g)  ⇒  r = [ROE + (P/B − 1)·g] / (P/B).
    """
    if not (_is_num(price_to_book) and _is_num(roe) and _is_num(growth)):
        return None
    if price_to_book <= 0:
        return None
    return (roe + (price_to_book - 1.0) * growth) / price_to_book


# ---------------------------------------------------------------------------
# Raw regression beta (2y weekly vs Nifty 500) — best-effort IO
# ---------------------------------------------------------------------------


def _weekly_returns(prices: pd.DataFrame) -> pd.Series:
    if prices.empty or "Close" not in prices.columns:
        return pd.Series(dtype=float)
    weekly = prices["Close"].resample("W").last().dropna()
    return weekly.pct_change().dropna()


def weekly_regression_beta(
    provider: DataProvider, ticker: str
) -> tuple[float | None, int, str]:
    """2y-weekly OLS beta vs Nifty 500 (fallback Nifty 50). Returns (beta, n, source)."""
    for bench, label in ((NIFTY500, "Nifty 500 (^CRSLDX)"), (NIFTY50, "Nifty 50 (^NSEI)")):
        try:
            stock = provider.get_prices(ticker, period="2y")
            market = provider.get_prices(bench, period="2y")
            r_i = _weekly_returns(stock)
            r_m = _weekly_returns(market)
            joined = pd.concat(
                [r_i.rename("i"), r_m.rename("m")], axis=1, join="inner"
            ).dropna()
            n = len(joined)
            if n >= _MIN_WEEKLY_OBS:
                var_m = float(joined["m"].var())
                if var_m > 0:
                    beta = float(joined["i"].cov(joined["m"]) / var_m)
                    beta = max(_BETA_CLAMP[0], min(_BETA_CLAMP[1], beta))
                    return beta, n, f"2y-weekly OLS vs {label}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weekly beta vs %s failed for %s: %s", bench, ticker, exc)
    return None, 0, ""


# ===========================================================================
# Structured outputs
# ===========================================================================


@dataclass
class BetaDecomposition:
    raw_regression_beta: float | None   # 2y-weekly vs Nifty 500
    raw_beta_obs: int
    raw_beta_source: str
    blume_beta: float | None            # 0.67·raw + 0.33
    bottom_up_beta: float | None        # peer-unlevered, relevered at target D/E
    avg_unlevered_beta: float | None
    unlevered_peer_betas: list[float]
    target_debt_to_equity: float | None
    peer_count: int
    beta_used: float                    # the beta actually fed into CAPM
    beta_used_source: str               # "bottom_up" / "blume" / "regression" / "fallback"


@dataclass
class CostOfEquity:
    capm_ke: float                      # Rf + β_used·ERP + size premium (canonical)
    capm_ke_bottom_up: float | None     # Rf + bottom_up·ERP + size (side-by-side view)
    risk_free_rate: float
    equity_risk_premium: float
    beta_used: float
    size_premium: float
    implied_ke: float | None            # the PRIMARY implied estimate
    implied_method: str | None          # "gordon" / "residual_income" / None
    implied_gap: float | None           # implied − capm (signed)
    gordon_implied_ke: float | None     # both estimates exposed regardless of primary
    rim_implied_ke: float | None


@dataclass
class CostOfDebt:
    kd_interest_based: float | None     # interest expense / avg total debt
    kd_synthetic: float | None          # Rf + coverage spread
    interest_coverage: float | None
    synthetic_spread: float | None
    kd_pretax_used: float
    kd_aftertax_used: float
    method_used: str                    # "interest_based" / "synthetic" / "fallback"


@dataclass
class CostOfCapital:
    """Full WACC build-up with every input exposed (a risk/explainability artifact)."""

    risk_free_rate: float
    equity_risk_premium: float
    tax_rate: float

    beta: BetaDecomposition
    cost_of_equity: CostOfEquity
    cost_of_debt: CostOfDebt

    equity_value: float                 # market cap (market value of equity)
    debt_value: float                   # market value of debt (book fallback)
    debt_value_is_book: bool
    equity_weight: float
    debt_weight: float

    wacc: float
    warnings: list[str] = field(default_factory=list)


# ===========================================================================
# Bottom-up beta
# ===========================================================================


def bottom_up_beta(
    peer_beta_de: list[tuple[float, float]] | None,
    target_de: float | None,
    tax_rate: float,
) -> tuple[float | None, float | None, list[float]]:
    """Unlever each peer beta, average, relever at the target D/E.

    Args:
        peer_beta_de: list of (levered beta, D/E) per comparable.
        target_de: the target company's own debt-to-equity.
        tax_rate: marginal tax rate.

    Returns ``(relevered_beta, avg_unlevered, [unlevered per peer])``.  The
    relevered beta is ``None`` when there are fewer than two usable peers or the
    target D/E is unavailable.
    """
    if not peer_beta_de or target_de is None or not _is_num(target_de):
        return None, None, []
    unlevered = [
        unlever_beta(bl, de, tax_rate)
        for bl, de in peer_beta_de
        if _is_num(bl) and _is_num(de) and de >= 0
    ]
    if len(unlevered) < 2:
        return None, (unlevered[0] if unlevered else None), unlevered
    avg_u = sum(unlevered) / len(unlevered)
    relevered = relever_beta(avg_u, target_de, tax_rate)
    relevered = max(_BETA_CLAMP[0], min(_BETA_CLAMP[1], relevered))
    return relevered, avg_u, unlevered


# ===========================================================================
# Orchestration
# ===========================================================================


def compute_cost_of_capital(
    profile: dict,
    income: pd.DataFrame,
    balance: pd.DataFrame,
    config: AppConfig,
    *,
    regression_beta: float | None = None,
    regression_beta_obs: int = 0,
    regression_beta_source: str = "",
    fallback_beta: float | None = None,
    peer_beta_de: list[tuple[float, float]] | None = None,
) -> CostOfCapital:
    """Assemble the full WACC decomposition.

    ``regression_beta`` is the raw 2y-weekly estimate (sourced by the pipeline);
    ``fallback_beta`` is the engine's existing beta (e.g. the 5y-monthly /
    sector-median estimate) used when no better estimate is available so the
    discount rate never silently changes for data-poor names.  ``peer_beta_de``
    are (levered beta, D/E) pairs for the bottom-up estimate.
    """
    warnings: list[str] = []
    rf = config.market.risk_free_rate
    erp = config.market.equity_risk_premium
    tax = config.market.tax_rate

    market_cap = profile.get("market_cap")
    market_cap = float(market_cap) if _is_num(market_cap) and market_cap > 0 else None

    # ── Capital structure (book debt, 3y average to smooth point-in-time) ──
    total_debt = _avg_tail(_col(balance, "total_debt"), 3)
    if not _is_num(total_debt):
        pd_debt = profile.get("total_debt")
        total_debt = float(pd_debt) if _is_num(pd_debt) else 0.0
    total_debt = max(0.0, total_debt)

    target_de = (total_debt / market_cap) if (market_cap and market_cap > 0) else None

    # ── Beta decomposition ────────────────────────────────────────────────
    # Damodaran's bottom-up beta is the intended primary, BUT only when it agrees
    # with the target's own regression: a peer set that skews to smaller / more
    # cyclical names can push it far from the firm's actual return behaviour. So
    # bottom-up is canonical only within _BETA_DIVERGENCE of the Blume-adjusted
    # regression beta; otherwise the (reliable, market-shrunk) Blume regression
    # wins and the divergence is flagged.
    raw = regression_beta if _is_num(regression_beta) else None
    blume = blume_adjust(raw) if raw is not None else None
    bu, avg_u, unlevered = bottom_up_beta(peer_beta_de, target_de, tax)

    if bu is not None and blume is not None:
        if abs(bu - blume) <= _BETA_DIVERGENCE:
            beta_used, beta_src = bu, "bottom_up"
        else:
            beta_used, beta_src = blume, "blume_regression"
            warnings.append(
                f"Bottom-up beta {bu:.2f} diverges from regression {blume:.2f} "
                "(peer-set composition) — used Blume-adjusted regression"
            )
    elif bu is not None:
        beta_used, beta_src = bu, "bottom_up"
    elif blume is not None:
        beta_used, beta_src = blume, "blume_regression"
    elif _is_num(fallback_beta):
        # Data-poor name (no regression, no peers): keep the engine's existing
        # beta so the discount rate doesn't silently change.
        beta_used, beta_src = float(fallback_beta), "fallback"
    else:
        beta_used, beta_src = 1.0, "fallback"
        warnings.append("No beta source available — defaulted to 1.0")

    if bu is None and peer_beta_de:
        warnings.append("Bottom-up beta: fewer than two usable peers")

    beta_decomp = BetaDecomposition(
        raw_regression_beta=raw,
        raw_beta_obs=regression_beta_obs,
        raw_beta_source=regression_beta_source,
        blume_beta=blume,
        bottom_up_beta=bu,
        avg_unlevered_beta=avg_u,
        unlevered_peer_betas=unlevered,
        target_debt_to_equity=target_de,
        peer_count=len(peer_beta_de) if peer_beta_de else 0,
        beta_used=beta_used,
        beta_used_source=beta_src,
    )

    # ── Cost of equity: CAPM + implied ────────────────────────────────────
    alpha_size = size_premium(market_cap)
    capm_ke = rf + beta_used * erp + alpha_size
    capm_ke_bottom_up = (rf + bu * erp + alpha_size) if bu is not None else None

    # Sustainable growth for the implied models: g = ROE × retention, bounded
    # below the discount rate and the long-run cap so the inversions stay finite.
    roe = profile.get("return_on_equity")
    roe = float(roe) if _is_num(roe) else None
    div_yield = profile.get("dividend_yield")
    div_yield = float(div_yield) if _is_num(div_yield) else None
    # yfinance is inconsistent: dividend_yield sometimes arrives as a percent
    # number (e.g. 0.46 for 0.46%). No equity yields 15%+, so treat anything
    # above that as percent-as-number and rescale.
    if div_yield is not None and div_yield > 0.15:
        div_yield = div_yield / 100.0
    pb = profile.get("price_to_book")
    pb = float(pb) if _is_num(pb) else None
    g_cap = config.dcf.terminal_growth_rate
    payout = 0.0
    if roe is not None:
        if div_yield and pb and roe > 0:
            # payout = DPS/EPS = (DPS/P)·(P/EPS); EPS/P = ROE/(P/B)  ⇒  payout = y·(P/B)/ROE
            payout = max(0.0, min(1.0, div_yield * pb / roe))
        g_sustain = max(0.0, min(g_cap, roe * (1.0 - payout)))
    else:
        g_sustain = g_cap

    g_imp = gordon_implied_ke(div_yield, g_sustain)
    r_imp = rim_implied_ke(pb, roe, g_sustain)
    # The residual-income inversion is the general primary method — it works for
    # any name and does not understate for low-payout firms the way the Gordon
    # inversion does (Tata Steel / Reliance).  Gordon is used only for genuine,
    # meaningful dividend payers (yield above the configured threshold, with a
    # sane positive payout).
    payer_threshold = config.market.dividend_payer_yield_threshold
    is_dividend_payer = (
        div_yield is not None
        and div_yield >= payer_threshold
        and 0.0 < payout < 1.0
    )
    if is_dividend_payer and g_imp is not None:
        implied_ke, implied_method = g_imp, "gordon"
    elif r_imp is not None:
        implied_ke, implied_method = r_imp, "residual_income"
    elif g_imp is not None:           # last resort if RIM inputs missing
        implied_ke, implied_method = g_imp, "gordon"
    else:
        implied_ke, implied_method = None, None
    # Reject implausible inversions (e.g. P/B≈1 with ROE≈g) rather than emit noise.
    if implied_ke is not None and not (0.02 < implied_ke < 0.40):
        warnings.append(
            f"Implied Ke ({implied_method}) out of plausible range — suppressed"
        )
        implied_ke, implied_method = None, None
    implied_gap = (implied_ke - capm_ke) if implied_ke is not None else None

    cost_of_equity = CostOfEquity(
        capm_ke=capm_ke,
        capm_ke_bottom_up=capm_ke_bottom_up,
        risk_free_rate=rf,
        equity_risk_premium=erp,
        beta_used=beta_used,
        size_premium=alpha_size,
        implied_ke=implied_ke,
        implied_method=implied_method,
        implied_gap=implied_gap,
        gordon_implied_ke=g_imp,
        rim_implied_ke=r_imp,
    )

    # ── Cost of debt: interest-based + synthetic ──────────────────────────
    interest = _latest(_col(income, "interest_expense"))
    interest = abs(interest) if _is_num(interest) else None
    kd_interest: float | None = None
    if interest is not None and total_debt > 0:
        kd_interest = max(0.01, min(0.30, interest / total_debt))

    ebit = _latest(_col(income, "operating_income"))
    coverage = (ebit / interest) if (_is_num(ebit) and interest and interest > 0) else None
    spread = synthetic_spread(coverage)
    kd_synth = rf + spread

    if kd_interest is not None:
        kd_pretax, kd_method = kd_interest, "interest_based"
    elif total_debt > 0:
        kd_pretax, kd_method = kd_synth, "synthetic"
    else:
        # Debt-free: a notional cost of debt that never actually enters WACC
        # (debt weight is zero), shown for completeness.
        kd_pretax, kd_method = kd_synth, "synthetic"
    kd_after = kd_pretax * (1.0 - tax)

    cost_of_debt = CostOfDebt(
        kd_interest_based=kd_interest,
        kd_synthetic=kd_synth,
        interest_coverage=coverage,
        synthetic_spread=spread,
        kd_pretax_used=kd_pretax,
        kd_aftertax_used=kd_after,
        method_used=kd_method,
    )

    # ── Weights + WACC ────────────────────────────────────────────────────
    if market_cap is None:
        warnings.append("Market cap unavailable — WACC weights default to all-equity")
        equity_value = 0.0 if total_debt > 0 else 1.0
    else:
        equity_value = market_cap
    total_capital = equity_value + total_debt
    if total_capital > 0:
        eq_w = equity_value / total_capital
        dbt_w = total_debt / total_capital
    else:
        eq_w, dbt_w = 1.0, 0.0
    wacc = eq_w * capm_ke + dbt_w * kd_after

    return CostOfCapital(
        risk_free_rate=rf,
        equity_risk_premium=erp,
        tax_rate=tax,
        beta=beta_decomp,
        cost_of_equity=cost_of_equity,
        cost_of_debt=cost_of_debt,
        equity_value=equity_value,
        debt_value=total_debt,
        debt_value_is_book=True,
        equity_weight=eq_w,
        debt_weight=dbt_w,
        wacc=wacc,
        warnings=warnings,
    )
