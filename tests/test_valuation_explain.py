"""Phase 2C-i — valuation explainability tests.

Covers: the model-selection rationale, the FCFF and RI bridges reconciling
exactly to the reported per-share value, and each plausibility guardrail firing
on a constructed bad case while staying quiet on a clean one.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from equity_research.analysis.dcf import DCFResult, WACCComponents
from equity_research.analysis.residual_income import RIResult
from equity_research.analysis.valuation import ValuationResult
from equity_research.analysis.valuation_explain import (
    build_bridge,
    build_rationale,
    explain_valuation,
    run_guardrails,
)
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def _wacc_components() -> WACCComponents:
    return WACCComponents(
        cost_of_equity=0.13, cost_of_debt_pretax=0.08, cost_of_debt_aftertax=0.06,
        equity_weight=0.9, debt_weight=0.1, wacc=0.12, size_premium=0.005, beta_used=0.9,
    )


def _dcf(**ov) -> DCFResult:
    """A self-consistent FCFF result: EV=1000, net_debt=200, equity=800, 100 sh → 8.0."""
    base = dict(
        base_fcff=100.0, fcff_margin=0.2, growth_rate=0.08, wacc=0.12,
        terminal_growth=0.05, net_debt=200.0, shares_outstanding=100.0,
        projected_fcff=[110.0, 120.0, 130.0, 140.0, 150.0],
        pv_fcff=[100.0, 95.0, 90.0, 85.0, 80.0],          # sum 450
        terminal_value_nominal=1500.0,
        pv_terminal_value=550.0,                           # EV = 450 + 550 = 1000
        enterprise_value=1000.0,
        equity_value=800.0,                                # 1000 − 200
        intrinsic_value_per_share=8.0,                     # 800 / 100
        wacc_components=_wacc_components(),
        sensitivity=pd.DataFrame(),
    )
    base.update(ov)
    return DCFResult(**base)


def _val(dcf: DCFResult, **ov) -> ValuationResult:
    base = dict(
        model_used="fcff",
        route_reason="Capital-light, positive FCFF — FCFF DCF",
        confidence="high",
        intrinsic_value=dcf.intrinsic_value_per_share,
        current_price=8.0,
        market_divergence_pct=0.0,
        diverges_materially=False,
        dcf_result=dcf,
    )
    base.update(ov)
    return ValuationResult(**base)


# ===========================================================================
# Rationale
# ===========================================================================


def test_rationale_headline_includes_sector_and_reason():
    profile = {"sector": "Information Technology", "industry": "IT Services"}
    val = _val(_dcf())
    r = build_rationale(profile, val)
    assert r.sector == "Information Technology"
    assert r.model == "fcff"
    assert r.model_label == "FCFF discounted cash flow"
    assert "FCFF" in r.reason
    assert r.headline.startswith("Information Technology —")


# ===========================================================================
# Bridge reconciliation
# ===========================================================================


def test_fcff_bridge_reconciles_exactly():
    val = _val(_dcf())
    bridge = build_bridge(val, wacc=0.12)
    assert bridge is not None
    # EV step equals PV(explicit) + PV(terminal)
    by_label = {s.label: s.value for s in bridge.steps}
    assert by_label["PV of explicit FCFFs"] == pytest.approx(450.0)
    assert by_label["PV of terminal value"] == pytest.approx(550.0)
    assert by_label["Enterprise value"] == pytest.approx(1000.0)
    assert by_label["Less: net debt"] == pytest.approx(-200.0)
    assert by_label["Equity value"] == pytest.approx(800.0)
    # bridge arithmetic ties to the reported per-share value
    assert bridge.value_per_share == pytest.approx(8.0)
    assert bridge.reconciles is True
    assert bridge.reconciliation_error == pytest.approx(0.0, abs=1e-9)


def test_ri_bridge_reconciles():
    ri = RIResult(
        book_value_per_share=50.0, cost_of_equity=0.13, growth_rate=0.08,
        terminal_growth=0.05, shares_outstanding=10.0,
        projected_net_income=[60.0], projected_book_value=[510.0],
        projected_ri=[12.0, 9.0, 7.0], pv_ri=[10.0, 8.0, 6.0],   # sum 24
        terminal_ri=90.0, pv_terminal_ri=76.0,
        intrinsic_value_per_share=60.0, equity_value=600.0,        # 500 + 24 + 76
    )
    val = _val(_dcf(), model_used="ri", route_reason="Volatile FCF — residual income",
               dcf_result=None, ri_result=ri, intrinsic_value=60.0)
    bridge = build_bridge(val, wacc=None)
    assert bridge is not None
    by_label = {s.label: s.value for s in bridge.steps}
    assert by_label["Book value of equity"] == pytest.approx(500.0)
    assert by_label["PV of residual income"] == pytest.approx(24.0)
    assert by_label["Equity value"] == pytest.approx(600.0)
    assert bridge.value_per_share == pytest.approx(60.0)
    assert bridge.reconciles is True


# ===========================================================================
# Guardrails — fire on bad, quiet on clean
# ===========================================================================


def _codes(diags) -> set[str]:
    return {d.code for d in diags}


def test_guardrails_quiet_on_clean_case(cfg):
    profile = {"current_price": 8.0}
    diags = run_guardrails(_val(_dcf()), profile, cfg, base_ebitda=100.0)
    assert diags == []


def test_value_vs_price_fires_when_far_above(cfg):
    # intrinsic 8.0 vs price 2.0 → 4× → outside 0.5–2.0 band
    val = _val(_dcf(), current_price=2.0)
    diags = run_guardrails(val, {"current_price": 2.0}, cfg, base_ebitda=100.0)
    assert "value_vs_price" in _codes(diags)


def test_terminal_value_share_fires(cfg):
    # PV(TV)=900 of EV 1000 → 90% > 75%
    dcf = _dcf(pv_fcff=[100.0], pv_terminal_value=900.0, enterprise_value=1000.0)
    diags = run_guardrails(_val(dcf), {"current_price": 8.0}, cfg, base_ebitda=100.0)
    assert "terminal_value_share" in _codes(diags)


def test_implied_exit_multiple_fires(cfg):
    # terminal_value_nominal 5000 vs terminal EBITDA ≈128 → ~39× > 25×
    dcf = _dcf(terminal_value_nominal=5000.0)
    diags = run_guardrails(_val(dcf), {"current_price": 8.0}, cfg, base_ebitda=100.0)
    assert "implied_exit_multiple" in _codes(diags)


def test_negative_ev_flagged_critical(cfg):
    dcf = _dcf(enterprise_value=-100.0)
    diags = run_guardrails(_val(dcf), {"current_price": 8.0}, cfg, base_ebitda=100.0)
    crit = [d for d in diags if d.code == "non_finite_or_negative"]
    assert crit and crit[0].severity == "critical"


def test_explain_valuation_end_to_end(cfg):
    profile = {"sector": "Information Technology", "current_price": 8.0}
    vx = explain_valuation(profile, _val(_dcf()), None, cfg, base_ebitda=100.0)
    assert vx.rationale.model == "fcff"
    assert vx.bridge is not None and vx.bridge.reconciles
    assert vx.diagnostics == []
    assert vx.has_critical is False
