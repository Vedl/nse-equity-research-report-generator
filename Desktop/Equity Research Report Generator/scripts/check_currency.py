#!/usr/bin/env python3
"""Quick check: is INFY data reported in USD instead of INR?"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf
import pandas as pd

# INFY.NS should be INR; let's check the raw yfinance data
t = yf.Ticker("INFY.NS")
info = t.info
print(f"INFY.NS financialCurrency: {info.get('financialCurrency')}")
print(f"INFY.NS currency: {info.get('currency')}")
print(f"INFY.NS market_cap: {info.get('marketCap')}")
print(f"INFY.NS current_price: {info.get('currentPrice')}")
print(f"INFY.NS shares_outstanding: {info.get('sharesOutstanding')}")

# Print raw financials
fin = t.financials  # index=items, columns=dates
if fin is not None and not fin.empty:
    print("\nRaw Income Statement (Total Revenue row):")
    for col in fin.columns:
        rev = fin.at["Total Revenue", col] if "Total Revenue" in fin.index else None
        print(f"  {col}: {rev}")

# Also check RELIANCE
t2 = yf.Ticker("RELIANCE.NS")
info2 = t2.info
print(f"\nRELIANCE.NS financialCurrency: {info2.get('financialCurrency')}")
print(f"RELIANCE.NS currency: {info2.get('currency')}")
print(f"RELIANCE.NS shares_outstanding: {info2.get('sharesOutstanding')}")

# Check USDINR
t3 = yf.Ticker("USDINR=X")
print(f"\nUSDINR fast_info last_price: {t3.fast_info.get('last_price')}")
try:
    print(f"USDINR info regularMarketPrice: {t3.info.get('regularMarketPrice')}")
except:
    pass
