from datetime import date
import json

import pandas as pd
import pytest

from src.market_data.history_layer import _classify_history, _stooq_transport_symbol
from src.orchestration.build_underlying_history import augment_symbol_map_with_current_holdings


def test_stooq_transport_symbol_recognizes_new_york_market():
    assert _stooq_transport_symbol("AAPL", "New York") == "AAPL.US"


def test_history_ready_classification():
    dates = pd.date_range("2025-01-01", periods=220, freq="B").date
    frame = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})
    assert _classify_history(frame) == "HISTORY_READY"


def test_short_history_classification():
    dates = pd.date_range("2026-06-01", periods=40, freq="B").date
    frame = pd.DataFrame({"date": dates, "close": [100.0] * len(dates)})
    assert _classify_history(frame) == "SHORT_HISTORY_BY_AGE"


def _write_aliases(tmp_path):
    aliases_path = tmp_path / "aliases.yml"
    aliases_path.write_text(
        'mapping_version: TEST\nproviders: {}\nmarket_suffixes:\n  stooq:\n    "NYSE ARCA": ".US"\n',
        encoding="utf-8",
    )
    return aliases_path


def test_market_data_scope_includes_current_holding_even_when_not_research_symbol_map(tmp_path):
    symbol_map = pd.DataFrame([{
        "cedear_ticker": "AAA", "canonical_underlying": "AAA", "underlying_market": "NASDAQ",
        "yahoo_symbol": "AAA", "stooq_symbol": "AAA", "cedear_byma_symbol": "AAA",
    }])
    portfolio = {"positions": [{"cedear_ticker": "VIG", "weight": 0.10}]}
    universe = {
        "Universe_Count": 1, "Eligible_Count": 0,
        "rows": [{
            "cedear_ticker": "VIG", "eligible": False, "underlying_ticker": "VIG",
            "underlying_market": "NYSE ARCA", "instrument_type": "ETF", "ratio": 20,
            "cedear_byma_symbol": "VIG",
        }],
    }
    portfolio_path = tmp_path / "portfolio.json"
    universe_path = tmp_path / "universe.json"
    aliases_path = _write_aliases(tmp_path)
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    out, metrics = augment_symbol_map_with_current_holdings(
        symbol_map, str(portfolio_path), str(universe_path), str(aliases_path)
    )
    assert set(out["cedear_ticker"]) == {"AAA", "VIG"}
    vig = out.loc[out["cedear_ticker"] == "VIG"].iloc[0]
    assert vig["yahoo_symbol"] == "VIG"
    assert vig["stooq_symbol"] == "VIG.US"
    assert vig["market_data_scope_reason"] == "CURRENT_PORTFOLIO_HOLDING"
    assert metrics["holding_rows_added"] == 1


def test_market_data_scope_uses_explicit_portfolio_identity_when_holding_absent_from_universe(tmp_path):
    symbol_map = pd.DataFrame([{
        "cedear_ticker": "AAA", "canonical_underlying": "AAA", "underlying_market": "NASDAQ",
        "yahoo_symbol": "AAA", "stooq_symbol": "AAA", "cedear_byma_symbol": "AAA",
    }])
    portfolio = {"positions": [{
        "cedear_ticker": "VIG", "weight": 0.10, "underlying_ticker": "VIG",
        "underlying_market": "NYSE ARCA", "instrument_type": "ETF tradicional",
        "cedear_byma_symbol": "VIG",
    }]}
    universe = {"Universe_Count": 0, "Eligible_Count": 0, "rows": []}
    portfolio_path = tmp_path / "portfolio.json"
    universe_path = tmp_path / "universe.json"
    aliases_path = _write_aliases(tmp_path)
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    out, metrics = augment_symbol_map_with_current_holdings(
        symbol_map, str(portfolio_path), str(universe_path), str(aliases_path)
    )
    vig = out.loc[out["cedear_ticker"] == "VIG"].iloc[0]
    assert vig["canonical_underlying"] == "VIG"
    assert vig["stooq_symbol"] == "VIG.US"
    assert metrics["holding_rows_added"] == 1


def test_market_data_scope_fails_closed_when_holding_identity_is_unknown(tmp_path):
    symbol_map = pd.DataFrame([{
        "cedear_ticker": "AAA", "canonical_underlying": "AAA", "underlying_market": "NASDAQ",
        "yahoo_symbol": "AAA", "stooq_symbol": "AAA", "cedear_byma_symbol": "AAA",
    }])
    portfolio = {"positions": [{"cedear_ticker": "UNKNOWN", "weight": 0.10}]}
    universe = {"Universe_Count": 0, "Eligible_Count": 0, "rows": []}
    portfolio_path = tmp_path / "portfolio.json"
    universe_path = tmp_path / "universe.json"
    aliases_path = _write_aliases(tmp_path)
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")
    universe_path.write_text(json.dumps(universe), encoding="utf-8")

    with pytest.raises(ValueError, match="missing canonical market-data identity: UNKNOWN"):
        augment_symbol_map_with_current_holdings(
            symbol_map, str(portfolio_path), str(universe_path), str(aliases_path)
        )
