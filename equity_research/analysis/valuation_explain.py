"""Valuation explainability (Phase 2C-i).

Makes the chosen valuation explain its math step by step and refuse to emit
nonsensical numbers silently.  Three pieces, all derived from already-computed
results (this module adds no new valuation math):

1. Model-selection rationale — a structured, human-readable record of *why* the
   router picked this model (sector, chosen model, one-line reason).
2. Valuation bridge — the full waterfall from drivers to per-share value as
   structured, labelled steps (not prose), one shape per model.  For the FCFF
   DCF: PV(explicit FCFFs) → + PV(terminal) → = EV → − net debt → − minority →
   = equity value → ÷ shares → intrinsic value/share.
3. Plausibility guardrails — diagnostics (flags + reasons, configurable
   thresholds) that surface a suspect valuation rather than presenting garbage
   as a target.  These never alter the number; they annotate it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from equity_research.analysis.cost_of_capital import CostOfCapital
from equity_research.analysis.valuation import ValuationResult
from equity_research.config import AppConfig

# Friendly labels for the router's model identifiers.
_MODEL_LABELS = {
    "fcff": "FCFF discounted cash flow",
    "ri": "Residual income",
    "excess_return": "Excess-return (bank)",
    "financial": "Justified P/B (financial)",
    "sotp": "Sum-of-the-parts",
    "ev_sales": "EV/Sales (loss-making)",
    "ev_ebitda": "EV/EBITDA relative",
}

_TOL = 1e-6   # relative reconciliation tolerance


def _is_num(v: float | None) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _rel_close(a: float, b: float, tol: float = _TOL) -> bool:
    scale = max(1.0, abs(a), abs(b))
    return abs(a - b) <= tol * scale


# ===========================================================================
# Structured outputs
# ===========================================================================


@dataclass
class ModelRationale:
    sector: str | None
    industry: str | None
    model: str            # router identifier (e.g. "fcff")
    model_label: str      # friendly label
    confidence: str
    reason: str           # the router's one-line why
    headline: str         # "<Sector> — <reason>"


@dataclass
class BridgeStep:
    label: str
    value: float | None
    kind: str             # component | subtotal | deduction | divisor | result


@dataclass
class ValuationBridge:
    model: str
    wacc: float | None                  # discount rate (from cost_of_capital)
    steps: list[BridgeStep]
    shares: float | None
    value_per_share: float | None       # the bridge's own arithmetic result
    reported_value_per_share: float | None  # what the model returned (zero-floored)
    reconciles: bool
    reconciliation_error: float | None  # |bridge − reported| (abs), None if n/a


@dataclass
class Diagnostic:
    code: str
    severity: str         # "warn" | "critical"
    message: str
    value: float | None = None
    threshold: float | None = None


@dataclass
class ValuationExplainability:
    rationale: ModelRationale
    bridge: ValuationBridge | None
    diagnostics: list[Diagnostic]
    has_critical: bool = False
    warnings: list[str] = field(default_factory=list)


# ===========================================================================
# 1 — Model-selection rationale
# ===========================================================================


def build_rationale(profile: dict, valuation: ValuationResult) -> ModelRationale:
    sector = profile.get("sector")
    model = valuation.model_used
    label = _MODEL_LABELS.get(model, model)
    reason = valuation.route_reason or label
    headline = f"{sector} — {reason}" if sector else reason
    return ModelRationale(
        sector=sector,
        industry=profile.get("industry"),
        model=model,
        model_label=label,
        confidence=valuation.confidence,
        reason=reason,
        headline=headline,
    )


# ===========================================================================
# 2 — Valuation bridge (one shape per model)
# ===========================================================================


def _finalize_bridge(
    model: str,
    wacc: float | None,
    steps: list[BridgeStep],
    equity_value: float | None,
    shares: float | None,
    reported_vps: float | None,
) -> ValuationBridge:
    """Recompute per-share from equity/shares and check it ties to the model."""
    vps = None
    if _is_num(equity_value) and _is_num(shares) and shares > 0:
        vps = equity_value / shares
    reconciles = False
    err: float | None = None
    if vps is not None and reported_vps is not None:
        # The model floors intrinsic at zero; treat a floored zero as reconciled.
        if reported_vps == 0.0 and vps <= 0.0:
            reconciles, err = True, 0.0
        else:
            err = abs(vps - reported_vps)
            reconciles = _rel_close(vps, reported_vps)
    return ValuationBridge(
        model=model, wacc=wacc, steps=steps, shares=shares,
        value_per_share=vps, reported_value_per_share=reported_vps,
        reconciles=reconciles, reconciliation_error=err,
    )


def build_bridge(
    valuation: ValuationResult, wacc: float | None
) -> ValuationBridge | None:
    """Return the labelled waterfall for whichever model was used."""
    model = valuation.model_used

    if model == "fcff" and valuation.dcf_result is not None:
        d = valuation.dcf_result
        pv_explicit = sum(d.pv_fcff) if d.pv_fcff else 0.0
        minority = d.enterprise_value - d.net_debt - d.equity_value
        steps = [
            BridgeStep("PV of explicit FCFFs", pv_explicit, "component"),
            BridgeStep("PV of terminal value", d.pv_terminal_value, "component"),
            BridgeStep("Enterprise value", d.enterprise_value, "subtotal"),
            BridgeStep("Less: net debt", -d.net_debt, "deduction"),
            BridgeStep("Less: minority interest", -minority, "deduction"),
            BridgeStep("Equity value", d.equity_value, "subtotal"),
            BridgeStep("Shares outstanding", d.shares_outstanding, "divisor"),
            BridgeStep("Intrinsic value / share", d.intrinsic_value_per_share, "result"),
        ]
        return _finalize_bridge(
            model, wacc or d.wacc, steps, d.equity_value,
            d.shares_outstanding, d.intrinsic_value_per_share,
        )

    if model == "ri" and valuation.ri_result is not None:
        r = valuation.ri_result
        bv_equity = r.book_value_per_share * r.shares_outstanding
        pv_ri = sum(r.pv_ri) if r.pv_ri else 0.0
        steps = [
            BridgeStep("Book value of equity", bv_equity, "component"),
            BridgeStep("PV of residual income", pv_ri, "component"),
            BridgeStep("PV of terminal residual income", r.pv_terminal_ri, "component"),
            BridgeStep("Equity value", r.equity_value, "subtotal"),
            BridgeStep("Shares outstanding", r.shares_outstanding, "divisor"),
            BridgeStep("Intrinsic value / share", r.intrinsic_value_per_share, "result"),
        ]
        return _finalize_bridge(
            model, wacc, steps, r.equity_value,
            r.shares_outstanding, r.intrinsic_value_per_share,
        )

    if model == "excess_return" and valuation.excess_return_result is not None:
        e = valuation.excess_return_result
        bv_equity = e.book_value_per_share * e.shares_outstanding
        pv_er = sum(e.pv_excess_return) if e.pv_excess_return else 0.0
        steps = [
            BridgeStep("Book value of equity", bv_equity, "component"),
            BridgeStep("PV of excess returns", pv_er, "component"),
            BridgeStep("PV of terminal excess return", e.pv_terminal_er, "component"),
            BridgeStep("Equity value", e.equity_value, "subtotal"),
            BridgeStep("Shares outstanding", e.shares_outstanding, "divisor"),
            BridgeStep("Intrinsic value / share", e.intrinsic_value_per_share, "result"),
        ]
        return _finalize_bridge(
            model, wacc, steps, e.equity_value,
            e.shares_outstanding, e.intrinsic_value_per_share,
        )

    if model == "financial" and valuation.financial_result is not None:
        f = valuation.financial_result
        steps = [
            BridgeStep("Book value / share", f.book_value_per_share, "component"),
            BridgeStep("Justified P/B multiple", f.justified_pb, "component"),
            BridgeStep("Equity value", f.equity_value, "subtotal"),
            BridgeStep("Shares outstanding", f.shares_outstanding, "divisor"),
            BridgeStep("Intrinsic value / share", f.intrinsic_value_per_share, "result"),
        ]
        return _finalize_bridge(
            model, wacc, steps, f.equity_value,
            f.shares_outstanding, f.intrinsic_value_per_share,
        )

    if model == "sotp" and valuation.sotp_result is not None:
        s = valuation.sotp_result
        steps = [
            BridgeStep(f"Segment EV: {seg.name}", seg.segment_ev, "component")
            for seg in s.segments
        ]
        steps += [
            BridgeStep("Total enterprise value", s.total_ev, "subtotal"),
            BridgeStep("Less: net debt", -s.net_debt, "deduction"),
            BridgeStep("Equity value", s.equity_value, "subtotal"),
            BridgeStep("Shares outstanding", s.shares_outstanding, "divisor"),
            BridgeStep("Intrinsic value / share", s.intrinsic_value_per_share, "result"),
        ]
        return _finalize_bridge(
            model, wacc, steps, s.equity_value,
            s.shares_outstanding, s.intrinsic_value_per_share,
        )

    return None


# ===========================================================================
# 3 — Plausibility guardrails
# ===========================================================================


def implied_terminal_ev_ebitda(
    valuation: ValuationResult, terminal_ebitda: float | None
) -> float | None:
    """Implied exit EV/EBITDA backed out of the perpetuity terminal value."""
    d = valuation.dcf_result
    if d is None or not _is_num(terminal_ebitda) or terminal_ebitda <= 0:
        return None
    return d.terminal_value_nominal / terminal_ebitda


def run_guardrails(
    valuation: ValuationResult,
    profile: dict,
    config: AppConfig,
    *,
    base_ebitda: float | None = None,
) -> list[Diagnostic]:
    """Flag — never silently emit — a suspect valuation.  Returns fired flags."""
    g = config.guardrails
    diags: list[Diagnostic] = []

    intrinsic = valuation.intrinsic_value
    price = valuation.current_price or profile.get("current_price")

    # (a) negative / non-finite headline values → critical
    bad_vals: list[tuple[str, float | None]] = [("intrinsic value/share", intrinsic)]
    d = valuation.dcf_result
    if d is not None:
        bad_vals += [("enterprise value", d.enterprise_value), ("equity value", d.equity_value)]
    for name, v in bad_vals:
        if v is not None and (not math.isfinite(v) or v < 0):
            diags.append(Diagnostic(
                code="non_finite_or_negative", severity="critical",
                message=f"{name} is {'non-finite' if (v is None or not math.isfinite(v)) else 'negative'} "
                        f"({v}) — not a valid target",
                value=v,
            ))

    # (b) intrinsic / price outside [low, high] → flag
    if _is_num(intrinsic) and _is_num(price) and price > 0 and intrinsic > 0:
        ratio = intrinsic / price
        if ratio < g.value_to_price_low or ratio > g.value_to_price_high:
            diags.append(Diagnostic(
                code="value_vs_price", severity="warn",
                message=f"Intrinsic value is {ratio:.2f}× the market price — outside the "
                        f"{g.value_to_price_low:g}×–{g.value_to_price_high:g}× plausibility band",
                value=ratio,
                threshold=g.value_to_price_high if ratio > g.value_to_price_high else g.value_to_price_low,
            ))

    # (c) terminal value as % of EV > max → flag (FCFF only)
    if d is not None and _is_num(d.enterprise_value) and d.enterprise_value > 0:
        tv_share = d.pv_terminal_value / d.enterprise_value
        if tv_share > g.terminal_value_max_share:
            diags.append(Diagnostic(
                code="terminal_value_share", severity="warn",
                message=f"Terminal value is {tv_share:.0%} of EV (> {g.terminal_value_max_share:.0%}) — "
                        "valuation is mostly a terminal-value bet, not an explicit-forecast result",
                value=tv_share, threshold=g.terminal_value_max_share,
            ))

    # (d) implied exit multiple far out of line (FCFF)
    if d is not None and _is_num(base_ebitda) and base_ebitda > 0:
        horizon = len(d.projected_fcff) if d.projected_fcff else 0
        terminal_ebitda = base_ebitda * (1.0 + d.terminal_growth) ** horizon
        implied = implied_terminal_ev_ebitda(valuation, terminal_ebitda)
        if implied is not None and (
            implied < g.implied_exit_multiple_low or implied > g.implied_exit_multiple_high
        ):
            diags.append(Diagnostic(
                code="implied_exit_multiple", severity="warn",
                message=f"Implied terminal EV/EBITDA of {implied:.1f}× is outside the sector-sane "
                        f"{g.implied_exit_multiple_low:g}×–{g.implied_exit_multiple_high:g}× band",
                value=implied,
                threshold=g.implied_exit_multiple_high if implied > g.implied_exit_multiple_high
                else g.implied_exit_multiple_low,
            ))

    # (e) two-stage bank residual income: terminal-value share + implied P/TBV
    # (financial only) — an over-aggressive two-stage result still flags.
    fin = valuation.financial_result
    if fin is not None and getattr(fin, "valuation_method", None) == "two_stage_ri":
        tvs = fin.terminal_value_share
        if _is_num(tvs) and tvs > g.terminal_value_max_share:
            diags.append(Diagnostic(
                code="terminal_value_share", severity="warn",
                message=f"Terminal value is {tvs:.0%} of intrinsic (> {g.terminal_value_max_share:.0%}) — "
                        "the two-stage bank value is mostly a terminal-value bet",
                value=tvs, threshold=g.terminal_value_max_share,
            ))
        exit_pb = fin.implied_exit_ptbv
        if _is_num(exit_pb) and exit_pb > g.implied_exit_ptbv_high:
            diags.append(Diagnostic(
                code="implied_exit_ptbv", severity="warn",
                message=f"Implied exit P/TBV of {exit_pb:.1f}× exceeds the sector-sane "
                        f"{g.implied_exit_ptbv_high:g}× ceiling — terminal franchise value too aggressive",
                value=exit_pb, threshold=g.implied_exit_ptbv_high,
            ))
        impl_pb = fin.implied_ptbv
        if _is_num(impl_pb) and impl_pb > g.implied_exit_ptbv_high:
            diags.append(Diagnostic(
                code="implied_ptbv", severity="warn",
                message=f"Implied P/TBV of {impl_pb:.1f}× exceeds the sector-sane "
                        f"{g.implied_exit_ptbv_high:g}× ceiling",
                value=impl_pb, threshold=g.implied_exit_ptbv_high,
            ))

    return diags


# ===========================================================================
# Orchestration
# ===========================================================================


def explain_valuation(
    profile: dict,
    valuation: ValuationResult,
    cost_of_capital: CostOfCapital | None,
    config: AppConfig,
    *,
    base_ebitda: float | None = None,
) -> ValuationExplainability:
    """Assemble rationale + bridge + guardrail diagnostics for the chosen model."""
    wacc = cost_of_capital.wacc if cost_of_capital is not None else None
    rationale = build_rationale(profile, valuation)
    bridge = build_bridge(valuation, wacc)
    diagnostics = run_guardrails(valuation, profile, config, base_ebitda=base_ebitda)

    warnings: list[str] = []
    if bridge is not None and not bridge.reconciles:
        warnings.append(
            f"Valuation bridge does not reconcile to the reported per-share value "
            f"(error {bridge.reconciliation_error})"
        )

    return ValuationExplainability(
        rationale=rationale,
        bridge=bridge,
        diagnostics=diagnostics,
        has_critical=any(d.severity == "critical" for d in diagnostics),
        warnings=warnings,
    )
