"""Promoter & governance scorecard (India-specific).

Builds a traffic-light scorecard from the shareholding data available through
the automated pipeline. Metrics that require BSE filings scraping (pledge %,
related-party transactions, auditor continuity, board independence) surface as
"N/A — not available via automated pipeline" rather than fabricated values,
per the no-hallucinated-data contract.

yfinance's ``heldPercentInsiders`` is used as the promoter-holding proxy for
Indian listcos — for NSE companies the "insider" bucket maps to the promoter
group in Yahoo's data model. This is documented in the report footnote.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from equity_research.analysis.india_valuation import _PSU_TICKERS

logger = logging.getLogger(__name__)


@dataclass
class GovernanceMetric:
    """One row of the traffic-light scorecard."""

    name: str
    value: str            # display string ("54.2%", "N/A")
    light: str            # "green" / "amber" / "red" / "na"
    note: str


@dataclass
class GovernanceResult:
    """Traffic-light governance scorecard."""

    metrics: list[GovernanceMetric]
    is_psu: bool
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def governance_scorecard(profile: dict) -> GovernanceResult:
    """Score promoter / institutional ownership and structural flags.

    Thresholds (Indian market conventions):
    * Promoter holding: 40–75% green (alignment without float breach);
      25–40% amber; <25% red (weak skin-in-the-game); ≥75% amber
      (SEBI minimum-public-shareholding ceiling).
    * Institutional (FII+DII): >25% green, 10–25% amber, <10% red.
    """
    metrics: list[GovernanceMetric] = []
    flags: list[str] = []
    warnings: list[str] = []

    ticker_base = (profile.get("ticker") or "").replace(".NS", "").upper()
    is_psu = ticker_base in _PSU_TICKERS

    # --- Promoter holding (insider % proxy) ---
    promoter = profile.get("held_percent_insiders")
    if promoter is not None:
        pct = float(promoter) * 100 if promoter <= 1.0 else float(promoter)
        if 40 <= pct < 75:
            light = "green"
            note = "Healthy promoter alignment"
        elif 25 <= pct < 40:
            light = "amber"
            note = "Moderate promoter holding"
        elif pct >= 75:
            light = "amber"
            note = "At/above SEBI 75% ceiling — limited float"
        else:
            light = "red"
            note = "Low promoter skin-in-the-game"
            flags.append(f"Promoter holding only {pct:.1f}% — diffuse ownership")
        metrics.append(GovernanceMetric("Promoter holding", f"{pct:.1f}%", light, note))
    else:
        warnings.append("Promoter holding unavailable from yfinance profile")
        metrics.append(GovernanceMetric("Promoter holding", "N/A", "na",
                                        "Not available via automated pipeline"))

    # --- Institutional holding ---
    inst = profile.get("held_percent_institutions")
    if inst is not None:
        pct = float(inst) * 100 if inst <= 1.0 else float(inst)
        light = "green" if pct > 25 else ("amber" if pct >= 10 else "red")
        note = "Strong institutional sponsorship" if light == "green" else (
            "Moderate institutional interest" if light == "amber" else "Thin institutional coverage")
        metrics.append(GovernanceMetric("Institutional holding (FII + DII)", f"{pct:.1f}%", light, note))
    else:
        metrics.append(GovernanceMetric("Institutional holding (FII + DII)", "N/A", "na",
                                        "Not available via automated pipeline"))

    # --- PSU / state ownership ---
    metrics.append(GovernanceMetric(
        "State ownership (PSU)",
        "Yes" if is_psu else "No",
        "amber" if is_psu else "green",
        "Government-controlled — capital-allocation discount applies" if is_psu
        else "Privately promoted",
    ))
    if is_psu:
        flags.append("PSU: state ownership discount applied in the India valuation engine")

    # --- Metrics requiring BSE filings (honestly N/A) ---
    for name in (
        "Promoter pledge %",
        "Related-party transactions / Revenue",
        "Auditor continuity (2Y)",
        "Board independence",
    ):
        metrics.append(GovernanceMetric(
            name, "N/A", "na", "Requires BSE filings — not available via automated pipeline"))

    return GovernanceResult(metrics=metrics, is_psu=is_psu, flags=flags, warnings=warnings)
