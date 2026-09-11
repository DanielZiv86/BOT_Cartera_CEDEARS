from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> int:
    p = argparse.ArgumentParser(
        description="SHADOW ONLY: slice the broad-universe valuation and the latest local-market "
        "layer down to the value-first shadow Top-30, so the unmodified production "
        "src.orchestration.build_g4_cash_hurdle can be reused as-is against them."
    )
    p.add_argument("--shadow-ranking", required=True, help="value_research_shadow.parquet")
    p.add_argument("--valuation", required=True, help="valuation_scenarios.parquet computed over the full universe (same shadow run)")
    p.add_argument("--universe", required=True, help="cedear_universe_master.parquet, for sector/mandate metadata the deep scenario review needs")
    p.add_argument("--local-market", required=True, help="latest cedear_local_market.parquet")
    p.add_argument("--output-dir", default="data/canonical/value_research_shadow_g4_inputs")
    args = p.parse_args()

    shadow = pd.read_parquet(args.shadow_ranking)
    if "selected" not in shadow.columns:
        raise ValueError("shadow ranking frame missing 'selected' column")
    selected = shadow.loc[shadow["selected"].fillna(False).astype(bool)]
    tickers = sorted(selected["cedear_ticker"].astype(str).str.upper().unique().tolist())
    if len(tickers) != len(selected):
        raise ValueError("duplicate selected tickers in shadow ranking")

    valuation = pd.read_parquet(args.valuation)
    valuation["cedear_ticker"] = valuation["cedear_ticker"].astype(str).str.upper()
    valuation_30 = valuation[valuation["cedear_ticker"].isin(tickers)].drop_duplicates("cedear_ticker", keep="last")

    universe = pd.read_parquet(args.universe)
    universe["cedear_ticker"] = universe["cedear_ticker"].astype(str).str.upper()
    missing_cols = [c for c in universe.columns if c != "cedear_ticker" and c not in valuation_30.columns]
    if missing_cols:
        valuation_30 = valuation_30.merge(universe[["cedear_ticker", *missing_cols]], on="cedear_ticker", how="left", validate="one_to_one")

    local = pd.read_parquet(args.local_market)
    local_ticker_col = "cedear_ticker" if "cedear_ticker" in local.columns else "ticker"
    local[local_ticker_col] = local[local_ticker_col].astype(str).str.upper()
    local_30 = local[local[local_ticker_col].isin(tickers)].drop_duplicates(local_ticker_col, keep="last")
    if local_ticker_col != "cedear_ticker":
        local_30 = local_30.rename(columns={local_ticker_col: "cedear_ticker"})
    # calculate_g4_cash_hurdle iterates local_market as its left side, so a
    # shadow-selected ticker simply absent from it would silently disappear
    # from the result instead of showing up as BLOCKED_BY_DATA. Insert an
    # explicit empty row for any unmatched ticker so it fails closed and
    # visibly, like every other missing-data case in this pipeline.
    unmatched_local = sorted(set(tickers) - set(local_30["cedear_ticker"]))
    if unmatched_local:
        placeholders = pd.DataFrame({"cedear_ticker": unmatched_local})
        local_30 = pd.concat([local_30, placeholders], ignore_index=True)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    valuation_30.to_parquet(out / "valuation_inputs_shadow30.parquet", index=False)
    local_30.to_parquet(out / "local_market_shadow30.parquet", index=False)

    diagnostics = {
        "shadow_selected_count": len(tickers),
        "valuation_matched_count": int(valuation_30["cedear_ticker"].nunique()),
        "valuation_unmatched_tickers": sorted(set(tickers) - set(valuation_30["cedear_ticker"])),
        "local_market_matched_count": len(tickers) - len(unmatched_local),
        "local_market_unmatched_tickers": unmatched_local,
        "note": "A shadow-selected ticker missing from the local-market layer gets an explicit empty placeholder row instead of being silently dropped, so build_g4_cash_hurdle reports it as BLOCKED_BY_DATA (LOCAL_MARKET_GATE_BLOCKED) rather than disappearing from the 30.",
    }
    (out / "shadow_g4_input_diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    print(json.dumps(diagnostics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
