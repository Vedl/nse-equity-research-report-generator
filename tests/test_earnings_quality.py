"""Phase 2A — earnings-quality / financial-reliability tests.

Two synthetic names with hand-computed expected values:

* ``CLEAN`` — low accruals, cash-backed earnings, strong fundamentals → Green.
* ``WEAK``  — ballooning NOA, CFO ≪ NI, deteriorating fundamentals → Red.

All numbers below are chosen so the NOA, accrual-ratio, F-score and M-score
formulas can be verified by hand in the assertions.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from equity_research.analysis.earnings_quality import (
    assess_earnings_quality,
    sector_percentile,
    sloan_accruals,
)

_YEARS = pd.Index([2023, 2024], name="year")


def _df(cols: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(cols, index=_YEARS)


# ---------------------------------------------------------------------------
# CLEAN company — every figure hand-computed in the assertions below
# ---------------------------------------------------------------------------
# NOA_2023 = (1000-200)-(400-150) = 550 ; NOA_2024 = (1060-230)-(410-150) = 570
# avg NOA  = 560 ; BS accrual = (570-550)/560 = 20/560
# CF accrual = (NI - CFO - CFI)/avg = (100-140-(-50))/560 = 10/560


@pytest.fixture
def clean_income() -> pd.DataFrame:
    return _df({
        "total_revenue":             [460, 500],
        "cost_of_revenue":           [290, 300],
        "gross_profit":              [170, 200],
        "operating_income":          [80, 95],
        "ebitda":                    [110, 130],
        "net_income":                [85, 100],
        "pretax_income":             [78, 92],
        "interest_expense":          [5, 5],
        "selling_general_admin":     [50, 52],
        "depreciation_amortization": [25, 26],
        "basic_average_shares":      [50, 50],
    })


@pytest.fixture
def clean_balance() -> pd.DataFrame:
    return _df({
        "total_assets":         [1000, 1060],
        "cash_and_equivalents": [200, 230],
        "total_liabilities":    [400, 410],
        "total_debt":           [150, 150],
        "long_term_debt":       [120, 120],
        "current_assets":       [360, 400],
        "current_liabilities":  [200, 200],
        "net_ppe":              [400, 410],
        "accounts_receivable":  [90, 92],
    })


@pytest.fixture
def clean_cashflow() -> pd.DataFrame:
    return _df({
        "operating_cash_flow":  [120, 140],
        "investing_cash_flow":  [-40, -50],
        "capital_expenditure":  [-40, -50],
        "free_cash_flow":       [80, 90],
    })


# ---------------------------------------------------------------------------
# WEAK company
# ---------------------------------------------------------------------------
# NOA_2023 = (1000-100)-(500-200) = 600 ; NOA_2024 = (1400-80)-(560-300) = 1060
# avg NOA  = 830 ; BS accrual = (1060-600)/830 = 460/830
# CF accrual = (120-30-(-350))/830 = 440/830


@pytest.fixture
def weak_income() -> pd.DataFrame:
    return _df({
        "total_revenue":             [800, 1000],
        "cost_of_revenue":           [500, 720],
        "gross_profit":              [300, 280],
        "operating_income":          [150, 100],
        "ebitda":                    [200, 160],
        "net_income":                [150, 120],
        "pretax_income":             [140, 110],
        "interest_expense":          [10, 20],
        "selling_general_admin":     [80, 110],
        "depreciation_amortization": [40, 60],
        "basic_average_shares":      [50, 60],
    })


@pytest.fixture
def weak_balance() -> pd.DataFrame:
    return _df({
        "total_assets":         [1000, 1400],
        "cash_and_equivalents": [100, 80],
        "total_liabilities":    [500, 560],
        "total_debt":           [200, 300],
        "long_term_debt":       [150, 280],
        "current_assets":       [300, 330],
        "current_liabilities":  [200, 260],
        "net_ppe":              [400, 700],
        "accounts_receivable":  [100, 250],
    })


@pytest.fixture
def weak_cashflow() -> pd.DataFrame:
    return _df({
        "operating_cash_flow":  [100, 30],
        "investing_cash_flow":  [-150, -350],
        "capital_expenditure":  [-150, -350],
        "free_cash_flow":       [-50, -320],
    })


# ===========================================================================
# Sloan accruals — exact hand-computed values
# ===========================================================================


def test_clean_sloan_accruals(clean_income, clean_balance, clean_cashflow):
    acc = sloan_accruals(clean_income, clean_balance, clean_cashflow)
    assert acc.noa_latest == pytest.approx(570.0)
    assert acc.noa_prior == pytest.approx(550.0)
    assert acc.avg_noa == pytest.approx(560.0)
    assert acc.bs_accrual_ratio == pytest.approx(20.0 / 560.0)
    assert acc.cf_accrual_ratio == pytest.approx(10.0 / 560.0)
    # 20/560 = 3.57% ≤ 5% → green
    assert acc.flag == "green"


def test_weak_sloan_accruals(weak_income, weak_balance, weak_cashflow):
    acc = sloan_accruals(weak_income, weak_balance, weak_cashflow)
    assert acc.noa_latest == pytest.approx(1060.0)
    assert acc.noa_prior == pytest.approx(600.0)
    assert acc.avg_noa == pytest.approx(830.0)
    assert acc.bs_accrual_ratio == pytest.approx(460.0 / 830.0)
    assert acc.cf_accrual_ratio == pytest.approx(440.0 / 830.0)
    # 460/830 = 55% ≫ 10% → red
    assert acc.flag == "red"


def test_sloan_accruals_missing_data_is_null():
    # Only total_assets present → NOA undefined → clean nulls, no exception.
    bal = _df({"total_assets": [1000, 1100]})
    acc = sloan_accruals(pd.DataFrame(), bal, pd.DataFrame())
    assert acc.noa_latest is None
    assert acc.bs_accrual_ratio is None
    assert acc.cf_accrual_ratio is None
    assert acc.flag == "na"


# ===========================================================================
# Piotroski & Beneish integration — hand-computed
# ===========================================================================


def test_clean_piotroski_all_nine(clean_income, clean_balance, clean_cashflow):
    res = assess_earnings_quality(clean_income, clean_balance, clean_cashflow)
    # Every one of the 9 signals passes by construction.
    assert res.piotroski.score == 9
    assert res.piotroski.max_available == 9


def test_weak_piotroski_two(weak_income, weak_balance, weak_cashflow):
    res = assess_earnings_quality(weak_income, weak_balance, weak_cashflow)
    # Only F1 (ROA>0) and F2 (CFO>0) pass; the other seven fail.
    assert res.piotroski.score == 2
    assert res.piotroski.max_available == 9


def test_weak_beneish_indices_and_flag(weak_income, weak_balance, weak_cashflow):
    res = assess_earnings_quality(weak_income, weak_balance, weak_cashflow)
    v = res.beneish.variables
    # DSRI = (250/1000)/(100/800) = 0.25/0.125 = 2.0
    assert v["DSRI"] == pytest.approx(2.0)
    # SGI = 1000/800 = 1.25
    assert v["SGI"] == pytest.approx(1.25)
    # TATA = (NI - CFO)/TA = (120-30)/1400
    assert v["TATA"] == pytest.approx(90.0 / 1400.0)
    # Hand-summed M ≈ -0.94 (> -1.78) → manipulation flag
    assert res.beneish.m_score == pytest.approx(-0.938, abs=0.02)
    assert res.beneish.flagged is True


def test_clean_beneish_not_flagged(clean_income, clean_balance, clean_cashflow):
    res = assess_earnings_quality(clean_income, clean_balance, clean_cashflow)
    # TATA = (100-140)/1060 (negative accruals — conservative)
    assert res.beneish.variables["TATA"] == pytest.approx(-40.0 / 1060.0)
    # Hand-summed M ≈ -2.66 (≤ -2.22) → green, not flagged
    assert res.beneish.m_score == pytest.approx(-2.657, abs=0.02)
    assert res.beneish.flagged is False


# ===========================================================================
# Combined verdict
# ===========================================================================


def test_clean_verdict_green(clean_income, clean_balance, clean_cashflow):
    res = assess_earnings_quality(clean_income, clean_balance, clean_cashflow)
    assert res.verdict == "Green"
    assert res.quality_score == pytest.approx(100.0)
    flags = {c.key: c.flag for c in res.components}
    assert flags == {"accruals": "green", "beneish": "green", "piotroski": "green"}
    # Every component carries a one-line reason.
    assert all(c.reason for c in res.components)


def test_weak_verdict_red(weak_income, weak_balance, weak_cashflow):
    res = assess_earnings_quality(weak_income, weak_balance, weak_cashflow)
    assert res.verdict == "Red"
    assert res.quality_score == pytest.approx(0.0)
    flags = {c.key: c.flag for c in res.components}
    assert flags == {"accruals": "red", "beneish": "red", "piotroski": "red"}


def test_empty_inputs_unrated_no_raise():
    res = assess_earnings_quality(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert res.verdict == "Unrated"
    assert res.quality_score is None
    assert res.accrual_sector_percentile is None
    assert res.fscore_sector_percentile is None


# ===========================================================================
# Sector percentile (pure helper)
# ===========================================================================


def test_sector_percentile_accruals_lower_is_better():
    # company accrual 0.035 vs peers; lower is better
    peers = [0.02, 0.04, 0.06, 0.08, 0.20]
    # peers with accrual >= 0.035: {0.04,0.06,0.08,0.20} = 4 of 5
    assert sector_percentile(0.035, peers, higher_is_better=False) == pytest.approx(80.0)


def test_sector_percentile_fscore_higher_is_better():
    peers = [3.0, 5.0, 6.0, 7.0, 8.0]
    assert sector_percentile(9.0, peers, higher_is_better=True) == pytest.approx(100.0)


def test_sector_percentile_thin_or_missing_returns_none():
    assert sector_percentile(0.05, [0.01, 0.02], higher_is_better=False) is None
    assert sector_percentile(None, [0.01, 0.02, 0.03], higher_is_better=False) is None
    assert sector_percentile(0.05, None, higher_is_better=False) is None


def test_assess_wires_percentiles(clean_income, clean_balance, clean_cashflow):
    res = assess_earnings_quality(
        clean_income, clean_balance, clean_cashflow,
        sector="Technology",
        accrual_peer_samples=[0.02, 0.04, 0.06, 0.08, 0.20],
        fscore_peer_samples=[3.0, 5.0, 6.0, 7.0, 8.0],
    )
    assert res.sector == "Technology"
    assert res.peer_sample_size == 5
    # clean accrual headline = 20/560 ≈ 0.0357; peers >= that: {0.04,0.06,0.08,0.20}=4/5
    assert res.accrual_sector_percentile == pytest.approx(80.0)
    # F-score 9 beats all 5 peers
    assert res.fscore_sector_percentile == pytest.approx(100.0)
