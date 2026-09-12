from __future__ import annotations

import pandas as pd

from src.orchestration.build_g4_cash_hurdle import _add_execution_gate, _apply_global_governance
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
    # bear_target=40 produces a bear_return_net beyond the -40% tail-risk
    # backstop (max_bear_downside default) even after it was loosened from
    # -15% -- this is meant to represent a name analysts themselves see
    # headed toward serious trouble, not normal single-stock volatility.
    valuation = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "valuation_method": "TEST_MODEL",
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": 0.95,
        "bull_target_price": 180.0,
        "base_target_price": 150.0,
        "bear_target_price": 40.0,
        "bull_probability": 0.35,
        "base_probability": 0.55,
        "bear_probability": 0.10,
    }])
    result, _ = calculate_g4_cash_hurdle(_base_local(), valuation, _fit(), _positions())
    assert result.iloc[0]["bear_return_net"] < G4Policy().max_bear_downside
    assert result.iloc[0]["g4_status"] == "G4_FAIL_DOWNSIDE"


def test_fx_regulatory_stress_is_reported_but_does_not_gate_pass():
    # base_target=108 is chosen so the degraded-CCL FX stress scenario
    # (fx_stress_return_net) breaches what used to be a -20% hard veto, while
    # the fundamental Bear case and risk-adjusted margin are both fine on
    # their own. A CEDEAR holder can hedge this exact scenario via canje
    # (conversion to the underlying foreign shares, exiting in USD abroad)
    # instead of being forced to sell locally through a degraded CCL, so this
    # is computed and reported for the allocator's stress budget but must not
    # block G4_PASS by itself.
    valuation = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "valuation_method": "TEST_MODEL",
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": 0.90,
        "current_price": 100.0,
        "bull_target_price": 150.0,
        "base_target_price": 108.0,
        "bear_target_price": 90.0,
        "bull_probability": 0.25,
        "base_probability": 0.55,
        "bear_probability": 0.20,
    }])
    result, metrics = calculate_g4_cash_hurdle(_base_local(), valuation, _fit(), _positions(), policy=G4Policy())
    row = result.iloc[0]
    assert row["bear_return_net"] >= G4Policy().max_bear_downside
    assert row["fx_stress_return_net"] < -0.20
    assert row["g4_status"] == "G4_PASS"
    assert "fx_regulatory_stress_fail_count" not in metrics
    assert "G4_FAIL_FX_REGULATORY_STRESS" not in result["g4_status"].tolist()


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


def test_clean_pass_candidates_allow_deployment_despite_unrelated_blocked_ticker():
    # 2026-09-12 fix: an unrelated BLOCKED_BY_DATA ticker (a per-ticker data
    # gap) used to veto deployment for the WHOLE Top-30, even when other,
    # cleanly-evaluated candidates passed G4. It should now only keep that
    # one ticker out of consideration; ranking_status still surfaces the
    # gap, but deployment_decision follows the clean candidates.
    governed = _apply_global_governance({
        "ticker_count": 30,
        "evaluated_count": 29,
        "blocked_count": 1,
        "pass_count": 3,
        "clean_g4_pass_count": 3,
        "extreme_target_review_required_count": 0,
    })
    assert governed["deployment_decision"] == "ALLOW_NEW_DEPLOYMENT"
    assert governed["ranking_status"] == "COMPLETE_WITH_DATA_GAPS"


def test_no_clean_pass_candidates_still_holds_on_blocked_data():
    governed = _apply_global_governance({
        "ticker_count": 30,
        "evaluated_count": 29,
        "blocked_count": 1,
        "pass_count": 0,
        "clean_g4_pass_count": 0,
        "extreme_target_review_required_count": 0,
    })
    assert governed["deployment_decision"] == "NO_NEW_DEPLOYMENT_DATA_GAPS"
    assert governed["ranking_status"] == "COMPLETE_WITH_DATA_GAPS"


def test_execution_gate_accepts_current_canonical_local_market_statuses():
    economic = pd.DataFrame([{"cedear_ticker": "CIBR", "g4_status": "G4_FAIL_DOWNSIDE"}])
    local = pd.DataFrame([{
        "cedear_ticker": "CIBR",
        "execution_book_status": "BOOK_EXECUTABLE_BY_SANITY",
        "executable_buy_ars": 12345.0,
        "ratio_status": "RATIO_VALIDATED_CANONICAL_CCL",
        "ccl_status": "CCL_READY_VALIDATED_CANONICAL",
        "market_session_status": "OPEN",
    }])
    out = _add_execution_gate(economic, local)
    assert bool(out.iloc[0]["analysis_ready"])
    assert bool(out.iloc[0]["execution_ready"])
    assert out.iloc[0]["execution_gate_status"] == "EXECUTION_READY"


def test_execution_gate_remains_fail_closed_without_executable_book():
    economic = pd.DataFrame([{"cedear_ticker": "TEST", "g4_status": "G4_FAIL_RETURN"}])
    local = pd.DataFrame([{
        "cedear_ticker": "TEST",
        "execution_book_status": "BOOK_NOT_EXECUTABLE",
        "executable_buy_ars": 12345.0,
        "ratio_status": "RATIO_VALIDATED_CANONICAL_CCL",
        "ccl_status": "CCL_READY_VALIDATED_CANONICAL",
        "market_session_status": "OPEN",
    }])
    out = _add_execution_gate(economic, local)
    assert not bool(out.iloc[0]["execution_ready"])
    assert out.iloc[0]["execution_gate_status"] == "NOT_EXECUTION_READY"
