"""
Test Script: Verify PositionManager write methods (Step 3).
Tests two-phase commit lifecycle and error handling.
"""

from database_manager import QuantDatabase
from position_manager import PositionManager


def test_position_manager_write():
    """
    Test position lifecycle: PENDING → OPEN → CLOSED and FAILED paths.
    """
    # Initialize database
    db = QuantDatabase()
    db.init_schema()
    
    # Clean up test data
    conn = db.get_connection()
    conn.execute("DELETE FROM positions WHERE symbol='TEST_WRITE'")
    conn.commit()
    
    pm = PositionManager(db)
    
    # =========================================================================
    # Test 1: Full happy-path lifecycle (PENDING → OPEN → CLOSED)
    # =========================================================================
    print("Running Test 1: Happy-path lifecycle...")
    
    # Phase 1: Record entry (PENDING)
    pos_id = pm.record_entry(
        symbol='TEST_WRITE',
        expiry_date='2025-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-25,  # SHORT position
        entry_price=200.0,
        strategy_regime='REGIME_LOW_VOL'
    )
    
    assert pos_id > 0, "FAIL: record_entry should return valid position_id"
    
    # Verify PENDING status
    position = pm.get_position_by_id(pos_id)
    assert position is not None, "FAIL: Position not found after entry"
    assert position['status'] == 'PENDING', f"FAIL: Expected PENDING, got {position['status']}"
    assert position['broker_order_id'] is None, "FAIL: broker_order_id should be NULL in PENDING"
    
    print("  ✓ Phase 1: PENDING position recorded")
    
    # Phase 2: Mark as OPEN (broker confirmed)
    pm.mark_position_open(pos_id, 'BROKER_ORDER_12345')
    
    position = pm.get_position_by_id(pos_id)
    assert position['status'] == 'OPEN', f"FAIL: Expected OPEN, got {position['status']}"
    assert position['broker_order_id'] == 'BROKER_ORDER_12345', "FAIL: broker_order_id not set"
    
    print("  ✓ Phase 2: Position marked OPEN")
    
    # Phase 3: Close position
    # SHORT Put @ 200, exit @ 150 = profit of 50 per lot * 25 lots = 1250
    pnl = pm.record_exit(pos_id, exit_price=150.0)
    
    expected_pnl = (200.0 - 150.0) * 25  # 1250.0
    assert pnl == expected_pnl, f"FAIL: Expected PnL {expected_pnl}, got {pnl}"
    
    position = pm.get_position_by_id(pos_id)
    assert position['status'] == 'CLOSED', f"FAIL: Expected CLOSED, got {position['status']}"
    assert position['exit_price'] == 150.0, "FAIL: exit_price not recorded"
    assert position['pnl'] == expected_pnl, "FAIL: PnL not calculated correctly"
    assert position['exit_timestamp'] is not None, "FAIL: exit_timestamp not set"
    
    print("  ✓ Phase 3: Position CLOSED with correct PnL")
    print("✓ Test 1 passed: Full lifecycle works\n")
    
    # =========================================================================
    # Test 2: LONG position PnL calculation
    # =========================================================================
    print("Running Test 2: LONG position PnL...")
    
    pos_id_long = pm.record_entry(
        symbol='TEST_WRITE',
        expiry_date='2025-01-09',
        strike_price=22600.0,
        right='Call',
        quantity=25,  # LONG position
        entry_price=180.0,
        strategy_regime='REGIME_TRENDING'
    )
    
    pm.mark_position_open(pos_id_long, 'BROKER_ORDER_67890')
    
    # LONG Call @ 180, exit @ 250 = profit of 70 per lot * 25 lots = 1750
    pnl_long = pm.record_exit(pos_id_long, exit_price=250.0)
    
    expected_pnl_long = (250.0 - 180.0) * 25  # 1750.0
    assert pnl_long == expected_pnl_long, f"FAIL: Expected PnL {expected_pnl_long}, got {pnl_long}"
    
    print("  ✓ LONG position PnL calculated correctly")
    print("✓ Test 2 passed: LONG PnL calculation\n")
    
    # =========================================================================
    # Test 3: Failure path (PENDING → FAILED)
    # =========================================================================
    print("Running Test 3: Failure path...")
    
    pos_id_fail = pm.record_entry(
        symbol='TEST_WRITE',
        expiry_date='2025-01-16',
        strike_price=22400.0,
        right='Put',
        quantity=-25,
        entry_price=190.0,
        strategy_regime='REGIME_HIGH_VOL'
    )
    
    # Broker rejects order
    pm.mark_position_failed(pos_id_fail, "Insufficient margin")
    
    position_fail = pm.get_position_by_id(pos_id_fail)
    assert position_fail['status'] == 'FAILED', "FAIL: Status should be FAILED"
    assert position_fail['error_msg'] == "Insufficient margin", "FAIL: error_msg not recorded"
    assert position_fail['broker_order_id'] is None, "FAIL: FAILED position should not have broker_order_id"
    
    print("  ✓ Position marked FAILED with error message")
    print("✓ Test 3 passed: Failure path works\n")
    
    # =========================================================================
    # Test 4: Invalid transitions (error handling)
    # =========================================================================
    print("Running Test 4: Invalid transitions...")
    
    # Test 4a: Cannot close FAILED position
    try:
        pm.record_exit(pos_id_fail, exit_price=100.0)
        assert False, "FAIL: Should raise RuntimeError when closing FAILED position"
    except RuntimeError as e:
        assert "FAILED" in str(e), "FAIL: Error message should mention FAILED status"
        print("  ✓ Cannot close FAILED position (RuntimeError raised)")
    
    # Test 4b: Cannot close already CLOSED position
    try:
        pm.record_exit(pos_id, exit_price=100.0)
        assert False, "FAIL: Should raise RuntimeError when closing CLOSED position"
    except RuntimeError as e:
        assert "CLOSED" in str(e), "FAIL: Error message should mention CLOSED status"
        print("  ✓ Cannot close CLOSED position (RuntimeError raised)")
    
    # Test 4c: Cannot mark non-existent position as OPEN
    try:
        pm.mark_position_open(999999, 'FAKE_ORDER')
        assert False, "FAIL: Should raise ValueError for non-existent position_id"
    except ValueError as e:
        assert "999999" in str(e), "FAIL: Error message should mention invalid ID"
        print("  ✓ Cannot mark non-existent position (ValueError raised)")
    
    # Test 4d: Cannot mark non-existent position as FAILED
    try:
        pm.mark_position_failed(888888, 'Some error')
        assert False, "FAIL: Should raise ValueError for non-existent position_id"
    except ValueError as e:
        assert "888888" in str(e), "FAIL: Error message should mention invalid ID"
        print("  ✓ Cannot mark non-existent position as FAILED (ValueError raised)")
    
    print("✓ Test 4 passed: Invalid transitions rejected\n")
    
    # =========================================================================
    # Test 5: has_open_position reflects PENDING and OPEN correctly
    # =========================================================================
    print("Running Test 5: has_open_position with write operations...")
    
    # Clean slate
    conn.execute("DELETE FROM positions WHERE symbol='TEST_WRITE'")
    conn.commit()
    
    assert pm.has_open_position(symbol='TEST_WRITE') == False, "FAIL: Should be False initially"
    
    # Add PENDING
    pos_pending = pm.record_entry(
        symbol='TEST_WRITE',
        expiry_date='2025-01-23',
        strike_price=22700.0,
        right='Call',
        quantity=25,
        entry_price=160.0,
        strategy_regime='REGIME_TRENDING'
    )
    
    assert pm.has_open_position(symbol='TEST_WRITE') == True, "FAIL: PENDING should count as open"
    
    # Mark as OPEN
    pm.mark_position_open(pos_pending, 'ORDER_XYZ')
    assert pm.has_open_position(symbol='TEST_WRITE') == True, "FAIL: OPEN should count as open"
    
    # Close it
    pm.record_exit(pos_pending, exit_price=200.0)
    assert pm.has_open_position(symbol='TEST_WRITE') == False, "FAIL: CLOSED should not count as open"
    
    print("  ✓ has_open_position reflects lifecycle correctly")
    print("✓ Test 5 passed: State queries work with writes\n")
    
    # =========================================================================
    # Test 6: Loss scenarios
    # =========================================================================
    print("Running Test 6: Loss scenarios...")
    
    # SHORT position losing money
    pos_loss_short = pm.record_entry(
        symbol='TEST_WRITE',
        expiry_date='2025-01-30',
        strike_price=22800.0,
        right='Put',
        quantity=-25,
        entry_price=150.0,
        strategy_regime='REGIME_LOW_VOL'
    )
    pm.mark_position_open(pos_loss_short, 'ORDER_LOSS1')
    
    # SHORT @ 150, exit @ 200 = loss of -50 per lot * 25 = -1250
    pnl_loss_short = pm.record_exit(pos_loss_short, exit_price=200.0)
    expected_loss_short = (150.0 - 200.0) * 25  # -1250.0
    assert pnl_loss_short == expected_loss_short, f"FAIL: Expected loss {expected_loss_short}, got {pnl_loss_short}"
    assert pnl_loss_short < 0, "FAIL: PnL should be negative for loss"
    
    print("  ✓ SHORT loss calculated correctly")
    
    # LONG position losing money
    pos_loss_long = pm.record_entry(
        symbol='TEST_WRITE',
        expiry_date='2025-01-30',
        strike_price=22900.0,
        right='Call',
        quantity=25,
        entry_price=220.0,
        strategy_regime='REGIME_TRENDING'
    )
    pm.mark_position_open(pos_loss_long, 'ORDER_LOSS2')
    
    # LONG @ 220, exit @ 150 = loss of -70 per lot * 25 = -1750
    pnl_loss_long = pm.record_exit(pos_loss_long, exit_price=150.0)
    expected_loss_long = (150.0 - 220.0) * 25  # -1750.0
    assert pnl_loss_long == expected_loss_long, f"FAIL: Expected loss {expected_loss_long}, got {pnl_loss_long}"
    assert pnl_loss_long < 0, "FAIL: PnL should be negative for loss"
    
    print("  ✓ LONG loss calculated correctly")
    print("✓ Test 6 passed: Loss calculations work\n")
    
    # Cleanup
    conn.execute("DELETE FROM positions WHERE symbol='TEST_WRITE'")
    conn.commit()
    db.close()
    
    print("✅ All PositionManager write-path tests passed.")


if __name__ == "__main__":
    test_position_manager_write()
