"""Sum-of-the-Parts (SOTP) valuation engine for conglomerates.

Reads segment definitions from config.yaml and applies segment-specific
EV/EBITDA multiples to the company's total EBITDA to derive a blended
enterprise value.

    Segment_EV = Total_EBITDA × segment_ebitda_share × segment_ev_ebitda_multiple
    Total_EV   = Σ Segment_EV
    Equity      = Total_EV − Net_Debt
    IV/share    = Equity / Shares

Config location: config.yaml under 'conglomerates:' key.

Public entry point: ``run_sotp(profile, financials, config) -> SOTPResult``
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from equity_research.analysis.ratios import _col, _latest
from equity_research.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class SegmentValue:
    """Valuation of a single business segment."""

    name: str
    ebitda_share: float             # fraction of total EBITDA (e.g. 0.35)
    ev_ebitda_multiple: float       # applied EV/EBITDA multiple
    segment_ebitda: float           # absolute EBITDA allocated
    segment_ev: float               # implied enterprise value
    note: str                       # analyst note from config


@dataclass
class SOTPResult:
    """SOTP valuation output."""

    segments: list[SegmentValue]
    total_ebitda: float
    total_ev: float
    net_debt: float
    equity_value: float
    shares_outstanding: float
    intrinsic_value_per_share: float

    # Blended implied EV/EBITDA for the whole company
    blended_ev_ebitda: float

    # Whether we had to use fallback data
    is_fallback: bool
    fallback_note: str


@dataclass
class ConglomerateSegment:
    """A single segment from config.yaml."""

    name: str
    ebitda_share: float
    ev_ebitda_multiple: float
    note: str = ""


@dataclass
class ConglomerateConfig:
    """Config for a single conglomerate from config.yaml."""

    display_name: str
    segments: list[ConglomerateSegment]
    use_financial_model: bool = False


def parse_conglomerates_config(raw: dict) -> dict[str, ConglomerateConfig]:
    """Parse the 'conglomerates' section from config.yaml.

    Returns:
        Dict mapping ticker base (e.g. 'RELIANCE') to ConglomerateConfig.
    """
    result: dict[str, ConglomerateConfig] = {}
    if not raw:
        return result

    for ticker_base, conf in raw.items():
        if not isinstance(conf, dict):
            continue

        # Check if this should use the financial model instead
        if conf.get("_use_financial_model", False):
            result[ticker_base] = ConglomerateConfig(
                display_name=conf.get("display_name", ticker_base),
                segments=[],
                use_financial_model=True,
            )
            continue

        segments = []
        for seg in conf.get("segments", []):
            segments.append(ConglomerateSegment(
                name=seg["name"],
                ebitda_share=float(seg["ebitda_share"]),
                ev_ebitda_multiple=float(seg["ev_ebitda_multiple"]),
                note=seg.get("note", ""),
            ))

        # Validate segment shares sum to ~1.0
        total_share = sum(s.ebitda_share for s in segments)
        if segments and abs(total_share - 1.0) > 0.05:
            logger.warning(
                "SOTP config for %s: segment shares sum to %.2f (expected ~1.0)",
                ticker_base, total_share,
            )

        result[ticker_base] = ConglomerateConfig(
            display_name=conf.get("display_name", ticker_base),
            segments=segments,
        )

    return result


def run_sotp(
    profile: dict,
    financials: dict[str, pd.DataFrame],
    config: AppConfig,
    conglomerate_conf: ConglomerateConfig,
) -> SOTPResult:
    """Run a Sum-of-the-Parts valuation for a conglomerate.

    Args:
        profile:             Normalized company profile dict.
        financials:          Dict with keys 'income', 'balance_sheet'.
        config:              Loaded AppConfig.
        conglomerate_conf:   ConglomerateConfig from config.yaml.

    Raises:
        ValueError: if EBITDA or shares are unavailable.
    """
    income = financials.get("income", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())

    fallback_note = ""
    is_fallback = False

    # --- Total EBITDA ---
    ebitda = _latest(_col(income, "ebitda"))

    if ebitda is None or ebitda <= 0:
        # Fallback: EBIT + D&A
        ebit = _latest(_col(income, "operating_income"))
        cashflow = financials.get("cash_flow", pd.DataFrame())
        da = _latest(_col(cashflow, "depreciation_amortization"))
        if ebit is not None and da is not None:
            ebitda = ebit + abs(da)
            fallback_note += "EBITDA derived from EBIT + D&A. "
            is_fallback = True
        elif ebit is not None:
            ebitda = ebit * 1.15  # rough 15% D&A assumption
            fallback_note += "EBITDA estimated from EBIT × 1.15. "
            is_fallback = True
        else:
            raise ValueError("EBITDA unavailable for SOTP valuation")

    # --- Net Debt ---
    debt = _latest(_col(balance, "total_debt"))
    cash = _latest(_col(balance, "cash_and_equivalents"))
    net_debt = (debt or 0.0) - (cash or 0.0)

    # --- Shares outstanding (with fallback) ---
    shares = profile.get("shares_outstanding")
    if not shares or shares <= 0:
        mktcap = profile.get("market_cap")
        price = profile.get("current_price")
        if mktcap and price and price > 0:
            shares = mktcap / price
            fallback_note += "Shares derived from market_cap / price. "
            is_fallback = True
        else:
            raise ValueError("shares_outstanding unavailable for SOTP")
    shares = float(shares)

    # --- Compute segment-level valuations ---
    segments: list[SegmentValue] = []
    total_ev = 0.0

    for seg_conf in conglomerate_conf.segments:
        seg_ebitda = ebitda * seg_conf.ebitda_share
        seg_ev = seg_ebitda * seg_conf.ev_ebitda_multiple
        total_ev += seg_ev

        segments.append(SegmentValue(
            name=seg_conf.name,
            ebitda_share=seg_conf.ebitda_share,
            ev_ebitda_multiple=seg_conf.ev_ebitda_multiple,
            segment_ebitda=seg_ebitda,
            segment_ev=seg_ev,
            note=seg_conf.note,
        ))

    # --- Equity value ---
    equity_value = total_ev - net_debt
    iv_per_share = max(0.0, equity_value / shares)

    # Blended EV/EBITDA
    blended = total_ev / ebitda if ebitda > 0 else 0.0

    logger.info(
        "SOTP: total_ebitda=%.2f total_ev=%.2f net_debt=%.2f equity=%.2f "
        "iv/share=%.2f blended_ev_ebitda=%.1fx segments=%d",
        ebitda, total_ev, net_debt, equity_value, iv_per_share,
        blended, len(segments),
    )

    return SOTPResult(
        segments=segments,
        total_ebitda=ebitda,
        total_ev=total_ev,
        net_debt=net_debt,
        equity_value=equity_value,
        shares_outstanding=shares,
        intrinsic_value_per_share=iv_per_share,
        blended_ev_ebitda=blended,
        is_fallback=is_fallback,
        fallback_note=fallback_note,
    )
