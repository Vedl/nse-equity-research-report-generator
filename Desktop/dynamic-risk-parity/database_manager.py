import sqlite3
import pandas as pd
from datetime import datetime
import threading

class QuantDatabase:
    """
    Thread-safe SQLite database manager for quantitative trading system.
    Handles tick data, trades, and position state persistence.
    """
    
    def __init__(self, db_name="quant_lab.db"):
        """
        Initialize connection to SQLite database.
        Enable check_same_thread=False for multi-threading support.
        """
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.lock = threading.Lock()
        
        # Initialize all tables (including legacy and new positions table)
        self.create_tables()
        self.create_options_table()
        self.create_synthetic_table()
        self.create_stream_table()
        self.init_schema()  # New: positions table for state management
        self.create_reconciliation_table()  # Step 6: Reconciliation audit log
        self.create_system_state_table()  # Step 6: System flags persistence
        
        print(f"[INFO] Database initialized: {db_name}")

    def create_tables(self):
        """
        Create necessary tables if they don't exist.
        """
        with self.lock:
            cursor = self.conn.cursor()
            
            # Market Data Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    price REAL NOT NULL,
                    volume INTEGER DEFAULT 0
                )
            ''')
            
            # Trades Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    pnl REAL DEFAULT 0,
                    strategy_signal INTEGER
                )
            ''')
            
            self.conn.commit()

    def create_options_table(self):
        """
        Create table for option_chain_logs.
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS option_chain_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expiry_date TEXT NOT NULL,
                    strike_price REAL NOT NULL,
                    right TEXT NOT NULL,
                    ltp REAL,
                    open_interest INTEGER,
                    volume INTEGER
                )
            ''')
            self.conn.commit()

    def create_synthetic_table(self):
        """
        Create table for synthetic_options.
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS synthetic_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    spot_price REAL,
                    vix REAL,
                    strike_price REAL,
                    time_to_expiry REAL,
                    call_price REAL,
                    put_price REAL,
                    call_delta REAL,
                    put_delta REAL
                )
            ''')
            self.conn.commit()

    def create_stream_table(self):
        """
        Create table for websocket stream_logs.
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stream_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    stock_code TEXT NOT NULL,
                    ltp REAL,
                    volume INTEGER,
                    oi INTEGER
                )
            ''')
            self.conn.commit()

    def init_schema(self):
        """
        Create positions table for persistent state management.
        This table is the source of truth for position tracking across restarts.
        
        Schema enforces:
        - Unique position_id for each trade lifecycle
        - Status tracking: PENDING -> OPEN -> CLOSED (or FAILED/ORPHANED)
        - Full audit trail with entry/exit prices and timestamps
        - Reconciliation timestamp for broker sync verification
        
        TODO: Future integrations will add methods:
        - insert_position_pending() - Pre-flight record before order
        - mark_position_open() - Confirm broker acceptance
        - mark_position_closed() - Record exit and PnL
        - get_open_positions() - Query active positions
        - reconcile_positions() - Sync with broker state
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    expiry_date TEXT,
                    strike_price REAL,
                    right TEXT,
                    quantity INTEGER,
                    entry_price REAL,
                    entry_timestamp DATETIME,
                    exit_price REAL,
                    exit_timestamp DATETIME,
                    pnl REAL,
                    status TEXT,
                    broker_order_id TEXT,
                    strategy_regime TEXT,
                    error_msg TEXT,
                    last_reconciled_at DATETIME
                )
            ''')
            self.conn.commit()

    def create_reconciliation_table(self):
        """
        Create table for reconciliation audit log (Step 6).
        Logs every reconciliation attempt for debugging and compliance.
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reconciliation_log (
                    reconcile_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    broker_positions TEXT,
                    db_positions TEXT,
                    status TEXT,
                    discrepancy_notes TEXT
                )
            ''')
            self.conn.commit()

    def create_system_state_table(self):
        """
        Create table for system state flags (Step 6).
        Used to persist small key-value pairs like trading_halted flag.
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            self.conn.commit()

    def insert_stream_tick(self, stock_code: str, ltp: float, volume: int, oi: int, timestamp=None):
        """
        Insert Websocket tick data.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO stream_logs (timestamp, stock_code, ltp, volume, oi)
                VALUES (?, ?, ?, ?, ?)
            ''', (timestamp, stock_code, ltp, volume, oi))
            self.conn.commit()

    def insert_option_tick(self, expiry_date: str, strike_price: float, right: str, 
                           ltp: float, open_interest: int, volume: int, timestamp=None):
        """
        Insert Option Chain tick data.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO option_chain_logs 
                (timestamp, expiry_date, strike_price, right, ltp, open_interest, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, expiry_date, strike_price, right, ltp, open_interest, volume))
            self.conn.commit()

    def insert_synthetic_batch(self, records: list):
        """
        Bulk insert synthetic options data.
        records: list of tuples (timestamp, spot, vix, strike, tte, call_price, put_price, call_delta, put_delta)
        """
        with self.lock:
            cursor = self.conn.cursor()
            cursor.executemany('''
                INSERT INTO synthetic_options 
                (timestamp, spot_price, vix, strike_price, time_to_expiry, 
                 call_price, put_price, call_delta, put_delta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', records)
            self.conn.commit()

    def insert_tick(self, symbol: str, price: float, volume: int = 0, timestamp=None):
        """
        Efficiently insert a new price row.
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO market_data (symbol, timestamp, price, volume)
                VALUES (?, ?, ?, ?)
            ''', (symbol, timestamp, price, volume))
            self.conn.commit()

    def log_trade(self, trade_data: dict):
        """
        Insert trade details.
        Expected keys in trade_data: symbol, action, quantity, price, pnl, strategy_signal
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO trades (timestamp, symbol, action, quantity, price, pnl, strategy_signal)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp,
                trade_data.get('symbol'),
                trade_data.get('action'),
                trade_data.get('quantity'),
                trade_data.get('price'),
                trade_data.get('pnl', 0),
                trade_data.get('strategy_signal')
            ))
            self.conn.commit()

    def fetch_recent_data(self, symbol: str, limit: int = 100):
        """
        Return the last N rows as a pandas DataFrame.
        Useful for Strategy warm-up or calculation.
        """
        with self.lock:
            query = '''
                SELECT timestamp, price, volume 
                FROM market_data 
                WHERE symbol = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            '''
            df = pd.read_sql_query(query, self.conn, params=(symbol, limit))
            # Reverse to chronological order (oldest first)
            df = df.iloc[::-1].reset_index(drop=True)
            return df

    def get_connection(self):
        """
        Return raw connection for advanced queries or testing.
        """
        return self.conn

    def close(self):
        """Close the database connection."""
        self.conn.close()
        print("[INFO] Database connection closed.")


if __name__ == "__main__":
    # Test the Class
    db = QuantDatabase()
    
    # Test Insert
    db.insert_tick("NIFTY", 19500.55, 100)
    db.insert_tick("NIFTY", 19510.00, 150)
    
    # Test Log Trade
    trade = {
        'symbol': 'NIFTY',
        'action': 'buy',
        'quantity': 50,
        'price': 19500,
        'pnl': 0,
        'strategy_signal': 1
    }
    db.log_trade(trade)
    
    # Test Fetch
    df = db.fetch_recent_data("NIFTY", 5)
    print("\nRecent Data Fetch:")
    print(df)
    
    # Test positions table exists
    cursor = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
    if cursor.fetchone():
        print("\n✓ positions table verified")
    
    db.close()
