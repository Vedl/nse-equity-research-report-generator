"""
Position Manager - Safe abstraction for position state management.
Provides centralized access to persistent position data with write safety.

Step 2: Read-only queries.
Step 3: Write methods with two-phase commit (PENDING → OPEN → CLOSED/FAILED).
"""

import sqlite3
from typing import Optional, List, Dict, Union
from datetime import datetime


class PositionManager:
    """
    Centralized position state manager.
    Database is the source of truth; this class provides safe read/write abstractions.
    
    Lifecycle: PENDING → OPEN → CLOSED (or FAILED)
    - PENDING: Order submitted, awaiting broker confirmation
    - OPEN: Order confirmed by broker, position active
    - CLOSED: Position exited, PnL realized
    - FAILED: Order rejected by broker
    - ORPHANED: Reconciliation mismatch detected (future step)
    """
    
    def __init__(self, db):
        """
        Initialize PositionManager with database connection.
        
        Args:
            db: Either a QuantDatabase instance or sqlite3.Connection object.
        """
        # Detect if db is QuantDatabase or raw Connection
        if hasattr(db, 'get_connection'):
            # QuantDatabase instance
            self.conn = db.get_connection()
        elif isinstance(db, sqlite3.Connection):
            # Raw connection
            self.conn = db
        else:
            raise TypeError("db must be QuantDatabase instance or sqlite3.Connection")
        
        # Enable row factory for dict-like access
        self.conn.row_factory = sqlite3.Row
    
    def normalize_row(self, row: sqlite3.Row) -> dict:
        """
        Convert sqlite3.Row to plain dict for easier handling.
        
        Args:
            row: sqlite3.Row from query result
            
        Returns:
            Plain dictionary with column names as keys
        """
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}
    
    # ============================================================================
    # READ METHODS (Step 2)
    # ============================================================================
    
    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Fetch all active positions (status='OPEN' or 'PENDING').
        
        Treats PENDING as active for safety: if an order is in-flight,
        we must not allow duplicate entries.
        
        Args:
            symbol: Optional filter by symbol (e.g., 'NIFTY')
            
        Returns:
            List of position dicts, empty list if none found
        """
        if symbol:
            query = """
                SELECT * FROM positions 
                WHERE (status='OPEN' OR status='PENDING') AND symbol=?
                ORDER BY entry_timestamp DESC
            """
            cursor = self.conn.execute(query, (symbol,))
        else:
            query = """
                SELECT * FROM positions 
                WHERE status='OPEN' OR status='PENDING'
                ORDER BY entry_timestamp DESC
            """
            cursor = self.conn.execute(query)
        
        rows = cursor.fetchall()
        return [self.normalize_row(row) for row in rows]
    
    def has_open_position(self, symbol: Optional[str] = None, 
                         right: Optional[str] = None) -> bool:
        """
        Quick check: does any active position exist matching filters?
        
        Active = OPEN or PENDING status.
        
        Args:
            symbol: Optional filter by symbol
            right: Optional filter by option type ('Call' or 'Put')
            
        Returns:
            True if at least one matching position exists
        """
        conditions = ["(status='OPEN' OR status='PENDING')"]
        params = []
        
        if symbol:
            conditions.append("symbol=?")
            params.append(symbol)
        
        if right:
            conditions.append("right=?")
            params.append(right)
        
        query = f"SELECT COUNT(*) FROM positions WHERE {' AND '.join(conditions)}"
        cursor = self.conn.execute(query, params)
        count = cursor.fetchone()[0]
        return count > 0
    
    def get_position_by_id(self, position_id: int) -> Optional[Dict]:
        """
        Fetch a single position by its primary key.
        
        Args:
            position_id: The position_id from positions table
            
        Returns:
            Position dict or None if not found
        """
        query = "SELECT * FROM positions WHERE position_id=?"
        cursor = self.conn.execute(query, (position_id,))
        row = cursor.fetchone()
        return self.normalize_row(row) if row else None
    
    def get_positions_by_status(self, status: str) -> List[Dict]:
        """
        Fetch all positions with a specific status.
        
        Args:
            status: One of 'PENDING', 'OPEN', 'CLOSED', 'FAILED', 'ORPHANED'
            
        Returns:
            List of position dicts
        """
        query = "SELECT * FROM positions WHERE status=? ORDER BY entry_timestamp DESC"
        cursor = self.conn.execute(query, (status,))
        rows = cursor.fetchall()
        return [self.normalize_row(row) for row in rows]
    
    # ============================================================================
    # WRITE METHODS (Step 3)
    # ============================================================================
    
    def record_entry(self, symbol: str, expiry_date: str, strike_price: float,
                     right: str, quantity: int, entry_price: float, 
                     strategy_regime: str) -> int:
        """
        Insert new position with status='PENDING'.
        
        This is phase 1 of two-phase commit: record intent to open position
        before calling broker API. Prevents duplicate entries on retry.
        
        Args:
            symbol: Underlying symbol (e.g., 'NIFTY')
            expiry_date: Option expiry (e.g., '2025-01-09')
            strike_price: Strike price (e.g., 22500.0)
            right: 'Call' or 'Put'
            quantity: Number of lots (negative for SHORT, positive for LONG)
            entry_price: Premium (received for short, paid for long)
            strategy_regime: Market regime at entry (e.g., 'REGIME_LOW_VOL')
            
        Returns:
            position_id for tracking through lifecycle
        """
        timestamp = datetime.utcnow().isoformat()
        
        query = """
            INSERT INTO positions 
            (symbol, expiry_date, strike_price, right, quantity, entry_price, 
             entry_timestamp, status, strategy_regime)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """
        
        cursor = self.conn.execute(query, (
            symbol, expiry_date, strike_price, right, quantity, entry_price,
            timestamp, strategy_regime
        ))
        self.conn.commit()
        
        return cursor.lastrowid
    
    def mark_position_open(self, position_id: int, broker_order_id: str) -> None:
        """
        Update position status from PENDING → OPEN after broker confirms.
        
        This is phase 2 of two-phase commit: confirm successful order execution.
        
        Args:
            position_id: ID returned from record_entry()
            broker_order_id: Order ID from broker response
            
        Raises:
            ValueError: If position_id does not exist
        """
        # Verify position exists
        position = self.get_position_by_id(position_id)
        if position is None:
            raise ValueError(f"Position ID {position_id} does not exist")
        
        query = """
            UPDATE positions 
            SET status='OPEN', broker_order_id=?
            WHERE position_id=?
        """
        
        self.conn.execute(query, (broker_order_id, position_id))
        self.conn.commit()
    
    def mark_position_failed(self, position_id: int, error_msg: str) -> None:
        """
        Update position status to FAILED if broker rejects order.
        
        Keeps audit trail of failed orders. Does not delete row.
        
        Args:
            position_id: ID of position that failed
            error_msg: Error message from broker
            
        Raises:
            ValueError: If position_id does not exist
        """
        # Verify position exists
        position = self.get_position_by_id(position_id)
        if position is None:
            raise ValueError(f"Position ID {position_id} does not exist")
        
        query = """
            UPDATE positions 
            SET status='FAILED', error_msg=?
            WHERE position_id=?
        """
        
        self.conn.execute(query, (error_msg, position_id))
        self.conn.commit()
    
    def record_exit(self, position_id: int, exit_price: float) -> float:
        """
        Close position: update status='CLOSED', record exit price, calculate PnL.
        
        PnL calculation respects quantity sign convention:
        - quantity < 0 (SHORT): pnl = (entry_price - exit_price) * abs(quantity)
        - quantity > 0 (LONG):  pnl = (exit_price - entry_price) * abs(quantity)
        
        Args:
            position_id: ID of position to close
            exit_price: Premium at exit
            
        Returns:
            Calculated PnL (positive = profit, negative = loss)
            
        Raises:
            ValueError: If position_id does not exist
            RuntimeError: If position is not OPEN or PENDING
        """
        # Fetch existing position
        position = self.get_position_by_id(position_id)
        if position is None:
            raise ValueError(f"Position ID {position_id} does not exist")
        
        # Verify position can be closed
        if position['status'] not in ('OPEN', 'PENDING'):
            raise RuntimeError(
                f"Cannot close position with status '{position['status']}'. "
                f"Only OPEN or PENDING positions can be closed."
            )
        
        # Calculate PnL based on quantity sign
        quantity = position['quantity']
        entry_price = position['entry_price']
        
        if quantity < 0:
            # SHORT position: profit when exit price < entry price
            pnl = (entry_price - exit_price) * abs(quantity)
        else:
            # LONG position: profit when exit price > entry price
            pnl = (exit_price - entry_price) * abs(quantity)
        
        # Update position
        timestamp = datetime.utcnow().isoformat()
        
        query = """
            UPDATE positions 
            SET status='CLOSED', exit_price=?, exit_timestamp=?, pnl=?
            WHERE position_id=?
        """
        
        self.conn.execute(query, (exit_price, timestamp, pnl, position_id))
        self.conn.commit()
        
        return pnl
    
    # ============================================================================
    # FUTURE METHODS (Step 6+)
    # ============================================================================
    
    # def mark_orphaned(self, position_id: int, reason: str) -> None:
    #     """
    #     Flag position as ORPHANED when reconciliation detects mismatch.
    #     
    #     Step 6 implementation (reconciliation module).
    #     """
    #     pass


if __name__ == "__main__":
    # Quick sanity check
    from database_manager import QuantDatabase
    
    db = QuantDatabase()
    pm = PositionManager(db)
    
    print(f"Open positions: {len(pm.get_open_positions())}")
    print(f"Has open position: {pm.has_open_position()}")
    print("✓ PositionManager import and basic usage OK")
    
    db.close()
