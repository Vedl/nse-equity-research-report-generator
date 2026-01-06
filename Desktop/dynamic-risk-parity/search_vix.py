from connector import BreezeClient
from datetime import datetime, timedelta
import app_config as config
config.TRADING_MODE = "LIVE"

def check_symbol(client, symbol):
    print(f"Testing {symbol}...")
    try:
        # Try last known trading day (Dec 26)
        data = client.breeze.get_historical_data_v2(
            interval="1minute",
            from_date="2025-12-26T09:15:00.000Z",
            to_date="2025-12-26T15:30:00.000Z",
            stock_code=symbol,
            exchange_code="NSE",
            product_type="cash",
            expiry_date="",
            right="",
            strike_price=""
        )
        if data and 'Success' in data and len(data['Success']) > 0:
            print(f"[SUCCESS] Found data for {symbol}: {len(data['Success'])} rows")
            return True
        else:
            print(f"[FAIL] No data for {symbol}: {data}")
    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
    return False

client = BreezeClient()
candidates = ["VIX", "INDIAVIX", "INDIA VIX", "NIFTY VIX", "CNX VIX", "INDIA VIX INDEX", "VOLT"]

found = False
for cand in candidates:
    if check_symbol(client, cand):
        found = True
        break
        
if not found:
    print("Could not find VIX symbol.")
