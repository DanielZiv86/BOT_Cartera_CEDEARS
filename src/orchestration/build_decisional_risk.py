from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# A COMPLETE_WITH_REVIEW_FLAGS G4 ranking is still globally complete: all 30
# candidates were evaluated and none was blocked. Review-flagged candidates are
# kept out of G4's actionable set; Risk must not turn those isolated review
# flags into a global veto when clean actionable candidates remain.
RISK_ACCEPTED_G4_RANKING_STATUSES = {
    "COMPLETE_ACTIONABLE",
    "COMPLETE_WITH_REVIEW_FLAGS",
}


def g4_ranking_is_risk_acceptable(manifest: dict) -> bool:
    return (
        manifest.get("ticker_count") == 30
        and manifest.get("evaluated_count") == 30
        and manifest.get("blocked_count") == 0
        and manifest.get("ranking_status") in RISK_ACCEPTED_G4_RANKING_STATUSES
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Build fail-closed decisional Risk gate from exact G4 lineage")
    p.add_argument("--g4-dir", required=True)
    p.add_argument("--portfolio-dir", required=True)
    p.add_argument("--output-dir", default="data/canonical/decisional_risk")
    p.add_argument("--risk-run-id", required=True, type=int)
    args = p.parse_args()

    g4 = Path(args.g4_dir); portfolio = Path(args.portfolio_dir); out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    lineage = json.loads((g4 / "e2e_lineage.json").read_text())
    manifest = json.loads((g4 / "g4_manifest.json").read_text())
    positions = pd.read_parquet(portfolio / "portfolio_positions.parquet")
    pmanifest = json.loads((portfolio / "portfolio_state_manifest.json").read_text())

    required_lineage = ["e2e_run_id","research_run_id","universe_run_id","valuation_run_id","local_market_run_id","portfolio_run_id","g4_run_id"]
    missing = [k for k in required_lineage if not lineage.get(k)]
    blockers = []
    if missing: blockers.append("INCOMPLETE_LINEAGE:" + ",".join(missing))
    if manifest.get("ticker_count") != 30 or manifest.get("evaluated_count") != 30 or manifest.get("blocked_count") != 0:
        blockers.append("G4_CONTRACT_NOT_COMPLETE")
    elif not g4_ranking_is_risk_acceptable(manifest):
        blockers.append("G4_RANKING_NOT_RISK_ACCEPTABLE")

    portfolio_validation = pmanifest.get("portfolio_state_validation", {})
    if portfolio_validation.get("portfolio_state_status") != "PORTFOLIO_STATE_VALIDATED":
        blockers.append("PORTFOLIO_STATE_NOT_VALIDATED")
    portfolio_risk = pmanifest.get("portfolio_risk", {})
    if portfolio_risk.get("portfolio_risk_status") != "PORTFOLIO_RISK_READY":
        blockers.append("PORTFOLIO_RISK_NOT_READY")

    g4_decision = manifest.get("deployment_decision")
    cash_status = manifest.get("cash_optimality_status")
    if blockers:
        risk_status, veto, deployment = "BLOCKED", "YES", "NO_NEW_DEPLOYMENT"
    else:
        risk_status, veto = "PASS", "NO"
        deployment = "NO_NEW_DEPLOYMENT" if g4_decision == "NO_NEW_DEPLOYMENT" or cash_status == "CASH_OPTIMAL_BY_MODEL" else "G4_CANDIDATES_MAY_PROCEED"

    payload = {
        "layer":"DECISIONAL_RISK","methodology_version":"RISK-DECISIONAL-1.2","created_at":datetime.now(timezone.utc).isoformat(),
        "risk_status":risk_status,"risk_veto":veto,"deployment_decision":deployment,"blockers":blockers,
        "g4_contract":{"ticker_count":manifest.get("ticker_count"),"evaluated_count":manifest.get("evaluated_count"),"blocked_count":manifest.get("blocked_count"),"pass_count":manifest.get("pass_count"),"fail_count":manifest.get("fail_count"),"cash_optimality_status":cash_status,"deployment_decision":g4_decision,"ranking_status":manifest.get("ranking_status"),"extreme_target_review_required_count":manifest.get("extreme_target_review_required_count"),"clean_g4_pass_count":manifest.get("clean_g4_pass_count")},
        "portfolio_state_validation": portfolio_validation,
        "portfolio_risk":portfolio_risk,"position_count":int(len(positions)),
        "principle":"Risk does not manufacture deployment. A complete 30/30 G4 ranking may proceed with isolated review flags because review-flagged names are excluded from G4 actionable candidates; incomplete or blocked G4 remains fail-closed."
    }
    (out/"decisional_risk.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False))
    lineage["decisional_risk_run_id"] = args.risk_run_id
    lineage["decisional_risk_status"] = risk_status
    lineage["decisional_risk_veto"] = veto
    (out/"e2e_lineage.json").write_text(json.dumps(lineage,indent=2,ensure_ascii=False))
    print(json.dumps(payload,indent=2,ensure_ascii=False))
    if blockers: raise SystemExit("Decisional Risk blocked: " + ";".join(blockers))

if __name__ == "__main__": main()
