"""CLI entry point: python -m equity_research <TICKER> [options]."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from equity_research.config import load_config
from equity_research.data.yfinance_provider import YFinanceProvider
from equity_research.utils.formatting import NA, fmt_inr, fmt_pct, fmt_x

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s: %(message)s",
)
logger = logging.getLogger("equity_research")


def _print_section(title: str) -> None:
    width = 70
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def _print_df(df: pd.DataFrame, label: str, scale_cr: bool = True) -> None:
    """Pretty-print a financial DataFrame, values in Crores if scale_cr."""
    if df.empty:
        print(f"  [{label}: no data available]")
        return
    display = df.copy()
    if scale_cr:
        display = display / 1e7  # INR → Crores
        display = display.round(0).astype(object)
    print(f"\n  {label} (INR Crores, rounded)" if scale_cr else f"\n  {label}")
    print(display.to_string())


def run_dry_run(ticker: str, provider: YFinanceProvider) -> None:
    """Fetch all data for the ticker and print normalized tables."""
    print(f"\n{'#' * 70}")
    print(f"  EQUITY RESEARCH — DRY RUN: {ticker.upper()}")
    print(f"{'#' * 70}")

    # ── Profile ──────────────────────────────────────────────────────────
    _print_section("COMPANY PROFILE")
    profile = provider.get_profile(ticker)
    rows = [
        ("Ticker",              profile.get("ticker", NA)),
        ("Name",                profile.get("long_name") or NA),
        ("Sector",              profile.get("sector") or NA),
        ("Industry",            profile.get("industry") or NA),
        ("Market Cap",          fmt_inr(profile.get("market_cap"))),
        ("Current Price",       f"₹{profile.get('current_price') or NA}"),
        ("52W High",            f"₹{profile.get('fifty_two_week_high') or NA}"),
        ("52W Low",             f"₹{profile.get('fifty_two_week_low') or NA}"),
        ("Beta",                fmt_x(profile.get("beta"), suffix="")),
        ("Shares Outstanding",  f"{(profile.get('shares_outstanding') or 0)/1e7:,.0f} Cr"),
        ("Trailing P/E",        fmt_x(profile.get("trailing_pe"))),
        ("Price/Book",          fmt_x(profile.get("price_to_book"))),
        ("EV",                  fmt_inr(profile.get("enterprise_value"))),
        ("Dividend Yield",      fmt_pct(profile.get("dividend_yield"))),
        ("ROE",                 fmt_pct(profile.get("return_on_equity"))),
        ("Debt/Equity",         fmt_x(
            (profile.get("debt_to_equity") or 0) / 100
            if profile.get("debt_to_equity") is not None else None
        )),
    ]
    col_w = max(len(k) for k, _ in rows) + 2
    for key, val in rows:
        print(f"  {key:<{col_w}} {val}")

    # ── Business summary ─────────────────────────────────────────────────
    summary = profile.get("long_business_summary")
    if summary:
        _print_section("BUSINESS OVERVIEW (first 500 chars)")
        print(f"  {summary[:500]}{'...' if len(summary) > 500 else ''}")

    # ── Financials ───────────────────────────────────────────────────────
    financials = provider.get_financials(ticker)

    _print_section("INCOME STATEMENT")
    _print_df(financials["income"], "Income Statement")

    _print_section("BALANCE SHEET")
    _print_df(financials["balance_sheet"], "Balance Sheet")

    _print_section("CASH FLOW")
    _print_df(financials["cash_flow"], "Cash Flow Statement")

    # ── Peers ─────────────────────────────────────────────────────────────
    _print_section("PEER COMPANIES")
    peers = provider.get_peers(ticker)
    if peers:
        print(f"  Found {len(peers)} peer(s):")
        for p in peers:
            print(f"    • {p}")
    else:
        print("  No peers found.")

    print(f"\n{'#' * 70}")
    print("  Dry run complete. Use --help for full usage.")
    print(f"{'#' * 70}\n")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the report generator."""
    parser = argparse.ArgumentParser(
        prog="equity_research",
        description="Generate an equity research report for a Nifty 500 company.",
    )
    parser.add_argument("ticker", help="NSE ticker symbol, e.g. RELIANCE or RELIANCE.NS")
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.yaml (default: repo root config.yaml)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="DIR",
        help="Output directory for the PDF (overrides config.report.output_dir)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print normalized data without generating a PDF",
    )
    args = parser.parse_args(argv)

    # Load config
    config_path = Path(args.config) if args.config else None
    try:
        cfg = load_config(config_path) if config_path else load_config()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Config error: %s", exc)
        return 1

    if args.output:
        cfg.report.output_dir = args.output

    provider = YFinanceProvider(cfg)

    if args.dry_run:
        run_dry_run(args.ticker, provider)
        return 0

    # Full report generation (implemented in M5)
    logger.info(
        "Full PDF report generation will be available after Milestone 5. "
        "Run with --dry-run to see normalized data."
    )
    run_dry_run(args.ticker, provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
