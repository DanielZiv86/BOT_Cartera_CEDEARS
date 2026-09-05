from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.risk.risk_engine import calculate_risk_and_correlations


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cross-sectional Risk and Correlation Engine")
    parser.add_argument("--history", required=True)
    parser.add_argument("--output-dir", default="data/canonical/risk")
    parser.add_argument("--benchmark", default="SPY")
    args = parser.parse_args()

    history = pd.read_parquet(args.history)
    risk, corr, rolling, metrics = calculate_risk_and_correlations(history, benchmark_ticker=args.benchmark)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    risk.to_json(output / "risk_metrics.json", orient="records", indent=2, force_ascii=False)
    risk.to_parquet(output / "risk_metrics.parquet", index=False)
    corr.to_parquet(output / "correlation_matrix_long.parquet", index=False)
    rolling.to_parquet(output / "rolling_correlations.parquet", index=False)
    (output / "risk_engine_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
