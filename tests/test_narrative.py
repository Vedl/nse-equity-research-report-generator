"""Phase 2C-iii — LLM narrative tests.

The narrative is a discrete, best-effort step: a failure (missing key, missing
SDK, API error) must degrade to absent and never block the response. The payload
must never contain fabricated broker/news when those are absent.
"""

from __future__ import annotations

import json

from equity_research.analysis.narrative import (
    build_narrative_payload,
    generate_narrative,
)
from equity_research.analysis.recommendation import decide_recommendation


# --- Fakes -----------------------------------------------------------------


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self, behavior) -> None:
        self._behavior = behavior

    def create(self, **kwargs):
        return self._behavior(kwargs)


class _FakeClient:
    def __init__(self, behavior) -> None:
        self.messages = _FakeMessages(behavior)


_VALID_JSON = json.dumps({
    "thesis": "TCS trades modestly above its FCFF intrinsic value of 1,688.",
    "key_drivers": ["Stable FCFF", "Low leverage"],
    "risks": ["Margin pressure"],
    "catalysts": ["Deal wins"],
    "what_would_change_the_view": ["A re-rating of the discount rate"],
    "limitations_and_confidence": "No guardrail fired; medium confidence.",
})

_REC = decide_recommendation(upside_pct=-0.22, quality_verdict="Amber", guardrail_fired=False)


def _payload() -> dict:
    return build_narrative_payload(
        company={"name": "TCS", "ticker": "TCS.NS", "sector": "Technology"},
        recommendation=_REC,
        quality_verdict="Amber",
        quality_components=[{"name": "Sloan accruals", "flag": "green", "reason": "low"}],
        valuation_rationale="Technology — FCFF DCF",
        bridge=[{"label": "Equity value", "value": 611000.0}],
        wacc_build_up={"wacc": 0.125, "cost_of_equity": 0.126},
        guardrail_flags=[],
        intrinsic_value=1688.9,
        current_price=2161.1,
    )


# --- Degradation -----------------------------------------------------------


def test_no_key_no_client_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert generate_narrative(_payload()) is None


def test_api_failure_returns_none_does_not_raise():
    def boom(_kwargs):
        raise RuntimeError("API down")

    assert generate_narrative(_payload(), client=_FakeClient(boom)) is None


def test_valid_response_is_parsed():
    client = _FakeClient(lambda _k: _Resp(_VALID_JSON))
    nar = generate_narrative(_payload(), client=client)
    assert nar is not None
    assert "1,688" in nar.thesis
    assert nar.key_drivers == ["Stable FCFF", "Low leverage"]
    assert nar.model == "claude-sonnet-4-6"


def test_fenced_json_is_parsed():
    fenced = f"```json\n{_VALID_JSON}\n```"
    client = _FakeClient(lambda _k: _Resp(fenced))
    nar = generate_narrative(_payload(), client=client)
    assert nar is not None and nar.risks == ["Margin pressure"]


def test_malformed_json_returns_none():
    client = _FakeClient(lambda _k: _Resp("not json at all"))
    assert generate_narrative(_payload(), client=client) is None


# --- No fabricated broker/news ---------------------------------------------


def test_payload_omits_broker_news_when_absent():
    p = _payload()
    assert "broker_consensus" not in p
    assert "news_sentiment" not in p
    # overlay notes mark them pending (from the recommendation), not fabricated
    assert any("pending" in n.lower() for n in p["overlay_notes"])


def test_payload_includes_broker_news_when_present():
    p = build_narrative_payload(
        company={"name": "X"}, recommendation=_REC, quality_verdict="Amber",
        quality_components=[], valuation_rationale="r", bridge=[],
        wacc_build_up={}, guardrail_flags=[], intrinsic_value=1.0, current_price=1.0,
        broker={"rating": "Buy", "count": 30}, news={"sentiment": 0.2},
    )
    assert p["broker_consensus"] == {"rating": "Buy", "count": 30}
    assert p["news_sentiment"] == {"sentiment": 0.2}
