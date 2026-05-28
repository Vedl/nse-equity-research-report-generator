"""Valuation summary: DCF value + comps range → upside/downside vs current price."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from equity_research.analysis.comps import CompsResult
from equity_research.analysis.dcf import DCFResult
from equity_research.utils.formatting import safe_divide

logger = logging.getLogger(__name__)


@dataclass
class ValuationSummary:
    """Consolidated valuation output for the report's valuation section."""

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

    Args:
        current_price: Live market price (INR per share).
        dcf_result:    Output of run_dcf(), or None if DCF was not run.
        comps_result:  Output of compute_comps(), or None if comps were not run.

    Returns:
        ValuationSummary with upside/downside percentages relative to current_price.
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
        "Valuation: price=%.2f  DCF=%.2f (%.1f%%)  comps=[%.2f, %.2f] median=%.2f (%.1f%%)",
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
