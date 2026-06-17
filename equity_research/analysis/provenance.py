"""Data-provenance block — Phase 3D Part 2.

Every research response carries a ``provenance`` section that honestly reports:
  - how many fiscal years of fundamental data are available and which range;
  - whether forward estimates (EPS, analyst count) are present;
  - news headline count and retrieval timestamp;
  - explicit disclosures for any window shortfall (e.g. a 3y-CAGR label when
    only 2 years are available).

The provenance block is *pure metadata* — it never alters intrinsic values,
WACC, Ke, or the directional call.  It is computed from data already fetched
inside ``_build_research``; no additional network calls are made.
"""

from __future__ import annotations

import pandas as pd


def build_provenance(
    *,
    ticker: str,
    income: "pd.DataFrame",
    balance: "pd.DataFrame",
    cashflow: "pd.DataFrame",
    profile: dict,
    news_result: object | None = None,
) -> dict:
    """Assemble the data-provenance block for one ticker.

    Args:
        ticker:      NSE ticker (e.g. ``HDFCBANK.NS``).
        income:      Annual income-statement DataFrame (integer FY as index).
        balance:     Annual balance-sheet DataFrame.
        cashflow:    Annual cash-flow DataFrame.
        profile:     Company profile dict from the data provider.
        news_result: ``NewsSentimentResult`` or None.

    Returns:
        A dict with keys ``fundamentals``, ``forward_estimates``, ``news``,
        and ``disclosures``.  All values are JSON-serialisable.
    """
    # ── Fundamental depth ────────────────────────────────────────────────────
    n_fy = len(income) if income is not None and not income.empty else 0
    fy_years: list[int] = sorted([int(y) for y in income.index.tolist()]) if n_fy > 0 else []

    if n_fy >= 2:
        fy_range = f"FY{fy_years[0] % 100:02d}–FY{fy_years[-1] % 100:02d}"
    elif n_fy == 1:
        fy_range = f"FY{fy_years[0] % 100:02d}"
    else:
        fy_range = "n/a"

    as_of_fy = fy_years[-1] if fy_years else None

    # Intended vs actual CAGR window
    intended_cagr_years = 3
    actual_cagr_years = max(0, n_fy - 1)  # CAGR needs at least 2 data points

    # ── Forward estimates ────────────────────────────────────────────────────
    forward_eps = profile.get("forward_eps")
    analyst_count = profile.get("numberOfAnalystOpinions") or profile.get("analyst_count")

    # ── News ─────────────────────────────────────────────────────────────────
    news_count = 0
    news_sourced_at = None
    if news_result is not None:
        headlines = getattr(news_result, "headlines", [])
        news_count = len(headlines)
        news_sourced_at = getattr(news_result, "sourced_at", None) or None

    # ── Disclosures (honest window shortfall warnings) ────────────────────────
    disclosures: list[str] = []

    if n_fy == 0:
        disclosures.append(
            "No fundamental data available — all ratio and valuation "
            "computations use fallback or analyst estimates only."
        )
    elif n_fy < 3:
        disclosures.append(
            f"Only {n_fy} FY of fundamentals available (range: {fy_range}). "
            f"Revenue/EPS CAGR labels say '{intended_cagr_years}y' but the actual "
            f"window is {actual_cagr_years}y. Interpret trend metrics with caution."
        )
    elif n_fy < 5:
        disclosures.append(
            f"Fundamentals cover {n_fy} FY ({fy_range}). Any 5y-average "
            f"computations (e.g. trailing ROE) use the available {n_fy}y window."
        )

    if forward_eps is None:
        disclosures.append(
            "No analyst forward EPS available — bank valuation uses trailing ROE "
            "normalisation rather than the two-stage forward-ROE path."
        )

    return {
        "fundamentals": {
            "source": "yfinance (NSE/BSE filings via Yahoo Finance)",
            "fiscal_years_available": n_fy,
            "fy_range": fy_range,
            "as_of_fy": as_of_fy,
            "actual_cagr_window_years": actual_cagr_years,
            "intended_cagr_window_years": intended_cagr_years,
        },
        "forward_estimates": {
            "source": "yfinance analyst consensus",
            "forward_eps_available": forward_eps is not None,
            "analyst_count": int(analyst_count) if analyst_count is not None else None,
        },
        "news": {
            "source": "Google News RSS",
            "headline_count": news_count,
            "sourced_at": news_sourced_at,
        },
        "disclosures": disclosures,
    }
