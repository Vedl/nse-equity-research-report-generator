"""Abstract DataProvider interface.

All data access in this application goes through this interface so that the
underlying source (yfinance, ICICI Breeze, paid feed, …) can be swapped
without touching any analysis or report-assembly code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataProvider(ABC):
    """Source-agnostic interface for fetching equity data."""

    @abstractmethod
    def get_profile(self, ticker: str) -> dict:
        """Return company profile and snapshot fields.

        Expected keys (any may be None if unavailable):
            long_name, sector, industry, market_cap, current_price,
            fifty_two_week_high, fifty_two_week_low, beta,
            shares_outstanding, trailing_pe, forward_pe, price_to_book,
            enterprise_value, dividend_yield, long_business_summary,
            total_debt, return_on_equity, return_on_assets.
        """

    @abstractmethod
    def get_financials(self, ticker: str) -> dict[str, pd.DataFrame]:
        """Return normalized annual financial statements.

        Returns a dict with three keys:
            'income'        — income statement
            'balance_sheet' — balance sheet
            'cash_flow'     — cash flow statement

        Each DataFrame:
            index   : year (int), ascending, up to 5 years of history
            columns : normalized snake_case field names (see yfinance_provider
                      for the full field list); missing fields are NaN columns,
                      never omitted.
        """

    @abstractmethod
    def get_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        """Return OHLCV price history.

        Args:
            ticker: NSE ticker (with or without .NS suffix).
            period: yfinance-style period string, e.g. '1y', '2y', '5y'.

        Returns:
            DataFrame with DatetimeIndex and columns:
                Open, High, Low, Close, Volume (capitalised, yfinance convention).
        """

    @abstractmethod
    def get_peers(self, ticker: str) -> list[str]:
        """Return NSE tickers (with .NS suffix) of comparable peers.

        Returns an empty list (never raises) if peers cannot be determined.
        Up to config.peers.max_peers tickers are returned.
        """
