"""Pytest tests for analysis/router.py."""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import pytest

from equity_research.analysis.router import Confidence, ModelRoute, route_model
from equity_research.config import load_config

_REPO = Path(__file__).parent.parent


@pytest.fixture
def cfg():
    return load_config(_REPO / "config.yaml")


def test_router_default_fcff(cfg, synthetic_profile, synthetic_income, synthetic_balance, synthetic_cashflow):
    """Stable operating company with positive cash flows should route to FCFF."""
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    decision = route_model(synthetic_profile, financials, cfg)
    assert decision.model == ModelRoute.FCFF
    assert "FCFF" in decision.reason


def test_router_financial_services_keyword(cfg, bank_profile, synthetic_income, synthetic_balance, synthetic_cashflow):
    """Company in Financial Services sector should route to EXCESS_RETURN."""
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": synthetic_cashflow,
    }
    decision = route_model(bank_profile, financials, cfg)
    assert decision.model == ModelRoute.FINANCIAL
    assert "Financial" in decision.reason


def test_router_no_operating_income(cfg, synthetic_profile, bank_income, bank_balance, synthetic_cashflow):
    """Company with no operating income should route to EXCESS_RETURN."""
    financials = {
        "income": bank_income,
        "balance_sheet": bank_balance,
        "cash_flow": synthetic_cashflow,
    }
    # Remove financial keyword to test Rule 1 strictly
    profile = synthetic_profile.copy()
    profile["sector"] = "Technology"
    profile["industry"] = "Software"
    
    decision = route_model(profile, financials, cfg)
    assert decision.model == ModelRoute.FINANCIAL
    assert "operating income" in decision.reason.lower()


def test_router_infra_capex_heavy(cfg, infra_profile, synthetic_income, synthetic_balance, infra_cashflow):
    """Infra/utilities mid-capex-cycle should route to EV_EBITDA_RELATIVE."""
    balance = synthetic_balance.copy()
    # EBITDA is ~292.82e7. We need net_debt > 4 * EBITDA = 1171.28e7.
    # Set total_debt = 1500e7 and cash = 100e7 so net_debt = 1400e7 > 1171.28e7
    balance["total_debt"] = 1500.0e7
    balance["cash_and_equivalents"] = 100.0e7
    financials = {
        "income": synthetic_income,
        "balance_sheet": balance,
        "cash_flow": infra_cashflow,
    }
    decision = route_model(infra_profile, financials, cfg)
    assert decision.model == ModelRoute.RESIDUAL_INCOME


def test_router_negative_median_fcff_residual_income(cfg, synthetic_profile, synthetic_income, synthetic_balance, negative_fcff_cashflow):
    """Volatile or negative median cash flow but positive book value should route to RESIDUAL_INCOME."""
    financials = {
        "income": synthetic_income,
        "balance_sheet": synthetic_balance,
        "cash_flow": negative_fcff_cashflow,
    }
    decision = route_model(synthetic_profile, financials, cfg)
    assert decision.model == ModelRoute.RESIDUAL_INCOME
    assert "residual income" in decision.reason.lower()
