from __future__ import annotations

import pandas as pd

from src.market_data.cedear_local import build_local_market_layer


def test_implied_ccl_and_costs():
    universe = pd.DataFrame([{"cedear_ticker":"AAPL","ratio":20,"instrument_type":"Equity"}])
    underlying = pd.DataFrame([{"cedear_ticker":"AAPL","last_close":200.0,"last_close_date":"2026-09-04","currency":"USD","freshness_status":"PRICE_READY_FRESH","provider_selected":"test"}])
    local = pd.DataFrame([{"cedear_ticker":"AAPL","last_price_ars":25000.0,"bid_ars":24900.0,"ask_ars":25100.0,"nominal_volume":1000,"cash_volume_ars":25000000,"market_timestamp":"2026-09-04","provider":"test","provider_tier":"test","source_ref":"test","loaded_at":"now","raw_keys":[],"attempt_log":[]}])
    result = build_local_market_layer(universe, underlying, local, brokerage_rate=0.006)
    row = result.iloc[0]
    assert abs(row["mid_ars"] - 25000.0) < 1e-12
    assert abs(row["spread_pct"] - 0.008) < 1e-12
    assert abs(row["implied_ccl"] - 2500.0) < 1e-12
    assert abs(row["effective_buy_ars"] - 25250.6) < 1e-9
    assert row["book_status"] == "BOOK_READY"
    assert row["ccl_status"] == "CCL_READY"


def test_non_usd_underlying_blocks_ccl():
    universe = pd.DataFrame([{"cedear_ticker":"TEST","ratio":10}])
    underlying = pd.DataFrame([{"cedear_ticker":"TEST","last_close":50.0,"currency":"EUR","freshness_status":"PRICE_READY_FRESH"}])
    local = pd.DataFrame([{"cedear_ticker":"TEST","last_price_ars":1000.0,"bid_ars":None,"ask_ars":None}])
    result = build_local_market_layer(universe, underlying, local)
    assert result.iloc[0]["ccl_status"] == "CCL_BLOCKED"
