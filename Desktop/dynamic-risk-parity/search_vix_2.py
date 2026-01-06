from connector import BreezeClient
import app_config as config
config.TRADING_MODE = "LIVE"

def check_symbol(client, symbol):
    print(f"Testing {symbol}...")
    try:
        data = client.breeze.get_historical_data_v2(
            interval="1minute",
            from_date="2025-12-26T09:15:00.000Z",
            to_date="2025-12-26T15:30:00.000Z",
            stock_code=symbol,
            exchange_code="NSE",
            product_type="cash", # India VIX is an index/cash product
            expiry_date="",
            right="",
            strike_price=""
        )
        if data and 'Success' in data and len(data['Success']) > 0:
            print(f"[SUCCESS] Found data for {symbol}: {len(data['Success'])} rows")
            return True
        else:
            print(f"[FAIL] {symbol}: {data['Status']} {data.get('Error')}")
    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
    return False

client = BreezeClient()
candidates = [
    "INDIA VIX", "INDIAVIX", "VIX", "IVIX", "INDVIX", 
    "NIFTY VIX", "CNX VIX", 
    "NIFTY 50", "NIFTY" # Control Test
]

print("Starting Search...")
for cand in candidates:
    if check_symbol(client, cand):
        print(f"FOUND IT: {cand}")
        # continue to check others? No, assume first match.
        break
