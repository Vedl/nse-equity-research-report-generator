"""Phase 3B-iii — two-stage residual-income bank valuation.

A single-stage justified P/B caps growth at the terminal g and so understates a
bank compounding tangible book at 12–15%.  The two-stage model adds an explicit
high-growth stage GROUNDED in sourced forward estimates (book grows at
retention × forward ROTE), then fades to a sustainable terminal kept below Ke.
Over-aggressive results still trip the plausibility guardrails.
"""

from __future__ import annotations

import pandas as pd
import pytest

from equity_research.analysis.financial_sector import (
    _EXCESS_ROTE_PERSISTENCE,
    run_financial_valuation,
    two_stage_residual_income,
)
from equity_research.analysis.valuation import ValuationResult
from equity_research.analysis.valuation_explain import run_guardrails
from equity_research.config import load_config

_CFG = load_config()
_YEARS = [2023, 2024, 2025]


def _financials(ni=(80, 90, 100), tbv=(600, 650, 700)):
    bal = pd.DataFrame(
        {"stockholders_equity": list(tbv), "tangible_book_value": list(tbv)}, index=_YEARS
    )
    inc = pd.DataFrame({"net_income": list(ni)}, index=_YEARS)
    return {"income": inc, "balance_sheet": bal}


def _profile(**over):
    p = {"shares_outstanding": 100.0, "current_price": 10.0, "beta": 1.0,
         "dividend_yield": 0.02, "market_cap": 1000.0, "sector": "Financial Services"}
    p.update(over)
    return p


# --- two_stage_residual_income unit behaviour ---------------------------------


def test_no_excess_returns_book_value():
    # ROTE == Ke → zero residual income at every stage and a zero terminal excess.
    r = two_stage_residual_income(100.0, 0.10, 0.10, 0.5, 0.05)
    assert r["intrinsic"] == pytest.approx(100.0, abs=1e-6)
    assert r["terminal_rote"] == pytest.approx(0.10)


def test_value_creator_above_book_destroyer_below():
    creator = two_stage_residual_income(100.0, 0.16, 0.10, 0.6, 0.05)["intrinsic"]
    destroyer = two_stage_residual_income(100.0, 0.07, 0.10, 0.6, 0.05)["intrinsic"]
    assert creator > 100.0          # ROTE > Ke creates value
    assert destroyer < 100.0        # ROTE < Ke destroys it


def test_explicit_growth_sourced_from_retention():
    # Retained earnings compound book at retention × forward ROTE, so a higher
    # retention (sourced from payout) lifts a value-creator's intrinsic.
    low = two_stage_residual_income(100.0, 0.16, 0.10, 0.20, 0.05)["intrinsic"]
    high = two_stage_residual_income(100.0, 0.16, 0.10, 0.80, 0.05)["intrinsic"]
    assert high > low


def test_terminal_rote_is_persistence_fade():
    r = two_stage_residual_income(100.0, 0.20, 0.10, 0.5, 0.05)
    assert r["terminal_rote"] == pytest.approx(0.10 + _EXCESS_ROTE_PERSISTENCE * (0.20 - 0.10))


# --- run_financial_valuation integration --------------------------------------


def test_two_stage_used_only_with_forward_eps():
    with_fwd = run_financial_valuation(_profile(forward_eps=1.4), _financials(), _CFG)
    without = run_financial_valuation(_profile(), _financials(), _CFG)
    assert with_fwd.valuation_method == "two_stage_ri"
    assert without.valuation_method == "single_stage_pb"
    assert without.intrinsic_value_per_share == pytest.approx(without.single_stage_value)


def test_terminal_g_below_ke_both_paths():
    for prof in (_profile(), _profile(forward_eps=1.4)):
        r = run_financial_valuation(prof, _financials(), _CFG)
        assert r.growth_rate < r.cost_of_equity


def test_value_destroyer_gets_no_growth_premium():
    # forward ROTE below Ke: residual income is negative at every stage, so the
    # two-stage value must stay BELOW tangible book (P/TBV < 1) — growth at a
    # sub-Ke return destroys value; it never earns a growth premium.
    r = run_financial_valuation(_profile(forward_eps=0.4), _financials(ni=(40, 42, 45)), _CFG)
    assert r.roe_basis == "forward_normalized"
    assert r.forward_roe < r.cost_of_equity
    assert r.implied_ptbv < 1.0


def test_guardrails_fire_on_over_aggressive_two_stage():
    # Tiny book + large forward EPS → an over-aggressive two-stage P/TBV.
    bal = pd.DataFrame(
        {"stockholders_equity": [1.0, 1.0, 1.0], "tangible_book_value": [1.0, 1.0, 1.0]},
        index=_YEARS,
    )
    inc = pd.DataFrame({"net_income": [0.3, 0.4, 0.5]}, index=_YEARS)
    prof = _profile(forward_eps=1.0, dividend_yield=0.0, current_price=1.0)
    r = run_financial_valuation(prof, {"income": inc, "balance_sheet": bal}, _CFG)
    assert r.valuation_method == "two_stage_ri"
    vr = ValuationResult(
        model_used="financial", route_reason="", confidence="",
        intrinsic_value=r.intrinsic_value_per_share, current_price=prof["current_price"],
        market_divergence_pct=None, diverges_materially=False, dcf_result=None,
        financial_result=r,
    )
    codes = {d.code for d in run_guardrails(vr, prof, _CFG)}
    assert codes & {"implied_ptbv", "implied_exit_ptbv", "terminal_value_share"}
