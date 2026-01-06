import time
from datetime import datetime
from connector import BreezeClient
from database_manager import QuantDatabase
import utils
import sys

# Global Counters
tick_count = 0
last_summary_time = time.time()

# Global DB and Client
db = None
client = None

def on_ticks(ticks):
    """
    Callback for processing websocket ticks.
    """
    global db, tick_count
    if not db:
        return
        
    try:
        # Standardize input to list
        data_list = ticks if isinstance(ticks, list) else [ticks]
        
        for tick in data_list:
            # Extract Fields
            # Keys might vary slightly, handling common variations
            stock_code = tick.get('stock_code') or tick.get('symbol') or 'UNKNOWN'
            ltp = tick.get('last') or tick.get('ltp')
            vol = tick.get('volume') or tick.get('total_volume') or 0
            oi = tick.get('open_interest') or tick.get('oi') or 0
            
            # Ensure safe types
            if ltp is not None:
                final_ltp = float(ltp)
                final_vol = int(vol) if vol else 0
                final_oi = int(oi) if oi else 0
                
                # Insert immediately
                db.insert_stream_tick(str(stock_code), final_ltp, final_vol, final_oi)
                
                # Console Feedback
                tick_count += 1
                print(".", end="", flush=True)
                
                # Summary every 100 ticks
                if tick_count % 100 == 0:
                    print(f"\n[INFO] Saved {tick_count} ticks... Last: {stock_code} @ {final_ltp}")

    except Exception as e:
        print(f"\n[ERROR] Tick Processing Failed: {e}")

def main():
    global db, client
    
    print("[INFO] Starting Stream Logger (ZERO API LIMIT MODE)...")
    
    # 1. Initialize DB
    try:
        db = QuantDatabase()
        print("[INFO] Database Connected (Table: stream_logs).")
    except Exception as e:
        print(f"[FATAL] DB Init failed: {e}")
        sys.exit(1)

    # 2. Initialize Breeze
    try:
        client = BreezeClient()
        breeze = client.breeze
        print("[INFO] Breeze Client Initialized.")
    except Exception as e:
        print(f"[FATAL] Client Init failed: {e}")
        sys.exit(1)

    # 3. Connect WebSocket
    try:
        breeze.ws_connect()
        breeze.on_ticks = on_ticks
        print("[INFO] WebSocket Connected.")
    except Exception as e:
        print(f"[FATAL] WS Connect failed: {e}")
        sys.exit(1)

    # 4. Subscribe Logic
    # Hardcoded Range: 25800 to 26100 (ATM +/- 3 approx)
    strikes = ['25900', '25950', '26000', '26050', '26100'] # 25800 ... 26100 (Inclusive end needs +50 in range)
    
    # Expiry
    expiry_str = utils.get_next_expiry() # e.g. "02-Jan-2026"
    
    # Convert to ISO for API
    try:
        expiry_dt = datetime.strptime(expiry_str.title(), "%d-%b-%Y")
        expiry_iso = expiry_dt.strftime("%Y-%m-%dT06:00:00.000Z")
        print(f"[INFO] Target Expiry: {expiry_iso}")
    except Exception as e:
        print(f"[ERROR] Date conversion failed: {e}")
        sys.exit(1)

    # Subscribe NIFTY SPOT
    try:
        breeze.subscribe_feeds(stock_code="NIFTY", exchange_code="NSE", product_type="cash", right="others", strike_price="0", expiry_date="")
        print("[SUB] Subscribed to NIFTY Spot.")
    except Exception as e:
        print(f"[WARN] Spot Subscribe failed: {e}")

    # Subscribe OPTIONS
    count = 0
    for strike in strikes:
        for right in ["Call", "Put"]:
            try:
                breeze.subscribe_feeds(
                    exchange_code="NFO",
                    stock_code="NIFTY",
                    product_type="options",
                    expiry_date=expiry_iso,
                    strike_price=str(strike),
                    right=right
                )
                count += 1
                # Tiny sleep to avoid overwhelming the subscription request queue if library is sensitive
                time.sleep(0.05) 
            except Exception as e:
                print(f"[WARN] Failed to subscribe {strike} {right}: {e}")
    
    print(f"[INFO] Subscribed to {count} Option Contracts (25800-26100).")
    print("------------------------------------------------")
    print("[RUNNING] Listening for ticks... (Dots indicate data)")

    # 5. Keep Alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Stopping Logger...")
        sys.exit(0)

if __name__ == "__main__":
    main()
