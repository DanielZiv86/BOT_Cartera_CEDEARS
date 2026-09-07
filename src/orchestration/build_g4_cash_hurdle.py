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
    cash, risk, penalties = raw.get("cash_hurdle", {}), raw.get("risk", {}), raw.get("penalties", {})
    return G4Policy(
        cash_return_assumption=float(cash.get("cash_return_assumption", 0.0)), minimum_excess_return_over_cash=float(cash.get("minimum_excess_return_over_cash", 0.05)),
        capital_preservation_buffer=float(cash.get("capital_preservation_buffer", 0.03)), minimum_margin_over_hurdle=float(cash.get("minimum_margin_over_hurdle", 0.02)),
        max_bear_downside=float(risk.get("max_bear_downside", -0.15)), candidate_test_weight_nav=float(risk.get("candidate_test_weight_nav", 0.05)),
        max_single_name_weight=float(risk.get("max_single_name_weight", 0.20)), soft_single_name_weight=float(risk.get("soft_single_name_weight", 0.12)),
        warning_single_name_weight=float(risk.get("warning_single_name_weight", 0.15)), correlation_warning=float(risk.get("correlation_warning", 0.75)),
        uncertainty_penalty_max=float(penalties.get("uncertainty_penalty_max", 0.10)), local_warning_penalty=float(penalties.get("local_warning_penalty", 0.02)),
        correlation_penalty_max=float(penalties.get("correlation_penalty_max", 0.03)), concentration_penalty_max=float(penalties.get("concentration_penalty_max", 0.03)),
    ), raw


def _load_valuation_inputs(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() == ".parquet": return pd.read_parquet(p)
    if p.suffix.lower() == ".csv": return pd.read_csv(p)
    if p.suffix.lower() == ".json": return pd.read_json(p)
    raise ValueError(f"Unsupported valuation input format: {p.suffix}")


def _apply_global_governance(metrics: dict) -> dict:
    governed = dict(metrics)
    blocked, passes = int(governed.get("blocked_count", 0) or 0), int(governed.get("pass_count", 0) or 0)
    clean_passes = int(governed.get("clean_g4_pass_count", passes) or 0)
    review_required, total = int(governed.get("extreme_target_review_required_count", 0) or 0), int(governed.get("ticker_count", 0) or 0)
    if total == 0 or blocked > 0:
        governed.update(deployment_decision="RESEARCH_BLOCKED", ranking_status="PARTIAL_NOT_ACTIONABLE")
    elif clean_passes > 0:
        governed.update(deployment_decision="ALLOW_NEW_DEPLOYMENT", ranking_status="COMPLETE_WITH_REVIEW_FLAGS" if review_required > 0 else "COMPLETE_ACTIONABLE")
    elif passes > 0 and review_required > 0:
        governed.update(deployment_decision="NO_NEW_DEPLOYMENT_PENDING_TARGET_REVIEW", ranking_status="COMPLETE_REVIEW_REQUIRED")
    else:
        governed.update(deployment_decision="NO_NEW_DEPLOYMENT", ranking_status="COMPLETE_ACTIONABLE")
    return governed


def _add_execution_gate(result: pd.DataFrame, local_market: pd.DataFrame) -> pd.DataFrame:
    if result.empty: return result
    cols=[c for c in ["cedear_ticker","execution_book_status","executable_buy_ars","ratio_status","ccl_status","market_session_status"] if c in local_market.columns]
    lm=local_market[cols].drop_duplicates("cedear_ticker")
    out=result.merge(lm,on="cedear_ticker",how="left",suffixes=("","_execution"))
    book=out.get("execution_book_status",pd.Series(index=out.index,dtype=object)).eq("BOOK_EXECUTABLE_BY_SANITY")
    buy=pd.to_numeric(out.get("executable_buy_ars"),errors="coerce").gt(0)
    ratio=out.get("ratio_status",pd.Series(index=out.index,dtype=object)).eq("RATIO_VALIDATED_COMAFI")
    ccl=out.get("ccl_status",pd.Series(index=out.index,dtype=object)).isin(["CCL_READY_VALIDATED","CCL_WARNING_MARKET_DEVIATION"])
    out["analysis_ready"]=out["g4_status"].ne("BLOCKED_BY_DATA")
    out["execution_ready"]=out["analysis_ready"] & book & buy & ratio & ccl
    out["execution_gate_status"]="NOT_EXECUTION_READY"
    out.loc[out["execution_ready"],"execution_gate_status"]="EXECUTION_READY"
    return out


def main() -> int:
    parser=argparse.ArgumentParser(description="Build deterministic Valuation + G4 Cash Hurdle layer")
    for arg in ("local-market","valuation-inputs","portfolio-fit","positions","policy","output-dir"): parser.add_argument(f"--{arg}",required=True)
    parser.add_argument("--brokerage-rate",type=float,default=0.006); args=parser.parse_args()
    local_market=pd.read_parquet(args.local_market); valuation_inputs=_load_valuation_inputs(args.valuation_inputs)
    portfolio_fit=pd.read_parquet(args.portfolio_fit); positions=pd.read_parquet(args.positions); policy,raw_policy=_load_policy(args.policy)
    result,metrics=calculate_g4_cash_hurdle(local_market=local_market,valuation_inputs=valuation_inputs,portfolio_fit=portfolio_fit,positions=positions,policy=policy,brokerage_rate=args.brokerage_rate)
    result,review_metrics=apply_extreme_target_review(result,valuation_inputs,raw_policy); result=_add_execution_gate(result,local_market)
    metrics=_apply_global_governance({**metrics,**review_metrics})
    metrics["analysis_ready_count"]=int(result.get("analysis_ready",pd.Series(dtype=bool)).sum())
    metrics["execution_ready_count"]=int(result.get("execution_ready",pd.Series(dtype=bool)).sum())
    if not result.empty and "g4_rank" in result.columns: result.loc[result["g4_status"]=="BLOCKED_BY_DATA","g4_rank"]=pd.NA
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    json_df=result.copy()
    for col in ("blockers","target_review_flags"):
        if col in json_df.columns: json_df[col]=json_df[col].map(lambda x:x if isinstance(x,list) else [])
    json_df.to_json(out/"g4_cash_hurdle.json",orient="records",indent=2,force_ascii=False)
    parquet=result.copy()
    for col in ("blockers","target_review_flags"):
        if col in parquet.columns: parquet[col]=parquet[col].map(lambda x:json.dumps(x,ensure_ascii=False) if isinstance(x,list) else x)
    parquet.to_parquet(out/"g4_cash_hurdle.parquet",index=False)
    ranked=result[result["g4_status"]!="BLOCKED_BY_DATA"].copy() if not result.empty else result.copy()
    if not ranked.empty: ranked=ranked.sort_values("net_benefit_vs_cash",ascending=False)
    ranked.to_json(out/"g4_ranked_evaluated.json",orient="records",indent=2,force_ascii=False)
    actionable=result[(result["g4_status"]=="G4_PASS")&(result["target_review_status"]=="ACTIONABLE_IF_GLOBAL_GOVERNANCE_ALLOWS")&(result["execution_ready"])].copy() if not result.empty else result.copy()
    if not actionable.empty: actionable=actionable.sort_values("net_benefit_vs_cash",ascending=False)
    actionable.to_json(out/"g4_ranked_actionable.json",orient="records",indent=2,force_ascii=False)
    manifest={"layer":"Valuation Engine + G4 Cash Hurdle","created_at":datetime.now(timezone.utc).isoformat(),"policy_file":args.policy,"valuation_input_file":args.valuation_inputs,"policy":raw_policy,"brokerage_rate_per_side":args.brokerage_rate,**metrics,"methodology_version":raw_policy.get("methodology_version","G4-1.0")}
    (out/"g4_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8"); print(json.dumps(manifest,indent=2,ensure_ascii=False)); return 0

if __name__=="__main__": raise SystemExit(main())
