"""Valuation sensitivity + scenarios (Phase 2C-ii).

Builds on the 2C-i bridge/guardrails. Three outputs, all **model-appropriate** —
the driver set is branched by the routed model, never hardcoded to FCFF:

  - FCFF DCF      → discount input = WACC; drivers WACC, terminal g, revenue
                    CAGR, operating margin, exit/reinvestment.
  - Financial/RI  → discount input = Ke; drivers Ke, ROE, terminal g.  A WACC×g
                    table would be meaningless for a bank.
  - SOTP          → no discount×g grid; degrades to a segment-multiple scenario
                    with an explicit note.

1. Two-way sensitivity grid: intrinsic value/share across the model's primary
   discount input (±1.5%) × terminal g (±1%).
2. Tornado: each model-appropriate driver varied over its range, others held at
   base; (driver, low, high, swing) ranked by |swing|.
3. Base / bull / bear scenarios: coherent assumption sets (bull lowers the
   discount rate and lifts growth/margin together; bear the reverse), each with
   its intrinsic value, a 12-month and Y-year target, the explicit bridge from
   today's value to the Y-year target, and any plausibility flags re-run through
   the 2C-i guardrails.

The perturbation engine uses a model-appropriate single-stage closed form and
scales it so the base case ties exactly to the model's reported per-share value;
scenarios/grid cells are that base scaled by the closed-form sensitivity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from equity_research.analysis.valuation import ValuationResult
from equity_research.analysis.valuation_explain import (
    BridgeStep,
    Diagnostic,
    run_guardrails,
)
from equity_research.config import AppConfig

# Grid axes (offsets applied to the base discount input and terminal growth).
DISCOUNT_OFFSETS = (-0.015, -0.0075, 0.0, 0.0075, 0.015)
GROWTH_OFFSETS = (-0.01, -0.005, 0.0, 0.005, 0.01)
DEFAULT_HORIZON_Y = 3
_MIN_SPREAD = 0.005   # floor on (discount − g) to keep the perpetuity finite


def _is_num(v: float | None) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


# ===========================================================================
# Structured outputs
# ===========================================================================


@dataclass
class SensitivityGrid:
    row_driver: str               # "WACC" | "Ke"
    col_driver: str               # "Terminal growth"
    row_values: list[float]       # discount inputs (base + offsets)
    col_values: list[float]       # terminal-g values
    values: list[list[float]]     # intrinsic/share per [row][col]
    base_row: float
    base_col: float


@dataclass
class TornadoDriver:
    driver: str
    low_input: float
    high_input: float
    low_value: float              # intrinsic at the low end of the driver
    high_value: float
    base_value: float
    swing: float                  # |high_value − low_value|


@dataclass
class Scenario:
    name: str                     # "base" | "bull" | "bear"
    assumptions: dict[str, float]
    intrinsic_value: float
    target_12m: float
    target_y_year: float
    horizon_years: int
    bridge_to_target: list[BridgeStep]
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class ValuationScenarios:
    model: str
    discount_driver: str          # "WACC" | "Ke" | "—"
    sensitivity: SensitivityGrid | None
    tornado: list[TornadoDriver]
    scenarios: list[Scenario]
    note: str | None = None
    warnings: list[str] = field(default_factory=list)


# ===========================================================================
# Model-appropriate valuers (per-share as a function of the model's drivers)
# ===========================================================================
#
# Each valuer is a pure single-stage closed form returning a RAW per-share value
# (not floored — flooring would break grid monotonicity). The caller scales it so
# the base case equals the model's reported per-share value.


def _fcff_valuer(
    base_fcff: float, horizon: int, net_debt: float, shares: float
) -> Callable[..., float]:
    def value(*, wacc: float, terminal_g: float, growth: float,
              margin_factor: float = 1.0, tv_factor: float = 1.0) -> float:
        fcff = base_fcff * margin_factor
        projected = []
        for _ in range(horizon):
            fcff *= (1.0 + growth)
            projected.append(fcff)
        pv_explicit = sum(cf / (1.0 + wacc) ** (t + 1) for t, cf in enumerate(projected))
        spread = max(wacc - terminal_g, _MIN_SPREAD)
        tv = projected[-1] * (1.0 + terminal_g) / spread * tv_factor
        pv_tv = tv / (1.0 + wacc) ** horizon
        equity = (pv_explicit + pv_tv) - net_debt
        return equity / shares if shares > 0 else float("nan")
    return value


def _financial_valuer(bvps: float) -> Callable[..., float]:
    def value(*, ke: float, roe: float, g: float) -> float:
        spread = max(ke - g, _MIN_SPREAD)
        pb = (roe - g) / spread
        return pb * bvps
    return value


def _sotp_valuer(total_ev: float, net_debt: float, shares: float) -> Callable[..., float]:
    def value(*, ev_factor: float = 1.0) -> float:
        equity = total_ev * ev_factor - net_debt
        return equity / shares if shares > 0 else float("nan")
    return value


# ===========================================================================
# Grid + tornado + scenarios assembly
# ===========================================================================


def _scaled(valuer: Callable[..., float], base_kwargs: dict, reported: float) -> Callable[..., float]:
    """Wrap *valuer* so the base case returns *reported* exactly; others scale."""
    base_raw = valuer(**base_kwargs)
    scale = (reported / base_raw) if (_is_num(base_raw) and abs(base_raw) > 1e-12) else 1.0

    def scaled(**kw) -> float:
        merged = {**base_kwargs, **kw}
        return scale * valuer(**merged)
    return scaled


def _build_grid(scaled: Callable[..., float], disc_key: str, disc_base: float,
                g_base: float, row_label: str) -> SensitivityGrid:
    rows = [disc_base + o for o in DISCOUNT_OFFSETS]
    cols = [g_base + o for o in GROWTH_OFFSETS]
    g_key = _g_kw(disc_key)
    values = [[scaled(**{disc_key: r, g_key: c}) for c in cols] for r in rows]
    return SensitivityGrid(
        row_driver=row_label, col_driver="Terminal growth",
        row_values=rows, col_values=cols, values=values,
        base_row=disc_base, base_col=g_base,
    )


def _g_kw(disc_key: str) -> str:
    # FCFF valuer takes terminal_g; financial valuer takes g.
    return "terminal_g" if disc_key == "wacc" else "g"


def _tornado(scaled: Callable[..., float], base_kwargs: dict,
             driver_ranges: list[tuple[str, str, float, float]]) -> list[TornadoDriver]:
    """driver_ranges: (label, kwarg, low_input, high_input)."""
    base_val = scaled(**base_kwargs)
    out: list[TornadoDriver] = []
    for label, kw, lo, hi in driver_ranges:
        lo_v = scaled(**{kw: lo})
        hi_v = scaled(**{kw: hi})
        out.append(TornadoDriver(
            driver=label, low_input=lo, high_input=hi,
            low_value=lo_v, high_value=hi_v, base_value=base_val,
            swing=abs(hi_v - lo_v),
        ))
    out.sort(key=lambda d: d.swing, reverse=True)
    return out


def _scenario(name: str, scaled: Callable[..., float], kwargs: dict,
              assumptions: dict[str, float], g_compound: float, horizon_y: int,
              price: float | None, model: str, profile: dict,
              config: AppConfig) -> Scenario:
    raw = scaled(**kwargs)
    intrinsic = max(0.0, raw)
    factor = (1.0 + g_compound) ** horizon_y
    target_y = intrinsic * factor
    target_12m = intrinsic * (1.0 + g_compound)
    bridge = [
        BridgeStep("Intrinsic value / share (today)", intrinsic, "subtotal"),
        BridgeStep(f"Compounded at {g_compound:.1%} for {horizon_y}y", factor, "component"),
        BridgeStep(f"{horizon_y}-year target / share", target_y, "result"),
    ]
    # Re-run the 2C-i guardrails on the scenario's per-share value.
    scn_val = ValuationResult(
        model_used=model, route_reason="", confidence="",
        intrinsic_value=intrinsic, current_price=price,
        market_divergence_pct=None, diverges_materially=False, dcf_result=None,
    )
    diags = run_guardrails(scn_val, profile, config)
    return Scenario(
        name=name, assumptions=assumptions, intrinsic_value=intrinsic,
        target_12m=target_12m, target_y_year=target_y, horizon_years=horizon_y,
        bridge_to_target=bridge, diagnostics=diags,
    )


def build_scenarios(
    valuation: ValuationResult,
    profile: dict,
    config: AppConfig,
    *,
    horizon_y: int = DEFAULT_HORIZON_Y,
) -> ValuationScenarios:
    """Assemble the model-appropriate sensitivity grid, tornado, and scenarios."""
    model = valuation.model_used
    price = valuation.current_price or profile.get("current_price")
    reported = valuation.intrinsic_value

    # ---- FCFF DCF: WACC × terminal g ----------------------------------------
    if model == "fcff" and valuation.dcf_result is not None and _is_num(reported):
        d = valuation.dcf_result
        horizon = len(d.projected_fcff) or config.dcf.projection_horizon
        valuer = _fcff_valuer(d.base_fcff, horizon, d.net_debt, d.shares_outstanding)
        base_kw = dict(wacc=d.wacc, terminal_g=d.terminal_growth, growth=d.growth_rate,
                       margin_factor=1.0, tv_factor=1.0)
        scaled = _scaled(valuer, base_kw, reported)
        grid = _build_grid(scaled, "wacc", d.wacc, d.terminal_growth, "WACC")
        tornado = _tornado(scaled, base_kw, [
            ("WACC", "wacc", d.wacc - 0.015, d.wacc + 0.015),
            ("Terminal g", "terminal_g", d.terminal_growth - 0.01, d.terminal_growth + 0.01),
            ("Revenue CAGR", "growth", d.growth_rate - 0.02, d.growth_rate + 0.02),
            ("Operating margin", "margin_factor", 0.90, 1.10),
            ("Exit / reinvestment", "tv_factor", 0.85, 1.15),
        ])
        scenarios = [
            _scenario("base", scaled, dict(base_kw), {
                "wacc": d.wacc, "terminal_g": d.terminal_growth, "revenue_cagr": d.growth_rate,
                "margin_factor": 1.0}, d.terminal_growth, horizon_y, price, model, profile, config),
            _scenario("bull", scaled, dict(wacc=d.wacc - 0.01, terminal_g=d.terminal_growth + 0.005,
                      growth=d.growth_rate + 0.02, margin_factor=1.05), {
                "wacc": d.wacc - 0.01, "terminal_g": d.terminal_growth + 0.005,
                "revenue_cagr": d.growth_rate + 0.02, "margin_factor": 1.05},
                d.terminal_growth + 0.005, horizon_y, price, model, profile, config),
            _scenario("bear", scaled, dict(wacc=d.wacc + 0.01, terminal_g=d.terminal_growth - 0.005,
                      growth=d.growth_rate - 0.02, margin_factor=0.95), {
                "wacc": d.wacc + 0.01, "terminal_g": d.terminal_growth - 0.005,
                "revenue_cagr": d.growth_rate - 0.02, "margin_factor": 0.95},
                max(0.0, d.terminal_growth - 0.005), horizon_y, price, model, profile, config),
        ]
        return ValuationScenarios("fcff", "WACC", grid, tornado, scenarios)

    # ---- Financial (Justified P/B) or RI: Ke × terminal g -------------------
    fin = valuation.financial_result
    ri = valuation.ri_result
    if model in ("financial", "ri") and _is_num(reported) and (fin is not None or ri is not None):
        if fin is not None:
            ke, roe, g_base, bvps = fin.cost_of_equity, fin.roe, fin.growth_rate, fin.book_value_per_share
        else:
            ke, g_base, bvps = ri.cost_of_equity, ri.terminal_growth, ri.book_value_per_share
            # Derive an effective ROE from the first residual income: RI₁=(ROE−Ke)·BV₀.
            roe = (ri.pv_ri[0] / bvps + ke) if (ri.pv_ri and bvps) else ke + 0.02
        valuer = _financial_valuer(bvps)
        base_kw = dict(ke=ke, roe=roe, g=g_base)
        scaled = _scaled(valuer, base_kw, reported)
        grid = _build_grid(scaled, "ke", ke, g_base, "Ke")
        tornado = _tornado(scaled, base_kw, [
            ("Ke", "ke", ke - 0.015, ke + 0.015),
            ("ROE", "roe", roe - 0.02, roe + 0.02),
            ("Terminal g", "g", g_base - 0.01, g_base + 0.01),
        ])
        scenarios = [
            _scenario("base", scaled, dict(base_kw),
                      {"ke": ke, "roe": roe, "g": g_base}, g_base, horizon_y, price, model, profile, config),
            _scenario("bull", scaled, dict(ke=ke - 0.01, roe=roe + 0.02, g=g_base + 0.005),
                      {"ke": ke - 0.01, "roe": roe + 0.02, "g": g_base + 0.005},
                      g_base + 0.005, horizon_y, price, model, profile, config),
            _scenario("bear", scaled, dict(ke=ke + 0.01, roe=roe - 0.02, g=g_base - 0.005),
                      {"ke": ke + 0.01, "roe": roe - 0.02, "g": g_base - 0.005},
                      max(0.0, g_base - 0.005), horizon_y, price, model, profile, config),
        ]
        return ValuationScenarios(model, "Ke", grid, tornado, scenarios)

    # ---- SOTP: degrade gracefully (segment-multiple scenario, no disc×g grid) -
    if model == "sotp" and valuation.sotp_result is not None and _is_num(reported):
        s = valuation.sotp_result
        valuer = _sotp_valuer(s.total_ev, s.net_debt, s.shares_outstanding)
        base_kw = dict(ev_factor=1.0)
        scaled = _scaled(valuer, base_kw, reported)
        tornado = _tornado(scaled, base_kw, [
            ("Segment multiples", "ev_factor", 0.85, 1.15),
        ])
        g_c = config.dcf.terminal_growth_rate
        scenarios = [
            _scenario("base", scaled, dict(ev_factor=1.0), {"ev_factor": 1.0},
                      g_c, horizon_y, price, model, profile, config),
            _scenario("bull", scaled, dict(ev_factor=1.15), {"ev_factor": 1.15},
                      g_c, horizon_y, price, model, profile, config),
            _scenario("bear", scaled, dict(ev_factor=0.85), {"ev_factor": 0.85},
                      g_c, horizon_y, price, model, profile, config),
        ]
        return ValuationScenarios(
            "sotp", "—", None, tornado, scenarios,
            note="SOTP is valued by segment EV/EBITDA multiples; a discount-rate × "
                 "terminal-growth grid is not meaningful. Scenarios vary the blended "
                 "segment multiple (±15%) instead.",
        )

    # ---- Unsupported / insufficient data ------------------------------------
    return ValuationScenarios(
        model, "—", None, [], [],
        note="Sensitivity and scenarios unavailable for this model / data.",
    )
