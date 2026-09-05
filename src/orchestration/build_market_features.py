from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.features.market_features import calculate_market_features


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical market feature snapshot")
    parser.add_argument("--history", required=True, help="Path to underlying_history.parquet")
    parser.add_argument("--output-dir", default="data/canonical/features")
    args = parser.parse_args()

    history = pd.read_parquet(args.history)
    features, metrics = calculate_market_features(history)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    features_json = output_dir / "market_features.json"
    features_parquet = output_dir / "market_features.parquet"
    metrics_json = output_dir / "market_feature_metrics.json"

    features.to_json(features_json, orient="records", indent=2, force_ascii=False)
    features.to_parquet(features_parquet, index=False)
    metrics_json.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
