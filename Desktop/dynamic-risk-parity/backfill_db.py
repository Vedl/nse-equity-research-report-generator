import pandas as pd
from database_manager import QuantDatabase
import os
from tqdm import tqdm

def backfill():
    csv_file = "nifty_training_data.csv"
    
    if not os.path.exists(csv_file):
        print(f"File {csv_file} not found.")
        return

    print("Loading data...")
    df = pd.read_csv(csv_file)
    
    # Check columns
    # Expected: datetime, open, high, low, close, volume (or similar)
    print(f"Columns found: {df.columns.tolist()}")
    
    # Initialize DB
    db = QuantDatabase()
    
    # 1. Fetch existing timestamps to prevent duplicates
    print("Checking existing data in DB...")
    with db.lock:
        cursor = db.conn.cursor()
        cursor.execute("SELECT timestamp FROM market_ticks WHERE symbol='NIFTY'")
        existing_rows = cursor.fetchall()
    
    # Convert to set for O(1) lookup. DB timestamps might be strings or datetime objects depending on SQLite adapter.
    # Usually they come out as strings 'YYYY-MM-DD HH:MM:SS.ssssss'
    existing_timestamps = set([str(row[0]) for row in existing_rows])
    
    print(f"Found {len(existing_timestamps)} existing rows.")
    
    print("Starting backfill...")
    count = 0
    skipped = 0
    
    # Iterate
    for index, row in tqdm(df.iterrows(), total=len(df)):
        # Mapping
        # Use 'close' as 'price'
        price = row.get('close')
        volume = row.get('volume', 0)
        timestamp = str(row.get('datetime')) # Ensure string format matches DB default
        
        # Check duplicate
        # Note: We need to be careful about format matching. 
        # API might give '2025-12-29 10:00:00', DB might have '2025-12-29 10:00:00.000000'.
        # For robustness, we could compare as datetime objects, but string exact match checks if exact same data source.
        # Let's try basic inclusion.
        
        if timestamp in existing_timestamps:
            skipped += 1
            continue
            
        # Ensure we have a timestamp
        if timestamp:
            db.insert_tick(symbol="NIFTY", price=price, volume=volume, timestamp=timestamp)
            count += 1
            
    print(f"Backfill Complete: {count} new rows inserted. ({skipped} duplicates skipped).")
    db.close()

if __name__ == "__main__":
    backfill()
