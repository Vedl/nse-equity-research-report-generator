"""Phase 2C-iii — deterministic narrative tests.

The narrative is now a pure, template-based function of the structured payload:
no external API, no key, no cost.  The contract these tests pin down:

  * **No invented numerals.**  Every number in the prose must be reproducible by
    applying the module's own formatters to a payload value, or must already
    appear inside a payload string.  A figure that satisfies neither is a
    fabrication and fails the suite.
  * **Guardrail honesty.**  A flagged name's narrative must state that the
    directional call is withheld and must name the limitation from the guardrail.
  * **Determinism / offline.**  It produces byte-identical output across calls
    with no network access and no ANTHROPIC_API_KEY.
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
    {"label": "Intrinsic value / share", "value": 1688.9},
]

_WACC_BUILD_UP = {
    "wacc": 0.125,
    "cost_of_equity": 0.126,
    "beta_used": 0.95,
    "risk_free_rate": 0.071,
    "equity_risk_premium": 0.055,
}

# Pre-ranked by |swing| desc, as the pipeline delivers it.
_TORNADO = [
    {"driver": "WACC", "low_input": 0.140, "high_input": 0.110,
     "low_value": 1500.0, "high_value": 1900.0, "base_value": 1688.9, "swing": 400.0},
    {"driver": "Revenue CAGR", "low_input": 0.06, "high_input": 0.10,
     "low_value": 1600.0, "high_value": 1780.0, "base_value": 1688.9, "swing": 180.0},
    {"driver": "Terminal g", "low_input": 0.03, "high_input": 0.05,
     "low_value": 1620.0, "high_value": 1760.0, "base_value": 1688.9, "swing": 140.0},
]


def _grid(row_driver: str = "WACC") -> dict:
    rows = [0.110, 0.1175, 0.125, 0.1325, 0.140]
    cols = [0.030, 0.035, 0.040, 0.045, 0.050]
    # Lower discount (low row index) and higher growth (high col index) → higher value.
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


def _payload(
    rec,
    *,
    rationale: str = _RATIONALE,
    guardrails=(),
    model: str = "fcff",
    model_label: str = "FCFF discounted cash flow",
    discount_driver: str = "WACC",
    components=None,
    broker=None,
    news=None,
) -> dict:
    return build_narrative_payload(
        company={"name": "Tata Consultancy Services", "ticker": "TCS.NS", "sector": "Technology"},
        recommendation=rec,
        quality_verdict=rec.quality_verdict,
        quality_components=list(_CLEAN_COMPONENTS if components is None else components),
        valuation_rationale=rationale,
        bridge=list(_BRIDGE),
        wacc_build_up=dict(_WACC_BUILD_UP),
        guardrail_flags=list(guardrails),
        intrinsic_value=1688.9,
        current_price=2161.1,
        model=model,
        model_label=model_label,
        tornado=list(_TORNADO),
        sensitivity=_grid("Ke" if discount_driver == "Ke" else "WACC"),
        discount_driver=discount_driver,
        broker=broker,
        news=news,
    )


def _clean_rec():
    # Green quality, clear upside, no guardrail → confident BUY.
    return decide_recommendation(upside_pct=0.32, quality_verdict="Green", guardrail_fired=False)


def _flagged_rec():
    # Would read SELL, but a guardrail fired → HOLD, low confidence, withheld.
    return decide_recommendation(upside_pct=-0.60, quality_verdict="Amber", guardrail_fired=True)


_LIMIT_MSG = ("Intrinsic value is 0.47× the market price — outside the 0.3×–3× "
              "plausibility band")


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
    """Every numeral the narrative is permitted to print: a payload number run
    through any formatter (in either sign), or a numeral embedded in a string."""
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


# ---------------------------------------------------------------------------
# Contract 1 — no numeral absent from the payload
# ---------------------------------------------------------------------------


def test_clean_narrative_invents_no_numeral():
    p = _payload(_clean_rec())
    nar = generate_narrative(p)
    missing = _text_cores(nar.thesis) - _allowed_cores(p)
    assert not missing, f"narrative cites numerals absent from payload: {sorted(missing)}"


def test_flagged_narrative_invents_no_numeral():
    p = _payload(
        _flagged_rec(),
        guardrails=[{"code": "value_vs_price", "severity": "warn", "message": _LIMIT_MSG}],
        model="financial", model_label="Justified P/B (financial)", discount_driver="Ke",
    )
    nar = generate_narrative(p)
    missing = _text_cores(nar.thesis) - _allowed_cores(p)
    assert not missing, f"narrative cites numerals absent from payload: {sorted(missing)}"


def test_fabricated_numeral_would_be_caught():
    """Guard the guard: a numeral not in the payload must register as missing."""
    p = _payload(_clean_rec())
    assert "999999" not in _allowed_cores(p)
    assert _text_cores("a target of ₹999,999") - _allowed_cores(p) == {"999999"}


# ---------------------------------------------------------------------------
# Contract 2 — flagged names: withheld call + named limitation
# ---------------------------------------------------------------------------


def test_flagged_states_withheld_and_names_limitation():
    p = _payload(
        _flagged_rec(),
        guardrails=[{"code": "value_vs_price", "severity": "warn", "message": _LIMIT_MSG}],
        model="financial", model_label="Justified P/B (financial)", discount_driver="Ke",
    )
    nar = generate_narrative(p)
    lower = nar.thesis.lower()
    # withheld call, plainly stated
    assert "withheld" in lower
    assert "flagged" in lower
    assert "not a call" in lower
    # the limitation is named verbatim from the guardrail, not softened
    assert _LIMIT_MSG in nar.risks
    assert _LIMIT_MSG in nar.thesis
    # and the remedy is conditional on the model + flag
    assert "normalized forward roe" in lower


def test_clean_name_states_a_confident_call():
    nar = generate_narrative(_payload(_clean_rec()))
    assert "BUY" in nar.one_line_view
    assert "withheld" not in nar.thesis.lower()
    assert "high conviction" in nar.one_line_view.lower()


# ---------------------------------------------------------------------------
# Contract 3 — deterministic, offline, no key
# ---------------------------------------------------------------------------


def test_generates_identically_offline_without_network_or_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _no_network(*_a, **_k):
        raise AssertionError("narrative must not open a network connection")

    monkeypatch.setattr(socket, "socket", _no_network)

    p = _payload(_clean_rec())
    first = generate_narrative(p)
    second = generate_narrative(p)
    assert first == second
    assert first.generator == "deterministic-template-v1"
    assert first.thesis.strip()


# ---------------------------------------------------------------------------
# Section provenance — derived from the right payload field
# ---------------------------------------------------------------------------


def test_approach_surfaces_router_rationale_verbatim():
    nar = generate_narrative(_payload(_clean_rec()))
    assert _RATIONALE in nar.approach


def test_what_drives_value_follows_tornado_ranking():
    nar = generate_narrative(_payload(_clean_rec()))
    assert "most sensitive to WACC, then Revenue CAGR, then Terminal g" in nar.what_drives_value


def test_what_it_hinges_on_uses_grid_corners():
    nar = generate_narrative(_payload(_clean_rec()))
    # min corner = high WACC, low growth = 1700; max corner = low WACC, high growth = 2300
    assert "₹1,700" in nar.what_it_hinges_on
    assert "₹2,300" in nar.what_it_hinges_on


def test_earnings_quality_reflects_verdict_and_components():
    comps = [
        {"name": "Sloan accruals", "flag": "amber", "reason": "rising accrual ratio"},
        {"name": "Beneish M-score", "flag": "green", "reason": "no manipulation flag"},
    ]
    rec = decide_recommendation(upside_pct=0.05, quality_verdict="Amber", guardrail_fired=False)
    nar = generate_narrative(_payload(rec, components=comps))
    assert "screens Amber" in nar.earnings_quality
    assert "Sloan accruals (amber): rising accrual ratio" in nar.earnings_quality


# ---------------------------------------------------------------------------
# Payload hygiene — broker/news never fabricated
# ---------------------------------------------------------------------------


def test_payload_omits_broker_news_when_absent():
    p = _payload(_clean_rec())
    assert "broker_consensus" not in p
    assert "news_sentiment" not in p
    assert any("pending" in n.lower() for n in p["overlay_notes"])


def test_payload_includes_broker_news_when_present():
    p = _payload(_clean_rec(), broker={"rating": "Buy", "count": 30}, news={"sentiment": 0.2})
    assert p["broker_consensus"] == {"rating": "Buy", "count": 30}
    assert p["news_sentiment"] == {"sentiment": 0.2}
