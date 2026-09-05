from datetime import date

import pandas as pd

from src.market_data.history_layer import _classify_history, _stooq_transport_symbol


def test_stooq_transport_symbol_recognizes_new_york_market():
    assert _stooq_transport_symbol("AAPL", "New York") == "AAPL.US"


def test_history_ready_classification():
    dates = pd.date_range("2025-01-01", periods=220, freq="B").date
    frame = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})
    assert _classify_history(frame) == "HISTORY_READY"


def test_short_history_classification():
    dates = pd.date_range("2026-06-01", periods=40, freq="B").date
    frame = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})
    assert _classify_history(frame) == "SHORT_HISTORY_BY_AGE"
