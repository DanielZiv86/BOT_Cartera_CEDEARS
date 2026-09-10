from __future__ import annotations

import argparse,json
from datetime import datetime,timezone
from pathlib import Path


def main()->None:
    p=argparse.ArgumentParser(description='Investment Committee: exact-lineage final decision and shadow-book persistence');p.add_argument('--g4-dir',required=True);p.add_argument('--risk-dir',required=True);p.add_argument('--output-dir',default='data/canonical/committee');p.add_argument('--committee-run-id',required=True,type=int);a=p.parse_args();g4=Path(a.g4_dir);risk=Path(a.risk_dir);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    gl=json.loads((g4/'e2e_lineage.json').read_text());rl=json.loads((risk/'e2e_lineage.json').read_text());gm=json.loads((g4/'g4_manifest.json').read_text());rr=json.loads((risk/'decisional_risk.json').read_text());keys=['e2e_run_id','research_run_id','universe_run_id','valuation_run_id','local_market_run_id','portfolio_run_id','g4_run_id']
    assert all(gl.get(k)==rl.get(k) for k in keys),'Risk and G4 lineage mismatch';assert rl.get('decisional_risk_run_id'),'Missing decisional Risk run id';assert gm.get('ticker_count')==30 and int(gm.get('evaluated_count',0))+int(gm.get('blocked_count',0))==30,gm;assert gm.get('g4_accounting_complete') is True,gm;assert rr.get('risk_status')=='PASS',rr
    passes=int(gm.get('pass_count',0) or 0);fails=int(gm.get('fail_count',0) or 0);blocked=int(gm.get('blocked_count',0) or 0);evaluated=int(gm.get('evaluated_count',0) or 0)
    if rr.get('risk_veto')=='YES':decision='HOLD_CASH_NO_ACTION';rationale='RISK_VETO'
    elif passes==0 and evaluated>0 and fails==evaluated:decision='HOLD_CASH_NO_ACTION';rationale='NO_CANDIDATE_BEATS_CASH_HURDLE'
    elif blocked>0:decision='HOLD_CASH_NO_ACTION';rationale='SCENARIO_DATA_GAPS_FAIL_CLOSED'
    elif gm.get('deployment_decision')=='NO_NEW_DEPLOYMENT' and gm.get('cash_optimality_status')=='CASH_OPTIMAL_BY_MODEL':decision='HOLD_CASH_NO_ACTION';rationale='CASH_OPTIMAL_BY_MODEL'
    elif passes>0 and rr.get('deployment_decision')=='G4_CANDIDATES_MAY_PROCEED':decision='CANDIDATES_REQUIRE_EXECUTION_GATE';rationale='G4_PASS_RISK_PASS'
    else:decision='HOLD_CASH_NO_ACTION';rationale='NO_TRADE_READY_CANDIDATE'
    secondary=[]
    if blocked>0:secondary.append('SCENARIO_DATA_GAPS_FAIL_CLOSED')
    now=datetime.now(timezone.utc).isoformat();committee={'layer':'INVESTMENT_COMMITTEE','methodology_version':'COMMITTEE-1.2','created_at':now,'decision':decision,'rationale':rationale,'secondary_considerations':secondary,'risk_veto':rr.get('risk_veto'),'g4_cash_optimality_status':gm.get('cash_optimality_status'),'g4_pass_count':passes,'g4_fail_count':fails,'g4_blocked_count':blocked,'new_trades':[],'fabricated_trade_count':0,'decision_is_valid_no_action':decision=='HOLD_CASH_NO_ACTION'};shadow={'created_at':now,'e2e_run_id':gl['e2e_run_id'],'committee_run_id':a.committee_run_id,'decision':decision,'orders':[],'order_count':0,'status':'NO_ACTION_PERSISTED' if not committee['new_trades'] else 'PENDING_EXECUTION_GATE'}
    rl['committee_run_id']=a.committee_run_id;rl['committee_decision']=decision;rl['decision_persisted']=True;(out/'committee_decision.json').write_text(json.dumps(committee,indent=2,ensure_ascii=False));(out/'shadow_book.json').write_text(json.dumps(shadow,indent=2,ensure_ascii=False));(out/'e2e_lineage.json').write_text(json.dumps(rl,indent=2,ensure_ascii=False));print(json.dumps({'committee':committee,'shadow_book':shadow,'lineage':rl},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
