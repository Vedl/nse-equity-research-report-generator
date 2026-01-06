"""
Database Initialization Script
Ensures the positions table schema is created.
Safe to run multiple times (idempotent).
"""

from database_manager import QuantDatabase

def main():
    db = QuantDatabase()
    # init_schema() is called automatically in __init__
    # but we explicitly call it again to ensure idempotency
    db.init_schema()
    
    # Verify table exists
    cursor = db.get_connection().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='positions'"
    )
    
    if cursor.fetchone():
        print("✓ DB initialized successfully.")
        print("✓ positions table ready for use.")
    else:
        print("✗ ERROR: positions table creation failed.")
    
    db.close()

if __name__ == "__main__":
    main()
