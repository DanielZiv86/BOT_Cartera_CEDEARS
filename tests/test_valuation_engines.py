from __future__ import annotations

from datetime import date

from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import build_etf_scenario


POLICY = {
    "freshness": {
        "price_target_max_age_days": 45,
        "recommendation_max_age_days": 45,
        "etf_holdings_max_age_days": 35,
        "fundamentals_max_period_age_days": 400,
    },
    "quality": {
        "minimum_equity_analyst_count": 3,
        "minimum_etf_covered_weight": 0.50,
        "minimum_etf_valid_holdings": 2,
        "maximum_etf_holdings_to_analyze": 10,
    },
    "probabilities": {
        "prior_bull": 0.25,
        "prior_base": 0.50,
        "prior_bear": 0.25,
        "max_recommendation_blend_weight": 0.50,
    },
    "confidence": {
        "base": 0.35,
        "fresh_price_target_bonus": 0.20,
        "analyst_count_bonus_max": 0.15,
        "fresh_recommendation_bonus": 0.10,
        "fundamentals_bonus": 0.10,
        "etf_holdings_coverage_bonus_max": 0.20,
        "etf_fresh_holdings_bonus": 0.10,
    },
}


class EquityConnector:
    def price_target(self, symbol):
        return {"targetHigh": 150, "targetMean": 125, "targetMedian": 123, "targetLow": 90, "numberAnalysts": 20, "lastUpdated": "2026-09-01"}
    def recommendation_trends(self, symbol):
        return [{"period": "2026-09-01", "strongBuy": 8, "buy": 6, "hold": 5, "sell": 1, "strongSell": 0}]
    def basic_financials(self, symbol):
        return {"metric": {"peTTM": 22}, "series": {"annual": {"netMargin": [{"period": "2025-12-31", "v": 0.2}]}}}
    def retrieved_at(self):
        return "2026-09-05T00:00:00+00:00"


class ETFConnector:
    def etf_profile(self, symbol):
        return {"profile": {"dividendYield": 2.0}}
    def etf_holdings(self, symbol):
        return {"atDate": "2026-09-01", "holdings": [
            {"symbol": "AAA", "percent": 35.0},
            {"symbol": "BBB", "percent": 25.0},
            {"symbol": "CCC", "percent": 20.0},
        ]}
    def quote(self, symbol):
        return {"c": 100.0}
    def price_target(self, symbol):
        return {"targetHigh": 125.0, "targetMean": 115.0, "targetMedian": 114.0, "targetLow": 90.0, "numberAnalysts": 10, "lastUpdated": "2026-09-01"}
    def retrieved_at(self):
        return "2026-09-05T00:00:00+00:00"


def test_equity_ready_when_consensus_is_fresh():
    row = build_equity_scenario("AAA", 100.0, EquityConnector(), POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["bull_target_price"] == 150
    assert row["bear_target_price"] == 90
    assert abs(row["bull_probability"] + row["base_probability"] + row["bear_probability"] - 1.0) < 1e-9


def test_equity_stale_target_blocks():
    connector = EquityConnector()
    connector.price_target = lambda symbol: {"targetHigh": 150, "targetMean": 125, "targetMedian": 123, "targetLow": 90, "numberAnalysts": 20, "lastUpdated": "2026-06-01"}
    row = build_equity_scenario("AAA", 100.0, connector, POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "BLOCKED_BY_DATA"
    assert "PRICE_TARGET_STALE" in row["blockers"]


def test_etf_lookthrough_ready_with_sufficient_fresh_coverage():
    row = build_etf_scenario("ETF1", 100.0, ETFConnector(), POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["etf_lookthrough_covered_weight"] >= 0.50
    assert row["bear_target_price"] < row["base_target_price"] < row["bull_target_price"]
