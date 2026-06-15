"""LLM equity-research narrative — "the why" (Phase 2C-iii).

Generates a structured ER thesis from the COMPUTED numbers only, via the
Anthropic API (claude-sonnet-4-6).  Hard constraints, enforced in the system
prompt and by structured output:

  * explain only what the data supports — drivers, risks, catalysts, and what
    would change the view;
  * MUST NOT invent figures, broker quotes, or news;
  * MUST faithfully convey guardrail flags and limitations rather than paper
    over them — for a flagged name, state the limitation and the lowered
    confidence, never assert a confident target.

Robustness: this is a discrete, cacheable step.  ``generate_narrative`` returns
``None`` on any failure (missing key, missing SDK, API error) — the report still
renders with all structured data; the narrative simply degrades to absent and
never blocks the response.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# The user mandated this exact model for the narrative step.
NARRATIVE_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4000

_SYSTEM_PROMPT = """\
You are an equity-research analyst writing the "why" behind a quantitative \
valuation. You are given a JSON object of ALREADY-COMPUTED figures for one \
company. Write a structured thesis.

Hard rules — these are non-negotiable:
1. Use ONLY numbers present in the provided JSON. Do NOT invent or estimate any \
figure, price target, multiple, growth rate, broker rating, analyst quote, or \
news item. If something is not in the JSON, do not mention a number for it.
2. If `recommendation.flagged` is true OR `guardrail_flags` is non-empty, you \
MUST state the limitation plainly and that confidence is low. You MUST NOT \
assert a confident directional target (no "clear SELL", no "X% overvalued" as \
a confident claim). Explain WHY the valuation is flagged using the provided \
flag reasons.
3. If `recommendation.flagged` is false, you may state the directional call and \
its rationale confidently, but still grounded only in the provided numbers.
4. Do not fabricate broker consensus or news. If they are marked pending/absent, \
either omit them or state they are pending — never invent them.
5. Be concise and specific. Cite the actual figures from the JSON.

Return ONLY a single JSON object (no markdown fences, no prose around it) with \
exactly these keys:
  "thesis": string,
  "key_drivers": array of strings,
  "risks": array of strings,
  "catalysts": array of strings,
  "what_would_change_the_view": array of strings,
  "limitations_and_confidence": string."""


def _extract_json(text: str) -> dict:
    """Parse the model's JSON, tolerating ```json fences or surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start : end + 1]
    return json.loads(t)


@dataclass
class Narrative:
    """Structured ER thesis sections generated from the computed numbers."""

    thesis: str
    key_drivers: list[str]
    risks: list[str]
    catalysts: list[str]
    what_would_change_the_view: list[str]
    limitations_and_confidence: str
    model: str = NARRATIVE_MODEL
    warnings: list[str] = field(default_factory=list)


def generate_narrative(
    payload: dict,
    *,
    api_key: str | None = None,
    model: str = NARRATIVE_MODEL,
    client: object | None = None,
) -> Narrative | None:
    """Generate the structured thesis, or ``None`` if the step can't run.

    ``client`` may be injected (tests); otherwise an Anthropic client is built
    from ``api_key`` / ``ANTHROPIC_API_KEY``.  Any failure → ``None`` (logged),
    so the surrounding report is never blocked.
    """
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if client is None and not key:
        logger.info("Narrative skipped: no ANTHROPIC_API_KEY configured")
        return None
    try:
        if client is None:
            import anthropic  # lazy — module import must not require the SDK

            client = anthropic.Anthropic(api_key=key)

        resp = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        )
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        if not text:
            logger.warning("Narrative: empty response from model")
            return None
        data = _extract_json(text)
        return Narrative(
            thesis=data["thesis"],
            key_drivers=list(data.get("key_drivers", [])),
            risks=list(data.get("risks", [])),
            catalysts=list(data.get("catalysts", [])),
            what_would_change_the_view=list(data.get("what_would_change_the_view", [])),
            limitations_and_confidence=data["limitations_and_confidence"],
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 — narrative must never block the report
        logger.warning("Narrative generation failed (%s) — degrading to absent", exc)
        return None


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
    broker: object | None = None,
    news: object | None = None,
) -> dict:
    """Assemble the computed-numbers-only payload handed to the model.

    Broker/news are included only when present — never stubbed into the payload,
    so the model has nothing to fabricate from.
    """
    payload: dict = {
        "company": company,
        "recommendation": {
            "action": recommendation.action,
            "conviction": recommendation.conviction,
            "flagged": recommendation.flagged,
            "upside_pct": recommendation.upside_pct,
            "required_margin_of_safety": recommendation.required_mos,
            "reason": recommendation.reason,
        },
        "earnings_quality": {
            "verdict": quality_verdict,
            "components": quality_components,
        },
        "valuation": {
            "model_rationale": valuation_rationale,
            "intrinsic_value_per_share": intrinsic_value,
            "current_price": current_price,
            "bridge": bridge,
        },
        "wacc_build_up": wacc_build_up,
        "guardrail_flags": guardrail_flags,
        "overlay_notes": recommendation.overlay_notes,
    }
    if broker is not None:
        payload["broker_consensus"] = broker
    if news is not None:
        payload["news_sentiment"] = news
    return payload
