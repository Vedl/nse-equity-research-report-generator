import pandas as pd
import numpy as np
import joblib
import os
import sys

def calculate_indicators(df):
    """
    Calculate technical indicators matching training data.
    """
    # Ensure sorted
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # 1. RSI (14)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 2. MACD (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    # 3. Bollinger Bands (20, 2)
    rolling_mean = df['close'].rolling(window=20).mean()
    rolling_std = df['close'].rolling(window=20).std()
    df['bb_upper'] = rolling_mean + (rolling_std * 2)
    df['bb_lower'] = rolling_mean - (rolling_std * 2)
    
    # 4. ATR Proxy (14)
    tr = abs(df['close'] - df['close'].shift(1))
    df['atr'] = tr.ewm(alpha=1/14, adjust=False).mean()
    
    return df

def backtest():
    input_file = "ready_for_training.csv"
    model_path = "sniper_brain.pkl"
    scaler_path = "sniper_scaler.pkl"
    
    # Check files
    if not os.path.exists(input_file):
        print(f"[ERROR] Data file {input_file} not found.")
        return
    if not os.path.exists(model_path) or not os.path.exists(scaler_path):
        print("[ERROR] Model or Scaler not found.")
        return

    print(f"[INFO] Loading Data from {input_file}...")
    df = pd.read_csv(input_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    print("[INFO] Calculating Indicators...")
    df = calculate_indicators(df)
    
    # Drop warm-up NaN from indicators (first ~20 rows)
    df.dropna(subset=['rsi', 'macd', 'bb_upper', 'atr'], inplace=True)
    
    print(f"[INFO] Loaded Model: {model_path}")
    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
    
    # Feature Definition
    feature_order = [
        'spot_price', 'vix', 'call_delta', 'put_delta', 
        'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'atr'
    ]
    
    print("\n--- Starting Backtest (Confidence Threshold: 60%) ---")
    signals_found = 0
    
    for i, row in df.iterrows():
        # Construct Feature Vector
        # Hardcodes: VIX=11.0, Deltas +/- 0.5
        features = {
            'spot_price': row['close'],
            'vix': 11.0,
            'call_delta': 0.5,
            'put_delta': -0.5,
            'rsi': row['rsi'],
            'macd': row['macd'],
            'macd_signal': row['macd_signal'],
            'bb_upper': row['bb_upper'],
            'bb_lower': row['bb_lower'],
            'atr': row['atr']
        }
        
        # Convert to DataFrame (1 row) to match Scaler expectations (if named features used)
        # But commonly scaler is numpy array. Strategy.py converts to values.
        # Let's verify how scaler was trained. Typically StandardScaler loses names unless pandas used.
        # Strategy uses: self.scaler.transform(live_df[feature_order].values)
        # We will do the same.
        
        feature_values = [features[col] for col in feature_order]
        X = np.array([feature_values])
        
        # Scale
        X_scaled = scaler.transform(X)
        
        # Predict
        # model.classes_ usually [0, 1] for Hold, Buy
        # predict_proba returns [[prob_0, prob_1]]
        prob_buy = model.predict_proba(X_scaled)[0][1]
        
        if prob_buy > 0.60:
            signals_found += 1
            ts_str = row['timestamp'].strftime('%H:%M')
            print(f"[{ts_str}] 🎯 Signal Found! Price: {row['close']:.2f} | Conf: {prob_buy*100:.1f}%")

    print(f"\n========================================")
    print(f"Total Signals Found: {signals_found}")
    print(f"Total Candles Tested: {len(df)}")
    print(f"========================================")

if __name__ == "__main__":
    backtest()
