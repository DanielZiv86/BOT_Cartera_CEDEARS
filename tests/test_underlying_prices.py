from datetime import date

import pandas as pd

from src.connectors.base import PriceQuote
from src.market_data.underlying_prices import acquire_underlying_prices, build_price_metrics


class FailingConnector:
    name = "yahoo"
    provider_tier = "APPROVED_MARKET_DATA_FALLBACK"

    def get_last_close(self, symbol, market=None):
        raise RuntimeError("simulated failure")


class WorkingConnector:
    name = "stooq"
    provider_tier = "APPROVED_MARKET_DATA_FALLBACK"

    def get_last_close(self, symbol, market=None):
        return PriceQuote(
            symbol=symbol,
            close=100.0,
            close_date=date(2026, 9, 4),
            prior_close=99.0,
            currency="USD",
            source=self.name,
            source_ref="https://example.test",
            provider_tier=self.provider_tier,
            confidence="MEDIUM_FALLBACK",
        )


def _symbol_map():
    return pd.DataFrame([
        {
            "cedear_ticker": "AAPL",
            "canonical_underlying": "AAPL",
            "underlying_market": "NASDAQ",
            "instrument_type": "Acción",
            "ratio": 10.0,
            "mandate_exception": False,
            "mapping_status": "RESOLVED",
            "mapping_version": "1.0",
            "yahoo_symbol": "AAPL",
            "stooq_symbol": "AAPL",
        }
    ])


def test_fallback_uses_second_provider_after_failure():
    frame = acquire_underlying_prices(
        _symbol_map(),
        [FailingConnector(), WorkingConnector()],
        as_of=date(2026, 9, 5),
    )
    row = frame.iloc[0]
    assert row["provider_selected"] == "stooq"
    assert row["last_close"] == 100.0
    assert row["freshness_status"] == "PRICE_READY_FRESH"
    assert row["attempt_log"][0]["status"] == "ERROR"
    assert row["attempt_log"][1]["status"] == "SUCCESS"


def test_metrics_count_ready_and_blocked_correctly():
    frame = acquire_underlying_prices(
        _symbol_map(),
        [WorkingConnector()],
        as_of=date(2026, 9, 5),
    )
    metrics = build_price_metrics(frame)
    assert metrics["Eligible_Count"] == 1
    assert metrics["Underlying_Price_Total_Ready_Count"] == 1
    assert metrics["Price_Blocked_Count"] == 0
    assert metrics["PASS_UNDERLYING_PRICE_LAYER"] is True
