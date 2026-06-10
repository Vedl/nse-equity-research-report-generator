from __future__ import annotations

from dataclasses import dataclass

@dataclass
class FactorResult:
    factor_name: str
    long_label: str
    short_label: str
    period_start: str
    period_end: str
    
    long_annual_returns: list[float]
    short_annual_returns: list[float]
    benchmark_annual_returns: list[float]
    spread_annual_returns: list[float]
    
    long_cagr: float
    short_cagr: float
    benchmark_cagr: float
    spread_cagr: float
    
    long_sharpe: float
    short_sharpe: float
    spread_sharpe: float
    
    max_drawdown_long: float
    max_drawdown_short: float
    
    hit_rate: float
    cumulative_dates: list[str]
    cumulative_long: list[float]
    cumulative_short: list[float]
    cumulative_benchmark: list[float]
    
    ic_mean: float | None = None

@dataclass
class BacktestResult:
    universe_size: int
    stocks_with_history: int
    backtest_start: str
    backtest_end: str
    benchmark: str
    rebalance_frequency: str
    
    factors: list[FactorResult]
    
    caveats: list[str]
    methodology_notes: list[str]
