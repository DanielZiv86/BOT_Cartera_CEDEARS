from __future__ import annotations

import yaml

from src.orchestration.build_g4_blocker_triage import _load_policy, triage_scenario_review

POLICY_PATH = "config/g4_blocker_triage_policy.yml"


def _policy():
    return _load_policy(POLICY_PATH)


def test_real_policy_file_parses_and_covers_the_expected_buckets():
    raw = yaml.safe_load(open(POLICY_PATH, encoding="utf-8"))
    assert set(raw["buckets"]) == {
        "identity_verification_needed",
        "connector_investigation_needed",
        "sector_classification_needed",
        "insufficient_market_data",
    }
    assert raw["default_bucket"] == "uncatalogued_blocker_needs_triage_update"


def test_clean_run_with_everything_validated_produces_no_triage_rows():
    # Real shape of today's production state (post-ARM fix): every Top-30
    # row scenario_validated=True, g4_blocked_count=0.
    rows = [{"cedear_ticker": t, "scenario_validated": True, "scenario_review_blockers": []} for t in ("NVDA", "AMZN", "GE", "LLY")]
    triaged, summary = triage_scenario_review(rows, _policy())
    assert triaged == [] and summary == {}


def test_arm_pre_fix_identity_gap_routes_to_identity_verification_needed():
    # Real ARM row found 2026-09-14 before the fix (see PR #34): UK-domiciled
    # ADR, no verified ratio on file, numeric ratio already in-band.
    row = {
        "cedear_ticker": "ARM",
        "scenario_validated": False,
        "scenario_review_blockers": ["FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED"],
        "identity_implied_to_market_ratio": 1.0439436584326782,
        "identity_flags": ["ADR_OR_FOREIGN_SHARE_NORMALIZATION_REQUIRED"],
        "identity_adr_ratio_applied": 1.0,
        "identity_adr_ratio_verified": False,
        "issuer_country_normalized": "GB",
        "underlying_market_official": "NASDAQ GS",
    }
    triaged, summary = triage_scenario_review([row], _policy())
    assert summary == {"identity_verification_needed": 1}
    r = triaged[0]
    assert r["cedear_ticker"] == "ARM" and r["buckets"] == ["identity_verification_needed"]
    assert r["diagnostic_context"]["identity_implied_to_market_ratio"] == 1.0439436584326782
    assert r["diagnostic_context"]["issuer_country_normalized"] == "GB"
    assert r["diagnostic_context"]["identity_adr_ratio_verified"] is False
    # Fields belonging to other buckets must not leak into this row's context.
    assert "etf_holdings_age_days" not in r["diagnostic_context"]


def test_vig_pre_fix_etf_holdings_stale_routes_to_connector_investigation_needed():
    # Real VIG row found 2026-09-14 before the Vanguard endpoint fix: stale
    # secondary-source holdings snapshot exceeded the freshness policy.
    row = {
        "cedear_ticker": "VIG",
        "scenario_validated": False,
        "scenario_review_blockers": ["ETF_HOLDINGS_STALE"],
        "etf_holdings_age_days": 76,
        "etf_holdings_max_age_days_applied": 45,
        "etf_holdings_date": "2026-06-30",
        "holdings_provider": "StockAnalysis",
        "holdings_source_tier": "SECONDARY_FALLBACK",
    }
    triaged, summary = triage_scenario_review([row], _policy())
    assert summary == {"connector_investigation_needed": 1}
    r = triaged[0]
    assert r["buckets"] == ["connector_investigation_needed"]
    assert r["diagnostic_context"]["etf_holdings_age_days"] == 76
    assert r["diagnostic_context"]["holdings_provider"] == "StockAnalysis"


def test_insufficient_market_data_routes_to_the_no_action_bucket():
    row = {"cedear_ticker": "NEWCO", "scenario_validated": False, "scenario_review_blockers": ["INSUFFICIENT_ANALYST_COVERAGE"], "analyst_count": 1}
    triaged, summary = triage_scenario_review([row], _policy())
    assert summary == {"insufficient_market_data": 1}
    assert triaged[0]["diagnostic_context"] == {"analyst_count": 1}


def test_unknown_blocker_code_fails_closed_into_default_bucket():
    # A blocker code the taxonomy has never seen must never be silently
    # treated as "no action needed" -- it has to demand explicit attention.
    row = {"cedear_ticker": "MYSTERY", "scenario_validated": False, "scenario_review_blockers": ["SOME_NEW_CODE_NOT_YET_CATALOGUED"]}
    triaged, summary = triage_scenario_review([row], _policy())
    assert summary == {"uncatalogued_blocker_needs_triage_update": 1}
    assert triaged[0]["buckets"] == ["uncatalogued_blocker_needs_triage_update"]


def test_multiple_blockers_on_one_ticker_can_span_multiple_buckets():
    row = {
        "cedear_ticker": "MULTI",
        "scenario_validated": False,
        "scenario_review_blockers": ["FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED", "ETF_HOLDINGS_STALE"],
        "identity_implied_to_market_ratio": 0.9,
        "etf_holdings_age_days": 90,
    }
    triaged, summary = triage_scenario_review([row], _policy())
    assert summary == {"identity_verification_needed": 1, "connector_investigation_needed": 1}
    r = triaged[0]
    assert r["buckets"] == ["connector_investigation_needed", "identity_verification_needed"]
    assert set(r["diagnostic_context"]) >= {"identity_implied_to_market_ratio", "etf_holdings_age_days"}


def test_missing_blockers_list_still_gets_flagged_not_silently_dropped():
    # scenario_validated=False but scenario_review_blockers is empty/missing
    # (shouldn't normally happen, but must never disappear from the triage).
    row = {"cedear_ticker": "GHOST", "scenario_validated": False, "scenario_review_blockers": []}
    triaged, summary = triage_scenario_review([row], _policy())
    assert len(triaged) == 1
    assert triaged[0]["blockers"] == ["SCENARIO_VALIDATION_FAILED_NO_BLOCKER_RECORDED"]
    assert triaged[0]["buckets"] == ["uncatalogued_blocker_needs_triage_update"]
