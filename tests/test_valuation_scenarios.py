"""Phase 2C-ii — sensitivity + scenarios tests.

Covers: FCFF grid monotonicity (value ↓ as WACC ↑, ↑ as terminal g ↑),
bear < base < bull, each scenario reconciling through its bridge to the stated
per-share value, and — the key one — the driver set switching by model so the
financial path produces a Ke×g grid, NOT WACC×g.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from equity_research.analysis.dcf import DCFResult, WACCComponents
from equity_research.analysis.financial_sector import BankMetrics, FinancialValuationResult
from equity_research.analysis.valuation import ValuationResult
from equity_research.analysis.valuation_scenarios import build_scenarios
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def _dcf(**ov) -> DCFResult:
    base = dict(
        base_fcff=100.0, fcff_margin=0.2, growth_rate=0.08, wacc=0.12,
        terminal_growth=0.05, net_debt=200.0, shares_outstanding=100.0,
        projected_fcff=[108.0, 116.6, 126.0, 136.0, 146.9],
        pv_fcff=[96.0, 93.0, 90.0, 86.0, 83.0],
        terminal_value_nominal=2000.0, pv_terminal_value=600.0,
        enterprise_value=1048.0, equity_value=848.0, intrinsic_value_per_share=8.48,
        wacc_components=WACCComponents(0.13, 0.08, 0.06, 0.9, 0.1, 0.12, 0.005, 0.9),
        sensitivity=pd.DataFrame(),
    )
    base.update(ov)
    return DCFResult(**base)


def _fcff_val(**ov) -> ValuationResult:
    d = _dcf()
    base = dict(
        model_used="fcff", route_reason="FCFF DCF", confidence="high",
        intrinsic_value=d.intrinsic_value_per_share, current_price=8.0,
        market_divergence_pct=0.0, diverges_materially=False, dcf_result=d,
    )
    base.update(ov)
    return ValuationResult(**base)


def _financial_val() -> ValuationResult:
    fin = FinancialValuationResult(
        justified_pb=1.6, intrinsic_value_per_share=640.0, equity_value=640.0e9,
        book_value_per_share=400.0, cost_of_equity=0.13, roe=0.16,
        growth_rate=0.08, terminal_growth=0.05, shares_outstanding=1.0e9,
        retention_ratio=0.5, roe_ke_spread=0.03,
        sensitivity_roe_labels=[], sensitivity_ke_labels=[], sensitivity_pb=[],
        bank_metrics=BankMetrics(None, None, None, None, None),
        is_fallback=False, fallback_note="",
    )
    return ValuationResult(
        model_used="financial", route_reason="Financial — Justified P/B",
        confidence="medium", intrinsic_value=640.0, current_price=600.0,
        market_divergence_pct=0.0, diverges_materially=False,
        dcf_result=None, financial_result=fin,
    )


# ===========================================================================
# FCFF grid
# ===========================================================================


def test_fcff_grid_is_wacc_by_g(cfg):
    vs = build_scenarios(_fcff_val(), {"current_price": 8.0}, cfg)
    assert vs.discount_driver == "WACC"
    assert vs.sensitivity is not None
    assert vs.sensitivity.row_driver == "WACC"
    assert vs.sensitivity.col_driver == "Terminal growth"


def test_fcff_grid_monotonic(cfg):
    grid = build_scenarios(_fcff_val(), {"current_price": 8.0}, cfg).sensitivity
    n_rows, n_cols = len(grid.row_values), len(grid.col_values)
    # Down each column as WACC (row) rises.
    for j in range(n_cols):
        col = [grid.values[i][j] for i in range(n_rows)]
        assert all(col[i] > col[i + 1] for i in range(n_rows - 1)), f"col {j} not ↓ in WACC"
    # Up along each row as terminal g rises.
    for i in range(n_rows):
        row = grid.values[i]
        assert all(row[j] < row[j + 1] for j in range(n_cols - 1)), f"row {i} not ↑ in g"


def test_fcff_base_cell_ties_to_reported(cfg):
    grid = build_scenarios(_fcff_val(), {"current_price": 8.0}, cfg).sensitivity
    mid = len(grid.row_values) // 2
    assert grid.values[mid][mid] == pytest.approx(8.48)   # base WACC × base g


# ===========================================================================
# Scenarios
# ===========================================================================


def test_bear_base_bull_ordering(cfg):
    vs = build_scenarios(_fcff_val(), {"current_price": 8.0}, cfg)
    by = {s.name: s.intrinsic_value for s in vs.scenarios}
    assert by["bear"] < by["base"] < by["bull"]


def test_scenarios_reconcile_through_bridge(cfg):
    vs = build_scenarios(_fcff_val(), {"current_price": 8.0}, cfg)
    for s in vs.scenarios:
        assert s.bridge_to_target[0].value == pytest.approx(s.intrinsic_value)
        # result step = today's value × compounding factor = Y-year target
        compound = s.bridge_to_target[1].value
        assert s.bridge_to_target[-1].value == pytest.approx(s.intrinsic_value * compound)
        assert s.target_y_year == pytest.approx(s.intrinsic_value * compound)


def test_base_scenario_ties_to_reported(cfg):
    vs = build_scenarios(_fcff_val(), {"current_price": 8.0}, cfg)
    base = next(s for s in vs.scenarios if s.name == "base")
    assert base.intrinsic_value == pytest.approx(8.48)


# ===========================================================================
# Model-appropriate driver switch — the key guard against hardcoded FCFF
# ===========================================================================


def test_financial_grid_is_ke_not_wacc(cfg):
    vs = build_scenarios(_financial_val(), {"current_price": 600.0}, cfg)
    assert vs.discount_driver == "Ke"
    assert vs.sensitivity is not None
    assert vs.sensitivity.row_driver == "Ke"          # NOT "WACC"
    # tornado drivers are Ke / ROE / terminal g — not revenue CAGR / margin
    drivers = {t.driver for t in vs.tornado}
    assert "Ke" in drivers and "ROE" in drivers
    assert "Revenue CAGR" not in drivers and "WACC" not in drivers


def test_financial_base_ties_and_bull_bear_order(cfg):
    vs = build_scenarios(_financial_val(), {"current_price": 600.0}, cfg)
    by = {s.name: s.intrinsic_value for s in vs.scenarios}
    assert by["base"] == pytest.approx(640.0)
    # ROE (16%) > Ke (13%) → bull (lower Ke, higher ROE/g) worth more
    assert by["bear"] < by["base"] < by["bull"]
