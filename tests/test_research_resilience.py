"""Regression tests for BUG 1 — single-company analysis must not 500 the endpoint.

Covers two things:

1. RELIANCE.NS (a conglomerate → SOTP route) assembles a valid research bundle.
2. A malformed yfinance field for one company (e.g. a non-numeric
   ``held_percent_insiders``, which Yahoo can return for Indian listcos)
   degrades gracefully instead of raising — previously this crashed
   ``governance_scorecard`` with a ``TypeError`` and 500'd the whole request.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from equity_research.analysis.governance import governance_scorecard
from equity_research.analysis.pipeline import ResearchBundle, run_research_pipeline
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


class _OfflineProvider:
    """Minimal DataProvider that never touches the network.

    Empty price history forces the sector-median beta fallback; no peers means
    the relative cross-check is empty.  Both are valid, documented states.
    """

    def __init__(self, profile: dict, financials: dict[str, pd.DataFrame]) -> None:
        self._profile = profile
        self._financials = financials

    def get_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        return pd.DataFrame()

    def get_peers(self, ticker: str) -> list[str]:
        return []

    def get_profile(self, ticker: str) -> dict:
        return self._profile

    def get_financials(self, ticker: str) -> dict[str, pd.DataFrame]:
        return self._financials


def _reliance_profile(base: dict) -> dict:
    """Shape a synthetic profile to look like RELIANCE (Energy conglomerate)."""
    p = dict(base)
    p["ticker"] = "RELIANCE.NS"
    p["long_name"] = "Reliance Industries Limited"
    p["sector"] = "Energy"
    p["industry"] = "Oil & Gas Refining & Marketing"
    p["held_percent_insiders"] = 0.50
    p["held_percent_institutions"] = 0.28
    return p


def test_reliance_returns_valid_report_object(
    cfg, synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow
):
    """RELIANCE.NS must assemble a complete, valid research bundle."""
    profile = _reliance_profile(synthetic_profile)
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    provider = _OfflineProvider(profile, financials)

    bundle = run_research_pipeline(profile, financials, provider, cfg)

    assert isinstance(bundle, ResearchBundle)
    # RELIANCE is configured as a conglomerate in config.yaml → Sum-of-the-Parts.
    assert bundle.valuation.model_used == "sotp"
    assert bundle.valuation.sotp_result is not None
    # A clean, finite intrinsic value and a valid rating.
    iv = bundle.valuation.intrinsic_value
    assert iv is not None and math.isfinite(iv) and iv > 0
    assert bundle.conviction.rating in {"BUY", "HOLD", "SELL", "NR"}
    # Every supplementary section is present (degraded or not).
    assert bundle.piotroski is not None
    assert bundle.beneish is not None
    assert bundle.governance is not None
    assert bundle.governance.metrics  # at least the traffic-light rows
    # Earnings-quality / financial-reliability overlay is wired through.
    eq = bundle.earnings_quality
    assert eq is not None
    assert eq.verdict in {"Green", "Amber", "Red", "Unrated"}
    assert len(eq.components) == 3
    # The offline provider returns no peers → sector percentile cleanly absent.
    assert eq.accrual_sector_percentile is None
    # Cost-of-capital decomposition is wired through and internally consistent.
    coc = bundle.cost_of_capital
    assert coc is not None
    assert 0.0 < coc.wacc < 0.5
    assert coc.equity_weight + coc.debt_weight == pytest.approx(1.0)
    # No peers offline → bottom-up unavailable → engine's fallback beta retained.
    assert coc.beta.bottom_up_beta is None
    assert coc.beta.beta_used == pytest.approx(bundle.beta.beta)


def test_pipeline_resilient_to_non_numeric_insider_holding(
    cfg, synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow
):
    """A non-numeric held_percent_insiders must NOT crash the pipeline (BUG 1)."""
    profile = _reliance_profile(synthetic_profile)
    profile["held_percent_insiders"] = "NA"  # the exact live-data value that crashed governance
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    provider = _OfflineProvider(profile, financials)

    # Must not raise — previously raised TypeError at governance.py and 500'd.
    bundle = run_research_pipeline(profile, financials, provider, cfg)
    assert bundle.valuation.model_used == "sotp"


def test_governance_scorecard_handles_non_numeric_and_nan_holdings(synthetic_profile):
    """Governance scorecard coerces bad holding values to N/A instead of raising."""
    p = dict(synthetic_profile)
    p["held_percent_insiders"] = "NA"           # non-numeric string
    p["held_percent_institutions"] = float("nan")  # NaN

    result = governance_scorecard(p)  # must not raise

    promoter = next(m for m in result.metrics if m.name == "Promoter holding")
    institutional = next(
        m for m in result.metrics if m.name.startswith("Institutional holding")
    )
    assert promoter.value == "N/A" and promoter.light == "na"
    assert institutional.value == "N/A" and institutional.light == "na"
