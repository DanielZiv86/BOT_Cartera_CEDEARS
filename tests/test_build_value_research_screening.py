import pandas as pd

from src.orchestration.build_value_research_screening import _normalize_for_downstream_contract, integrity_report
from src.research.ranking import build_value_ranking
from src.research.screening import build_screening_scores
from src.research.value_screening import build_value_scores


def _universe(n_equity=4, n_etf=2):
    tickers = [f"EQ{i}" for i in range(n_equity)] + [f"ET{i}" for i in range(n_etf)]
    types = ["EQUITY"] * n_equity + ["ETF"] * n_etf
    return pd.DataFrame({"cedear_ticker": tickers, "instrument_type": types})


def _valuation_and_features(n_equity=4, n_etf=2):
    tickers = [f"EQ{i}" for i in range(n_equity)] + [f"ET{i}" for i in range(n_etf)]
    types = ["EQUITY"] * n_equity + ["ETF"] * n_etf
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
    features = pd.DataFrame({
        "cedear_ticker": tickers,
        "as_of_date": ["2026-09-04"] * (n_equity + n_etf),
        "last_price": [120.0] * (n_equity + n_etf),
        "ma200": [100.0] * (n_equity + n_etf),
        "momentum_6m": [0.20] * (n_equity + n_etf),
        "momentum_3m": [0.20] * (n_equity + n_etf),
        "volatility_63d": [0.15] * (n_equity + n_etf),
        "max_drawdown": [-0.10] * (n_equity + n_etf),
    })
    return valuation, features


def _built(n_equity=4, n_etf=2, top_n=4, etf_slots=2):
    universe = _universe(n_equity, n_etf)
    valuation, features = _valuation_and_features(n_equity, n_etf)
    technical, _ = build_screening_scores(universe, features)
    value, _ = build_value_scores(universe, valuation)
    ranked, metrics = build_value_ranking(value, technical, top_n=top_n, etf_slots=etf_slots)
    return _normalize_for_downstream_contract(ranked, technical), technical, metrics


def test_rank_and_top_n_eligibility_coalesce_both_tracks_with_no_gaps():
    # rank is a coalesce of each track's own within-track rank (value_rank for
    # equities, technical_rank for ETFs) -- not a single cross-track ordering.
    # Downstream (valuation_scenarios.yml) only uses it to order the selected
    # tickers before listing them, so per-track validity is what matters.
    out, _, _ = _built()
    assert out["rank"].notna().all()
    equity_rows = out[out["instrument_class"] == "EQUITY"]
    etf_rows_ranks = out.loc[out["instrument_class"] != "EQUITY", "rank"].astype(int).tolist()
    assert sorted(etf_rows_ranks) == etf_rows_ranks
    equity_rows_ranks = equity_rows["rank"].astype(int).tolist()
    assert sorted(equity_rows_ranks) == equity_rows_ranks
    etf_rows = out[out["instrument_class"] != "EQUITY"]
    assert (equity_rows["top_n_eligibility"] == equity_rows["equity_top_n_eligibility"].fillna(False)).all()
    assert (etf_rows["top_n_eligibility"] == etf_rows["etf_top_n_eligibility"].fillna(False)).all()


def test_lineage_columns_carried_over_from_technical_screening():
    out, technical, _ = _built()
    assert out["scoring_model_id"].notna().all()
    assert out["lineage_status"].notna().all()
    assert set(out["scoring_model_id"]) <= set(technical["scoring_model_id"])


def test_integrity_report_passes_with_complete_data_and_catches_universe_mismatch():
    out, _, metrics = _built(n_equity=4, n_etf=2)
    ok = integrity_report(out, metrics, expected_count=6)
    assert ok["status"] == "PASS", ok["checks"]
    assert ok["universe_count"] == 6 and ok["coverage_pct"] == 100.0
    mismatched = integrity_report(out, metrics, expected_count=99)
    assert mismatched["status"] == "FAIL"
    assert mismatched["checks"]["universe_count_matches_expected"] is False


def test_downstream_certification_contract_columns_present_and_valid():
    # Mirrors the exact assertion valuation_scenarios.yml's certification step
    # makes on a technical-only research_screening.parquet: selected==True
    # rows sorted by rank all have top_n_eligibility==True and cedear_ticker
    # is unique.
    out, _, _ = _built(top_n=4, etf_slots=2)
    selected = out.loc[out["selected"].fillna(False).astype(bool)].sort_values("rank")
    assert len(selected) == 4
    assert selected["top_n_eligibility"].fillna(False).astype(bool).all()
    assert selected["cedear_ticker"].nunique() == 4
