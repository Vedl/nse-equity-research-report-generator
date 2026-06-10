"""Pytest tests for analysis/excess_return.py."""

from __future__ import annotations

from pathlib import Path
import pytest

from equity_research.analysis.excess_return import run_excess_return
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def test_excess_return_calculation(cfg, bank_profile, bank_income, bank_balance):
    """Run excess return model on synthetic bank data and verify outputs."""
    financials = {
        "income": bank_income,
        "balance_sheet": bank_balance,
    }
    result = run_excess_return(bank_profile, financials, cfg)
    
    assert not result.is_pb_fallback
    assert result.book_value_per_share > 0
    assert result.cost_of_equity > 0
    assert result.roe > 0
    assert result.sustainable_growth >= 0
    assert result.intrinsic_value_per_share > 0
    assert len(result.projected_excess_return) == cfg.dcf.projection_horizon
    assert len(result.projected_book_value) == cfg.dcf.projection_horizon


def test_excess_return_pb_fallback(cfg, bank_profile, bank_balance):
    """Verify that we fall back to P/B multiple valuation when ROE is missing or invalid."""
    import pandas as pd
    profile = bank_profile.copy()
    profile["return_on_equity"] = None
    # Empty income statement means ROE cannot be computed
    financials = {
        "income": pd.DataFrame(),
        "balance_sheet": bank_balance,
    }
    result = run_excess_return(profile, financials, cfg)
    
    assert result.is_pb_fallback
    assert result.intrinsic_value_per_share > 0
    # Implied P/B value: book_value_per_share (from balance sheet) * price_to_book
    expected_intrinsic = result.book_value_per_share * profile["price_to_book"]
    assert abs(result.intrinsic_value_per_share - expected_intrinsic) < 0.001
