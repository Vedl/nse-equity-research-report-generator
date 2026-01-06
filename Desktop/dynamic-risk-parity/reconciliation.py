"""
Reconciliation Module (Step 6)
Compares broker positions vs database positions and logs discrepancies.

Safety Features:
- Read-only against broker API (no order placement)
- Persists trading_halted flag on mismatch (exits still allowed)
- Marks DB-only positions as ORPHANED
- Imports broker-only positions as UNMANAGED
- Full audit trail in reconciliation_log table
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional


class Reconciliator:
    """
    Reconciliation engine for broker <-> DB position sync.
    
    Conservative approach:
    - Never deletes positions
    - Only updates statuses (ORPHANED, UNMANAGED)
    - Persists trading_halted flag for operator review
    - Logs every reconciliation attempt
    """
    
    def __init__(self, position_manager, broker_client, db):
        """
        Initialize reconciliator with dependencies.
        
        Args:
            position_manager: PositionManager instance (from position_manager.py)
            broker_client: BreezeClient instance (has get_positions())
            db: QuantDatabase instance or sqlite3.Connection
        """
        self.position_manager = position_manager
        self.broker_client = broker_client
        
        # Get DB connection
        if hasattr(db, 'get_connection'):
            self.conn = db.get_connection()
        elif isinstance(db, sqlite3.Connection):
            self.conn = db
        else:
            raise TypeError("db must be QuantDatabase or sqlite3.Connection")
    
    def reconcile(self) -> Dict:
        """
        Compare broker positions vs DB positions and handle discrepancies.
        
        Returns:
            dict with keys:
                - 'status': 'OK' | 'MISMATCH' | 'ERROR'
                - 'broker_positions': list of broker positions
                - 'db_positions': list of DB positions
                - 'discrepancies': list of discrepancy notes
        """
        timestamp = datetime.utcnow().isoformat()
        
        try:
            # Step 1: Fetch broker positions
            broker_positions = self.broker_client.get_positions()
            
            # Step 2: Fetch DB positions (PENDING and OPEN only)
            db_positions_raw = self.position_manager.get_open_positions()
            
            # Normalize DB positions to match broker format
            db_positions = [{
                'symbol': pos['symbol'],
                'expiry_date': pos['expiry_date'],
                'strike_price': pos['strike_price'],
                'right': pos['right'],
                'quantity': pos['quantity']
            } for pos in db_positions_raw]
            
            # Step 3: Create comparable sets
            broker_set = set(self._position_to_tuple(p) for p in broker_positions)
            db_set = set(self._position_to_tuple(p) for p in db_positions)
            
            # Step 4: Compute differences
            extra_in_broker = broker_set - db_set
            extra_in_db = db_set - broker_set
            
            # Step 5: Build discrepancy notes
            discrepancies = []
            
            if extra_in_db:
                for pos_tuple in extra_in_db:
                    discrepancies.append(f"ORPHANED: DB position {pos_tuple} not found in broker")
            
            if extra_in_broker:
                for pos_tuple in extra_in_broker:
                    discrepancies.append(f"UNMANAGED: Broker position {pos_tuple} not found in DB")
            
            # Step 6: Determine status
            if not discrepancies:
                status = 'OK'
            else:
                status = 'MISMATCH'
            
            # Step 7: Log to reconciliation_log
            self._log_reconciliation(
                timestamp,
                broker_positions,
                db_positions,
                status,
                discrepancies
            )
            
            # Step 8: Handle mismatch if needed
            if status == 'MISMATCH':
                self.handle_mismatch(
                    extra_in_db,
                    extra_in_broker,
                    db_positions_raw,
                    broker_positions
                )
            else:
                # Status OK: Update last_reconciled_at for all open positions
                self._update_reconciliation_timestamp(timestamp)
            
            return {
                'status': status,
                'broker_positions': broker_positions,
                'db_positions': db_positions,
                'discrepancies': discrepancies
            }
            
        except Exception as e:
            # Log error and return error status (do NOT raise)
            error_msg = f"Reconciliation failed: {str(e)}"
            self._log_reconciliation(
                timestamp,
                [],
                [],
                'ERROR',
                [error_msg]
            )
            
            return {
                'status': 'ERROR',
                'broker_positions': [],
                'db_positions': [],
                'discrepancies': [error_msg]
            }
    
    def handle_mismatch(self, extra_in_db: set, extra_in_broker: set,
                       db_positions_raw: list, broker_positions: list) -> None:
        """
        Handle reconciliation mismatch by updating DB state.
        
        Actions:
        1. Mark DB-only positions as ORPHANED
        2. Import broker-only positions as UNMANAGED
        3. Set trading_halted flag (exits still allowed)
        
        Args:
            extra_in_db: Set of position tuples only in DB
            extra_in_broker: Set of position tuples only in broker
            db_positions_raw: Full DB position dicts (for position_id lookup)
            broker_positions: Full broker position dicts (for import)
        """
        # Build lookup maps
        db_map = {self._position_to_tuple(p): p for p in db_positions_raw}
        broker_map = {self._position_to_tuple(p): p for p in broker_positions}
        
        # Mark ORPHANED positions
        for pos_tuple in extra_in_db:
            db_pos = db_map.get(pos_tuple)
            if db_pos:
                position_id = db_pos['position_id']
                self._mark_orphaned(position_id, f"Not found in broker during reconciliation")
        
        # Import UNMANAGED positions (idempotent)
        for pos_tuple in extra_in_broker:
            broker_pos = broker_map.get(pos_tuple)
            if broker_pos:
                self._import_unmanaged(broker_pos)
        
        # Set trading_halted flag
        self.set_system_state('trading_halted', 'true')
        print("[CRITICAL] Trading halted due to reconciliation mismatch. Manual review required.")
        print("           NOTE: Exits are still allowed, only new entries blocked.")
    
    def _position_to_tuple(self, pos: dict) -> Tuple:
        """
        Convert position dict to comparable tuple key.
        
        Args:
            pos: Position dict with keys: symbol, expiry_date, strike_price, right, quantity
            
        Returns:
            Tuple: (symbol, expiry_date, strike_price, right, quantity)
        """
        return (
            pos.get('symbol', ''),
            pos.get('expiry_date', ''),
            float(pos.get('strike_price', 0.0)),
            pos.get('right', ''),
            int(pos.get('quantity', 0))
        )
    
    def _log_reconciliation(self, timestamp: str, broker_positions: list,
                          db_positions: list, status: str, discrepancies: list) -> None:
        """
        Insert reconciliation attempt into audit log.
        
        Args:
            timestamp: UTC ISO timestamp
            broker_positions: List of broker position dicts
            db_positions: List of DB position dicts
            status: 'OK' | 'MISMATCH' | 'ERROR'
            discrepancies: List of discrepancy note strings
        """
        broker_json = json.dumps(broker_positions)
        db_json = json.dumps(db_positions)
        discrepancy_notes = '\n'.join(discrepancies) if discrepancies else None
        
        query = """
            INSERT INTO reconciliation_log 
            (timestamp, broker_positions, db_positions, status, discrepancy_notes)
            VALUES (?, ?, ?, ?, ?)
        """
        
        self.conn.execute(query, (timestamp, broker_json, db_json, status, discrepancy_notes))
        self.conn.commit()
    
    def _mark_orphaned(self, position_id: int, reason: str) -> None:
        """
        Mark a DB position as ORPHANED (broker doesn't have it).
        
        Args:
            position_id: Position ID to mark
            reason: Reason for orphaning
        """
        query = """
            UPDATE positions 
            SET status='ORPHANED', error_msg=?
            WHERE position_id=?
        """
        
        self.conn.execute(query, (reason, position_id))
        self.conn.commit()
        print(f"[RECONCILE] Marked position {position_id} as ORPHANED: {reason}")
    
    def _import_unmanaged(self, broker_pos: dict) -> None:
        """
        Import a broker-only position as UNMANAGED (idempotent).
        
        If an identical UNMANAGED position already exists, do not insert duplicate.
        
        Args:
            broker_pos: Broker position dict to import
        """
        # Check if already imported
        check_query = """
            SELECT position_id FROM positions
            WHERE symbol=? AND expiry_date=? AND strike_price=? AND right=? 
            AND quantity=? AND status='UNMANAGED'
        """
        
        cursor = self.conn.execute(check_query, (
            broker_pos['symbol'],
            broker_pos['expiry_date'],
            broker_pos['strike_price'],
            broker_pos['right'],
            broker_pos['quantity']
        ))
        
        if cursor.fetchone():
            # Already imported, skip
            return
        
        # Insert new UNMANAGED position
        timestamp = datetime.utcnow().isoformat()
        
        insert_query = """
            INSERT INTO positions 
            (symbol, expiry_date, strike_price, right, quantity, entry_price, 
             entry_timestamp, status, strategy_regime, error_msg)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'UNMANAGED', 'IMPORTED_BROKER', ?)
        """
        
        note = f"Imported from broker during reconciliation at {timestamp}"
        
        self.conn.execute(insert_query, (
            broker_pos['symbol'],
            broker_pos['expiry_date'],
            broker_pos['strike_price'],
            broker_pos['right'],
            broker_pos['quantity'],
            0.0,  # entry_price unknown
            timestamp,
            note
        ))
        self.conn.commit()
        print(f"[RECONCILE] Imported UNMANAGED position from broker: {broker_pos}")
    
    def _update_reconciliation_timestamp(self, timestamp: str) -> None:
        """
        Update last_reconciled_at for all open positions (status=OK case).
        
        Args:
            timestamp: UTC ISO timestamp
        """
        query = """
            UPDATE positions 
            SET last_reconciled_at=?
            WHERE status IN ('OPEN', 'PENDING')
        """
        
        self.conn.execute(query, (timestamp,))
        self.conn.commit()
    
    def get_system_state(self, key: str) -> Optional[str]:
        """
        Read a system state flag.
        
        Args:
            key: State key (e.g., 'trading_halted')
            
        Returns:
            Value string or None if not set
        """
        query = "SELECT value FROM system_state WHERE key=?"
        cursor = self.conn.execute(query, (key,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def set_system_state(self, key: str, value: str) -> None:
        """
        Write a system state flag (upsert).
        
        Args:
            key: State key (e.g., 'trading_halted')
            value: Value to set (e.g., 'true' or 'false')
        """
        # Upsert: INSERT OR REPLACE
        query = "INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)"
        self.conn.execute(query, (key, value))
        self.conn.commit()


if __name__ == "__main__":
    # Basic sanity check
    from database_manager import QuantDatabase
    from position_manager import PositionManager
    
    # Mock broker client
    class MockBroker:
        def get_positions(self):
            return []
    
    db = QuantDatabase()
    pm = PositionManager(db)
    broker = MockBroker()
    
    reconciliator = Reconciliator(pm, broker, db)
    result = reconciliator.reconcile()
    
    print(f"Reconciliation status: {result['status']}")
    print("✓ Reconciliator import and basic usage OK")
    
    db.close()
