import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import joblib
import os

def calculate_adx(df, period=14):
    """
    Computes ADX.
    """
    data = df.copy()
    data['h-l'] = data['High'] - data['Low']
    data['h-pc'] = abs(data['High'] - data['Close'].shift(1))
    data['l-pc'] = abs(data['Low'] - data['Close'].shift(1))
    data['tr'] = data[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    
    data['up_move'] = data['High'] - data['High'].shift(1)
    data['down_move'] = data['Low'].shift(1) - data['Low']
    
    data['plus_dm'] = np.where((data['up_move'] > data['down_move']) & (data['up_move'] > 0), data['up_move'], 0)
    data['minus_dm'] = np.where((data['down_move'] > data['up_move']) & (data['down_move'] > 0), data['down_move'], 0)
    
    # Smoothed
    tr14 = data['tr'].ewm(alpha=1/period, adjust=False).mean()
    plus_dm14 = data['plus_dm'].ewm(alpha=1/period, adjust=False).mean()
    minus_dm14 = data['minus_dm'].ewm(alpha=1/period, adjust=False).mean()
    
    tr14 = tr14.replace(0, 1)
    plus_di = 100 * (plus_dm14 / tr14)
    minus_di = 100 * (minus_dm14 / tr14)
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def main():
    print("[INFO] Downloading Market Data (5 Years)...")
    # NIFTY 50 and INDIA VIX
    # Utilizing ^NSEI and ^INDIAVIX
    
    # Download separately to ensure clean merge
    nifty = yf.download("^NSEI", period="5y", interval="1d", progress=False)
    vix = yf.download("^INDIAVIX", period="5y", interval="1d", progress=False)
    
    # Flatten multi-level columns if present (yfinance update)
    # Check if columns are MultiIndex
    if isinstance(nifty.columns, pd.MultiIndex):
        nifty.columns = nifty.columns.droplevel(1) # Drop Ticker level
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.droplevel(1)

    print(f"[INFO] NIFTY Rows: {len(nifty)} | VIX Rows: {len(vix)}")
    
    # Prepare Data
    df = nifty.copy()
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    
    # Merge VIX Close as 'VIX'
    # Align dates
    df = df.join(vix['Close'].rename('VIX'), how='inner')
    
    print("[INFO] Calculating Features...")
    
    # 1. Returns
    df['returns'] = df['Close'].pct_change()
    
    # 2. Volatility (20d Rolling Std of Returns)
    df['volatility'] = df['returns'].rolling(window=20).std() * 100 # Scaled for visibility
    
    # 3. ADX (14)
    df['adx'] = calculate_adx(df)
    
    # 4. RSI (14) - Momentum
    df['rsi'] = calculate_rsi(df['Close'])
    
    # 5. Relative Volume (20d)
    # Handle Volume=0
    df['Volume'] = df['Volume'].replace(0, np.nan).fillna(method='ffill')
    df['rel_volume'] = df['Volume'] / df['Volume'].rolling(window=20).mean()
    
    # Drop NaNs
    df.dropna(inplace=True)
    print(f"[INFO] Training Data Size: {len(df)} days")
    
    # Feature Selection for Clustering
    # We want to identify regimes based on Volatility, Trend, and Momentum
    # VIX is the ultimate volatility gauge, but realized volatility is also good.
    # User asked for: Volatility, Trend (ADX), Momentum (RSI), Rel Volume.
    # And specifically VIX analysis in output.
    # We will Include VIX in clustering? 
    # User Request: "Train it on the features to discover ... (VIX, ADX, RSI, RelVol)"
    # Actually, user said "Calculate Volatility...". and "Print average VIX...". 
    # Usually VIX *is* a feature. Let's include VIX as a feature.
    
    features = ['VIX', 'volatility', 'adx', 'rsi', 'rel_volume']
    X = df[features]
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Cluster
    print("[INFO] Training KMeans (3 Clusters)...")
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    clusters = kmeans.fit_predict(X_scaled)
    
    df['cluster'] = clusters
    
    # Analysis
    print("\n--- Regime Analysis ---")
    stats = df.groupby('cluster')[['VIX', 'returns', 'adx']].mean()
    counts = df['cluster'].value_counts()
    
    # Interpret Clusters
    # heuristic: Low VIX = Low Vol, High VIX = High Vol.
    # We can try to map them to names dynamically, or just print stats.
    
    for i in range(3):
        n = counts[i]
        mu_vix = stats.loc[i, 'VIX']
        mu_adx = stats.loc[i, 'adx']
        print(f"Cluster {i}: N={n} | Avg VIX: {mu_vix:.2f} | Avg ADX: {mu_adx:.2f}")
        
    # Save
    joblib.dump(kmeans, 'regime_general.pkl')
    joblib.dump(scaler, 'regime_scaler.pkl')
    print("\n[SUCCESS] Model saved as 'regime_general.pkl'")
    print("[SUCCESS] Scaler saved as 'regime_scaler.pkl'")

if __name__ == "__main__":
    main()
