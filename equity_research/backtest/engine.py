import logging
import math
import pandas as pd
import yfinance as yf
from pathlib import Path

from equity_research.backtest.models import FactorResult, BacktestResult

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "backtest_cache"
CACHE_FILE = CACHE_DIR / "monthly_prices.pkl"
NIFTY500_CSV = Path(__file__).parent.parent / "data" / "nifty500_tickers.csv"
RF_RATE = 0.068

def _calc_cagr(start_val: float, end_val: float, years: float) -> float:
    if start_val <= 0 or years <= 0:
        return 0.0
    return (end_val / start_val) ** (1 / years) - 1.0

def _calc_max_drawdown(cum_returns: pd.Series) -> float:
    rolling_max = cum_returns.cummax()
    drawdowns = (cum_returns - rolling_max) / rolling_max
    return float(drawdowns.min())

def _calc_sharpe(returns: pd.Series, risk_free: float = RF_RATE) -> float:
    mean_ret = returns.mean()
    std_ret = returns.std()
    if std_ret == 0 or pd.isna(std_ret):
        return 0.0
    return float((mean_ret - risk_free) / std_ret)

def fetch_historical_prices(force_refresh: bool = False) -> pd.DataFrame:
    if not force_refresh and CACHE_FILE.exists():
        logger.info("Loading backtest price data from cache.")
        return pd.read_pickle(CACHE_FILE)
        
    logger.info("Downloading historical prices for Nifty 500...")
    try:
        df_tickers = pd.read_csv(NIFTY500_CSV, dtype=str)
        tickers = df_tickers['ticker'].dropna().tolist()
    except Exception as e:
        logger.error(f"Failed to load Nifty 500 tickers: {e}")
        tickers = []
        
    tickers.append("^NSEI")
    
    try:
        data = yf.download(tickers, period="max", interval="1mo", progress=False, ignore_tz=True)
        if isinstance(data.columns, pd.MultiIndex):
            if 'Close' in data.columns.levels[0]:
                prices = data['Close']
            else:
                # Fallback if something weird happens
                prices = data.xs('Close', level=0, axis=1, drop_level=True) if 'Close' in data.columns else data
        else:
            prices = data
            
        prices = prices.dropna(how='all')
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        prices.to_pickle(CACHE_FILE)
        return prices
    except Exception as e:
        logger.error(f"Failed to download prices: {e}")
        return pd.DataFrame()

def run_static_factor(
    prices: pd.DataFrame, 
    factor_name: str, 
    long_tickers: list[str], 
    short_tickers: list[str], 
    long_label: str, 
    short_label: str,
    ic_mean: float | None = None
) -> FactorResult:
    """Backtest a static factor basket vs a short basket vs benchmark."""
    benchmark = "^NSEI"
    
    valid_long = [t for t in long_tickers if t in prices.columns]
    valid_short = [t for t in short_tickers if t in prices.columns]
    
    returns = prices.pct_change(fill_method=None)
    
    long_ret = returns[valid_long].mean(axis=1) if valid_long else pd.Series(0, index=returns.index)
    short_ret = returns[valid_short].mean(axis=1) if valid_short else pd.Series(0, index=returns.index)
    bench_ret = returns[benchmark] if benchmark in returns.columns else pd.Series(0, index=returns.index)
    
    df_ret = pd.DataFrame({
        'Long': long_ret,
        'Short': short_ret,
        'Benchmark': bench_ret
    }).dropna(subset=['Benchmark'])
    
    df_ret = df_ret.loc['2005-01-01':]
    if df_ret.empty:
        raise ValueError("Not enough data to run backtest.")
    
    df_ret.index = pd.to_datetime(df_ret.index)
    df_ret['Year'] = df_ret.index.year
    annual_ret = df_ret.groupby('Year').apply(lambda x: (1 + x[['Long', 'Short', 'Benchmark']]).prod() - 1)
    
    cum_ret = (1 + df_ret[['Long', 'Short', 'Benchmark']]).cumprod()
    years = (df_ret.index[-1] - df_ret.index[0]).days / 365.25
    
    long_cagr = _calc_cagr(1.0, float(cum_ret['Long'].iloc[-1]), years) if len(cum_ret) > 0 else 0.0
    short_cagr = _calc_cagr(1.0, float(cum_ret['Short'].iloc[-1]), years) if len(cum_ret) > 0 else 0.0
    bench_cagr = _calc_cagr(1.0, float(cum_ret['Benchmark'].iloc[-1]), years) if len(cum_ret) > 0 else 0.0
    
    annual_ret['Spread'] = annual_ret['Long'] - annual_ret['Short']
    hit_rate = float((annual_ret['Spread'] > 0).mean()) if not annual_ret.empty else 0.0
    spread_cagr = long_cagr - short_cagr
    
    monthly_rf = (1 + RF_RATE)**(1/12) - 1
    long_sharpe = _calc_sharpe(df_ret['Long'], monthly_rf) * math.sqrt(12)
    short_sharpe = _calc_sharpe(df_ret['Short'], monthly_rf) * math.sqrt(12)
    
    spread_series = df_ret['Long'] - df_ret['Short']
    spread_sharpe = _calc_sharpe(spread_series, 0) * math.sqrt(12)
    
    return FactorResult(
        factor_name=factor_name,
        long_label=long_label,
        short_label=short_label,
        period_start=df_ret.index[0].strftime("%Y-%m"),
        period_end=df_ret.index[-1].strftime("%Y-%m"),
        long_annual_returns=annual_ret['Long'].tolist(),
        short_annual_returns=annual_ret['Short'].tolist(),
        benchmark_annual_returns=annual_ret['Benchmark'].tolist(),
        spread_annual_returns=annual_ret['Spread'].tolist(),
        long_cagr=long_cagr,
        short_cagr=short_cagr,
        benchmark_cagr=bench_cagr,
        spread_cagr=spread_cagr,
        long_sharpe=long_sharpe,
        short_sharpe=short_sharpe,
        spread_sharpe=spread_sharpe,
        max_drawdown_long=_calc_max_drawdown(cum_ret['Long']),
        max_drawdown_short=_calc_max_drawdown(cum_ret['Short']),
        hit_rate=hit_rate,
        ic_mean=ic_mean,
        cumulative_dates=cum_ret.index.strftime("%Y-%m").tolist(),
        cumulative_long=cum_ret['Long'].tolist(),
        cumulative_short=cum_ret['Short'].tolist(),
        cumulative_benchmark=cum_ret['Benchmark'].tolist()
    )
