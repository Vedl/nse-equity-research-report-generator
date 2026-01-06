"""
Test Script: Verify positions table creation
Validates Step 1 implementation.
"""

from database_manager import QuantDatabase

def test_positions_table_exists():
    """
    Verify that the positions table was created with correct schema.
    """
    db = QuantDatabase()
    db.init_schema()
    
    # Test 1: Table exists
    cursor = db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='positions'"
    )
    result = cursor.fetchone()
    
    assert result is not None, "FAIL: positions table does not exist"
    print("✓ Test 1 passed: positions table exists")
    
    # Test 2: Verify schema structure
    cursor = db.get_connection().execute("PRAGMA table_info(positions)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    required_columns = {
        'position_id': 'INTEGER',
        'symbol': 'TEXT',
        'expiry_date': 'TEXT',
        'strike_price': 'REAL',
        'right': 'TEXT',
        'quantity': 'INTEGER',
        'entry_price': 'REAL',
        'entry_timestamp': 'DATETIME',
        'exit_price': 'REAL',
        'exit_timestamp': 'DATETIME',
        'pnl': 'REAL',
        'status': 'TEXT',
        'broker_order_id': 'TEXT',
        'strategy_regime': 'TEXT',
        'error_msg': 'TEXT',
        'last_reconciled_at': 'DATETIME'
    }
    
    for col_name, col_type in required_columns.items():
        assert col_name in columns, f"FAIL: Missing column {col_name}"
        assert columns[col_name] == col_type, f"FAIL: Column {col_name} has wrong type {columns[col_name]}, expected {col_type}"
    
    print("✓ Test 2 passed: All required columns present with correct types")
    
    # Test 3: Insert test position (verify constraints)
    conn = db.get_connection()
    
    # Get initial count
    cursor = conn.execute("SELECT COUNT(*) FROM positions")
    initial_count = cursor.fetchone()[0]
    
    conn.execute('''
        INSERT INTO positions 
        (symbol, expiry_date, strike_price, right, quantity, entry_price, 
         entry_timestamp, status, strategy_regime)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
    ''', ('NIFTY', '2025-01-09', 22500.0, 'Put', -25, 200.0, 'PENDING', 'REGIME_LOW_VOL'))
    
    conn.commit()
    
    cursor = conn.execute("SELECT COUNT(*) FROM positions")
    new_count = cursor.fetchone()[0]
    assert new_count == initial_count + 1, "FAIL: Test insert failed"
    print("✓ Test 3 passed: Insert operation works correctly")
    
    # Cleanup test data
    conn.execute("DELETE FROM positions WHERE symbol='NIFTY' AND status='PENDING' AND strike_price=22500.0")
    conn.commit()
    
    db.close()
    print("\n✅ All tests passed. Step 1 implementation verified.")

if __name__ == "__main__":
    test_positions_table_exists()
