from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.market_data.cedear_local import build_local_market_layer


def test_implied_ccl_uses_comafi_ratio_and_valid_book():
    universe = pd.DataFrame([{"cedear_ticker": "AAPL", "ratio": 10, "instrument_type": "Equity"}])
    underlying = pd.DataFrame([{"cedear_ticker": "AAPL", "last_close": 200.0, "last_close_date": "2026-09-04", "currency": "USD", "freshness_status": "PRICE_READY_FRESH", "provider_selected": "test"}])
    local = pd.DataFrame([{"cedear_ticker": "AAPL", "last_price_ars": 25000.0, "bid_ars": 24900.0, "ask_ars": 25100.0, "nominal_volume": 1000, "cash_volume_ars": 25000000, "market_timestamp": "2026-09-04", "provider": "test", "provider_tier": "test", "source_ref": "test", "loaded_at": "now", "raw_keys": [], "attempt_log": []}])
    ratios = pd.DataFrame([{"cedear_ticker": "AAPL", "comafi_ratio_text": "20:1", "comafi_ratio_multiplier": 20.0, "ratio_conflict": False, "comafi_source_ref": "test"}])
    refs = pd.DataFrame([{"cedear_ticker": "AAPL", "ccl_reference_mark": 2500.0}])
    now = datetime(2026, 9, 4, 16, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

    result = build_local_market_layer(universe, underlying, local, ratios, refs, brokerage_rate=0.006, now=now)
    row = result.iloc[0]
    assert abs(row["validated_mid_ars"] - 25000.0) < 1e-12
    assert abs(row["spread_pct"] - 0.008) < 1e-12
    assert abs(row["implied_ccl"] - 2500.0) < 1e-12
    assert abs(row["effective_executable_buy_ars"] - 25250.6) < 1e-9
    assert row["ratio_status"] == "RATIO_VALIDATED_COMAFI"
    assert row["ccl_status"] == "CCL_READY_VALIDATED"
    assert row["valuation_g4_local_gate"] == "PASS_WITH_VALIDATED_LOCAL_DATA"


def test_absurd_book_is_excluded_from_mid_and_execution():
    universe = pd.DataFrame([{"cedear_ticker": "ADP", "ratio": 2}])
    underlying = pd.DataFrame([{"cedear_ticker": "ADP", "last_close": 92.0, "currency": "USD", "freshness_status": "PRICE_READY_FRESH"}])
    local = pd.DataFrame([{"cedear_ticker": "ADP", "last_price_ars": 73350.0, "bid_ars": 1.0, "ask_ars": 73975.0}])
    ratios = pd.DataFrame([{"cedear_ticker": "ADP", "comafi_ratio_multiplier": 2.0, "comafi_ratio_text": "2:1", "ratio_conflict": False}])
    result = build_local_market_layer(universe, underlying, local, ratios)
    row = result.iloc[0]
    assert row["book_sanity_status"] == "BOOK_INVALID_SANITY"
    assert pd.isna(row["validated_mid_ars"])
    assert abs(row["analytical_local_ref_ars"] - 73350.0) < 1e-12
    assert pd.isna(row["effective_executable_buy_ars"])


def test_non_usd_underlying_blocks_ccl():
    universe = pd.DataFrame([{"cedear_ticker": "TEST", "ratio": 10}])
    underlying = pd.DataFrame([{"cedear_ticker": "TEST", "last_close": 50.0, "currency": "EUR", "freshness_status": "PRICE_READY_FRESH"}])
    local = pd.DataFrame([{"cedear_ticker": "TEST", "last_price_ars": 1000.0, "bid_ars": None, "ask_ars": None}])
    ratios = pd.DataFrame([{"cedear_ticker": "TEST", "comafi_ratio_multiplier": 10.0, "comafi_ratio_text": "10:1", "ratio_conflict": False}])
    result = build_local_market_layer(universe, underlying, local, ratios)
    assert result.iloc[0]["ccl_status"] == "CCL_BLOCKED"
