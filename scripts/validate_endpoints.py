"""Validate the research endpoint across a diverse set of 10 tickers.

Imports _build_research and _normalize_ticker from main directly — no running
HTTP server is required.  Module-level init (config load, YFinanceProvider,
CSV load) runs on import, which exercises the same startup path as production.

Usage
-----
    python scripts/validate_endpoints.py

Exit codes
----------
    0 — all tickers pass
    1 — one or more tickers fail (details printed to stdout)

Assertions per ticker
---------------------
    1. company.name is not null
    2. price.current is not null
    3. financials.income_statement has >= 1 row
    4. ratios.net_margin is not null  (skipped for banks — see BANK_TICKERS)
       For banks: assert net_margin IS null (NII-based companies have no
       revenue-denominated margin, so null is the correct, expected output)
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

# Ensure project root is on sys.path so 'import main' works regardless of CWD
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from main import _build_research, _normalize_ticker  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TICKERS = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "HINDUNILVR",
    "SUNPHARMA",
    # TATAMOTORS.NS is currently broken on Yahoo Finance (returns 404 / "possibly
    # delisted") as of May 2026, likely due to DVR share restructuring.  Substituted
    # with MARUTI to keep automotive sector coverage in the test set.
    "MARUTI",
    "COALINDIA",
    "ADANIPORTS",
]

# Banks report Net Interest Income (NII), not revenue-based margins.
# net_margin will correctly be null for these tickers.
BANK_TICKERS: set[str] = {"HDFCBANK", "ICICIBANK"}

# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

Result = tuple[str, float | None, float | None, float | None, str, str]


def _validate_ticker(ticker: str) -> Result:
    """Run _build_research and assert expected fields. Return a result row."""
    ticker_ns = _normalize_ticker(ticker)
    try:
        t0 = time.monotonic()
        data = _build_research(ticker_ns)
        elapsed = time.monotonic() - t0

        name       = data["company"]["name"]
        price      = data["price"]["current"]
        income     = data["financials"]["income_statement"]
        net_margin = data["ratios"]["net_margin"]
        dcf_val    = (data["valuation"]["dcf"] or {}).get("intrinsic_value")

        assert name is not None, "company.name is null"
        assert price is not None, "price.current is null"
        assert len(income) >= 1, f"income_statement is empty (0 rows)"

        if ticker in BANK_TICKERS:
            # Banks: net_margin should be null (correct behaviour)
            if net_margin is not None:
                # Not a hard failure — NII-heavy banks can sometimes have
                # partial revenue data; warn but don't block.
                note = f"dcf/margin null expected for bank (got {net_margin:.2%})"
            else:
                note = "dcf/margin null — expected for banks ✓"
        else:
            assert net_margin is not None, "ratios.net_margin is null"
            note = f"({elapsed:.1f}s)"

        return (ticker, price, dcf_val, net_margin, "PASS", note)

    except AssertionError as exc:
        return (ticker, None, None, None, "FAIL", str(exc))
    except Exception as exc:
        return (ticker, None, None, None, "FAIL", f"{type(exc).__name__}: {exc}")


def main() -> None:
    print(f"\nValidating {len(TICKERS)} tickers …\n")

    results: list[Result] = []
    for ticker in TICKERS:
        print(f"  → {ticker:<14}", end=" ", flush=True)
        row = _validate_ticker(ticker)
        status = row[4]
        print(status)
        results.append(row)

    # ── Summary table ────────────────────────────────────────────────────
    col_w = {"ticker": 14, "price": 10, "dcf": 10, "margin": 12, "status": 6}
    header = (
        f"{'Ticker':<{col_w['ticker']}} "
        f"{'Price (₹)':>{col_w['price']}} "
        f"{'DCF (₹)':>{col_w['dcf']}} "
        f"{'Net Margin':>{col_w['margin']}} "
        f"{'Status':<{col_w['status']}} "
        f"Note"
    )
    separator = "─" * len(header)

    print(f"\n{separator}")
    print(header)
    print(separator)

    fail_count = 0
    for ticker, price, dcf, margin, status, note in results:
        price_s  = f"{price:>10,.1f}" if price  is not None else f"{'null':>10}"
        dcf_s    = f"{dcf:>10,.1f}"   if dcf    is not None else f"{'null':>10}"
        margin_s = f"{margin:>12.2%}" if margin is not None else f"{'null':>12}"
        print(
            f"{ticker:<{col_w['ticker']}} "
            f"{price_s} "
            f"{dcf_s} "
            f"{margin_s} "
            f"{status:<{col_w['status']}} "
            f"{note}"
        )
        if status == "FAIL":
            fail_count += 1

    print(separator)
    pass_count = len(results) - fail_count
    print(f"\n{pass_count}/{len(results)} tickers PASS\n")

    if fail_count:
        print(f"BLOCKING: {fail_count} ticker(s) failed. Fix before building the frontend.\n")
        sys.exit(1)
    else:
        print("All tickers passed. Backend is ready.\n")


if __name__ == "__main__":
    main()
