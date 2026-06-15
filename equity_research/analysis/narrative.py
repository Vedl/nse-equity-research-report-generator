"""Deterministic equity-research narrative — "the why" (Phase 2C-iii).

This module composes a structured ER thesis as conditional prose **purely from
the structured payload** it is handed — the same already-computed numbers the
rest of the report renders (router rationale, valuation bridge, tornado ranking,
sensitivity grid, cost-of-capital build-up, earnings-quality verdict, guardrail
flags, and the guardrail-aware recommendation).

Design goals — reliability over fluency:

  * **No external API, no key, no cost.**  It is a pure function of the payload;
    it runs identically offline and is fully reproducible.
  * **It cannot cite a number that was not computed.**  Every numeral printed is
    either a payload value run through one of the shared formatters in
    ``_FORMATTERS`` or a numeral lifted verbatim from a payload string (a router
    rationale, a guardrail message, an earnings-quality reason).  The narrative
    never performs fresh arithmetic and prints the result.
  * **Guardrail honesty.**  When the recommendation is flagged, the thesis states
    plainly that the directional call is withheld and names the limitation from
    the guardrail flags — it never asserts a confident target.

The recommendation logic (margin-of-safety, quality overlay, guardrail override)
lives in ``recommendation.py`` and is unchanged; this module only narrates it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ===========================================================================
# Number formatting — the ONLY way a numeral reaches the prose
# ===========================================================================
#
# Every formatter takes a single payload value and returns a display string (or
# ``None`` for a non-finite/absent input).  The accompanying tests rebuild the
# set of permissible numerals by applying exactly these formatters to every
# number in the payload, so the generator is structurally barred from inventing
# a figure: a numeral that no formatter-of-a-payload-value can produce, and that
# appears in no payload string, cannot legitimately appear in the prose.


def _finite(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _fmt_money(v: object) -> str | None:
    """₹ per-share / value, rounded to the rupee with thousands separators."""
    if not _finite(v):
        return None
    sign = "-" if v < 0 else ""
    return f"{sign}₹{abs(round(v)):,}"


def _fmt_pct0(v: object) -> str | None:
    """Whole-percent — for upside/downside and margins of safety."""
    if not _finite(v):
        return None
    return f"{round(v * 100)}%"


def _fmt_pct1(v: object) -> str | None:
    """One-decimal percent — for rates (WACC, Ke, rf, ERP, terminal g)."""
    if not _finite(v):
        return None
    return f"{v * 100:.1f}%"


def _fmt_mult(v: object) -> str | None:
    """Multiple, e.g. a justified P/B — two decimals with a × suffix."""
    if not _finite(v):
        return None
    return f"{v:.2f}×"


def _fmt_num2(v: object) -> str | None:
    """Plain two-decimal number — for a beta."""
    if not _finite(v):
        return None
    return f"{v:.2f}"


def _fmt_int(v: object) -> str | None:
    if not _finite(v):
        return None
    return f"{int(round(v))}"


# The canonical formatter set.  Tests import this to rebuild the allowed numerals.
_FORMATTERS = (_fmt_money, _fmt_pct0, _fmt_pct1, _fmt_mult, _fmt_num2, _fmt_int)

# A token that looks like a number, tolerating a leading minus, a ₹ prefix and
# embedded thousands separators.  Callers normalise the unicode minus first.
_NUMBER_TOKEN = re.compile(r"-?₹?\d[\d,]*(?:\.\d+)?")


def _num_core(token: str) -> str:
    """Reduce a formatted token to its bare numeric core for comparison.

    ``"₹1,688" -> "1688"``, ``"60%" -> "60"``, ``"0.73×" -> "0.73"``,
    ``"-₹5" -> "-5"``.  Returns ``""`` when there is no number.
    """
    t = (
        token.replace("−", "-")  # unicode MINUS SIGN → ASCII
        .replace(",", "")
        .replace("₹", "")
        .replace("%", "")
        .replace("×", "")
        .strip()
    )
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return m.group(0) if m else ""


# ===========================================================================
# Structured output
# ===========================================================================


@dataclass
class Narrative:
    """A structured ER thesis, every numeral derived from the payload."""

    one_line_view: str
    approach: str
    what_drives_value: str
    what_it_hinges_on: str
    earnings_quality: str
    risks: str
    what_would_change_the_view: str
    thesis: str                         # the full note, all sections composed
    generator: str = "deterministic-template-v1"
    warnings: list[str] = field(default_factory=list)


# ===========================================================================
# Section builders — each sentence is conditional on, and derived from, payload
# ===========================================================================


def _direction_word(upside: object) -> str | None:
    if not _finite(upside):
        return None
    if upside > 0.005:
        return "upside"
    if upside < -0.005:
        return "downside"
    return "broadly in line"


def _one_line_view(company: dict, rec: dict, val: dict) -> str:
    ticker = company.get("ticker") or company.get("name") or "The company"
    label = val.get("model_label") or "the valuation model"
    iv = _fmt_money(val.get("intrinsic_value_per_share"))
    px = _fmt_money(val.get("current_price"))
    conv = rec.get("conviction") or "low"
    mag = _fmt_pct0(abs(rec["upside_pct"])) if _finite(rec.get("upside_pct")) else None
    direction = _direction_word(rec.get("upside_pct"))

    vs_price = f" against a market price of {px}" if px else ""
    iv_clause = f"{label} marks an intrinsic value of {iv}{vs_price}" if iv else (
        f"{label} could not mark a usable intrinsic value"
    )
    call_clause = (
        f"; the blended call implies {mag} {direction}"
        if (mag and direction) else ""
    )

    if rec.get("flagged"):
        return (
            f"{ticker} — directional call withheld; valuation flagged. "
            f"{iv_clause}{call_clause}, but a plausibility guardrail fired, so this "
            f"is treated as indicative at {conv} confidence, not a call."
        )

    action = rec.get("action") or "HOLD"
    mos = _fmt_pct0(rec.get("required_margin_of_safety"))
    verdict = (rec.get("quality_verdict") or "Unrated")
    mos_clause = (
        f" The call clears the {mos} margin of safety required at {verdict} earnings quality."
        if (action in ("BUY", "SELL") and mos) else ""
    )
    return (
        f"{ticker} — {action} ({conv} conviction). {iv_clause}{call_clause}.{mos_clause}"
    )


def _approach(val: dict, coc: dict, discount_driver: str | None) -> str:
    rationale = (val.get("model_rationale") or "").strip()
    parts: list[str] = []
    if rationale:
        parts.append(f"Approach — {rationale}")
    else:
        parts.append("Approach — model rationale unavailable.")

    # Which discount input is meaningful is set by the routed model.
    rate_val, rate_name = None, None
    if discount_driver == "Ke":
        rate_val, rate_name = coc.get("cost_of_equity"), "cost of equity"
    elif discount_driver == "WACC":
        rate_val, rate_name = coc.get("wacc"), "WACC"
    rate = _fmt_pct1(rate_val)

    # Cost-of-capital build-up (rf + ERP + beta), all from the payload.
    rf = _fmt_pct1(coc.get("risk_free_rate"))
    erp = _fmt_pct1(coc.get("equity_risk_premium"))
    beta = _fmt_num2(coc.get("beta_used"))
    if rate and rate_name:
        build = ""
        if rf and erp and beta:
            build = (
                f", built up from a {rf} risk-free rate, a {erp} equity risk premium "
                f"and a beta of {beta}"
            )
        parts.append(f"Cash flows are discounted at a {rate} {rate_name}{build}.")

    # The valuation bridge, surfaced as its labelled waterfall.
    bridge = val.get("bridge") or []
    labels = [s.get("label") for s in bridge if s.get("label")]
    iv = _fmt_money(val.get("intrinsic_value_per_share"))
    if len(labels) >= 2 and iv:
        chain = " → ".join(labels[:-1])
        parts.append(f"The bridge runs {chain}, arriving at an intrinsic value of {iv} per share.")
    return " ".join(parts)


def _what_drives_value(tornado: list[dict]) -> str:
    drivers = [t.get("driver") for t in tornado if t.get("driver")]
    if not drivers:
        return (
            "What drives value — a ranked driver sensitivity is not available for "
            "this model."
        )
    if len(drivers) == 1:
        ranking = f"is driven almost entirely by {drivers[0]}"
    elif len(drivers) == 2:
        ranking = f"is most sensitive to {drivers[0]}, then {drivers[1]}"
    else:
        ranking = (
            f"is most sensitive to {drivers[0]}, then {drivers[1]}, then {drivers[2]}"
        )
    top = tornado[0]
    swing = _fmt_money(top.get("swing"))
    tail = (
        f" Flexing {top.get('driver')} across its range moves intrinsic value by "
        f"about {swing} per share."
        if swing else ""
    )
    return f"What drives value — the valuation {ranking}.{tail}"


def _what_it_hinges_on(sensitivity: dict | None, val: dict, note: str | None) -> str:
    if not sensitivity or not sensitivity.get("values"):
        if note:
            return f"What it hinges on — {note}"
        return "What it hinges on — a two-way sensitivity grid is not available for this model."

    rows = sensitivity.get("row_values") or []
    cols = sensitivity.get("col_values") or []
    grid = sensitivity.get("values") or []
    row_driver = sensitivity.get("row_driver") or "the discount rate"
    col_driver = (sensitivity.get("col_driver") or "terminal growth").lower()

    # Rows ascend with the discount input; cols ascend with terminal growth.
    # Lowest value: high discount + low growth; highest: low discount + high growth.
    low_corner = _fmt_money(grid[-1][0]) if grid and grid[-1] else None
    high_corner = _fmt_money(grid[0][-1]) if grid and grid[0] else None
    r_lo, r_hi = _fmt_pct1(rows[0]) if rows else None, _fmt_pct1(rows[-1]) if rows else None
    c_lo, c_hi = _fmt_pct1(cols[0]) if cols else None, _fmt_pct1(cols[-1]) if cols else None
    px = _fmt_money(val.get("current_price"))

    if not (low_corner and high_corner):
        return "What it hinges on — sensitivity grid corners are unavailable."

    band = ""
    if r_lo and r_hi and c_lo and c_hi:
        band = (
            f" across a {row_driver} band of {r_lo}–{r_hi} and {col_driver} of "
            f"{c_lo}–{c_hi}"
        )
    vs_price = f" — against today's {px}" if px else ""
    return (
        f"What it hinges on —{band} intrinsic value ranges from {low_corner} "
        f"(high {row_driver}, low growth) to {high_corner} (low {row_driver}, "
        f"high growth){vs_price}."
    )


_FLAG_RANK = {"red": 0, "amber": 1, "green": 2}


def _earnings_quality(eq: dict) -> str:
    verdict = eq.get("verdict") or "Unrated"
    comps = list(eq.get("components") or [])
    if not comps:
        return f"Earnings quality — screens {verdict}; no component detail available."

    comps.sort(key=lambda c: _FLAG_RANK.get((c.get("flag") or "").lower(), 3))
    concerns = [c for c in comps if (c.get("flag") or "").lower() != "green"]
    clean = [c for c in comps if (c.get("flag") or "").lower() == "green"]

    def _fmt(c: dict) -> str:
        name, flag, reason = c.get("name"), c.get("flag"), c.get("reason")
        base = f"{name} ({flag})"
        return f"{base}: {reason}" if reason else base

    if concerns:
        body = "; ".join(_fmt(c) for c in concerns)
        clean_tail = " The remaining components screen clean." if clean else ""
        return f"Earnings quality — screens {verdict}. Watch items: {body}.{clean_tail}"
    return f"Earnings quality — screens {verdict}; all components screen clean."


def _risks(guardrails: list[dict], eq: dict) -> str:
    items: list[str] = []
    for g in guardrails or []:
        msg = (g.get("message") or "").strip()
        sev = (g.get("severity") or "warn")
        if msg:
            items.append(f"[{sev}] {msg}")
    for c in eq.get("components") or []:
        flag = (c.get("flag") or "").lower()
        if flag in ("red", "amber"):
            reason = c.get("reason")
            tail = f" — {reason}" if reason else ""
            items.append(f"earnings-quality {flag} on {c.get('name')}{tail}")
    if not items:
        verdict = eq.get("verdict") or "Unrated"
        return (
            "Risks & caveats — no plausibility guardrail fired and earnings quality "
            f"screens {verdict} with no red or amber flags."
        )
    return "Risks & caveats — " + "; ".join(items) + "."


def _what_would_change_the_view(
    rec: dict, val: dict, tornado: list[dict]
) -> str:
    model = (val.get("model") or "").lower()
    top_driver = tornado[0].get("driver") if tornado else None
    verdict = rec.get("quality_verdict") or "Unrated"

    if rec.get("flagged"):
        if model in ("financial", "ri", "excess_return"):
            return (
                "What would change the view — a normalized forward ROE, replacing the "
                "merger-distorted trailing figure, would resolve the guardrail flag and "
                "could move the call off Hold."
            )
        if model == "fcff":
            extra = f", notably {top_driver}," if top_driver else ""
            return (
                "What would change the view — resolving the inputs that tripped the "
                f"plausibility guardrail{extra} would restore a confident directional call."
            )
        return (
            "What would change the view — clearing the plausibility flag would restore "
            "a directional call."
        )

    action = rec.get("action") or "HOLD"
    driver = top_driver or "the primary discount input"
    if action == "BUY":
        return (
            f"What would change the view — the thesis weakens if {driver} re-rates "
            f"against it, or if earnings quality slips below {verdict}."
        )
    if action == "SELL":
        return (
            f"What would change the view — the view turns more constructive if {driver} "
            f"improves, or on an earnings-quality upgrade above {verdict}."
        )
    mos = _fmt_pct0(rec.get("required_margin_of_safety"))
    band = f" beyond the {mos} margin of safety" if mos else ""
    return (
        f"What would change the view — a move{band}, driven by {driver}, would trigger "
        "a directional call."
    )


# ===========================================================================
# Public API
# ===========================================================================


def generate_narrative(payload: dict) -> Narrative:
    """Compose the structured ER thesis from the payload.

    Pure and deterministic: no network, no API key, no randomness.  Always
    returns a ``Narrative`` — missing sub-sections degrade to an explicit
    "not available" sentence rather than failing.
    """
    company = payload.get("company") or {}
    rec = payload.get("recommendation") or {}
    val = payload.get("valuation") or {}
    coc = payload.get("wacc_build_up") or {}
    eq = payload.get("earnings_quality") or {}
    guardrails = payload.get("guardrail_flags") or []
    tornado = payload.get("tornado") or []
    sensitivity = payload.get("sensitivity")
    scenarios_note = payload.get("scenarios_note")
    discount_driver = payload.get("discount_driver")

    one_line = _one_line_view(company, rec, val)
    approach = _approach(val, coc, discount_driver)
    drives = _what_drives_value(tornado)
    hinges = _what_it_hinges_on(sensitivity, val, scenarios_note)
    quality = _earnings_quality(eq)
    risks = _risks(guardrails, eq)
    change = _what_would_change_the_view(rec, val, tornado)

    thesis = "\n\n".join([one_line, approach, drives, hinges, quality, risks, change])

    return Narrative(
        one_line_view=one_line,
        approach=approach,
        what_drives_value=drives,
        what_it_hinges_on=hinges,
        earnings_quality=quality,
        risks=risks,
        what_would_change_the_view=change,
        thesis=thesis,
    )


def build_narrative_payload(
    *,
    company: dict,
    recommendation,
    quality_verdict: str,
    quality_components: list[dict],
    valuation_rationale: str,
    bridge: list[dict],
    wacc_build_up: dict,
    guardrail_flags: list[dict],
    intrinsic_value: float | None,
    current_price: float | None,
    model: str | None = None,
    model_label: str | None = None,
    tornado: list[dict] | None = None,
    sensitivity: dict | None = None,
    discount_driver: str | None = None,
    scenarios_note: str | None = None,
    broker: object | None = None,
    news: object | None = None,
) -> dict:
    """Assemble the computed-numbers-only payload handed to the generator.

    Broker/news are included only when present — never stubbed in — so the
    narrative has nothing to fabricate from.
    """
    payload: dict = {
        "company": company,
        "recommendation": {
            "action": recommendation.action,
            "conviction": recommendation.conviction,
            "flagged": recommendation.flagged,
            "upside_pct": recommendation.upside_pct,
            "required_margin_of_safety": recommendation.required_mos,
            "quality_verdict": recommendation.quality_verdict,
            "reason": recommendation.reason,
        },
        "earnings_quality": {
            "verdict": quality_verdict,
            "components": quality_components,
        },
        "valuation": {
            "model": model,
            "model_label": model_label,
            "model_rationale": valuation_rationale,
            "intrinsic_value_per_share": intrinsic_value,
            "current_price": current_price,
            "bridge": bridge,
        },
        "wacc_build_up": wacc_build_up,
        "guardrail_flags": guardrail_flags,
        "tornado": tornado or [],
        "sensitivity": sensitivity,
        "discount_driver": discount_driver,
        "scenarios_note": scenarios_note,
        "overlay_notes": recommendation.overlay_notes,
    }
    if broker is not None:
        payload["broker_consensus"] = broker
    if news is not None:
        payload["news_sentiment"] = news
    return payload
