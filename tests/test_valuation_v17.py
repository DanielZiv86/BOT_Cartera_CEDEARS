from __future__ import annotations

from src.connectors.issuer_holdings import HoldingsSnapshot, IssuerHoldingsConnector
from src.orchestration.build_valuation_scenarios import _estimate_etf_plan


POLICY = {
    "quality": {
        "minimum_etf_covered_weight": 0.50,
        "minimum_etf_valid_holdings": 2,
        "maximum_etf_holdings_to_analyze": 10,
        "maximum_direct_constituent_lookups_per_etf": 4,
    }
}


def _ready():
    return {
        "valuation_status": "VALUATION_READY",
        "current_price": 100.0,
        "bull_target_price": 120.0,
        "base_target_price": 110.0,
        "bear_target_price": 90.0,
    }


def test_planner_prioritizes_fund_near_coverage_hurdle():
    snapshot = HoldingsSnapshot(
        ticker="SPY",
        holdings=[
            {"symbol": "AAA", "percent": 30.0},
            {"symbol": "BBB", "percent": 18.0},
            {"symbol": "CCC", "percent": 4.0},
            {"symbol": "DDD", "percent": 3.0},
        ],
        as_of="2026-09-05",
        source_ref="issuer",
        source_tier="ISSUER_OFFICIAL",
        provider="Issuer",
    )
    plan = _estimate_etf_plan(snapshot, {"AAA": _ready(), "BBB": _ready()}, POLICY)
    assert round(plan["cached_weight"], 2) == 0.48
    assert plan["estimated_feasible_within_per_fund_cap"] is True
    assert plan["estimated_lookups_needed"] == 1


def test_planner_marks_expensive_fund_infeasible_within_per_fund_cap():
    snapshot = HoldingsSnapshot(
        ticker="BROAD",
        holdings=[{"symbol": f"X{i}", "percent": 6.0} for i in range(10)],
        as_of="2026-09-05",
        source_ref="issuer",
        source_tier="ISSUER_OFFICIAL",
        provider="Issuer",
    )
    plan = _estimate_etf_plan(snapshot, {}, POLICY)
    assert plan["estimated_feasible_within_per_fund_cap"] is False
    assert plan["estimated_lookups_needed"] == 5


def test_secondary_fallback_inherits_primary_fund_freshness_and_holdings_limit():
    class Connector(IssuerHoldingsConnector):
        def _fetch_source(self, ticker, cfg, tier):
            if tier == "ISSUER_OFFICIAL":
                raise RuntimeError("primary unavailable")
            return HoldingsSnapshot(
                ticker=ticker,
                holdings=[{"symbol": "AAA", "percent": 60.0}],
                as_of="2026-06-30",
                source_ref="secondary",
                source_tier=tier,
                provider="Secondary",
                freshness_max_age_days=int(cfg.get("max_age_days")) if cfg.get("max_age_days") else None,
                max_holdings_to_analyze=int(cfg.get("max_holdings_to_analyze")) if cfg.get("max_holdings_to_analyze") else None,
            )

    connector = Connector({
        "VEA": {
            "primary": {
                "provider": "Vanguard",
                "mode": "html_table",
                "url": "primary",
                "max_age_days": 75,
                "max_holdings_to_analyze": 80,
            },
            "secondary": {
                "provider": "Secondary",
                "mode": "html_table",
                "url": "secondary",
            },
        }
    })
    snapshot = connector.fetch("VEA")
    assert snapshot.source_tier == "SECONDARY_HOLDINGS_FALLBACK"
    assert snapshot.freshness_max_age_days == 75
    assert snapshot.max_holdings_to_analyze == 80
