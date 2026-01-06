import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
import joblib
from database_manager import QuantDatabase

def train_forest():
    print("[INFO] Connecting to Database...")
    db = QuantDatabase()
    
    # Load Data with Indicators
    # Note: We need 'spot_price' to calculate target, even if it's a feature too.
    query = "SELECT * FROM synthetic_options ORDER BY timestamp ASC"
    df = pd.read_sql(query, db.conn)
    db.close()
    
    print(f"[INFO] Loaded {len(df)} rows.")
    
    # 1. Target Creation
    # Predict if Price(t+5) > Price(t)
    df['future_price'] = df['spot_price'].shift(-5)
    df['target'] = (df['future_price'] > df['spot_price']).astype(int)
    
    # Drop rows with NaN (Result of shift or indicators)
    df.dropna(inplace=True)
    
    print(f"[INFO] Training Data Size: {len(df)}")
    
    # 2. Select Features
    # Requirements: RSI, MACD, Spot_Price, VIX, Call_Delta
    features = ['rsi', 'macd', 'spot_price', 'vix', 'call_delta']
    
    # Verify these columns exist
    missing = [c for c in features if c not in df.columns]
    if missing:
        print(f"[ERROR] Missing columns: {missing}. Did you run add_indicators.py?")
        return

    X = df[features]
    y = df['target']
    
    # 3. Model Training
    # Split 80/20, No Shuffle (Time Series Split)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    print(f"[INFO] Training Random Forest (n=200, depth=10)...")
    rf = RandomForestClassifier(n_estimators=200, max_depth=10, random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)
    
    # 4. Evaluation
    y_pred = rf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    print("="*30)
    print(f"accuracy: {acc:.4f}")
    print("="*30)
    
    print("\nConfusion Matrix:")
    print(confusion_matrix(y_test, y_pred))
    
    # 5. Feature Importance
    print("\n[FEATURE IMPORTANCE]")
    importances = rf.feature_importances_
    feature_imp_df = pd.DataFrame({'Feature': features, 'Importance': importances})
    feature_imp_df = feature_imp_df.sort_values('Importance', ascending=False)
    print(feature_imp_df)
    
    # Save Model
    joblib.dump(rf, "forest_brain.pkl")
    print("\n[SUCCESS] Model saved as 'forest_brain.pkl'")

if __name__ == "__main__":
    train_forest()
