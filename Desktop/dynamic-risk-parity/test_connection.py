import app_config as config
# Force TRADING_MODE to LIVE for this connection test
config.TRADING_MODE = "LIVE"

from connector import BreezeClient
import sys

def test_connection():
    print("Testing connection to ICICI Breeze API...")
    
    try:
        # Initialize client (will trigger generate_session because we forced LIVE mode)
        client = BreezeClient()
        
        # Fetch NIFTY Spot Price
        # Exchange: NSE, Stock Code: NIFTY, Product: cash
        print("Fetching NIFTY LTP...")
        
        # Note: breeze.get_quotes usually returns a dict.
        # We need to handle potential library variations, but standard is:
        response = client.breeze.get_quotes(
            stock_code="NIFTY",
            exchange_code="NSE",
            product_type="cash"
        )
        
        # Response structure typically:
        # {'Success': ..., 'Status': ..., 'Model': [{'ltp': 19500, ...}]}
        
        if response.get("Status") == 200:
            ltp = response.get("Success", [{}])[0].get("ltp")
            # Fallback if structure is different (sometimes in 'Model' or directly)
            if not ltp and 'Model' in response:
                 ltp = response['Model'][0].get('ltp')
            
            if ltp:
                print(f"CONNECTION SUCCESSFUL: NIFTY is at {ltp}")
            else:
                print(f"Connection Successful, but couldn't parse LTP from response: {response}")
        else:
            print(f"Connection Failed at API level. Response: {response}")

    except Exception as e:
        print(f"CONNECTION FAILED: {str(e)}")

if __name__ == "__main__":
    test_connection()
