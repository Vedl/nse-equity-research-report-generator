import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def visualize():
    db_path = "quant_lab.db"
    conn = sqlite3.connect(db_path)
    print(f"[INFO] Connecting to {db_path}...")

    # Load Option Chain Logs
    query = "SELECT * FROM option_chain_logs ORDER BY timestamp ASC"
    df = pd.read_sql(query, conn)
    conn.close()

    if df.empty:
        print("[ERROR] No data found in option_chain_logs.")
        return

    # Parse Timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='mixed')
    
    # ---------------------------------------------------------
    # 1. Infer Spot Price (Median Strike per Timestamp)
    # ---------------------------------------------------------
    # Since we log ATM +/- 5 strikes, the median strike at any time T is roughly the ATM strike, 
    # which tracks the Spot Price.
    df_spot = df.groupby('timestamp')['strike_price'].median().reset_index()
    df_spot.rename(columns={'strike_price': 'approx_spot'}, inplace=True)

    # ---------------------------------------------------------
    # 2. Extract Premiums for a specific Strike
    # ---------------------------------------------------------
    # Find the strike that is most frequently the "Median Strike" (ATM)
    most_common_atm = df_spot['approx_spot'].mode()[0]
    print(f"[INFO] Most Common ATM Strike: {most_common_atm}")
    
    # Filter data for this specific strike
    limit_strike_df = df[df['strike_price'] == most_common_atm]
    
    # Pivot to get Call/Put columns
    # We might have duplicates if logger ran fast, take mean just in case
    premium_df = limit_strike_df.pivot_table(index='timestamp', columns='right', values='ltp', aggfunc='mean')
    
    # ---------------------------------------------------------
    # 3. Analyze Time Gaps (The Crash/Choke)
    # ---------------------------------------------------------
    df_spot['time_diff'] = df_spot['timestamp'].diff().dt.total_seconds()
    
    # ---------------------------------------------------------
    # PLOTTING
    # ---------------------------------------------------------
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 18), sharex=True)
    
    # Plot 1: Market Proxy
    ax1.plot(df_spot['timestamp'], df_spot['approx_spot'], color='black', label='Approx. Spot (ATM Strike)')
    ax1.set_title(f"Market Movement (Inferred from Median Strike)")
    ax1.set_ylabel("Price")
    ax1.legend()
    ax1.grid(True)

    # Plot 2: Premiums
    if not premium_df.empty and 'Call' in premium_df.columns and 'Put' in premium_df.columns:
        ax2.plot(premium_df.index, premium_df['Call'], color='green', label=f'{most_common_atm} CE')
        ax2.plot(premium_df.index, premium_df['Put'], color='red', label=f'{most_common_atm} PE')
        ax2.set_title(f"Premiums for Strike {most_common_atm}")
        ax2.set_ylabel("Premium")
        ax2.legend()
        ax2.grid(True)
    else:
        ax2.text(0.5, 0.5, "Insufficient Data for Premiums", ha='center')

    # Plot 3: Time Gaps (API Health)
    # Filter out the first NaN
    gaps = df_spot.dropna(subset=['time_diff'])
    ax3.scatter(gaps['timestamp'], gaps['time_diff'], color='blue', alpha=0.6, s=10)
    ax3.set_title("API Health: Time Gaps Between Snapshots (Seconds)")
    ax3.set_ylabel("Gap (s)")
    ax3.set_ylim(0, max(gaps['time_diff'].max() + 5, 60)) # Cap nicely
    ax3.axhline(60, color='red', linestyle='--', label='1 Min Threshold')
    ax3.legend()
    ax3.grid(True)

    # Formatting Dates
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.autofmt_xdate()

    plt.tight_layout()
    output_file = "session_autopsy.png"
    plt.savefig(output_file)
    print(f"[SUCCESS] Chart saved to {output_file}")

if __name__ == "__main__":
    visualize()
