from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from src.research.ranking import build_value_ranking
from src.research.screening import build_screening_scores
from src.research.value_screening import build_value_scores


def _normalize_for_downstream_contract(ranked: pd.DataFrame, technical: pd.DataFrame) -> pd.DataFrame:
    """Coalesce the two-track value-first output into the single rank/
    top_n_eligibility contract valuation_scenarios.yml's certification step
    already expects from a technical-only ranking. rank here is each track's
    own within-track rank (value_rank for equities, technical_rank for ETFs)
    coalesced into one column -- not a single cross-track ordering, since the
    two tracks are never compared against each other. Downstream only uses
    it to sort the *selected* rows before listing tickers, so within-track
    validity (checked separately in integrity_report below) is what matters,
    not global uniqueness."""
    out = ranked.copy()
    out["rank"] = out["value_rank"].combine_first(out["technical_rank"]).astype("Int64")
    out["top_n_eligibility"] = (
        out["equity_top_n_eligibility"].fillna(False).astype(bool)
        | out["etf_top_n_eligibility"].fillna(False).astype(bool)
    )
    lineage_cols = technical[["cedear_ticker", "scoring_model_id", "lineage_status"]]
    out = out.merge(lineage_cols, on="cedear_ticker", how="left", validate="one_to_one")
    return out


def integrity_report(ranked: pd.DataFrame, ranking_metrics: dict, expected_count: int | None = None) -> dict:
    """Value-first equivalent of build_research_screening.integrity_report.

    A single global rank/duplicate check doesn't apply here: equities and
    ETFs are ranked in separate, non-comparable pools (value_score vs
    screening_score), so the coalesced rank column legitimately repeats
    across tracks. Uniqueness/range are instead checked within each track.
    """
    n = len(ranked)
    is_equity = ranked["instrument_class"].eq("EQUITY")
    equity_ranks = pd.to_numeric(ranked.loc[is_equity, "rank"], errors="coerce")
    etf_ranks = pd.to_numeric(ranked.loc[~is_equity, "rank"], errors="coerce")
    equity_n = int(ranking_metrics["equity_candidate_count"])
    etf_n = int(ranking_metrics["etf_candidate_count"])

    def _track_ok(ranks: pd.Series, track_n: int) -> bool:
        return (
            track_n == 0
            or (ranks.notna().all() and not ranks.duplicated().any()
                and int(ranks.min()) == 1 and int(ranks.max()) == track_n)
        )

    checks = {
        "universe_count_matches_expected": expected_count is None or n == expected_count,
        "unique_tickers": ranked["cedear_ticker"].nunique() == n,
        "value_records_complete": ranked.loc[is_equity, "value_score"].notna().all(),
        "screening_records_complete": ranked["screening_score"].notna().all(),
        "missing_ranks_zero": ranked["rank"].notna().all(),
        "equity_track_rank_valid": _track_ok(equity_ranks, equity_n),
        "etf_track_rank_valid": _track_ok(etf_ranks, etf_n),
        "value_score_range_valid": ranked.loc[is_equity, "value_score"].between(0, 100).all(),
        "screening_score_range_valid": ranked["screening_score"].between(0, 100).all(),
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
    parser = argparse.ArgumentParser(description="Build value-first Research Top-N (fundamentals rank equities, technical screening is a binary timing gate)")
    parser.add_argument("--universe", required=True)
    parser.add_argument("--features", required=True)
    parser.add_argument("--valuation", required=True, help="valuation_scenarios.parquet built over the FULL universe (not a pre-selected Top-N)")
    parser.add_argument("--policy", default="config/value_screening_policy.yml")
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--output-dir", default="data/canonical/research")
    args = parser.parse_args()

    universe = pd.read_parquet(args.universe)
    features = pd.read_parquet(args.features)
    valuation = pd.read_parquet(args.valuation)
    policy = yaml.safe_load(Path(args.policy).read_text(encoding="utf-8")) or {}
    ranking_policy = policy.get("ranking", {}) or {}

    technical, technical_metrics = build_screening_scores(universe, features)
    value, value_metrics = build_value_scores(universe, valuation, policy)
    ranked, ranking_metrics = build_value_ranking(
        value,
        technical,
        top_n=args.top_n,
        etf_slots=int(ranking_policy.get("etf_slots", 6)),
        min_timing_gate_score=float(ranking_policy.get("min_timing_gate_score", 45.0)),
        min_technical_data_quality=float(ranking_policy.get("min_technical_data_quality", 60.0)),
        min_value_data_quality=float(policy.get("min_value_data_quality", 50.0)),
    )
    ranked = _normalize_for_downstream_contract(ranked, technical)
    integrity = integrity_report(ranked, ranking_metrics, args.expected_count)

    metrics = {
        "technical_screening_metrics": technical_metrics,
        "value_screening_metrics": value_metrics,
        "ranking_metrics": ranking_metrics,
        "top_n_requested": args.top_n,
        "selected_count": int(ranked["selected"].sum()),
        "ranking_count": int(ranked["rank"].notna().sum()),
        "ranking_status": "RANKING_COMPLETE" if integrity["status"] == "PASS" else "RANKING_INVALID",
        "research_integrity_gate": integrity["status"],
        "deployment_ineligible_count": int((~ranked.get("deployment_eligibility", pd.Series(True, index=ranked.index))).sum()),
    }
    reconciliation = {
        "universe_input": len(ranked),
        "value_scored": int(value["value_score"].notna().sum()),
        "technical_scored": int(technical["screening_score"].notna().sum()),
        "ranked": int(ranked["rank"].notna().sum()),
        "equity_selected": int(ranking_metrics["equity_selected_count"]),
        "etf_selected": int(ranking_metrics["etf_selected_count"]),
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
