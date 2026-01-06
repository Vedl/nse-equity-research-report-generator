import json
import time
from datetime import datetime
from connector import BreezeClient
from database_manager import QuantDatabase
import utils
import sys

def main():
    print("[INFO] Starting Chain Logger...")
    
    # Initialize DB and Client
    try:
        db = QuantDatabase()
        client = BreezeClient()
        breeze = client.breeze
    except Exception as e:
        print(f"[FATAL] Initialization failed: {e}")
        sys.exit(1)

    stock_code = "NIFTY"
    
    print(f"[INFO] Monitoring {stock_code} Option Chain (ATM +/- 5 strikes). Press Ctrl+C to stop.")

    while True:
        try:
            now = datetime.now()
            print(f"\n[LOOP] Fetching data at {now.strftime('%H:%M:%S')}...")
            
            # 1. Get NIFTY Spot Price for ATM
            # Note: Breeze API uses 'NIFTY' or 'NIFTY 50' depending on exact symbol mapping. 
            # Usually 'NIFTY' for NSE Index.
            spot_quotes = breeze.get_quotes(stock_code="NIFTY", exchange_code="NSE", product_type="cash", right="others", strike_price="0", expiry_date="")
            
            if not spot_quotes or 'Success' not in spot_quotes:
                 # Fallback/Error handling
                 print(f"[WARN] Failed to fetch Spot Price: {spot_quotes}")
                 # Try continuing if possible or retry
                 time.sleep(5)
                 continue
                 
            # Parse LTP. Structure depends on API response.
            # Assuming list of dicts or standard response 'Success': [{'ltp': ...}]
            # Usually response is dict with 'Success' key containing list
            ltp_spot = 0.0
            if 'Success' in spot_quotes and len(spot_quotes['Success']) > 0:
                ltp_spot = float(spot_quotes['Success'][0]['ltp'])
            
            if ltp_spot == 0:
                 print("[WARN] Spot Price is 0. Using fallback or skipping.")
                 time.sleep(5)
                 continue
                 
            # 2. Calculate ATM
            atm_strike = round(ltp_spot / 50) * 50
            print(f"[INFO] Spot: {ltp_spot} | ATM: {atm_strike}")
            
            # 3. Define Strikes (ATM - 5 to ATM + 5) -> 11 strikes actually including ATM
            # User said "10 strikes total", let's do ATM - 5 to ATM + 5 (exclusive? inclusive?)
            # "ATM - 5 strikes to ATM + 5 strikes" usually implies range.
            # 50 points steps.
            # Let's do 5 below and 4 above + ATM = 10? Or just range.
            # I will ensure good coverage: 5 down, ATM, 5 up = 11 strikes.
            
            strikes = [atm_strike + (i * 50) for i in range(-5, 6)]
            
            # 4. Get Expiry
            expiry_str = utils.get_next_expiry()
            
            # Convert DD-MMM-YYYY to ISO (Expected by Breeze API: YYYY-MM-DDTHH:MM:SS.000Z)
            # utils returns e.g. "30-DEC-2025"
            try:
                # Title case the month for parsing just in case (DEC -> Dec)
                expiry_dt = datetime.strptime(expiry_str.title(), "%d-%b-%Y")
                expiry_iso = expiry_dt.strftime("%Y-%m-%dT06:00:00.000Z")
                print(f"[INFO] Target Expiry: {expiry_str} -> {expiry_iso}")
            except ValueError as e:
                print(f"[ERROR] Date parsing failed for {expiry_str}: {e}")
                time.sleep(10)
                continue
            
            # 5. Fetch Quotes
            saved_count = 0
            
            for strike in strikes:
                for right in ["Call", "Put"]:
                    try:
                        # Fetch Quote
                        # Note: NIFTY Options are on 'NFO' exchange
                        quote = breeze.get_quotes(
                            stock_code="NIFTY",
                            exchange_code="NFO",
                            product_type="options",
                            expiry_date=expiry_iso,
                            strike_price=str(strike),
                            right=right.lower()
                        )
                        
                        if quote and 'Success' in quote and len(quote['Success']) > 0:
                            data = quote['Success'][0]
                            ltp_opt = float(data.get('ltp', 0))
                            oi = int(data.get('open_interest', 0) or 0)
                            vol = int(data.get('volume', 0) or 0)
                            
                            db.insert_option_tick(
                                expiry_date=expiry_str,
                                strike_price=strike,
                                right=right,
                                ltp=ltp_opt,
                                open_interest=oi,
                                volume=vol
                            )
                            saved_count += 1
                    
                    except Exception as e:
                        # Check for JSON error (wrapped or direct)
                        is_json_error = isinstance(e, json.JSONDecodeError) or "Expecting value" in str(e)
                        
                        if is_json_error:
                             print(f"[INFO] Retrying {strike} {right} in 1s...")
                             time.sleep(1.0)
                             try:
                                 # RETRY LOGIC (Duplicate of above)
                                 quote = breeze.get_quotes(
                                     stock_code="NIFTY",
                                     exchange_code="NFO",
                                     product_type="options",
                                     expiry_date=expiry_iso,
                                     strike_price=str(strike),
                                     right=right.lower()
                                 )
                                 
                                 if quote and 'Success' in quote and len(quote['Success']) > 0:
                                     data = quote['Success'][0]
                                     ltp_opt = float(data.get('ltp', 0))
                                     oi = int(data.get('open_interest', 0) or 0)
                                     vol = int(data.get('volume', 0) or 0)
                                     
                                     db.insert_option_tick(
                                         expiry_date=expiry_str,
                                         strike_price=strike,
                                         right=right,
                                         ltp=ltp_opt,
                                         open_interest=oi,
                                         volume=vol
                                     )
                                     saved_count += 1
                                     print(f"[SUCCESS] Retry successful for {strike} {right}")
                                     
                             except Exception as retry_e:
                                 print(f"[WARN] Retry failed for {strike} {right}. Skipping.")
                        else:
                             print(f"[ERROR] Fetch failed for {strike} {right}: {e}")
                    
                    time.sleep(0.5) # Increased Rate limit protection
            
            print(f"[LOG] Saved {saved_count} option contracts for {now.strftime('%Y-%m-%d %H:%M:%S')}.")
            
            # Loop delay
            time.sleep(60)

        except KeyboardInterrupt:
            print("\n[INFO] Checking out...")
            break
        except Exception as e:
            print(f"[ERROR] Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
