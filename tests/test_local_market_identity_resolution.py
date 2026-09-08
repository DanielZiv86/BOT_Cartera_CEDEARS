import pandas as pd

from src.orchestration.build_cedear_local_market import _identity_candidates, _lookup_panel


def test_canonical_identity_is_preferred_over_legacy():
    row = pd.Series({"cedear_ticker": "RDS", "legacy_cedear_ticker": "SHEL"})
    assert _identity_candidates(row) == ["RDS", "SHEL"]
    value, symbol = _lookup_panel({"RDS": {"v": 1}, "SHEL": {"v": 2}}, _identity_candidates(row))
    assert symbol == "RDS"
    assert value["v"] == 1


def test_legacy_identity_recovers_market_data_without_changing_canonical_ticker():
    row = pd.Series({"cedear_ticker": "RDS", "legacy_cedear_ticker": "SHEL"})
    value, symbol = _lookup_panel({"SHEL": {"last_price_ars": 123.0}}, _identity_candidates(row))
    assert symbol == "SHEL"
    assert value["last_price_ars"] == 123.0


def test_missing_legacy_value_does_not_create_fake_alias():
    row = pd.Series({"cedear_ticker": "AAA", "legacy_cedear_ticker": None})
    assert _identity_candidates(row) == ["AAA"]
