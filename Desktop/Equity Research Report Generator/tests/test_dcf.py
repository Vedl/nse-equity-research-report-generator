"""Pytest tests for analysis/dcf.py.

Hand-computed reference values
-------------------------------
terminal_value test (wacc=0.12, g=0.04, fcff_final=133.1):
    TV = 133.1 × 1.04 / (0.12 − 0.04) = 138.424 / 0.08 = 1730.3

pv_cashflows test — growth rate == discount rate (10%):
    CF = [110, 121, 133.1], wacc = 0.10
    PV1 = 110 / 1.10       = 100.000
    PV2 = 121 / 1.21       = 100.000
    PV3 = 133.1 / 1.331    = 100.000

dcf_equity_per_share 3-year explicit (wacc=0.12, g=0.04):
    projected = [110, 121, 133.1]
    TV  = 1730.3
    PV1 = 110 / 1.12       =  98.21429
    PV2 = 121 / 1.12²      =  96.46046
    PV3 = 133.1 / 1.12³    =  94.73800
    PV(TV) = 1730.3 / 1.12³ = 1231.593
    EV     = 1521.006
    Equity = 1521.006 − 500 = 1021.006
    Intrinsic = 1021.006 / 10 = 102.101

compute_wacc (market_cap=1000, debt=400, ie=20, beta=1.2, using config values):
    Ke = rf + 1.2 × erp
    Kd_pre = 20/400 = 0.05,  Kd_after = 0.05 × (1 − tax)
    WACC = (1000/1400) × Ke + (400/1400) × Kd_after

compute_base_fcff (synthetic fixtures, 2024 row):
    NOPAT  = 219.615e7 × 0.75   = 164.711e7
    D&A    =  73.205e7
    CapEx  = −87.846e7
    ΔNWC   = −29.282e7
    FCFF   = 164.711 + 73.205 − 87.846 − 29.282 = 120.788 (×1e7)
    margin = 120.788 / 1464.10  ≈ 0.0825
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from equity_research.analysis.dcf import (
    DCFResult,
    WACCComponents,
    build_sensitivity_table,
    compute_base_fcff,
    compute_growth_rates,
    compute_wacc,
    dcf_equity_per_share,
    project_fcff,
    pv_cashflows,
    run_dcf,
    terminal_value,
)
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Fixtures: minimal DataFrames for unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


@pytest.fixture
def mini_balance() -> pd.DataFrame:
    """One-row balance sheet with 400 units of debt and 100 units of cash."""
    return pd.DataFrame(
        {"total_debt": [400.0], "cash_and_equivalents": [100.0]},
        index=pd.Index([2024], name="year"),
    )


@pytest.fixture
def mini_income() -> pd.DataFrame:
    """One-row income statement with 20 units of interest expense."""
    return pd.DataFrame(
        {
            "total_revenue": [2000.0],
            "operating_income": [300.0],
            "interest_expense": [20.0],
        },
        index=pd.Index([2024], name="year"),
    )


@pytest.fixture
def mini_profile() -> dict:
    """Minimal profile: market_cap=1000, beta=1.2."""
    return {"market_cap": 1000.0, "beta": 1.2, "shares_outstanding": 10.0}


# ---------------------------------------------------------------------------
# terminal_value
# ---------------------------------------------------------------------------


def test_terminal_value_known_answer() -> None:
    # TV = 133.1 × 1.04 / (0.12 − 0.04) = 1730.3
    tv = terminal_value(133.1, wacc=0.12, g=0.04)
    assert tv == pytest.approx(1730.3, rel=1e-6)


def test_terminal_value_wacc_greater_than_g() -> None:
    # Any WACC > g should work without raising
    tv = terminal_value(100.0, wacc=0.10, g=0.04)
    assert tv > 0


def test_terminal_value_wacc_equal_g_raises() -> None:
    with pytest.raises(ValueError, match="strictly greater"):
        terminal_value(100.0, wacc=0.05, g=0.05)


def test_terminal_value_wacc_less_than_g_raises() -> None:
    with pytest.raises(ValueError):
        terminal_value(100.0, wacc=0.03, g=0.05)


def test_terminal_value_higher_g_gives_higher_tv() -> None:
    tv_lo = terminal_value(100.0, wacc=0.12, g=0.03)
    tv_hi = terminal_value(100.0, wacc=0.12, g=0.05)
    assert tv_hi > tv_lo


def test_terminal_value_higher_wacc_gives_lower_tv() -> None:
    tv_lo = terminal_value(100.0, wacc=0.10, g=0.04)
    tv_hi = terminal_value(100.0, wacc=0.15, g=0.04)
    assert tv_lo > tv_hi


# ---------------------------------------------------------------------------
# pv_cashflows
# ---------------------------------------------------------------------------


def test_pv_cashflows_single() -> None:
    # PV of 110 at 10% in 1 year = 100
    result = pv_cashflows([110.0], wacc=0.10)
    assert result == pytest.approx([100.0], rel=1e-10)


def test_pv_cashflows_growth_equals_discount_rate() -> None:
    # [110, 121, 133.1] growing at 10%, discounted at 10% → all PVs = 100
    result = pv_cashflows([110.0, 121.0, 133.1], wacc=0.10)
    assert result == pytest.approx([100.0, 100.0, 100.0], rel=1e-6)


def test_pv_cashflows_discounts_by_year() -> None:
    # Check each element uses the correct exponent: t+1
    pvs = pv_cashflows([100.0, 100.0], wacc=0.10)
    assert pvs[0] == pytest.approx(100.0 / 1.10, rel=1e-10)
    assert pvs[1] == pytest.approx(100.0 / (1.10 ** 2), rel=1e-10)


def test_pv_cashflows_order_matters() -> None:
    # First CF (t=1) is discounted less than second CF (t=2)
    pvs = pv_cashflows([100.0, 100.0], wacc=0.10)
    assert pvs[0] > pvs[1]


def test_pv_cashflows_empty_list() -> None:
    assert pv_cashflows([], wacc=0.10) == []


# ---------------------------------------------------------------------------
# project_fcff
# ---------------------------------------------------------------------------


def test_project_fcff_constant_growth() -> None:
    # 100 × 1.10 × 1.10 × 1.10 = 133.1
    result = project_fcff(100.0, [0.10, 0.10, 0.10])
    assert result == pytest.approx([110.0, 121.0, 133.1], rel=1e-6)


def test_project_fcff_zero_growth() -> None:
    result = project_fcff(100.0, [0.0, 0.0])
    assert result == pytest.approx([100.0, 100.0], rel=1e-10)


def test_project_fcff_length_matches_rates() -> None:
    result = project_fcff(100.0, [0.05, 0.08, 0.10, 0.12, 0.15])
    assert len(result) == 5


def test_project_fcff_each_year_grows_from_previous() -> None:
    result = project_fcff(100.0, [0.10, 0.20])
    assert result[0] == pytest.approx(110.0, rel=1e-10)
    assert result[1] == pytest.approx(110.0 * 1.20, rel=1e-10)


# ---------------------------------------------------------------------------
# dcf_equity_per_share — full 3-year known-answer case
# ---------------------------------------------------------------------------


def test_dcf_equity_per_share_tv_formula() -> None:
    # TV = 133.1 × 1.04 / 0.08 = 1730.3
    tv = terminal_value(133.1, wacc=0.12, g=0.04)
    assert tv == pytest.approx(1730.3, rel=1e-6)


def test_dcf_equity_per_share_three_year_explicit() -> None:
    """Full 3-year DCF — every number derived by hand in the module docstring."""
    fcffs = [110.0, 121.0, 133.1]
    wacc = 0.12
    tv = terminal_value(fcffs[-1], wacc, g=0.04)   # 1730.3

    intrinsic = dcf_equity_per_share(fcffs, tv, wacc, net_debt=500.0, shares=10.0)

    # PVs at 12%:
    #   PV1 = 110/1.12          =  98.21429
    #   PV2 = 121/1.12²         =  96.46046
    #   PV3 = 133.1/1.12³       =  94.73800
    #   PV(TV) = 1730.3/1.12³   = 1231.593
    #   EV = 1521.006,  Equity = 1021.006,  Intrinsic = 102.101
    assert intrinsic == pytest.approx(102.101, rel=1e-3)


def test_dcf_equity_per_share_net_cash_increases_value() -> None:
    # Negative net debt (net cash) → equity > EV → higher intrinsic value
    tv = terminal_value(100.0, 0.12, 0.04)
    val_debt = dcf_equity_per_share([100.0], tv, 0.12, net_debt=200.0, shares=1.0)
    val_cash = dcf_equity_per_share([100.0], tv, 0.12, net_debt=-200.0, shares=1.0)
    assert val_cash > val_debt


def test_dcf_equity_per_share_zero_shares_raises() -> None:
    tv = terminal_value(100.0, 0.12, 0.04)
    with pytest.raises(ValueError, match="shares must be positive"):
        dcf_equity_per_share([100.0], tv, 0.12, net_debt=0.0, shares=0.0)


def test_dcf_equity_per_share_higher_wacc_lower_value() -> None:
    fcffs = [110.0, 121.0, 133.1]
    tv_lo = terminal_value(fcffs[-1], 0.10, 0.04)
    tv_hi = terminal_value(fcffs[-1], 0.15, 0.04)
    val_lo = dcf_equity_per_share(fcffs, tv_lo, 0.10, 0.0, 1.0)
    val_hi = dcf_equity_per_share(fcffs, tv_hi, 0.15, 0.0, 1.0)
    assert val_lo > val_hi


# ---------------------------------------------------------------------------
# build_sensitivity_table
# ---------------------------------------------------------------------------


def test_sensitivity_table_shape() -> None:
    fcffs = project_fcff(100.0, [0.10] * 5)
    tbl = build_sensitivity_table(fcffs, wacc_base=0.12, g_base=0.04, net_debt=0.0, shares=1.0)
    assert tbl.shape == (5, 5)


def test_sensitivity_table_center_matches_base_case() -> None:
    """The (0, 0)-offset cell must equal dcf_equity_per_share at base WACC and g."""
    fcffs = project_fcff(100.0, [0.10] * 5)
    wacc = 0.12
    g = 0.04
    net_debt = 500.0
    shares = 10.0

    tbl = build_sensitivity_table(fcffs, wacc, g, net_debt, shares)
    tv_base = terminal_value(fcffs[-1], wacc, g)
    expected = dcf_equity_per_share(fcffs, tv_base, wacc, net_debt, shares)

    # Center row index 2, center column index 2 (offsets = 0)
    center_row = tbl.index[2]
    center_col = tbl.columns[2]
    assert tbl.loc[center_row, center_col] == pytest.approx(expected, rel=1e-8)


def test_sensitivity_table_higher_wacc_lower_value() -> None:
    """Moving down a column (higher WACC) should reduce intrinsic value."""
    fcffs = project_fcff(100.0, [0.10] * 5)
    tbl = build_sensitivity_table(fcffs, 0.12, 0.04, 0.0, 1.0)
    col = tbl.columns[2]   # center g column
    values = tbl[col].dropna().values
    for i in range(len(values) - 1):
        assert values[i] > values[i + 1], (
            f"Expected row {i} > row {i+1} for same g, got {values[i]} <= {values[i+1]}"
        )


def test_sensitivity_table_higher_g_higher_value() -> None:
    """Moving right across a row (higher terminal g) should increase intrinsic value."""
    fcffs = project_fcff(100.0, [0.10] * 5)
    tbl = build_sensitivity_table(fcffs, 0.12, 0.04, 0.0, 1.0)
    row = tbl.index[2]   # center WACC row
    values = tbl.loc[row].dropna().values
    for i in range(len(values) - 1):
        assert values[i] < values[i + 1], (
            f"Expected col {i} < col {i+1} for same WACC, got {values[i]} >= {values[i+1]}"
        )


def test_sensitivity_table_invalid_cell_is_nan() -> None:
    """WACC ≤ terminal g must produce NaN, not a spurious value."""
    fcffs = project_fcff(100.0, [0.10] * 5)
    # wacc_base=0.05, g_base=0.04
    # Smallest WACC = 0.05 − 0.02 = 0.03; largest g = 0.04 + 0.01 = 0.05
    # → several cells have WACC ≤ g
    tbl = build_sensitivity_table(
        fcffs,
        wacc_base=0.05,
        g_base=0.04,
        net_debt=0.0,
        shares=1.0,
        wacc_offsets=(-0.02, -0.01, 0.0, 0.01, 0.02),
        g_offsets=(-0.01, -0.005, 0.0, 0.005, 0.01),
    )
    # WACC=0.03 row (index 0): all g values (0.03–0.05) → 0.03 ≤ every g → all NaN
    first_row = tbl.iloc[0]
    assert first_row.isna().all(), f"Expected all NaN in first row, got:\n{first_row}"


def test_sensitivity_table_index_and_columns_are_pct_strings() -> None:
    fcffs = project_fcff(100.0, [0.10] * 3)
    tbl = build_sensitivity_table(fcffs, 0.12, 0.04, 0.0, 1.0)
    assert tbl.index.name == "WACC"
    assert all("%" in c for c in tbl.columns)
    assert all("%" in r for r in tbl.index)


# ---------------------------------------------------------------------------
# compute_wacc
# ---------------------------------------------------------------------------


def test_compute_wacc_known_answer(mini_profile, mini_income, mini_balance, cfg) -> None:
    """WACC with market_cap=1000, D=400, ie=20, beta=1.2, from actual config values."""
    result = compute_wacc(mini_profile, mini_income, mini_balance, cfg)

    # Ke = Rf + 1.2 × ERP
    ke = cfg.market.risk_free_rate + 1.2 * cfg.market.equity_risk_premium
    # Kd_pre = 20/400 = 0.05 (5%); clamped already in [1%,30%]
    kd_after = 0.05 * (1.0 - cfg.market.tax_rate)
    # E=1000, D=400, V=1400
    expected_wacc = (1000.0 / 1400.0) * ke + (400.0 / 1400.0) * kd_after

    assert result.wacc == pytest.approx(expected_wacc, rel=1e-6)
    assert result.cost_of_equity == pytest.approx(ke, rel=1e-10)
    assert result.cost_of_debt_pretax == pytest.approx(0.05, rel=1e-6)
    assert result.cost_of_debt_aftertax == pytest.approx(kd_after, rel=1e-6)


def test_compute_wacc_weights_sum_to_one(mini_profile, mini_income, mini_balance, cfg) -> None:
    result = compute_wacc(mini_profile, mini_income, mini_balance, cfg)
    assert result.equity_weight + result.debt_weight == pytest.approx(1.0, rel=1e-10)


def test_compute_wacc_correct_weights(mini_profile, mini_income, mini_balance, cfg) -> None:
    result = compute_wacc(mini_profile, mini_income, mini_balance, cfg)
    # E=1000, D=400
    assert result.equity_weight == pytest.approx(1000.0 / 1400.0, rel=1e-6)
    assert result.debt_weight == pytest.approx(400.0 / 1400.0, rel=1e-6)


def test_compute_wacc_missing_market_cap_raises(mini_income, mini_balance, cfg) -> None:
    bad_profile = {"beta": 1.0}   # no market_cap
    with pytest.raises(ValueError, match="market_cap"):
        compute_wacc(bad_profile, mini_income, mini_balance, cfg)


def test_compute_wacc_missing_beta_defaults_to_one(mini_income, mini_balance, cfg) -> None:
    profile_no_beta = {"market_cap": 1000.0}  # no beta
    result = compute_wacc(profile_no_beta, mini_income, mini_balance, cfg)
    ke_expected = cfg.market.risk_free_rate + 1.0 * cfg.market.equity_risk_premium
    assert result.cost_of_equity == pytest.approx(ke_expected, rel=1e-6)


def test_compute_wacc_pure_equity_firm(mini_income, cfg) -> None:
    """Company with zero debt: WACC should equal cost of equity."""
    profile = {"market_cap": 1000.0, "beta": 1.2}
    balance_no_debt = pd.DataFrame(
        {"total_debt": [0.0], "cash_and_equivalents": [0.0]},
        index=pd.Index([2024], name="year"),
    )
    result = compute_wacc(profile, mini_income, balance_no_debt, cfg)
    ke = cfg.market.risk_free_rate + 1.2 * cfg.market.equity_risk_premium
    assert result.wacc == pytest.approx(ke, rel=1e-6)
    assert result.equity_weight == pytest.approx(1.0, rel=1e-10)
    assert result.debt_weight == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# compute_base_fcff — synthetic fixtures
# ---------------------------------------------------------------------------


def test_compute_base_fcff_known_answer(
    synthetic_income: pd.DataFrame,
    synthetic_cashflow: pd.DataFrame,
    cfg,
) -> None:
    """
    2024 FCFF (hand-computed):
      NOPAT  = 219.615e7 × 0.75 = 164.711e7
      D&A    = 73.205e7
      CapEx  = −87.846e7
      ΔNWC   = −29.282e7
      FCFF   = 120.788e7
      margin ≈ 0.0825
    """
    base_fcff, margin = compute_base_fcff(
        synthetic_income, synthetic_cashflow, tax_rate=cfg.market.tax_rate
    )
    assert base_fcff == pytest.approx(120.788e7, rel=1e-3)
    assert margin == pytest.approx(0.0825, rel=1e-3)


def test_compute_base_fcff_returns_tuple(
    synthetic_income, synthetic_cashflow, cfg
) -> None:
    result = compute_base_fcff(synthetic_income, synthetic_cashflow, cfg.market.tax_rate)
    assert isinstance(result, tuple) and len(result) == 2


def test_compute_base_fcff_margin_positive(
    synthetic_income, synthetic_cashflow, cfg
) -> None:
    _, margin = compute_base_fcff(synthetic_income, synthetic_cashflow, cfg.market.tax_rate)
    assert margin > 0


def test_compute_base_fcff_empty_income_raises(synthetic_cashflow, cfg) -> None:
    with pytest.raises(ValueError, match="Insufficient|no usable"):
        compute_base_fcff(pd.DataFrame(), synthetic_cashflow, cfg.market.tax_rate)


# ---------------------------------------------------------------------------
# compute_growth_rates
# ---------------------------------------------------------------------------


def test_compute_growth_rates_manual_override(synthetic_income, cfg) -> None:
    cfg.dcf.revenue_growth_source = "manual"
    cfg.dcf.revenue_growth_override = 0.12
    cfg.dcf.projection_horizon = 5
    rates = compute_growth_rates(synthetic_income, cfg)
    assert rates == pytest.approx([0.12] * 5, rel=1e-10)


def test_compute_growth_rates_manual_no_override_raises(synthetic_income, cfg) -> None:
    cfg.dcf.revenue_growth_source = "manual"
    cfg.dcf.revenue_growth_override = None
    with pytest.raises(ValueError, match="revenue_growth_override"):
        compute_growth_rates(synthetic_income, cfg)


def test_compute_growth_rates_historical_cagr(synthetic_income, cfg) -> None:
    """Synthetic fixtures grow at exactly 10% p.a. — historical CAGR should be 10%."""
    cfg.dcf.revenue_growth_source = "historical_cagr"
    cfg.dcf.projection_horizon = 5
    rates = compute_growth_rates(synthetic_income, cfg)
    assert len(rates) == 5
    assert rates[0] == pytest.approx(0.10, rel=1e-3)


def test_compute_growth_rates_length_equals_horizon(synthetic_income, cfg) -> None:
    cfg.dcf.revenue_growth_source = "historical_cagr"
    cfg.dcf.projection_horizon = 3
    rates = compute_growth_rates(synthetic_income, cfg)
    assert len(rates) == 3


def test_compute_growth_rates_clamped(synthetic_income, cfg) -> None:
    """Growth rates must stay within [−30%, 50%] regardless of input data."""
    cfg.dcf.revenue_growth_source = "historical_cagr"
    rates = compute_growth_rates(synthetic_income, cfg)
    for g in rates:
        assert -0.30 <= g <= 0.50


# ---------------------------------------------------------------------------
# run_dcf — integration test on synthetic fixtures
# ---------------------------------------------------------------------------


def test_run_dcf_returns_dcf_result(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert isinstance(result, DCFResult)


def test_run_dcf_enterprise_value_positive(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert result.enterprise_value > 0


def test_run_dcf_intrinsic_value_finite(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    import math
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert math.isfinite(result.intrinsic_value_per_share)


def test_run_dcf_sensitivity_is_5x5(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert result.sensitivity.shape == (5, 5)


def test_run_dcf_projected_fcff_length_equals_horizon(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert len(result.projected_fcff) == cfg.dcf.projection_horizon


def test_run_dcf_wacc_reasonable(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    """WACC should sit in a credible range for an Indian equity (5%–25%)."""
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert 0.05 < result.wacc < 0.25


def test_run_dcf_pv_fcff_length_matches_projection(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert len(result.pv_fcff) == len(result.projected_fcff)


def test_run_dcf_ev_equals_pv_fcff_plus_pv_tv(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    """Internal consistency: EV = Σ PV(FCFF) + PV(TV)."""
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    ev_check = sum(result.pv_fcff) + result.pv_terminal_value
    assert result.enterprise_value == pytest.approx(ev_check, rel=1e-8)


def test_run_dcf_equity_equals_ev_minus_net_debt(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    """Internal consistency: Equity = EV − Net Debt."""
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = run_dcf(synthetic_profile, financials, cfg)
    assert result.equity_value == pytest.approx(
        result.enterprise_value - result.net_debt, rel=1e-8
    )


def test_run_dcf_missing_shares_raises(
    synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    bad_profile = {"market_cap": 1000e9, "beta": 1.2}   # no shares
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    with pytest.raises(ValueError, match="shares_outstanding"):
        run_dcf(bad_profile, financials, cfg)
