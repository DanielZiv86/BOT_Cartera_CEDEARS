from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.ranking import build_ranking
from src.research.screening import build_screening_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Build minimal Research MVP screening + ranking + Top-N")
    parser.add_argument("--universe", required=True, help="Path to cedear_universe_master.parquet")
    parser.add_argument("--features", required=True, help="Path to market_features.parquet")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--output-dir", default="data/canonical/research")
    args = parser.parse_args()

    universe = pd.read_parquet(args.universe)
    features = pd.read_parquet(args.features)

    screening, metrics = build_screening_scores(universe, features)
    ranked = build_ranking(screening, top_n=args.top_n)

    metrics["top_n_requested"] = int(args.top_n)
    metrics["selected_count"] = int(ranked["selected"].sum())
    metrics["ranking_status"] = (
        "RANKING_COMPLETE" if metrics["blocked_by_data_count"] == 0 else "RANKING_PARTIAL_BLOCKED_BY_DATA"
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "research_screening.json"
    parquet_path = output_dir / "research_screening.parquet"
    metrics_path = output_dir / "research_screening_metrics.json"

    ranked.to_json(json_path, orient="records", indent=2, force_ascii=False)
    ranked.to_parquet(parquet_path, index=False)
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print("\nTop candidates:")
    print(
        ranked.loc[ranked["selected"], ["cedear_ticker", "screening_score", "rank"]]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
