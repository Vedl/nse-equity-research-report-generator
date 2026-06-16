"""Phase 3B-v — cost-of-equity country-risk double-count fix.

The model paired the G-Sec Rf (which embeds India's sovereign default spread) with
the country-loaded Damodaran India ERP, counting country risk twice.  The fix
builds a default-free rupee risk-free (G-Sec − sovereign default spread) and keeps
the full India ERP — country risk once, in the ERP.  One risk-free feeds every
CAPM Ke (financial + FCFF/SOTP WACC).  The financial sanity check now operates on
beta (Rf/ERP-invariant), not a Ke level.
"""

from __future__ import annotations

import pandas as pd
import pytest

from equity_research.analysis.cost_of_capital import blume_adjust, compute_cost_of_capital
from equity_research.analysis.dcf import compute_wacc, size_premium
from equity_research.analysis.financial_sector import _compute_ke
from equity_research.config import load_config

_CFG = load_config()


def _df(data: dict) -> pd.DataFrame:
    return pd.DataFrame(data, index=pd.Index([2024, 2025], name="year")).astype(float)


def test_riskfree_is_default_free_not_raw_gsec():
    m = _CFG.market
    assert m.risk_free_rate == pytest.approx(m.gsec_yield - m.sovereign_default_spread)
    assert m.risk_free_rate < m.gsec_yield                    # de-spread applied
    assert m.risk_free_rate == pytest.approx(0.0464, abs=1e-4)  # 6.8% − 2.16%


def test_beta_one_lands_near_11_6_not_13_8():
    # Financial CAPM Ke at β=1 = default-free Rf + 1·ERP ≈ 11.6%, not the old 13.8%.
    ke = _compute_ke({"beta": 1.0}, _CFG)
    assert ke == pytest.approx(0.1164, abs=2e-3)
    assert ke < 0.125
    assert _compute_ke({"beta": 1.0}, _CFG) != pytest.approx(0.138, abs=1e-3)


def test_financial_beta_band_passes_sbin_real_beta():
    # SBIN's real levered regression β (~1.06–1.11) passes the β band directly —
    # no peer-median swap (the old Ke-level band forced one because the inflated
    # Ke tripped 15%).
    profile = {"market_cap": 1.0e13, "beta": 1.0}
    income = _df({"operating_income": [3.0e11, 3.2e11], "net_income": [2.5e11, 2.7e11]})
    balance = _df({"total_debt": [6.0e12, 6.0e12]})
    coc = compute_cost_of_capital(
        profile, income, balance, _CFG,
        regression_beta=1.11, fallback_beta=1.0,
        peer_beta_de=[(1.0, 0.5), (1.1, 0.5)],   # available, but must NOT be used
        is_financial=True,
    )
    assert coc.beta.beta_used_source == "blume_regression_financial"
    assert coc.beta.beta_used == pytest.approx(blume_adjust(1.11))
    assert _CFG.market.financial_beta_low <= coc.beta.beta_used <= _CFG.market.financial_beta_high


def test_fcff_wacc_uses_the_same_corrected_riskfree():
    # A debt-free FCFF name: WACC == Ke, built from the default-free Rf — and
    # materially (~the default spread) below the old double-counted level.
    profile = {"market_cap": 1.0e12, "beta": 1.0}
    income = _df({"operating_income": [1.0e11, 1.1e11], "interest_expense": [0.0, 0.0]})
    balance = _df({"total_debt": [0.0, 0.0], "cash_and_equivalents": [0.0, 0.0]})
    result = compute_wacc(profile, income, balance, _CFG)
    m = _CFG.market
    ke = m.risk_free_rate + 1.0 * m.equity_risk_premium + size_premium(1.0e12)
    assert result.wacc == pytest.approx(ke, rel=1e-6)
    old_double_counted = m.gsec_yield + 1.0 * m.equity_risk_premium + size_premium(1.0e12)
    assert result.wacc < old_double_counted - 0.02   # ~2.16% lower, model-wide
