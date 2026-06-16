"""Phase 2B — cost-of-capital decomposition tests.

The unlever/relever math, Blume adjustment, Damodaran coverage→spread table,
and the implied-Ke inversions are checked against hand-computed values.  The
WACC orchestration is checked for the two sanity properties the protocol calls
out: a near debt-free name collapses WACC ≈ Ke, and a levered name lands WACC < Ke.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from equity_research.analysis.cost_of_capital import (
    blume_adjust,
    bottom_up_beta,
    compute_cost_of_capital,
    gordon_implied_ke,
    relever_beta,
    rim_implied_ke,
    synthetic_spread,
    unlever_beta,
)
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent
_YEARS = pd.Index([2023, 2024], name="year")


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def _df(cols: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(cols, index=_YEARS)


# ===========================================================================
# Pure beta math
# ===========================================================================


def test_unlever_relever_roundtrip():
    bl, de, t = 1.2, 0.5, 0.25
    bu = unlever_beta(bl, de, t)
    # βu = 1.2 / (1 + 0.75·0.5) = 1.2 / 1.375
    assert bu == pytest.approx(1.2 / 1.375)
    # relever back recovers the levered beta exactly
    assert relever_beta(bu, de, t) == pytest.approx(bl)


def test_blume_adjust():
    # 0.67·1.2 + 0.33 = 1.134
    assert blume_adjust(1.2) == pytest.approx(1.134)
    # market beta is a fixed point
    assert blume_adjust(1.0) == pytest.approx(1.0)


def test_bottom_up_beta_handcomputed():
    peers = [(1.2, 0.5), (0.9, 0.0), (1.5, 1.0)]
    t = 0.25
    relevered, avg_u, unlevered = bottom_up_beta(peers, target_de=0.2, tax_rate=t)
    # unlevered: 1.2/1.375, 0.9/1.0, 1.5/1.75
    assert unlevered == pytest.approx([1.2 / 1.375, 0.9, 1.5 / 1.75])
    exp_avg = (1.2 / 1.375 + 0.9 + 1.5 / 1.75) / 3
    assert avg_u == pytest.approx(exp_avg)
    # relever at target D/E 0.2: avg · (1 + 0.75·0.2)
    assert relevered == pytest.approx(exp_avg * 1.15)


def test_bottom_up_beta_needs_two_peers():
    rel, _avg, _u = bottom_up_beta([(1.2, 0.5)], target_de=0.2, tax_rate=0.25)
    assert rel is None
    rel2, _a, _u2 = bottom_up_beta(None, target_de=0.2, tax_rate=0.25)
    assert rel2 is None
    # missing target D/E → unavailable
    rel3, _a3, _u3 = bottom_up_beta([(1.2, 0.5), (0.9, 0.1)], target_de=None, tax_rate=0.25)
    assert rel3 is None


# ===========================================================================
# Synthetic cost of debt (Damodaran coverage → spread)
# ===========================================================================


def test_synthetic_spread_table():
    assert synthetic_spread(10.0) == pytest.approx(0.0075)   # AAA
    assert synthetic_spread(5.0) == pytest.approx(0.0150)    # 5 ≥ 4.25 (A)
    assert synthetic_spread(3.5) == pytest.approx(0.0200)    # 3.5 ≥ 3.0 (BBB)
    assert synthetic_spread(1.0) == pytest.approx(0.0850)    # 1.0 ≥ 0.80 (CCC)
    assert synthetic_spread(0.3) == pytest.approx(0.1400)    # distress
    assert synthetic_spread(None) == pytest.approx(0.02)     # no signal default


# ===========================================================================
# Implied cost of equity
# ===========================================================================


def test_gordon_implied_ke():
    # y=2%, g=5% → 0.02·1.05 + 0.05 = 0.071
    assert gordon_implied_ke(0.02, 0.05) == pytest.approx(0.071)
    assert gordon_implied_ke(0.0, 0.05) is None
    assert gordon_implied_ke(None, 0.05) is None


def test_rim_implied_ke():
    # r = [ROE + (P/B − 1)·g] / (P/B) = (0.30 + 2·0.05)/3 = 0.40/3
    assert rim_implied_ke(3.0, 0.30, 0.05) == pytest.approx(0.40 / 3.0)
    assert rim_implied_ke(0.0, 0.30, 0.05) is None
    assert rim_implied_ke(3.0, None, 0.05) is None


# ===========================================================================
# WACC orchestration — sanity properties
# ===========================================================================


def _profile(market_cap: float, **extra) -> dict:
    p = {"market_cap": market_cap}
    p.update(extra)
    return p


def test_debt_free_wacc_collapses_to_ke(cfg):
    """Near debt-free (TCS-like): WACC must collapse to essentially equal Ke."""
    profile = _profile(1.0e13)  # mega-cap, no debt
    income = _df({"interest_expense": [0.0, 0.0], "operating_income": [1.0e12, 1.1e12],
                  "net_income": [9.0e11, 1.0e12]})
    balance = _df({"total_debt": [0.0, 0.0], "total_assets": [5.0e12, 5.5e12],
                   "total_liabilities": [1.0e12, 1.0e12]})
    coc = compute_cost_of_capital(profile, income, balance, cfg, fallback_beta=1.0)
    assert coc.debt_weight == pytest.approx(0.0)
    assert coc.wacc == pytest.approx(coc.cost_of_equity.capm_ke)
    # Ke = default-free Rf + β·ERP + size premium = 0.0464 + 1.0·0.07 + 0.005 ≈ 0.121
    assert 0.10 < coc.cost_of_equity.capm_ke < 0.14
    assert coc.cost_of_equity.capm_ke == pytest.approx(
        cfg.market.risk_free_rate + cfg.market.equity_risk_premium + 0.005
    )


def test_levered_wacc_below_ke(cfg):
    """A levered name: after-tax debt drags WACC below Ke."""
    profile = _profile(1.0e12)
    income = _df({"interest_expense": [3.0e10, 3.0e10], "operating_income": [2.0e11, 2.0e11],
                  "net_income": [1.5e11, 1.5e11]})
    balance = _df({"total_debt": [5.0e11, 5.0e11], "total_assets": [2.0e12, 2.0e12],
                   "total_liabilities": [8.0e11, 8.0e11]})
    coc = compute_cost_of_capital(profile, income, balance, cfg, fallback_beta=1.0)
    assert coc.debt_weight > 0.2
    # Kd interest-based = 3e10 / 5e11 = 6%
    assert coc.cost_of_debt.kd_interest_based == pytest.approx(0.06)
    assert coc.cost_of_debt.method_used == "interest_based"
    assert coc.wacc < coc.cost_of_equity.capm_ke


def test_bottom_up_used_when_it_agrees_with_regression(cfg):
    """Bottom-up is canonical when within the divergence band of Blume regression."""
    profile = _profile(1.0e12)
    income = _df({"interest_expense": [1.0e10, 1.0e10], "operating_income": [2.0e11, 2.0e11]})
    balance = _df({"total_debt": [2.0e11, 2.0e11]})  # D/E = 0.2
    # bottom-up ≈ 1.01, Blume(1.4)=1.268 → |diff| 0.26 ≤ 0.35 → bottom-up wins.
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=1.4, regression_beta_obs=100, regression_beta_source="2y-weekly",
        fallback_beta=1.0,
        peer_beta_de=[(1.2, 0.5), (0.9, 0.0), (1.5, 1.0)],
    )
    assert coc.beta.bottom_up_beta is not None
    assert coc.beta.beta_used_source == "bottom_up"
    assert coc.beta.beta_used == pytest.approx(coc.beta.bottom_up_beta)
    # raw + Blume still reported for comparison
    assert coc.beta.raw_regression_beta == pytest.approx(1.4)
    assert coc.beta.blume_beta == pytest.approx(0.67 * 1.4 + 0.33)
    # CAPM-with-bottom-up is exposed side-by-side
    assert coc.cost_of_equity.capm_ke_bottom_up is not None


def test_divergent_bottom_up_falls_back_to_blume_regression(cfg):
    """A noisy peer set (bottom-up far from regression) must not hijack the rate."""
    profile = _profile(1.0e12)
    income = _df({"interest_expense": [1.0e10, 1.0e10], "operating_income": [2.0e11, 2.0e11]})
    balance = _df({"total_debt": [1.0e10, 1.0e10]})  # ~ debt-free → relever ≈ unlever
    # peers all ~0.2 (the Yahoo-beta pathology) vs Blume(1.4)=1.268 → diverges → Blume.
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=1.4, fallback_beta=1.0,
        peer_beta_de=[(0.2, 0.0), (0.2, 0.0), (0.2, 0.0)],
    )
    assert coc.beta.bottom_up_beta is not None  # still computed + reported
    assert coc.beta.beta_used_source == "blume_regression"
    assert coc.beta.beta_used == pytest.approx(coc.beta.blume_beta)
    assert any("diverges" in w for w in coc.warnings)


def test_no_peers_uses_blume_regression(cfg):
    """No peers but a regression present → Blume-adjusted regression is canonical."""
    profile = _profile(1.0e12)
    income = _df({"interest_expense": [1.0e10, 1.0e10], "operating_income": [2.0e11, 2.0e11]})
    balance = _df({"total_debt": [2.0e11, 2.0e11]})
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=0.7, fallback_beta=0.85, peer_beta_de=None,
    )
    assert coc.beta.beta_used == pytest.approx(blume_adjust(0.7))
    assert coc.beta.beta_used_source == "blume_regression"


def test_financial_skips_unlever_and_uses_blume(cfg):
    """Banks must NOT unlever/relever; canonical = Blume levered regression, Ke in band."""
    profile = _profile(1.0e13)  # large-cap bank
    income = _df({"interest_expense": [1.0e10, 1.0e10], "operating_income": [3.0e11, 3.0e11]})
    balance = _df({"total_debt": [6.0e12, 6.0e12]})  # huge bank "debt" (deposits/borrowings)
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=1.0, fallback_beta=1.0,
        peer_beta_de=[(1.5, 0.6), (1.5, 0.6)],   # would relever high on the corporate path
        is_financial=True,
    )
    # No bottom-up: the unlever/relever path is bypassed entirely.
    assert coc.beta.bottom_up_beta is None
    assert coc.beta.beta_used_source == "blume_regression_financial"
    assert coc.beta.beta_used == pytest.approx(blume_adjust(1.0))   # = 1.0
    # The levered-regression β lands inside the β sanity band (Rf/ERP-invariant).
    assert cfg.market.financial_beta_low <= coc.beta.beta_used <= cfg.market.financial_beta_high


def test_financial_beta_band_clamp(cfg):
    """A too-high bank beta is clamped to the β-band edge and flagged."""
    profile = _profile(1.0e13)
    income = _df({"operating_income": [3.0e11, 3.0e11]})
    balance = _df({"total_debt": [6.0e12, 6.0e12]})
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=2.5, fallback_beta=1.0, peer_beta_de=None, is_financial=True,
    )  # blume(2.5)=2.0 > 1.6 → clamps to the band's high edge
    assert coc.beta.beta_used_source == "financial_beta_clamp"
    assert coc.beta.beta_used == pytest.approx(cfg.market.financial_beta_high)
    assert any("clamped" in w for w in coc.warnings)


def test_financial_peer_median_fallback(cfg):
    """Out-of-band regression beta but in-band peer median → use peer-median bank beta."""
    profile = _profile(1.0e13)
    income = _df({"operating_income": [3.0e11, 3.0e11]})
    balance = _df({"total_debt": [6.0e12, 6.0e12]})
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=2.0, fallback_beta=1.0,    # blume(2.0)=1.67 > 1.6 → out of β band
        peer_beta_de=[(0.9, 0.5), (0.95, 0.5)],    # median 0.925 → in band
        is_financial=True,
    )
    assert coc.beta.beta_used_source == "peer_median_bank"
    assert coc.beta.beta_used == pytest.approx(0.925)
    assert cfg.market.financial_beta_low <= coc.beta.beta_used <= cfg.market.financial_beta_high


def test_no_regression_no_peers_preserves_engine_beta(cfg):
    """Data-poor name (no regression, no peers) → engine's fallback beta kept."""
    profile = _profile(1.0e12)
    income = _df({"interest_expense": [1.0e10, 1.0e10]})
    balance = _df({"total_debt": [2.0e11, 2.0e11]})
    coc = compute_cost_of_capital(
        profile, income, balance, cfg,
        regression_beta=None, fallback_beta=0.85, peer_beta_de=None,
    )
    assert coc.beta.beta_used == pytest.approx(0.85)
    assert coc.beta.beta_used_source == "fallback"


def test_low_yield_uses_rim_primary(cfg):
    """Low-payout name (yield < threshold): RIM is the primary implied estimate."""
    profile = _profile(1.0e12, dividend_yield=0.005, price_to_book=2.0,
                       return_on_equity=0.15)
    income = _df({"interest_expense": [0.0, 0.0], "operating_income": [2.0e11, 2.0e11]})
    balance = _df({"total_debt": [0.0, 0.0]})
    coc = compute_cost_of_capital(profile, income, balance, cfg, fallback_beta=1.0)
    ke = coc.cost_of_equity
    assert ke.implied_method == "residual_income"
    # g caps at terminal 0.05 → RIM = (0.15 + (2-1)·0.05)/2 = 0.10
    assert ke.rim_implied_ke == pytest.approx(0.10)
    assert ke.implied_ke == pytest.approx(ke.rim_implied_ke)
    # both estimates exposed regardless of which is primary
    assert ke.gordon_implied_ke is not None
    assert ke.implied_gap == pytest.approx(ke.implied_ke - ke.capm_ke)


def test_dividend_payer_uses_gordon_primary(cfg):
    """Genuine dividend payer (yield ≥ threshold, sane payout): Gordon primary."""
    profile = _profile(1.0e12, dividend_yield=0.04, price_to_book=3.0,
                       return_on_equity=0.20)
    income = _df({"interest_expense": [0.0, 0.0], "operating_income": [2.0e11, 2.0e11]})
    balance = _df({"total_debt": [0.0, 0.0]})
    coc = compute_cost_of_capital(profile, income, balance, cfg, fallback_beta=1.0)
    ke = coc.cost_of_equity
    assert ke.implied_method == "gordon"
    # payout = 0.04·3/0.20 = 0.6 → g = min(0.05, 0.20·0.4) = 0.05
    # Gordon = 0.04·1.05 + 0.05 = 0.092
    assert ke.gordon_implied_ke == pytest.approx(0.092)
    assert ke.implied_ke == pytest.approx(ke.gordon_implied_ke)
    assert ke.rim_implied_ke is not None   # still exposed


def test_no_raise_on_empty_inputs(cfg):
    coc = compute_cost_of_capital({}, pd.DataFrame(), pd.DataFrame(), cfg)
    # all-equity default weighting, finite WACC, no exception
    assert coc.wacc > 0
    assert coc.equity_weight == pytest.approx(1.0)
