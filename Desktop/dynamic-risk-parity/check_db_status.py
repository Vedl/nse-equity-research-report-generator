from database_manager import QuantDatabase
import pandas as pd

def check_status():
    db = QuantDatabase()
    
    print("Checking 'option_chain_logs' table...")
    try:
        query = "SELECT COUNT(*) FROM option_chain_logs"
        cursor = db.conn.cursor()
        cursor.execute(query)
        count = cursor.fetchone()[0]
        print(f"Total Rows: {count}")
        
        if count > 0:
            print("\nLatest 5 Entries:")
            df = pd.read_sql_query("SELECT * FROM option_chain_logs ORDER BY id DESC LIMIT 5", db.conn)
            print(df)
            
            # Verify Strikes count for the last logged batch
            print("\nVerifying Strike Count for latest batch...")
            # Get latest timestamp
            latest_ts = df.iloc[0]['timestamp'] 
            # We assume batch is within the same second/minute roughly
            # Let's just group by timestamp roughly or pick the last minute
            
            query_distinct = f"SELECT count(DISTINCT strike_price) FROM option_chain_logs WHERE timestamp > datetime('{latest_ts}', '-1 minute')"
            cursor.execute(query_distinct)
            strikes_count = cursor.fetchone()[0]
            print(f"Distinct Strikes Logged in last minute: {strikes_count}")
            
            # Show the strikes
            query_strikes = f"SELECT DISTINCT strike_price FROM option_chain_logs WHERE timestamp > datetime('{latest_ts}', '-1 minute')"
            cursor = db.conn.execute(query_strikes)
            print("Strikes list:", [row[0] for row in cursor.fetchall()])
        else:
            print("[WARN] Table is empty!")
            
    except Exception as e:
        print(f"[ERROR] Query failed: {e}")
        
    db.close()

if __name__ == "__main__":
    check_status()
