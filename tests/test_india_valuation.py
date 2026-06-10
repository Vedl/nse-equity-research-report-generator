import pytest
import pandas as pd
from equity_research.analysis.india_valuation import IndiaValuationEngine, IndiaValuationInputs, PromoterProfile

def test_india_valuation_engine():
    promoter = PromoterProfile(
        promoter_holding_pct=70.0,
        promoter_pledge_pct=0.0,
        has_qualified_audit=True,
        related_party_pct=5.0
    )
    inputs = IndiaValuationInputs(
        ticker="TCS.NS",
        sector="Information Technology",
        industry="Software",
        is_psu=False,
        business_group="Tata",
        is_holding_company=False,
        promoter=promoter,
        net_income=50000,
        ebitda=70000,
        cfo=55000,
        total_assets=100000,
        total_assets_prev=90000,
        current_assets=50000,
        current_assets_prev=45000,
        current_liabs=20000,
        current_liabs_prev=18000,
        dcf_equity_value_per_share=3500.0,
        dcf_wacc=0.11,
        dcf_terminal_growth=0.04,
        current_price=3800.0,
        shares_outstanding=300,
        net_debt=-20000
    )

    engine = IndiaValuationEngine(inputs)
    res = engine.run()
    
    assert res.is_psu == False
    assert res.primary_multiple == "EV/EBITDA"
    assert res.promoter_score > 75
    assert res.group_adjustment_pct == 0.10
    assert res.blended_value > 3500.0
