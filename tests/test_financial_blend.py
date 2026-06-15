"""Retention-aware bank valuation — the dividend-DDM is weighted by payout.

A dividend-only DDM is valid only to the extent earnings are distributed, so a
high-retention bank must be valued off the ROE-spread (justified-P/B) component,
not the DDM. The weight is continuous in payout (no arbitrary cutoff).
"""

from __future__ import annotations

import pytest

from equity_research.analysis.financial_sector import (
    _DDM_MAX_WEIGHT,
    payout_weighted_blend,
)

_PB = 900.0    # ROE-spread (justified-P/B) value
_DDM = 180.0   # dividend-only DDM value (structurally lower)


def test_ddm_weight_falls_as_payout_falls():
    weights = [payout_weighted_blend(_PB, _DDM, p)[1] for p in (0.80, 0.50, 0.16, 0.01)]
    assert weights == sorted(weights, reverse=True)        # strictly non-increasing
    assert weights[0] > weights[-1]                         # and actually falls
    # weight equals payout in the uncapped region
    assert payout_weighted_blend(_PB, _DDM, 0.16)[1] == pytest.approx(0.16)


def test_high_retention_valued_off_roe_spread_not_ddm():
    # 1.2% payout (AXIS-like) → almost entirely the ROE-spread value.
    intrinsic, w = payout_weighted_blend(_PB, _DDM, 0.012)
    assert w == pytest.approx(0.012)
    assert intrinsic == pytest.approx(0.988 * _PB + 0.012 * _DDM)
    # within 2% of the pure ROE-spread value, nowhere near the 50/50 blend
    assert abs(intrinsic - _PB) / _PB < 0.02
    assert intrinsic > 0.5 * (_PB + _DDM)


def test_high_payout_leans_on_ddm_but_capped():
    # 95% payout → DDM weight capped, not 0.95.
    intrinsic, w = payout_weighted_blend(_PB, _DDM, 0.95)
    assert w == pytest.approx(_DDM_MAX_WEIGHT)
    assert intrinsic == pytest.approx((1 - _DDM_MAX_WEIGHT) * _PB + _DDM_MAX_WEIGHT * _DDM)


def test_no_ddm_returns_roe_spread():
    intrinsic, w = payout_weighted_blend(_PB, None, 0.5)
    assert intrinsic == pytest.approx(_PB)
    assert w == 0.0


def test_icici_case_clears_where_fifty_fifty_did_not():
    # ICICI live: pb≈896, ddm≈188, payout≈15.9%, price≈1343.
    fifty_fifty = 0.5 * 896 + 0.5 * 188
    weighted, _ = payout_weighted_blend(896.0, 188.0, 0.159)
    price = 1343.0
    assert fifty_fifty / price < 0.5      # old blend was flagged
    assert weighted / price >= 0.5        # payout-weighted clears
