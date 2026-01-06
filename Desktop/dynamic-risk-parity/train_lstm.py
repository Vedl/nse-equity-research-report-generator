import numpy as np
import pandas as pd
import tensorflow as pd_tf # Name conflict protection if needed, but standard is import tensorflow as tf
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from sklearn.preprocessing import MinMaxScaler
import joblib
from database_manager import QuantDatabase
import os

# Suppress TF warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

def create_sequences(data, target, window_size):
    X, y = [], []
    # data: (N, features)
    # target: (N,)
    
    # We need samples where we have a full window of past data
    for i in range(window_size, len(data)):
        # Sequence: rows i-window_size to i (exclusive of i in python slicing? No, usually [i-win : i])
        # Let's say window=30.
        # i=30. seq = data[0:30] (rows 0..29, total 30).
        # Target corresponding to this sequence? 
        # The prompt says: "Past 30 minutes of data to predict the result 5 minutes later."
        # Usually this means the sequence ending at 't' tries to predict 't+5'.
        # The 'target' array should already be aligned such that target[i] is the outcome for time t.
        # But wait, how did we define Target?
        # "If price(t+5) > price(t), Target = 1."
        # So at row 't', we calculated Target based on future.
        # So for the sequence data[t-29 : t+1], the specific timestamp is 't'.
        # We want to map Sequence_t -> Target_t.
        
        X.append(data[i-window_size:i])
        y.append(target[i-1]) # target[i]?? 
        # Wait. if data indices are 0..N-1.
        # i=30. data[0:30] are rows 0..29. The last row is 29.
        # The target for this sequence should be the target associated with row 29.
        # So y.append(target[i-1])? Yes.
        
    return np.array(X), np.array(y)

def train_model():
    print("[INFO] connection to DB...")
    db = QuantDatabase()
    
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

    # 1. Feature Engineering & Target Creation
    # Target: Price(t+5) > Price(t)
    # Shift(-5) gives Price at t+5
    df['future_price'] = df['spot_price'].shift(-5)
    df['target'] = (df['future_price'] > df['spot_price']).astype(int)
    
    # Drop NaNs created by shift (last 5 rows)
    df.dropna(inplace=True)
    
    print(f"[INFO] Data after creating target: {len(df)} rows.")
    print(f"[INFO] Class balance: {df['target'].value_counts(normalize=True)}")
    
    features = ['spot_price', 'vix', 'call_delta', 'put_delta']
    data_values = df[features].values
    target_values = df['target'].values
    
    # 2. Preprocessing
    scaler = MinMaxScaler()
    data_scaled = scaler.fit_transform(data_values)
    
    # Save Scaler
    scaler_path = "scaler.pkl"
    joblib.dump(scaler, scaler_path)
    print(f"[INFO] Scaler saved to {scaler_path}")
    
    # 3. Create Sequences
    WINDOW_SIZE = 30
    X, y = create_sequences(data_scaled, target_values, WINDOW_SIZE)
    
    print(f"[INFO] Training Data Shape: X={X.shape}, y={y.shape}")
    
    # Split Train/Test (80/20)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    # 4. Model Architecture
    model = Sequential()
    # LSTM layer 1: 50 units, return_sequences=True
    model.add(LSTM(50, return_sequences=True, input_shape=(WINDOW_SIZE, len(features))))
    model.add(Dropout(0.2))
    
    # LSTM layer 2: 50 units
    model.add(LSTM(50))
    
    # Dense Output
    model.add(Dense(1, activation='sigmoid'))
    
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    model.summary()
    
    # 5. Train
    EPOCHS = 5 # User said 5-10
    BATCH_SIZE = 32
    
    print("[INFO] Starting Training...")
    history = model.fit(
        X_train, y_train,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        validation_data=(X_test, y_test)
    )
    
    # 6. Save Model
    model_path = "lstm_brain.h5"
    model.save(model_path)
    print(f"[SUCCESS] Model saved to {model_path}")

if __name__ == "__main__":
    train_model()
