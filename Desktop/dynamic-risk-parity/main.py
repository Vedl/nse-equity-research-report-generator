"""
CHANGELOG (Step 7: Scheduled Reconciliation + Startup Check):
1. Added startup reconciliation check - exits with error if broker/DB mismatch detected
2. Implemented scheduled background reconciliation thread (every 5 minutes)
3. Runtime halt flag toggling - sets strategy.trading_halted on mismatch (exits still allowed)
4. Graceful shutdown handling with daemon thread
5. Comprehensive logging for reconciliation events
6. Passes QuantDatabase instance to strategy for PositionManager integration
"""

import time
import sys
import threading
from datetime import datetime
from connector import BreezeClient
from strategy import MLStrategy
from database_manager import QuantDatabase
from position_manager import PositionManager
from reconciliation import Reconciliator
import utils

# Global instances
client = None
strategy = None
db = None
position_manager = None
reconciliator = None
stock_code = "NIFTY"  # NIFTY 50

def on_ticks(ticks):
    """
    Callback function to handle incoming websocket ticks.
    """
    global client, strategy, db
    
    # 'ticks' is usually a dict or list of dicts. 
    # Adjust parsing based on actual response structure.
    # Example structure: {'symbol': 'NIFTY', 'ltp': 19450, ...}
    
    # print(f\"[DEBUG] Tick received: {ticks}\") # Uncomment for verbose logging
    
    current_price = float(ticks.get('last', 0))
    current_vol = int(ticks.get('volume', 0) or 0) # Handle None or missing volume
    
    # Sync to DB
    if db:
        db.insert_tick(stock_code, current_price, current_vol)

    # 1. Pass data to Strategy
    signal_data = strategy.generate_signal(ticks)
    
    # signal_data is now a dict: {'signal': int, 'action': str, 'right': str, 'strike': str}
    signal_val = signal_data.get('signal', 0)
    
    if signal_val != 0:
        # Action required (Entry or Exit)
        action = signal_data.get('action')
        right = signal_data.get('right')
        strike = signal_data.get('strike')
        pnl = signal_data.get('pnl', 0.0)
        
        # Calculate Expiry Dynamically
        expiry = utils.get_next_expiry()
        
        # Log Trade to DB
        if db:
            trade_record = {
                'symbol': stock_code,
                'action': action,
                'quantity': 50,
                'price': current_price,
                'pnl': pnl,
                'strategy_signal': signal_val
            }
            db.log_trade(trade_record)
        
        client.place_order(
            stock_code=stock_code,
            action=action, 
            quantity=50, 
            price=current_price,
            product_type="options",
            right=right,
            strike_price=strike,
            expiry_date=expiry
        )


def reconciliation_task():
    """
    Background thread that runs reconciliation every 5 minutes.
    
    On mismatch:
    - Sets trading_halted flag on strategy (blocks new entries)
    - Does NOT exit process (allows exits to continue)
    
    On OK:
    - Clears trading_halted flag
    """
    global reconciliator, strategy
    
    while True:
        try:
            time.sleep(300)  # 5 minutes
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{timestamp}] Running scheduled reconciliation...")
            
            result = reconciliator.reconcile()
            status = result.get('status', 'UNKNOWN')
            
            if status == 'MISMATCH':
                discrepancies = result.get('discrepancies', [])
                print(f"[{timestamp}] ⚠️  RECONCILIATION MISMATCH DETECTED")
                print(f"               Discrepancies: {len(discrepancies)}")
                for disc in discrepancies[:3]:  # Show first 3
                    print(f"               - {disc}")
                
                # Set runtime halt flag on strategy
                if strategy and hasattr(strategy, 'trading_halted'):
                    strategy.trading_halted = True
                    print(f"[{timestamp}] 🛑 Strategy trading_halted set to True (new entries blocked)")
                elif strategy:
                    # Attribute doesn't exist, create it
                    strategy.trading_halted = True
                    print(f"[{timestamp}] 🛑 Strategy trading_halted attribute created and set to True")
                
                # Ensure system_state persisted (reconciliator already does this in handle_mismatch)
                reconciliator.set_system_state('trading_halted', 'true')
                
                print(f"[{timestamp}] ℹ️  NOTE: Exits are still allowed, only new entries blocked")
                
            elif status == 'OK':
                print(f"[{timestamp}] ✓ Reconciliation OK: Broker and DB in sync")
                
                # Clear runtime halt if it was set
                if strategy and hasattr(strategy, 'trading_halted'):
                    if strategy.trading_halted:
                        strategy.trading_halted = False
                        reconciliator.set_system_state('trading_halted', 'false')
                        print(f"[{timestamp}] ✓ Trading resumed (halt flag cleared)")
            
            else:
                print(f"[{timestamp}] ⚠️  Reconciliation status: {status}")
        
        except Exception as e:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] ❌ Reconciliation thread error: {e}")
            # Don't crash the thread, continue scheduling


def startup_reconciliation_check():
    """
    Critical startup check: ensure broker/DB are in sync before starting trading.
    
    If mismatch detected:
    - Print critical error
    - Exit process with code 1 (do NOT start trading)
    
    If OK:
    - Continue to trading loop
    """
    global reconciliator
    
    print("\n" + "="*70)
    print("[STARTUP] Running reconciliation check...")
    print("="*70)
    
    result = reconciliator.reconcile()
    status = result.get('status', 'UNKNOWN')
    discrepancies = result.get('discrepancies', [])
    
    if status == 'MISMATCH':
        print("\n" + "!"*70)
        print("!!! CRITICAL: BROKER/DB MISMATCH DETECTED AT STARTUP !!!")
        print("!"*70)
        print(f"\nDiscrepancies found: {len(discrepancies)}")
        for disc in discrepancies:
            print(f"  - {disc}")
        
        print("\n⛔ TRADING DISABLED")
        print("   System will NOT start trading until mismatch is resolved.")
        print("\n📋 Action Required:")
        print("   1. Review reconciliation_log table in database")
        print("   2. Manually reconcile positions (close orphaned or import unmanaged)")
        print("   3. Clear trading_halted flag: UPDATE system_state SET value='false' WHERE key='trading_halted'")
        print("   4. Restart system")
        print("\n" + "="*70)
        
        sys.exit(1)  # Exit with error code
    
    elif status == 'OK':
        print("✓ Reconciliation OK: Broker and DB positions are in sync")
        print("✓ Safe to start trading")
        print("="*70 + "\n")
    
    else:
        print(f"⚠️  Reconciliation returned unexpected status: {status}")
        print("   Proceeding with caution...")
        print("="*70 + "\n")


def main():
    global client, strategy, db, position_manager, reconciliator
    
    print("\n" + "="*70)
    print("NIFTY DERIVATIVES TRADING SYSTEM - Step 7")
    print("="*70)
    
    # 1. Initialize Database
    print("[INIT] Initializing database...")
    db = QuantDatabase()
    
    # 2. Initialize Broker Client
    print("[INIT] Connecting to broker...")
    client = BreezeClient()
    
    # 3. Initialize Position Manager
    print("[INIT] Initializing position manager...")
    position_manager = PositionManager(db)
    
    # 4. Initialize Strategy (pass db for PositionManager integration)
    print("[INIT] Loading strategy...")
    strategy = MLStrategy(breeze_client=client.breeze, db=db)
    
    # 5. Initialize Reconciliator
    print("[INIT] Initializing reconciliation engine...")
    reconciliator = Reconciliator(position_manager, client, db)
    
    # 6. CRITICAL: Startup Reconciliation Check
    startup_reconciliation_check()
    
    # 7. Start background reconciliation thread (daemon)
    print("[INIT] Starting background reconciliation thread (every 5 minutes)...")
    reconcile_thread = threading.Thread(target=reconciliation_task, daemon=True)
    reconcile_thread.start()
    
    # 8. Subscribe to Live Feed
    # Note: Websocket usually requires a valid session even for PAPER mode 
    # if you want real market data.
    # If in pure simulation without creds, we might need a mock loop.
    
    print("\n[INFO] Connecting to websocket...")
    try:
        # Helper to get the breeze instance
        breeze = client.breeze
        
        # Connect to websocket
        breeze.ws_connect()
        
        # Callback assignment (this depends on library version, sometimes it's passed in connect or subscribe)
        # Assuming standard usage:
        breeze.on_ticks = on_ticks
        
        # Subscribe to NIFTY
        # Arguments: stock_code, exchange_code, product_type, expiry_date, right, strike_price
        # For NIFTY Index (Spot), exchange is usually NSE. For Futures/Options, NFO.
        # Example for NIFTY 50 Stock:
        breeze.subscribe_feeds(exchange_code="NSE", stock_code="NIFTY", product_type="cash", right="others", strike_price="0", expiry_date="")
        
        print(f"[INFO] Subscribed to {stock_code}. Waiting for ticks...")
        print("[INFO] System is live. Press Ctrl+C to stop.")
        print("="*70 + "\n")
        
        # Keep the script running
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n[SHUTDOWN] Received shutdown signal...")
        print("[SHUTDOWN] Gracefully exiting...")
        print("[SHUTDOWN] Reconciliation thread will terminate (daemon)")
        print("[SHUTDOWN] Goodbye!")
        sys.exit(0)
    
    except Exception as e:
        print(f"\n[ERROR] Websocket connection failed: {e}")
        print("[TIP] Ensure your API keys in config.py are correct and session is active.")
        sys.exit(1)


if __name__ == "__main__":
    main()


"""
================================================================================
MANUAL TESTING CHECKLIST (Step 7)
================================================================================

1. TEST CLEAN STARTUP:
   python main.py
   Expected: Reconciliation OK, system starts normally

2. TEST DIRTY STARTUP (simulate mismatch):
   # Insert orphaned DB position before starting
   sqlite3 quant_lab.db << EOF
   INSERT INTO positions (symbol, expiry_date, strike_price, right, quantity, entry_price, entry_timestamp, status, broker_order_id, strategy_regime)
   VALUES ('NIFTY', '2026-01-09', 22500.0, 'Put', -25, 200.0, datetime('now'), 'OPEN', 'TEST_ORPHAN', 'TEST');
   EOF
   
   python main.py
   Expected: System exits with CRITICAL error, does NOT start trading

3. TEST RUNTIME RECONCILIATION:
   # Start system normally, let it run
   # After 5 minutes, should see scheduled reconciliation log
   # Manually check logs:
   sqlite3 quant_lab.db "SELECT reconcile_id, timestamp, status FROM reconciliation_log ORDER BY reconcile_id DESC LIMIT 5;"

4. SIMULATE RUNTIME MISMATCH:
   # While system is running, manually add position via broker app or:
   sqlite3 quant_lab.db "INSERT INTO positions (symbol, expiry_date, strike_price, right, quantity, entry_price, entry_timestamp, status, strategy_regime) VALUES ('NIFTY', '2026-01-16', 22600.0, 'Call', 25, 180.0, datetime('now'), 'OPEN', 'MANUAL_TEST');"
   # Wait for next 5-minute reconciliation cycle
   # Expected: trading_halted flag set, new entries blocked, exits still allowed

5. VERIFY RECONCILIATION LOG:
   sqlite3 quant_lab.db "SELECT * FROM reconciliation_log ORDER BY reconcile_id DESC LIMIT 5;"

6. CHECK SYSTEM STATE:
   sqlite3 quant_lab.db "SELECT * FROM system_state WHERE key='trading_halted';"

================================================================================
"""
