"""Phase 2C-iii — deterministic narrative tests.

The narrative is a pure, template-based function of the structured payload: no
external API, no key, no cost.  The contract these tests pin down:

  * **No invented numerals.**  Every number in the prose is reproducible by
    applying the module's own formatters to a payload value, or already appears
    inside a payload string.
  * **One coherent anchor.**  The headline is the blended *target* the upside is
    computed from, with the primary intrinsic and peer median shown as its
    components — so target / components / price / % all reconcile through one
    stated number.  The stated % equals (target − price)/price within rounding.
  * **Guardrail honesty.**  A flagged name states the withheld call plainly and
    names the limitation; never a confident target.
  * **Determinism / offline.**  Byte-identical output, no network, no key.
"""

from __future__ import annotations

import math
import re
import socket

from equity_research.analysis.narrative import (
    _FORMATTERS,
    _num_core,
    build_narrative_payload,
    generate_narrative,
)
from equity_research.analysis.recommendation import decide_recommendation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RATIONALE = "Technology — FCFF discounted cash flow chosen for a cash-generative, low-leverage name"

_BRIDGE = [
    {"label": "PV of explicit FCFFs", "value": 410000.0},
    {"label": "PV of terminal value", "value": 980000.0},
    {"label": "Enterprise value", "value": 1390000.0},
    {"label": "Less: net debt", "value": -120000.0},
    {"label": "Equity value", "value": 1270000.0},
    {"label": "Shares outstanding", "value": 752.0},
    {"label": "Intrinsic value / share", "value": 1695.0},
]

_WACC_BUILD_UP = {
    "wacc": 0.125, "cost_of_equity": 0.126, "beta_used": 0.95,
    "risk_free_rate": 0.071, "equity_risk_premium": 0.055,
}

# Pre-ranked by |swing| desc, as the pipeline delivers it.
_TORNADO = [
    {"driver": "WACC", "low_input": 0.140, "high_input": 0.110,
     "low_value": 1500.0, "high_value": 1900.0, "base_value": 1695.0, "swing": 400.0},
    {"driver": "Revenue CAGR", "low_input": 0.06, "high_input": 0.10,
     "low_value": 1600.0, "high_value": 1780.0, "base_value": 1695.0, "swing": 180.0},
    {"driver": "Terminal g", "low_input": 0.03, "high_input": 0.05,
     "low_value": 1620.0, "high_value": 1760.0, "base_value": 1695.0, "swing": 140.0},
]


def _grid(row_driver: str = "WACC") -> dict:
    rows = [0.110, 0.1175, 0.125, 0.1325, 0.140]
    cols = [0.030, 0.035, 0.040, 0.045, 0.050]
    values = [[1700.0 + (4 - i) * 100 + j * 50 for j in range(5)] for i in range(5)]
    return {
        "row_driver": row_driver, "col_driver": "Terminal growth",
        "row_values": rows, "col_values": cols, "values": values,
        "base_row": 0.125, "base_col": 0.040,
    }


_CLEAN_COMPONENTS = [
    {"name": "Sloan accruals", "flag": "green", "reason": "low and stable"},
    {"name": "Beneish M-score", "flag": "green", "reason": "no manipulation flag"},
]

_LIMIT_MSG = ("Intrinsic value is 0.48× the market price — outside the 0.5×–2× "
              "plausibility band")


def _make(
    *,
    price: float,
    primary: float,
    secondary: float | None,
    target: float,
    quality: str,
    flagged: bool,
    ticker: str = "TCS.NS",
    model: str = "fcff",
    model_label: str = "FCFF discounted cash flow",
    discount_driver: str = "WACC",
    components=None,
    rationale: str = _RATIONALE,
    guardrails=(),
    broker=None,
    news=None,
):
    """Build a coherent (rec, upside, payload) triple.

    ``upside`` is derived from target/price exactly as the pipeline does
    (``final_value / price − 1``) and fed to the real ``decide_recommendation``,
    so the recommendation and the shown numbers always reconcile.
    """
    upside = target / price - 1.0
    rec = decide_recommendation(
        upside_pct=upside, quality_verdict=quality, guardrail_fired=flagged
    )
    payload = build_narrative_payload(
        company={"name": ticker.split(".")[0], "ticker": ticker, "sector": "Technology"},
        recommendation=rec,
        quality_verdict=quality,
        quality_components=list(_CLEAN_COMPONENTS if components is None else components),
        valuation_rationale=rationale,
        bridge=list(_BRIDGE),
        wacc_build_up=dict(_WACC_BUILD_UP),
        guardrail_flags=list(guardrails),
        intrinsic_value=primary,
        current_price=price,
        target=target,
        secondary_value=secondary,
        secondary_label="Peer-multiple median",
        model=model,
        model_label=model_label,
        tornado=list(_TORNADO),
        sensitivity=_grid("Ke" if discount_driver == "Ke" else "WACC"),
        discount_driver=discount_driver,
        broker=broker,
        news=news,
    )
    return rec, upside, payload


def _clean():
    # Green quality, target above price → confident BUY.  primary < price but
    # the peer median lifts the blend above price — exactly the divergence the
    # single-anchor headline must reconcile.
    return _make(price=2161.1, primary=1695.0, secondary=3200.0, target=2850.0,
                 quality="Green", flagged=False)


def _flagged():
    # Would read SELL, but a guardrail fired → HOLD, low confidence, withheld.
    return _make(price=777.0, primary=371.0, secondary=661.0, target=489.0,
                 quality="Amber", flagged=True, ticker="HDFCBANK.NS",
                 model="financial", model_label="Justified P/B (financial)",
                 discount_driver="Ke",
                 guardrails=[{"code": "value_vs_price", "severity": "warn", "message": _LIMIT_MSG}])


# ---------------------------------------------------------------------------
# Numeral-provenance machinery (mirrors the module's formatter contract)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"-?₹?\d[\d,]*(?:\.\d+)?")


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def _allowed_cores(payload: dict) -> set[str]:
    cores: set[str] = set()
    for leaf in _walk(payload):
        if isinstance(leaf, bool):
            continue
        if isinstance(leaf, (int, float)):
            if not math.isfinite(leaf):
                continue
            for fmt in _FORMATTERS:
                for cand in (leaf, abs(leaf)):
                    s = fmt(cand)
                    if s:
                        cores.add(_num_core(s))
            cores.add(_num_core(str(leaf)))
        elif isinstance(leaf, str):
            for tok in _TOKEN.findall(leaf.replace("−", "-")):
                cores.add(_num_core(tok))
    cores.discard("")
    return cores


def _text_cores(text: str) -> set[str]:
    return {_num_core(tok) for tok in _TOKEN.findall(text.replace("−", "-"))} - {""}


def _moneys(text: str) -> list[int]:
    return [int(m.replace(",", "")) for m in re.findall(r"₹([\d,]+)", text)]


def _signed_pct(text: str) -> int | None:
    """The directional headline %: ``"37% below"`` → −37, ``"32% above"`` → +32."""
    m = re.search(r"(\d+)%\s+(below|above)", text)
    if not m:
        return None
    return -int(m.group(1)) if m.group(2) == "below" else int(m.group(1))


# ---------------------------------------------------------------------------
# Contract 1 — no numeral absent from the payload
# ---------------------------------------------------------------------------


def test_clean_narrative_invents_no_numeral():
    _, _, p = _clean()
    nar = generate_narrative(p)
    missing = _text_cores(nar.thesis) - _allowed_cores(p)
    assert not missing, f"narrative cites numerals absent from payload: {sorted(missing)}"


def test_flagged_narrative_invents_no_numeral():
    _, _, p = _flagged()
    nar = generate_narrative(p)
    missing = _text_cores(nar.thesis) - _allowed_cores(p)
    assert not missing, f"narrative cites numerals absent from payload: {sorted(missing)}"


def test_fabricated_numeral_would_be_caught():
    """Guard the guard: a numeral not in the payload must register as missing."""
    _, _, p = _clean()
    assert "424242" not in _allowed_cores(p)
    assert _text_cores("a target of ₹424,242") - _allowed_cores(p) == {"424242"}


# ---------------------------------------------------------------------------
# Contract 2 — single coherent anchor: target / components / price / % reconcile
# ---------------------------------------------------------------------------


def test_stated_pct_reconciles_with_shown_target_and_price():
    for builder in (_clean, _flagged):
        _, _, p = builder()
        line = generate_narrative(p).one_line_view
        moneys = _moneys(line)
        target, price = moneys[0], moneys[-1]   # headline anchor; price is last
        stated = _signed_pct(line)
        assert stated is not None, line
        recomputed = round((target - price) / price * 100)
        assert abs(stated - recomputed) <= 1, (
            f"stated {stated}% vs (target {target} − price {price})/price "
            f"= {recomputed}% in: {line}"
        )


def test_shown_components_are_the_actual_blend_inputs():
    _, _, p = _flagged()
    val = p["valuation"]
    line = generate_narrative(p).one_line_view
    from equity_research.analysis.narrative import _fmt_money
    # headline anchor is the blended target
    assert _fmt_money(val["target"]) in line
    # primary intrinsic and peer median are shown as its components
    assert _fmt_money(val["intrinsic_value_per_share"]) in line
    assert _fmt_money(val["secondary_value"]) in line
    assert val["secondary_label"] in line
    assert val["model_label"] in line


def test_anchor_is_target_not_primary_intrinsic():
    # The bug being fixed: primary intrinsic shown beside a blend-derived %.
    _, _, p = _flagged()
    line = generate_narrative(p).one_line_view
    # The first ₹ figure (the anchor) is the target, not the primary intrinsic.
    assert _moneys(line)[0] == round(p["valuation"]["target"])
    assert _moneys(line)[0] != round(p["valuation"]["intrinsic_value_per_share"])


# ---------------------------------------------------------------------------
# Contract 3 — flagged names: withheld call + named limitation
# ---------------------------------------------------------------------------


def test_flagged_states_withheld_and_names_limitation():
    _, _, p = _flagged()
    nar = generate_narrative(p)
    lower = nar.thesis.lower()
    assert "withheld" in lower
    assert "flagged" in lower
    assert "not a call" in lower
    assert _LIMIT_MSG in nar.risks          # named verbatim, not softened
    assert _LIMIT_MSG in nar.thesis
    assert "normalized forward roe" in lower  # remedy conditional on model + flag


def test_clean_name_states_a_confident_call():
    _, _, p = _clean()
    nar = generate_narrative(p)
    assert "BUY" in nar.one_line_view
    assert "withheld" not in nar.thesis.lower()
    assert "high conviction" in nar.one_line_view.lower()


# ---------------------------------------------------------------------------
# Contract 4 — deterministic, offline, no key
# ---------------------------------------------------------------------------


def test_generates_identically_offline_without_network_or_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _no_network(*_a, **_k):
        raise AssertionError("narrative must not open a network connection")

    monkeypatch.setattr(socket, "socket", _no_network)

    _, _, p = _clean()
    first = generate_narrative(p)
    second = generate_narrative(p)
    assert first == second
    assert first.generator == "deterministic-template-v1"
    assert first.thesis.strip()


# ---------------------------------------------------------------------------
# Section provenance — derived from the right payload field
# ---------------------------------------------------------------------------


def test_approach_surfaces_router_rationale_verbatim():
    _, _, p = _clean()
    assert _RATIONALE in generate_narrative(p).approach


def test_what_drives_value_follows_tornado_ranking():
    _, _, p = _clean()
    drives = generate_narrative(p).what_drives_value
    assert "most sensitive to WACC, then Revenue CAGR, then Terminal g" in drives


def test_what_it_hinges_on_uses_grid_corners():
    _, _, p = _clean()
    hinges = generate_narrative(p).what_it_hinges_on
    assert "₹1,700" in hinges   # high WACC, low growth
    assert "₹2,300" in hinges   # low WACC, high growth


def test_earnings_quality_reflects_verdict_and_components():
    comps = [
        {"name": "Sloan accruals", "flag": "amber", "reason": "rising accrual ratio"},
        {"name": "Beneish M-score", "flag": "green", "reason": "no manipulation flag"},
    ]
    _, _, p = _make(price=2000.0, primary=1800.0, secondary=2200.0, target=2100.0,
                    quality="Amber", flagged=False, components=comps)
    eq = generate_narrative(p).earnings_quality
    assert "screens Amber" in eq
    assert "Sloan accruals (amber): rising accrual ratio" in eq


# ---------------------------------------------------------------------------
# Payload hygiene — broker/news never fabricated
# ---------------------------------------------------------------------------


def test_payload_omits_broker_news_when_absent():
    _, _, p = _clean()
    assert "broker_consensus" not in p
    assert "news_sentiment" not in p
    assert any("pending" in n.lower() for n in p["overlay_notes"])


def test_payload_includes_broker_news_when_present():
    _, _, p = _make(price=2161.1, primary=1695.0, secondary=3200.0, target=2850.0,
                    quality="Green", flagged=False,
                    broker={"rating": "Buy", "count": 30}, news={"sentiment": 0.2})
    assert p["broker_consensus"] == {"rating": "Buy", "count": 30}
    assert p["news_sentiment"] == {"sentiment": 0.2}
