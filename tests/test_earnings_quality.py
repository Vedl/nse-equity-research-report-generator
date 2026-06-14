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
# avg NOA  = 560 ; BS accrual (secondary) = (570-550)/560 = 20/560
# PRIMARY (Hribar-Collins) = (NI - CFO)/avg total assets
#        = (100-140)/((1000+1060)/2) = -40/1030  (negative → clean)


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
# avg NOA  = 830 ; BS accrual (secondary) = (1060-600)/830 = 460/830 → 55% (RED),
#   but this is inflated by capex/NOA growth (net PPE 400→700) — a benign reason.
# PRIMARY (Hribar-Collins) = (NI - CFO)/avg total assets
#        = (120-30)/((1000+1400)/2) = 90/1200 = 7.5% → AMBER.
# The company is still Red overall, driven by Beneish (manipulation) + Piotroski
# (weak fundamentals), NOT by a polluted accrual figure.


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


# ---------------------------------------------------------------------------
# TREASURY-HEAVY company (the TCS / Indian-IT profile that used to false-positive)
# ---------------------------------------------------------------------------
# Huge short-term investments (treasury), roughly flat YoY; CFO ≥ NI every year;
# operating assets growing modestly from receivables.  Must NOT come out red.
#
# NOA strips cash AND ST investments via the broad line (417 / 414):
#   NOA_2023 = (1600-417)-(639-94)  = 1183-545 = 638
#   NOA_2024 = (1820-414)-(739-113) = 1406-626 = 780      (NOT 1130 — STI removed)
# PRIMARY (Hribar-Collins) = (NI-CFO)/avgTA = (486-489)/((1600+1820)/2)
#                          = -3/1710 ≈ -0.18%  → green
# Old polluted form (NI-CFO-CFI)/avgNOA = (486-489+128)/709 = 17.6% would be RED.


@pytest.fixture
def treasury_income() -> pd.DataFrame:
    return _df({
        "total_revenue":             [2200, 2400],
        "cost_of_revenue":           [1400, 1500],
        "gross_profit":              [800, 900],
        "operating_income":          [560, 620],
        "ebitda":                    [600, 660],
        "net_income":                [450, 486],
        "pretax_income":             [580, 640],
        "interest_expense":          [5, 5],
        "selling_general_admin":     [240, 280],
        "depreciation_amortization": [40, 41],
        "basic_average_shares":      [370, 370],
    })


@pytest.fixture
def treasury_balance() -> pd.DataFrame:
    return _df({
        "total_assets":                     [1600, 1820],
        "cash_and_equivalents":             [83, 64],     # narrow cash only
        "cash_and_short_term_investments":  [417, 414],   # broad treasury line
        "short_term_investments":           [334, 350],   # standalone STI
        "total_liabilities":                [639, 739],
        "total_debt":                       [94, 113],
        "long_term_debt":                   [40, 45],
        "current_assets":                   [900, 1000],
        "current_liabilities":              [500, 560],
        "net_ppe":                          [120, 130],
        "accounts_receivable":              [500, 576],
    })


@pytest.fixture
def treasury_cashflow() -> pd.DataFrame:
    return _df({
        "operating_cash_flow":  [470, 489],    # CFO ≥ NI
        "investing_cash_flow":  [-100, -128],  # treasury deployment — must be ignored
        "capital_expenditure":  [-35, -41],
        "free_cash_flow":       [435, 448],
    })


# ===========================================================================
# Sloan accruals — exact hand-computed values
# ===========================================================================


def test_clean_sloan_accruals(clean_income, clean_balance, clean_cashflow):
    acc = sloan_accruals(clean_income, clean_balance, clean_cashflow)
    assert acc.noa_latest == pytest.approx(570.0)
    assert acc.noa_prior == pytest.approx(550.0)
    assert acc.avg_noa == pytest.approx(560.0)
    assert acc.avg_total_assets == pytest.approx(1030.0)
    # secondary ΔNOA ratio unchanged
    assert acc.bs_accrual_ratio == pytest.approx(20.0 / 560.0)
    # PRIMARY Hribar-Collins operating accrual = (100-140)/1030 = -40/1030
    assert acc.cf_accrual_ratio == pytest.approx(-40.0 / 1030.0)
    # headline is the PRIMARY (CF) measure
    assert acc.headline_ratio == pytest.approx(-40.0 / 1030.0)
    # -3.9% (negative, CFO > NI) → green
    assert acc.flag == "green"


def test_weak_sloan_accruals(weak_income, weak_balance, weak_cashflow):
    acc = sloan_accruals(weak_income, weak_balance, weak_cashflow)
    assert acc.noa_latest == pytest.approx(1060.0)
    assert acc.noa_prior == pytest.approx(600.0)
    assert acc.avg_noa == pytest.approx(830.0)
    assert acc.avg_total_assets == pytest.approx(1200.0)
    # secondary ΔNOA ratio: 460/830 = 55% (red on its own, but capex-inflated)
    assert acc.bs_accrual_ratio == pytest.approx(460.0 / 830.0)
    # PRIMARY Hribar-Collins: 90/1200 = 7.5% → amber (no longer the polluted 53%)
    assert acc.cf_accrual_ratio == pytest.approx(90.0 / 1200.0)
    assert acc.headline_ratio == pytest.approx(90.0 / 1200.0)
    assert acc.flag == "amber"


def test_sloan_accruals_missing_data_is_null():
    # Only total_assets present → NOA undefined → clean nulls, no exception.
    bal = _df({"total_assets": [1000, 1100]})
    acc = sloan_accruals(pd.DataFrame(), bal, pd.DataFrame())
    assert acc.noa_latest is None
    assert acc.bs_accrual_ratio is None
    assert acc.cf_accrual_ratio is None
    assert acc.flag == "na"


def test_treasury_heavy_not_false_positive(
    treasury_income, treasury_balance, treasury_cashflow
):
    """TCS-style: huge flat treasury, CFO ≥ NI → must be green, not red."""
    acc = sloan_accruals(treasury_income, treasury_balance, treasury_cashflow)
    # Short-term investments ARE stripped from operating assets (else 1130).
    assert acc.noa_latest == pytest.approx(780.0)
    assert acc.noa_prior == pytest.approx(638.0)
    # PRIMARY (Hribar-Collins) is treasury-immune and negative → green.
    assert acc.cf_accrual_ratio == pytest.approx(-3.0 / 1710.0)
    assert acc.headline_ratio == pytest.approx(-3.0 / 1710.0)
    assert acc.flag == "green"
    # Secondary ΔNOA is elevated (receivables-driven) but does NOT drive the flag.
    assert acc.bs_accrual_ratio == pytest.approx(142.0 / 709.0)

    res = assess_earnings_quality(treasury_income, treasury_balance, treasury_cashflow)
    acc_comp = next(c for c in res.components if c.key == "accruals")
    assert acc_comp.flag == "green"
    # The whole point: a cash-rich, clean-converting name is NOT flagged Red.
    assert res.verdict != "Red"


def test_operating_accrual_red_when_income_outruns_cash():
    """Primary flag still goes red when NI ≫ CFO relative to assets."""
    inc = _df({"net_income": [180, 200]})
    bal = _df({"total_assets": [1000, 1000], "total_liabilities": [400, 400], "total_debt": [0, 0]})
    cf = _df({"operating_cash_flow": [60, 50]})
    acc = sloan_accruals(inc, bal, cf)
    # (200 - 50) / 1000 = 0.15 → red
    assert acc.cf_accrual_ratio == pytest.approx(150.0 / 1000.0)
    assert acc.headline_ratio == pytest.approx(150.0 / 1000.0)
    assert acc.flag == "red"


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
    # Red is driven by Beneish (manipulation) + Piotroski (weak), the honest
    # reasons — the operating accrual is now amber, not a polluted red.
    assert res.verdict == "Red"
    flags = {c.key: c.flag for c in res.components}
    assert flags == {"accruals": "amber", "beneish": "red", "piotroski": "red"}
    # score = (amber 1 + red 0 + red 0) / (2 * 3) * 100
    assert res.quality_score == pytest.approx(100.0 / 6.0)


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
    # clean headline = -40/1030 ≈ -0.039 (negative); lower-is-better, so it beats
    # every peer in {0.02,0.04,0.06,0.08,0.20} → 100th percentile
    assert res.accrual_sector_percentile == pytest.approx(100.0)
    # F-score 9 beats all 5 peers
    assert res.fscore_sector_percentile == pytest.approx(100.0)
