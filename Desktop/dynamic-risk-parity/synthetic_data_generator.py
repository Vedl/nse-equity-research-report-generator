import pandas as pd
import numpy as np
from scipy.stats import norm
from database_manager import QuantDatabase
from datetime import datetime, timedelta
import os
from tqdm import tqdm

def black_scholes(S, K, T, r, sigma, option_type="call"):
    """
    Vectorized BSM Formula
    """
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if option_type == "call":
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        delta = norm.cdf(d1)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1
        
    return price, delta

def get_years_to_expiry(timestamp):
    """
    Calculate years to the next Tuesday from a given timestamp.
    """
    # Tuesday = 1
    # Find next Tuesday
    days_ahead = 1 - timestamp.weekday()
    if days_ahead <= 0: # Target is today or past
        # If it's Tuesday (0), we check time for 3:30 PM cutoff?
        # For simplicity in historical data, let's assume if it is Tuesday, it expires today END of day.
        # Or better, just roll to next week if days_ahead < 0.
        # User prompt check: "Calculate years to the next Tuesday".
        # Let's say: Next occurring Tuesday.
        days_ahead += 7
        
    expiry_date = timestamp + timedelta(days=days_ahead)
    expiry_date = expiry_date.replace(hour=15, minute=30, second=0, microsecond=0)
    
    diff = expiry_date - timestamp
    minutes = diff.total_seconds() / 60
    
    # Avoid negative or zero time (assume min 1 min)
    if minutes <= 0:
        minutes = 1
        
    # Trading minutes in a year? Or calendar? Standard BSM uses Calendar years typically.
    years = minutes / (365 * 24 * 60)
    return years

def generate_data():
    db = QuantDatabase()
    
    # 1. Fetch Spot Data
    print("Fetching Spot Data from DB...")
    spot_df = pd.read_sql("SELECT timestamp, price FROM market_ticks WHERE symbol='NIFTY'", db.conn)
    # Handle potentially mixed formats from different backfills
    spot_df['timestamp'] = pd.to_datetime(spot_df['timestamp'], format='mixed')
    spot_df.sort_values('timestamp', inplace=True)
    print(f"Loaded {len(spot_df)} Spot rows.")
    
    # 2. Load VIX CSV
    vix_file = "indvix_training_data.csv"
    if not os.path.exists(vix_file):
        print(f"[ERROR] {vix_file} not found.")
        return

    print("Loading VIX Data...")
    vix_df = pd.read_csv(vix_file)
    # Check Header
    # Expected: 'datetime', 'close' (or 'price')
    # My previous download might have 'close', 'datetime' etc.
    # Let's inspect columns or assume standard
    # data_collector uses: 'close', 'datetime', 'volume', etc.
    if 'close' in vix_df.columns:
        vix_df.rename(columns={'close': 'vix'}, inplace=True)
    
    vix_df['timestamp'] = pd.to_datetime(vix_df['datetime'])
    vix_df.sort_values('timestamp', inplace=True)
    vix_df = vix_df[['timestamp', 'vix']] # Keep only what we need
    print(f"Loaded {len(vix_df)} VIX rows.")
    
    # 3. Merge AsOf
    print("Merging Data...")
    merged_df = pd.merge_asof(spot_df, vix_df, on='timestamp', direction='nearest')
    
    # Drop rows where VIX is NaN (mismatched dates)
    merged_df.dropna(subset=['vix'], inplace=True)
    
    print(f"Merged Data: {len(merged_df)} rows.")

    # 4. Calculations
    print("Calculating BSM Greeks...")
    
    # Strike: Round spot to nearest 50
    merged_df['strike'] = (round(merged_df['price'] / 50) * 50).astype(int)
    
    # Time to Expiry (Vectorized apply)
    tqdm.pandas(desc="Calculating Time")
    merged_df['tte'] = merged_df['timestamp'].progress_apply(get_years_to_expiry)
    
    # Inputs
    S = merged_df['price'].values
    K = merged_df['strike'].values
    T = merged_df['tte'].values
    R = 0.06 # 6% Risk Free Rate assumption
    V = merged_df['vix'].values / 100.0 # VIX is pct
    
    c_price, c_delta = black_scholes(S, K, T, R, V, "call")
    p_price, p_delta = black_scholes(S, K, T, R, V, "put")
    
    merged_df['call_price'] = c_price
    merged_df['put_price'] = p_price
    merged_df['call_delta'] = c_delta
    merged_df['put_delta'] = p_delta
    
    # 5. Prepare for Insert
    # list of tuples: (timestamp, spot, vix, strike, tte, call_price, put_price, call_delta, put_delta)
    print("Preparing Bulk Insert...")
    
    records = []
    for _, row in tqdm(merged_df.iterrows(), total=len(merged_df)):
        records.append((
            str(row['timestamp']), # SQLite stores datetime as string usually
            row['price'],
            row['vix'],
            row['strike'],
            row['tte'],
            row['call_price'],
            row['put_price'],
            row['call_delta'],
            row['put_delta']
        ))
        
    # Insert in chunks of 5000
    chunk_size = 5000
    total_inserted = 0
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i+chunk_size]
        db.insert_synthetic_batch(chunk)
        total_inserted += len(chunk)
        
    print(f"Generated {total_inserted} rows of synthetic options data using minute-level VIX.")
    db.close()

if __name__ == "__main__":
    generate_data()
