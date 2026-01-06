import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

def calculate_rsi(data, window=14):
    """
    Calculate Relative Strength Index (RSI) manually using pandas.
    Using Simple Moving Average for simplicity in this example.
    """
    delta = data.diff()
    gain = (delta.where(delta > 0, 0))
    loss = (-delta.where(delta < 0, 0))
    
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def train():
    print("Loading data...")
    try:
        df = pd.read_csv("nifty_training_data.csv")
    except FileNotFoundError:
        print("Error: 'nifty_training_data.csv' not found. Please run data_collector.py first.")
        return

    # Ensure column names are standardized
    # Breeze API often returns 'close', 'open' etc.
    # We'll normalize to lowercase just in case.
    df.columns = [c.lower() for c in df.columns]
    
    print("Engineering features...")
    # 1. SMAs
    df['sma_5'] = df['close'].rolling(window=5).mean()
    df['sma_15'] = df['close'].rolling(window=15).mean()
    
    # 2. RSI
    df['rsi'] = calculate_rsi(df['close'], window=14)
    
    # 3. Body Size
    df['body_size'] = df['close'] - df['open']
    
    # Define Target
    # 1 if Next Close > Current Close, else 0
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)
    
    # Clean: Drop NaNs created by rolling windows and shift
    df.dropna(inplace=True)
    
    # Define Features (X) and Target (y)
    features = ['sma_5', 'sma_15', 'rsi', 'body_size']
    X = df[features]
    y = df['target']
    
    print(f"Data shape after cleaning: {df.shape}")
    
    # Split Data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Initialize and Train Model
    print("Training RandomForestClassifier...")
    model = RandomForestClassifier(n_estimators=100, min_samples_split=10, random_state=42)
    model.fit(X_train, y_train)
    
    # Evaluate
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    print(f"Model Accuracy Score: {accuracy:.4f}")
    
    # Save Model
    model_filename = "my_model.pkl"
    joblib.dump(model, model_filename)
    print(f"Model saved to {model_filename}")

if __name__ == "__main__":
    train()
