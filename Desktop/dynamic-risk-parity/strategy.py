import pandas as pd
import numpy as np
import joblib
import os
import sys
from conductor import MarketConductor
from position_manager import PositionManager
from risk_controller import RiskController

class MLStrategy:
    """
    Sniper Strategy: High Precision, Low Recall.
    Uses Deep Neural Network generated signals with strict probability thresholds.
    """

    def __init__(self, breeze_client=None, db=None):
        print("[INFO] Sniper Strategy Initializing...")
        self.price_buffer = [] 
        self.model = None
        self.scaler = None
        self.breeze = breeze_client
        self.conductor = MarketConductor()
        
        # Position Manager - persistent state tracking
        if db is None:
            from database_manager import QuantDatabase
            db = QuantDatabase()
        self.position_manager = PositionManager(db)
        
        # Risk Controller - pre-trade gating (Step 8)
        risk_config = {
            'max_lots_per_trade': 2,
            'max_margin_per_trade': 150000,  # ₹1.5 lakh per trade
            'max_loss_per_trade': 15000,     # ₹15k max loss per trade
            'max_daily_loss': 30000,         # ₹30k max loss per day
            'loss_multiplier': 2.0           # For SHORT options worst-case
        }
        self.risk_controller = RiskController(db, risk_config)
        
        # Configuration
        self.confidence_threshold = 0.70
        self.stop_loss_pct = 0.20
        
        # Track entry details for current position (for stop loss calculation)
        # These are NOT the source of truth, just cached values
        self.active_position_id = None
        self.entry_price = 0.0
        self.entry_underlying_price = 0.0 
        
        # --- PATH LOGIC ---
        # Get the folder where strategy.py is located
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct full paths
        model_path = os.path.join(base_dir, 'sniper_brain.pkl')
        scaler_path = os.path.join(base_dir, 'sniper_scaler.pkl')
        
        print(f"[INFO] Looking for AI Brains at: {base_dir}")
        
        try:
            # Load Model
            if os.path.exists(model_path):
                self.model = joblib.load(model_path)
            else:
                print(f"[FATAL] Model file missing: {model_path}")
                sys.exit(1)
                
            # Load Scaler
            if os.path.exists(scaler_path):
                self.scaler = joblib.load(scaler_path)
            else:
                print(f"[FATAL] Scaler file missing: {scaler_path}")
                sys.exit(1)
                
            print(f"[INFO] Sniper System Loaded. Model: {model_path}")
            print(f"[INFO] Scaler Loaded. Path: {scaler_path}")
            
        except Exception as e:
            print(f"[FATAL] Failed to load AI components: {e}")
            sys.exit(1)

    def get_atm_strike(self, ltp: float) -> int:
        return round(ltp / 50) * 50

    def calculate_indicators(self, df):
        """
        Calculate technical indicators matching training data.
        """
        # RSI (14)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
        loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD (12, 26, 9)
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        # Bollinger Bands (20, 2)
        rolling_mean = df['close'].rolling(window=20).mean()
        rolling_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = rolling_mean + (rolling_std * 2)
        df['bb_lower'] = rolling_mean - (rolling_std * 2)
        
        # ATR Proxy (14)
        tr = abs(df['close'] - df['close'].shift(1))
        df['atr'] = tr.ewm(alpha=1/14, adjust=False).mean()
        
        return df

    def generate_signal(self, incoming_data: dict) -> dict:
        """
        Evaluate Sniper Model probability to generate entry signals.
        """
        current_close = float(incoming_data.get('last', 0.0))
        current_open = float(incoming_data.get('open', current_close))
        # High/Low for Conductor (Fallback to close if missing in tick stream)
        current_high = float(incoming_data.get('high', current_close))
        current_low = float(incoming_data.get('low', current_close))

        self.price_buffer.append({
            'close': current_close, 
            'open': current_open,
            'high': current_high,
            'low': current_low
        })

        # Ensure enough data for indicators
        if len(self.price_buffer) < 40:
             print(f"[INFO] Gathering data... {len(self.price_buffer)}/40")
             return {'signal': 0}

        # Keep buffer manageable
        if len(self.price_buffer) > 100:
            self.price_buffer.pop(0)

        # 1. Feature Calculations
        df = pd.DataFrame(self.price_buffer)
        df = self.calculate_indicators(df)
        
        latest = df.iloc[-1]
        
        # Check for NaNs
        if pd.isna(latest['macd_signal']) or pd.isna(latest['rsi']):
             print("[WAIT] Indicators warming up (NaN values)...")
             return {'signal': 0}
             
        # --- LIVE VIX FETCHING ---
        live_vix = 11.0 # Default safe fallback
        
        if self.breeze:
            try:
                # Try fetching INDVIX (Index)
                vix_quote = self.breeze.get_quotes(stock_code="INDVIX", exchange_code="NSE", product_type="cash")
                
                if vix_quote and 'Success' in vix_quote and len(vix_quote['Success']) > 0:
                    live_vix = float(vix_quote['Success'][0]['ltp'])
                else:
                    # Fallback or specific warning if critical
                    # print("[WARN] VIX Fetch Failed (Empty). Defaulting to 11.0")
                    pass 
            except Exception as e:
                print(f"[WARN] VIX Fetch Failed: {e}. Defaulting to {live_vix}")
                
        # --- SAFETY ADAPTER (Data Drift) ---
        # Model expects VIX > 11.0 (Training Range 12-16). 
        # If real VIX is 9.8, clamp it to 11.0 to avoid outlier penalty.
        model_input_vix = max(11.0, live_vix)
        
        # --- CONDUCTOR: REGIME DETECTION ---
        regime = self.conductor.get_regime(df, live_vix) # Use real VIX for regime
        print(f"[CONDUCTOR] Market Regime: {regime} | VIX: {live_vix}")

        # 2. Strict Feature Ordering & Construction
        # Must match training data (10 features): 
        feature_order = [
            'spot_price', 'vix', 'call_delta', 'put_delta', 
            'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'atr'
        ]
        
        live_features = {
            'spot_price': current_close,
            'vix': model_input_vix, # Use the Adjusted VIX for Brain
            'call_delta': 0.5, # ATM
            'put_delta': -0.5, # ATM
            'rsi': latest['rsi'],
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'bb_upper': latest['bb_upper'],
            'bb_lower': latest['bb_lower'],
            'atr': latest['atr']
        }
        
        # Create DataFrame with single row, correctly ordered
        live_df = pd.DataFrame([live_features], columns=feature_order)
        
        # --- INPUT VALIDATION ---
        if live_df.isnull().values.any() or np.isinf(live_df.values).any():
            print("[WAIT] Invalid feature values detected (NaN/Inf). Skipping prediction.")
            return {'signal': 0}

        # 3. Apply Scaling
        try:
            # Convert to numpy array to avoid "feature names" warning and ensure compatibility
            input_vector = live_df[feature_order].values
            
            # transform expects matching columns/shape
            scaled_features = self.scaler.transform(input_vector)
            
            # Debug Logging - Print raw scaled values to verify normalization
            # e.g. [-0.5, 1.2, ...] instead of [25000, 13, ...]
            # print(f"[DEBUG] Scaled Input: {scaled_features[0]}") 
            
        except Exception as e:
            print(f"[ERROR] Scaling failed: {e}")
            return {'signal': 0}

        # 4. Prediction
        prob = 0.0
        if self.model:
            try:
                prob = self.model.predict_proba(scaled_features)[0][1]
            except Exception as e:
                print(f"[ERROR] Prediction failed: {e}")
                return {'signal': 0}
        
        # --- STRIKE SELECTION LOGIC ---
        base_strike = self.get_atm_strike(current_close)
        target_strike = str(base_strike)
        
        # In LOW_VOL regime, switch to ITM for Sell PE (Spot + 100) or Sell CE (Spot - 100)
        # Assuming we only SELL PE (Bullish) for now based on training data bias (or logic below)
        # Logic below is HARDCODED to 'SHORT_PE' if prob > threshold.
        # So we only care about Put Strike.
        # ITM Put = Strike > Spot. So base_strike + 100 is Deep ITM (Riskier but higher delta/premium).
        # User said "Switch to ITM Strike Selection ... Scalps".
        # Yes, Selling ITM Puts is aggressive.
        
        is_scalp = False
        if regime == 'REGIME_LOW_VOL':
             target_strike = str(base_strike + 100) # Select ITM Put
             is_scalp = True
             # print(f"[STRATEGY] Low Vol Mode: Selecting ITM Strike {target_strike} for Scalp.")
        
        MOCK_PREMIUM = 200.0
        
        # --- Strict Stop Loss Logic ---
        # Check database for active position (PENDING or OPEN)
        if self.position_manager.has_open_position(symbol='NIFTY'):
             # Fetch active position from DB
             open_positions = self.position_manager.get_open_positions(symbol='NIFTY')
             if not open_positions:
                 # Edge case: has_open_position was True but get returned empty
                 # Continue to entry logic
                 pass
             else:
                 active_pos = open_positions[0]  # Should only be one
                 self.active_position_id = active_pos['position_id']
                 
                 # Restore cached values if not already set
                 if self.entry_price == 0.0:
                     self.entry_price = active_pos['entry_price']
                 if self.entry_underlying_price == 0.0:
                     # Approximate from current close (not perfect but prevents crash)
                     self.entry_underlying_price = current_close
                 
                 # Calculate simulated option price
                 right_for_exit = active_pos['right']
                 
                 if active_pos['quantity'] < 0:  # SHORT position
                     change = current_close - self.entry_underlying_price
                     current_sim_option_price = self.entry_price - change
                 
                 sl_threshold = self.entry_price * (1 + self.stop_loss_pct)
                 
                 if current_sim_option_price >= sl_threshold:
                     print(f"[RISK ALERT] Stop Loss Hit at {current_sim_option_price:.2f}. Closing position {self.active_position_id}")
                     
                     # Record exit in database
                     pnl = self.position_manager.record_exit(self.active_position_id, current_sim_option_price)
                     print(f"[EXIT] Position {self.active_position_id} closed. PnL: {pnl:.2f}")
                     
                     # Clear cached state
                     self.active_position_id = None
                     self.entry_price = 0.0
                     self.entry_underlying_price = 0.0
                     
                     return {'signal': -1, 'action': 'buy', 'right': right_for_exit, 'strike': target_strike, 'pnl': pnl}

                 return {'signal': 0}

        # 5. Entry Logic (Sniper)
        if prob > self.confidence_threshold:
            # CRITICAL: Check database before entering new position
            if self.position_manager.has_open_position(symbol='NIFTY'):
                print(f"[BLOCKED] Entry signal rejected: Already have OPEN/PENDING position")
                return {'signal': 0}
            
            print(f"[SNIPER] High Confidence Signal ({prob:.2f}). Regime: {regime}. Strike: {target_strike}")
            
            # STEP 8: PRE-TRADE RISK VALIDATION
            # Estimate margin (simplified: use premium * quantity * lot_size as proxy)
            lot_size = 25  # NIFTY lot size
            quantity = -25  # SHORT position (negative)
            estimated_margin = MOCK_PREMIUM * abs(quantity) * 2  # 2x premium as margin estimate
            
            allowed, risk_reason = self.risk_controller.validate_entry(
                symbol='NIFTY',
                expiry_date=datetime.now().strftime('%Y-%m-%d'),  # Simplified
                strike_price=float(target_strike),
                right='Put',
                quantity=quantity,
                entry_price=MOCK_PREMIUM,
                estimated_margin=estimated_margin
            )
            
            if not allowed:
                print(f"[RISK BLOCK] {risk_reason}")
                return {'signal': 0}
            
            print(f"[RISK OK] Pre-trade validation passed")
            
            # Record position as PENDING (pre-broker-call state)
            from datetime import datetime
            expiry_date = datetime.now().strftime('%Y-%m-%d')  # Simplified for now
            
            position_id = self.position_manager.record_entry(
                symbol='NIFTY',
                expiry_date=expiry_date,  # TODO: Use proper expiry from utils.get_next_expiry()
                strike_price=float(target_strike),
                right='Put',
                quantity=quantity,
                entry_price=MOCK_PREMIUM,
                strategy_regime=regime
            )
            
            print(f"[ENTRY] Position {position_id} recorded as PENDING")
            
            # Cache values for stop loss calculation
            self.active_position_id = position_id
            self.entry_underlying_price = current_close
            self.entry_price = MOCK_PREMIUM
            
            return {
                'signal': 1, 
                'action': 'sell', 
                'right': 'Put', 
                'strike': target_strike, 
                'pnl': 0.0,
                'regime': regime,
                'is_scalp': is_scalp,
                'position_id': position_id  # Pass to connector for broker call
            }
            
        else:
            print(f"[FILTER] Signal Rejected. Prob: {prob:.4f} | Regime: {regime}")
            return {'signal': 0}
