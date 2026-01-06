import pandas as pd
import numpy as np
from database_manager import QuantDatabase
from tqdm import tqdm

def create_smart_targets():
    print("[INFO] Connecting to Database...")
    db = QuantDatabase()
    
    # 1. Load Data
    query = "SELECT * FROM synthetic_options ORDER BY timestamp ASC"
    df = pd.read_sql(query, db.conn)
    
    print(f"[INFO] Loaded {len(df)} rows.")
    
    # Needs numerical spot_price
    prices = df['spot_price'].values
    
    # Parameters
    # Upper Barrier (Profit): +0.10% -> 1.0010
    # Lower Barrier (Stop): -0.05% -> 0.9995
    # Vertical Barrier (Time): 20 minutes (rows)
    
    UPPER_PCT = 0.0010
    LOWER_PCT = 0.0005
    TIME_HORIZON = 20
    
    targets = []
    
    print("[INFO] labeling data (Triple Barrier Method)...")
    
    for i in tqdm(range(len(prices))):
        current_price = prices[i]
        
        # End of data check
        if i + 1 >= len(prices):
            targets.append(0)
            continue
            
        # Define window
        end_idx = min(i + 1 + TIME_HORIZON, len(prices))
        future_prices = prices[i+1 : end_idx]
        
        # Barriers
        upper_barrier = current_price * (1 + UPPER_PCT)
        lower_barrier = current_price * (1 - LOWER_PCT)
        
        # Check logic
        # 1. Did we hit upper barrier?
        # 2. Did we hit lower barrier?
        # 3. Which happened first?
        
        # Indices where condition met
        # (This is relative to the slice `future_prices`)
        hit_upper = np.where(future_prices >= upper_barrier)[0]
        hit_lower = np.where(future_prices <= lower_barrier)[0]
        
        first_upper = hit_upper[0] if len(hit_upper) > 0 else 9999
        first_lower = hit_lower[0] if len(hit_lower) > 0 else 9999
        
        if first_upper == 9999 and first_lower == 9999:
            # Reached vertical barrier (Time limit) without hitting either
            # Label 0 (Ignored/Hold - or treat as 0 per instructions "If price hits Lower Barrier OR Time Limit first -> Label 0")
            targets.append(0)
            
        elif first_lower < first_upper:
            # Hit Stop Loss first
            targets.append(0)
            
        elif first_upper < first_lower:
            # Hit Profit first
            targets.append(1)
        else:
            # Should not happen unless both 9999 (handled) or same index (impossible unless gap logic flawed)
            targets.append(0)
            
    df['target'] = targets
    
    # Stats
    balance = df['target'].value_counts(normalize=True)
    print("\n[RESULTS] Class Balance:")
    print(balance)
    print(f"Buys: {balance.get(1, 0)*100:.2f}%, Others: {balance.get(0, 0)*100:.2f}%")
    
    # Select Columns for Smart Data
    # features (Spot, VIX, Delta, RSI, MACD, etc.) + target
    # Keep timestamp for ordering/lookback if needed
    cols_to_keep = ['timestamp', 'spot_price', 'vix', 'call_delta', 'put_delta', 
                    'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'atr', 'target']
    
    # Filter only existing columns
    cols_to_keep = [c for c in cols_to_keep if c in df.columns]
    
    smart_df = df[cols_to_keep].copy()
    
    # Save to New Table
    print("[INFO] Saving to table 'smart_training_data'...")
    try:
        smart_df.to_sql('smart_training_data', db.conn, if_exists='replace', index=False)
        print("[SUCCESS] Smart Labels created and saved.")
    except Exception as e:
        print(f"[ERROR] Save failed: {e}")
        
    db.close()

if __name__ == "__main__":
    create_smart_targets()
