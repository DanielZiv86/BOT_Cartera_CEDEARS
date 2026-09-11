from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.research.ranking import build_value_ranking
from src.research.screening import build_screening_scores
from src.research.value_screening import build_value_scores


def _tickers(df: pd.DataFrame, mask: pd.Series | None = None) -> list[str]:
    frame = df if mask is None else df.loc[mask]
    return sorted(frame["cedear_ticker"].astype(str).str.upper().tolist())


def build_comparison(shadow_ranked: pd.DataFrame, current_topn: pd.DataFrame) -> dict:
    shadow_selected = set(_tickers(shadow_ranked, shadow_ranked["selected"].fillna(False).astype(bool)))
    current_selected = set(_tickers(current_topn, current_topn["selected"].fillna(False).astype(bool)))
    return {
        "shadow_top_n_count": len(shadow_selected),
        "current_top_n_count": len(current_selected),
        "unchanged_count": len(shadow_selected & current_selected),
        "entering_shadow_only": sorted(shadow_selected - current_selected),
        "leaving_current_only": sorted(current_selected - shadow_selected),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="SHADOW ONLY: value-first Top-N research, does not feed production Committee")
    p.add_argument("--universe", required=True, help="cedear_universe_master.parquet, full canonical eligible universe")
    p.add_argument("--features", required=True, help="market_features.parquet, full universe")
    p.add_argument("--valuation", required=True, help="valuation_scenarios.parquet built over the FULL universe (not a pre-selected Top-N)")
    p.add_argument("--current-research", required=True, help="research_screening.parquet from the production technical-only Research run, for comparison")
    p.add_argument("--policy", default="config/value_screening_policy.yml")
    p.add_argument("--output-dir", default="data/canonical/value_research_shadow")
    args = p.parse_args()

    universe = pd.read_parquet(args.universe)
    features = pd.read_parquet(args.features)
    valuation = pd.read_parquet(args.valuation)
    current_research = pd.read_parquet(args.current_research)
    policy = yaml.safe_load(Path(args.policy).read_text(encoding="utf-8")) or {}
    ranking_policy = policy.get("ranking", {}) or {}

    technical, technical_metrics = build_screening_scores(universe, features)
    value, value_metrics = build_value_scores(universe, valuation, policy)
    shadow_ranked, ranking_metrics = build_value_ranking(
        value,
        technical,
        top_n=int(ranking_policy.get("top_n", 30)),
        etf_slots=int(ranking_policy.get("etf_slots", 6)),
        min_timing_gate_score=float(ranking_policy.get("min_timing_gate_score", 45.0)),
        min_technical_data_quality=float(ranking_policy.get("min_technical_data_quality", 60.0)),
        min_value_data_quality=float(policy.get("min_value_data_quality", 50.0)),
    )

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    shadow_ranked.to_parquet(out / "value_research_shadow.parquet", index=False)
    shadow_ranked.to_json(out / "value_research_shadow.json", orient="records", indent=2, force_ascii=False)

    comparison = build_comparison(shadow_ranked, current_research)
    manifest = {
        "layer": "Value-First Research Shadow (Fase 1, audit only)",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "production_decision_authority": False,
        "shadow_only": True,
        "note": "Does not feed production Research, Valuation, G4, Risk or Committee. See plan: value-first Top-30 redesign.",
        "universe_count": int(len(universe)),
        "technical_screening_metrics": technical_metrics,
        "value_screening_metrics": value_metrics,
        "ranking_metrics": ranking_metrics,
        "comparison_vs_current_production_topn": comparison,
    }
    (out / "value_research_shadow_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
