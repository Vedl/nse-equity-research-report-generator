"""Financial sector valuation — Justified P/B via ROE Spread.

The correct model for banks, NBFCs, insurance, and financial services:

    Justified P/B = (ROE − g) / (Ke − g)

Where:
    ROE = Return on Tangible Equity (ROTE) — book is tangible common equity
          (total equity − goodwill − intangibles), the correct bank base since
          acquisition goodwill earns no return.  Where a consensus forward EPS
          exists the ROE is normalized to forward EPS ÷ projected tangible book
          (projected = current tangible book + retained forward earnings); else
          it falls back to trailing ROTE and the guardrail stays.
    g   = a capped sustainable terminal assumption, kept safely below Ke (NOT
          retention × ROE, which would push g onto Ke for high-ROE banks).
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
    book_value_per_share: float         # tangible book/share (the base used)
    cost_of_equity: float               # Ke from CAPM
    roe: float                          # ROE used in the multiple (ROTE)
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

    # The ROTE-based justified-P/B value == intrinsic (no dividend-only DDM blend).
    pb_model_value: float | None = None

    # Tangible-book transparency (Phase 3B-i, Commit 1)
    total_book_value_per_share: float | None = None  # pre-tangible (total equity)
    book_basis: str = "total_no_goodwill_data"       # how the book was resolved

    # Forward-ROE normalization (Phase 3B-i, Commit 2)
    roe_basis: str = "trailing"                      # "forward_normalized" | "trailing"
    trailing_roe: float | None = None                # trailing ROTE (fallback level)
    forward_roe: float | None = None                 # fwd EPS / projected tangible book
    forward_eps: float | None = None                 # consensus forward EPS used
    projected_tangible_book_per_share: float | None = None

    # Two-stage residual income (Phase 3B-iii)
    valuation_method: str = "single_stage_pb"        # "two_stage_ri" | "single_stage_pb"
    single_stage_value: float | None = None          # justified-P/B value (for contrast)
    explicit_years: int | None = None
    fade_years: int | None = None
    terminal_rote: float | None = None
    terminal_value_share: float | None = None        # PV(terminal RI) / intrinsic
    implied_exit_ptbv: float | None = None           # terminal equity / terminal book
    implied_ptbv: float | None = None                # intrinsic / tangible book


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


# Minimum spread of Ke over terminal g in the normalized path — keeps the
# (Ke − g) denominator from collapsing (the spread floor required for stability).
_MIN_KE_G_SPREAD = 0.02

# Two-stage residual-income parameters (Phase 3B-iii).  Fixed, documented, uniform
# across all financials — NOT fitted to any name's market price.
_EXPLICIT_YEARS = 5            # high-growth stage at the sourced forward ROTE
_FADE_YEARS = 5               # linear fade of ROTE toward the sustainable terminal
# Fraction of the forward excess ROTE (ROTE − Ke) assumed to persist in the
# terminal — partial mean-reversion of bank excess returns.  Conservative (half).
_EXCESS_ROTE_PERSISTENCE = 0.5


def two_stage_residual_income(
    tangible_bvps: float,
    forward_rote: float,
    cost_of_equity: float,
    retention: float,
    terminal_g: float,
    *,
    explicit_years: int = _EXPLICIT_YEARS,
    fade_years: int = _FADE_YEARS,
) -> dict:
    """Two-stage residual-income value on tangible book (bank P-TBV).

    V0 = B0 + Σ PV[(ROTE_t − Ke)·B_{t-1}] + PV(terminal residual income).

    Explicit stage: ROTE held at the SOURCED forward ROTE; book compounds at
    ``retention × forward ROTE`` (the real retained-earnings book growth).  Fade
    stage: ROTE fades linearly to a terminal ROTE = Ke + persistence×(fwd−Ke);
    book keeps compounding at ``retention × ROTE_t``.  Terminal: a Gordon residual
    income growing at ``terminal_g`` (a capped assumption kept below Ke — NOT
    retention × ROE).  Returns intrinsic, the terminal inputs, and the
    plausibility diagnostics (terminal-value share, implied exit P/TBV).
    """
    ke = cost_of_equity
    terminal_rote = ke + _EXCESS_ROTE_PERSISTENCE * (forward_rote - ke)
    b = tangible_bvps
    pv_ri = 0.0
    for t in range(1, explicit_years + 1):
        pv_ri += (forward_rote - ke) * b / (1.0 + ke) ** t
        b *= 1.0 + retention * forward_rote
    for j in range(1, fade_years + 1):
        rote_t = forward_rote + (terminal_rote - forward_rote) * j / fade_years
        pv_ri += (rote_t - ke) * b / (1.0 + ke) ** (explicit_years + j)
        b *= 1.0 + retention * rote_t

    n = explicit_years + fade_years
    terminal_ri = (terminal_rote - ke) * b          # first terminal-year RI on end book
    tv = terminal_ri / (ke - terminal_g) if ke > terminal_g else 0.0
    pv_tv = tv / (1.0 + ke) ** n
    intrinsic = max(0.0, tangible_bvps + pv_ri + pv_tv)

    tv_share = (pv_tv / intrinsic) if intrinsic > 0 else 0.0
    implied_exit_ptbv = ((b + tv) / b) if b > 0 else 0.0   # terminal equity / terminal book
    return {
        "intrinsic": intrinsic,
        "terminal_rote": terminal_rote,
        "terminal_g": terminal_g,
        "terminal_book_value": b,
        "terminal_value_share": tv_share,
        "implied_exit_ptbv": implied_exit_ptbv,
        "implied_ptbv": (intrinsic / tangible_bvps) if tangible_bvps > 0 else 0.0,
    }


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


def _tangible_equity_series(balance: pd.DataFrame) -> tuple[pd.Series, str]:
    """Tangible common equity per period — the correct base for a bank's P/B
    spread valuation (acquisition goodwill/intangibles earn no return, so
    including them understates ROE and depresses the justified multiple).

    Resolution order, with the basis returned for transparency:
      1. ``tangible_reported``     — Yahoo's reported Tangible Book Value;
      2. ``tangible_derived``      — total equity − goodwill & intangibles;
      3. ``total_no_goodwill_data``— total equity (clean names with no goodwill
         line are then identical to before).
    """
    tbv = _col(balance, "tangible_book_value").dropna()
    if not tbv.empty:
        return tbv, "tangible_reported"
    equity = _col(balance, "stockholders_equity")
    gw = _col(balance, "goodwill_and_intangibles")
    if not equity.dropna().empty and not gw.dropna().empty:
        common = equity.index.intersection(gw.index)
        tang = (equity.loc[common] - gw.loc[common]).dropna() if len(common) else pd.Series(dtype=float)
        if not tang.empty:
            return tang, "tangible_derived"
    return equity.dropna(), "total_no_goodwill_data"


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

    # --- Book value: tangible common equity (ROTE / P-TBV) ---
    tangible_series, book_basis = _tangible_equity_series(balance)
    total_equity_latest = _latest(_col(balance, "stockholders_equity"))
    bv_latest = _latest(tangible_series)

    if bv_latest is None or bv_latest <= 0:
        # Attempt from profile P/B (a total-book proxy — no tangible split here)
        pb = profile.get("price_to_book")
        price = profile.get("current_price")
        if pb and pb > 0 and price and price > 0:
            bv_per_share = price / pb
            bv_latest = bv_per_share * shares
            fallback_note += "Book value derived from price / P/B. "
            is_fallback = True
            book_basis = "price_to_book_fallback"
        else:
            raise ValueError("Book value unavailable for financial valuation")

    bv_per_share = bv_latest / shares
    total_bv_per_share = (
        total_equity_latest / shares
        if total_equity_latest and total_equity_latest > 0
        else bv_per_share
    )

    # --- Trailing ROE on tangible equity (ROTE) — fallback when no estimate ---
    trailing_roe: float | None = None
    ni_series = _col(income, "net_income")

    # Method 1: multi-year average ROTE from statements
    if not tangible_series.empty and not ni_series.empty:
        common = tangible_series.index.intersection(ni_series.index)
        if len(common) >= 2:
            roe_vals = ni_series.loc[common] / tangible_series.loc[common]
            valid_roe = roe_vals.dropna()
            valid_roe = valid_roe[valid_roe.between(-0.5, 0.5)]
            if not valid_roe.empty:
                trailing_roe = float(valid_roe.mean())

    # Method 2: latest year (tangible)
    if trailing_roe is None:
        ni0 = _latest(ni_series)
        if ni0 is not None and bv_latest > 0:
            trailing_roe = ni0 / bv_latest

    # Method 3: profile (Yahoo returnOnEquity — total-equity basis, last resort)
    if trailing_roe is None:
        roe_profile = profile.get("return_on_equity")
        if roe_profile is not None and math.isfinite(roe_profile):
            trailing_roe = float(roe_profile)

    # Method 4: absolute fallback
    if trailing_roe is None or not math.isfinite(trailing_roe):
        trailing_roe = ke + 0.02  # assume marginal value creator
        fallback_note += "ROE unavailable — assumed Ke + 2%. "
        is_fallback = True

    trailing_roe = max(-0.05, min(0.40, trailing_roe))

    # --- Payout & retention (needed for the projected-book forward ROE) ---
    div_yield = profile.get("dividend_yield")
    price = profile.get("current_price")
    ni_latest = _latest(ni_series) if not ni_series.empty else None
    if div_yield and price and price > 0 and ni_latest and ni_latest > 0:
        total_dividends = div_yield * price * shares
        payout_ratio = min(0.90, max(0.0, total_dividends / ni_latest))
    else:
        payout_ratio = 0.30  # banks typically pay ~30%
    retention = 1.0 - payout_ratio

    # --- Normalized forward ROE (Phase 3B-i, Commit 2) ---
    # forward ROE = forward EPS / PROJECTED tangible book, where
    #   projected tangible book = current tangible book/share + retained EPS
    #   retained EPS            = (1 − payout) × forward EPS
    # Projected (not trailing) book so the year's retained earnings don't overstate
    # the ratio.  Replaces the trailing ROTE in the justified P/B where a forward
    # EPS exists; otherwise we fall back to trailing and keep the guardrail —
    # honest degradation, never a fabricated estimate.
    forward_eps = profile.get("forward_eps")
    forward_roe: float | None = None
    projected_tangible_book_ps: float | None = None
    if (
        forward_eps is not None
        and isinstance(forward_eps, (int, float))
        and math.isfinite(forward_eps)
        and forward_eps > 0
        and bv_per_share > 0
    ):
        projected_tangible_book_ps = bv_per_share + retention * float(forward_eps)
        if projected_tangible_book_ps > 0:
            forward_roe = float(forward_eps) / projected_tangible_book_ps

    if forward_roe is not None and math.isfinite(forward_roe):
        roe = max(-0.05, min(0.40, forward_roe))
        roe_basis = "forward_normalized"
    else:
        roe = trailing_roe
        roe_basis = "trailing"

    # --- Terminal growth: a capped sustainable assumption, safely below Ke ---
    # The spread floor is always enforced.  In the normalized path g is a capped,
    # documented terminal assumption (Yahoo carries no LTG) — deliberately NOT
    # retention × ROE, which for high-ROE/high-retention banks pushes g onto Ke
    # and re-explodes the (Ke − g) denominator.  The trailing fallback keeps the
    # retention-implied growth, also capped below Ke.
    if roe_basis == "forward_normalized":
        sustainable_g = min(config.dcf.terminal_growth_rate, config.market.risk_free_rate + 0.02)
        sustainable_g = max(0.0, min(sustainable_g, ke - _MIN_KE_G_SPREAD))
    else:
        sustainable_g = trailing_roe * retention
        sustainable_g = min(sustainable_g, config.market.risk_free_rate + 0.02)
        sustainable_g = min(sustainable_g, ke - 0.005)

    # --- Justified P/B ---
    pb_justified = justified_pb(roe, sustainable_g, ke)
    pb_value = pb_justified * bv_per_share

    # --- Intrinsic value ---
    # Single-stage justified P/B is retention-complete but caps growth at the
    # terminal g (~5%); it cannot represent a franchise compounding tangible book
    # at 12–15% for a high-growth stage.  Where a SOURCED forward ROTE exists we
    # use a two-stage residual-income value (explicit high-growth stage on the
    # forward ROTE, fade to a sustainable terminal); otherwise we keep the
    # single-stage justified-P/B value (honest degradation).  No dividend-only DDM
    # (removed in 3B-ii) — peer P/TBV and consensus are surfaced separately.
    two_stage = None
    if roe_basis == "forward_normalized":
        two_stage = two_stage_residual_income(
            bv_per_share, roe, ke, retention, sustainable_g,
        )
        intrinsic = two_stage["intrinsic"]
        valuation_method = "two_stage_ri"
    else:
        intrinsic = pb_value
        valuation_method = "single_stage_pb"
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
        pb_model_value=pb_value,
        total_book_value_per_share=total_bv_per_share,
        book_basis=book_basis,
        roe_basis=roe_basis,
        trailing_roe=trailing_roe,
        forward_roe=forward_roe,
        forward_eps=(float(forward_eps) if forward_eps else None),
        projected_tangible_book_per_share=projected_tangible_book_ps,
        valuation_method=valuation_method,
        single_stage_value=pb_value,
        explicit_years=(_EXPLICIT_YEARS if two_stage else None),
        fade_years=(_FADE_YEARS if two_stage else None),
        terminal_rote=(two_stage["terminal_rote"] if two_stage else None),
        terminal_value_share=(two_stage["terminal_value_share"] if two_stage else None),
        implied_exit_ptbv=(two_stage["implied_exit_ptbv"] if two_stage else None),
        implied_ptbv=(two_stage["implied_ptbv"] if two_stage else None),
    )
