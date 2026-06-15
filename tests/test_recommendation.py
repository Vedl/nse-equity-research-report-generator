"""Phase 2C-iii — guardrail-aware recommendation tests.

The central requirement: a flagged valuation must never produce a confident
directional call (HDFC's merger-ROE must come back Hold/low-confidence, not a
confident SELL). Plus: the quality overlay sets the required margin of safety,
and broker/news are never fabricated while absent.
"""

from __future__ import annotations

import pytest

from equity_research.analysis.recommendation import (
    decide_recommendation,
    required_margin_of_safety,
)


# ===========================================================================
# The critical test — a fired guardrail forbids a confident directional call
# ===========================================================================


def test_flagged_downside_is_hold_not_confident_sell():
    """HDFC-like: −53% downside but a guardrail fired → Hold/low, NOT SELL."""
    rec = decide_recommendation(
        upside_pct=-0.53, quality_verdict="Amber",
        guardrail_fired=True, has_critical=False,
    )
    assert rec.action == "HOLD"          # not a confident SELL
    assert rec.conviction == "low"
    assert rec.flagged is True
    assert "SELL" not in rec.reason or "withheld" in rec.reason
    # The reason must explain the call was withheld due to the flag.
    assert "guardrail" in rec.reason.lower()


def test_flagged_upside_is_also_downgraded_to_hold():
    rec = decide_recommendation(
        upside_pct=0.40, quality_verdict="Green", guardrail_fired=True,
    )
    assert rec.action == "HOLD"
    assert rec.conviction == "low"


def test_unflagged_downside_can_be_a_real_sell():
    """ICICI-like: clears the guardrail → a directional call is allowed."""
    rec = decide_recommendation(
        upside_pct=-0.42, quality_verdict="Amber", guardrail_fired=False,
    )
    assert rec.action == "SELL"
    assert rec.conviction == "medium"
    assert rec.flagged is False


def test_unflagged_green_strong_upside_is_high_conviction_buy():
    rec = decide_recommendation(
        upside_pct=0.30, quality_verdict="Green", guardrail_fired=False,
    )
    assert rec.action == "BUY"
    assert rec.conviction == "high"   # Green + ≥1.5× MoS


# ===========================================================================
# Quality overlay sets the required margin of safety
# ===========================================================================


def test_required_mos_rises_as_quality_falls():
    green = required_margin_of_safety("Green")
    amber = required_margin_of_safety("Amber")
    red = required_margin_of_safety("Red")
    assert green < amber < red
    assert required_margin_of_safety(None) == required_margin_of_safety("Unrated")


def test_overlay_changes_call_at_same_upside():
    # +15% upside: clears Green's 10% MoS (BUY) but not Red's 35% (HOLD).
    buy = decide_recommendation(upside_pct=0.15, quality_verdict="Green", guardrail_fired=False)
    hold = decide_recommendation(upside_pct=0.15, quality_verdict="Red", guardrail_fired=False)
    assert buy.action == "BUY"
    assert hold.action == "HOLD"


# ===========================================================================
# Broker / news: pending, never fabricated
# ===========================================================================


def test_broker_and_news_marked_pending_when_absent():
    rec = decide_recommendation(upside_pct=0.05, quality_verdict="Amber", guardrail_fired=False)
    joined = " ".join(rec.overlay_notes).lower()
    assert "broker" in joined and "pending" in joined
    assert "news" in joined


def test_no_upside_estimate_is_hold():
    rec = decide_recommendation(upside_pct=None, quality_verdict="Green", guardrail_fired=False)
    assert rec.action == "HOLD"
    assert rec.conviction == "low"
