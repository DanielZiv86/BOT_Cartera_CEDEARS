from src.universe.symbol_map import build_symbol_map, load_alias_config

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
