import pandas as pd
from scipy.stats import spearmanr

def calculate_ic(factor_scores: pd.Series, forward_returns: pd.Series) -> float:
    """Calculate the Information Coefficient (Spearman rank correlation) 
    between factor scores and forward returns for a single period.
    """
    # Align the data
    df = pd.DataFrame({'factor': factor_scores, 'ret': forward_returns}).dropna()
    if len(df) < 10:
        return 0.0
    
    correlation, _ = spearmanr(df['factor'], df['ret'])
    return float(correlation) if not pd.isna(correlation) else 0.0

def calculate_rolling_ic(factor_panel: pd.DataFrame, forward_returns_panel: pd.DataFrame) -> float:
    """Calculate the average IC over all periods.
    factor_panel and forward_returns_panel should be Date x Tickers DataFrames.
    """
    ics = []
    # Ensure indices match
    common_dates = factor_panel.index.intersection(forward_returns_panel.index)
    
    for dt in common_dates:
        scores = factor_panel.loc[dt]
        fwd_ret = forward_returns_panel.loc[dt]
        ic = calculate_ic(scores, fwd_ret)
        ics.append(ic)
        
    if not ics:
        return 0.0
    
    # Return the mean IC
    return sum(ics) / len(ics)
