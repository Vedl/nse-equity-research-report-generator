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

            # Run DCF
            dcf_result = run_dcf(profile, financials, _config)
            intrinsic = dcf_result.intrinsic_value_per_share

            deviation = ((intrinsic - current_price) / current_price * 100) if current_price else None

            # Net debt
            debt_s = _col(balance, "total_debt")
            cash_s = _col(balance, "cash_and_equivalents")
            latest_debt = max(0.0, float(debt_s.dropna().iloc[-1]) if not debt_s.dropna().empty else 0.0)
            latest_cash = max(0.0, float(cash_s.dropna().iloc[-1]) if not cash_s.dropna().empty else 0.0)
            net_debt = latest_debt - latest_cash

            rows.append({
                "ticker": ticker,
                "current_price": current_price,
                "dcf_intrinsic": intrinsic,
                "deviation_%": deviation,
                "base_fcff_Cr": dcf_result.base_fcff / 1e7,
                "growth_rate": dcf_result.growth_rate,
                "wacc": dcf_result.wacc,
                "terminal_growth": dcf_result.terminal_growth,
                "net_debt_Cr": net_debt / 1e7,
                "shares_cr": dcf_result.shares_outstanding / 1e7,
            })

        except Exception as exc:
            print(f"  ERROR: {exc}")
            rows.append({
                "ticker": ticker,
                "current_price": None,
                "dcf_intrinsic": None,
                "deviation_%": None,
                "base_fcff_Cr": None,
                "growth_rate": None,
                "wacc": None,
                "terminal_growth": None,
                "net_debt_Cr": None,
                "shares_cr": None,
            })

    # Print table
    print("\n" + "="*140)
    print(f"{'Ticker':<12} {'Price':>10} {'DCF':>10} {'Dev%':>8} {'BaseFCFF(Cr)':>14} "
          f"{'Growth':>8} {'WACC':>8} {'TG':>6} {'NetDebt(Cr)':>14} {'Shares(Cr)':>12}")
    print("="*140)
    for r in rows:
        print(
            f"{r['ticker']:<12} "
            f"{_fmt(r['current_price']):>10} "
            f"{_fmt(r['dcf_intrinsic']):>10} "
            f"{_fmt(r['deviation_%'], suffix='%'):>8} "
            f"{_fmt(r['base_fcff_Cr']):>14} "
            f"{_fmt(r['growth_rate'], precision=3):>8} "
            f"{_fmt(r['wacc'], precision=3):>8} "
            f"{_fmt(r['terminal_growth'], precision=2):>6} "
            f"{_fmt(r['net_debt_Cr']):>14} "
            f"{_fmt(r['shares_cr']):>12}"
        )

    # Identify tickers with >40% deviation
    print("\n--- Tickers with |deviation| > 40% ---")
    for r in rows:
        d = r.get("deviation_%")
        if d is not None and abs(d) > 40:
            print(f"  {r['ticker']}: {d:+.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    diagnose()
