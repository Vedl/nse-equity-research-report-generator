import pandas as pd
import numpy as np
import joblib
import os
import sys

def calculate_indicators(df):
    """
    Calculate technical indicators matching training data.
    """
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

def simulate():
    input_file = "ready_for_training.csv"
    model_path = "sniper_brain.pkl"
    scaler_path = "sniper_scaler.pkl"
    
    if not os.path.exists(input_file):
        print(f"[ERROR] {input_file} missing.")
        return

    # Load & Prep
    df = pd.read_csv(input_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = calculate_indicators(df)
    
    # Drop warmup
    df.dropna(subset=['rsi', 'macd', 'bb_upper', 'atr'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # Load AI
    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
    
    # Config
    INITIAL_CAPITAL = 100000.0
    capital = INITIAL_CAPITAL
    LOT_SIZE = 75
    DELTA = 0.5
    COST_PER_TRADE = 150.0
    
    position = None # {'entry_price': float, 'entry_time': timestamp, 'entry_idx': int}
    trades = [] # List of dicts
    
    feature_order = [
        'spot_price', 'vix', 'call_delta', 'put_delta', 
        'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'atr'
    ]
    
    print(f"[INFO] Starting Simulation with ₹{capital:,.2f}")
    
    for i in range(len(df)):
        row = df.iloc[i]
        
        # 1. Manage Open Position (Time-based Exit)
        if position:
            minutes_held = i - position['entry_idx'] # Since 1 row = 1 min
            
            if minutes_held >= 20 or i == len(df) - 1:
                # EXIT
                exit_price = row['close']
                points = exit_price - position['entry_price']
                option_points = points * DELTA
                gross_pnl = option_points * LOT_SIZE
                net_pnl = gross_pnl - COST_PER_TRADE
                
                capital += net_pnl
                
                trade_res = {
                    'entry_time': position['entry_time'],
                    'exit_time': row['timestamp'],
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': net_pnl,
                    'result': 'WIN' if net_pnl > 0 else 'LOSS'
                }
                trades.append(trade_res)
                
                # print(f"  [EXIT] @ {row['timestamp'].strftime('%H:%M')} | PnL: ₹{net_pnl:.2f}")
                position = None
            
            continue # Skip finding new trades if in position
            
        # 2. Look for Entry
        # Construct Features
        features = [
            row['close'], 
            11.0,           # VIX (Bridged)
            0.5,            # Call Delta
            -0.5,           # Put Delta
            row['rsi'],
            row['macd'],
            row['macd_signal'],
            row['bb_upper'],
            row['bb_lower'],
            row['atr']
        ]
        
        X = np.array([features])
        X_scaled = scaler.transform(X)
        prob_buy = model.predict_proba(X_scaled)[0][1]
        
        if prob_buy > 0.70:
            # ENTRY
            position = {
                'entry_price': row['close'],
                'entry_time': row['timestamp'],
                'entry_idx': i
            }
            # print(f"[ENTRY] @ {row['timestamp'].strftime('%H:%M')} | Price: {row['close']:.2f} | Conf: {prob_buy*100:.1f}%")

    # Final Report
    wins = [t for t in trades if t['result'] == 'WIN']
    losses = [t for t in trades if t['result'] == 'LOSS']
    
    total_trades = len(trades)
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
    net_profit = capital - INITIAL_CAPITAL
    
    print("\n" + "="*40)
    print("       SNIPER STRATEGY: P&L REPORT       ")
    print("="*40)
    print(f"Total Trades: {total_trades}")
    print(f"Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Net Profit: ₹{net_profit:,.2f}")
    print("-" * 40)
    print(f"If you ran this today, your ₹1 Lakh would now be ₹{capital:,.2f}.")
    print("="*40)

if __name__ == "__main__":
    simulate()
