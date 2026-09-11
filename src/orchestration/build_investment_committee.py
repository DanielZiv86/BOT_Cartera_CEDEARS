from __future__ import annotations

import argparse,json
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import yaml

from src.portfolio.allocation import AllocationPolicy, build_portfolio_allocation
from src.portfolio.goals import load_financial_goal, evaluate_goal


def _load_allocation_policy(path: str) -> AllocationPolicy:
    raw = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    rb = raw.get('risk_budget', {})
    return AllocationPolicy(
        position_stress_budget_nav=float(rb.get('position_stress_budget_nav', .02)),
        portfolio_stress_budget_nav=float(rb.get('portfolio_stress_budget_nav', .10)),
        max_single_name_weight=float(rb.get('max_single_name_weight', .20)),
        max_positions=int(rb.get('max_positions', 10)),
        min_position_weight=float(rb.get('min_position_weight', .02)),
        max_new_deployment_weight_nav=float(rb.get('max_new_deployment_weight_nav', 1.00)),
    )


def _build_new_trades(g4_dir: Path, allocation_policy_path: str) -> tuple[list[dict], dict]:
    """Size G4_PASS candidates into concrete trades via the risk-budget allocator.

    Returns (trades, allocation_metrics). Never called unless the Committee's
    own decision waterfall has already determined passes>0 and every other
    gate (risk veto, data gaps) allows candidates to proceed -- this function
    only decides how much, never whether.
    """
    g4_result = pd.read_parquet(g4_dir / 'g4_cash_hurdle.parquet')
    policy = _load_allocation_policy(allocation_policy_path)
    allocated, metrics = build_portfolio_allocation(g4_result, policy)
    trades = allocated.to_dict(orient='records')
    return trades, metrics


def _evaluate_goal_tracking(portfolio_state_manifest_path: str, financial_goal_path: str, new_trades: list[dict], as_of_date: str | None) -> dict:
    """Goal-pace monitoring only -- never gates the decision above.

    Reports the annual return required to clear the financial goal from the
    portfolio's real current NAV, and how the expected return of THIS cycle's
    new capital (if any) compares to that pace. Absence of new trades, or a
    required return that isn't computable (goal already met / horizon
    elapsed), are both reported as explicit statuses, never silently omitted.
    """
    manifest = json.loads(Path(portfolio_state_manifest_path).read_text(encoding='utf-8'))
    current_nav = float(manifest['portfolio_state_validation']['nav_total_usd'])
    goal = load_financial_goal(financial_goal_path)
    as_of = datetime.strptime(as_of_date, '%Y-%m-%d').date() if as_of_date else datetime.now(timezone.utc).date()
    status = evaluate_goal(current_nav, goal, as_of)

    total_delta = sum(float(t['weight_delta']) for t in new_trades) if new_trades else 0.0
    if new_trades and total_delta > 1e-12:
        weighted_er = sum(float(t['weight_delta']) * float(t['risk_adjusted_er']) for t in new_trades) / total_delta
    else:
        weighted_er = None
    status['goal_new_deployment_weighted_expected_return'] = weighted_er

    required = status.get('goal_required_annual_return')
    if weighted_er is None:
        pace = 'NO_NEW_DEPLOYMENT_THIS_CYCLE'
    elif required is None:
        pace = 'REQUIRED_RETURN_NOT_COMPUTABLE'
    elif weighted_er >= required:
        pace = 'NEW_DEPLOYMENT_MEETS_OR_EXCEEDS_PACE'
    else:
        pace = 'NEW_DEPLOYMENT_BELOW_PACE'
    status['goal_pace_status'] = pace
    return status


def main()->None:
    p=argparse.ArgumentParser(description='Investment Committee: exact-lineage final decision and shadow-book persistence');p.add_argument('--g4-dir',required=True);p.add_argument('--risk-dir',required=True);p.add_argument('--output-dir',default='data/canonical/committee');p.add_argument('--committee-run-id',required=True,type=int);p.add_argument('--allocation-policy',default='config/portfolio_allocation_policy.yml');p.add_argument('--portfolio-state-manifest',required=True);p.add_argument('--financial-goal',default='config/financial_goal.yml');p.add_argument('--as-of-date',default=None,help='YYYY-MM-DD override for goal pace evaluation; defaults to today (UTC)');a=p.parse_args();g4=Path(a.g4_dir);risk=Path(a.risk_dir);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
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

    new_trades: list[dict] = []
    allocation_metrics: dict | None = None
    if decision == 'CANDIDATES_REQUIRE_EXECUTION_GATE':
        new_trades, allocation_metrics = _build_new_trades(g4, a.allocation_policy)

    goal_tracking=_evaluate_goal_tracking(a.portfolio_state_manifest,a.financial_goal,new_trades,a.as_of_date)

    now=datetime.now(timezone.utc).isoformat();committee={'layer':'INVESTMENT_COMMITTEE','methodology_version':'COMMITTEE-1.2','created_at':now,'decision':decision,'rationale':rationale,'secondary_considerations':secondary,'risk_veto':rr.get('risk_veto'),'g4_cash_optimality_status':gm.get('cash_optimality_status'),'g4_pass_count':passes,'g4_fail_count':fails,'g4_blocked_count':blocked,'new_trades':new_trades,'allocation_metrics':allocation_metrics,'goal_tracking':goal_tracking,'fabricated_trade_count':0,'decision_is_valid_no_action':decision=='HOLD_CASH_NO_ACTION'};shadow={'created_at':now,'e2e_run_id':gl['e2e_run_id'],'committee_run_id':a.committee_run_id,'decision':decision,'orders':new_trades,'order_count':len(new_trades),'status':'NO_ACTION_PERSISTED' if not committee['new_trades'] else 'PENDING_EXECUTION_GATE'}
    rl['committee_run_id']=a.committee_run_id;rl['committee_decision']=decision;rl['decision_persisted']=True;(out/'committee_decision.json').write_text(json.dumps(committee,indent=2,ensure_ascii=False));(out/'shadow_book.json').write_text(json.dumps(shadow,indent=2,ensure_ascii=False));(out/'e2e_lineage.json').write_text(json.dumps(rl,indent=2,ensure_ascii=False));print(json.dumps({'committee':committee,'shadow_book':shadow,'lineage':rl},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
