"""Comparable company (comps) analysis.

Fetches trading multiples for sector peers and derives an implied value range
for the target company by applying median peer multiples to the target's own
financial metrics.

Multiples used
--------------
* P/E       — price / trailing EPS  (from yfinance profile)
* EV/EBITDA — enterprise value / EBITDA
* P/B       — price / book value per share
* EV/Sales  — enterprise value / revenue

All multiples come from each peer's ``get_profile()`` result, so only one API
call per peer is required.  Only positive multiples are included in the median;
loss-making or anomalous peers are skipped gracefully.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PeerMultiples:
    """Trading multiples for a single comparable company."""

    ticker: str
    pe: float | None           # P / E  (trailing)
    ev_ebitda: float | None    # EV / EBITDA
    pb: float | None           # Price / Book
    ev_sales: float | None     # EV / Revenue


@dataclass
class CompsResult:
    """Full comparable analysis output."""

    peers: list[PeerMultiples]

    # Median multiples across qualifying peers
    median_pe: float | None
    median_ev_ebitda: float | None
    median_pb: float | None
    median_ev_sales: float | None

    # Implied price per share (median multiple × target metric)
    implied_pe: float | None
    implied_ev_ebitda: float | None
    implied_pb: float | None
    implied_ev_sales: float | None

    # Cross-multiple range
    implied_low: float | None
    implied_high: float | None
    implied_median: float | None


# ---------------------------------------------------------------------------
# Pure math helpers (all independently testable)
# ---------------------------------------------------------------------------


def _pos_median(values: list[float | None]) -> float | None:
    """Median of the strictly-positive, finite values in *values*; None if none qualify."""
    valid = sorted(
        v for v in values
        if v is not None and math.isfinite(v) and v > 0
    )
    if not valid:
        return None
    n = len(valid)
    mid = n // 2
    return valid[mid] if n % 2 else (valid[mid - 1] + valid[mid]) / 2.0


def _implied_range(
    values: list[float | None],
) -> tuple[float | None, float | None, float | None]:
    """Return (low, high, median) of the finite non-None implied prices."""
    finite = [v for v in values if v is not None and math.isfinite(v)]
    if not finite:
        return None, None, None
    return min(finite), max(finite), _pos_median(finite)


def _implied_from_pe(median_pe: float | None, eps: float | None) -> float | None:
    """Implied price = median P/E × EPS.  None if EPS ≤ 0."""
    if median_pe is None or eps is None or eps <= 0:
        return None
    return median_pe * eps


def _implied_from_ev_ebitda(
    median_ev_ebitda: float | None,
    ebitda: float | None,
    net_debt: float | None,
    shares: float | None,
) -> float | None:
    """Implied price = (median EV/EBITDA × EBITDA − net_debt) / shares."""
    if any(v is None for v in [median_ev_ebitda, ebitda, shares]):
        return None
    if ebitda <= 0 or shares <= 0:   # type: ignore[operator]
        return None
    implied_ev = median_ev_ebitda * ebitda   # type: ignore[operator]
    equity = implied_ev - (net_debt or 0.0)
    return equity / shares   # type: ignore[operator]


def _implied_from_pb(
    median_pb: float | None,
    book_per_share: float | None,
) -> float | None:
    """Implied price = median P/B × book value per share."""
    if median_pb is None or book_per_share is None or book_per_share <= 0:
        return None
    return median_pb * book_per_share


def _implied_from_ev_sales(
    median_ev_sales: float | None,
    revenue: float | None,
    net_debt: float | None,
    shares: float | None,
) -> float | None:
    """Implied price = (median EV/Sales × revenue − net_debt) / shares."""
    if any(v is None for v in [median_ev_sales, revenue, shares]):
        return None
    if revenue <= 0 or shares <= 0:   # type: ignore[operator]
        return None
    implied_ev = median_ev_sales * revenue   # type: ignore[operator]
    equity = implied_ev - (net_debt or 0.0)
    return equity / shares   # type: ignore[operator]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_peer_multiples(peer_profile: dict) -> PeerMultiples:
    """Pull trading multiples out of a normalized profile dict."""

    def _pos(val: object) -> float | None:
        if val is None:
            return None
        try:
            f = float(val)   # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return f if (math.isfinite(f) and f > 0) else None

    return PeerMultiples(
        ticker=str(peer_profile.get("ticker", "UNKNOWN")),
        pe=_pos(peer_profile.get("trailing_pe")),
        ev_ebitda=_pos(peer_profile.get("enterprise_to_ebitda")),
        pb=_pos(peer_profile.get("price_to_book")),
        ev_sales=_pos(peer_profile.get("enterprise_to_revenue")),
    )


@dataclass
class _TargetMetrics:
    eps: float | None
    ebitda: float | None
    revenue: float | None
    book_per_share: float | None
    net_debt: float | None
    shares: float | None


def _extract_target_metrics(
    profile: dict,
    financials: dict[str, pd.DataFrame],
) -> _TargetMetrics:
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())

    # EPS: prefer income-statement basic_eps; fall back to trailingEps from profile
    eps_stmt = _latest(_col(income, "basic_eps"))
    eps_profile = profile.get("trailing_eps")
    if eps_profile is not None and not (isinstance(eps_profile, float) and math.isnan(eps_profile)):
        eps_profile = float(eps_profile)
    else:
        eps_profile = None
    # Use whichever is positive and non-None; prefer statement value
    eps: float | None
    if eps_stmt is not None and eps_stmt > 0:
        eps = eps_stmt
    elif eps_profile is not None and eps_profile > 0:
        eps = eps_profile
    else:
        # Last resort: net_income / shares
        ni = _latest(_col(income, "net_income"))
        sh_raw = profile.get("shares_outstanding")
        sh = float(sh_raw) if sh_raw and sh_raw > 0 else None
        eps = (ni / sh) if (ni and sh and ni > 0) else None
        if eps is None:
            logger.warning("EPS unavailable for comps P/E implied value")

    ebitda = _latest(_col(income, "ebitda"))
    revenue = _latest(_col(income, "total_revenue"))
    equity = _latest(_col(balance, "stockholders_equity"))
    debt = _latest(_col(balance, "total_debt"))
    cash = _latest(_col(balance, "cash_and_equivalents"))

    sh_raw = profile.get("shares_outstanding")
    shares: float | None = float(sh_raw) if sh_raw and sh_raw > 0 else None

    net_debt: float | None = None
    if debt is not None:
        net_debt = debt - (cash or 0.0)

    book_per_share: float | None = None
    if equity is not None and equity > 0 and shares:
        book_per_share = equity / shares

    return _TargetMetrics(
        eps=eps,
        ebitda=ebitda,
        revenue=revenue,
        book_per_share=book_per_share,
        net_debt=net_debt,
        shares=shares,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_comps(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    provider: DataProvider,
    config: AppConfig,
) -> CompsResult:
    """Fetch peer multiples and derive implied values for the target company.

    Args:
        profile:    Normalized profile for the target (from DataProvider.get_profile).
        financials: Target's financials dict ('income', 'balance_sheet', 'cash_flow').
        provider:   DataProvider instance (used to fetch peer profiles).
        config:     AppConfig (max_peers, peer overrides).

    Returns:
        CompsResult with per-peer multiples, medians, and implied value range.
    """
    ticker = profile.get("ticker", "UNKNOWN")
    peer_tickers = provider.get_peers(ticker)

    if not peer_tickers:
        logger.warning("No peers found for %s — comps analysis will be empty", ticker)

    peer_multiples: list[PeerMultiples] = []
    for pt in peer_tickers:
        try:
            pp = provider.get_profile(pt)
            pm = _extract_peer_multiples(pp)
            if all(v is None for v in [pm.pe, pm.ev_ebitda, pm.pb, pm.ev_sales]):
                logger.warning("Peer %s: no usable multiples — skipping", pt)
                continue
            peer_multiples.append(pm)
            logger.debug(
                "Peer %s: P/E=%s  EV/EBITDA=%s  P/B=%s  EV/Sales=%s",
                pt, pm.pe, pm.ev_ebitda, pm.pb, pm.ev_sales,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch profile for peer %s: %s", pt, exc)

    # Medians (only positive values contribute)
    median_pe = _pos_median([pm.pe for pm in peer_multiples])
    median_ev_ebitda = _pos_median([pm.ev_ebitda for pm in peer_multiples])
    median_pb = _pos_median([pm.pb for pm in peer_multiples])
    median_ev_sales = _pos_median([pm.ev_sales for pm in peer_multiples])

    # Target metrics
    target = _extract_target_metrics(profile, financials)

    # Implied prices
    impl_pe = _implied_from_pe(median_pe, target.eps)
    impl_ev_ebitda = _implied_from_ev_ebitda(
        median_ev_ebitda, target.ebitda, target.net_debt, target.shares
    )
    impl_pb = _implied_from_pb(median_pb, target.book_per_share)
    impl_ev_sales = _implied_from_ev_sales(
        median_ev_sales, target.revenue, target.net_debt, target.shares
    )

    low, high, med = _implied_range([impl_pe, impl_ev_ebitda, impl_pb, impl_ev_sales])

    logger.info(
        "Comps %s: %d peers  median P/E=%.1f  EV/EBITDA=%.1f  P/B=%.1f  EV/Sales=%.1f  "
        "range [%.2f, %.2f]",
        ticker, len(peer_multiples),
        median_pe or 0, median_ev_ebitda or 0, median_pb or 0, median_ev_sales or 0,
        low or 0, high or 0,
    )

    return CompsResult(
        peers=peer_multiples,
        median_pe=median_pe,
        median_ev_ebitda=median_ev_ebitda,
        median_pb=median_pb,
        median_ev_sales=median_ev_sales,
        implied_pe=impl_pe,
        implied_ev_ebitda=impl_ev_ebitda,
        implied_pb=impl_pb,
        implied_ev_sales=impl_ev_sales,
        implied_low=low,
        implied_high=high,
        implied_median=med,
    )
