"""Model F — EV/GCI + ROIC vs WACC cross-check (McKinsey value-driver framework).

From Koller, Goedhart & Wessels, "Valuation: Measuring and Managing the Value
of Companies" (McKinsey). The key value driver (KVD) formula:

    Value = NOPLAT_1 × (1 − g/ROIC) / (WACC − g)

If ROIC > WACC the company creates value and deserves a premium to invested
capital; if ROIC < WACC it destroys value and should trade at a discount.

Public entry point: ``run_value_driver(income, balance, profile, wacc, g, tax_rate)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from equity_research.analysis.quality import roic_series
from equity_research.analysis.ratios import _col, _latest

logger = logging.getLogger(__name__)


@dataclass
class ValueDriverResult:
    """ROIC-vs-WACC cross-check output for the report."""

    roic_series: list[tuple[int, float]]   # 5-year ROIC trend
    latest_roic: float | None
    wacc: float
    spread: float | None                   # ROIC − WACC
    creates_value: bool | None
    invested_capital: float | None         # latest IC (₹)
    kvd_enterprise_value: float | None     # KVD formula EV (₹)
    kvd_value_per_share: float | None
    warnings: list[str] = field(default_factory=list)


def run_value_driver(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    profile: dict,
    wacc: float,
    growth: float,
    tax_rate: float,
) -> ValueDriverResult:
    """Compute the 5-year ROIC trend and the KVD-formula cross-check value.

    # Koller, Goedhart & Wessels (McKinsey), "Valuation": key value driver formula
    """
    warnings: list[str] = []
    series = roic_series(income, balance, tax_rate)
    latest_roic = series[-1][1] if series else None
    spread = (latest_roic - wacc) if latest_roic is not None else None
    creates_value = (spread > 0) if spread is not None else None

    # Invested capital (latest year): Net PP&E + operating NWC
    ppe = _latest(_col(balance, "net_ppe"))
    ca = _latest(_col(balance, "current_assets"))
    cl = _latest(_col(balance, "current_liabilities"))
    cash = _latest(_col(balance, "cash_and_equivalents"))
    ic: float | None = None
    if ppe is not None:
        ic = ppe + ((ca or 0.0) - (cash or 0.0) - (cl or 0.0))

    # KVD: Value = NOPLAT_1 × (1 − g/ROIC) / (WACC − g)
    kvd_ev: float | None = None
    kvd_per_share: float | None = None
    ebit = _latest(_col(income, "operating_income"))
    if (
        ebit is not None and latest_roic is not None and latest_roic > 0
        and wacc > growth
    ):
        noplat_1 = ebit * (1.0 - tax_rate) * (1.0 + growth)
        kvd_ev = noplat_1 * (1.0 - growth / latest_roic) / (wacc - growth)
        if kvd_ev <= 0:
            warnings.append(
                "KVD value non-positive — growth assumption exceeds what ROIC can fund")
            kvd_ev = None
        else:
            debt = _latest(_col(balance, "total_debt")) or 0.0
            cash_v = cash or 0.0
            shares = profile.get("shares_outstanding")
            if shares and shares > 0:
                kvd_per_share = max(0.0, (kvd_ev - (debt - cash_v)) / float(shares))
    else:
        warnings.append("KVD cross-check unavailable (missing EBIT/ROIC, or WACC ≤ g)")

    return ValueDriverResult(
        roic_series=series,
        latest_roic=latest_roic,
        wacc=wacc,
        spread=spread,
        creates_value=creates_value,
        invested_capital=ic,
        kvd_enterprise_value=kvd_ev,
        kvd_value_per_share=kvd_per_share,
        warnings=warnings,
    )
