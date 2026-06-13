"""Earnings-quality / financial-reliability module (Phase 2A).

Scores how reliable a company's *reported statements* are, fused into a single
Green / Amber / Red verdict.  This is a **risk overlay** consumed downstream —
it is deliberately NOT fed into the discount rate.

Four pieces, combined into one verdict with per-component scores and a one-line
plain-English reason each:

1. Sloan (1996) accruals — NOA-based balance-sheet and cash-flow accrual ratios.
   Higher accruals  ⇒  earnings are less cash-backed and less persistent.
2. Beneish (1999) M-score — 8-variable manipulation screen (reused from
   :mod:`quality`).  M > -1.78 flags a potential manipulator.
3. Piotroski (2000) F-score — 9-point fundamental-strength score (reused).
4. Industry-relative percentile — the accrual ratio and F-score ranked against
   the company's NSE-sector peers (sourced best-effort by the pipeline).

Every sub-metric degrades to a clean ``None`` when an input line item is
missing.  Nothing here raises on bad/sparse data and nothing is fabricated.

Definitions (Sloan 1996; Penman, *Financial Statement Analysis*):

    Net Operating Assets (NOA)
        = (Total Assets − Cash & ST investments)
          − (Total Liabilities − Total Debt[short+long])
        = Operating Assets − Operating Liabilities

    Balance-sheet accrual ratio = (NOA_t − NOA_{t-1}) / avg(NOA_t, NOA_{t-1})
    Cash-flow accrual ratio     = (NetIncome − CFO − CFI) / avg(NOA_t, NOA_{t-1})
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from equity_research.analysis.quality import (
    BeneishResult,
    PiotroskiResult,
    beneish_m_score,
    piotroski_f_score,
)
from equity_research.analysis.ratios import _col

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flag thresholds (single source of truth, all tunable here)
# ---------------------------------------------------------------------------

# Sloan accrual ratio — signed, higher = lower quality (Sloan 1996 anomaly).
_ACCRUAL_RED = 0.10        # > 10% of NOA accrued → high-accrual red flag
_ACCRUAL_AMBER = 0.05      # 5–10% → watch

# Beneish M-score (Beneish 1999); -1.78 is the published manipulation threshold.
_BENEISH_RED = -1.78       # M > -1.78 → potential manipulator
_BENEISH_AMBER = -2.22     # -2.22 < M ≤ -1.78 → elevated

# Piotroski F-score (0–9).
_FSCORE_GREEN = 7          # ≥ 7 → fundamentally strong
_FSCORE_RED = 3            # ≤ 3 → fundamentally weak

_GREEN, _AMBER, _RED, _NA = "green", "amber", "red", "na"
# Quality points per flag (higher = better) for the combined verdict.
_FLAG_POINTS = {_GREEN: 2.0, _AMBER: 1.0, _RED: 0.0}


# ---------------------------------------------------------------------------
# Small local helpers (mirror the year-indexed DataFrame convention used
# across the analysis package: ascending year index, latest = last row).
# ---------------------------------------------------------------------------


def _is_num(v: float | None) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _yr(series: pd.Series, offset: int = 0) -> float | None:
    """Value at (latest − offset) after dropping NaNs; offset 0 = latest year."""
    valid = series.dropna()
    if len(valid) <= offset:
        return None
    return float(valid.iloc[-(offset + 1)])


# ===========================================================================
# 1 — Sloan accruals (NOA-based)
# ===========================================================================


@dataclass
class SloanAccruals:
    """Sloan (1996) NOA-based accrual ratios; higher ⇒ lower earnings quality."""

    noa_latest: float | None
    noa_prior: float | None
    avg_noa: float | None
    bs_accrual_ratio: float | None     # (NOA_t − NOA_{t-1}) / avg(NOA)
    cf_accrual_ratio: float | None     # (NI − CFO − CFI) / avg(NOA)
    headline_ratio: float | None       # the ratio used for the flag (BS, else CF)
    flag: str                          # green / amber / red / na
    reason: str
    warnings: list[str] = field(default_factory=list)


def _net_operating_assets(balance: pd.DataFrame, offset: int) -> float | None:
    """NOA = (TA − Cash&STI) − (TL − TotalDebt) for the (latest − offset) year.

    ``cash_and_equivalents`` already folds in short-term investments in the
    normalized schema (yfinance "Cash, Cash Equivalents & Short Term
    Investments"), so it is the correct "Cash & ST investments" leg.
    """
    ta = _yr(_col(balance, "total_assets"), offset)
    cash = _yr(_col(balance, "cash_and_equivalents"), offset)
    tl = _yr(_col(balance, "total_liabilities"), offset)
    debt = _yr(_col(balance, "total_debt"), offset)
    if not (_is_num(ta) and _is_num(tl)):
        return None
    # Cash and debt legs default to 0 only when the firm genuinely reports none;
    # but TA and TL are mandatory for a meaningful NOA.
    cash = cash if _is_num(cash) else 0.0
    debt = debt if _is_num(debt) else 0.0
    operating_assets = ta - cash
    operating_liabilities = tl - debt
    return operating_assets - operating_liabilities


def _accrual_flag(ratio: float | None) -> str:
    if not _is_num(ratio):
        return _NA
    if ratio > _ACCRUAL_RED:
        return _RED
    if ratio > _ACCRUAL_AMBER:
        return _AMBER
    return _GREEN


def sloan_accruals(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> SloanAccruals:
    """Compute NOA-based balance-sheet and cash-flow accrual ratios.

    Uses the latest fiscal year plus the prior year for the NOA delta.  Returns
    clean ``None`` sub-metrics (never raises) when inputs are missing.
    """
    warnings: list[str] = []

    noa_t = _net_operating_assets(balance, 0)
    noa_p = _net_operating_assets(balance, 1)

    avg_noa: float | None = None
    if _is_num(noa_t) and _is_num(noa_p):
        avg_noa = (noa_t + noa_p) / 2.0
    elif _is_num(noa_t):
        # Only one year of NOA — scaling by a single-year base is still standard.
        avg_noa = noa_t

    # A non-positive average NOA makes the scaled ratio uninterpretable
    # (sign flips, division blows up) — degrade rather than emit a garbage ratio.
    scalable = _is_num(avg_noa) and avg_noa > 0
    if not scalable:
        warnings.append("NOA base non-positive or unavailable — accrual ratios undefined")

    bs_ratio: float | None = None
    if _is_num(noa_t) and _is_num(noa_p) and scalable:
        bs_ratio = (noa_t - noa_p) / avg_noa  # type: ignore[operator]

    cf_ratio: float | None = None
    ni = _yr(_col(income, "net_income"))
    cfo = _yr(_col(cashflow, "operating_cash_flow"))
    cfi = _yr(_col(cashflow, "investing_cash_flow"))
    if all(_is_num(x) for x in (ni, cfo, cfi)) and scalable:
        cf_ratio = (ni - cfo - cfi) / avg_noa  # type: ignore[operator]
    elif not all(_is_num(x) for x in (ni, cfo, cfi)):
        warnings.append("Cash-flow accrual ratio: NI, CFO or CFI missing")

    # The balance-sheet ratio is Sloan's preferred construct; fall back to the
    # cash-flow ratio when the NOA delta is unavailable.
    headline = bs_ratio if bs_ratio is not None else cf_ratio
    flag = _accrual_flag(headline)

    if flag == _NA:
        reason = "Accruals: insufficient balance-sheet/cash-flow data"
    elif flag == _RED:
        reason = (
            f"High accruals ({headline:+.1%} of NOA) — earnings poorly cash-backed, "
            "lower persistence (Sloan)"
        )
    elif flag == _AMBER:
        reason = f"Moderate accruals ({headline:+.1%} of NOA) — watch earnings backing"
    else:
        reason = f"Low accruals ({headline:+.1%} of NOA) — earnings well cash-backed"

    return SloanAccruals(
        noa_latest=noa_t,
        noa_prior=noa_p,
        avg_noa=avg_noa,
        bs_accrual_ratio=bs_ratio,
        cf_accrual_ratio=cf_ratio,
        headline_ratio=headline,
        flag=flag,
        reason=reason,
        warnings=warnings,
    )


# ===========================================================================
# 2 / 3 — Beneish & Piotroski → flags  (formulas reused from quality.py)
# ===========================================================================


def _beneish_flag(res: BeneishResult) -> str:
    if res.m_score is None or not res.is_reliable:
        return _NA
    if res.m_score > _BENEISH_RED:
        return _RED
    if res.m_score > _BENEISH_AMBER:
        return _AMBER
    return _GREEN


def _beneish_reason(res: BeneishResult, flag: str) -> str:
    if flag == _NA:
        return "Beneish M-score: insufficient two-year data"
    m = res.m_score
    if flag == _RED:
        return f"Beneish M = {m:.2f} (> -1.78) — statements flag possible manipulation"
    if flag == _AMBER:
        return f"Beneish M = {m:.2f} — elevated, short of the -1.78 manipulation line"
    return f"Beneish M = {m:.2f} — no manipulation signal"


def _piotroski_flag(res: PiotroskiResult) -> str:
    # Need a reasonable number of signals to judge; the result's own verdict
    # uses 7 as the reliability bar.
    if res.max_available < 5:
        return _NA
    if res.score >= _FSCORE_GREEN:
        return _GREEN
    if res.score <= _FSCORE_RED:
        return _RED
    return _AMBER


def _piotroski_reason(res: PiotroskiResult, flag: str) -> str:
    if flag == _NA:
        return "Piotroski F-score: too few signals computable"
    s = f"{res.score}/{res.max_available}" if res.max_available < 9 else f"{res.score}/9"
    if flag == _GREEN:
        return f"Piotroski F = {s} — fundamentally strong, accruals-consistent"
    if flag == _RED:
        return f"Piotroski F = {s} — fundamentally weak across profitability/leverage"
    return f"Piotroski F = {s} — mixed fundamental strength"


# ===========================================================================
# 4 — Industry-relative percentile (pure helper)
# ===========================================================================


def sector_percentile(
    value: float | None,
    samples: list[float] | None,
    *,
    higher_is_better: bool,
) -> float | None:
    """Percentile standing of *value* within *samples* (0–100, 100 = best).

    ``higher_is_better=True`` ranks larger values higher (F-score); ``False``
    ranks smaller values higher (accrual ratio — low accruals are better).
    Ties count as "at least as good".  Returns ``None`` if there are fewer than
    three finite peer samples (too thin to rank).
    """
    if not _is_num(value) or not samples:
        return None
    peers = [s for s in samples if _is_num(s)]
    if len(peers) < 3:
        return None
    if higher_is_better:
        n_worse = sum(1 for s in peers if s <= value)
    else:
        n_worse = sum(1 for s in peers if s >= value)
    return 100.0 * n_worse / len(peers)


# ===========================================================================
# Combined verdict
# ===========================================================================


@dataclass
class EQComponent:
    """One screen's contribution to the combined earnings-quality verdict."""

    key: str            # "accruals" / "beneish" / "piotroski"
    name: str           # human label
    flag: str           # green / amber / red / na
    metric: float | None  # the headline number behind the flag
    reason: str         # one-line plain-English explanation


@dataclass
class EarningsQualityResult:
    """Combined financial-reliability assessment (risk overlay, not a rate input)."""

    verdict: str                       # "Green" / "Amber" / "Red" / "Unrated"
    verdict_reason: str
    quality_score: float | None        # 0–100, blend of available components
    components: list[EQComponent]

    accruals: SloanAccruals
    beneish: BeneishResult
    piotroski: PiotroskiResult

    # Industry-relative context (sourced best-effort; null when peers unavailable)
    sector: str | None = None
    peer_sample_size: int = 0
    accrual_sector_percentile: float | None = None
    fscore_sector_percentile: float | None = None

    warnings: list[str] = field(default_factory=list)


def _combine(components: list[EQComponent]) -> tuple[str, str, float | None]:
    """Fuse component flags into a Green/Amber/Red verdict + reason + 0–100 score.

    Rules (transparent and explainable):
      * Quality score = mean of available component points (green 2 / amber 1 /
        red 0), rescaled to 0–100.
      * Red    if two or more components are red, OR Beneish flags manipulation
               while any other screen is non-green.
      * Green  if every available component is green (≥ 2 available).
      * Amber  otherwise (incl. a lone red, or a single Beneish flag).
      * Unrated if no component has enough data.
    """
    available = [c for c in components if c.flag != _NA]
    if not available:
        return "Unrated", "Insufficient data for an earnings-quality verdict", None

    points = sum(_FLAG_POINTS[c.flag] for c in available)
    score = 100.0 * points / (2.0 * len(available))

    reds = [c for c in available if c.flag == _RED]
    n_red = len(reds)
    beneish = next((c for c in available if c.key == "beneish"), None)
    beneish_red = beneish is not None and beneish.flag == _RED
    # A Beneish manipulation flag is the most serious single signal: escalate to
    # Red when it is corroborated by any other non-green screen.
    other_non_green = any(c.flag != _GREEN for c in available if c.key != "beneish")

    if n_red >= 2 or (beneish_red and other_non_green):
        verdict = "Red"
    elif all(c.flag == _GREEN for c in available) and len(available) >= 2:
        verdict = "Green"
    else:
        verdict = "Amber"

    red_names = ", ".join(c.name for c in reds)
    if verdict == "Red":
        reason = f"Multiple reliability red flags ({red_names})" if red_names else "Reliability red flags"
    elif verdict == "Green":
        reason = "All available reliability screens clean"
    else:
        amber_names = ", ".join(c.name for c in available if c.flag != _GREEN)
        reason = f"Mixed signals ({amber_names})" if amber_names else "Mixed reliability signals"

    return verdict, reason, score


def assess_earnings_quality(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame,
    *,
    sector: str | None = None,
    accrual_peer_samples: list[float] | None = None,
    fscore_peer_samples: list[float] | None = None,
) -> EarningsQualityResult:
    """Run all three screens and fuse them into one Green/Amber/Red verdict.

    The three screens are computed from the company's own statements and are
    fully deterministic/unit-testable.  ``*_peer_samples`` are optional
    industry context the pipeline sources best-effort; when absent the
    percentiles are simply ``None`` and the verdict is unaffected.
    """
    warnings: list[str] = []

    accruals = sloan_accruals(income, balance, cashflow)
    beneish = beneish_m_score(income, balance, cashflow)
    piotroski = piotroski_f_score(income, balance, cashflow)

    acc_flag = accruals.flag
    ben_flag = _beneish_flag(beneish)
    pio_flag = _piotroski_flag(piotroski)

    components = [
        EQComponent("accruals", "Sloan accruals", acc_flag, accruals.headline_ratio, accruals.reason),
        EQComponent("beneish", "Beneish M-score", ben_flag, beneish.m_score, _beneish_reason(beneish, ben_flag)),
        EQComponent("piotroski", "Piotroski F-score", pio_flag, float(piotroski.score), _piotroski_reason(piotroski, pio_flag)),
    ]

    verdict, verdict_reason, score = _combine(components)

    warnings.extend(accruals.warnings)
    if not beneish.is_reliable:
        warnings.append("Beneish M-score unreliable (≥3 indices substituted)")

    acc_pct = sector_percentile(
        accruals.headline_ratio, accrual_peer_samples, higher_is_better=False
    )
    f_pct = sector_percentile(
        float(piotroski.score) if piotroski.max_available >= 5 else None,
        fscore_peer_samples,
        higher_is_better=True,
    )
    peer_n = len([s for s in (accrual_peer_samples or []) if _is_num(s)])

    return EarningsQualityResult(
        verdict=verdict,
        verdict_reason=verdict_reason,
        quality_score=score,
        components=components,
        accruals=accruals,
        beneish=beneish,
        piotroski=piotroski,
        sector=sector,
        peer_sample_size=peer_n,
        accrual_sector_percentile=acc_pct,
        fscore_sector_percentile=f_pct,
        warnings=warnings,
    )
