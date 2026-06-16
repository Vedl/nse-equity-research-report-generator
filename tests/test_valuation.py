"""Known-answer tests for the Phase 1/2 valuation overhaul.

Covers the deployment checklist cases: two-stage DCF maths, size premium,
negative-FCFF edge cases, banks with broken book value, sparse data,
Piotroski strong-vs-weak discrimination, Beneish manipulation flagging,
Altman zoning, H-Model DDM, blending/rating/confidence, and ₹ formatting.
"""

from __future__ import annotations


import pandas as pd
import pytest

from equity_research.analysis.conviction import (
    assign_rating,
    blend_values,
    confidence_score,
)
from equity_research.analysis.dcf import (
    size_premium,
    terminal_value,
    two_stage_growth_schedule,
)
from equity_research.analysis.financial_sector import run_financial_valuation
from equity_research.analysis.quality import (
    altman_z_score,
    beneish_m_score,
    cash_conversion_cycle,
    dupont_decomposition,
    piotroski_f_score,
)
from equity_research.config import load_config
from equity_research.utils.contracts import ValuationError
from equity_research.utils.formatting import format_inr, indian_group

from pathlib import Path

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def _df(data: dict, years: list[int]) -> pd.DataFrame:
    return pd.DataFrame(data, index=pd.Index(years, name="year")).astype(float)


# ---------------------------------------------------------------------------
# 1–3. Two-stage DCF mechanics
# ---------------------------------------------------------------------------


def test_two_stage_schedule_known_answer() -> None:
    """g1=20%, gT=5%, 5+5 → fade hits exactly 5% in year 10.

    Per the fade formula g_t = gT + (g1 − gT) × (10 − t)/5:
    year 6 = 5% + 15%×4/5 = 17%; year 8 = 5% + 15%×2/5 = 11%; year 10 = 5%.
    """
    sched = two_stage_growth_schedule(0.20, 0.05, stage1_years=5, fade_years=5)
    assert len(sched) == 10
    assert sched[:5] == [0.20] * 5
    assert sched[5] == pytest.approx(0.17)
    assert sched[7] == pytest.approx(0.11)
    assert sched[9] == pytest.approx(0.05)


def test_two_stage_schedule_monotonic_fade() -> None:
    sched = two_stage_growth_schedule(0.30, 0.05)
    fade = sched[5:]
    assert all(a >= b for a, b in zip(fade, fade[1:]))   # decreasing to terminal


def test_size_premium_bands() -> None:
    """Large ≥ ₹50,000 Cr → 0.5%; mid ≥ ₹17,000 Cr → 1.0%; small → 2.0%."""
    assert size_premium(60_000e7) == pytest.approx(0.005)
    assert size_premium(20_000e7) == pytest.approx(0.010)
    assert size_premium(5_000e7) == pytest.approx(0.020)
    assert size_premium(None) == pytest.approx(0.010)    # unknown → mid-cap


# ---------------------------------------------------------------------------
# 4. Negative terminal value guard
# ---------------------------------------------------------------------------


def test_terminal_value_raises_when_wacc_below_growth() -> None:
    with pytest.raises(ValueError):
        terminal_value(100.0, wacc=0.04, g=0.05)


def test_valuation_error_is_value_error() -> None:
    """ValuationError must be catchable as ValueError by legacy handlers."""
    assert issubclass(ValuationError, ValueError)


# ---------------------------------------------------------------------------
# 5. Negative FCFF in all five years
# ---------------------------------------------------------------------------


def test_negative_fcff_all_years_uses_least_negative(cfg) -> None:
    """All-negative FCFF must not produce a fabricated positive base."""
    from equity_research.analysis.dcf import compute_base_fcff

    years = [2021, 2022, 2023, 2024, 2025]
    income = _df({"total_revenue": [100e7] * 5, "operating_income": [-10e7] * 5}, years)
    cashflow = _df({
        "depreciation_amortization": [2e7] * 5,
        "capital_expenditure": [-5e7] * 5,
        "change_in_working_capital": [-1e7] * 5,
    }, years)
    base, _margin = compute_base_fcff(income, cashflow, tax_rate=0.25)
    # FCFF each year = −10×0.75 + 2 − 5 − 1 = −11.5 Cr; least-negative = −11.5 Cr
    assert base == pytest.approx(-11.5e7)
    assert base < 0   # never silently flipped positive


# ---------------------------------------------------------------------------
# 6. Bank with negative equity (guard) and sparse data
# ---------------------------------------------------------------------------


def test_bank_negative_equity_falls_back_or_raises(cfg) -> None:
    years = [2024, 2025]
    income = _df({"net_income": [50e7, 60e7]}, years)
    balance = _df({"stockholders_equity": [-100e7, -120e7]}, years)
    profile = {
        "ticker": "BADBANK.NS", "market_cap": 1_000e7, "beta": 1.0,
        "shares_outstanding": 10e7, "current_price": 100.0,
        # no price_to_book → book value cannot be derived
    }
    with pytest.raises(ValueError):
        run_financial_valuation(profile, {"income": income, "balance_sheet": balance}, cfg)


def test_dcf_with_under_3_years_of_data_still_runs(cfg) -> None:
    from equity_research.analysis.dcf import run_dcf

    years = [2024, 2025]
    income = _df({
        "total_revenue": [100e7, 115e7], "operating_income": [20e7, 24e7],
        "interest_expense": [2e7, 2e7],
    }, years)
    balance = _df({
        "total_debt": [10e7, 10e7], "cash_and_equivalents": [5e7, 6e7],
    }, years)
    cashflow = _df({
        "depreciation_amortization": [4e7, 4e7],
        "capital_expenditure": [-6e7, -7e7],
        "change_in_working_capital": [-1e7, -1e7],
    }, years)
    profile = {"market_cap": 5_000e7, "beta": 1.0, "shares_outstanding": 10e7}
    result = run_dcf(profile, {
        "income": income, "balance_sheet": balance, "cash_flow": cashflow,
    }, cfg)
    assert result.intrinsic_value_per_share > 0
    assert len(result.projected_fcff) == cfg.dcf.projection_horizon + cfg.dcf.stage2_fade_years


# ---------------------------------------------------------------------------
# 7. Piotroski: strong vs weak discrimination
# ---------------------------------------------------------------------------


def _strong_company():
    years = [2024, 2025]
    income = _df({
        "total_revenue": [100e7, 120e7], "cost_of_revenue": [60e7, 68e7],
        "gross_profit": [40e7, 52e7], "net_income": [10e7, 14e7],
        "basic_average_shares": [10e7, 10e7],
    }, years)
    balance = _df({
        "total_assets": [100e7, 105e7], "current_assets": [40e7, 46e7],
        "current_liabilities": [20e7, 20e7], "long_term_debt": [20e7, 16e7],
    }, years)
    cashflow = _df({"operating_cash_flow": [16e7, 20e7]}, years)
    return income, balance, cashflow


def _weak_company():
    years = [2024, 2025]
    income = _df({
        "total_revenue": [120e7, 100e7], "cost_of_revenue": [70e7, 65e7],
        "gross_profit": [50e7, 35e7], "net_income": [5e7, -8e7],
        "basic_average_shares": [10e7, 12e7],
    }, years)
    balance = _df({
        "total_assets": [100e7, 110e7], "current_assets": [40e7, 36e7],
        "current_liabilities": [20e7, 26e7], "long_term_debt": [20e7, 30e7],
    }, years)
    cashflow = _df({"operating_cash_flow": [6e7, -4e7]}, years)
    return income, balance, cashflow


def test_piotroski_strong_company_scores_high() -> None:
    r = piotroski_f_score(*_strong_company())
    assert r.score >= 7
    assert r.verdict == "Strong"


def test_piotroski_weak_company_scores_low() -> None:
    r = piotroski_f_score(*_weak_company())
    assert r.score <= 2
    assert r.verdict == "Weak"


# ---------------------------------------------------------------------------
# 8. Beneish: manipulator-profile data must flag
# ---------------------------------------------------------------------------


def test_beneish_flags_manipulator_profile() -> None:
    """Receivables ballooning vs sales, collapsing margins, heavy accruals —
    the canonical pre-restatement fingerprint (cf. Beneish 1999 sample).
    """
    years = [2024, 2025]
    income = _df({
        "total_revenue": [100e7, 160e7],          # SGI 1.6
        "cost_of_revenue": [60e7, 120e7],         # GM 40% → 25% (GMI 1.6)
        "selling_general_admin": [10e7, 12e7],
        "net_income": [10e7, 22e7],
        "depreciation_amortization": [5e7, 4e7],
    }, years)
    balance = _df({
        "accounts_receivable": [15e7, 60e7],      # DSRI 2.5
        "current_assets": [40e7, 90e7],
        "current_liabilities": [20e7, 30e7],
        "net_ppe": [40e7, 42e7],
        "total_assets": [100e7, 170e7],
        "long_term_debt": [20e7, 40e7],
    }, years)
    cashflow = _df({"operating_cash_flow": [9e7, -5e7]}, years)   # TATA strongly +
    r = beneish_m_score(income, balance, cashflow)
    assert r.m_score is not None
    assert r.m_score > -1.78
    assert r.flagged is True


def test_beneish_clean_company_not_flagged() -> None:
    income, balance, cashflow = _strong_company()
    income["selling_general_admin"] = [8e7, 9e7]
    income["depreciation_amortization"] = [4e7, 4.4e7]
    balance["accounts_receivable"] = [12e7, 13e7]
    balance["net_ppe"] = [40e7, 42e7]
    r = beneish_m_score(income, balance, cashflow)
    assert r.m_score is not None
    assert r.flagged is False


# ---------------------------------------------------------------------------
# 9. Altman zones
# ---------------------------------------------------------------------------


def test_altman_safe_zone_known_answer() -> None:
    years = [2025]
    income = _df({"operating_income": [30e7]}, years)
    balance = _df({
        "total_assets": [100e7], "current_assets": [50e7],
        "current_liabilities": [20e7], "retained_earnings": [40e7],
        "stockholders_equity": [60e7], "total_liabilities": [40e7],
    }, years)
    r = altman_z_score(income, balance)
    # Z = 6.56×0.30 + 3.26×0.40 + 6.72×0.30 + 1.05×1.50 = 6.86
    assert r.z_score == pytest.approx(6.86, abs=0.01)
    assert r.zone == "Safe"


def test_altman_not_applicable_for_financials() -> None:
    r = altman_z_score(pd.DataFrame(), pd.DataFrame(), is_financial=True)
    assert r.applicable is False
    assert r.zone == "N/A"


# ---------------------------------------------------------------------------
# 10. H-Model DDM known answer
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. Blending, rating, confidence
# ---------------------------------------------------------------------------


def test_blend_weights_60_40() -> None:
    assert blend_values(100.0, 50.0) == pytest.approx(0.6 * 100 + 0.4 * 50)
    assert blend_values(100.0, None) == pytest.approx(100.0)
    assert blend_values(None, 50.0) == pytest.approx(50.0)
    assert blend_values(None, None) is None


def test_rating_bands() -> None:
    assert assign_rating(0.20) == "BUY"
    assert assign_rating(0.15) == "BUY"
    assert assign_rating(0.05) == "HOLD"
    assert assign_rating(-0.11) == "SELL"
    assert assign_rating(-0.10) == "HOLD"   # band is −10% inclusive … +15% exclusive
    assert assign_rating(-0.05) == "HOLD"
    assert assign_rating(None) == "NR"


def test_confidence_score_full_house() -> None:
    score, comps, agree = confidence_score(
        primary_value=100.0, secondary_value=105.0,   # within 15% → +20
        clean_data_years=5, peer_count=6, beta_months=60,
        has_analyst_consensus=True, earnings_quality_high=True,
        negative_base_fcff=False, high_accruals=False, beneish_flagged=False,
    )
    assert score == 100
    assert agree is True


def test_confidence_score_penalties_floor_at_zero() -> None:
    score, _, _ = confidence_score(
        primary_value=100.0, secondary_value=200.0,   # diverge → +0
        clean_data_years=2, peer_count=1, beta_months=0,
        has_analyst_consensus=False, earnings_quality_high=False,
        negative_base_fcff=True, high_accruals=True, beneish_flagged=True,
    )
    assert score == 0


# ---------------------------------------------------------------------------
# 12. Indian-notation formatting
# ---------------------------------------------------------------------------


def test_indian_group_lakh_crore_notation() -> None:
    assert indian_group(12345678) == "1,23,45,678"
    assert indian_group(1234.5, 2) == "1,234.50"
    assert indian_group(-12345678) == "-1,23,45,678"


def test_format_inr_crore() -> None:
    # ₹7.78 lakh crore market cap → "₹7,78,251 Cr"
    assert format_inr(7_78_251e7) == "₹7,78,251 Cr"
    assert format_inr(None) == "n/a"
    assert format_inr(2151.0, unit="rupee", decimals=2) == "₹2,151.00"


# ---------------------------------------------------------------------------
# 13. CCC & DuPont sanity on aligned data
# ---------------------------------------------------------------------------


def test_ccc_known_answer() -> None:
    years = [2025]
    income = _df({"total_revenue": [365e7], "cost_of_revenue": [365e7]}, years)
    balance = _df({
        "accounts_receivable": [50e7], "inventory": [30e7], "accounts_payable": [20e7],
    }, years)
    r = cash_conversion_cycle(income, balance)
    assert r.dso[-1] == pytest.approx(50.0)
    assert r.dio[-1] == pytest.approx(30.0)
    assert r.dpo[-1] == pytest.approx(20.0)
    assert r.ccc[-1] == pytest.approx(60.0)


def test_dupont_product_reconciles_to_roe() -> None:
    years = [2025]
    income = _df({
        "net_income": [12e7], "pretax_income": [16e7], "operating_income": [20e7],
        "total_revenue": [100e7],
    }, years)
    balance = _df({"total_assets": [80e7], "stockholders_equity": [40e7]}, years)
    r = dupont_decomposition(income, balance)
    y = r.years[-1]
    product = (y.tax_burden * y.interest_burden * y.ebit_margin
               * y.asset_turnover * y.leverage)
    assert product == pytest.approx(y.roe, rel=1e-9)
    assert y.roe == pytest.approx(0.30)
