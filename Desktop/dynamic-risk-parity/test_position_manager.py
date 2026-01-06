"""
Test Script: Verify PositionManager read-only methods (Step 2).
Tests query functionality without modifying strategy or other modules.
"""

from database_manager import QuantDatabase
from position_manager import PositionManager
from datetime import datetime


def test_position_manager():
    """
    Verify PositionManager read methods work correctly.
    """
    # Initialize database
    db = QuantDatabase()
    db.init_schema()
    
    # Get raw connection for test setup
    conn = db.get_connection()
    
    # Clean up any test data from previous runs
    conn.execute("DELETE FROM positions WHERE symbol='TEST_NIFTY'")
    conn.commit()
    
    # Insert test positions
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Position 1: PENDING (order in-flight)
    conn.execute('''
        INSERT INTO positions 
        (symbol, expiry_date, strike_price, right, quantity, entry_price, 
         entry_timestamp, status, strategy_regime)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', ('TEST_NIFTY', '2025-01-09', 22500.0, 'Put', -25, 200.0, timestamp, 'PENDING', 'REGIME_LOW_VOL'))
    conn.commit()
    
    pending_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Position 2: OPEN (active trade)
    conn.execute('''
        INSERT INTO positions 
        (symbol, expiry_date, strike_price, right, quantity, entry_price, 
         entry_timestamp, status, broker_order_id, strategy_regime)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', ('TEST_NIFTY', '2025-01-09', 22600.0, 'Call', 25, 180.0, timestamp, 'OPEN', 'BROKER12345', 'REGIME_TRENDING'))
    conn.commit()
    
    open_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Position 3: CLOSED (historical trade, should be excluded)
    conn.execute('''
        INSERT INTO positions 
        (symbol, expiry_date, strike_price, right, quantity, entry_price, 
         entry_timestamp, exit_price, exit_timestamp, pnl, status, strategy_regime)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', ('TEST_NIFTY', '2025-01-02', 22400.0, 'Put', -25, 220.0, timestamp, 150.0, timestamp, 1750.0, 'CLOSED', 'REGIME_HIGH_VOL'))
    conn.commit()
    
    # Initialize PositionManager
    pm = PositionManager(db)
    
    # =========================================================================
    # Test 1: get_open_positions() returns both PENDING and OPEN
    # =========================================================================
    all_open = pm.get_open_positions()
    assert len(all_open) >= 2, f"FAIL: Expected at least 2 open positions, got {len(all_open)}"
    
    # Filter to our test positions
    test_open = [p for p in all_open if p['symbol'] == 'TEST_NIFTY']
    assert len(test_open) == 2, f"FAIL: Expected 2 TEST_NIFTY positions, got {len(test_open)}"
    
    statuses = {p['status'] for p in test_open}
    assert 'PENDING' in statuses, "FAIL: PENDING position not returned"
    assert 'OPEN' in statuses, "FAIL: OPEN position not returned"
    
    print("✓ Test 1 passed: get_open_positions() returns PENDING and OPEN")
    
    # =========================================================================
    # Test 2: has_open_position() returns True
    # =========================================================================
    assert pm.has_open_position() == True, "FAIL: has_open_position() should return True"
    assert pm.has_open_position(symbol='TEST_NIFTY') == True, "FAIL: Symbol filter failed"
    assert pm.has_open_position(symbol='NONEXISTENT') == False, "FAIL: Should return False for nonexistent symbol"
    
    print("✓ Test 2 passed: has_open_position() filtering works")
    
    # =========================================================================
    # Test 3: get_position_by_id() returns correct record
    # =========================================================================
    pending_pos = pm.get_position_by_id(pending_id)
    assert pending_pos is not None, "FAIL: Could not fetch PENDING position by ID"
    assert pending_pos['status'] == 'PENDING', "FAIL: Wrong status"
    assert pending_pos['strike_price'] == 22500.0, "FAIL: Wrong strike price"
    assert pending_pos['right'] == 'Put', "FAIL: Wrong option type"
    
    open_pos = pm.get_position_by_id(open_id)
    assert open_pos is not None, "FAIL: Could not fetch OPEN position by ID"
    assert open_pos['broker_order_id'] == 'BROKER12345', "FAIL: Broker order ID mismatch"
    
    print("✓ Test 3 passed: get_position_by_id() returns correct records")
    
    # =========================================================================
    # Test 4: get_open_positions(symbol=...) filters correctly
    # =========================================================================
    nifty_positions = pm.get_open_positions(symbol='TEST_NIFTY')
    assert len(nifty_positions) == 2, f"FAIL: Symbol filter returned {len(nifty_positions)} instead of 2"
    
    other_positions = pm.get_open_positions(symbol='OTHER_SYMBOL')
    test_other = [p for p in other_positions if p['symbol'] == 'TEST_NIFTY']
    assert len(test_other) == 0, "FAIL: Filter by OTHER_SYMBOL should not return TEST_NIFTY"
    
    print("✓ Test 4 passed: get_open_positions(symbol=...) filters correctly")
    
    # =========================================================================
    # Test 5: get_positions_by_status() works
    # =========================================================================
    closed_positions = pm.get_positions_by_status('CLOSED')
    test_closed = [p for p in closed_positions if p['symbol'] == 'TEST_NIFTY']
    assert len(test_closed) >= 1, "FAIL: Should find at least 1 CLOSED position"
    
    pending_positions = pm.get_positions_by_status('PENDING')
    test_pending = [p for p in pending_positions if p['symbol'] == 'TEST_NIFTY']
    assert len(test_pending) == 1, "FAIL: Should find exactly 1 PENDING position"
    
    print("✓ Test 5 passed: get_positions_by_status() works")
    
    # =========================================================================
    # Test 6: has_open_position with right filter
    # =========================================================================
    assert pm.has_open_position(symbol='TEST_NIFTY', right='Put') == True, "FAIL: Put filter failed"
    assert pm.has_open_position(symbol='TEST_NIFTY', right='Call') == True, "FAIL: Call filter failed"
    
    print("✓ Test 6 passed: has_open_position with right filter works")
    
    # Cleanup
    conn.execute("DELETE FROM positions WHERE symbol='TEST_NIFTY'")
    conn.commit()
    db.close()
    
    print("\n✅ All PositionManager tests passed.")


if __name__ == "__main__":
    test_position_manager()
