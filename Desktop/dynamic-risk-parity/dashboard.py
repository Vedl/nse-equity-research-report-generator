import pandas as pd
import matplotlib.pyplot as plt
import os

def generate_dashboard():
    print("Generating Performance Report...")
    
    file_path = "paper_trades.csv"
    if not os.path.exists(file_path):
        print("Error: paper_trades.csv not found.")
        return

    # Load Data
    import csv
    
    data = []
    try:
        with open(file_path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader, None) # Skip original header
            
            for row in reader:
                # Row might have 5 or 7 columns
                # ["Timestamp", "Symbol", "Action", "Quantity", "Price", "Right", "Strike"]
                # If 5 cols, Right/Strike are missing
                
                if len(row) < 5:
                     continue
                     
                record = {
                    "Timestamp": row[0],
                    "Symbol": row[1],
                    "Action": row[2],
                    "Quantity": row[3],
                    "Price": row[4]
                }
                
                if len(row) >= 7:
                    record["Right"] = row[5]
                    record["Strike"] = row[6]
                else:
                    record["Right"] = "Unknown"
                    record["Strike"] = "N/A"
                    
                data.append(record)
                
        df = pd.DataFrame(data)
        print(f"Loaded {len(df)} rows.")
        
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    if df.empty:
        print("No trades found in CSV.")
        return

    # Check for required columns
    required_cols = {'Action', 'Price', 'Right', 'Timestamp'}
    if not required_cols.issubset(df.columns):
        print(f"CSV missing columns. Found: {df.columns}")
        # Handle legacy CSV format if created before options pivot
        # If 'Right' is missing, maybe fill 'Unknown'
        if 'Right' not in df.columns:
            df['Right'] = 'Unknown'

    # Filter for standard options trades or legacy
    # We maintain separate FIFO queues for Calls and Puts (and 'Unknown')
    trades = []
    
    # queues = { 'Call': [], 'Put': [], ... }
    # Store indices of Open positions: (index, price, quantity)
    entry_queues = {} 

    for i, row in df.iterrows():
        action = row['Action'].lower()
        right = row.get('Right', 'Unknown')
        price = float(row['Price'])
        timestamp = row['Timestamp']
        
        # Key to match trades. strictly speaking should match Strike too, 
        # but per user request/FIFO nature of this simple bot:
        key = right 
        
        if key not in entry_queues:
            entry_queues[key] = []
            
        if action == 'sell':
            # Entry (Short Selling)
            entry_queues[key].append({'price': price, 'time': timestamp})
        elif action == 'buy':
            # Exit (Buy to Cover)
            if entry_queues[key]:
                entry = entry_queues[key].pop(0)
                entry_price = entry['price']
                exit_price = price
                
                # Profit for Short: Entry - Exit
                pnl = entry_price - exit_price
                
                trades.append({
                    'Entry Time': entry['time'],
                    'Exit Time': timestamp,
                    'Type': f"Short {right}",
                    'Entry': entry_price,
                    'Exit': exit_price,
                    'PnL': pnl
                })

    if not trades:
        print("No completed trades found (positions might be open).")
        return

    # Create Trades DataFrame
    trades_df = pd.DataFrame(trades)
    
    # --- Statistics ---
    total_trades = len(trades_df)
    winning_trades = trades_df[trades_df['PnL'] > 0]
    losing_trades = trades_df[trades_df['PnL'] <= 0]
    
    win_rate = (len(winning_trades) / total_trades) * 100
    total_pnl = trades_df['PnL'].sum()
    
    best_trade_pnl = trades_df['PnL'].max()
    worst_trade_pnl = trades_df['PnL'].min()
    
    # Calculate Max Drawdown
    # Create a cumulative series
    trades_df['Cumulative PnL'] = trades_df['PnL'].cumsum()
    
    # Calculate Running Max
    trades_df['Running Max'] = trades_df['Cumulative PnL'].cummax()
    
    # Calculate Drawdown
    trades_df['Drawdown'] = trades_df['Running Max'] - trades_df['Cumulative PnL']
    
    # Max Drawdown is the maximum value of the Drawdown series
    max_drawdown = trades_df['Drawdown'].max()
    # If cum PnL starts negative, running max might be < 0 if strictly following cummax logic,
    # but usually DD is peak to trough. If no new peak, DD increases.
    # The above formula works: Running Max is the highest peak so far. Drawdown is distance from that peak.
    
    print("\n" + "="*30)
    print(" ROBUST PERFORMANCE REPORT")
    print("="*30)
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {win_rate:.2f}%")
    print(f"Total P&L:    {total_pnl:.2f} Points")
    print(f"Max Drawdown: {max_drawdown:.2f} Points")
    print(f"Best Trade:   {best_trade_pnl:.2f}")
    print(f"Worst Trade:  {worst_trade_pnl:.2f}")
    print("="*30 + "\n")

    # --- Visualization ---
    plt.figure(figsize=(10, 6))
    plt.plot(range(1, total_trades + 1), trades_df['Cumulative PnL'], marker='o', linestyle='-', label='Equity Curve')
    
    # Optionally plot Max Drawdown regions?
    # For now just the requested Equity Curve
    
    plt.title('Performance: Equity Curve')
    plt.xlabel('Trade Count')
    plt.ylabel('Cumulative P&L (Points)')
    plt.axhline(0, color='r', linestyle='--', alpha=0.5)
    plt.legend()
    plt.grid(True)
    
    output_img = "equity_curve.png"
    plt.savefig(output_img)
    print(f"Equity curve chart saved to {output_img}")

if __name__ == "__main__":
    generate_dashboard()
