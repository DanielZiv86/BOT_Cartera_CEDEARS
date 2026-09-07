from datetime import date

from src.connectors.issuer_holdings import HoldingsSnapshot
from src.valuation.etf_issuer_engine import build_issuer_etf_scenario


POLICY = {
    "freshness": {"price_target_max_age_days": 45, "etf_holdings_max_age_days": 75},
    "quality": {
        "minimum_equity_analyst_count": 3,
        "minimum_etf_covered_weight": 0.50,
        "minimum_etf_valid_holdings": 5,
        "maximum_etf_holdings_to_analyze": 10,
        "maximum_direct_constituent_lookups_per_etf": 0,
    },
    "probabilities": {"prior_bull": 0.25, "prior_base": 0.50, "prior_bear": 0.25},
    "confidence": {"base": 0.35, "fresh_price_target_bonus": 0.20, "analyst_count_bonus_max": 0.15},
    "instrument_overrides": {"non_equity_trackers": []},
}


class BroadIssuer:
    def fetch(self, symbol):
        return HoldingsSnapshot(
            ticker=symbol,
            holdings=[{"symbol": f"INTL{i}", "percent": 1.0} for i in range(10)],
            as_of="2026-09-01",
            source_ref="https://issuer.example/broad-etf",
            source_tier="ISSUER_OFFICIAL",
            provider="Issuer",
        )
    def retrieved_at(self):
        return "2026-09-07T00:00:00+00:00"


class AggregateConsensus:
    def price_target(self, symbol):
        assert symbol == "BROAD"
        return {"targetHigh": 120, "targetMean": 108, "targetMedian": 107, "targetLow": 88, "numberAnalysts": 8, "lastUpdated": "2026-09-05"}
    def retrieved_at(self):
        return "2026-09-07T00:00:00+00:00"


def test_broad_etf_uses_fresh_aggregate_consensus_without_relaxing_lookthrough_gate():
    row = build_issuer_etf_scenario("BROAD", 100.0, AggregateConsensus(), BroadIssuer(), POLICY, as_of=date(2026, 9, 7), constituent_cache={}, direct_lookup_budget={"remaining": 0})
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["valuation_method"] == "ETF_AGGREGATE_ANALYST_CONSENSUS_FALLBACK_V1"
    assert row["etf_lookthrough_covered_weight"] < 0.50
    assert row["lookthrough_status"] == "INSUFFICIENT_FOR_PRIMARY_METHOD"
    assert "ETF_LOOKTHROUGH_COVERAGE_INSUFFICIENT" in row["lookthrough_blockers"]
    assert row["bear_target_price"] < row["base_target_price"] < row["bull_target_price"]
    assert abs(row["bull_probability"] + row["base_probability"] + row["bear_probability"] - 1.0) < 1e-9


class NoAggregateConsensus(AggregateConsensus):
    def price_target(self, symbol):
        return {"targetHigh": 0, "targetMean": 0, "targetLow": 0, "numberAnalysts": 0, "lastUpdated": None}


def test_broad_etf_remains_blocked_when_no_independent_aggregate_evidence_exists():
    row = build_issuer_etf_scenario("BROAD", 100.0, NoAggregateConsensus(), BroadIssuer(), POLICY, as_of=date(2026, 9, 7), constituent_cache={}, direct_lookup_budget={"remaining": 0})
    assert row["valuation_status"] == "BLOCKED_BY_DATA"
    assert row["valuation_method"] == "ISSUER_HOLDINGS_LOOKTHROUGH_V1"
    assert "ETF_LOOKTHROUGH_COVERAGE_INSUFFICIENT" in row["blockers"]
