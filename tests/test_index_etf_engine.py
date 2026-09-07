from src.valuation.index_etf_engine import build_index_etf_scenario


def _policy():
    return {
        "probabilities": {"prior_bull": .25, "prior_base": .50, "prior_bear": .25},
        "index_etf_models": {"VEA": {"current_pe": 16.6, "dividend_yield": .0239, "base_earnings_growth": .075, "bull_growth": .11, "bear_growth": -.04, "bull_terminal_pe": 17.5, "base_terminal_pe": 16.2, "bear_terminal_pe": 13.5, "confidence": .62, "source_date": "2026-07-31", "source_ref": "Vanguard Advisors VEA fundamentals"}},
    }


def test_vea_index_model_is_ready_and_ordered():
    row = build_index_etf_scenario("VEA", 73.76, _policy())
    assert row["valuation_status"] == "VALUATION_READY"
    assert row["valuation_method"] == "INDEX_ETF_AGGREGATE_FUNDAMENTALS_V1"
    assert row["bear_target_price"] < row["base_target_price"] < row["bull_target_price"]
    assert abs(row["bull_probability"] + row["base_probability"] + row["bear_probability"] - 1.0) < 1e-9
    assert row["valuation_confidence"] == .62


def test_index_model_fails_closed_without_evidence():
    p = _policy(); del p["index_etf_models"]["VEA"]["current_pe"]
    row = build_index_etf_scenario("VEA", 73.76, p)
    assert row["valuation_status"] == "BLOCKED_BY_DATA"
    assert "INDEX_ETF_CURRENT_PE_MISSING" in row["blockers"]
