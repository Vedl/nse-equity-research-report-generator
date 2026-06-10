"""Download the Nifty 500 constituent list from NSE and enrich with yfinance
sector/industry data, then write equity_research/data/nifty500_tickers.csv.

Why the yfinance enrichment step matters
-----------------------------------------
get_peers() in yfinance_provider.py matches profile["sector"] and profile["industry"]
(yfinance strings, e.g. "Financial Services") against the CSV columns.  The raw NSE CSV
only provides a single "Industry" column with values like "BANKS", "FINANCIAL SERVICES" —
different strings that would cause get_peers() to find zero matches for every ticker.
By fetching yfinance sector/industry here, we ensure the CSV values are compatible.

Usage
-----
    python scripts/fetch_nifty500.py

Estimated runtime: ~5–10 minutes (500 tickers, 5 concurrent workers).
Re-run whenever the Nifty 500 composition changes (typically quarterly rebalancing).

Output
------
    equity_research/data/nifty500_tickers.csv
    Columns: ticker, company_name, sector, industry
"""

from __future__ import annotations

import io
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_OUTPUT_CSV = _PROJECT_ROOT / "equity_research" / "data" / "nifty500_tickers.csv"

_NSE_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
_NSE_HOME_URL = "https://www.nseindia.com"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_HOME_URL,
}

# ---------------------------------------------------------------------------
# Step 1 — Download the NSE Nifty 500 CSV
# ---------------------------------------------------------------------------


def _download_nse_csv() -> pd.DataFrame:
    """Try to download the NSE Nifty 500 CSV.

    NSE requires a browser-like session (cookies set by loading the homepage
    first).  Falls back with an instruction if the download fails.

    Returns:
        Raw DataFrame from the NSE CSV (all columns, unfiltered).

    Raises:
        SystemExit: if the download fails and no fallback is available.
    """
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)

    # Prime the session cookies by visiting the homepage
    logger.info("Priming NSE session cookies …")
    try:
        session.get(_NSE_HOME_URL, timeout=15)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load NSE homepage: %s — continuing anyway", exc)

    time.sleep(1)

    logger.info("Downloading Nifty 500 CSV from NSE …")
    try:
        resp = session.get(_NSE_CSV_URL, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text" not in content_type and "csv" not in content_type:
            raise ValueError(
                f"Unexpected content-type '{content_type}' — NSE may have returned HTML"
            )
        df = pd.read_csv(io.StringIO(resp.text))
        logger.info("Downloaded %d rows from NSE.", len(df))
        return df
    except Exception as exc:  # noqa: BLE001
        logger.error("NSE download failed: %s", exc)
        logger.error(
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "MANUAL FALLBACK:\n"
            "  1. Open https://www.nseindia.com/market-data/securities-available-for-trading\n"
            "     → scroll to 'Nifty 500' → click 'Download'\n"
            "  OR visit: %s directly in a browser\n"
            "  2. Save the file to: %s\n"
            "  3. Re-run this script.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            _NSE_CSV_URL,
            _OUTPUT_CSV,
        )
        sys.exit(1)


def _parse_nse_df(raw: pd.DataFrame) -> pd.DataFrame:
    """Filter to EQ series and extract Symbol + Company Name.

    NSE CSV columns: 'Company Name', 'Industry', 'Symbol', 'Series', 'ISIN Code'
    (column names may have leading/trailing spaces — strip them).
    """
    raw.columns = raw.columns.str.strip()
    logger.info("NSE columns: %s", list(raw.columns))

    # Filter to equity series
    if "Series" in raw.columns:
        eq = raw[raw["Series"].str.strip() == "EQ"].copy()
        logger.info(
            "Filtered to EQ series: %d / %d rows", len(eq), len(raw)
        )
    else:
        logger.warning("No 'Series' column found — using all rows")
        eq = raw.copy()

    # Normalise column names to what we expect
    col_map = {
        "Symbol":       "symbol",
        "Company Name": "company_name",
        "Industry":     "nse_industry",
    }
    missing = [c for c in col_map if c not in eq.columns]
    if missing:
        raise ValueError(f"Expected columns not found in NSE CSV: {missing}")

    result = eq.rename(columns=col_map)[["symbol", "company_name", "nse_industry"]].copy()
    result["symbol"] = result["symbol"].str.strip()
    result["company_name"] = result["company_name"].str.strip()
    result["nse_industry"] = result["nse_industry"].str.strip()
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Step 2 — Enrich with yfinance sector/industry
# ---------------------------------------------------------------------------


def _fetch_yf_sector(symbol: str) -> tuple[str, str, str]:
    """Return (ticker_ns, sector, industry) from yfinance info.

    Falls back to ("", "") if yfinance returns no data.
    """
    ticker_ns = f"{symbol.upper()}.NS"
    try:
        info = yf.Ticker(ticker_ns).info
        sector = (info.get("sector") or "").strip()
        industry = (info.get("industry") or "").strip()
        return ticker_ns, sector, industry
    except Exception as exc:  # noqa: BLE001
        logger.debug("yfinance fetch failed for %s: %s", ticker_ns, exc)
        return ticker_ns, "", ""


def _enrich_with_yfinance(
    parsed: pd.DataFrame,
    max_workers: int = 5,
    batch_sleep: float = 1.0,
) -> pd.DataFrame:
    """Add yfinance sector/industry columns to the parsed NSE DataFrame.

    Processes tickers in batches with a short sleep between batches to
    avoid triggering Yahoo's rate limiter.

    Args:
        parsed:       DataFrame with columns: symbol, company_name, nse_industry
        max_workers:  Thread pool size for concurrent yfinance fetches.
        batch_sleep:  Seconds to sleep between batches.

    Returns:
        DataFrame with columns: ticker, company_name, sector, industry
    """
    symbols = parsed["symbol"].tolist()
    total = len(symbols)
    logger.info(
        "Enriching %d tickers with yfinance sector/industry "
        "(max_workers=%d) — estimated %.0f–%.0f min …",
        total,
        max_workers,
        total / max_workers / 60,
        total / max_workers * 2 / 60,
    )

    results: dict[str, tuple[str, str]] = {}  # symbol → (sector, industry)
    batch_size = 20

    for batch_start in range(0, total, batch_size):
        batch = symbols[batch_start : batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_yf_sector, s): s for s in batch}
            for fut in as_completed(futures):
                ticker_ns, sector, industry = fut.result()
                sym = ticker_ns.replace(".NS", "")
                results[sym] = (sector, industry)

        completed = min(batch_start + batch_size, total)
        logger.info("  … %d / %d tickers processed", completed, total)
        if batch_start + batch_size < total:
            time.sleep(batch_sleep)

    # Build output rows
    rows = []
    yf_count = 0
    fallback_count = 0
    for _, row in parsed.iterrows():
        sym = row["symbol"]
        sector, industry = results.get(sym, ("", ""))
        if sector:
            yf_count += 1
        else:
            # Fall back to the NSE Industry value for both columns
            sector = row["nse_industry"]
            industry = row["nse_industry"]
            fallback_count += 1
            logger.debug(
                "%s: yfinance sector empty — using NSE Industry '%s'", sym, sector
            )
        rows.append(
            {
                "ticker":       f"{sym}.NS",
                "company_name": row["company_name"],
                "sector":       sector,
                "industry":     industry,
            }
        )

    logger.info(
        "Enrichment complete: %d yfinance values, %d NSE-Industry fallbacks",
        yf_count,
        fallback_count,
    )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Download, parse, enrich, and write the Nifty 500 ticker CSV."""
    raw_df = _download_nse_csv()
    parsed = _parse_nse_df(raw_df)

    enriched = _enrich_with_yfinance(parsed)

    # Validate row count
    n_rows = len(enriched)
    logger.info("Total rows to write: %d", n_rows)
    if n_rows < 490:
        logger.error(
            "Only %d tickers after enrichment — expected >= 490. "
            "Possible causes: NSE CSV truncated, EQ filter too strict, or "
            "network issues reduced the download. Investigate before committing.",
            n_rows,
        )
        sys.exit(1)

    # Write CSV
    enriched.to_csv(_OUTPUT_CSV, index=False)
    logger.info("Written: %s  (%d rows)", _OUTPUT_CSV, n_rows)

    # Print sample
    print("\nSample output (first 5 rows):")
    print(enriched.head().to_string(index=False))
    print(f"\n✓  {n_rows} tickers written to {_OUTPUT_CSV}")


if __name__ == "__main__":
    main()
