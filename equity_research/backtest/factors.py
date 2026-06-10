import pandas as pd
from typing import Optional

from equity_research.backtest.engine import run_static_factor
from equity_research.backtest.models import FactorResult
from equity_research.backtest.ic_analysis import calculate_rolling_ic

def run_momentum_factor(prices: pd.DataFrame, all_tickers: list[str]) -> FactorResult:
    # 12M minus 1M price momentum (skip the most recent month for reversal effects)
    returns_1m = prices.pct_change(periods=1, fill_method=None)
    returns_12m = prices.pct_change(periods=12, fill_method=None)
    
    # The factor score at time t is returns_12m(t-1) - returns_1m(t-1)
    # We test it against forward 1M returns: returns_1m(t+1)
    # So we shift the factor score forward by 1 period so it aligns with forward return
    factor_panel = returns_12m.shift(1) - returns_1m.shift(1)
    factor_panel = factor_panel[all_tickers]
    
    # Compute IC
    forward_returns = returns_1m.shift(-1)[all_tickers]
    ic = calculate_rolling_ic(factor_panel, forward_returns)
    
    # Calculate simple quintiles across time for the cumulative chart
    # Average the scores over time to form static portfolios for demonstration
    mean_scores = factor_panel.mean().dropna().sort_values()
    if mean_scores.empty:
        return run_static_factor(prices, "Price Momentum (12M-1M)", [], [], "Top Quintile", "Bottom Quintile", ic)
        
    quintile = len(mean_scores) // 5
    if quintile == 0: quintile = 1
    
    bottom_tickers = mean_scores.iloc[:quintile].index.tolist()
    top_tickers = mean_scores.iloc[-quintile:].index.tolist()
    
    return run_static_factor(
        prices,
        "Price Momentum (12M-1M)",
        top_tickers,
        bottom_tickers,
        "Top Quintile (High Momentum)",
        "Bottom Quintile (Low Momentum)",
        ic_mean=ic
    )

def run_quality_factor(prices: pd.DataFrame, all_tickers: list[str]) -> FactorResult:
    # Proxy for Quality: Low Volatility (12M trailing standard deviation)
    returns_1m = prices.pct_change(fill_method=None)
    
    # We use 12M rolling std of monthly returns as proxy for volatility
    vol_panel = returns_1m.rolling(window=12).std()
    
    # Low vol = high quality, so factor score is negative vol
    factor_panel = -vol_panel.shift(1)[all_tickers]
    
    forward_returns = returns_1m.shift(-1)[all_tickers]
    ic = calculate_rolling_ic(factor_panel, forward_returns)
    
    mean_scores = factor_panel.mean().dropna().sort_values()
    if mean_scores.empty:
        return run_static_factor(prices, "Quality (Low Volatility Proxy)", [], [], "Low Vol", "High Vol", ic)
        
    quintile = len(mean_scores) // 5
    if quintile == 0: quintile = 1
    
    high_vol = mean_scores.iloc[:quintile].index.tolist()
    low_vol = mean_scores.iloc[-quintile:].index.tolist()
    
    return run_static_factor(
        prices,
        "Quality (Low Volatility Proxy)",
        low_vol,
        high_vol,
        "Top Quintile (Low Volatility)",
        "Bottom Quintile (High Volatility)",
        ic_mean=ic
    )
