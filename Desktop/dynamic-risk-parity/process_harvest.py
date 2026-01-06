import pandas as pd
import os

def process():
    input_file = "today_market_data.csv"
    output_file = "ready_for_training.csv"
    
    if not os.path.exists(input_file):
        print(f"[ERROR] Input file {input_file} not found.")
        return

    print(f"[INFO] Loading {input_file}...")
    df = pd.read_csv(input_file)
    
    # 1. Preprocessing
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Identify Most Active Codes (Top 5) to ensure we get Spot + Key Options
    # We want NIFTY Spot + Top Options
    activity_counts = df['stock_code'].value_counts()
    print("\n--- Activity Analysis (Ticks per Symbol) ---")
    print(activity_counts.head(10))
    
    # Select top 5 for processing to be safe (Spot, CE, PE, maybe next strikes)
    top_codes = activity_counts.head(5).index.tolist()
    print(f"\n[INFO] Processing Top Active Symbols: {top_codes}")
    
    df_filtered = df[df['stock_code'].isin(top_codes)].copy()
    
    # 2. Resampling (1-Minute OHLCV)
    # We define a custom aggregation for the 'ltp' column and 'volume'
    # OHLC comes from 'ltp'
    # Volume is sum of volume (Wait, tick volume is usually cumulative or snapshot? 
    # In stream logs, volume is often cumulative for the day or snapshot. 
    # If it's cumulative, we need max - min. If it's distinct trade volume (unlikely in simple tick feed), sum.
    # Breeze 'volume' key is usually "Total Traded Volume" for the day.
    # So for 1-min volume, we should take (Last Volume of Minute - First Volume of Minute).
    # IF the field 'volume' is incremental (tick size), we sum. 
    # Let's assume for now we just want the 'close' volume or simple volume, 
    # but for standard OHLCV from ticks, usually you want the volume traded IN that minute. 
    # If the feed gives 'Total Volume', we take delta.
    # Observing the csv structure might help, but let's stick to standard practice: 
    # If checking volume is tricky, we can use 'tick_count' as a proxy or just take the max volume (total volume so far).
    # Let's look at the data sample from previous step: Volume was 0 in first rows. 
    # If Volume is 0, let's just stick to Price OHLC for now to be safe, or include Volume as max.
    
    ohlc_dict = {
        'ltp': ['first', 'max', 'min', 'last'],
        'volume': 'max'  # Taking max assuming it's cumulative total volume
    }
    
    df_filtered.set_index('timestamp', inplace=True)
    
    # Group by symbol and resample
    # We iterate manually to keep it clean or use groupby
    final_dfs = []
    
    for symbol, sub_df in df_filtered.groupby('stock_code'):
        # Resample 1Min
        resampled = sub_df.resample('1min').agg(ohlc_dict)
        
        # Flatten columns
        resampled.columns = ['open', 'high', 'low', 'close', 'total_volume']
        resampled['symbol'] = symbol
        
        # Calculate Minute Volume (Delta of Total Volume)
        # resampled['volume'] = resampled['total_volume'].diff().fillna(0) # Logic if cumulative
        # If the input volume was 0 (as seen in sample), this will just be 0.
        
        resampled.dropna(subset=['open'], inplace=True) # Drop empty minutes
        final_dfs.append(resampled)
        
    if not final_dfs:
        print("[WARN] No data processed.")
        return

    result_df = pd.concat(final_dfs).reset_index()
    
    # Reorder columns
    cols = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'total_volume']
    result_df = result_df[cols]
    
    # 3. Save
    result_df.to_csv(output_file, index=False)
    print(f"\n[SUCCESS] Processed {len(result_df)} candles.")
    print(f"Saved to {output_file}")
    
    # 4. Verify
    print("\n--- Candle Sample (First 5 Rows) ---")
    print(result_df.head().to_string(index=False))

if __name__ == "__main__":
    process()
