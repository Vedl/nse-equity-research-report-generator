import pandas as pd
import numpy as np
from database_manager import QuantDatabase

# Actually, implementing indicators from scratch in pandas is safer than downloading new libs if not in requirements.
# I will implement manually to avoid "ModuleNotFoundError".

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    # Wilder's Smoothing (Standard RSI) usually uses Exponential Moving Average, but simple rolling mean is often used in basic variations.
    # Let's use standard EMA for Wilder's? 
    # Actually, the standard RSI formula often uses (PreviousAvg * 13 + Current) / 14.
    # For simplicity and speed in "pandas", standard EWMA is good.
    
    gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/period, adjust=False).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

def calculate_bollinger_bands(series, window=20, num_std=2):
    rolling_mean = series.rolling(window=window).mean()
    rolling_std = series.rolling(window=window).std()
    upper = rolling_mean + (rolling_std * num_std)
    lower = rolling_mean - (rolling_std * num_std)
    return upper, lower

def calculate_atr_proxy(price_series, window=14):
    """
    True ATR requires High/Low. 
    Since we only have Spot Price (Close), we use Volatility based on Absolute Changes.
    TR approx = abs(Close - PrevClose)
    """
    prev_close = price_series.shift(1)
    tr = abs(price_series - prev_close)
    atr = tr.ewm(alpha=1/window, adjust=False).mean()
    return atr

def add_indicators():
    print("[INFO] Connecting to Database...")
    db = QuantDatabase()
    
    # 1. Load Data
    print("[INFO] Fetching synthetic_options...")
    df = pd.read_sql("SELECT * FROM synthetic_options ORDER BY timestamp ASC", db.conn)
    
    if len(df) == 0:
        print("[ERROR] Table is empty!")
        return

    print(f"[INFO] Loaded {len(df)} rows. Calculating indicators...")
    
    # Ensure numerical
    price = df['spot_price']
    
    # 2. Calculate Indicators
    
    # RSI
    df['rsi'] = calculate_rsi(price)
    
    # MACD
    df['macd'], df['macd_signal'] = calculate_macd(price)
    
    # Bollinger Bands
    df['bb_upper'], df['bb_lower'] = calculate_bollinger_bands(price)
    
    # ATR (Proxy)
    df['atr'] = calculate_atr_proxy(price)
    
    # Fill NaNs (result of rolling windows)
    # Forward fill or 0? 
    # For NN, 0 or mean is better than dropping 8000 rows? 
    # Rolling(26) creates 26 NaNs. It's fine to drop or fill.
    # Let's bfill (backfill) to preserve data size, or just fill with 0.
    df.bfill(inplace=True)
    df.fillna(0, inplace=True)
    
    print("[INFO] Indicators calculated.")
    
    # 3. Update Database
    # We will replace the table to ensure schema update
    print("[INFO] Updating columns in Database...")
    
    try:
        # Use pandas to_sql to replace the table with the new schema
        # index=False because we don't want to write the pandas index, 
        # but we DO want to keep the existing 'id'? 
        # 'id' is in the DF because we did SELECT *.
        # So we write it back.
        
        df.to_sql('synthetic_options', db.conn, if_exists='replace', index=False)
        print("Indicators added. Database enriched with Momentum and Trend data.")
        
    except Exception as e:
        print(f"[ERROR] Failed to update table: {e}")
        
    db.close()

if __name__ == "__main__":
    add_indicators()
