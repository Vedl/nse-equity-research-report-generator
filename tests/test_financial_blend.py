"""Phase 3B-ii — the bank intrinsic IS the ROTE-based justified-P/B value.

There is no dividend-only DDM in the blend: (ROE − g)/(Ke − g) is already
retention-complete (it prices both paid-out dividends and retained-earnings value
through g), so a dividend-only H-model would be a downward-biased SUBSET, not an
independent cross-check.  Genuine cross-checks (peer P/TBV via the conviction
blend, analyst consensus) are surfaced separately, never folded into this number.
"""

from __future__ import annotations

import pandas as pd
import pytest

from equity_research.analysis.financial_sector import run_financial_valuation
from equity_research.config import load_config

_CFG = load_config()
_YEARS = [2023, 2024, 2025]


def _financials():
    bal = pd.DataFrame(
        {"stockholders_equity": [600, 650, 700], "tangible_book_value": [600, 650, 700]},
        index=_YEARS,
    )
    inc = pd.DataFrame({"net_income": [80, 90, 100]}, index=_YEARS)
    return {"income": inc, "balance_sheet": bal}


def _profile(**over):
    p = {"shares_outstanding": 100.0, "current_price": 10.0, "beta": 1.0,
         "dividend_yield": 0.02, "market_cap": 1000.0, "sector": "Financial Services"}
    p.update(over)
    return p


def test_intrinsic_is_the_justified_pb_value_trailing():
    r = run_financial_valuation(_profile(), _financials(), _CFG)
    assert r.roe_basis == "trailing"
    assert r.intrinsic_value_per_share == pytest.approx(r.pb_model_value)
    assert r.pb_model_value == pytest.approx(r.justified_pb * r.book_value_per_share)


def test_forward_path_two_stage_has_no_ddm_drag():
    # The forward path uses the two-stage RI value (Phase 3B-iii). It still carries
    # no dividend-only DDM: a value-creator is never dragged BELOW its single-stage
    # justified-P/B value (the old DDM blend used to pull it down).
    r = run_financial_valuation(_profile(forward_eps=1.6), _financials(), _CFG)
    assert r.roe_basis == "forward_normalized"
    assert r.valuation_method == "two_stage_ri"
    assert r.single_stage_value == pytest.approx(r.justified_pb * r.book_value_per_share)
    assert r.intrinsic_value_per_share >= r.single_stage_value      # uplift, no DDM drag


def test_high_dividend_is_not_dragged_below_the_justified_pb():
    # A high payout used to pull intrinsic toward a low dividend-only DDM value.
    # Now the dividend yield does not drag intrinsic below the justified-P/B value.
    r = run_financial_valuation(_profile(dividend_yield=0.07), _financials(), _CFG)
    assert r.intrinsic_value_per_share == pytest.approx(r.pb_model_value)
    assert r.intrinsic_value_per_share >= r.justified_pb * r.book_value_per_share - 1e-6


def test_no_ddm_attributes_on_result():
    r = run_financial_valuation(_profile(), _financials(), _CFG)
    for attr in ("ddm_value_per_share", "ddm_weight", "ddm_dps0", "ddm_g_short"):
        assert not hasattr(r, attr), f"{attr} should be gone after Phase 3B-ii"
