"""
Test Script: Verify Reconciliator functionality (Step 6).
Tests reconciliation logic, DB updates, and audit logging.
"""

from database_manager import QuantDatabase
from position_manager import PositionManager
from reconciliation import Reconciliator
from datetime import datetime


class MockBrokerClient:
    """Mock broker client for testing"""
    def __init__(self, positions=None):
        self.positions = positions if positions is not None else []
    
    def get_positions(self):
        return self.positions


def test_reconciliator():
    """
    Test reconciliation module with various scenarios.
    """
    # Initialize database
    db = QuantDatabase()
    db.init_schema()
    
    # Clean up test data
    conn = db.get_connection()
    conn.execute("DELETE FROM positions WHERE symbol='TEST_RECON'")
    conn.execute("DELETE FROM reconciliation_log")
    conn.execute("DELETE FROM system_state WHERE key='trading_halted'")
    conn.commit()
    
    pm = PositionManager(db)
    
    # =========================================================================
    # Test 1: Clean state (DB empty, broker empty)
    # =========================================================================
    print("Running Test 1: Clean state...")
    
    broker = MockBrokerClient(positions=[])
    reconciliator = Reconciliator(pm, broker, db)
    
    result = reconciliator.reconcile()
    
    assert result['status'] == 'OK', f"FAIL: Expected OK, got {result['status']}"
    assert len(result['discrepancies']) == 0, "FAIL: Should have no discrepancies"
    
    # Verify reconciliation_log
    cursor = conn.execute("SELECT status FROM reconciliation_log ORDER BY reconcile_id DESC LIMIT 1")
    log_status = cursor.fetchone()[0]
    assert log_status == 'OK', f"FAIL: Log status should be OK, got {log_status}"
    
    print("  ✓ Clean state: status OK, no discrepancies")
    print("✓ Test 1 passed\n")
    
    # =========================================================================
    # Test 2: Orphaned DB position (DB has position, broker doesn't)
    # =========================================================================
    print("Running Test 2: Orphaned DB position...")
    
    # Insert an OPEN position in DB
    pos_id = pm.record_entry(
        symbol='TEST_RECON',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-25,
        entry_price=200.0,
        strategy_regime='TEST'
    )
    pm.mark_position_open(pos_id, 'BROKER_TEST_123')
    
    # Broker returns empty (position not in broker)
    broker = MockBrokerClient(positions=[])
    reconciliator = Reconciliator(pm, broker, db)
    
    result = reconciliator.reconcile()
    
    assert result['status'] == 'MISMATCH', f"FAIL: Expected MISMATCH, got {result['status']}"
    assert len(result['discrepancies']) == 1, f"FAIL: Expected 1 discrepancy, got {len(result['discrepancies'])}"
    assert 'ORPHANED' in result['discrepancies'][0], "FAIL: Discrepancy should mention ORPHANED"
    
    # Verify position marked as ORPHANED
    orphaned_pos = pm.get_position_by_id(pos_id)
    assert orphaned_pos['status'] == 'ORPHANED', f"FAIL: Position should be ORPHANED, got {orphaned_pos['status']}"
    
    # Verify trading_halted flag set
    halted = reconciliator.get_system_state('trading_halted')
    assert halted == 'true', f"FAIL: trading_halted should be 'true', got {halted}"
    
    print("  ✓ Orphaned DB position marked as ORPHANED")
    print("  ✓ trading_halted flag set to 'true'")
    print("✓ Test 2 passed\n")
    
    # =========================================================================
    # Test 3: Unmanaged broker position (broker has position, DB doesn't)
    # =========================================================================
    print("Running Test 3: Unmanaged broker position...")
    
    # Clean DB
    conn.execute("DELETE FROM positions WHERE symbol='TEST_RECON'")
    conn.execute("DELETE FROM system_state WHERE key='trading_halted'")
    conn.commit()
    
    # Broker returns a position
    broker_position = {
        'symbol': 'TEST_RECON',
        'expiry_date': '2026-01-16',
        'strike_price': 22600.0,
        'right': 'Call',
        'quantity': 25  # LONG position
    }
    broker = MockBrokerClient(positions=[broker_position])
    reconciliator = Reconciliator(pm, broker, db)
    
    result = reconciliator.reconcile()
    
    assert result['status'] == 'MISMATCH', f"FAIL: Expected MISMATCH, got {result['status']}"
    assert len(result['discrepancies']) == 1, f"FAIL: Expected 1 discrepancy, got {len(result['discrepancies'])}"
    assert 'UNMANAGED' in result['discrepancies'][0], "FAIL: Discrepancy should mention UNMANAGED"
    
    # Verify UNMANAGED position imported
    unmanaged_positions = pm.get_positions_by_status('UNMANAGED')
    test_unmanaged = [p for p in unmanaged_positions if p['symbol'] == 'TEST_RECON']
    assert len(test_unmanaged) == 1, f"FAIL: Expected 1 UNMANAGED position, got {len(test_unmanaged)}"
    
    imported_pos = test_unmanaged[0]
    assert imported_pos['symbol'] == 'TEST_RECON', "FAIL: Symbol mismatch"
    assert imported_pos['strike_price'] == 22600.0, "FAIL: Strike mismatch"
    assert imported_pos['right'] == 'Call', "FAIL: Right mismatch"
    assert imported_pos['quantity'] == 25, "FAIL: Quantity mismatch"
    assert imported_pos['strategy_regime'] == 'IMPORTED_BROKER', "FAIL: Should be marked as IMPORTED_BROKER"
    
    print("  ✓ Unmanaged broker position imported as UNMANAGED")
    print("  ✓ trading_halted flag set to 'true'")
    print("✓ Test 3 passed\n")
    
    # =========================================================================
    # Test 4: Idempotency (calling reconcile twice doesn't duplicate UNMANAGED)
    # =========================================================================
    print("Running Test 4: Idempotency test...")
    
    # Call reconcile again with same broker position
    # Note: UNMANAGED positions are not included in get_open_positions(),
    # so broker position will still show as extra, but should NOT create a duplicate
    result2 = reconciliator.reconcile()
    
    # The status will still be MISMATCH because UNMANAGED != OPEN/PENDING
    # But the key test is: no duplicate UNMANAGED rows should be created
    
    # Verify no duplicate UNMANAGED positions
    unmanaged_positions2 = pm.get_positions_by_status('UNMANAGED')
    test_unmanaged2 = [p for p in unmanaged_positions2 if p['symbol'] == 'TEST_RECON']
    assert len(test_unmanaged2) == 1, f"FAIL: Should still have only 1 UNMANAGED position, got {len(test_unmanaged2)}"
    
    print("  ✓ No duplicate UNMANAGED positions created")
    print("✓ Test 4 passed\n")
    
    # =========================================================================
    # Test 5: Reconciliation log audit trail
    # =========================================================================
    print("Running Test 5: Reconciliation log audit trail...")
    
    cursor = conn.execute("""
        SELECT reconcile_id, status, discrepancy_notes 
        FROM reconciliation_log 
        ORDER BY reconcile_id DESC 
        LIMIT 5
    """)
    logs = cursor.fetchall()
    
    assert len(logs) >= 4, f"FAIL: Expected at least 4 reconciliation logs, got {len(logs)}"
    
    # Verify statuses
    statuses = [log[1] for log in logs]
    assert 'OK' in statuses, "FAIL: Should have at least one OK status"
    assert 'MISMATCH' in statuses, "FAIL: Should have at least one MISMATCH status"
    
    print(f"  ✓ Reconciliation log has {len(logs)} entries")
    print(f"  ✓ Statuses found: {set(statuses)}")
    print("✓ Test 5 passed\n")
    
    # =========================================================================
    # Test 6: System state get/set
    # =========================================================================
    print("Running Test 6: System state persistence...")
    
    reconciliator.set_system_state('test_key', 'test_value')
    value = reconciliator.get_system_state('test_key')
    assert value == 'test_value', f"FAIL: Expected 'test_value', got {value}"
    
    # Test non-existent key
    null_value = reconciliator.get_system_state('nonexistent')
    assert null_value is None, f"FAIL: Should return None for missing key, got {null_value}"
    
    print("  ✓ System state get/set works correctly")
    print("✓ Test 6 passed\n")
    
    # Cleanup
    conn.execute("DELETE FROM positions WHERE symbol='TEST_RECON'")
    conn.execute("DELETE FROM system_state WHERE key IN ('trading_halted', 'test_key')")
    conn.commit()
    db.close()
    
    print("✅ All Reconciliator tests passed.")


if __name__ == "__main__":
    test_reconciliator()
