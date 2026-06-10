from __future__ import annotations

import pandas as pd
from pathlib import Path

from equity_research.backtest.models import BacktestResult, FactorResult
from equity_research.backtest.engine import fetch_historical_prices, run_static_factor, NIFTY500_CSV
from equity_research.backtest.factors import run_momentum_factor, run_quality_factor
from equity_research.analysis.india_valuation import _PSU_TICKERS, _GROUP_MAPPING

def run_backtest(force_refresh: bool = False) -> BacktestResult:
    """Execute the full backtesting suite on India Valuation factors."""
    prices = fetch_historical_prices(force_refresh)
    if prices.empty:
        raise ValueError("Failed to fetch historical prices for backtest.")
        
    df_tickers = pd.read_csv(NIFTY500_CSV, dtype=str)
    all_tickers = df_tickers['ticker'].dropna().tolist()
    
    # Structural Factor 1: PSU Discount
    psu_tickers = [t + ".NS" if not t.endswith(".NS") else t for t in _PSU_TICKERS]
    non_psu_tickers = [t for t in all_tickers if t not in psu_tickers]
    
    f1 = run_static_factor(
        prices, 
        factor_name="PSU Discount Hypothesis", 
        long_tickers=non_psu_tickers, 
        short_tickers=psu_tickers,
        long_label="Non-PSU (Private)", 
        short_label="PSU (Government)",
        ic_mean=None
    )
    
    # Structural Factor 2: Business Group Alpha
    premium_groups = ["Tata", "Mahindra", "Bajaj", "Godrej"]
    premium_bases = [k for k, v in _GROUP_MAPPING.items() if v in premium_groups]
    premium_tickers = [t + ".NS" if not t.endswith(".NS") else t for t in premium_bases]
    
    f2 = run_static_factor(
        prices, 
        factor_name="Business Group Alpha", 
        long_tickers=premium_tickers, 
        short_tickers=non_psu_tickers,
        long_label="Premium Groups (Tata/Bajaj/Mahindra)", 
        short_label="Broad Private Sector",
        ic_mean=None
    )
    
    # Dynamic Factor 3: Momentum
    f3 = run_momentum_factor(prices, all_tickers)
    
    # Dynamic Factor 4: Quality (Low Volatility Proxy)
    f4 = run_quality_factor(prices, all_tickers)
    
    return BacktestResult(
        universe_size=len(all_tickers),
        stocks_with_history=len(prices.columns) - 1, # minus benchmark
        backtest_start=f1.period_start,
        backtest_end=f1.period_end,
        benchmark="Nifty 50 (^NSEI)",
        rebalance_frequency="Monthly (Equal Weighted) for Dynamic",
        factors=[f1, f2, f3, f4],
        caveats=[
            "Survivorship bias: only currently-listed Nifty 500 stocks included.",
            "Fundamental factors (P/E, P/B) excluded due to 5Y max fundamental data limit.",
            "Static classification: PSU/group status applied retrospectively.",
            "No transaction costs, taxes, or market impact modeled.",
            "Equal-weighted static portfolios for visual demonstration."
        ],
        methodology_notes=[
            "Returns calculated using monthly adjusted close prices.",
            "Sharpe ratios use a 6.8% risk-free rate assumption.",
            "IC Analysis (Spearman Rank) performed dynamically on forward 1M returns.",
            "Data source: Yahoo Finance historical price database."
        ]
    )
