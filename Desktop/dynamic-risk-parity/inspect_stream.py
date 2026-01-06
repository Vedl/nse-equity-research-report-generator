import sqlite3
import pandas as pd
import os

def inspect():
    db_path = "quant_lab.db"
    
    if not os.path.exists(db_path):
        print(f"[ERROR] Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    print(f"[INFO] Analyzing {db_path} (Table: stream_logs)...\n")
    
    try:
        # Load Data
        df = pd.read_sql("SELECT * FROM stream_logs ORDER BY timestamp ASC", conn)
        
        if df.empty:
            print("[WARN] No data found in stream_logs.")
            return
            
        # 1. Count
        total_ticks = len(df)
        print(f"Total Ticks Captured: {total_ticks}")
        
        # 2. Time Check
        start_time = df['timestamp'].iloc[0]
        end_time = df['timestamp'].iloc[-1]
        print(f"Start Time: {start_time}")
        print(f"End Time:   {end_time}")
        
        # 3. Data Quality (First 5 Rows)
        print("\n--- Data Sample (First 5 Rows) ---")
        print(df.head().to_string(index=False))
        
        # 4. Export
        csv_filename = "today_market_data.csv"
        df.to_csv(csv_filename, index=False)
        print(f"\n[SUCCESS] Data exported to {csv_filename}")
        
    except Exception as e:
        print(f"[ERROR] Inspection failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    inspect()
