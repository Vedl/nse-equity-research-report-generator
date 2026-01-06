import sqlite3
import pandas as pd
from datetime import datetime

def check_pnl():
    db_path = "quant_lab.db"
    
    print("------------------------------------------------")
    print("       🔍 QUANT LAB: SESSION AUDIT REPORT       ")
    print("------------------------------------------------")
    
    try:
        conn = sqlite3.connect(db_path)
        
        # Query for Today's Trades
        query = """
            SELECT * FROM trades 
            WHERE date(timestamp) = date('now', 'localtime')
            ORDER BY timestamp DESC
        """
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            print("\n💤 STATUS: NO TRADES EXECUTED TODAY (Capital Preserved).")
            print("   The Sniper is waiting for the perfect shot.")
            print("\n------------------------------------------------")
            return

        # Process Data
        # Ensure timestamp is datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Calculate Stats
        total_trades = len(df)
        total_pnl = df['pnl'].sum()
        winners = len(df[df['pnl'] > 0])
        losers = len(df[df['pnl'] <= 0])
        
        # Display DataFrame (Selected Columns)
        display_cols = ['timestamp', 'symbol', 'action', 'price', 'pnl']
        print(f"\n[INFO] Found {total_trades} Trades:")
        
        # Check if columns exist (legacy db might differ)
        available_cols = [c for c in display_cols if c in df.columns]
        print(df[available_cols].to_string(index=False))
        
        print("\n" + "="*30)
        print(f"📊 SESSION P&L: ₹{total_pnl:,.2f}")
        print("="*30)
        print(f"   Win Rate: {(winners/total_trades*100):.1f}% ({winners} W / {losers} L)")
        
    except sqlite3.OperationalError as e:
        if "no such table: trades" in str(e):
             print("\n💤 STATUS: NO TRADES YET (Database New).")
        else:
             print(f"\n[ERROR] Database Error: {e}")
    except Exception as e:
        print(f"\n[ERROR] Audit Failed: {e}")
    finally:
        print("\n------------------------------------------------")

if __name__ == "__main__":
    check_pnl()
