import sqlite3
import pandas as pd
from database_manager import QuantDatabase

def inspect():
    db_path = "quant_lab.db"
    conn = sqlite3.connect(db_path)
    
    print(f"[INFO] Inspecting {db_path}...\n")
    
    # 1. Option Chain Logs
    try:
        df_chain = pd.read_sql("SELECT * FROM option_chain_logs", conn)
        print(f"--- table: option_chain_logs ---")
        print(f"Total Rows: {len(df_chain)}")
        if not df_chain.empty:
            print("\nFirst 5 Rows (Timestamps):")
            print(df_chain[['timestamp', 'strike_price', 'right', 'ltp']].head().to_string(index=False))
            print("\nLast 5 Rows (Timestamps):")
            print(df_chain[['timestamp', 'strike_price', 'right', 'ltp']].tail().to_string(index=False))
            
            # Check for unique timestamps
            unique_ts = df_chain['timestamp'].nunique()
            print(f"\nUnique Snapshots (Timestamps): {unique_ts}")
    except Exception as e:
        print(f"[ERROR] Could not read option_chain_logs: {e}")

    print("\n" + "="*30 + "\n")

    # 2. Synthetic Options
    try:
        df_synth = pd.read_sql("SELECT * FROM synthetic_options", conn)
        print(f"--- table: synthetic_options ---")
        print(f"Total Rows: {len(df_synth)}")
    except Exception as e:
        print(f"[ERROR] Could not read synthetic_options: {e}")

    conn.close()

if __name__ == "__main__":
    inspect()
