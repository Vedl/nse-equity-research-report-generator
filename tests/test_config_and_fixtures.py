"""M1 smoke tests: config loading, fixture shapes, and formatting utilities."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from equity_research.config import AppConfig, load_config
from equity_research.utils.formatting import (
    NA,
    cagr,
    fmt_inr,
    fmt_pct,
    fmt_x,
    na_if_none,
    safe_divide,
)

_REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_load_config_returns_app_config() -> None:
    cfg = load_config(_REPO_ROOT / "config.yaml")
    assert isinstance(cfg, AppConfig)


def test_config_values_are_reasonable() -> None:
    cfg = load_config(_REPO_ROOT / "config.yaml")
    assert 0.01 < cfg.market.risk_free_rate < 0.20
    assert 0.01 < cfg.market.equity_risk_premium < 0.20
    assert 0.10 < cfg.market.tax_rate < 0.50
    assert cfg.dcf.projection_horizon >= 1
    assert 0.0 < cfg.dcf.terminal_growth_rate < 0.15
    assert cfg.peers.max_peers >= 1
    assert cfg.report.currency == "INR"


def test_load_config_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")


# ---------------------------------------------------------------------------
# Fixture shapes
# ---------------------------------------------------------------------------


def test_synthetic_income_shape(synthetic_income: pd.DataFrame) -> None:
    assert synthetic_income.index.name == "year"
    assert len(synthetic_income) == 5
    assert "total_revenue" in synthetic_income.columns
    assert "net_income" in synthetic_income.columns
    assert "basic_eps" in synthetic_income.columns


def test_synthetic_balance_shape(synthetic_balance: pd.DataFrame) -> None:
    assert len(synthetic_balance) == 5
    assert "total_assets" in synthetic_balance.columns
    assert "stockholders_equity" in synthetic_balance.columns
    assert "current_liabilities" in synthetic_balance.columns


def test_synthetic_cashflow_shape(synthetic_cashflow: pd.DataFrame) -> None:
    assert len(synthetic_cashflow) == 5
    assert "operating_cash_flow" in synthetic_cashflow.columns
    assert "capital_expenditure" in synthetic_cashflow.columns
    assert "free_cash_flow" in synthetic_cashflow.columns


def test_synthetic_profile_keys(synthetic_profile: dict) -> None:
    required = {
        "ticker", "long_name", "sector", "industry", "market_cap",
        "current_price", "beta", "shares_outstanding", "trailing_pe",
        "price_to_book", "enterprise_value", "return_on_equity",
    }
    assert required.issubset(synthetic_profile.keys())


# ---------------------------------------------------------------------------
# Formatting utilities
# ---------------------------------------------------------------------------


def test_safe_divide_normal() -> None:
    assert safe_divide(10.0, 4.0) == pytest.approx(2.5)


def test_safe_divide_zero_denominator() -> None:
    assert safe_divide(10.0, 0.0) is None


def test_safe_divide_none_inputs() -> None:
    assert safe_divide(None, 5.0) is None
    assert safe_divide(5.0, None) is None


def test_safe_divide_nan() -> None:
    import math
    assert safe_divide(float("nan"), 5.0) is None


def test_na_if_none_with_value() -> None:
    assert na_if_none(3.14) == 3.14


def test_na_if_none_with_none() -> None:
    assert na_if_none(None) == NA


def test_fmt_inr_crores() -> None:
    # 1000 Crores = 1000 * 1e7 = 1e10
    result = fmt_inr(1_000 * 1e7)
    assert "₹" in result
    assert "Cr" in result
    assert "1,000" in result


def test_fmt_inr_none() -> None:
    assert fmt_inr(None) == NA


def test_fmt_pct_normal() -> None:
    assert fmt_pct(0.15) == "15.00%"


def test_fmt_pct_none() -> None:
    assert fmt_pct(None) == NA


def test_fmt_x_normal() -> None:
    assert fmt_x(25.0) == "25.00x"


def test_fmt_x_none() -> None:
    assert fmt_x(None) == NA


def test_cagr_known_answer() -> None:
    # 1000 → 1464.1 over 4 years = 10% CAGR
    result = cagr(1_000.0, 1_464.1, 4)
    assert result == pytest.approx(0.10, rel=1e-3)


def test_cagr_invalid_inputs() -> None:
    assert cagr(None, 100.0, 3) is None
    assert cagr(0.0, 100.0, 3) is None
    assert cagr(100.0, 50.0, 0) is None
