from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.market_data.history_layer import build_underlying_history
from src.universe.loader import load_universe_json
from src.universe.symbol_map import build_symbol_map, load_alias_config


def _current_holding_identity_rows(portfolio: dict, tickers: set[str]) -> pd.DataFrame:
    """Return explicitly identified current holdings embedded in the portfolio snapshot.

    Portfolio market-data identity is deliberately independent from Research eligibility.
    We never infer an underlying for an unresolved holding: the snapshot must carry the
    minimum identity required to obtain foreign-market history.
    """
    rows = []
    for position in portfolio.get("positions", []):
        ticker = str(position.get("cedear_ticker") or "").strip().upper()
        if ticker not in tickers:
            continue
        underlying = str(position.get("underlying_ticker") or "").strip()
        market = str(position.get("underlying_market") or "").strip()
        if not underlying or not market:
            continue
        rows.append({
            "cedear_ticker": ticker,
            "cedear_byma_symbol": str(position.get("cedear_byma_symbol") or ticker).strip().upper(),
            "underlying_ticker": underlying,
            "underlying_market": market,
            "instrument_type": position.get("instrument_type"),
            "ratio": position.get("ratio"),
            "mandate_exception": bool(position.get("mandate_exception", False)),
            "byma_tradable": bool(position.get("byma_tradable", True)),
        })
    return pd.DataFrame(rows)


def augment_symbol_map_with_current_holdings(
    symbol_map: pd.DataFrame,
    portfolio_state_path: str | None,
    universe_input_path: str | None,
    aliases_path: str,
) -> tuple[pd.DataFrame, dict]:
    """Guarantee market-data coverage for current holdings without changing Research eligibility.

    Resolution order for holdings absent from the Research symbol map:
    1. any matching row in the hydrated master universe, including Research-ineligible rows;
    2. explicit market-data identity embedded in the canonical portfolio snapshot.

    Missing identity is a hard failure. This keeps the risk layer fail-closed without
    re-admitting quarantined holdings into Research or guessing provider symbols.
    """
    base = symbol_map.copy()
    if not portfolio_state_path:
        return base, {"current_holding_count": 0, "holding_rows_added": 0, "missing_holdings": []}
    if not universe_input_path:
        raise ValueError("--universe-input is required when --portfolio-state is supplied")

    portfolio = json.loads(Path(portfolio_state_path).read_text(encoding="utf-8"))
    holdings = sorted({
        str(row.get("cedear_ticker") or "").strip().upper()
        for row in portfolio.get("positions", [])
        if float(row.get("weight") or 0.0) > 0 and str(row.get("cedear_ticker") or "").strip()
    })
    existing = set(base["cedear_ticker"].astype(str).str.strip().str.upper())
    missing = [ticker for ticker in holdings if ticker not in existing]
    if not missing:
        return base, {"current_holding_count": len(holdings), "holding_rows_added": 0, "missing_holdings": []}

    payload = load_universe_json(universe_input_path)
    source = pd.DataFrame(payload.get("rows", []))
    if "cedear_ticker" not in source.columns:
        source = pd.DataFrame(columns=["cedear_ticker"])
    source["cedear_ticker"] = source["cedear_ticker"].astype(str).str.strip().str.upper()
    holding_source = source[source["cedear_ticker"].isin(missing)].copy()
    found = set(holding_source["cedear_ticker"])

    unresolved = set(missing) - found
    portfolio_source = _current_holding_identity_rows(portfolio, unresolved)
    if not portfolio_source.empty:
        holding_source = pd.concat([holding_source, portfolio_source], ignore_index=True, sort=False)
        found.update(portfolio_source["cedear_ticker"].astype(str).str.upper())

    unresolved = sorted(set(missing) - found)
    if unresolved:
        raise ValueError(
            "current holdings missing canonical market-data identity: " + ", ".join(unresolved)
        )

    additions = build_symbol_map(holding_source, load_alias_config(aliases_path))
    additions["market_data_scope_reason"] = "CURRENT_PORTFOLIO_HOLDING"
    if "market_data_scope_reason" not in base.columns:
        base["market_data_scope_reason"] = "RESEARCH_ELIGIBLE"
    combined = pd.concat([base, additions], ignore_index=True)
    combined["cedear_ticker"] = combined["cedear_ticker"].astype(str).str.strip().str.upper()
    if combined["cedear_ticker"].duplicated().any():
        duplicates = sorted(combined.loc[combined["cedear_ticker"].duplicated(False), "cedear_ticker"].unique())
        raise ValueError("duplicate symbols after current-holding augmentation: " + ", ".join(duplicates))
    return combined.sort_values("cedear_ticker").reset_index(drop=True), {
        "current_holding_count": len(holdings),
        "holding_rows_added": len(additions),
        "missing_holdings": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical underlying historical price layer")
    parser.add_argument("--symbol-map", required=True)
    parser.add_argument("--portfolio-state")
    parser.add_argument("--universe-input")
    parser.add_argument("--aliases", default="config/symbol_aliases.yml")
    parser.add_argument("--output-dir", default="data/canonical/market_data")
    parser.add_argument("--max-workers", type=int, default=12)
    args = parser.parse_args()

    symbol_map = pd.read_json(args.symbol_map)
    if symbol_map.empty:
        raise SystemExit("security_symbol_map is empty")
    required = {"cedear_ticker", "canonical_underlying", "underlying_market", "yahoo_symbol", "stooq_symbol"}
    missing = sorted(required - set(symbol_map.columns))
    if missing:
        raise SystemExit("security_symbol_map missing columns: " + ", ".join(missing))

    symbol_map, scope_metrics = augment_symbol_map_with_current_holdings(
        symbol_map=symbol_map,
        portfolio_state_path=args.portfolio_state,
        universe_input_path=args.universe_input,
        aliases_path=args.aliases,
    )
    history, status, metrics = build_underlying_history(symbol_map, max_workers=args.max_workers)
    metrics["market_data_scope"] = scope_metrics

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history_parquet = output_dir / "underlying_history.parquet"
    status_json = output_dir / "underlying_history_status.json"
    status_parquet = output_dir / "underlying_history_status.parquet"
    metrics_json = output_dir / "underlying_history_metrics.json"

    history.to_parquet(history_parquet, index=False)
    status.to_json(status_json, orient="records", indent=2, force_ascii=False)
    status.to_parquet(status_parquet, index=False)
    metrics_json.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
