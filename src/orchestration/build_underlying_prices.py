from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.connectors.stooq import StooqPriceConnector
from src.connectors.yahoo import YahooPriceConnector
from src.market_data.underlying_prices import acquire_underlying_prices, build_price_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build canonical underlying price layer")
    parser.add_argument("--symbol-map", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol_map_path = Path(args.symbol_map)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not symbol_map_path.exists():
        raise SystemExit(f"Missing symbol map: {symbol_map_path}")

    symbol_map = pd.read_json(symbol_map_path)
    required = {
        "cedear_ticker",
        "canonical_underlying",
        "underlying_market",
        "mapping_status",
        "yahoo_symbol",
        "stooq_symbol",
    }
    missing = sorted(required.difference(symbol_map.columns))
    if missing:
        raise SystemExit(f"Symbol map missing required columns: {missing}")

    unresolved = symbol_map[symbol_map["mapping_status"] != "RESOLVED"]
    if not unresolved.empty:
        raise SystemExit(f"Symbol map contains {len(unresolved)} unresolved mappings")

    connectors = [YahooPriceConnector(), StooqPriceConnector()]
    prices = acquire_underlying_prices(symbol_map, connectors)
    metrics = build_price_metrics(prices)

    json_path = output_dir / "underlying_prices.json"
    parquet_path = output_dir / "underlying_prices.parquet"
    metrics_path = output_dir / "underlying_price_metrics.json"

    prices.to_json(json_path, orient="records", indent=2, force_ascii=False)
    prices_for_parquet = prices.copy()
    prices_for_parquet["attempt_log"] = prices_for_parquet["attempt_log"].map(
        lambda value: json.dumps(value, ensure_ascii=False)
    )
    prices_for_parquet.to_parquet(parquet_path, index=False)

    manifest = {
        "layer": "Underlying Price Layer",
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol_map_source": str(symbol_map_path),
        "provider_order": [connector.name for connector in connectors],
        **metrics,
    }
    metrics_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if metrics["Underlying_Price_Total_Ready_Count"] == 0:
        raise SystemExit("No underlying prices could be acquired from configured providers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
