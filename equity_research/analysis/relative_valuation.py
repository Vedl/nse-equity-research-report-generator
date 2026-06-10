"""Relative valuation cross-check.

Computes implied prices from peer multiples (P/E, EV/EBITDA, P/B) and
returns a (low, high, median) range.  Used as a triangulation check for
every company regardless of intrinsic model.

This is intentionally thin — it delegates to ``compute_comps()`` and
extracts the implied range.  The benefit of having this as a separate
module is that the orchestrator can call it independently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from equity_research.analysis.comps import CompsResult, compute_comps
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RelativeRange:
    """Implied price range from relative valuation."""

    low: float | None
    high: float | None
    median: float | None

    # Individual implied prices for transparency
    implied_pe: float | None
    implied_ev_ebitda: float | None
    implied_pb: float | None
    implied_ev_sales: float | None


def relative_valuation_range(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    provider: DataProvider,
    config: AppConfig,
) -> tuple[RelativeRange, CompsResult | None]:
    """Compute a relative valuation range from peer multiples.

    Returns:
        (RelativeRange, CompsResult) — the range and the full comps result
        for the frontend peer table.

    Never raises — returns an empty range if comps fail.
    """
    try:
        comps = compute_comps(profile, financials, provider, config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Relative valuation failed: %s", exc)
        return RelativeRange(
            low=None, high=None, median=None,
            implied_pe=None, implied_ev_ebitda=None,
            implied_pb=None, implied_ev_sales=None,
        ), None

    rel = RelativeRange(
        low=comps.implied_low,
        high=comps.implied_high,
        median=comps.implied_median,
        implied_pe=comps.implied_pe,
        implied_ev_ebitda=comps.implied_ev_ebitda,
        implied_pb=comps.implied_pb,
        implied_ev_sales=comps.implied_ev_sales,
    )

    logger.info(
        "Relative range: [%.2f, %.2f] median=%.2f",
        rel.low or 0, rel.high or 0, rel.median or 0,
    )

    return rel, comps
