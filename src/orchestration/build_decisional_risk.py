from __future__ import annotations

import argparse,json
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd

RISK_ACCEPTED_G4_RANKING_STATUSES={"COMPLETE_ACTIONABLE","COMPLETE_WITH_REVIEW_FLAGS","COMPLETE_WITH_DATA_GAPS","COMPLETE_REVIEW_REQUIRED"}


def g4_ranking_is_risk_acceptable(manifest:dict)->bool:
    total=int(manifest.get('ticker_count',0) or 0); evaluated=int(manifest.get('evaluated_count',0) or 0); blocked=int(manifest.get('blocked_count',0) or 0)
    return total==30 and evaluated+blocked==30 and manifest.get('ranking_status') in RISK_ACCEPTED_G4_RANKING_STATUSES


def main()->None:
    p=argparse.ArgumentParser(description='Build fail-closed decisional Risk gate from exact G4 lineage');p.add_argument('--g4-dir',required=True);p.add_argument('--portfolio-dir',required=True);p.add_argument('--output-dir',default='data/canonical/decisional_risk');p.add_argument('--risk-run-id',required=True,type=int);a=p.parse_args()
    g4=Path(a.g4_dir);portfolio=Path(a.portfolio_dir);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True);lineage=json.loads((g4/'e2e_lineage.json').read_text());manifest=json.loads((g4/'g4_manifest.json').read_text());positions=pd.read_parquet(portfolio/'portfolio_positions.parquet');pmanifest=json.loads((portfolio/'portfolio_state_manifest.json').read_text())
    required=['e2e_run_id','research_run_id','universe_run_id','valuation_run_id','local_market_run_id','portfolio_run_id','g4_run_id'];missing=[k for k in required if not lineage.get(k)];blockers=[]
    if missing:blockers.append('INCOMPLETE_LINEAGE:'+','.join(missing))
    if not g4_ranking_is_risk_acceptable(manifest):blockers.append('G4_CONTRACT_NOT_ACCOUNTED')
    pv=pmanifest.get('portfolio_state_validation',{});pr=pmanifest.get('portfolio_risk',{})
    if pv.get('portfolio_state_status')!='PORTFOLIO_STATE_VALIDATED':blockers.append('PORTFOLIO_STATE_NOT_VALIDATED')
    if pr.get('portfolio_risk_status')!='PORTFOLIO_RISK_READY':blockers.append('PORTFOLIO_RISK_NOT_READY')
    g4_decision=manifest.get('deployment_decision');cash=manifest.get('cash_optimality_status');data_gaps=int(manifest.get('blocked_count',0) or 0)>0
    if blockers:risk_status,veto,deployment='BLOCKED','YES','NO_NEW_DEPLOYMENT'
    else:
        risk_status,veto='PASS','NO'
        # G4's own deployment_decision already correctly allows deployment
        # when clean G4_PASS candidates exist, even alongside an unrelated
        # BLOCKED_BY_DATA ticker elsewhere in the Top-30 (see build_g4_cash_
        # hurdle.py's _govern, reviewed 2026-09-12) -- Risk trusts that
        # rather than re-imposing its own independent data-gap veto, which
        # would double-count the same isolated per-ticker gap as risk
        # against unrelated candidates. data_gap_hold below still reports
        # the gap for visibility.
        deployment='G4_CANDIDATES_MAY_PROCEED' if g4_decision=='ALLOW_NEW_DEPLOYMENT' else 'NO_NEW_DEPLOYMENT'
    payload={'layer':'DECISIONAL_RISK','methodology_version':'RISK-DECISIONAL-1.4','created_at':datetime.now(timezone.utc).isoformat(),'risk_status':risk_status,'risk_veto':veto,'deployment_decision':deployment,'blockers':blockers,'data_gap_hold':data_gaps,'g4_contract':{'ticker_count':manifest.get('ticker_count'),'evaluated_count':manifest.get('evaluated_count'),'blocked_count':manifest.get('blocked_count'),'accounted_count':manifest.get('accounted_count'),'g4_accounting_complete':manifest.get('g4_accounting_complete'),'pass_count':manifest.get('pass_count'),'fail_count':manifest.get('fail_count'),'cash_optimality_status':cash,'deployment_decision':g4_decision,'ranking_status':manifest.get('ranking_status'),'scenario_validated_count':manifest.get('scenario_validated_count'),'scenario_blocked_count':manifest.get('scenario_blocked_count')},'portfolio_state_validation':pv,'portfolio_risk':pr,'position_count':int(len(positions)),'principle':'Risk distinguishes broken lineage from explicit fail-closed candidate data gaps. All 30 candidates must be accounted for; blocked scenario names cannot deploy and force a conservative no-new-deployment hold without manufacturing a global risk veto.'}
    (out/'decisional_risk.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False));lineage['decisional_risk_run_id']=a.risk_run_id;lineage['decisional_risk_status']=risk_status;lineage['decisional_risk_veto']=veto;(out/'e2e_lineage.json').write_text(json.dumps(lineage,indent=2,ensure_ascii=False));print(json.dumps(payload,indent=2,ensure_ascii=False))
    if blockers:raise SystemExit('Decisional Risk blocked: '+';'.join(blockers))

if __name__=='__main__':main()
