"""Pytest tests for analysis/residual_income.py."""

from __future__ import annotations

from pathlib import Path
import pytest

from equity_research.analysis.residual_income import run_residual_income
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def test_residual_income_calculation(cfg, synthetic_profile, synthetic_income, synthetic_balance):
    """Run residual income model on synthetic data and verify outputs."""
    # We will use negative_fcff_cashflow or default, but cashflow statement doesn't affect RI
    # except through dividends if payout ratio is estimated.
    import pandas as pd
    cashflow = pd.DataFrame(
        {
            "operating_cash_flow": [0.0] * 5,
            "capital_expenditure": [0.0] * 5,
            "free_cash_flow": [0.0] * 5,
            "depreciation_amortization": [0.0] * 5,
            "change_in_working_capital": [0.0] * 5,
        },
        index=synthetic_income.index,
    )
    
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": cashflow,
    }

    result = run_residual_income(synthetic_profile, financials, cfg)
    
    assert result.book_value_per_share > 0
    assert result.cost_of_equity > 0
    assert result.intrinsic_value_per_share > 0
    assert len(result.projected_net_income) == cfg.dcf.projection_horizon
    assert len(result.projected_book_value) == cfg.dcf.projection_horizon
    assert len(result.projected_ri) == cfg.dcf.projection_horizon
    assert len(result.pv_ri) == cfg.dcf.projection_horizon


def test_residual_income_missing_shares(cfg, synthetic_profile, synthetic_income, synthetic_balance):
    """Verify that ValueError is raised if shares_outstanding is missing."""
    profile = synthetic_profile.copy()
    profile["shares_outstanding"] = 0
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_income, # minimal dummy
    }
    with pytest.raises(ValueError, match="shares_outstanding"):
        run_residual_income(profile, financials, cfg)
