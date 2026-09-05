from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from src.valuation.g4 import G4Policy, calculate_g4_cash_hurdle
from src.valuation.g4_review import apply_extreme_target_review


def _load_policy(path: str) -> tuple[G4Policy, dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cash = raw.get("cash_hurdle", {})
    risk = raw.get("risk", {})
    penalties = raw.get("penalties", {})
    return G4Policy(
        cash_return_assumption=float(cash.get("cash_return_assumption", 0.0)),
        minimum_excess_return_over_cash=float(cash.get("minimum_excess_return_over_cash", 0.05)),
        capital_preservation_buffer=float(cash.get("capital_preservation_buffer", 0.03)),
        minimum_margin_over_hurdle=float(cash.get("minimum_margin_over_hurdle", 0.02)),
        max_bear_downside=float(risk.get("max_bear_downside", -0.15)),
        candidate_test_weight_nav=float(risk.get("candidate_test_weight_nav", 0.05)),
        max_single_name_weight=float(risk.get("max_single_name_weight", 0.20)),
        soft_single_name_weight=float(risk.get("soft_single_name_weight", 0.12)),
        warning_single_name_weight=float(risk.get("warning_single_name_weight", 0.15)),
        correlation_warning=float(risk.get("correlation_warning", 0.75)),
        uncertainty_penalty_max=float(penalties.get("uncertainty_penalty_max", 0.10)),
        local_warning_penalty=float(penalties.get("local_warning_penalty", 0.02)),
        correlation_penalty_max=float(penalties.get("correlation_penalty_max", 0.03)),
        concentration_penalty_max=float(penalties.get("concentration_penalty_max", 0.03)),
    ), raw


def _load_valuation_inputs(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    if p.suffix.lower() == ".csv":
        return pd.read_csv(p)
    if p.suffix.lower() == ".json":
        return pd.read_json(p)
    raise ValueError(f"Unsupported valuation input format: {p.suffix}")


def _apply_global_governance(metrics: dict) -> dict:
    governed = dict(metrics)
    blocked = int(governed.get("blocked_count", 0) or 0)
    passes = int(governed.get("pass_count", 0) or 0)
    clean_passes = int(governed.get("clean_g4_pass_count", passes) or 0)
    review_required = int(governed.get("extreme_target_review_required_count", 0) or 0)
    total = int(governed.get("ticker_count", 0) or 0)

    if total == 0 or blocked > 0:
        governed["deployment_decision"] = "RESEARCH_BLOCKED"
        governed["ranking_status"] = "PARTIAL_NOT_ACTIONABLE"
    elif clean_passes > 0:
        governed["deployment_decision"] = "ALLOW_NEW_DEPLOYMENT"
        governed["ranking_status"] = "COMPLETE_WITH_REVIEW_FLAGS" if review_required > 0 else "COMPLETE_ACTIONABLE"
    elif passes > 0 and review_required > 0:
        governed["deployment_decision"] = "NO_NEW_DEPLOYMENT_PENDING_TARGET_REVIEW"
        governed["ranking_status"] = "COMPLETE_REVIEW_REQUIRED"
    else:
        governed["deployment_decision"] = "NO_NEW_DEPLOYMENT"
        governed["ranking_status"] = "COMPLETE_ACTIONABLE"
    return governed


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Valuation + G4 Cash Hurdle layer")
    parser.add_argument("--local-market", required=True)
    parser.add_argument("--valuation-inputs", required=True)
    parser.add_argument("--portfolio-fit", required=True)
    parser.add_argument("--positions", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--brokerage-rate", type=float, default=0.006)
    args = parser.parse_args()

    local_market = pd.read_parquet(args.local_market)
    valuation_inputs = _load_valuation_inputs(args.valuation_inputs)
    portfolio_fit = pd.read_parquet(args.portfolio_fit)
    positions = pd.read_parquet(args.positions)
    policy, raw_policy = _load_policy(args.policy)

    result, metrics = calculate_g4_cash_hurdle(
        local_market=local_market,
        valuation_inputs=valuation_inputs,
        portfolio_fit=portfolio_fit,
        positions=positions,
        policy=policy,
        brokerage_rate=args.brokerage_rate,
    )
    result, review_metrics = apply_extreme_target_review(result, valuation_inputs, raw_policy)
    metrics = {**metrics, **review_metrics}
    metrics = _apply_global_governance(metrics)

    if not result.empty and "g4_rank" in result.columns:
        result.loc[result["g4_status"] == "BLOCKED_BY_DATA", "g4_rank"] = pd.NA

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_df = result.copy()
    if "blockers" in json_df.columns:
        json_df["blockers"] = json_df["blockers"].map(lambda x: x if isinstance(x, list) else [])
    if "target_review_flags" in json_df.columns:
        json_df["target_review_flags"] = json_df["target_review_flags"].map(lambda x: x if isinstance(x, list) else [])
    json_df.to_json(out / "g4_cash_hurdle.json", orient="records", indent=2, force_ascii=False)

    parquet = result.copy()
    for col in ("blockers", "target_review_flags"):
        if col in parquet.columns:
            parquet[col] = parquet[col].map(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else x)
    parquet.to_parquet(out / "g4_cash_hurdle.parquet", index=False)

    ranked = result[result["g4_status"] != "BLOCKED_BY_DATA"].copy() if not result.empty else result.copy()
    if not ranked.empty:
        ranked = ranked.sort_values("net_benefit_vs_cash", ascending=False)
    ranked.to_json(out / "g4_ranked_evaluated.json", orient="records", indent=2, force_ascii=False)

    actionable = result[
        (result["g4_status"] == "G4_PASS")
        & (result["target_review_status"] == "ACTIONABLE_IF_GLOBAL_GOVERNANCE_ALLOWS")
    ].copy() if not result.empty else result.copy()
    if not actionable.empty:
        actionable = actionable.sort_values("net_benefit_vs_cash", ascending=False)
    actionable.to_json(out / "g4_ranked_actionable.json", orient="records", indent=2, force_ascii=False)

    manifest = {
        "layer": "Valuation Engine + G4 Cash Hurdle",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": raw_policy.get("methodology_version", "G4-1.0"),
        "policy_file": args.policy,
        "valuation_input_file": args.valuation_inputs,
        "policy": raw_policy,
        "brokerage_rate_per_side": args.brokerage_rate,
        **metrics,
    }
    (out / "g4_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
