import pandas as pd

from src.research.ranking import build_ranking
from src.research.screening import build_screening_scores


def _universe() -> pd.DataFrame:
    return pd.DataFrame({"cedear_ticker": ["AAA", "BBB", "CCC", "DDD"]})


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cedear_ticker": ["AAA", "BBB", "CCC", "DDD"],
            "as_of_date": ["2026-09-04"] * 4,
            "feature_status": ["FEATURES_READY", "FEATURES_READY", "FEATURES_READY", "FEATURES_PARTIAL"],
            "last_price": [120.0, 110.0, 90.0, 100.0],
            "ma200": [100.0, 100.0, 100.0, None],
            "momentum_6m": [0.30, 0.15, -0.05, None],
            "volatility_63d": [0.15, 0.25, 0.35, None],
        }
    )


def test_screening_covers_full_universe_and_blocks_missing_data():
    screening, metrics = build_screening_scores(_universe(), _features())

    assert len(screening) == 4
    assert metrics["ticker_count"] == 4
    assert metrics["score_ready_count"] == 3
    assert metrics["blocked_by_data_count"] == 1
    assert metrics["pass_screening"] is False

    blocked = screening.loc[screening["cedear_ticker"] == "DDD"].iloc[0]
    assert blocked["screening_status"] == "BLOCKED_BY_DATA"
    assert pd.isna(blocked["screening_score"])


def test_ranking_is_deterministic_and_only_selects_score_ready():
    screening, _ = build_screening_scores(_universe(), _features())
    ranked = build_ranking(screening, top_n=2)

    selected = ranked.loc[ranked["selected"], "cedear_ticker"].tolist()
    assert selected == ["AAA", "BBB"]

    aaa = ranked.loc[ranked["cedear_ticker"] == "AAA"].iloc[0]
    ddd = ranked.loc[ranked["cedear_ticker"] == "DDD"].iloc[0]
    assert aaa["rank"] == 1
    assert pd.isna(ddd["rank"])
    assert bool(ddd["selected"]) is False


def test_equal_inputs_use_ticker_as_stable_tiebreaker():
    universe = pd.DataFrame({"cedear_ticker": ["BBB", "AAA"]})
    features = pd.DataFrame(
        {
            "cedear_ticker": ["BBB", "AAA"],
            "last_price": [110.0, 110.0],
            "ma200": [100.0, 100.0],
            "momentum_6m": [0.10, 0.10],
            "volatility_63d": [0.20, 0.20],
        }
    )
    screening, _ = build_screening_scores(universe, features)
    ranked = build_ranking(screening, top_n=1)

    assert ranked.iloc[0]["cedear_ticker"] == "AAA"
    assert ranked.iloc[0]["rank"] == 1
    assert bool(ranked.iloc[0]["selected"]) is True
