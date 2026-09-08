from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.ranking import build_ranking
from src.research.screening import build_screening_scores


def integrity_report(ranked: pd.DataFrame, expected_count: int | None = None) -> dict:
    n = len(ranked)
    ranks = pd.to_numeric(ranked["rank"], errors="coerce")
    checks = {
        "universe_count_matches_expected": expected_count is None or n == expected_count,
        "unique_tickers": ranked["cedear_ticker"].nunique() == n,
        "screening_records_complete": ranked["screening_score"].notna().all(),
        "missing_ranks_zero": ranks.notna().all(),
        "duplicate_ranks_zero": not ranks.duplicated().any(),
        "rank_min_is_one": int(ranks.min()) == 1 if n else False,
        "rank_max_matches_universe": int(ranks.max()) == n if n else False,
        "score_range_valid": ranked["screening_score"].between(0, 100).all(),
        "data_quality_complete": ranked["data_quality_score"].notna().all(),
        "scoring_model_complete": ranked["scoring_model_id"].notna().all(),
        "lineage_complete": ranked["lineage_status"].notna().all(),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": {k: bool(v) for k, v in checks.items()},
        "universe_count": n,
        "expected_count": expected_count,
        "coverage_pct": round(ranked["screening_score"].notna().mean() * 100, 2) if n else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Research MVP v1 universal screening")
    parser.add_argument("--universe", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--min-top-data-quality", type=float, default=60.0)
    parser.add_argument("--output-dir", default="data/canonical/research")
    args = parser.parse_args()

    universe = pd.read_parquet(args.universe)
    features = pd.read_parquet(args.features)
    screening, metrics = build_screening_scores(universe, features)
    ranked = build_ranking(screening, args.top_n, args.min_top_data_quality)
    integrity = integrity_report(ranked, args.expected_count)

    metrics.update({
        "top_n_requested": args.top_n,
        "selected_count": int(ranked["selected"].sum()),
        "ranking_count": int(ranked["rank"].notna().sum()),
        "ranking_status": "RANKING_COMPLETE" if integrity["status"] == "PASS" else "RANKING_INVALID",
        "research_integrity_gate": integrity["status"],
        "deployment_ineligible_count": int((~ranked.get("deployment_eligibility", pd.Series(True, index=ranked.index))).sum()),
    })
    reconciliation = {
        "universe_input": len(ranked),
        "scored": int(ranked["screening_score"].notna().sum()),
        "ranked": int(ranked["rank"].notna().sum()),
        "pass": int(ranked["screening_decision"].eq("PASS").sum()),
        "watch": int(ranked["screening_decision"].eq("WATCH").sum()),
        "fail": int(ranked["screening_decision"].eq("FAIL").sum()),
        "top_n": int(ranked["selected"].sum()),
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ranked.to_json(output_dir / "research_screening.json", orient="records", indent=2, force_ascii=False)
    ranked.to_parquet(output_dir / "research_screening.parquet", index=False)
    (output_dir / "research_screening_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output_dir / "research_integrity.json").write_text(json.dumps(integrity, indent=2), encoding="utf-8")
    (output_dir / "research_reconciliation.json").write_text(json.dumps(reconciliation, indent=2), encoding="utf-8")

    print(json.dumps({"metrics": metrics, "integrity": integrity, "reconciliation": reconciliation}, indent=2))
    if integrity["status"] != "PASS":
        raise SystemExit("RESEARCH_INTEGRITY_GATE=FAIL")


if __name__ == "__main__":
    main()
