from src.universe.symbol_map import build_symbol_map, load_alias_config

import numpy as np
import pandas as pd


def test_iwda_ln_maps_to_real_london_market_symbols():
    aliases = load_alias_config("config/symbol_aliases.yml")
    universe = pd.DataFrame([
        {
            "cedear_ticker": "IWDA",
            "cedear_byma_symbol": "IWDA",
            "legacy_cedear_ticker": "IWDA",
            "underlying_ticker": "IWDA LN",
            "underlying_market": "EUROCLEAR",
            "instrument_type": "ETF Share",
            "ratio": 24,
            "mandate_exception": True,
            "byma_tradable": False,
        }
    ])

    row = build_symbol_map(universe, aliases).iloc[0]

    assert row["cedear_ticker"] == "IWDA"
    assert row["canonical_underlying"] == "IWDA LN"
    assert row["yahoo_symbol"] == "IWDA.L"
    assert row["stooq_symbol"] == "IWDA.UK"
    assert row["iol_symbol"] == "IWDA"
    assert row["data912_symbol"] == "IWDA"
    assert bool(row["mandate_exception"]) is True


def test_unresolved_byma_symbol_falls_back_to_cedear_ticker_not_literal_nan():
    # `... or row["cedear_ticker"]` treats a pandas NaN as truthy (Python's `or`
    # doesn't know NaN means "missing"), so an unresolved BYMA symbol used to
    # collapse every such row to the literal string "NAN" instead of falling
    # back to the real ticker. Reproduces the exact shape build_universe.py
    # produces for a mandate-exception ticker with no BYMA-confirmed symbol
    # (cedear_byma_symbol left as float NaN, not None or "").
    aliases = load_alias_config("config/symbol_aliases.yml")
    universe = pd.DataFrame([{
        "cedear_ticker": "VIG", "cedear_byma_symbol": np.nan, "legacy_cedear_ticker": "VIG",
        "underlying_ticker": "VIG", "underlying_market": "NYSE ARCA", "instrument_type": "ETF Share",
        "ratio": 39, "mandate_exception": True, "byma_tradable": False,
    }])
    row = build_symbol_map(universe, aliases).iloc[0]
    assert row["cedear_ticker"] == "VIG"
    assert row["cedear_byma_symbol"] == "VIG"


def test_two_unresolved_byma_symbols_do_not_collapse_into_the_same_value():
    # The real-world failure this bug caused (found 2026-09-14, adding SPCX as
    # a second mandate-exception ticker with no BYMA symbol): with the old
    # `or`-on-NaN bug, both rows collapsed to "NAN" and looked like duplicate
    # tickers to any downstream duplicate check, even though they're two
    # genuinely different, real securities.
    aliases = load_alias_config("config/symbol_aliases.yml")
    universe = pd.DataFrame([
        {"cedear_ticker": "VIG", "cedear_byma_symbol": np.nan, "legacy_cedear_ticker": "VIG",
         "underlying_ticker": "VIG", "underlying_market": "NYSE ARCA", "instrument_type": "ETF Share",
         "ratio": 39, "mandate_exception": True, "byma_tradable": False},
        {"cedear_ticker": "SPCX", "cedear_byma_symbol": np.nan, "legacy_cedear_ticker": "SPCX",
         "underlying_ticker": "SPCX", "underlying_market": "NASDAQ GS", "instrument_type": "Acción",
         "ratio": 50, "mandate_exception": True, "byma_tradable": False},
    ])
    mapped = build_symbol_map(universe, aliases)
    assert sorted(mapped["cedear_ticker"]) == ["SPCX", "VIG"]
    assert not mapped["cedear_ticker"].duplicated().any()
