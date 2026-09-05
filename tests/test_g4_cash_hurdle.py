from __future__ import annotations

import pandas as pd

from src.orchestration.build_g4_cash_hurdle import _apply_global_governance
from src.valuation.g4 import G4Policy, calculate_g4_cash_hurdle
from src.valuation.g4_review import apply_extreme_target_review


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
        "current_price": 100.0,
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
        "clean_g4_pass_count": 60,
        "extreme_target_review_required_count": 30,
        "deployment_decision": "ALLOW_NEW_DEPLOYMENT",
    })
    assert governed["deployment_decision"] == "RESEARCH_BLOCKED"
    assert governed["ranking_status"] == "PARTIAL_NOT_ACTIONABLE"


def test_extreme_target_pass_is_flagged_and_not_clean_actionable():
    valuation = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "current_price": 100.0,
        "bull_target_price": 240.0,
        "base_target_price": 180.0,
        "bear_target_price": 80.0,
    }])
    economic = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "g4_status": "G4_PASS",
        "net_benefit_vs_cash": 0.25,
    }])
    reviewed, metrics = apply_extreme_target_review(economic, valuation, {
        "target_review": {
            "base_upside_review_threshold": 0.75,
            "bull_upside_review_threshold": 1.25,
            "high_low_dispersion_review_threshold": 1.00,
        }
    })
    row = reviewed.iloc[0]
    assert row["target_review_status"] == "EXTREME_TARGET_REQUIRES_REVIEW"
    assert "EXTREME_BASE_TARGET_UPSIDE" in row["target_review_flags"]
    assert "EXTREME_BULL_TARGET_UPSIDE" in row["target_review_flags"]
    assert "EXTREME_HIGH_LOW_TARGET_DISPERSION" in row["target_review_flags"]
    assert metrics["extreme_target_review_required_count"] == 1
    assert metrics["clean_g4_pass_count"] == 0
