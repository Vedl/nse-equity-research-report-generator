"""NSE 500 financial-extraction coverage report.

Sweeps the full company universe (data/company_universe.json), attempts to
extract each name's profile + annual financial statements via the production
``YFinanceProvider``, and classifies the outcome:

    OK         — profile resolved and every core financial field present
    PARTIAL    — profile resolved but some core fields missing/NaN
    EMPTY      — profile resolved but all three statements are empty
    NO_DATA    — profile did not resolve (unmapped/bad .NS symbol or no coverage)
    ERROR      — fetch raised after retries (rate limit / timeout / network)

Per-ticker it records which core fields were retrieved vs missing and the
failure reason, then prints a final coverage %% and the list of names still
failing with why.

Usage:
    python -m scripts.coverage_report [--limit N] [--offset N] [--out PATH]

Tip: set CACHE_DIR=/tmp/cov_cache to keep the sweep's disk cache off the repo,
and YF_RETRY_ATTEMPTS / YF_RETRY_BASE_DELAY to tune backoff for a public IP.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from equity_research.analysis.ratios import _col, _latest  # noqa: E402
from equity_research.config import load_config  # noqa: E402
from equity_research.data.yfinance_provider import YFinanceProvider  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent
_UNIVERSE = _REPO / "data" / "company_universe.json"

# Core fields the valuation/report pipeline actually depends on.
CORE_FIELDS: dict[str, list[str]] = {
    "income": ["total_revenue", "net_income", "ebitda", "operating_income", "basic_eps"],
    "balance_sheet": ["total_assets", "stockholders_equity", "total_debt", "cash_and_equivalents"],
    "cash_flow": ["operating_cash_flow", "capital_expenditure", "free_cash_flow"],
}
_TOTAL_CORE = sum(len(v) for v in CORE_FIELDS.values())


def _field_present(df, field: str) -> bool:
    """A field counts as retrieved if its column exists with a latest non-NaN value."""
    try:
        return _latest(_col(df, field)) is not None
    except Exception:  # noqa: BLE001
        return False


def assess_ticker(provider: YFinanceProvider, yf_ticker: str) -> dict:
    """Extract one ticker and classify the outcome."""
    t0 = time.monotonic()
    try:
        profile = provider.get_profile(yf_ticker)
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "reason": f"profile fetch raised: {exc}",
                "present": [], "missing": [], "elapsed": time.monotonic() - t0}

    if not profile.get("long_name"):
        return {"status": "NO_DATA",
                "reason": "profile did not resolve (unmapped/bad .NS symbol or no yfinance coverage)",
                "present": [], "missing": [], "elapsed": time.monotonic() - t0}

    try:
        fin = provider.get_financials(yf_ticker)
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "reason": f"financials fetch raised: {exc}",
                "present": [], "missing": [], "elapsed": time.monotonic() - t0}

    present: list[str] = []
    missing: list[str] = []
    all_empty = True
    for stmt, fields in CORE_FIELDS.items():
        df = fin.get(stmt)
        if df is not None and not df.empty:
            all_empty = False
        for f in fields:
            (present if (df is not None and _field_present(df, f)) else missing).append(f"{stmt}.{f}")

    elapsed = time.monotonic() - t0
    if all_empty:
        return {"status": "EMPTY",
                "reason": "profile resolved but all financial statements are empty",
                "present": present, "missing": missing, "elapsed": elapsed}
    if not missing:
        return {"status": "OK", "reason": "", "present": present, "missing": missing, "elapsed": elapsed}
    return {"status": "PARTIAL",
            "reason": f"{len(missing)}/{_TOTAL_CORE} core fields missing",
            "present": present, "missing": missing, "elapsed": elapsed}


def main() -> None:
    ap = argparse.ArgumentParser(description="NSE 500 extraction coverage report")
    ap.add_argument("--limit", type=int, default=None, help="only assess the first N tickers")
    ap.add_argument("--offset", type=int, default=0, help="skip the first N tickers")
    ap.add_argument("--out", type=str, default=str(_REPO / "data" / "coverage_report.json"))
    args = ap.parse_args()

    universe: dict = json.loads(_UNIVERSE.read_text())
    items = list(universe.items())[args.offset:]
    if args.limit is not None:
        items = items[: args.limit]

    config = load_config()
    provider = YFinanceProvider(config)

    results: dict[str, dict] = {}
    out_path = Path(args.out)
    t_start = time.monotonic()
    for i, (base, entry) in enumerate(items, 1):
        yf_ticker = entry.get("yfinance_ticker", f"{base}.NS")
        r = assess_ticker(provider, yf_ticker)
        r["name"] = entry.get("name")
        r["sector"] = entry.get("sector")
        r["yfinance_ticker"] = yf_ticker
        results[base] = r
        print(f"[{i}/{len(items)}] {yf_ticker:18s} {r['status']:8s} "
              f"({len(r['present'])}/{_TOTAL_CORE} fields, {r['elapsed']:.1f}s) {r['reason']}",
              flush=True)
        if i % 10 == 0 or i == len(items):  # checkpoint progress
            out_path.write_text(json.dumps(results, indent=2))

    out_path.write_text(json.dumps(results, indent=2))

    # ── Summary ──────────────────────────────────────────────────────────────
    counts = Counter(r["status"] for r in results.values())
    n = len(results)
    usable = counts["OK"] + counts["PARTIAL"]
    fields_retrieved = sum(len(r["present"]) for r in results.values())
    fields_possible = n * _TOTAL_CORE
    print("\n" + "=" * 64)
    print(f"NSE-500 EXTRACTION COVERAGE  ({n} tickers, {time.monotonic()-t_start:.0f}s)")
    print("=" * 64)
    for status in ("OK", "PARTIAL", "EMPTY", "NO_DATA", "ERROR"):
        print(f"  {status:8s}: {counts[status]:4d}  ({counts[status]/n*100:5.1f}%)")
    print("-" * 64)
    print(f"  Usable (OK+PARTIAL): {usable}/{n}  =  {usable/n*100:.1f}%")
    print(f"  Field-level coverage: {fields_retrieved}/{fields_possible}  =  "
          f"{fields_retrieved/fields_possible*100:.1f}%")
    print("-" * 64)
    failing = {b: r for b, r in results.items() if r["status"] in ("NO_DATA", "ERROR", "EMPTY")}
    print(f"  Names still failing ({len(failing)}):")
    for b, r in sorted(failing.items()):
        print(f"    {r['yfinance_ticker']:18s} {r['status']:8s} — {r['reason']}")
    print(f"\n  Full report written to {out_path}")


if __name__ == "__main__":
    main()
