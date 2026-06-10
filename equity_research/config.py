"""Load and validate config.yaml into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class MarketConfig:
    """Macro-market assumptions."""

    risk_free_rate: float
    equity_risk_premium: float
    tax_rate: float
    fallback_usd_inr: float = 95.0  # hard fallback when all live USDINR fetches fail


@dataclass
class DCFConfig:
    """DCF engine parameters."""

    projection_horizon: int
    terminal_growth_rate: float
    revenue_growth_source: str
    revenue_growth_override: Optional[float] = None
    stage2_fade_years: int = 0   # >0 enables two-stage DCF with linear fade


@dataclass
class PeersConfig:
    """Comparable company selection settings."""

    max_peers: int
    overrides: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RouterConfig:
    """Valuation model router settings."""

    capex_intensity_threshold: float = 0.25   # capex/revenue above which = capex-heavy
    leverage_threshold: float = 4.0           # net_debt/EBITDA above which = highly leveraged
    financial_keywords: list[str] = field(default_factory=lambda: [
        "bank", "nbfc", "insurance", "housing finance", "capital markets",
    ])


@dataclass
class ChartsConfig:
    """Chart rendering options."""

    price_history_period: str
    figsize: list[int]


@dataclass
class ReportConfig:
    """Report output settings."""

    currency: str
    output_dir: str
    charts: ChartsConfig


@dataclass
class AppConfig:
    """Top-level application configuration."""

    market: MarketConfig
    dcf: DCFConfig
    router: RouterConfig
    peers: PeersConfig
    report: ReportConfig
    conglomerates: dict[str, Any] = field(default_factory=dict)  # raw config for SOTP


def load_config(path: Path | str = _DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config.yaml and return a validated AppConfig dataclass.

    Raises FileNotFoundError if the config file does not exist.
    Raises ValueError if required keys are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as fh:
        raw = yaml.safe_load(fh)

    import os

    try:
        mkt = raw["market"]
        # Env vars (Railway deployment contract) override config.yaml values.
        market = MarketConfig(
            risk_free_rate=float(os.getenv("RISK_FREE_RATE", mkt["risk_free_rate"])),
            equity_risk_premium=float(os.getenv("INDIA_ERP", mkt["equity_risk_premium"])),
            tax_rate=float(mkt["tax_rate"]),
            fallback_usd_inr=float(mkt.get("fallback_usd_inr", 84.0)),
        )

        d = raw["dcf"]
        dcf = DCFConfig(
            projection_horizon=int(d["projection_horizon"]),
            terminal_growth_rate=float(d["terminal_growth_rate"]),
            revenue_growth_source=str(d["revenue_growth_source"]),
            revenue_growth_override=float(d["revenue_growth_override"])
            if d.get("revenue_growth_override") is not None
            else None,
            stage2_fade_years=int(d.get("stage2_fade_years", 0)),
        )

        p = raw.get("peers", {})
        peers = PeersConfig(
            max_peers=int(p.get("max_peers", 5)),
            overrides={k: list(v) for k, v in p.get("overrides", {}).items()},
        )

        rt = raw.get("router", {})
        router = RouterConfig(
            capex_intensity_threshold=float(rt.get("capex_intensity_threshold", 0.25)),
            leverage_threshold=float(rt.get("leverage_threshold", 4.0)),
            financial_keywords=list(rt.get("financial_keywords", [
                "bank", "nbfc", "insurance", "housing finance", "capital markets",
            ])),
        )

        r = raw["report"]
        ch = r.get("charts", {})
        charts = ChartsConfig(
            price_history_period=str(ch.get("price_history_period", "2y")),
            figsize=list(ch.get("figsize", [10, 4])),
        )
        report = ReportConfig(
            currency=str(r["currency"]),
            output_dir=str(r["output_dir"]),
            charts=charts,
        )
    except KeyError as exc:
        raise ValueError(f"Missing required config key: {exc}") from exc

    conglomerates_raw = raw.get("conglomerates", {})

    return AppConfig(
        market=market, dcf=dcf, router=router, peers=peers,
        report=report, conglomerates=conglomerates_raw,
    )
