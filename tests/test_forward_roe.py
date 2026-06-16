"""Phase 3B-i Commit 2 — forward-ROE normalization.

Where a consensus forward EPS exists, the justified-P/B ROE is normalized to
forward EPS ÷ PROJECTED tangible book; otherwise it falls back to trailing ROTE
and the guardrail stays.  Terminal g is a capped sustainable assumption kept
safely below Ke (never retention × ROE).
"""

from __future__ import annotations

import pandas as pd
import pytest

from equity_research.analysis.financial_sector import run_financial_valuation
from equity_research.analysis.valuation import ValuationResult
from equity_research.analysis.valuation_explain import run_guardrails
from equity_research.config import load_config

_CFG = load_config()
_YEARS = [2023, 2024, 2025]
_LO = _CFG.guardrails.value_to_price_low


def _financials():
    bal = pd.DataFrame(
        {"stockholders_equity": [600, 650, 700], "tangible_book_value": [600, 650, 700]},
        index=_YEARS,
    )
    inc = pd.DataFrame({"net_income": [40, 45, 50]}, index=_YEARS)
    return {"income": inc, "balance_sheet": bal}


def _profile(**over):
    p = {"shares_outstanding": 100.0, "current_price": 10.0, "beta": 1.0,
         "dividend_yield": 0.02, "market_cap": 1000.0, "sector": "Financial Services"}
    p.update(over)
    return p


def _fires_value_flag(r, profile) -> bool:
    vr = ValuationResult(
        model_used="financial", route_reason="", confidence="",
        intrinsic_value=r.intrinsic_value_per_share, current_price=profile["current_price"],
        market_divergence_pct=None, diverges_materially=False, dcf_result=None,
    )
    return any(d.code == "value_vs_price" for d in run_guardrails(vr, profile, _CFG))


def test_forward_roe_uses_projected_tangible_book():
    prof = _profile(forward_eps=1.4)
    r = run_financial_valuation(prof, _financials(), _CFG)
    assert r.roe_basis == "forward_normalized"
    # payout = 0.02×10×100 / 50 = 0.40 → retention 0.60; tangible book/share = 7.
    retention = 0.60
    expected = 1.4 / (7.0 + retention * 1.4)
    assert r.projected_tangible_book_per_share == pytest.approx(7.0 + retention * 1.4)
    assert r.forward_roe == pytest.approx(expected, abs=1e-6)
    assert r.roe == pytest.approx(expected, abs=1e-6)        # forward replaces trailing


def test_terminal_g_is_capped_assumption_not_retention_times_roe():
    prof = _profile(forward_eps=1.4)
    r = run_financial_valuation(prof, _financials(), _CFG)
    assert r.growth_rate < r.cost_of_equity                  # spread floor holds
    assert r.growth_rate == pytest.approx(_CFG.dcf.terminal_growth_rate, abs=1e-9)
    # explicitly NOT retention × ROE (that would be far higher here)
    assert r.growth_rate < 0.60 * r.roe


def test_no_estimate_falls_back_to_trailing_and_flags():
    prof = _profile()  # no forward_eps
    r = run_financial_valuation(prof, _financials(), _CFG)
    assert r.roe_basis == "trailing"
    assert r.roe == pytest.approx(r.trailing_roe)
    # depressed trailing ROTE → intrinsic well below the band → guardrail fires
    assert r.intrinsic_value_per_share / prof["current_price"] < _LO
    assert _fires_value_flag(r, prof)


def test_forward_estimate_lifts_value_and_clears_band():
    prof = _profile(forward_eps=1.4)
    r = run_financial_valuation(prof, _financials(), _CFG)
    ratio = r.intrinsic_value_per_share / prof["current_price"]
    assert ratio >= _LO                                      # cleared the low band
    assert not _fires_value_flag(r, prof)


def test_terminal_g_below_ke_for_both_paths():
    for prof in (_profile(), _profile(forward_eps=1.4)):
        r = run_financial_valuation(prof, _financials(), _CFG)
        assert r.growth_rate < r.cost_of_equity
