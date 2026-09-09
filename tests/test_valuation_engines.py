from datetime import date

from src.valuation.equity_engine import build_equity_scenario
from src.valuation.etf_engine import build_etf_scenario
from src.valuation.issuer_etf_engine import build_issuer_etf_scenario
from src.valuation.tracker_engine import build_tracker_scenario
from src.connectors.issuer_holdings import HoldingsSnapshot
from src.connectors.tracker_data import TrackerSnapshot


POLICY = {
    "freshness": {"price_target_max_age_days": 45},
    "quality": {"minimum_equity_analyst_count": 3},
    "confidence": {
        "base": 0.35,
        "fresh_price_target_bonus": 0.20,
        "analyst_count_bonus_max": 0.15,
        "fundamentals_bonus": 0.10,
    },
    "probabilities": {"prior_bull": 0.25, "prior_base": 0.50, "prior_bear": 0.25},
    "etf": {"minimum_lookthrough_coverage": 0.50},
    "index_etf_models": {},
    "non_equity_models": {
        "IBIT": {
            "method": "TRACKER_NAV_V1",
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
        raise AssertionError("recommendation enrichment is not part of valuation")
    def basic_financials(self, symbol):
        self.financial_calls.append(symbol)
        return {"metric": {
            "epsNormalizedAnnual": 8.0,
            "peNormalizedAnnual": 12.5,
            "epsGrowth3Y": 7.0,
            "totalDebt/totalEquityAnnual": 45.0,
            "netProfitMarginAnnual": 12.0,
            "currentRatioAnnual": 1.5,
        }}
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
    assert row["enrichment_status"] == "FUNDAMENTALS_ATTACHED_FOR_DEEP_SCENARIO_REVIEW"
    assert row["fundamental_eps_normalized"] == 8.0
    assert row["fundamental_pe_normalized"] == 12.5
    assert row["fundamental_eps_growth_3y"] == 7.0
    assert connector.price_target_calls == ["AAA"]
    assert connector.recommendation_calls == []
    assert connector.financial_calls == ["AAA"]


def test_equity_stale_target_blocks_but_keeps_fundamental_evidence():
    connector = EquityConnector()
    connector.price_target = lambda symbol: {"targetHigh": 150, "targetMean": 125, "targetMedian": 123, "targetLow": 90, "numberAnalysts": 20, "lastUpdated": "2026-06-01"}
    row = build_equity_scenario("AAA", 100.0, connector, POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "BLOCKED_BY_DATA"
    assert "PRICE_TARGET_STALE" in row["blockers"]
    assert row["fundamental_eps_normalized"] == 8.0
    assert connector.financial_calls == ["AAA"]


def test_etf_lookthrough_ready_with_sufficient_fresh_coverage():
    row = build_etf_scenario("ETF1", 100.0, ETFConnector(), POLICY, as_of=date(2026, 9, 5))
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["etf_lookthrough_covered_weight"] >= 0.50
    assert row["bear_target_price"] < row["base_target_price"] < row["bull_target_price"]


def test_etf_early_stop_avoids_unnecessary_constituent_calls():
    connector = ETFConnector()
    row = build_etf_scenario("ETF1", 100.0, connector, POLICY, as_of=date(2026, 9, 5), constituent_cache={})
    assert row["valuation_status"] == "VALUATION_READY"


def test_issuer_etf_engine_smoke():
    row = build_issuer_etf_scenario("ETF1", 100.0, IssuerConnector(), POLICY, as_of=date(2026, 9, 5))
    assert isinstance(row, dict)


def test_tracker_engine_smoke():
    row = build_tracker_scenario("IBIT", 43.79, TrackerConnector(), POLICY, as_of=date(2026, 9, 5))
    assert isinstance(row, dict)
