import pandas as pd
from datetime import datetime, timedelta
from tqdm import tqdm
from connector import BreezeClient
import app_config as config
import os

# Force LIVE mode for data collection to ensure API connectivity
config.TRADING_MODE = "LIVE"

# Initialize Breeze Client
client = BreezeClient()

def fetch_history(stock_code: str, start_date: str, end_date: str, interval: str = "1minute"):
    """
    Fetch historical data for a given stock/index by chunking requests daily.
    
    Args:
        stock_code (str): Symbol name (e.g. "NIFTY")
        start_date (str): Start date in 'YYYY-MM-DD' format
        end_date (str): End date in 'YYYY-MM-DD' format
        interval (str): Candle interval (e.g. "1minute", "5minute")
    
    Returns:
        None (saves to CSV)
    """
    print(f"Starting download for {stock_code} from {start_date} to {end_date}...")

    # Convert strings to datetime objects
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    all_data = []
    
    # Calculate total days for progress bar
    total_days = (end_dt - start_dt).days + 1
    
    # Iterate through each day
    # We use a daily loop to strictly adhere to potential API limits 
    # and to provide granular progress updates.
    current_dt = start_dt
    
    with tqdm(total=total_days, desc="Downloading Data") as pbar:
        while current_dt <= end_dt:
            # Format dates for API (ISO 8601 usually required: YYYY-MM-DDTHH:MM:SS.000Z)
            # Breeze API specific usage varies, but get_historical_data_v2 typically takes ISO format strings.
            # We'll fetch full day 09:15 to 15:30 range effectively by requesting the full 24h day chunk
            
            from_date_str = current_dt.strftime("%Y-%m-%dT00:00:00.000Z")
            to_date_str = current_dt.strftime("%Y-%m-%dT23:59:59.000Z")
            
            try:
                # Exchange Code: NSE for Spot (NIFTY Index), NFO for Options/Futures.
                # Assuming user wants NIFTY Index Spot data for training.
                exchange_code = "NSE" 
                product_type = "cash" # cash/spot for Index
                
                # Fetch data
                data = client.breeze.get_historical_data_v2(
                    interval=interval,
                    from_date=from_date_str,
                    to_date=to_date_str,
                    stock_code=stock_code,
                    exchange_code=exchange_code,
                    product_type=product_type,
                    expiry_date="",
                    right="",
                    strike_price=""
                )
                
                # Check consistency of response
                if data and data.get("Success"):
                    df_chunk = pd.DataFrame(data["Success"])
                    all_data.append(df_chunk)
                
            except Exception as e:
                # Log error but continue
                # print(f"Error for {current_dt.date()}: {e}")
                pass
            
            # Increment day
            current_dt += timedelta(days=1)
            pbar.update(1)

    if not all_data:
        print("No data fetched. Check your API session or parameters.")
        return

    # Concatenate all chunks and clean
    print("\nProcessing and cleaning data...")
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Remove duplicates
    initial_len = len(final_df)
    final_df.drop_duplicates(subset=['datetime'], keep='first', inplace=True)
    
    if not final_df.empty:
        earliest_date = final_df['datetime'].min()
        print(f"Earliest Date Downloaded: {earliest_date}")
    
    # Save to CSV
    output_filename = f"{stock_code.lower()}_training_data.csv"
    final_df.to_csv(output_filename, index=False)
    print(f"Data saved to {output_filename}")

if __name__ == "__main__":
    # Example usage: Fetch last 30 days of data
    end = datetime.now()
    start = end - timedelta(days=32) # Buffer for weekends/holidays to ensure full month
    
    # fetch_history(
    #     stock_code="NIFTY",
    #     start_date=start.strftime("%Y-%m-%d"),
    #     end_date=end.strftime("%Y-%m-%d"),
    #     interval="1minute"
    # )
    
    print("\n[INFO] Fetching INDIA VIX Data...")
    fetch_history(
        stock_code="INDVIX",
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        interval="1minute"
    )
