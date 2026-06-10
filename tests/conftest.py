"""Shared pytest fixtures — synthetic financial DataFrames and profiles.

All numeric values are chosen to produce round, easily-verified ratio outputs
so that test assertions can be written against known-answer computations.
"""

from __future__ import annotations

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Synthetic financials (5 years, 10% YoY revenue growth)
# ---------------------------------------------------------------------------
_YEARS = [2020, 2021, 2022, 2023, 2024]

# Revenue grows 10% per year from 1,000 Cr base (stored in full INR: × 1e7)
_REV = [1_000e7, 1_100e7, 1_210e7, 1_331e7, 1_464.1e7]


@pytest.fixture
def synthetic_income() -> pd.DataFrame:
    """Annual income statement with consistent 10% growth."""
    return pd.DataFrame(
        {
            "total_revenue": _REV,
            "gross_profit":            [r * 0.30 for r in _REV],   # 30% gross margin
            "operating_income":        [r * 0.15 for r in _REV],   # 15% operating margin
            "ebitda":                  [r * 0.20 for r in _REV],   # 20% EBITDA margin
            "net_income":              [r * 0.10 for r in _REV],   # 10% net margin
            "basic_eps":               [10.0 * (1.1 ** i) for i in range(5)],
            "interest_expense":        [r * 0.02 for r in _REV],   # interest = 2% of revenue
            "tax_provision":           [r * 0.033 for r in _REV],  # ~25% effective rate
            "depreciation_amortization": [r * 0.05 for r in _REV],
        },
        index=pd.Index(_YEARS, name="year"),
    )


@pytest.fixture
def synthetic_balance() -> pd.DataFrame:
    """Annual balance sheet sized consistently with income fixture."""
    equity = [800e7, 880e7, 968e7, 1_064.8e7, 1_171.28e7]
    debt = [400e7, 440e7, 484e7, 532.4e7, 585.64e7]
    return pd.DataFrame(
        {
            "total_assets":        [2_000e7, 2_200e7, 2_420e7, 2_662e7, 2_928.2e7],
            "current_assets":      [500e7,   550e7,   605e7,   665.5e7, 732.05e7],
            "cash_and_equivalents": [100e7,  110e7,   121e7,   133.1e7, 146.41e7],
            "inventory":           [150e7,   165e7,   181.5e7, 199.65e7, 219.615e7],
            "accounts_receivable": [200e7,   220e7,   242e7,   266.2e7, 292.82e7],
            "current_liabilities": [300e7,   330e7,   363e7,   399.3e7, 439.23e7],
            "total_debt":          debt,
            "stockholders_equity": equity,
            "net_ppe":             [700e7,   770e7,   847e7,   931.7e7, 1_024.87e7],
        },
        index=pd.Index(_YEARS, name="year"),
    )


@pytest.fixture
def synthetic_cashflow() -> pd.DataFrame:
    """Annual cash flow statement consistent with income and balance fixtures."""
    return pd.DataFrame(
        {
            "operating_cash_flow":      [130e7,  143e7,   157.3e7, 173.03e7, 190.333e7],
            "capital_expenditure":      [-60e7,  -66e7,   -72.6e7, -79.86e7, -87.846e7],
            "free_cash_flow":           [70e7,   77e7,    84.7e7,  93.17e7,  102.487e7],
            "depreciation_amortization": [50e7,  55e7,    60.5e7,  66.55e7,  73.205e7],
            "change_in_working_capital": [-20e7, -22e7,  -24.2e7, -26.62e7, -29.282e7],
        },
        index=pd.Index(_YEARS, name="year"),
    )


@pytest.fixture
def synthetic_profile() -> dict:
    """Company profile dict mirroring YFinanceProvider.get_profile() output."""
    return {
        "ticker": "TESTCORP.NS",
        "long_name": "Test Corporation Limited",
        "sector": "Technology",
        "industry": "Information Technology Services",
        "market_cap": 1_000e9,          # 1,000 Bn INR
        "current_price": 1_000.0,
        "fifty_two_week_high": 1_200.0,
        "fifty_two_week_low": 800.0,
        "beta": 1.2,
        "shares_outstanding": 1_000_000_000,
        "trailing_pe": 25.0,
        "forward_pe": 22.0,
        "price_to_book": 3.0,
        "enterprise_value": 1_040e9,
        "dividend_yield": 0.02,
        "long_business_summary": "Test Corporation is a leading IT services company.",
        "total_debt": 400e9,
        "return_on_equity": 0.125,
        "return_on_assets": 0.05,
        "debt_to_equity": 40.0,          # yfinance returns D/E in % (i.e. 40 means 40%)
    }


# ---------------------------------------------------------------------------
# Negative-FCFF fixtures (simulates capex-heavy companies like RELIANCE)
# ---------------------------------------------------------------------------

@pytest.fixture
def negative_fcff_cashflow() -> pd.DataFrame:
    """Cash flow statement where 3 of 5 years have negative FCFF.

    CapEx is very high (capex-heavy buildout), resulting in negative FCFF
    for 2020–2022 and slightly positive for 2023–2024.
    """
    return pd.DataFrame(
        {
            "operating_cash_flow":      [130e7,  143e7,   157.3e7, 173.03e7, 190.333e7],
            "capital_expenditure":      [-200e7, -220e7,  -242e7,  -79.86e7, -87.846e7],
            "free_cash_flow":           [-70e7,  -77e7,   -84.7e7, 93.17e7,  102.487e7],
            "depreciation_amortization": [50e7,   55e7,    60.5e7,  66.55e7,  73.205e7],
            "change_in_working_capital": [-20e7,  -22e7,  -24.2e7, -26.62e7, -29.282e7],
        },
        index=pd.Index(_YEARS, name="year"),
    )


@pytest.fixture
def bank_profile() -> dict:
    """Company profile for a financial institution."""
    return {
        "ticker": "HDFCBANK.NS",
        "long_name": "HDFC Bank Limited",
        "sector": "Financial Services",
        "industry": "Banks—Regional",
        "market_cap": 10_000e9,
        "current_price": 1_500.0,
        "fifty_two_week_high": 1_800.0,
        "fifty_two_week_low": 1_300.0,
        "beta": 1.1,
        "shares_outstanding": 7_500_000_000,
        "trailing_pe": 18.0,
        "forward_pe": 16.0,
        "price_to_book": 2.5,
        "enterprise_value": 0.0,
        "dividend_yield": 0.015,
        "long_business_summary": "HDFC Bank is a major Indian banking and financial services company.",
        "total_debt": 0.0,
        "return_on_equity": 0.16,
        "return_on_assets": 0.02,
        "debt_to_equity": 0.0,
    }


@pytest.fixture
def bank_income() -> pd.DataFrame:
    """Income statement for a bank (operating_income is missing or all zeros)."""
    return pd.DataFrame(
        {
            "total_revenue": _REV,
            "gross_profit":            [r * 0.30 for r in _REV],
            "operating_income":        [0.0] * 5,
            "ebitda":                  [0.0] * 5,
            "net_income":              [r * 0.15 for r in _REV],
            "basic_eps":               [15.0 * (1.1 ** i) for i in range(5)],
            "interest_expense":        [0.0] * 5,
            "tax_provision":           [r * 0.05 for r in _REV],
            "depreciation_amortization": [0.0] * 5,
        },
        index=pd.Index(_YEARS, name="year"),
    )


@pytest.fixture
def bank_balance() -> pd.DataFrame:
    """Balance sheet for a bank."""
    equity = [800e7, 920e7, 1_058e7, 1_216.7e7, 1_399.2e7]
    return pd.DataFrame(
        {
            "total_assets":        [8_000e7, 9_200e7, 10_580e7, 12_167e7, 13_992e7],
            "current_assets":      [0.0] * 5,
            "cash_and_equivalents": [800e7,  920e7,   1_058e7,   1_216.7e7, 1_399.2e7],
            "inventory":           [0.0] * 5,
            "accounts_receivable": [0.0] * 5,
            "current_liabilities": [0.0] * 5,
            "total_debt":          [0.0] * 5,
            "stockholders_equity": equity,
            "net_ppe":             [0.0] * 5,
        },
        index=pd.Index(_YEARS, name="year"),
    )


@pytest.fixture
def infra_profile() -> dict:
    """Company profile for a high-capex infrastructure company."""
    return {
        "ticker": "ADANIGREEN.NS",
        "long_name": "Adani Green Energy Limited",
        "sector": "Utilities",
        "industry": "Utilities—Renewable",
        "market_cap": 2_300e9,
        "current_price": 1_475.0,
        "fifty_two_week_high": 2_000.0,
        "fifty_two_week_low": 800.0,
        "beta": 1.4,
        "shares_outstanding": 1_580_000_000,
        "trailing_pe": 150.0,
        "forward_pe": 120.0,
        "price_to_book": 35.0,
        "enterprise_value": 3_000e9,
        "dividend_yield": 0.0,
        "long_business_summary": "Adani Green Energy develops and operates utility-scale renewable power plants.",
        "total_debt": 700e9,
        "return_on_equity": 0.08,
        "return_on_assets": 0.015,
        "debt_to_equity": 800.0,
    }


@pytest.fixture
def infra_cashflow() -> pd.DataFrame:
    """Cash flow statement for a high-capex infra firm (negative free cash flow, high capex)."""
    return pd.DataFrame(
        {
            "operating_cash_flow":      [100e7,  110e7,   121e7,   133.1e7,  146.41e7],
            "capital_expenditure":      [-300e7, -350e7,  -400e7,  -450e7,   -500e7],
            "free_cash_flow":           [-200e7, -240e7,  -279e7,  -316.9e7, -353.59e7],
            "depreciation_amortization": [40e7,   45e7,    50e7,    55e7,     60e7],
            "change_in_working_capital": [-10e7,  -12e7,   -15e7,   -18e7,    -20e7],
        },
        index=pd.Index(_YEARS, name="year"),
    )

