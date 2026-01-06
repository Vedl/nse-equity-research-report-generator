"""
Test Script: Verify RiskController functionality (Step 8).
Tests pre-trade validation and risk limit enforcement.
"""

from database_manager import QuantDatabase
from risk_controller import RiskController
from datetime import datetime, date


def test_risk_controller():
    """
    Test risk controller with various scenarios.
    """
    # Initialize database
    db = QuantDatabase()
    db.init_schema()
    
    # Clean up test data
    conn = db.get_connection()
    conn.execute("DELETE FROM positions WHERE symbol='TEST_RISK'")
    conn.execute("DELETE FROM system_state WHERE key='trading_halted'")
    conn.commit()
    
    # Risk configuration
    config = {
        'max_lots_per_trade': 2,
        'max_margin_per_trade': 150000,
        'max_loss_per_trade': 15000,
        'max_daily_loss': 30000,
        'loss_multiplier': 2.0
    }
    
    rc = RiskController(db, config)
    
    # =========================================================================
    # Test 1: Allowed entry (all checks pass)
    # =========================================================================
    print("Running Test 1: Allowed entry...")
    
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-1,  # 1 lot SHORT
        entry_price=200.0,
        estimated_margin=50000.0
    )
    
    assert allowed == True, f"FAIL: Should allow valid entry, got {reason}"
    assert reason == "OK", f"FAIL: Reason should be OK, got {reason}"
    
    print("  ✓ Valid entry allowed")
    print("✓ Test 1 passed\n")
    
    # =========================================================================
    # Test 2: Quantity cap (too many lots)
    # =========================================================================
    print("Running Test 2: Quantity cap...")
    
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-5,  # 5 lots > max 2 lots
        entry_price=200.0,
        estimated_margin=50000.0
    )
    
    assert allowed == False, "FAIL: Should block excessive quantity"
    assert "Quantity" in reason or "max_lots" in reason, f"FAIL: Reason should mention quantity, got {reason}"
    
    print(f"  ✓ Excessive quantity blocked: {reason}")
    print("✓ Test 2 passed\n")
    
    # =========================================================================
    # Test 3: Margin cap (too high margin requirement)
    # =========================================================================
    print("Running Test 3: Margin cap...")
    
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-1,
        entry_price=200.0,
        estimated_margin=200000.0  # Exceeds 150k limit
    )
    
    assert allowed == False, "FAIL: Should block excessive margin"
    assert "margin" in reason.lower(), f"FAIL: Reason should mention margin, got {reason}"
    
    print(f"  ✓ Excessive margin blocked: {reason}")
    print("✓ Test 3 passed\n")
    
    # =========================================================================
    # Test 4: Loss limit per trade (worst-case loss too high)
    # =========================================================================
    print("Running Test 4: Loss limit per trade...")
    
    # Entry price of 500 * 1 lot * 25 lot_size * 2.0 multiplier = 25,000
    # This exceeds max_loss_per_trade of 15,000
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-1,
        entry_price=500.0,  # High premium
        estimated_margin=50000.0
    )
    
    assert allowed == False, "FAIL: Should block high-risk trade"
    assert "loss" in reason.lower(), f"FAIL: Reason should mention loss, got {reason}"
    
    print(f"  ✓ High-risk trade blocked: {reason}")
    print("✓ Test 4 passed\n")
    
    # =========================================================================
    # Test 5: Daily loss limit (already lost too much today)
    # =========================================================================
    print("Running Test 5: Daily loss limit...")
    
    # Insert CLOSED positions with negative PnL for today
    today = date.today().strftime('%Y-%m-%d')
    timestamp = datetime.now().isoformat()
    
    # First losing trade: -15k
    conn.execute('''
        INSERT INTO positions 
        (symbol, expiry_date, strike_price, right, quantity, entry_price, 
         entry_timestamp, exit_price, exit_timestamp, pnl, status, strategy_regime)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', 'TEST')
    ''', ('TEST_RISK', '2026-01-09', 22500.0, 'Put', -25, 200.0, timestamp, 250.0, timestamp, -15000.0))
    
    # Second losing trade: -18k (total = -33k, exceeds -30k limit)
    conn.execute('''
        INSERT INTO positions 
        (symbol, expiry_date, strike_price, right, quantity, entry_price, 
         entry_timestamp, exit_price, exit_timestamp, pnl, status, strategy_regime)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', 'TEST')
    ''', ('TEST_RISK', '2026-01-09', 22600.0, 'Call', 25, 180.0, timestamp, 150.0, timestamp, -18000.0))
    
    conn.commit()
    
    # Try to enter new position
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22700.0,
        right='Put',
        quantity=-1,
        entry_price=200.0,
        estimated_margin=50000.0
    )
    
    assert allowed == False, "FAIL: Should block entry when daily loss limit breached"
    assert "Daily" in reason or "daily" in reason, f"FAIL: Reason should mention daily loss, got {reason}"
    
    print(f"  ✓ Entry blocked due to daily loss limit: {reason}")
    print("✓ Test 5 passed\n")
    
    # =========================================================================
    # Test 6: Trading halted flag blocks entry
    # =========================================================================
    print("Running Test 6: Trading halted flag...")
    
    # Clean daily PnL by deleting test positions
    conn.execute("DELETE FROM positions WHERE symbol='TEST_RISK'")
    conn.commit()
    
    # Set trading_halted flag
    conn.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES ('trading_halted', 'true')")
    conn.commit()
    
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=-1,
        entry_price=200.0,
        estimated_margin=50000.0
    )
    
    assert allowed == False, "FAIL: Should block entry when trading_halted is true"
    assert "halted" in reason.lower(), f"FAIL: Reason should mention halted, got {reason}"
    
    print(f"  ✓ Entry blocked by trading_halted flag: {reason}")
    print("✓ Test 6 passed\n")
    
    # =========================================================================
    # Test 7: Zero quantity check
    # =========================================================================
    print("Running Test 7: Zero quantity...")
    
    # Clear halt flag
    conn.execute("DELETE FROM system_state WHERE key='trading_halted'")
    conn.commit()
    
    allowed, reason = rc.validate_entry(
        symbol='TEST_RISK',
        expiry_date='2026-01-09',
        strike_price=22500.0,
        right='Put',
        quantity=0,  # Invalid
        entry_price=200.0,
        estimated_margin=50000.0
    )
    
    assert allowed == False, "FAIL: Should block zero quantity"
    assert "zero" in reason.lower() or "Quantity" in reason, f"FAIL: Reason should mention zero quantity, got {reason}"
    
    print(f"  ✓ Zero quantity blocked: {reason}")
    print("✓ Test 7 passed\n")
    
    # =========================================================================
    # Test 8: Risk metrics
    # =========================================================================
    print("Running Test 8: Risk metrics...")
    
    metrics = rc.get_risk_metrics()
    
    assert 'daily_pnl' in metrics, "FAIL: Missing daily_pnl in metrics"
    assert 'trading_halted' in metrics, "FAIL: Missing trading_halted in metrics"
    assert 'open_positions_count' in metrics, "FAIL: Missing open_positions_count in metrics"
    
    print(f"  ✓ Risk metrics: {metrics}")
    print("✓ Test 8 passed\n")
    
    # Cleanup
    conn.execute("DELETE FROM positions WHERE symbol='TEST_RISK'")
    conn.execute("DELETE FROM system_state WHERE key='trading_halted'")
    conn.commit()
    db.close()
    
    print("✅ All RiskController tests passed.")


if __name__ == "__main__":
    test_risk_controller()
