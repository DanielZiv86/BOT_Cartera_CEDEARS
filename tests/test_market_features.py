import pandas as pd

from src.features.market_features import calculate_market_features


def _history(rows: int = 300, start: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=rows)
    prices = [start * (1.001 ** i) for i in range(rows)]
    return pd.DataFrame(
        {
            "cedear_ticker": ["TEST"] * rows,
            "canonical_underlying": ["TEST"] * rows,
            "date": dates,
            "close": prices,
            "adjusted_close": prices,
        }
    )


def test_market_features_ready_with_full_history():
    features, metrics = calculate_market_features(_history())
    row = features.iloc[0]
    assert row["feature_status"] == "FEATURES_READY"
    assert row["populated_feature_count"] == row["feature_count"]
    assert metrics["pass_market_features"] is True
    assert row["return_252d"] > 0
    assert row["momentum_12m"] == row["return_252d"]
    assert row["ma20"] > 0
    assert row["max_drawdown"] <= 0


def test_market_features_partial_when_history_short():
    features, metrics = calculate_market_features(_history(rows=80))
    row = features.iloc[0]
    assert row["feature_status"] == "FEATURES_PARTIAL"
    assert pd.isna(row["return_252d"])
    assert metrics["pass_market_features"] is False
