"""Guardrail-aware Buy/Hold/Sell + quality/sentiment overlay (Phase 2C-iii).

The recommendation is a function of three things:

  1. upside/downside — intrinsic value vs market price;
  2. the earnings-quality overlay — higher quality needs a smaller margin of
     safety before a directional call, lower quality needs more (NEVER alters
     WACC/Ke; it only sets the bar for the call);
  3. the plausibility-guardrail status — **the critical constraint**: if any
     guardrail fired for a name, the call MUST NOT be a confident directional
     one.  It is downgraded toward Hold and marked low-confidence, so a flagged
     valuation (HDFC's merger-ROE, single-stage-g conservatism on high-growth
     banks) can never produce a confident "SELL, X% overvalued".

Broker consensus and news sentiment are consumed through a clean interface that
Phase 3 will populate; while absent they degrade gracefully (marked pending,
never fabricated).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Required margin of safety by earnings-quality verdict. Higher quality ⇒ a
# smaller cushion is demanded before issuing a directional call.
_MOS_BY_QUALITY: dict[str, float] = {
    "Green": 0.10,
    "Amber": 0.20,
    "Red": 0.35,
    "Unrated": 0.25,
}
_DEFAULT_MOS = 0.25


@dataclass
class Recommendation:
    """A guardrail-aware directional call with explicit conviction + reasoning."""

    action: str                     # "BUY" / "HOLD" / "SELL"
    conviction: str                 # "high" / "medium" / "low"
    flagged: bool                   # a plausibility guardrail fired
    upside_pct: float | None        # intrinsic/price − 1
    required_mos: float             # margin of safety demanded (by quality)
    quality_verdict: str            # Green / Amber / Red / Unrated
    reason: str
    overlay_notes: list[str] = field(default_factory=list)


def required_margin_of_safety(
    quality_verdict: str | None,
    *,
    broker: object | None = None,
    news: object | None = None,
) -> float:
    """Margin of safety required before a directional call, set by quality.

    ``broker``/``news`` are reserved for the Phase-3 sentiment overlay; while
    they are ``None`` the MoS depends on the earnings-quality verdict alone.
    """
    return _MOS_BY_QUALITY.get(quality_verdict or "Unrated", _DEFAULT_MOS)


def decide_recommendation(
    *,
    upside_pct: float | None,
    quality_verdict: str | None,
    guardrail_fired: bool,
    has_critical: bool = False,
    broker: object | None = None,
    news: object | None = None,
) -> Recommendation:
    """Combine upside, the quality overlay, and guardrail status into a call."""
    verdict = quality_verdict or "Unrated"
    notes: list[str] = []
    if broker is None:
        notes.append("Broker consensus: pending (Phase 3)")
    if news is None:
        notes.append("News sentiment: pending (Phase 3)")

    mos = required_margin_of_safety(verdict, broker=broker, news=news)
    flagged = bool(guardrail_fired or has_critical)

    # ── Base directional call: upside vs the quality-set margin of safety ──
    if upside_pct is None:
        action, conviction = "HOLD", "low"
        reason = "No upside estimate available — Hold."
    elif upside_pct >= mos:
        action = "BUY"
        conviction = "high" if (verdict == "Green" and upside_pct >= 1.5 * mos) else "medium"
        reason = (
            f"Intrinsic value implies {upside_pct:+.0%} upside, clearing the "
            f"{mos:.0%} margin of safety required at {verdict} quality."
        )
    elif upside_pct <= -mos:
        action = "SELL"
        conviction = "high" if (verdict == "Green" and upside_pct <= -1.5 * mos) else "medium"
        reason = (
            f"Intrinsic value implies {upside_pct:+.0%} downside, beyond the "
            f"−{mos:.0%} margin required at {verdict} quality."
        )
    else:
        action = "HOLD"
        conviction = "low" if verdict == "Red" else "medium"
        reason = (
            f"Intrinsic value is within ±{mos:.0%} of price "
            f"({upside_pct:+.0%}) — fairly valued, Hold."
        )

    # ── GUARDRAIL OVERRIDE (the critical requirement) ─────────────────────
    # A flagged valuation must never become a confident directional call.
    if flagged:
        if action in ("BUY", "SELL"):
            reason = (
                "Valuation flagged by a plausibility guardrail — a confident "
                f"directional call is withheld and defaulted to Hold. (Unflagged "
                f"read would have been {action} on {upside_pct:+.0%}.)"
            )
            action = "HOLD"
        else:
            reason = reason + " Valuation is flagged — treat with low confidence."
        conviction = "low"

    return Recommendation(
        action=action,
        conviction=conviction,
        flagged=flagged,
        upside_pct=upside_pct,
        required_mos=mos,
        quality_verdict=verdict,
        reason=reason,
        overlay_notes=notes,
    )
