from __future__ import annotations

from datetime import date

from src.connectors.issuer_holdings import HoldingsSnapshot
from src.connectors.non_equity_tracker import TrackerSnapshot
from src.orchestration.build_valuation_scenarios import _is_etf
from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import build_etf_scenario
from src.valuation.etf_issuer_engine import build_issuer_etf_scenario
from src.valuation.non_equity_tracker_engine import build_non_equity_tracker_scenario


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
    "instrument_overrides": {
        "etf_like_tickers": ["GLD", "IBIT", "ETHA"],
        "non_equity_trackers": ["GLD", "IBIT", "ETHA"],
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

TRACKER_POLICY = {
    "version": "NET-TEST",
    "effective_date": "2026-09-05",
    "max_issuer_nav_age_days": 10,
    "trackers": {
        "IBIT": {
            "asset": "BITCOIN",
            "annual_fee": 0.0025,
            "confidence": 0.60,
            "issuer_url": "https://issuer.example/ibit",
            "scenarios": {
                "bull_return": 0.60,
                "base_return": 0.15,
                "bear_return": -0.45,
                "bull_probability": 0.30,
                "base_probability": 0.45,
                "bear_probability": 0.25,
            },
        }
    },
}


class EquityConnector:
    def __init__(self):
        self.price_target_calls = []
        self.recommendation_calls = []
        self.financial_calls = []
    def price_target(self, symbol):
        self.price_target_calls.append(symbol)
        return {"targetHigh": 150, "targetMean": 125, "targetMedian": 123, "targetLow": 90, "numberAnalysts": 20, "lastUpdated": "2026-09-01"}
    def recommendation_trends(self, symbol):
        self.recommendation_calls.append(symbol)
        raise AssertionError("recommendation enrichment must be deferred in universe mode")
    def basic_financials(self, symbol):
        self.financial_calls.append(symbol)
        raise AssertionError("fundamental enrichment must be deferred in universe mode")
    def retrieved_at(self):
        return "2026-09-05T00:00:00+00:00"


class ETFConnector:
    def __init__(self):
        self.quote_calls = []
        self.target_calls = []
    def etf_profile(self, symbol):
        return {"profile": {"dividendYield": 2.0}}
    def etf_holdings(self, symbol):
        return {"atDate": "2026-09-01", "holdings": [
            {"symbol": "AAA", "percent": 35.0},
            {"symbol": "BBB", "percent": 25.0},
            {"symbol": "CCC", "percent": 20.0},
        ]}
    def quote(self, symbol):
        self.quote_calls.append(symbol)
        return {"c": 100.0}
    def price_target(self, symbol):
        self.target_calls.append(symbol)
        return {"targetHigh": 125.0, "targetMean": 115.0, "targetMedian": 114.0, "targetLow": 90.0, "numberAnalysts": 10, "lastUpdated": "2026-09-01"}
    def retrieved_at(self):
        return "2026-09-05T00:00:00+00:00"


class IssuerConnector:
    def fetch(self, symbol):
        return HoldingsSnapshot(
            ticker=symbol,
            holdings=[
                {"symbol": "AAA", "percent": 35.0},
                {"symbol": "BBB", "percent": 25.0},
                {"symbol": "CCC", "percent": 20.0},
            ],
            as_of="2026-09-01",
            source_ref="https://issuer.example/fund",
            source_tier="ISSUER_OFFICIAL",
            provider="Issuer",
        )
    def retrieved_at(self):
        return "2026-09-05T00:00:00+00:00"


class TrackerConnector:
    def fetch(self, symbol):
        return TrackerSnapshot(
            ticker=symbol,
            nav=44.76,
            nav_date="2026-09-02",
            market_price=43.79,
            market_price_date="2026-09-02",
            premium_discount_pct=0.14,
            source_ref="https://issuer.example/ibit",
            provider="Issuer",
        )
    def retrieved_at(self):
        return "2026-09-05T00:00:00+00:00"


def test_equity_ready_when_consensus_is_fresh():
    connector = EquityConnector()
    row = build_equity_scenario("AAA", 100.0, connector, POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["bull_target_price"] == 150
    assert row["bear_target_price"] == 90
    assert row["bull_probability"] == 0.25
    assert row["base_probability"] == 0.50
    assert row["bear_probability"] == 0.25
    assert row["enrichment_status"] == "DEFERRED_TO_DEEP_RESEARCH"
    assert connector.price_target_calls == ["AAA"]
    assert connector.recommendation_calls == []
    assert connector.financial_calls == []


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


def test_etf_early_stop_avoids_unnecessary_constituent_calls():
    connector = ETFConnector()
    row = build_etf_scenario("ETF1", 100.0, connector, POLICY, as_of=date(2026, 9, 5), constituent_cache={})
    assert row["valuation_status"] == "VALUATION_READY"
    assert connector.quote_calls == ["AAA", "BBB"]
    assert connector.target_calls == ["AAA", "BBB"]
    assert row["etf_analyzed_holding_count"] == 2


def test_etf_shared_cache_reuses_constituents_across_funds():
    connector = ETFConnector()
    cache = {}
    first = build_etf_scenario("ETF1", 100.0, connector, POLICY, as_of=date(2026, 9, 5), constituent_cache=cache)
    second = build_etf_scenario("ETF2", 100.0, connector, POLICY, as_of=date(2026, 9, 5), constituent_cache=cache)
    assert first["valuation_status"] == "VALUATION_READY"
    assert second["valuation_status"] == "VALUATION_READY"
    assert connector.quote_calls == ["AAA", "BBB"]
    assert connector.target_calls == ["AAA", "BBB"]
    assert second["etf_shared_constituent_cache_hits"] == 2


def test_issuer_fallback_ready_with_official_holdings():
    row = build_issuer_etf_scenario("ETF1", 100.0, ETFConnector(), IssuerConnector(), POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["valuation_method"] == "ISSUER_HOLDINGS_LOOKTHROUGH_V1"
    assert row["holdings_source_tier"] == "ISSUER_OFFICIAL"
    assert row["etf_lookthrough_covered_weight"] >= 0.50


def test_non_equity_tracker_is_not_forced_through_equity_holdings():
    row = build_issuer_etf_scenario("IBIT", 100.0, ETFConnector(), IssuerConnector(), POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "BLOCKED_BY_DATA"
    assert "NON_EQUITY_TRACKER_NOT_ELIGIBLE_FOR_EQUITY_LOOKTHROUGH" in row["blockers"]


def test_non_equity_tracker_uses_fresh_issuer_nav_and_explicit_stress_policy():
    row = build_non_equity_tracker_scenario("IBIT", 43.79, TrackerConnector(), TRACKER_POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["valuation_method"] == "NON_EQUITY_TRACKER_NAV_STRESS_V1"
    assert row["issuer_nav"] == 44.76
    assert row["bear_target_price"] < row["base_target_price"] < row["bull_target_price"]
    assert row["scenario_bear_return_asset"] == -0.45


def test_non_equity_tracker_stale_nav_blocks():
    connector = TrackerConnector()
    connector.fetch = lambda symbol: TrackerSnapshot(
        ticker=symbol,
        nav=44.76,
        nav_date="2026-08-01",
        market_price=43.79,
        market_price_date="2026-08-01",
        premium_discount_pct=0.0,
        source_ref="https://issuer.example/ibit",
        provider="Issuer",
    )
    row = build_non_equity_tracker_scenario("IBIT", 43.79, connector, TRACKER_POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "BLOCKED_BY_DATA"
    assert "ISSUER_NAV_STALE" in row["blockers"]


def test_netflix_is_not_misclassified_as_etf_by_substring():
    assert _is_etf("NFLX", "Acción", "Netflix Inc", POLICY) is False
    assert _is_etf("SPY", "ETF tradicional", "SPDR S&P 500 ETF Trust", POLICY) is True
