from src.orchestration.build_valuation_scenarios import _issuer_source_symbol


def test_cedear_fund_identity_wins_over_provider_underlying_alias():
    sources = {"IWDA": {"primary": {}}, "SPY": {"primary": {}}}
    assert _issuer_source_symbol("IWDA", "IWDA LN", sources) == "IWDA"


def test_underlying_identity_is_valid_fallback_when_ce_dear_key_absent():
    sources = {"SPY": {"primary": {}}}
    assert _issuer_source_symbol("SPYAR", "SPY", sources) == "SPY"


def test_missing_source_returns_canonical_identity_for_auditable_blocker():
    assert _issuer_source_symbol("UNKNOWN", "UNKNOWN US", {}) == "UNKNOWN"
