import pandas as pd
import numpy as np
import yfinance as yf
import joblib
import os
import time
from datetime import datetime, timedelta

class MarketConductor:
    """
    Orchestrates the market regime detection using an ML-based Classifier.
    Separates 'Market Analysis' from 'Execution Logic'.
    """
    def __init__(self):
        self.model = None
        self.scaler = None
        
        # Caching
        self.last_check_time = 0
        self.cached_regime = "REGIME_NEUTRAL"
        self.cache_duration = 1800 # 30 minutes
        
        # Load AI Components
        base_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(base_dir, 'regime_general.pkl')
        scaler_path = os.path.join(base_dir, 'regime_scaler.pkl')
        
        try:
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                self.model = joblib.load(model_path)
                self.scaler = joblib.load(scaler_path)
                print(f"[INFO] Conductor Loaded AI Brain: {model_path}")
            else:
                print(f"[WARN] Conductor AI missing. Will fallback to rule-based.")
        except Exception as e:
            print(f"[ERROR] Conductor Init Failed: {e}")

    def calculate_indicators(self, df, period=14):
        """
        Computes feature vector for regime model.
        """
        data = df.copy()
        
        # 1. Returns & Volatility
        data['returns'] = data['Close'].pct_change()
        data['volatility'] = data['returns'].rolling(window=20).std() * 100
        
        # 2. RSI
        delta = data['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
        loss = -delta.where(delta < 0, 0).ewm(alpha=1/period, adjust=False).mean()
        rs = gain / loss
        data['rsi'] = 100 - (100 / (1 + rs))
        
        # 3. ADX
        data['h-l'] = data['High'] - data['Low']
        data['h-pc'] = abs(data['High'] - data['Close'].shift(1))
        data['l-pc'] = abs(data['Low'] - data['Close'].shift(1))
        data['tr'] = data[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        
        data['up_move'] = data['High'] - data['High'].shift(1)
        data['down_move'] = data['Low'].shift(1) - data['Low']
        
        data['plus_dm'] = np.where((data['up_move'] > data['down_move']) & (data['up_move'] > 0), data['up_move'], 0)
        data['minus_dm'] = np.where((data['down_move'] > data['up_move']) & (data['down_move'] > 0), data['down_move'], 0)
        
        tr14 = data['tr'].ewm(alpha=1/period, adjust=False).mean()
        plus_dm14 = data['plus_dm'].ewm(alpha=1/period, adjust=False).mean()
        minus_dm14 = data['minus_dm'].ewm(alpha=1/period, adjust=False).mean()
        
        tr14 = tr14.replace(0, 1)
        plus_di = 100 * (plus_dm14 / tr14)
        minus_di = 100 * (minus_dm14 / tr14)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
        data['adx'] = dx.ewm(alpha=1/period, adjust=False).mean()
        
        # 4. Relative Volume
        data['Volume'] = data['Volume'].replace(0, np.nan).fillna(method='ffill')
        data['rel_volume'] = data['Volume'] / data['Volume'].rolling(window=20).mean()
        
        return data

    def get_regime(self, df_ignored, vix_ignored) -> str:
        """
        Determines the current market regime using the ML Classifier.
        Arguments (df_ignored, vix_ignored) kept for compatibility with Strategy Call.
        """
        # Cache Check
        if time.time() - self.last_check_time < self.cache_duration:
            return self.cached_regime
            
        print("[CONDUCTOR] Fetching Macro Data for Regime Analysis...")
        
        if not self.model or not self.scaler:
            return 'REGIME_NEUTRAL'
            
        try:
            # Download Data
            nifty = yf.download("^NSEI", period="60d", interval="1d", progress=False)
            vix = yf.download("^INDIAVIX", period="60d", interval="1d", progress=False)
            
            if len(nifty) < 20 or len(vix) < 20:
                print("[WARN] Insufficient history for regime.")
                return 'REGIME_NEUTRAL'
                
            # Flatten MultiIndex if present
            if isinstance(nifty.columns, pd.MultiIndex):
                nifty.columns = nifty.columns.droplevel(1)
            if isinstance(vix.columns, pd.MultiIndex):
                vix.columns = vix.columns.droplevel(1)
                
            # Prep dataframe
            df = nifty[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df = df.join(vix['Close'].rename('VIX'), how='inner')
            
            # Calculate Features
            df = self.calculate_indicators(df)
            
            # Get latest row
            last_row = df.iloc[-1]
            
            # Feature Vector
            # Order must match training: ['VIX', 'volatility', 'adx', 'rsi', 'rel_volume']
            features = [
                last_row['VIX'],
                last_row['volatility'],
                last_row['adx'],
                last_row['rsi'],
                last_row['rel_volume']
            ]
            
            # Scale
            X_scaled = self.scaler.transform([features])
            
            # Predict
            cluster = self.model.predict(X_scaled)[0]
            
            # Map
            # Cluster 0: Trending
            # Cluster 1: Neutral/Low Vol -> REGIME_LOW_VOL
            # Cluster 2: High Vol -> REGIME_HIGH_VOL
            
            regime_map = {
                0: 'REGIME_TRENDING',
                1: 'REGIME_LOW_VOL',
                2: 'REGIME_HIGH_VOL'
            }
            
            prediction = regime_map.get(cluster, 'REGIME_NEUTRAL')
            
            print(f"[CONDUCTOR] AI Analysis Complete. Cluster: {cluster} -> {prediction}")
            print(f"            Features: VIX={features[0]:.1f}, Vol={features[1]:.1f}, ADX={features[2]:.1f}")
            
            self.cached_regime = prediction
            self.last_check_time = time.time()
            return prediction
            
        except Exception as e:
            print(f"[ERROR] Regime Classification Failed: {e}")
            return 'REGIME_NEUTRAL'
