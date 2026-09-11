import json

import pandas as pd
import pytest

from src.orchestration.prepare_value_shadow_g4_inputs import main


def _write(path, df):
    df.to_parquet(path, index=False)


def test_slices_to_shadow_top30_and_fails_closed_on_missing_local_market(tmp_path, monkeypatch, capsys):
    shadow = pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "CCC", "DDD"],
        "selected": [True, True, True, False],
    })
    valuation = pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
        "valuation_status": ["VALUATION_READY"] * 5,
    })
    universe = pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
        "industry_sector_official": ["TECH", "TECH", "ENERGY", "FINANCIALS", "TECH"],
    })
    # CCC is missing from the local-market layer entirely.
    local = pd.DataFrame({
        "cedear_ticker": ["AAA", "BBB", "EEE"],
        "valuation_g4_local_gate": ["PASS", "PASS", "PASS"],
    })

    _write(tmp_path / "shadow.parquet", shadow)
    _write(tmp_path / "valuation.parquet", valuation)
    _write(tmp_path / "universe.parquet", universe)
    _write(tmp_path / "local.parquet", local)
    out_dir = tmp_path / "out"

    monkeypatch.setattr("sys.argv", [
        "prepare_value_shadow_g4_inputs",
        "--shadow-ranking", str(tmp_path / "shadow.parquet"),
        "--valuation", str(tmp_path / "valuation.parquet"),
        "--universe", str(tmp_path / "universe.parquet"),
        "--local-market", str(tmp_path / "local.parquet"),
        "--output-dir", str(out_dir),
    ])
    assert main() == 0

    valuation_30 = pd.read_parquet(out_dir / "valuation_inputs_shadow30.parquet")
    assert sorted(valuation_30["cedear_ticker"]) == ["AAA", "BBB", "CCC"]
    assert "industry_sector_official" in valuation_30.columns
    assert valuation_30.set_index("cedear_ticker").loc["CCC", "industry_sector_official"] == "ENERGY"

    local_30 = pd.read_parquet(out_dir / "local_market_shadow30.parquet")
    assert sorted(local_30["cedear_ticker"]) == ["AAA", "BBB", "CCC"]
    ccc_row = local_30.set_index("cedear_ticker").loc["CCC"]
    assert pd.isna(ccc_row["valuation_g4_local_gate"])

    diagnostics = json.loads((out_dir / "shadow_g4_input_diagnostics.json").read_text())
    assert diagnostics["shadow_selected_count"] == 3
    assert diagnostics["local_market_unmatched_tickers"] == ["CCC"]
    assert diagnostics["valuation_unmatched_tickers"] == []

    out = capsys.readouterr().out
    assert "CCC" in out
