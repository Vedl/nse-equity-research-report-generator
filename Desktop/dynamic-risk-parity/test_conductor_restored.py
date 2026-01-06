from conductor import MarketConductor
import sys

def test():
    print("[TEST] Initializing MarketConductor...")
    try:
        conductor = MarketConductor()
        print("[TEST] Conductor Initialized.")
        
        print("[TEST] Calling get_regime(None, None)...")
        regime = conductor.get_regime(None, None)
        
        print(f"\n[RESULT] Detected Regime: {regime}")
        
        if regime in ['REGIME_TRENDING', 'REGIME_LOW_VOL', 'REGIME_HIGH_VOL', 'REGIME_NEUTRAL']:
             print("[PASS] Regime is a valid category.")
        else:
             print(f"[FAIL] Invalid Regime returned: {regime}")
             
    except Exception as e:
        print(f"[FAIL] Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
