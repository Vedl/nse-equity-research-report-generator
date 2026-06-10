"""Build data/company_universe.json from the bundled Nifty 500 constituent list.

Each entry carries the valuation_family assigned by the rule-based sector
router — deterministic and auditable, mirroring equity_research/analysis/router.py.

Run:  python scripts/build_universe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

CSV = REPO / "equity_research" / "data" / "nifty500_tickers.csv"
OUT = REPO / "data" / "company_universe.json"

# Conglomerates with SOTP segment configs in config.yaml
SOTP_TICKERS = {"RELIANCE", "ITC", "LT"}

# Sector/industry → valuation family. First match wins; mirrors the router's
# priorities. Industry checks run before sector checks (more specific).
INDUSTRY_RULES: list[tuple[str, str]] = [
    ("insurance", "INSURANCE"),
    ("bank", "BANKS_NBFCS"),
    ("credit services", "BANKS_NBFCS"),
    ("asset management", "BANKS_NBFCS"),
    ("capital markets", "BANKS_NBFCS"),
    ("financial conglomerates", "BANKS_NBFCS"),
    ("mortgage", "BANKS_NBFCS"),
    ("real estate", "REAL_ESTATE"),
    ("steel", "METALS_MINING"),
    ("aluminum", "METALS_MINING"),
    ("copper", "METALS_MINING"),
    ("metals", "METALS_MINING"),
    ("mining", "METALS_MINING"),
    ("coking coal", "METALS_MINING"),
    ("thermal coal", "METALS_MINING"),
    ("oil & gas", "OIL_GAS"),
    ("oil and gas", "OIL_GAS"),
    ("refining", "OIL_GAS"),
    ("drug manufacturers", "PHARMA"),
    ("biotechnology", "PHARMA"),
    ("medical", "PHARMA"),
    ("diagnostics", "PHARMA"),
    ("information technology", "IT_TECH"),
    ("software", "IT_TECH"),
    ("semiconductor", "IT_TECH"),
    ("utilities", "UTILITIES_PSU"),
    ("conglomerates", "CONGLOMERATES"),
]
SECTOR_RULES: dict[str, str] = {
    "Financial Services": "BANKS_NBFCS",
    "Technology": "IT_TECH",
    "Healthcare": "PHARMA",
    "Consumer Defensive": "CONSUMER_FMCG",
    "Energy": "OIL_GAS",
    "Utilities": "UTILITIES_PSU",
    "Basic Materials": "METALS_MINING",
    "Real Estate": "REAL_ESTATE",
}

# Valuation family → primary model run by the engine
FAMILY_MODEL = {
    "BANKS_NBFCS": "justified_pb_ddm",
    "INSURANCE": "justified_pb_ddm",
    "UTILITIES_PSU": "fcff_dcf",
    "REAL_ESTATE": "ev_ebitda_comps",
    "METALS_MINING": "ev_ebitda_comps",
    "CONGLOMERATES": "sotp",
    "PHARMA": "fcff_dcf",
    "IT_TECH": "fcff_dcf",
    "CONSUMER_FMCG": "fcff_dcf",
    "OIL_GAS": "ev_ebitda_comps",
    "DEFAULT": "fcff_dcf",
}


def classify(ticker_base: str, sector: str, industry: str) -> str:
    """Assign a valuation family — rule-based, no ML, fully auditable."""
    if ticker_base in SOTP_TICKERS:
        return "CONGLOMERATES"
    ind = (industry or "").lower()
    for needle, family in INDUSTRY_RULES:
        if needle in ind:
            return family
    if sector in SECTOR_RULES:
        return SECTOR_RULES[sector]
    return "DEFAULT"


def main() -> None:
    df = pd.read_csv(CSV, dtype=str).fillna("")
    universe: dict[str, dict] = {}
    family_counts: dict[str, int] = {}

    for _, row in df.iterrows():
        yf_ticker = row["ticker"].strip()
        base = yf_ticker.replace(".NS", "").upper()
        family = classify(base, row["sector"].strip(), row["industry"].strip())
        family_counts[family] = family_counts.get(family, 0) + 1
        universe[base] = {
            "name": row["company_name"].strip(),
            "sector": row["sector"].strip() or None,
            "industry": row["industry"].strip() or None,
            "market_cap_band": None,        # populated lazily from live data
            "valuation_family": family,
            "primary_model": FAMILY_MODEL[family],
            "yfinance_ticker": yf_ticker,
            "nse_symbol": base,
            "bse_code": None,               # not in the bundled list — never guessed
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(universe, indent=1))
    print(f"Wrote {len(universe)} companies → {OUT}")
    for fam, n in sorted(family_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {fam:<15} {n}")


if __name__ == "__main__":
    main()
