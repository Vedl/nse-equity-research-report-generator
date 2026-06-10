"""Valuation blending, conviction scoring, and rating assignment.

* Weighted intrinsic value: primary model 60%, secondary model 40%.
* Valuation Confidence Score (0–100) per the project scoring rubric.
* BUY / HOLD / SELL rating from blended upside (sell-side convention:
  BUY ≥ +15%, HOLD −10%…+15%, SELL < −10%).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PRIMARY_WEIGHT = 0.60
SECONDARY_WEIGHT = 0.40

BUY_THRESHOLD = 0.15     # ≥ +15% upside
SELL_THRESHOLD = -0.10   # < −10% downside


@dataclass
class ConfidenceComponent:
    name: str
    points: int          # signed contribution actually applied
    max_points: int      # positive criteria only (penalties have max 0)
    detail: str


@dataclass
class ConvictionResult:
    """Blended value, scenario band, confidence score, and rating."""

    primary_model: str
    primary_value: float | None
    secondary_model: str | None
    secondary_value: float | None
    blended_value: float | None          # 0.6×primary + 0.4×secondary
    bear_value: float | None
    bull_value: float | None
    target_price: float | None           # = blended value (12-month)
    upside_pct: float | None
    rating: str                          # "BUY" / "HOLD" / "SELL" / "NR"
    confidence_score: int                # 0–100
    confidence_components: list[ConfidenceComponent] = field(default_factory=list)
    models_agree: bool | None = None     # within 15%


def blend_values(
    primary_value: float | None,
    secondary_value: float | None,
) -> float | None:
    """Primary 60% / secondary 40% weighted average; degrades to whichever exists."""
    if primary_value is not None and primary_value > 0:
        if secondary_value is not None and secondary_value > 0:
            return PRIMARY_WEIGHT * primary_value + SECONDARY_WEIGHT * secondary_value
        return primary_value
    if secondary_value is not None and secondary_value > 0:
        return secondary_value
    return None


def assign_rating(upside_pct: float | None) -> str:
    """Sell-side rating bands: BUY ≥ +15%, HOLD −10%…+15%, SELL < −10%."""
    if upside_pct is None:
        return "NR"
    if upside_pct >= BUY_THRESHOLD:
        return "BUY"
    if upside_pct < SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


def confidence_score(
    primary_value: float | None,
    secondary_value: float | None,
    clean_data_years: int,
    peer_count: int,
    beta_months: int | None,
    has_analyst_consensus: bool,
    earnings_quality_high: bool | None,
    negative_base_fcff: bool,
    high_accruals: bool | None,
    beneish_flagged: bool | None,
) -> tuple[int, list[ConfidenceComponent], bool | None]:
    """Valuation Confidence Score (0–100) per the project rubric:

    +20 models agree within 15%        +20 five years of clean financials
    +15 peer group ≥ 5                 +15 beta from ≥ 36 months of returns
    +15 analyst consensus available    +15 high earnings quality
    −10 negative base-case FCFF        −10 high accruals
    −20 Beneish flag
    """
    comps: list[ConfidenceComponent] = []

    # Models agree within 15%
    agree: bool | None = None
    if primary_value and secondary_value and primary_value > 0:
        agree = abs(secondary_value - primary_value) / primary_value <= 0.15
        comps.append(ConfidenceComponent(
            "Model agreement (≤15% divergence)", 20 if agree else 0, 20,
            f"primary ₹{primary_value:,.0f} vs secondary ₹{secondary_value:,.0f}"))
    else:
        comps.append(ConfidenceComponent(
            "Model agreement (≤15% divergence)", 0, 20, "secondary model unavailable"))

    comps.append(ConfidenceComponent(
        "5 years of clean financial data", 20 if clean_data_years >= 5 else 0, 20,
        f"{clean_data_years} usable years"))

    comps.append(ConfidenceComponent(
        "Peer group ≥ 5 companies", 15 if peer_count >= 5 else 0, 15,
        f"{peer_count} peers"))

    beta_ok = beta_months is not None and beta_months >= 36
    comps.append(ConfidenceComponent(
        "Beta from ≥ 36 months of returns", 15 if beta_ok else 0, 15,
        f"{beta_months or 0} months" if beta_months is not None else "provider beta (history unknown)"))

    comps.append(ConfidenceComponent(
        "Analyst consensus cross-check", 15 if has_analyst_consensus else 0, 15,
        "consensus target available" if has_analyst_consensus else "no consensus data"))

    comps.append(ConfidenceComponent(
        "High earnings quality", 15 if earnings_quality_high else 0, 15,
        "CFO conversion healthy" if earnings_quality_high else "earnings quality weak or unknown"))

    if negative_base_fcff:
        comps.append(ConfidenceComponent(
            "Penalty: negative base-case FCFF", -10, 0, "base FCFF below zero"))
    if high_accruals:
        comps.append(ConfidenceComponent(
            "Penalty: high accruals", -10, 0, "accruals ratio above threshold (Sloan 1996)"))
    if beneish_flagged:
        comps.append(ConfidenceComponent(
            "Penalty: Beneish M-Score flag", -20, 0, "M-Score above −1.78"))

    score = max(0, min(100, sum(c.points for c in comps)))
    return score, comps, agree
