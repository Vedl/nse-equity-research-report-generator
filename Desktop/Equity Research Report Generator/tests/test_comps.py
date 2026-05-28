"""Tests for analysis/comps.py and analysis/valuation.py.

Hand-computed reference values used in assertions
--------------------------------------------------
_pos_median:
  [10, 20, 30]            → 20   (odd, middle)
  [10, 30]                → 20   (even, average of two)
  [None, 20, None]        → 20   (Nones ignored)
  [-5, 10, 20]            → 15   (negatives excluded; even of [10, 20])
  []                      → None
  [None]                  → None

_implied_from_pe(20, 50)            = 1000
_implied_from_ev_ebitda(12, 200, 100, 10) = (12×200 − 100)/10 = 230
_implied_from_ev_ebitda(12, 200, None, 10) = 12×200/10 = 240  (net_debt→0)
_implied_from_pb(2.0, 80)           = 160
_implied_from_ev_sales(3.0, 500, 100, 10) = (3×500 − 100)/10 = 140

_implied_range([1000, 230, 160, 140]) → low=140, high=1000, median=(160+230)/2=195

Mocked comps pipeline (3 peers):
  P/E      = [20, 25, 18]  → sorted [18,20,25] → median = 20
  EV/EBITDA= [12, 14, 10]  → sorted [10,12,14] → median = 12
  P/B      = [2.5, 3.0, 2.0]→sorted [2,2.5,3] → median = 2.5
  EV/Sales = [3.0, 3.5, 2.5]→sorted [2.5,3,3.5]→ median = 3.0

  Synthetic-fixture target (2024 values, all ×1e7 INR):
    EPS               = 14.641  (basic_eps from income)
    EBITDA            = 1464.1e7 × 0.20 = 292.82e7
    Revenue           = 1464.1e7
    Equity            = 1171.28e7
    Debt              = 585.64e7,  Cash = 146.41e7
    Net debt          = 439.23e7
    Shares            = 1 000 000 000
    Book/share        = 1171.28e7 / 1e9 = 11.7128

  implied_pe       = 20 × 14.641                     = 292.82
  implied_ev_ebitda= (12 × 292.82e7 − 439.23e7)/1e9 = 30.7461
  implied_pb       = 2.5 × 11.7128                   = 29.282
  implied_ev_sales = (3 × 1464.1e7 − 439.23e7)/1e9  = 39.530

ValuationSummary:
  current=900, dcf=1200 → dcf_upside = 300/900 = 1/3
  current=900, dcf=600  → dcf_upside = −300/900 = −1/3
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from equity_research.analysis.comps import (
    CompsResult,
    PeerMultiples,
    _extract_peer_multiples,
    _implied_from_ev_ebitda,
    _implied_from_ev_sales,
    _implied_from_pb,
    _implied_from_pe,
    _implied_range,
    _pos_median,
    compute_comps,
)
from equity_research.analysis.dcf import DCFResult, WACCComponents
from equity_research.analysis.valuation import ValuationSummary, valuation_summary
from equity_research.config import load_config

_REPO = pytest.importorpath = __file__  # just to locate repo root
import pathlib
_REPO = pathlib.Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# _pos_median
# ---------------------------------------------------------------------------


def test_pos_median_odd_count() -> None:
    assert _pos_median([10.0, 20.0, 30.0]) == pytest.approx(20.0)


def test_pos_median_even_count() -> None:
    assert _pos_median([10.0, 30.0]) == pytest.approx(20.0)


def test_pos_median_ignores_none() -> None:
    assert _pos_median([None, 20.0, None]) == pytest.approx(20.0)


def test_pos_median_excludes_negatives() -> None:
    # [-5, 10, 20] → valid=[10, 20] → even → (10+20)/2 = 15
    assert _pos_median([-5.0, 10.0, 20.0]) == pytest.approx(15.0)


def test_pos_median_excludes_zero() -> None:
    assert _pos_median([0.0, 10.0, 20.0]) == pytest.approx(15.0)


def test_pos_median_all_none_returns_none() -> None:
    assert _pos_median([None, None]) is None


def test_pos_median_empty_returns_none() -> None:
    assert _pos_median([]) is None


def test_pos_median_single_value() -> None:
    assert _pos_median([42.0]) == pytest.approx(42.0)


def test_pos_median_five_values() -> None:
    # [5,1,3,4,2] → sorted [1,2,3,4,5] → median = 3
    assert _pos_median([5.0, 1.0, 3.0, 4.0, 2.0]) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# _implied_range
# ---------------------------------------------------------------------------


def test_implied_range_normal() -> None:
    low, high, med = _implied_range([1000.0, 230.0, 160.0, 140.0])
    assert low == pytest.approx(140.0)
    assert high == pytest.approx(1000.0)
    assert med == pytest.approx(195.0)   # (160+230)/2


def test_implied_range_all_none() -> None:
    low, high, med = _implied_range([None, None, None])
    assert low is None and high is None and med is None


def test_implied_range_single_value() -> None:
    low, high, med = _implied_range([500.0])
    assert low == pytest.approx(500.0)
    assert high == pytest.approx(500.0)
    assert med == pytest.approx(500.0)


def test_implied_range_mixed_none() -> None:
    low, high, med = _implied_range([None, 200.0, None, 100.0])
    assert low == pytest.approx(100.0)
    assert high == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Individual implied-value functions
# ---------------------------------------------------------------------------


def test_implied_from_pe_known_answer() -> None:
    assert _implied_from_pe(20.0, 50.0) == pytest.approx(1000.0)


def test_implied_from_pe_none_pe() -> None:
    assert _implied_from_pe(None, 50.0) is None


def test_implied_from_pe_none_eps() -> None:
    assert _implied_from_pe(20.0, None) is None


def test_implied_from_pe_zero_eps() -> None:
    assert _implied_from_pe(20.0, 0.0) is None


def test_implied_from_pe_negative_eps() -> None:
    assert _implied_from_pe(20.0, -5.0) is None


def test_implied_from_ev_ebitda_known_answer() -> None:
    # (12 × 200 − 100) / 10 = 230
    assert _implied_from_ev_ebitda(12.0, 200.0, 100.0, 10.0) == pytest.approx(230.0)


def test_implied_from_ev_ebitda_none_net_debt_defaults_zero() -> None:
    # (12 × 200 − 0) / 10 = 240
    assert _implied_from_ev_ebitda(12.0, 200.0, None, 10.0) == pytest.approx(240.0)


def test_implied_from_ev_ebitda_missing_multiple() -> None:
    assert _implied_from_ev_ebitda(None, 200.0, 100.0, 10.0) is None


def test_implied_from_ev_ebitda_zero_ebitda() -> None:
    assert _implied_from_ev_ebitda(12.0, 0.0, 100.0, 10.0) is None


def test_implied_from_ev_ebitda_zero_shares() -> None:
    assert _implied_from_ev_ebitda(12.0, 200.0, 100.0, 0.0) is None


def test_implied_from_pb_known_answer() -> None:
    assert _implied_from_pb(2.0, 80.0) == pytest.approx(160.0)


def test_implied_from_pb_none_pb() -> None:
    assert _implied_from_pb(None, 80.0) is None


def test_implied_from_pb_zero_book() -> None:
    assert _implied_from_pb(2.0, 0.0) is None


def test_implied_from_pb_negative_book() -> None:
    assert _implied_from_pb(2.0, -10.0) is None


def test_implied_from_ev_sales_known_answer() -> None:
    # (3 × 500 − 100) / 10 = 140
    assert _implied_from_ev_sales(3.0, 500.0, 100.0, 10.0) == pytest.approx(140.0)


def test_implied_from_ev_sales_none_net_debt_defaults_zero() -> None:
    # (3 × 500 − 0) / 10 = 150
    assert _implied_from_ev_sales(3.0, 500.0, None, 10.0) == pytest.approx(150.0)


def test_implied_from_ev_sales_zero_revenue() -> None:
    assert _implied_from_ev_sales(3.0, 0.0, 100.0, 10.0) is None


# ---------------------------------------------------------------------------
# _extract_peer_multiples
# ---------------------------------------------------------------------------


def test_extract_peer_multiples_all_present() -> None:
    profile = {
        "ticker": "TEST.NS",
        "trailing_pe": 22.0,
        "enterprise_to_ebitda": 14.0,
        "price_to_book": 3.0,
        "enterprise_to_revenue": 3.5,
    }
    pm = _extract_peer_multiples(profile)
    assert pm.ticker == "TEST.NS"
    assert pm.pe == pytest.approx(22.0)
    assert pm.ev_ebitda == pytest.approx(14.0)
    assert pm.pb == pytest.approx(3.0)
    assert pm.ev_sales == pytest.approx(3.5)


def test_extract_peer_multiples_missing_pe() -> None:
    profile = {"ticker": "TEST.NS", "price_to_book": 2.0}
    pm = _extract_peer_multiples(profile)
    assert pm.pe is None
    assert pm.pb == pytest.approx(2.0)


def test_extract_peer_multiples_negative_excluded() -> None:
    profile = {
        "ticker": "TEST.NS",
        "trailing_pe": -5.0,    # loss-making → excluded
        "price_to_book": 1.5,
    }
    pm = _extract_peer_multiples(profile)
    assert pm.pe is None
    assert pm.pb == pytest.approx(1.5)


def test_extract_peer_multiples_all_none() -> None:
    pm = _extract_peer_multiples({"ticker": "EMPTY.NS"})
    assert pm.pe is None
    assert pm.ev_ebitda is None
    assert pm.pb is None
    assert pm.ev_sales is None


# ---------------------------------------------------------------------------
# compute_comps — mocked provider
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def _make_peer_profile(ticker, pe, ev_ebitda, pb, ev_sales):
    return {
        "ticker": ticker,
        "trailing_pe": pe,
        "enterprise_to_ebitda": ev_ebitda,
        "price_to_book": pb,
        "enterprise_to_revenue": ev_sales,
    }


@pytest.fixture
def mock_provider():
    mp = MagicMock()
    mp.get_peers.return_value = ["PEER1.NS", "PEER2.NS", "PEER3.NS"]
    mp.get_profile.side_effect = [
        _make_peer_profile("PEER1.NS", pe=20.0, ev_ebitda=12.0, pb=2.5, ev_sales=3.0),
        _make_peer_profile("PEER2.NS", pe=25.0, ev_ebitda=14.0, pb=3.0, ev_sales=3.5),
        _make_peer_profile("PEER3.NS", pe=18.0, ev_ebitda=10.0, pb=2.0, ev_sales=2.5),
    ]
    return mp


@pytest.fixture
def comps_result(
    synthetic_profile,
    synthetic_income,
    synthetic_balance,
    synthetic_cashflow,
    mock_provider,
    cfg,
) -> CompsResult:
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    return compute_comps(synthetic_profile, financials, mock_provider, cfg)


def test_comps_returns_correct_type(comps_result) -> None:
    assert isinstance(comps_result, CompsResult)


def test_comps_peer_count(comps_result) -> None:
    assert len(comps_result.peers) == 3


def test_comps_median_pe(comps_result) -> None:
    # [18, 20, 25] → median = 20
    assert comps_result.median_pe == pytest.approx(20.0)


def test_comps_median_ev_ebitda(comps_result) -> None:
    # [10, 12, 14] → median = 12
    assert comps_result.median_ev_ebitda == pytest.approx(12.0)


def test_comps_median_pb(comps_result) -> None:
    # [2.0, 2.5, 3.0] → median = 2.5
    assert comps_result.median_pb == pytest.approx(2.5)


def test_comps_median_ev_sales(comps_result) -> None:
    # [2.5, 3.0, 3.5] → median = 3.0
    assert comps_result.median_ev_sales == pytest.approx(3.0)


def test_comps_implied_pe(comps_result) -> None:
    # median_pe=20 × EPS=14.641 = 292.82
    assert comps_result.implied_pe == pytest.approx(20.0 * 14.641, rel=1e-3)


def test_comps_implied_ev_ebitda(comps_result) -> None:
    # (12 × 292.82e7 − 439.23e7) / 1e9
    ebitda = 1_464.1e7 * 0.20
    net_debt = 585.64e7 - 146.41e7
    expected = (12.0 * ebitda - net_debt) / 1e9
    assert comps_result.implied_ev_ebitda == pytest.approx(expected, rel=1e-3)


def test_comps_implied_pb(comps_result) -> None:
    # 2.5 × (1171.28e7 / 1e9) = 2.5 × 11.7128 = 29.282
    book_per_share = 1_171.28e7 / 1e9
    assert comps_result.implied_pb == pytest.approx(2.5 * book_per_share, rel=1e-3)


def test_comps_implied_ev_sales(comps_result) -> None:
    # (3.0 × 1464.1e7 − 439.23e7) / 1e9
    net_debt = 585.64e7 - 146.41e7
    expected = (3.0 * 1_464.1e7 - net_debt) / 1e9
    assert comps_result.implied_ev_sales == pytest.approx(expected, rel=1e-3)


def test_comps_implied_low_is_minimum(comps_result) -> None:
    candidates = [
        v for v in [
            comps_result.implied_pe,
            comps_result.implied_ev_ebitda,
            comps_result.implied_pb,
            comps_result.implied_ev_sales,
        ]
        if v is not None
    ]
    assert comps_result.implied_low == pytest.approx(min(candidates), rel=1e-6)


def test_comps_implied_high_is_maximum(comps_result) -> None:
    candidates = [
        v for v in [
            comps_result.implied_pe,
            comps_result.implied_ev_ebitda,
            comps_result.implied_pb,
            comps_result.implied_ev_sales,
        ]
        if v is not None
    ]
    assert comps_result.implied_high == pytest.approx(max(candidates), rel=1e-6)


def test_comps_implied_low_leq_high(comps_result) -> None:
    if comps_result.implied_low is not None and comps_result.implied_high is not None:
        assert comps_result.implied_low <= comps_result.implied_high


def test_comps_no_peers_returns_all_none(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    mp = MagicMock()
    mp.get_peers.return_value = []
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = compute_comps(synthetic_profile, financials, mp, cfg)
    assert result.median_pe is None
    assert result.implied_pe is None
    assert result.implied_low is None
    assert result.peers == []


def test_comps_all_none_peer_skipped(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    """A peer with no usable multiples must be excluded from the peer list."""
    mp = MagicMock()
    mp.get_peers.return_value = ["GOOD.NS", "BAD.NS"]
    mp.get_profile.side_effect = [
        _make_peer_profile("GOOD.NS", pe=20.0, ev_ebitda=12.0, pb=2.5, ev_sales=3.0),
        {"ticker": "BAD.NS"},    # no multiples at all
    ]
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = compute_comps(synthetic_profile, financials, mp, cfg)
    assert len(result.peers) == 1
    assert result.peers[0].ticker == "GOOD.NS"


def test_comps_peer_fetch_failure_skipped(
    synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow, cfg
) -> None:
    """A provider failure for one peer must not crash the whole comps run."""
    mp = MagicMock()
    mp.get_peers.return_value = ["OK.NS", "FAIL.NS"]
    mp.get_profile.side_effect = [
        _make_peer_profile("OK.NS", pe=22.0, ev_ebitda=13.0, pb=2.8, ev_sales=3.2),
        RuntimeError("network timeout"),
    ]
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    result = compute_comps(synthetic_profile, financials, mp, cfg)
    assert len(result.peers) == 1
    assert result.peers[0].ticker == "OK.NS"


# ---------------------------------------------------------------------------
# valuation_summary
# ---------------------------------------------------------------------------


def _make_dcf_result(intrinsic: float) -> DCFResult:
    wc = WACCComponents(
        cost_of_equity=0.134,
        cost_of_debt_pretax=0.05,
        cost_of_debt_aftertax=0.0375,
        equity_weight=0.90,
        debt_weight=0.10,
        wacc=0.124,
    )
    return DCFResult(
        base_fcff=100.0, fcff_margin=0.08, growth_rate=0.10,
        wacc=0.124, terminal_growth=0.04, net_debt=50.0, shares_outstanding=10.0,
        projected_fcff=[110.0, 121.0], pv_fcff=[98.2, 96.5],
        terminal_value_nominal=1730.0, pv_terminal_value=1200.0,
        enterprise_value=1395.0, equity_value=1345.0,
        intrinsic_value_per_share=intrinsic,
        wacc_components=wc,
        sensitivity=pd.DataFrame(),
    )


def _make_comps_result(low, high, median) -> CompsResult:
    return CompsResult(
        peers=[],
        median_pe=20.0, median_ev_ebitda=12.0, median_pb=2.5, median_ev_sales=3.0,
        implied_pe=None, implied_ev_ebitda=None, implied_pb=None, implied_ev_sales=None,
        implied_low=low, implied_high=high, implied_median=median,
    )


def test_valuation_summary_dcf_upside() -> None:
    # current=900, dcf=1200 → upside = 300/900 = 1/3
    vs = valuation_summary(900.0, _make_dcf_result(1200.0), None)
    assert vs.dcf_upside_pct == pytest.approx(1.0 / 3.0, rel=1e-6)


def test_valuation_summary_dcf_downside() -> None:
    # current=900, dcf=600 → upside = -300/900 = -1/3
    vs = valuation_summary(900.0, _make_dcf_result(600.0), None)
    assert vs.dcf_upside_pct == pytest.approx(-1.0 / 3.0, rel=1e-6)


def test_valuation_summary_no_dcf_gives_none() -> None:
    vs = valuation_summary(900.0, None, None)
    assert vs.dcf_value is None
    assert vs.dcf_upside_pct is None


def test_valuation_summary_comps_upside() -> None:
    # median=1350, current=900 → upside = 450/900 = 0.5
    vs = valuation_summary(900.0, None, _make_comps_result(500.0, 2000.0, 1350.0))
    assert vs.comps_upside_pct == pytest.approx(0.5, rel=1e-6)


def test_valuation_summary_comps_downside() -> None:
    # median=720, current=900 → upside = -180/900 = -0.20
    vs = valuation_summary(900.0, None, _make_comps_result(200.0, 900.0, 720.0))
    assert vs.comps_upside_pct == pytest.approx(-0.20, rel=1e-6)


def test_valuation_summary_no_comps_gives_none() -> None:
    vs = valuation_summary(900.0, None, None)
    assert vs.comps_low is None
    assert vs.comps_high is None
    assert vs.comps_upside_pct is None


def test_valuation_summary_preserves_current_price() -> None:
    vs = valuation_summary(1352.0, None, None)
    assert vs.current_price == pytest.approx(1352.0)


def test_valuation_summary_full(comps_result) -> None:
    dcf = _make_dcf_result(1200.0)
    vs = valuation_summary(1000.0, dcf, comps_result)
    assert isinstance(vs, ValuationSummary)
    assert vs.dcf_value == pytest.approx(1200.0)
    assert vs.dcf_upside_pct == pytest.approx(0.20, rel=1e-6)
    assert vs.comps_low is not None
    assert vs.comps_high is not None
    assert vs.comps_high > vs.comps_low
