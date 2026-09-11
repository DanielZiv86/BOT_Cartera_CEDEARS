import pandas as pd

from src.research.ranking import build_value_ranking
from src.research.screening import build_screening_scores
from src.research.value_screening import build_value_scores


def _universe(n_equity=4, n_etf=2):
    tickers = [f"EQ{i}" for i in range(n_equity)] + [f"ET{i}" for i in range(n_etf)]
    types = ["EQUITY"] * n_equity + ["ETF"] * n_etf
    return pd.DataFrame({"cedear_ticker": tickers, "instrument_type": types})


def _valuation_and_features(n_equity=4, n_etf=2, *, timing_bad_for: set[str] = frozenset()):
    tickers = [f"EQ{i}" for i in range(n_equity)] + [f"ET{i}" for i in range(n_etf)]
    types = ["EQUITY"] * n_equity + ["ETF"] * n_etf
    # Descending value quality: EQ0 is the best fundamental case, EQ(n-1) the worst.
    upside = [0.05 * (n_equity - i) for i in range(n_equity)] + [0.0] * n_etf
    current_price = [100.0] * (n_equity + n_etf)
    base_target = [100.0 * (1 + u) for u in upside]
    valuation = pd.DataFrame({
        "cedear_ticker": tickers,
        "valuation_engine_type": types,
        "valuation_status": ["VALUATION_READY"] * (n_equity + n_etf),
        "current_price": current_price,
        "base_target_price": base_target,
        "analyst_count": [10.0] * (n_equity + n_etf),
        "fundamental_pe_normalized": [15.0] * (n_equity + n_etf),
        "fundamental_eps_growth_3y": [0.10] * (n_equity + n_etf),
        "fundamental_roe": [0.15] * (n_equity + n_etf),
        "fundamental_debt_to_equity": [0.5] * (n_equity + n_etf),
    })
    # Every ETF gets a uniformly good technical profile so its own track is
    # easy to fill; timing_bad_for lists tickers that are uniformly bad on
    # every technical component (not just momentum), so their percentile
    # score is decisively low regardless of the rest of the peer set.
    bad = [t in timing_bad_for for t in tickers]
    features = pd.DataFrame({
        "cedear_ticker": tickers,
        "as_of_date": ["2026-09-04"] * (n_equity + n_etf),
        "last_price": [70.0 if b else 120.0 for b in bad],
        "ma200": [100.0] * (n_equity + n_etf),
        "momentum_6m": [-0.50 if b else 0.20 for b in bad],
        "momentum_3m": [-0.50 if b else 0.20 for b in bad],
        "volatility_63d": [0.60 if b else 0.15 for b in bad],
        "max_drawdown": [-0.60 if b else -0.10 for b in bad],
    })
    return valuation, features


def test_equity_track_ranks_by_value_not_by_technical_score():
    universe = _universe()
    valuation, features = _valuation_and_features()
    technical, _ = build_screening_scores(universe, features)
    value, _ = build_value_scores(universe, valuation)
    result, metrics = build_value_ranking(value, technical, top_n=4, etf_slots=2)
    equity_selected = result.loc[(result["selection_track"] == "EQUITY_VALUE"), "cedear_ticker"].tolist()
    # All four equities have identical technical momentum, so if the ranking
    # were technical-driven the selection would be arbitrary; instead it must
    # follow the constructed value ordering EQ0 > EQ1 > EQ2 > EQ3.
    assert equity_selected == ["EQ0", "EQ1"]
    assert metrics["equity_slots"] == 2
    assert metrics["equity_selected_count"] == 2


def test_technical_timing_gate_can_veto_a_fundamentally_top_ranked_equity():
    universe = _universe()
    valuation, features = _valuation_and_features(timing_bad_for={"EQ0"})
    technical, _ = build_screening_scores(universe, features)
    value, _ = build_value_scores(universe, valuation)
    result, metrics = build_value_ranking(value, technical, top_n=4, etf_slots=2, min_timing_gate_score=45.0)
    eq0 = result.loc[result["cedear_ticker"] == "EQ0"].iloc[0]
    assert eq0["value_rank"] == 1
    assert bool(eq0["technical_timing_ok"]) is False
    assert bool(eq0["selected"]) is False
    equity_selected = result.loc[result["selection_track"] == "EQUITY_VALUE", "cedear_ticker"].tolist()
    # EQ0 was the best fundamental case but gets vetoed on timing; EQ1/EQ2 fill instead.
    assert "EQ0" not in equity_selected
    assert equity_selected == ["EQ1", "EQ2"]


def test_etf_track_never_competes_on_value_and_keeps_its_own_slots():
    universe = _universe(n_equity=2, n_etf=2)
    valuation, features = _valuation_and_features(n_equity=2, n_etf=2)
    technical, _ = build_screening_scores(universe, features)
    value, _ = build_value_scores(universe, valuation)
    result, metrics = build_value_ranking(value, technical, top_n=3, etf_slots=1)
    etf_selected = result.loc[result["selection_track"] == "ETF_TECHNICAL", "cedear_ticker"].tolist()
    equity_selected = result.loc[result["selection_track"] == "EQUITY_VALUE", "cedear_ticker"].tolist()
    assert len(etf_selected) == 1 and etf_selected[0].startswith("ET")
    assert len(equity_selected) == 2
    assert metrics["etf_slots"] == 1 and metrics["equity_slots"] == 2


def test_unfilled_equity_slots_are_reported_not_papered_over():
    universe = _universe(n_equity=4, n_etf=2)
    # Every equity fails the timing gate: the equity track cannot fill 3 slots.
    valuation, features = _valuation_and_features(n_equity=4, n_etf=2, timing_bad_for={"EQ0", "EQ1", "EQ2", "EQ3"})
    technical, _ = build_screening_scores(universe, features)
    value, _ = build_value_scores(universe, valuation)
    result, metrics = build_value_ranking(value, technical, top_n=5, etf_slots=2)
    assert metrics["equity_slots"] == 3
    assert metrics["equity_selected_count"] == 0
    assert metrics["equity_slots_unfilled"] == 3
    assert not result.loc[result["instrument_class"] == "EQUITY", "selected"].any()
    # The ETF track is unaffected and still fills its own reserved slots.
    assert metrics["etf_selected_count"] == 2


def test_missing_technical_coverage_for_a_valued_ticker_fails_closed():
    universe = _universe()
    valuation, features = _valuation_and_features()
    technical, _ = build_screening_scores(universe, features)
    value, _ = build_value_scores(universe, valuation)
    technical = technical.loc[technical["cedear_ticker"] != "EQ0"].reset_index(drop=True)
    try:
        build_value_ranking(value, technical, top_n=4, etf_slots=2)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "EQ0" in str(exc)
