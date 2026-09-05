from __future__ import annotations

import pandas as pd

from src.orchestration.build_g4_cash_hurdle import _apply_global_governance
from src.valuation.g4 import G4Policy, calculate_g4_cash_hurdle


def _base_local():
    return pd.DataFrame([{
        "cedear_ticker": "TEST",
        "valuation_g4_local_gate": "PASS",
        "ratio_used": 10.0,
        "market_ccl_reference": 1600.0,
        "analytical_local_ref_ars": 16000.0,
        "spread_pct": 0.01,
        "execution_book_status": "EXECUTABLE_BOOK_READY",
    }])


def _fit():
    return pd.DataFrame([{
        "cedear_ticker": "TEST",
        "portfolio_fit_status": "PORTFOLIO_FIT_QUANT_READY",
        "diversification_score": 80.0,
        "max_corr_to_portfolio": 0.50,
    }])


def _positions():
    return pd.DataFrame([{"cedear_ticker": "OTHER", "weight": 0.30}])


def test_g4_pass_when_margin_and_downside_are_sufficient():
    valuation = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "valuation_method": "TEST_MODEL",
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": 0.90,
        "bull_target_price": 140.0,
        "base_target_price": 125.0,
        "bear_target_price": 90.0,
        "bull_probability": 0.25,
        "base_probability": 0.55,
        "bear_probability": 0.20,
    }])
    result, metrics = calculate_g4_cash_hurdle(
        _base_local(), valuation, _fit(), _positions(), policy=G4Policy(), brokerage_rate=0.006
    )
    row = result.iloc[0]
    assert row["g4_status"] == "G4_PASS"
    assert row["risk_adjusted_er"] > row["cash_hurdle"]
    assert row["bear_return_net"] >= -0.15
    assert metrics["cash_optimality_status"] == "CASH_NOT_OPTIMAL_BY_MODEL"


def test_missing_valuation_never_passes():
    result, metrics = calculate_g4_cash_hurdle(
        _base_local(), pd.DataFrame(columns=["cedear_ticker"]), _fit(), _positions()
    )
    row = result.iloc[0]
    assert row["g4_status"] == "BLOCKED_BY_DATA"
    assert "VALUATION_NOT_READY" in row["g4_reason"]
    assert metrics["cash_optimality_status"] == "NOT_DEMONSTRATED"


def test_bear_downside_can_fail_even_with_positive_expected_return():
    valuation = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "valuation_method": "TEST_MODEL",
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": 0.95,
        "bull_target_price": 180.0,
        "base_target_price": 150.0,
        "bear_target_price": 70.0,
        "bull_probability": 0.35,
        "base_probability": 0.55,
        "bear_probability": 0.10,
    }])
    result, _ = calculate_g4_cash_hurdle(_base_local(), valuation, _fit(), _positions())
    assert result.iloc[0]["g4_status"] == "G4_FAIL_DOWNSIDE"


def test_invalid_probabilities_block_ticker():
    valuation = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "valuation_method": "TEST_MODEL",
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": 0.90,
        "bull_target_price": 140.0,
        "base_target_price": 125.0,
        "bear_target_price": 90.0,
        "bull_probability": 0.50,
        "base_probability": 0.50,
        "bear_probability": 0.50,
    }])
    result, _ = calculate_g4_cash_hurdle(_base_local(), valuation, _fit(), _positions())
    assert result.iloc[0]["g4_status"] == "BLOCKED_BY_DATA"
    assert "SCENARIO_PROBABILITIES_INVALID" in result.iloc[0]["g4_reason"]


def test_incomplete_universe_blocks_global_deployment_even_with_passes():
    governed = _apply_global_governance({
        "ticker_count": 305,
        "blocked_count": 80,
        "pass_count": 90,
        "deployment_decision": "ALLOW_NEW_DEPLOYMENT",
    })
    assert governed["deployment_decision"] == "RESEARCH_BLOCKED"
    assert governed["ranking_status"] == "PARTIAL_NOT_ACTIONABLE"
