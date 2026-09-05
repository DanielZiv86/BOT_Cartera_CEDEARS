from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.market_data.history_layer import build_underlying_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical underlying historical price layer")
    parser.add_argument("--symbol-map", required=True)
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

    history, status, metrics = build_underlying_history(symbol_map, max_workers=args.max_workers)

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
