from __future__ import annotations

import pandas as pd

from src.portfolio.state import validate_portfolio_state
from src.risk.portfolio_fit import calculate_portfolio_fit
from src.risk.portfolio_risk import calculate_portfolio_risk


def test_validate_portfolio_state_baseline_weights():
    payload = {
        "portfolio_state_version": "TEST",
        "snapshot_id": "TEST",
        "as_of": "2026-09-04T00:00:00-03:00",
        "nav_total_usd": 100.0,
        "cash_usd": 60.0,
        "cash_weight": 0.60,
        "cedear_weight": 0.40,
        "positions": [
            {"cedear_ticker": "AAA", "weight": 0.15},
            {"cedear_ticker": "BBB", "weight": 0.25},
        ],
    }
    result = validate_portfolio_state(payload)
    assert result["portfolio_state_status"] == "PORTFOLIO_STATE_VALIDATED"
    assert abs(result["total_weight"] - 1.0) < 1e-12


def test_portfolio_risk_uses_total_nav_weights_not_risky_sleeve_weights():
    dates = pd.bdate_range("2025-01-01", periods=260)
    returns = pd.DataFrame(
        {
            "AAA": [0.001 if i % 2 == 0 else -0.001 for i in range(260)],
            "BBB": [0.002 if i % 3 else -0.001 for i in range(260)],
        },
        index=dates,
    )
    positions = pd.DataFrame([
        {"cedear_ticker": "AAA", "weight": 0.15},
        {"cedear_ticker": "BBB", "weight": 0.25},
    ])
    sector = pd.DataFrame([
        {"cedear_ticker": "AAA", "sector": "A"},
        {"cedear_ticker": "BBB", "sector": "B"},
    ])
    factor = pd.DataFrame([
        {"cedear_ticker": "AAA", "factor": "Quality"},
        {"cedear_ticker": "BBB", "factor": "Growth"},
    ])
    summary, contribution, sector_exp, factor_exp = calculate_portfolio_risk(
        returns, positions, sector, factor, cash_weight=0.60
    )
    assert summary["portfolio_risk_status"] == "PORTFOLIO_RISK_READY"
    assert abs(summary["risky_weight_input"] - 0.40) < 1e-12
    assert abs(summary["cash_weight_input"] - 0.60) < 1e-12
    assert abs(contribution["risk_contribution_pct"].sum() - 1.0) < 1e-9
    assert abs(sector_exp["weight"].sum() - 1.0) < 1e-12
    assert abs(factor_exp["weight"].sum() - 1.0) < 1e-12


def test_portfolio_fit_ready_only_with_full_risky_sleeve_correlation_coverage():
    positions = pd.DataFrame([
        {"cedear_ticker": "AAA", "weight": 0.10},
        {"cedear_ticker": "BBB", "weight": 0.30},
    ])
    complete = pd.DataFrame([
        {"ticker_a": "CCC", "ticker_b": "AAA", "correlation": 0.20},
        {"ticker_a": "CCC", "ticker_b": "BBB", "correlation": 0.40},
    ])
    ready, metrics = calculate_portfolio_fit(complete, positions, candidates=["CCC"])
    assert ready.iloc[0]["portfolio_fit_status"] == "PORTFOLIO_FIT_QUANT_READY"
    assert abs(float(ready.iloc[0]["portfolio_weight_covered"]) - 1.0) < 1e-12
    assert metrics["ready_count"] == 1

    partial = complete[complete["ticker_b"] == "BBB"].copy()
    result, metrics = calculate_portfolio_fit(partial, positions, candidates=["CCC"])
    assert result.iloc[0]["portfolio_fit_status"] == "PORTFOLIO_FIT_QUANT_PARTIAL"
    assert metrics["ready_count"] == 0
