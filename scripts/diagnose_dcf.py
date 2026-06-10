#!/usr/bin/env python3
"""Diagnostic script: prints DCF decomposition for the 10 featured tickers.

Run:  python -m scripts.diagnose_dcf   (from repo root)

This does NOT modify any code — it only reads live yfinance data,
runs the DCF engine as-is, and prints a formatted diagnostic table.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import math
import pandas as pd

from equity_research.config import load_config
from equity_research.data.yfinance_provider import YFinanceProvider
from equity_research.analysis.dcf import run_dcf, compute_base_fcff, compute_growth_rates
from equity_research.analysis.ratios import _col

_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "BAJFINANCE", "MARUTI", "WIPRO", "ASIANPAINT",
]

_config = load_config()
_provider = YFinanceProvider(_config)


def _fmt(v, divisor=1, precision=2, suffix=""):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "N/A"
    return f"{v/divisor:,.{precision}f}{suffix}"


def diagnose():
    rows = []
    for ticker in _TICKERS:
        ns = f"{ticker}.NS"
        print(f"Fetching {ns}...", flush=True)
        try:
            profile = _provider.get_profile(ns)
            financials = _provider.get_financials(ns)

            current_price = profile.get("current_price")
            shares = profile.get("shares_outstanding")

            # Compute FCFF per year for diagnosis
            income = financials["income"]
            cashflow = financials["cash_flow"]
            balance = financials["balance_sheet"]

            rev = _col(income, "total_revenue")
            oi = _col(income, "operating_income")
            da = _col(cashflow, "depreciation_amortization")
            capex = _col(cashflow, "capital_expenditure")
            nwc = _col(cashflow, "change_in_working_capital")

            frame = pd.DataFrame(
                {"revenue": rev, "op_income": oi, "da": da, "capex": capex, "nwc": nwc}
            ).dropna(subset=["revenue", "op_income"])

            for col in ("da", "capex", "nwc"):
                frame[col] = frame[col].fillna(0.0)

            nopat = frame["op_income"] * (1.0 - _config.market.tax_rate)
            frame["fcff"] = nopat + frame["da"] + frame["capex"] + frame["nwc"]

            print(f"  FCFF per year for {ticker}:")
            for yr, row in frame.iterrows():
                print(f"    {yr}: Rev={row['revenue']/1e9:.1f}B  OI={row['op_income']/1e9:.1f}B  "
                      f"D&A={row['da']/1e9:.1f}B  CapEx={row['capex']/1e9:.1f}B  "
                      f"ΔNWC={row['nwc']/1e9:.1f}B  FCFF={row['fcff']/1e9:.1f}B")

            # Run Old DCF
            try:
                old_dcf_result = run_dcf(profile, financials, _config)
                old_intrinsic = old_dcf_result.intrinsic_value_per_share
                old_deviation = ((old_intrinsic - current_price) / current_price * 100) if current_price else None
            except Exception as e:
                old_intrinsic = None
                old_deviation = None

            # Run New Valuation (Router + Intrinsic + Comps)
            from equity_research.analysis.valuation import run_valuation
            val_result = run_valuation(profile, financials, _provider, _config)
            
            new_intrinsic = val_result.intrinsic_value
            new_deviation = ((new_intrinsic - current_price) / current_price * 100) if current_price and new_intrinsic is not None else None
            model_used = val_result.model_used
            
            rel_median = val_result.relative.median if val_result.relative else None
            rel_low = val_result.relative.low if val_result.relative else None
            rel_high = val_result.relative.high if val_result.relative else None

            rows.append({
                "ticker": ticker,
                "current_price": current_price,
                "old_dcf": old_intrinsic,
                "old_deviation": old_deviation,
                "model_used": model_used,
                "new_intrinsic": new_intrinsic,
                "new_deviation": new_deviation,
                "rel_median": rel_median,
                "rel_low": rel_low,
                "rel_high": rel_high,
            })

        except Exception as exc:
            print(f"  ERROR: {exc}")
            rows.append({
                "ticker": ticker,
                "current_price": None,
                "old_dcf": None,
                "old_deviation": None,
                "model_used": "ERROR",
                "new_intrinsic": None,
                "new_deviation": None,
                "rel_median": None,
                "rel_low": None,
                "rel_high": None,
            })

    # Print table
    print("\n" + "="*145)
    print(f"{'Ticker':<12} {'Price':>10} | {'Old DCF':>12} {'OldDev%':>8} | {'New Model':>15} {'New Int':>12} {'NewDev%':>8} | {'CompsMed':>10} {'Comps Range':>20}")
    print("="*145)
    for r in rows:
        range_str = f"[{_fmt(r['rel_low'])}, {_fmt(r['rel_high'])}]" if r['rel_low'] is not None else "N/A"
        print(
            f"{r['ticker']:<12} "
            f"{_fmt(r['current_price']):>10} | "
            f"{_fmt(r['old_dcf']):>12} "
            f"{_fmt(r['old_deviation'], suffix='%'):>8} | "
            f"{r['model_used']:>15} "
            f"{_fmt(r['new_intrinsic']):>12} "
            f"{_fmt(r['new_deviation'], suffix='%'):>8} | "
            f"{_fmt(r['rel_median']):>10} "
            f"{range_str:>20}"
        )

    # Identify tickers with >40% deviation in new model
    print("\n--- Tickers with |new deviation| > 40% ---")
    for r in rows:
        d = r.get("new_deviation")
        if d is not None and abs(d) > 40:
            print(f"  {r['ticker']} ({r['model_used']}): {d:+.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    diagnose()
