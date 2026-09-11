import pandas as pd

from src.research.value_screening import build_value_scores


def _universe():
    return pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "CCC", "DDD"],
        "instrument_type": ["EQUITY", "EQUITY", "ETF", "EQUITY"],
        "industry_sector_official": ["Technology", "Consumer Discretionary", "Multi-Sector", ""],
    })


def _valuation():
    return pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "CCC", "DDD"],
        "valuation_engine_type": ["EQUITY", "EQUITY", "ETF", "EQUITY"],
        "valuation_status": ["VALUATION_READY", "VALUATION_READY", "VALUATION_READY", "BLOCKED_BY_DATA"],
        "current_price": [100.0, 100.0, 50.0, 80.0],
        "base_target_price": [130.0, 105.0, 55.0, None],
        "analyst_count": [12.0, 5.0, None, None],
        "fundamental_pe_normalized": [18.0, 24.0, None, None],
        "fundamental_eps_growth_3y": [0.15, 0.03, None, None],
        "fundamental_roe": [0.20, 0.08, None, None],
        "fundamental_debt_to_equity": [0.40, 1.10, None, None],
        "fundamental_market_cap_usd": [2_000_000_000_000.0, 50_000_000_000.0, None, None],
    })


def test_full_universe_coverage_and_cheap_high_quality_ticker_scores_highest():
    screening, metrics = build_value_scores(_universe(), _valuation())
    assert len(screening) == 4
    assert metrics["equity_ticker_count"] == 3
    assert metrics["non_equity_ticker_count"] == 1
    aaa = screening.loc[screening["cedear_ticker"] == "AAA"].iloc[0]
    bbb = screening.loc[screening["cedear_ticker"] == "BBB"].iloc[0]
    # AAA: bigger consensus upside, lower PE, higher growth, higher ROE, lower leverage than BBB.
    assert aaa["value_score"] > bbb["value_score"]


def test_missing_fundamentals_get_neutral_contribution_plus_uncertainty_penalty():
    screening, _ = build_value_scores(_universe(), _valuation())
    ddd = screening.loc[screening["cedear_ticker"] == "DDD"].iloc[0]
    assert ddd["value_screening_status"] == "SCORE_READY"
    assert pd.notna(ddd["value_score"])
    assert ddd["value_data_quality_score"] == 0.0
    assert ddd["value_uncertainty_penalty"] == 20.0
    assert "consensus_upside_to_base" in ddd["missing_value_components"]


def test_non_equity_never_competes_on_value():
    screening, _ = build_value_scores(_universe(), _valuation())
    ccc = screening.loc[screening["cedear_ticker"] == "CCC"].iloc[0]
    assert ccc["instrument_class"] == "ETF"
    assert bool(ccc["value_screening_applicable"]) is False
    assert ccc["value_data_quality_score"] == 0.0
    assert "consensus_upside_to_base" in ccc["missing_value_components"]


def test_component_weights_are_read_from_policy():
    policy = {"components": {"consensus_upside_to_base": {"higher_is_better": True, "weight": 1.0}}}
    screening, metrics = build_value_scores(_universe(), _valuation(), policy)
    assert metrics["components"] == ["consensus_upside_to_base"]
    aaa = screening.loc[screening["cedear_ticker"] == "AAA"].iloc[0]
    bbb = screening.loc[screening["cedear_ticker"] == "BBB"].iloc[0]
    # AAA has 30% upside vs BBB's 5%, and with a single component the percentile
    # ranking directly reflects that ordering.
    assert aaa["value_score"] > bbb["value_score"]


def test_megacap_tech_tilt_ranks_larger_tech_name_above_an_otherwise_identical_smaller_non_tech_peer():
    universe = pd.DataFrame({
        "cedear_ticker": ["MEGA", "SMALL"],
        "instrument_type": ["EQUITY", "EQUITY"],
        "industry_sector_official": ["Technology", "Industrials"],
    })
    valuation = pd.DataFrame({
        "cedear_ticker": ["MEGA", "SMALL"],
        "valuation_engine_type": ["EQUITY", "EQUITY"],
        "valuation_status": ["VALUATION_READY", "VALUATION_READY"],
        "current_price": [100.0, 100.0],
        "base_target_price": [115.0, 115.0],
        "fundamental_pe_normalized": [20.0, 20.0],
        "fundamental_eps_growth_3y": [0.10, 0.10],
        "fundamental_roe": [0.15, 0.15],
        "fundamental_debt_to_equity": [0.5, 0.5],
        "fundamental_market_cap_usd": [1_500_000_000_000.0, 2_000_000_000.0],
    })
    screening, _ = build_value_scores(universe, valuation)
    mega = screening.loc[screening["cedear_ticker"] == "MEGA"].iloc[0]
    small = screening.loc[screening["cedear_ticker"] == "SMALL"].iloc[0]
    # Every other fundamental is identical -- only market cap and sector differ.
    assert mega["value_score"] > small["value_score"]
    assert mega["state_value_fundamental_market_cap_usd"] == "OBSERVED"
    assert mega["state_value_sector_tech_affinity"] == "OBSERVED"
    assert mega["score_value_sector_tech_affinity"] == 1.0
    assert small["score_value_sector_tech_affinity"] == 0.0


def test_missing_sector_classification_gets_neutral_tech_affinity_score():
    universe = pd.DataFrame({
        "cedear_ticker": ["UNK"],
        "instrument_type": ["EQUITY"],
        "industry_sector_official": [""],
    })
    valuation = pd.DataFrame({
        "cedear_ticker": ["UNK"],
        "valuation_engine_type": ["EQUITY"],
        "valuation_status": ["VALUATION_READY"],
        "current_price": [100.0],
        "base_target_price": [110.0],
    })
    screening, _ = build_value_scores(universe, valuation)
    row = screening.iloc[0]
    assert row["state_value_sector_tech_affinity"] == "UNAVAILABLE"
    assert row["score_value_sector_tech_affinity"] == 0.50
    assert "sector_tech_affinity" in row["missing_value_components"]


def test_duplicate_canonical_ticker_is_rejected():
    universe = pd.DataFrame({"cedear_ticker": ["AAA", "AAA"]})
    try:
        build_value_scores(universe, _valuation())
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "duplicate" in str(exc)
