"""Load and validate config.yaml into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@dataclass
class MarketConfig:
    """Macro-market assumptions."""

    risk_free_rate: float
    equity_risk_premium: float
    tax_rate: float


@dataclass
class DCFConfig:
    """DCF engine parameters."""

    projection_horizon: int
    terminal_growth_rate: float
    revenue_growth_source: str
    revenue_growth_override: Optional[float] = None


@dataclass
class PeersConfig:
    """Comparable company selection settings."""

    max_peers: int
    overrides: dict[str, list[str]] = field(default_factory=dict)


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
    peers: PeersConfig
    report: ReportConfig


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

    try:
        mkt = raw["market"]
        market = MarketConfig(
            risk_free_rate=float(mkt["risk_free_rate"]),
            equity_risk_premium=float(mkt["equity_risk_premium"]),
            tax_rate=float(mkt["tax_rate"]),
        )

        d = raw["dcf"]
        dcf = DCFConfig(
            projection_horizon=int(d["projection_horizon"]),
            terminal_growth_rate=float(d["terminal_growth_rate"]),
            revenue_growth_source=str(d["revenue_growth_source"]),
            revenue_growth_override=float(d["revenue_growth_override"])
            if d.get("revenue_growth_override") is not None
            else None,
        )

        p = raw.get("peers", {})
        peers = PeersConfig(
            max_peers=int(p.get("max_peers", 5)),
            overrides={k: list(v) for k, v in p.get("overrides", {}).items()},
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

    return AppConfig(market=market, dcf=dcf, peers=peers, report=report)
