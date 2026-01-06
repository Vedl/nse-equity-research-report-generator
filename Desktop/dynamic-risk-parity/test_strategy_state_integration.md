# Strategy State Integration Test Plan (Step 4)

## Overview
Tests verify that strategy.py now uses PositionManager for persistent state instead of in-memory variables.

## Prerequisites
- Steps 1-3 completed (database schema, PositionManager implemented)
- `strategy.py` modified with PositionManager integration
- SQLite3 CLI installed for manual DB inspection

---

## Test 1: Crash Recovery

### Objective
Verify that process restart does NOT allow duplicate position entries.

### Steps

1. **Clean State**
   ```bash
   sqlite3 quant_lab.db "DELETE FROM positions WHERE symbol='NIFTY'"
   ```

2. **Start Strategy** (simulated - normally via main.py)
   ```python
   from strategy import MLStrategy
   from database_manager import QuantDatabase
   
   db = QuantDatabase()
   strategy = MLStrategy(breeze_client=None, db=db)
   
   # Simulate incoming tick that triggers HIGH confidence signal
   # (You would need to craft a tick that generates prob > 0.70)
   ```

3. **Verify PENDING Position Created**
   ```bash
   sqlite3 quant_lab.db "SELECT position_id, symbol, status FROM positions WHERE symbol='NIFTY'"
   ```
   
   **Expected Output:**
   ```
   1|NIFTY|PENDING
   ```

4. **Kill Process**
   - Press `Ctrl+C` or `kill` the Python process
   - Position state is in database (persisted)

5. **Restart Strategy**
   ```python
   from strategy import MLStrategy
   from database_manager import QuantDatabase
   
   db = QuantDatabase()
   strategy = MLStrategy(breeze_client=None, db=db)
   
   # Trigger SAME entry signal again
   ```

6. **Verify Entry Blocked**
   
   **Expected Log Output:**
   ```
   [BLOCKED] Entry signal rejected: Already have OPEN/PENDING position
   ```

7. **Verify No Duplicate Position**
   ```bash
   sqlite3 quant_lab.db "SELECT COUNT(*) FROM positions WHERE symbol='NIFTY' AND status IN ('PENDING','OPEN')"
   ```
   
   **Expected Output:**
   ```
   1
   ```
   (Only ONE position, not two)

### Pass Criteria
- ✅ Process restart loads position from DB
- ✅ Duplicate entry signal is rejected
- ✅ Only 1 PENDING/OPEN position exists in database

---

## Test 2: Duplicate Entry Prevention

### Objective
Verify multiple rapid entry signals do NOT create multiple positions.

### Steps

1. **Clean State**
   ```bash
   sqlite3 quant_lab.db "DELETE FROM positions WHERE symbol='NIFTY'"
   ```

2. **Trigger Entry Signal Multiple Times**
   ```python
   from strategy import MLStrategy
   from database_manager import QuantDatabase
   
   db = QuantDatabase()
   strategy = MLStrategy(breeze_client=None, db=db)
   
   # Call generate_signal() 3 times with identical high-confidence data
   result1 = strategy.generate_signal(tick_data)  # Should create PENDING
   result2 = strategy.generate_signal(tick_data)  # Should be blocked
   result3 = strategy.generate_signal(tick_data)  # Should be blocked
   
   print(result1)  # {'signal': 1, 'position_id': X, ...}
   print(result2)  # {'signal': 0} (blocked)
   print(result3)  # {'signal': 0} (blocked)
   ```

3. **Verify Only One Position**
   ```bash
   sqlite3 quant_lab.db "SELECT position_id, symbol, status, entry_timestamp FROM positions WHERE symbol='NIFTY' ORDER BY position_id"
   ```
   
   **Expected Output:**
   ```
   1|NIFTY|PENDING|2026-01-06T12:27:43
   ```
   (Single position, not 3)

### Pass Criteria
- ✅ First signal creates PENDING position
- ✅ Subsequent signals return `signal: 0` (blocked)
- ✅ Database has exactly 1 position

---

## Test 3: Exit Path

### Objective
Verify exit logic updates position status to CLOSED and records PnL.

### Steps

1. **Create OPEN Position Manually**
   ```bash
   sqlite3 quant_lab.db << EOF
   DELETE FROM positions WHERE symbol='NIFTY';
   INSERT INTO positions 
   (symbol, expiry_date, strike_price, right, quantity, entry_price, entry_timestamp, status, broker_order_id, strategy_regime)
   VALUES ('NIFTY', '2026-01-09', 22500.0, 'Put', -25, 200.0, datetime('now'), 'OPEN', 'TEST_ORDER_123', 'REGIME_LOW_VOL');
   EOF
   ```

2. **Trigger Stop Loss**
   ```python
   from strategy import MLStrategy
   from database_manager import QuantDatabase
   
   db = QuantDatabase()
   strategy = MLStrategy(breeze_client=None, db=db)
   
   # Craft tick data that triggers stop loss
   # (e.g., underlying price moved enough to breach 20% SL threshold)
   tick_causing_sl = {
       'last': 22800.0,  # Price moved up significantly
       'open': 22800.0,
       'high': 22800.0,
       'low': 22795.0
   }
   
   # Build price buffer first (need 40 ticks for indicators)
   # ... (omitted for brevity, assume buffer is warmed up)
   
   result = strategy.generate_signal(tick_causing_sl)
   print(result)  # Should contain 'signal': -1, 'action': 'buy'
   ```

3. **Verify Position CLOSED**
   ```bash
   sqlite3 quant_lab.db "SELECT position_id, status, exit_price, pnl FROM positions WHERE symbol='NIFTY'"
   ```
   
   **Expected Output:**
   ```
   1|CLOSED|240.0|-1000.0
   ```
   (Status changed to CLOSED, exit_price recorded, PnL calculated)

4. **Verify New Entry Allowed**
   ```python
   # After position closed, triggering entry signal should work again
   result = strategy.generate_signal(high_confidence_tick)
   print(result)  # Should be {'signal': 1, ...} (new entry allowed)
   ```

5. **Verify Two Positions in DB**
   ```bash
   sqlite3 quant_lab.db "SELECT position_id, status FROM positions WHERE symbol='NIFTY' ORDER BY position_id"
   ```
   
   **Expected Output:**
   ```
   1|CLOSED
   2|PENDING
   ```

### Pass Criteria
- ✅ Stop loss triggers exit
- ✅ Position status updated to CLOSED
- ✅ PnL calculated and recorded
- ✅ Cached state cleared (active_position_id = None)
- ✅ New entry signal works after exit

---

## Test 4: State Recovery on Restart (Warm Start)

### Objective
Verify strategy can resume monitoring existing OPEN position after restart.

### Steps

1. **Create OPEN Position Manually**
   ```bash
   sqlite3 quant_lab.db << EOF
   DELETE FROM positions WHERE symbol='NIFTY';
   INSERT INTO positions 
   (symbol, expiry_date, strike_price, right, quantity, entry_price, entry_timestamp, status, broker_order_id, strategy_regime)
   VALUES ('NIFTY', '2026-01-09', 22500.0, 'Put', -25, 200.0, datetime('now'), 'OPEN', 'BROKER_XYZ', 'REGIME_LOW_VOL');
   EOF
   ```

2. **Start Fresh Strategy Instance**
   ```python
   from strategy import MLStrategy
   from database_manager import QuantDatabase
   
   db = QuantDatabase()
   strategy = MLStrategy(breeze_client=None, db=db)  # Fresh instance, no in-memory state
   
   # Trigger tick that should check stop loss
   result = strategy.generate_signal(tick_data)
   ```

3. **Verify Stop Loss Still Works**
   - Even though strategy was just initialized (no cached `self.entry_price`),
   - It should load position from DB and restore cached values
   - Stop loss logic should still function

### Pass Criteria
- ✅ Strategy identifies existing OPEN position on first tick
- ✅ Entry signal blocked (position already exists)
- ✅ Stop loss logic functions correctly despite no prior in-memory state

---

## Manual Verification Queries

### Check All Positions
```bash
sqlite3 quant_lab.db "SELECT position_id, symbol, strike_price, right, quantity, entry_price, exit_price, pnl, status FROM positions ORDER BY entry_timestamp DESC LIMIT 10"
```

### Count Active Positions
```bash
sqlite3 quant_lab.db "SELECT symbol, COUNT(*) FROM positions WHERE status IN ('PENDING','OPEN') GROUP BY symbol"
```

### View Position Lifecycle
```bash
sqlite3 quant_lab.db "SELECT position_id, status, entry_timestamp, exit_timestamp FROM positions WHERE symbol='NIFTY' ORDER BY entry_timestamp DESC"
```

---

## Expected Failure Modes (Should NOT Occur)

❌ **Double Entry**: Two PENDING positions created from same signal
❌ **Lost Position**: Restart forgets about PENDING/OPEN position
❌ **Phantom Exit**: Exit recorded in DB but position still treated as OPEN
❌ **Stale State**: Cached `self.entry_price` used when DB position is different

---

## Success Summary

All tests pass if:
1. **Crash recovery** works (no duplicate entries)
2. **Duplicate prevention** works (rapid signals don't bypass check)
3. **Exit path** works (status → CLOSED, PnL recorded)
4. **Warm restart** works (pick up existing position from DB)

**Database is now the source of truth, not in-memory variables.**
