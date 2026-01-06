import pandas as pd
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report
import joblib
from database_manager import QuantDatabase
import time

def train_neural_net():
    print("[INFO] Connecting to Database...")
    db = QuantDatabase()
    
    # Load Data
    query = """
    SELECT timestamp, spot_price, vix, call_delta, put_delta 
    FROM synthetic_options 
    ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, db.conn)
    db.close()
    print(f"[INFO] Loaded {len(df)} rows.")

    if len(df) < 500:
        print("[ERROR] Not enough data to train.")
        return

    # 1. Feature Engineering: Lags (Memory)
    lag_features = ['spot_price', 'vix', 'call_delta']
    n_lags = 10
    
    print(f"[INFO] Generating {n_lags} lags for {lag_features}...")
    
    for col in lag_features:
        for lag in range(1, n_lags + 1):
            df[f'{col}_lag_{lag}'] = df[col].shift(lag)
            
    # 2. Target Creation
    # Predict if Price(t+5) > Price(t)
    df['future_price'] = df['spot_price'].shift(-5)
    df['target'] = (df['future_price'] > df['spot_price']).astype(int)
    
    # Drop NaNs (created by lags and future shift)
    df.dropna(inplace=True)
    
    print(f"[INFO] Training Data Size: {len(df)}")
    print(f"[INFO] Class Balance:\n{df['target'].value_counts(normalize=True)}")
    
    # 3. Prepare X and y
    # Feature columns: Original + Lags
    # (Excluding timestamp, future_price, target, and put_delta if we didn't lag it? 
    # User said lag spot, call_delta, vix. I'll include current values of these + put_delta too as features)
    
    feature_cols = [c for c in df.columns if c not in ['timestamp', 'future_price', 'target', 'id']]
    # Ensure all numerical
    
    X = df[feature_cols].values
    y = df['target'].values
    
    # 4. Preprocessing
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Save Scaler
    joblib.dump(scaler, "scaler.pkl")
    print("[INFO] Scaler saved as 'scaler.pkl'")
    
    # 5. Split Data
    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2, shuffle=False)
    # shuffle=False is important for Time Series?
    # Actually, for standard MLP classification on independent samples (feature engineered with lags), 
    # shuffling is usually okay but preserving time order for Train/Test split is better (Prevent lookahead bias).
    # train_test_split(shuffle=False) does exactly this: Train = first 80%, Test = last 20%.
    
    # 6. Model Training
    print("[INFO] Training MLPClassifier (Deep Neural Network)...")
    mlp = MLPClassifier(
        hidden_layer_sizes=(128, 64, 32),
        activation='relu',
        solver='adam',
        max_iter=500,
        random_state=42,
        verbose=True
    )
    
    start_time = time.time()
    mlp.fit(X_train, y_train)
    duration = time.time() - start_time
    print(f"[INFO] Training completed in {duration:.2f} seconds.")
    
    # 7. Evaluation
    y_pred = mlp.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)
    
    print(f"\n[RESULTS]")
    print(f"Accuracy: {acc:.4f}")
    print("Confusion Matrix:")
    print(cm)
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    # 8. Save Model
    joblib.dump(mlp, "neural_brain.pkl")
    print("[SUCCESS] Model saved as 'neural_brain.pkl'")

if __name__ == "__main__":
    train_neural_net()
