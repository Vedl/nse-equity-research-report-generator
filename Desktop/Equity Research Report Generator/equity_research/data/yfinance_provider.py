"""YFinanceProvider — DataProvider implementation backed by yfinance."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from equity_research.config import AppConfig
from equity_research.data.provider import DataProvider

logger = logging.getLogger(__name__)

_NIFTY500_CSV = Path(__file__).parent / "nifty500_tickers.csv"

# ---------------------------------------------------------------------------
# Field name mappings: normalized_name -> [possible yfinance index labels]
# ---------------------------------------------------------------------------

_INCOME_MAP: dict[str, list[str]] = {
    "total_revenue": ["Total Revenue", "Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "EBIT"],
    "ebitda": ["EBITDA", "Normalized EBITDA", "Reconciled EBITDA"],
    "net_income": [
        "Net Income",
        "Net Income From Continuing And Discontinued Operation",
        "Net Income From Continuing Operation Net Minority Interest",
        "Net Income Common Stockholders",
    ],
    "basic_eps": ["Basic EPS", "Diluted EPS"],
    "interest_expense": [
        "Interest Expense",
        "Interest Expense Non Operating",
        "Total Other Finance Cost",
    ],
    "tax_provision": ["Tax Provision", "Income Tax Expense"],
    "depreciation_amortization": [
        "Reconciled Depreciation",
        "Depreciation And Amortization",
        "Depreciation Amortization Depletion",
    ],
}

_BALANCE_MAP: dict[str, list[str]] = {
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "cash_and_equivalents": [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Short Term Investments",
    ],
    "inventory": ["Inventory"],
    "accounts_receivable": ["Accounts Receivable", "Net Receivables"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "total_debt": [
        "Total Debt",
        "Long Term Debt And Capital Lease Obligation",
        "Long Term Debt",
    ],
    "stockholders_equity": [
        "Stockholders Equity",
        "Total Stockholders Equity",
        "Total Equity Gross Minority Interest",
        "Common Stock Equity",
    ],
    "net_ppe": ["Net PPE", "Net Property Plant And Equipment"],
}

_CASHFLOW_MAP: dict[str, list[str]] = {
    "operating_cash_flow": ["Operating Cash Flow", "Cash Flow From Operations"],
    "capital_expenditure": [
        "Capital Expenditure",
        "Capital Expenditures",
        "Purchase Of PPE",
    ],
    "free_cash_flow": ["Free Cash Flow"],
    "depreciation_amortization": [
        "Depreciation And Amortization",
        "Depreciation Amortization Depletion",
        "Reconciled Depreciation",
    ],
    "change_in_working_capital": [
        "Change In Working Capital",
        "Changes In Cash",
    ],
}

# Profile keys: (normalized_name, raw_yfinance_info_key)
_PROFILE_KEYS: list[tuple[str, str]] = [
    ("long_name", "longName"),
    ("sector", "sector"),
    ("industry", "industry"),
    ("market_cap", "marketCap"),
    ("current_price", "currentPrice"),
    ("fifty_two_week_high", "fiftyTwoWeekHigh"),
    ("fifty_two_week_low", "fiftyTwoWeekLow"),
    ("beta", "beta"),
    ("shares_outstanding", "sharesOutstanding"),
    ("trailing_pe", "trailingPE"),
    ("forward_pe", "forwardPE"),
    ("price_to_book", "priceToBook"),
    ("enterprise_value", "enterpriseValue"),
    ("dividend_yield", "dividendYield"),
    ("long_business_summary", "longBusinessSummary"),
    ("total_debt", "totalDebt"),
    ("return_on_equity", "returnOnEquity"),
    ("return_on_assets", "returnOnAssets"),
    ("debt_to_equity", "debtToEquity"),
    ("trailing_eps", "trailingEps"),
    ("enterprise_to_ebitda", "enterpriseToEbitda"),
    ("enterprise_to_revenue", "enterpriseToRevenue"),
]


def _normalize_ticker(ticker: str) -> str:
    """Ensure ticker has the .NS suffix for NSE stocks."""
    upper = ticker.upper().strip()
    if not upper.endswith(".NS"):
        return f"{upper}.NS"
    return upper


def _is_nan(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return False


def _normalize_financial_df(
    raw_df: pd.DataFrame | None,
    field_map: dict[str, list[str]],
    statement_name: str,
) -> pd.DataFrame:
    """Map yfinance's raw financial DataFrame to a normalized form.

    Args:
        raw_df: yfinance DataFrame (index=items, columns=dates).
        field_map: mapping from normalized name to list of candidate yfinance names.
        statement_name: human label for logging.

    Returns:
        DataFrame with integer year index (ascending) and normalized columns.
        Completely missing fields become NaN columns.
    """
    if raw_df is None or raw_df.empty:
        logger.warning("%s: empty or None — returning empty DataFrame", statement_name)
        return pd.DataFrame(columns=list(field_map.keys()))

    # yfinance: index=line items, columns=report dates → transpose
    df = raw_df.T.copy()

    normalized: dict[str, pd.Series] = {}
    for norm_name, candidates in field_map.items():
        matched = False
        for candidate in candidates:
            if candidate in df.columns:
                normalized[norm_name] = pd.to_numeric(df[candidate], errors="coerce")
                matched = True
                break
        if not matched:
            logger.warning(
                "%s: field '%s' not found (tried: %s)",
                statement_name,
                norm_name,
                ", ".join(candidates),
            )
            normalized[norm_name] = pd.Series(
                [float("nan")] * len(df), index=df.index, dtype=float
            )

    result = pd.DataFrame(normalized, index=df.index)

    # Convert DatetimeIndex column headers to integer years
    try:
        result.index = pd.Index(result.index.year, name="year")
    except AttributeError:
        # Fallback: index may already be plain integers in some yfinance versions
        result.index.name = "year"

    result = result.sort_index()
    # Keep last 5 years of data
    result = result.tail(5)
    return result


class YFinanceProvider(DataProvider):
    """DataProvider backed by yfinance for NSE (Nifty 500) equities."""

    def __init__(self, config: AppConfig) -> None:
        """Initialise the provider with application config."""
        self._config = config
        self._nifty500: pd.DataFrame | None = None  # lazy-loaded

    # ------------------------------------------------------------------
    # DataProvider interface
    # ------------------------------------------------------------------

    def get_profile(self, ticker: str) -> dict:
        """Fetch and normalize company profile fields from yfinance info."""
        norm_ticker = _normalize_ticker(ticker)
        raw_info = self._fetch_info(norm_ticker)

        profile: dict = {}
        for norm_name, raw_key in _PROFILE_KEYS:
            raw_val = raw_info.get(raw_key)
            if _is_nan(raw_val) or raw_val is None:
                logger.warning("Profile field '%s' missing for %s", norm_name, norm_ticker)
                profile[norm_name] = None
            else:
                profile[norm_name] = raw_val

        profile["ticker"] = norm_ticker
        return profile

    def get_financials(self, ticker: str) -> dict[str, pd.DataFrame]:
        """Fetch and normalize annual income, balance sheet, and cash flow statements."""
        norm_ticker = _normalize_ticker(ticker)
        t = yf.Ticker(norm_ticker)

        income = _normalize_financial_df(
            self._safe_fetch(t, "financials", norm_ticker),
            _INCOME_MAP,
            f"{norm_ticker}/income",
        )
        balance = _normalize_financial_df(
            self._safe_fetch(t, "balance_sheet", norm_ticker),
            _BALANCE_MAP,
            f"{norm_ticker}/balance_sheet",
        )
        cashflow = _normalize_financial_df(
            self._safe_fetch(t, "cashflow", norm_ticker),
            _CASHFLOW_MAP,
            f"{norm_ticker}/cashflow",
        )

        return {
            "income": income,
            "balance_sheet": balance,
            "cash_flow": cashflow,
        }

    def get_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        """Fetch OHLCV price history from yfinance."""
        norm_ticker = _normalize_ticker(ticker)
        try:
            df = yf.Ticker(norm_ticker).history(period=period, auto_adjust=True)
            if df.empty:
                logger.warning("No price data returned for %s (period=%s)", norm_ticker, period)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch prices for %s: %s", norm_ticker, exc)
            return pd.DataFrame()

    def get_peers(self, ticker: str) -> list[str]:
        """Find sector peers from the bundled Nifty 500 ticker list."""
        norm_ticker = _normalize_ticker(ticker)

        # Check config overrides first
        base = norm_ticker.replace(".NS", "")
        overrides = self._config.peers.overrides
        if base in overrides:
            peers = [_normalize_ticker(p) for p in overrides[base]]
            logger.info("Using config overrides for %s: %s", norm_ticker, peers)
            return peers[: self._config.peers.max_peers]

        profile = self.get_profile(norm_ticker)
        sector = profile.get("sector")
        industry = profile.get("industry")

        if not sector:
            logger.warning(
                "Cannot find peers for %s: sector unknown", norm_ticker
            )
            return []

        nifty500 = self._load_nifty500()

        # Filter by industry first; fall back to sector-only if not enough
        industry_matches = nifty500[
            (nifty500["sector"] == sector) & (nifty500["industry"] == industry)
        ]
        sector_matches = nifty500[nifty500["sector"] == sector]

        candidates = (
            industry_matches
            if len(industry_matches) >= self._config.peers.max_peers
            else sector_matches
        )

        # Exclude the target ticker itself
        candidates = candidates[
            candidates["ticker"].str.upper() != norm_ticker.upper()
        ]

        peers = candidates["ticker"].tolist()[: self._config.peers.max_peers]

        if not peers:
            logger.warning(
                "No peers found for %s (sector='%s', industry='%s')",
                norm_ticker,
                sector,
                industry,
            )
        else:
            logger.info("Peers for %s: %s", norm_ticker, peers)

        return peers

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_info(self, ticker: str) -> dict:
        try:
            info = yf.Ticker(ticker).info
            if not info or len(info) < 5:
                logger.warning("Sparse or empty info dict for %s", ticker)
                return {}
            return info
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch info for %s: %s", ticker, exc)
            return {}

    @staticmethod
    def _safe_fetch(
        t: yf.Ticker, attr: str, ticker_label: str
    ) -> pd.DataFrame | None:
        """Fetch a yfinance DataFrame attribute, returning None on failure."""
        try:
            df = getattr(t, attr)
            return df if df is not None and not df.empty else None
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to fetch %s for %s: %s", attr, ticker_label, exc
            )
            return None

    def _load_nifty500(self) -> pd.DataFrame:
        """Load and cache the bundled Nifty 500 CSV."""
        if self._nifty500 is None:
            self._nifty500 = pd.read_csv(_NIFTY500_CSV, dtype=str).fillna("")
        return self._nifty500
