import pandas as pd

from src.orchestration.build_research_screening import integrity_report
from src.research.ranking import build_ranking
from src.research.screening import build_screening_scores


def _universe():
    return pd.DataFrame({"cedear_ticker": ["AAA", "BBB", "CCC", "DDD"], "instrument_type": ["EQUITY", "EQUITY", "ETF", "EQUITY"]})


def _features():
    return pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "CCC", "DDD"],
        "as_of_date": ["2026-09-04"] * 4,
        "last_price": [120.0, 110.0, 90.0, 100.0],
        "ma200": [100.0, 100.0, 100.0, None],
        "momentum_6m": [0.30, 0.15, -0.05, None],
        "momentum_3m": [0.20, 0.10, -0.02, None],
        "volatility_63d": [0.15, 0.25, 0.35, None],
        "max_drawdown": [-0.10, -0.20, -0.30, None],
    })


def test_missing_data_does_not_destroy_universal_coverage():
    screening, metrics = build_screening_scores(_universe(), _features())
    assert len(screening) == 4
    assert metrics["score_ready_count"] == 4
    assert metrics["score_ready_pct"] == 100.0
    ddd = screening.loc[screening["cedear_ticker"] == "DDD"].iloc[0]
    assert ddd["screening_status"] == "SCORE_READY"
    assert pd.notna(ddd["screening_score"])
    assert ddd["data_quality_score"] == 0.0
    assert ddd["uncertainty_penalty"] == 20.0
    assert "momentum_6m" in ddd["missing_components"]


def test_complete_deterministic_ranking_and_quality_floor():
    screening, _ = build_screening_scores(_universe(), _features())
    ranked = build_ranking(screening, top_n=2, min_top_data_quality=60)
    assert ranked["rank"].tolist() == [1, 2, 3, 4]
    assert ranked["rank"].nunique() == 4
    assert ranked["selected"].sum() == 2
    assert not bool(ranked.loc[ranked["cedear_ticker"] == "DDD", "selected"].iloc[0])


def test_integrity_gate_requires_exact_expected_count():
    screening, _ = build_screening_scores(_universe(), _features())
    ranked = build_ranking(screening, top_n=2)
    assert integrity_report(ranked, expected_count=4)["status"] == "PASS"
    assert integrity_report(ranked, expected_count=316)["status"] == "FAIL"


def test_equal_inputs_use_ticker_as_stable_tiebreaker():
    universe = pd.DataFrame({"cedear_ticker": ["BBB", "AAA"]})
    features = pd.DataFrame({
        "cedear_ticker": ["BBB", "AAA"], "last_price": [110, 110], "ma200": [100, 100],
        "momentum_6m": [0.1, 0.1], "momentum_3m": [0.1, 0.1],
        "volatility_63d": [0.2, 0.2], "max_drawdown": [-0.2, -0.2],
    })
    screening, _ = build_screening_scores(universe, features)
    ranked = build_ranking(screening, top_n=1)
    assert ranked.iloc[0]["cedear_ticker"] == "AAA"
