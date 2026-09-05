import pandas as pd

from src.risk.risk_engine import calculate_risk_and_correlations
from src.risk.portfolio_risk import calculate_portfolio_risk
from src.risk.portfolio_fit import calculate_portfolio_fit


def _history() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=320)
    rows = []
    for ticker, drift, phase in [("SPY", 0.0005, 0.0), ("AAA", 0.0008, 0.2), ("BBB", 0.0002, 1.1)]:
        price = 100.0
        for i, d in enumerate(dates):
            shock = ((i % 11) - 5) * 0.00035 + phase * 0.00005
            price *= 1.0 + drift + shock
            rows.append({
                "cedear_ticker": ticker,
                "canonical_underlying": ticker,
                "date": d,
                "close": price,
                "adjusted_close": price,
            })
    return pd.DataFrame(rows)


def test_cross_sectional_risk_engine_ready():
    risk, corr, rolling, metrics = calculate_risk_and_correlations(_history(), benchmark_ticker="SPY")
    assert len(risk) == 3
    assert metrics["ticker_count"] == 3
    assert metrics["pass_cross_sectional_risk"] is True
    assert {"ticker_a", "ticker_b", "correlation"}.issubset(corr.columns)
    assert set(rolling["window_trading_days"]) == {63, 126, 252}


def test_portfolio_risk_requires_real_weights_and_calculates_contribution():
    from src.risk.risk_engine import build_return_matrix
    returns = build_return_matrix(_history())
    positions = pd.DataFrame({"cedear_ticker": ["AAA", "BBB"], "weight": [0.6, 0.4]})
    summary, contribution, sector, factor = calculate_portfolio_risk(returns, positions)
    assert summary["portfolio_risk_status"] == "PORTFOLIO_RISK_READY"
    assert summary["portfolio_volatility_annualized"] >= 0
    assert len(contribution) == 2
    assert sector.empty and factor.empty


def test_quantitative_portfolio_fit_uses_correlations():
    _, corr, _, _ = calculate_risk_and_correlations(_history(), benchmark_ticker="SPY")
    positions = pd.DataFrame({"cedear_ticker": ["AAA"], "weight": [1.0]})
    fit, metrics = calculate_portfolio_fit(corr, positions, candidates=["BBB"])
    assert len(fit) == 1
    assert fit.iloc[0]["diversification_score"] is not None
    assert fit.iloc[0]["portfolio_fit_status"] == "PORTFOLIO_FIT_QUANT_READY"
