import pandas as pd
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, classification_report, confusion_matrix
import joblib
from database_manager import QuantDatabase
import time

def train_deep_net():
    print("[INFO] Connecting to Database...")
    db = QuantDatabase()
    
    # 1. Load Data
    print("[INFO] Loading Smart Training Data...")
    query = "SELECT * FROM smart_training_data ORDER BY timestamp ASC"
    df = pd.read_sql(query, db.conn)
    db.close()
    
    print(f"[INFO] Loaded {len(df)} rows.")
    
    if len(df) < 500:
        print("[ERROR] Not enough data.")
        return

    # 2. Prepare Features & Target
    # Columns to exclude
    exclude_cols = ['id', 'timestamp', 'target', 'future_price'] # future_price possibly not in smart_training_data schema unless I saved it? 
    # In create_smart_targets, I saved: cols_to_keep = ['timestamp', 'spot_price', 'vix', 'call_delta', 'put_delta', 'rsi', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'atr', 'target']
    # So future_price is not there.
    
    feature_cols = [c for c in df.columns if c not in ['id', 'timestamp', 'target']]
    print(f"[INFO] Features: {feature_cols}")
    
    X = df[feature_cols].values
    y = df['target'].values
    
    # 3. Preprocessing (Standard Scaler)
    print("[INFO] Scaling features...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Save Scaler (Crucial for live bot)
    joblib.dump(scaler, "sniper_scaler.pkl")
    print("[INFO] Scaler saved as 'sniper_scaler.pkl'")
    
    # 4. Split Data (Time Series Split)
    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2, shuffle=False)
    
    print(f"[INFO] Train Size: {len(X_train)}, Test Size: {len(X_test)}")
    print(f"[INFO] Train Class Balance: {np.bincount(y_train)}")
    
    # 5. Model Architecture
    # Deep Net: (256, 128, 64)
    print("[INFO] Training Deep Neural Network (Sniper)...")
    mlp = MLPClassifier(
        hidden_layer_sizes=(256, 128, 64),
        activation='relu',
        solver='adam',
        alpha=0.0001, # Regularization
        early_stopping=True, # Prevent overfitting
        validation_fraction=0.1,
        max_iter=500,
        random_state=42,
        verbose=True
    )
    
    start_time = time.time()
    mlp.fit(X_train, y_train)
    duration = time.time() - start_time
    print(f"[INFO] Training completed in {duration:.2f} seconds.")
    
    # 6. Evaluation
    print("\n[EVALUATION]")
    y_pred = mlp.predict(X_test)
    
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    cm = confusion_matrix(y_test, y_pred)
    
    print(f"Accuracy:  {acc:.4f}")
    print(f"Precision: {prec:.4f} (How trustworthy are the shots?)")
    print("\nConfusion Matrix:")
    print(cm)
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))
    
    # 7. Save Model
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    model_filename = "sniper_brain.pkl"
    
    joblib.dump(mlp, model_filename)
    print(f"[SUCCESS] Model saved as '{model_filename}'")

if __name__ == "__main__":
    train_deep_net()
