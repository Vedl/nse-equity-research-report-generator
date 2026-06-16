"""YFinanceProvider — DataProvider implementation backed by yfinance."""

from __future__ import annotations

import logging
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import pandas as pd
import yfinance as yf

from equity_research.config import AppConfig
from equity_research.data import cache as file_cache
from equity_research.data.provider import DataProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transient-failure retry/backoff (yfinance rate-limits aggressively on a
# public Railway IP).  Tunable via env so a bulk universe sweep can be more
# patient than the latency-sensitive request path.
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = int(os.getenv("YF_RETRY_ATTEMPTS", "3"))
_RETRY_BASE_DELAY = float(os.getenv("YF_RETRY_BASE_DELAY", "1.0"))

# Substrings that mark a retryable (transient) failure rather than a permanent
# "this ticker has no data" outcome.
_TRANSIENT_MARKERS = (
    "rate", "429", "too many", "timeout", "timed out",
    "connection", "temporarily", "unavailable", "503", "502",
)

_R = TypeVar("_R")


def _is_transient(exc: Exception) -> bool:
    return any(m in str(exc).lower() for m in _TRANSIENT_MARKERS)


def _with_retries(
    fn: Callable[[], _R],
    *,
    what: str,
    is_valid: Callable[[_R], bool] | None = None,
    attempts: int = _RETRY_ATTEMPTS,
    base_delay: float = _RETRY_BASE_DELAY,
) -> _R:
    """Call *fn* with exponential backoff + jitter on transient failures.

    Retries when *fn* raises, or when ``is_valid(result)`` is falsy — yfinance
    signals a rate-limit by returning an empty/sparse payload rather than
    raising, so an ``is_valid`` predicate lets callers treat that as retryable.
    Re-raises the last exception only if every attempt raised; otherwise returns
    the final (possibly still-invalid) result so callers can degrade gracefully.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = fn()
            if is_valid is None or is_valid(result):
                return result
            last_exc = None
            if attempt == attempts:
                return result  # hand back whatever we got; caller degrades
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == attempts:
                raise
            if not _is_transient(exc):
                # A permanent error won't be cured by waiting — fail fast.
                raise
        delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
        logger.warning(
            "%s: attempt %d/%d failed (%s) — backing off %.1fs",
            what, attempt, attempts, last_exc or "empty/sparse response", delay,
        )
        time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    return fn()  # pragma: no cover — unreachable, satisfies type checker

# ---------------------------------------------------------------------------
# Currency conversion helper
# ---------------------------------------------------------------------------

_USDINR_PLAUSIBLE = (75.0, 100.0)  # reject stale / incorrect yfinance quotes


def _fetch_usdinr(fallback: float = 95.0) -> float:
    """Return the live USDINR rate, with plausible-range filtering.

    Tries fast_info, then info dict, then 1-day history, then the inverse
    pair (INR=X).  Returns *fallback* only if all four fail.
    """
    def _ok(r: float | None) -> float | None:
        if r is None or not math.isfinite(r):
            return None
        return r if _USDINR_PLAUSIBLE[0] <= r <= _USDINR_PLAUSIBLE[1] else None

    # 1. fast_info
    try:
        r = _ok(yf.Ticker("USDINR=X").fast_info.get("last_price"))
        if r:
            return r
    except Exception:  # noqa: BLE001
        pass
    # 2. info dict
    try:
        r = _ok(yf.Ticker("USDINR=X").info.get("regularMarketPrice"))
        if r:
            return r
    except Exception:  # noqa: BLE001
        pass
    # 3. 1-day history
    try:
        hist = yf.Ticker("USDINR=X").history(period="5d")
        if not hist.empty:
            r = _ok(float(hist["Close"].dropna().iloc[-1]))
            if r:
                return r
    except Exception:  # noqa: BLE001
        pass
    # 4. Inverse pair: INR=X (quotes INR per 1 USD, but sometimes 1/USD)
    try:
        inv = yf.Ticker("INR=X").fast_info.get("last_price")
        if inv and math.isfinite(inv) and inv > 0:
            # INR=X usually quotes the same as USDINR=X
            r = _ok(inv)
            if r:
                return r
            # Try inverse in case it's USD per INR
            r = _ok(1.0 / inv)
            if r:
                return r
    except Exception:  # noqa: BLE001
        pass

    logger.warning(
        "All USDINR fetches failed or returned implausible values — using fallback %.2f",
        fallback,
    )
    return fallback

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
    # Extended fields for quality screens (Piotroski / Beneish / DuPont / CCC)
    "cost_of_revenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "selling_general_admin": ["Selling General And Administration"],
    "pretax_income": ["Pretax Income"],
    "basic_average_shares": ["Basic Average Shares", "Diluted Average Shares"],
    "diluted_eps": ["Diluted EPS", "Basic EPS"],
}

_BALANCE_MAP: dict[str, list[str]] = {
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "cash_and_equivalents": [
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Short Term Investments",
    ],
    # Broad treasury line (cash + ST investments) and the standalone ST-investment
    # line. Consumed by the Sloan/RSST NOA computation, which must strip *all*
    # financial assets — not just narrow cash — from operating assets. Kept
    # separate from ``cash_and_equivalents`` (which stays narrow for FCFF/net-debt).
    "cash_and_short_term_investments": [
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Short Term Investments",
    ],
    "short_term_investments": [
        "Other Short Term Investments",
        "Short Term Investments",
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
    # Tangible common equity inputs (bank ROTE / P-TBV — acquisition goodwill
    # earns no return).  ``tangible_book_value`` is Yahoo's directly-reported
    # figure; ``goodwill_and_intangibles`` lets us derive it when that row is
    # absent (tangible = stockholders_equity − goodwill − intangibles).
    "tangible_book_value": ["Tangible Book Value", "Net Tangible Assets"],
    "goodwill_and_intangibles": [
        "Goodwill And Other Intangible Assets",
        "Goodwill",
    ],
    # Extended fields for quality screens (Piotroski / Beneish / Altman / CCC)
    "accounts_payable": ["Accounts Payable", "Payables"],
    "long_term_debt": ["Long Term Debt And Capital Lease Obligation", "Long Term Debt"],
    "gross_ppe": ["Gross PPE"],
    "retained_earnings": ["Retained Earnings"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
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
    "investing_cash_flow": ["Investing Cash Flow"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "share_repurchase": ["Repurchase Of Capital Stock"],
    "change_in_working_capital": [
        "Change In Working Capital",
        # NOTE: "Changes In Cash" is intentionally excluded here.
        # It maps to the net change in the firm's cash balance (including dividends
        # and buybacks), not the change in operating working capital.  Using it
        # was causing catastrophic FCFF understatement for cash-generative companies
        # like Infosys where large buyback/dividend outflows were subtracted from FCFF.
        # If "Change In Working Capital" is absent, the code fills NaN with 0 (logged).
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
    ("forward_eps", "forwardEps"),
    ("target_mean_price", "targetMeanPrice"),
    ("target_median_price", "targetMedianPrice"),
    ("target_low_price", "targetLowPrice"),
    ("target_high_price", "targetHighPrice"),
    ("recommendation_key", "recommendationKey"),
    ("number_of_analyst_opinions", "numberOfAnalystOpinions"),
    ("held_percent_insiders", "heldPercentInsiders"),
    ("held_percent_institutions", "heldPercentInstitutions"),
]


# NSE tickers that yfinance lists under a different (usually pre-rename) symbol.
# Without this remap, recently-renamed-but-long-listed names resolve to no data
# even though full history exists under the legacy symbol.  Verified against live
# Yahoo Finance; in a restricted/sandboxed environment the alias may itself be
# uncovered, in which case the name simply stays unresolved (no worse than before).
_SYMBOL_OVERRIDES: dict[str, str] = {
    "UNITDSPR.NS": "MCDOWELL-N.NS",  # United Spirits — Yahoo keeps the legacy McDowell symbol
}


def _normalize_ticker(ticker: str) -> str:
    """Ensure ticker has the .NS suffix for NSE stocks, applying symbol overrides.

    Index symbols (^NSEI, ^CRSLDX, …) and FX pairs (USDINR=X) pass through
    unchanged — only equity tickers get the .NS suffix.  Known NSE→Yahoo symbol
    renames are remapped via ``_SYMBOL_OVERRIDES``.
    """
    upper = ticker.upper().strip()
    if upper.startswith("^") or upper.endswith("=X"):
        return upper
    norm = upper if upper.endswith(".NS") else f"{upper}.NS"
    return _SYMBOL_OVERRIDES.get(norm, norm)


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


def _normalize_dividend_yield(
    dy: float | None,
    trailing_yield: float | None,
    dps: float | None,
    price: float | None,
) -> float | None:
    """Return dividend yield as a fraction (e.g. 0.0082 for 0.82%).

    yfinance's ``dividendYield`` is percentage-points in current versions but was
    a fraction in older ones, and the magnitude alone is ambiguous for sub-1%
    payers (0.82 could be 0.82% or 82%).  Resolution order:

      1. ``trailingAnnualDividendYield`` — reliably already a fraction;
      2. disambiguate ``dividendYield`` against the unambiguous DPS / price;
      3. fall back to assuming percentage-points (current yfinance behaviour).
    """
    if isinstance(trailing_yield, (int, float)) and 0.0 < float(trailing_yield) < 0.5:
        return float(trailing_yield)
    if not isinstance(dy, (int, float)) or dy <= 0:
        return float(dy) if isinstance(dy, (int, float)) else None
    dy = float(dy)
    if (isinstance(dps, (int, float)) and dps > 0
            and isinstance(price, (int, float)) and price > 0):
        true_y = dps / price
        return dy if abs(dy - true_y) <= abs(dy / 100.0 - true_y) else dy / 100.0
    # No ground truth: current yfinance returns percentage points. Only rescale
    # values too large to be a plausible fraction, leaving an already-fractional
    # legacy value (≤ 0.2) untouched.
    return dy / 100.0 if dy > 0.2 else dy


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
        """Fetch and normalize company profile fields from yfinance info.

        Results are cached on disk for 24 h (see data/cache.py) so Railway
        restarts and repeat requests don't re-hit Yahoo.
        """
        norm_ticker = _normalize_ticker(ticker)

        cached = file_cache.get(f"{norm_ticker}_profile", "profile")
        if cached is not None:
            return cached

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
        # Expose the currency the financial statements are denominated in.
        # yfinance reports this as 'financialCurrency' (e.g. "USD" for INFY.NS,
        # "INR" for RELIANCE.NS).  Downstream code uses this to convert to INR.
        profile["financial_currency"] = raw_info.get("financialCurrency", "INR")

        # Normalize dividend yield to a fraction (0.0082 for 0.82%).  yfinance's
        # `dividendYield` is percentage-points in current versions but the old
        # `> 1.0` heuristic missed sub-1% payers (0.82 was read as 82%, exploding
        # the bank DDM blend).  See _normalize_dividend_yield.
        profile["dividend_yield"] = _normalize_dividend_yield(
            profile.get("dividend_yield"),
            raw_info.get("trailingAnnualDividendYield"),
            raw_info.get("dividendRate") or raw_info.get("trailingAnnualDividendRate"),
            profile.get("current_price"),
        )

        # --- Shares outstanding fallback chain ---
        shares = profile.get("shares_outstanding")
        if not shares or shares <= 0:
            # Method 2: market_cap / price
            mktcap = profile.get("market_cap")
            price = profile.get("current_price")
            if mktcap and price and price > 0:
                profile["shares_outstanding"] = mktcap / price
                logger.info(
                    "Shares fallback for %s: market_cap / price = %.0f",
                    norm_ticker, profile["shares_outstanding"],
                )
            else:
                # Method 3: float shares from raw info
                float_shares = raw_info.get("floatShares")
                if float_shares and float_shares > 0:
                    profile["shares_outstanding"] = float(float_shares)
                    logger.info(
                        "Shares fallback for %s: float_shares = %.0f",
                        norm_ticker, profile["shares_outstanding"],
                    )

        # --- Beta fallback ---
        beta = profile.get("beta")
        if beta is None or (isinstance(beta, float) and math.isnan(beta)):
            profile["beta"] = 1.0
            logger.info("Beta fallback for %s: defaulting to 1.0", norm_ticker)

        if profile.get("long_name"):   # only cache successful fetches
            file_cache.put(f"{norm_ticker}_profile", profile)
        return profile

    def get_financials(self, ticker: str) -> dict[str, pd.DataFrame]:
        """Fetch and normalize annual income, balance sheet, and cash flow statements.

        If the company reports financials in a foreign currency (e.g. USD for
        INFY.NS), all monetary values are converted to INR using the live
        USDINR rate so that the DCF engine always works in a single currency.
        """
        norm_ticker = _normalize_ticker(ticker)

        cached = file_cache.get(f"{norm_ticker}_financials", "financials")
        if cached is not None:
            try:
                return {
                    name: file_cache.payload_to_df(cached[name])
                    for name in ("income", "balance_sheet", "cash_flow")
                }
            except (KeyError, ValueError) as exc:
                logger.warning("Financials cache decode failed for %s: %s", norm_ticker, exc)

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

        # ── Currency normalization ────────────────────────────────────────
        fin_currency = self._get_financial_currency(norm_ticker)
        if fin_currency and fin_currency.upper() != "INR":
            rate = _fetch_usdinr(self._config.market.fallback_usd_inr)
            logger.info(
                "%s reports financials in %s — converting to INR at %.2f",
                norm_ticker, fin_currency, rate,
            )
            for df in (income, balance, cashflow):
                if not df.empty:
                    # Multiply all numeric columns by the FX rate
                    numeric_cols = df.select_dtypes(include="number").columns
                    df[numeric_cols] = df[numeric_cols] * rate

        result = {
            "income": income,
            "balance_sheet": balance,
            "cash_flow": cashflow,
        }
        if not income.empty or not balance.empty:   # only cache non-empty fetches
            file_cache.put(
                f"{norm_ticker}_financials",
                {name: file_cache.df_to_payload(df) for name, df in result.items()},
            )
        return result

    def get_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        """Fetch OHLCV price history from yfinance (disk-cached for 24 h)."""
        norm_ticker = _normalize_ticker(ticker)

        cache_key = f"{norm_ticker}_prices_{period}"
        cached = file_cache.get(cache_key, "prices")
        if cached is not None:
            try:
                return file_cache.payload_to_df(cached)
            except ValueError as exc:
                logger.warning("Prices cache decode failed for %s: %s", norm_ticker, exc)

        try:
            df = _with_retries(
                lambda: yf.Ticker(norm_ticker).history(period=period, auto_adjust=True),
                what=f"prices[{norm_ticker},{period}]",
                is_valid=lambda d: d is not None and not d.empty,
            )
            if df.empty:
                logger.warning("No price data returned for %s (period=%s)", norm_ticker, period)
            else:
                file_cache.put(cache_key, file_cache.df_to_payload(df))
            return df
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch prices for %s after retries: %s", norm_ticker, exc)
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
        # A sparse (<5 key) dict is yfinance's tell for a rate-limit, so treat it
        # as retryable; a genuinely-uncovered ticker also returns sparse and will
        # simply exhaust the (small) retry budget before degrading to {}.
        def _ok(info: dict) -> bool:
            return bool(info) and len(info) >= 5

        try:
            info = _with_retries(
                lambda: yf.Ticker(ticker).info, what=f"info[{ticker}]", is_valid=_ok
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch info for %s after retries: %s", ticker, exc)
            return {}
        if not _ok(info):
            logger.warning("Sparse or empty info dict for %s (rate-limited or no coverage)", ticker)
            return {}
        return info

    def _get_financial_currency(self, ticker: str) -> str:
        """Return the currency that this ticker's financial statements use.

        Falls back to 'INR' if the info dict is unavailable.
        """
        try:
            info = yf.Ticker(ticker).info
            return info.get("financialCurrency", "INR") or "INR"
        except Exception:  # noqa: BLE001
            return "INR"

    @staticmethod
    def _safe_fetch(
        t: yf.Ticker, attr: str, ticker_label: str
    ) -> pd.DataFrame | None:
        """Fetch a yfinance DataFrame attribute, returning None on failure.

        An empty statement DataFrame is yfinance's rate-limit / no-coverage
        signal, so it is treated as retryable before we degrade to None.
        """
        def _ok(df: pd.DataFrame | None) -> bool:
            return df is not None and not df.empty

        try:
            df = _with_retries(
                lambda: getattr(t, attr),
                what=f"{attr}[{ticker_label}]",
                is_valid=_ok,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch %s for %s after retries: %s", attr, ticker_label, exc)
            return None
        return df if _ok(df) else None

    def _load_nifty500(self) -> pd.DataFrame:
        """Load and cache the bundled Nifty 500 CSV."""
        if self._nifty500 is None:
            self._nifty500 = pd.read_csv(_NIFTY500_CSV, dtype=str).fillna("")
        return self._nifty500
