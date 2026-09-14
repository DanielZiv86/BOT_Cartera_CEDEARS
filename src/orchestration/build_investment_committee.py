from __future__ import annotations

import argparse,json
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import yaml

from src.portfolio.allocation import AllocationPolicy, build_portfolio_allocation
from src.portfolio.goals import load_financial_goal, evaluate_goal
from src.valuation.deep_scenario_engine import validate_scenarios


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
        diversification_multiplier_min=float(rb.get('diversification_multiplier_min', .5)),
        diversification_multiplier_max=float(rb.get('diversification_multiplier_max', 1.5)),
        diversification_score_neutral=float(rb.get('diversification_score_neutral', 50.0)),
    )


def _compute_existing_holdings_stress(positions_path: str, broad_valuation_path: str, scenario_policy_path: str) -> tuple[float, dict]:
    """Currently-held positions' own worst-case stress contribution to the
    whole-portfolio stress budget (see AllocationPolicy.portfolio_stress_
    budget_nav and build_portfolio_allocation's existing_holdings_stress_nav).

    Computed against the BROAD-universe valuation (every held ticker, not
    just this week's Top-30 -- most held names are outside it) using the same
    sector-aware Deep Scenario Review the rest of the pipeline already runs.
    Uses each ticker's raw bear-case percentage move
    (|bear_target_price/current_price - 1|) as the stress proxy -- not the
    full G4 bear_return_net, which additionally nets FX/CCL and brokerage
    frictions computed against a specific entry price/ratio a currently-held
    position (bought at a different time, at a different entry) doesn't have
    in this context. This is a deliberate simplification, not an oversight.

    Held tickers whose scenario can't currently be validated (BRKB's dual-
    class EPS bug, VIG's absence from the canonical universe -- see
    PROJECT_STATE.md's open items) are excluded from the sum, never defaulted
    to zero risk: their weight is reported in unassessed_weight so the gap
    stays visible instead of silently understating true portfolio stress.
    """
    positions = pd.read_parquet(positions_path)
    positions['weight'] = pd.to_numeric(positions['weight'], errors='coerce').fillna(0.0)
    held = positions[positions['weight'] > 1e-12].copy()
    held['cedear_ticker'] = held['cedear_ticker'].astype(str).str.upper()

    broad = pd.read_parquet(broad_valuation_path)
    policy = yaml.safe_load(Path(scenario_policy_path).read_text(encoding='utf-8')) or {}
    reviewed, _ = validate_scenarios(broad, policy)
    reviewed['cedear_ticker'] = reviewed['cedear_ticker'].astype(str).str.upper()
    reviewed = reviewed.drop_duplicates('cedear_ticker').set_index('cedear_ticker')
    assessed = reviewed[reviewed['scenario_validated'].fillna(False).astype(bool)] if 'scenario_validated' in reviewed.columns else reviewed.iloc[0:0]

    total_stress = 0.0
    assessed_weight = 0.0
    unassessed_weight = 0.0
    unassessed_tickers: list[str] = []
    for _, row in held.iterrows():
        ticker = row['cedear_ticker']
        weight = float(row['weight'])
        if ticker in assessed.index:
            r = assessed.loc[ticker]
            current = float(r['current_price'])
            bear = float(r['bear_target_price'])
            loss = abs(bear / current - 1.0) if current > 0 else 0.0
            total_stress += weight * loss
            assessed_weight += weight
        else:
            unassessed_weight += weight
            unassessed_tickers.append(ticker)

    metrics = {
        'existing_holdings_stress_method': 'RAW_BEAR_TARGET_PRICE_PCT_MOVE_NO_FX_BROKERAGE_FRICTION',
        'existing_holdings_assessed_weight': assessed_weight,
        'existing_holdings_unassessed_weight': unassessed_weight,
        'existing_holdings_unassessed_tickers': sorted(unassessed_tickers),
    }
    return total_stress, metrics


def _build_new_trades(g4_dir: Path, allocation_policy_path: str, existing_holdings_stress_nav: float = 0.0) -> tuple[list[dict], dict]:
    """Size G4_PASS candidates into concrete trades via the risk-budget allocator.

    Returns (trades, allocation_metrics). Never called unless the Committee's
    own decision waterfall has already determined passes>0 and every other
    gate (risk veto, data gaps) allows candidates to proceed -- this function
    only decides how much, never whether.

    existing_holdings_stress_nav (see _compute_existing_holdings_stress)
    defaults to 0.0 -- the previous new-deployment-only behavior -- when the
    caller doesn't have the inputs to compute it (e.g. a test, or a CLI
    invocation missing --positions/--broad-valuation).
    """
    g4_result = pd.read_parquet(g4_dir / 'g4_cash_hurdle.parquet')
    policy = _load_allocation_policy(allocation_policy_path)
    allocated, metrics = build_portfolio_allocation(g4_result, policy, existing_holdings_stress_nav=existing_holdings_stress_nav)
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
    p=argparse.ArgumentParser(description='Investment Committee: exact-lineage final decision and shadow-book persistence');p.add_argument('--g4-dir',required=True);p.add_argument('--risk-dir',required=True);p.add_argument('--output-dir',default='data/canonical/committee');p.add_argument('--committee-run-id',required=True,type=int);p.add_argument('--allocation-policy',default='config/portfolio_allocation_policy.yml');p.add_argument('--portfolio-state-manifest',required=True);p.add_argument('--financial-goal',default='config/financial_goal.yml');p.add_argument('--as-of-date',default=None,help='YYYY-MM-DD override for goal pace evaluation; defaults to today (UTC)');p.add_argument('--positions',default=None,help='portfolio_positions.parquet (cedear_ticker, weight); with --broad-valuation, enables existing_holdings_stress_nav; omitted, existing holdings contribute 0 to the portfolio stress budget (previous behavior)');p.add_argument('--broad-valuation',default=None,help='Deep Scenario Review broad-universe valuation parquet (every held ticker, not just this week Top-30)');p.add_argument('--scenario-policy',default='config/scenario_review_policy.yml');a=p.parse_args();g4=Path(a.g4_dir);risk=Path(a.risk_dir);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    gl=json.loads((g4/'e2e_lineage.json').read_text());rl=json.loads((risk/'e2e_lineage.json').read_text());gm=json.loads((g4/'g4_manifest.json').read_text());rr=json.loads((risk/'decisional_risk.json').read_text());keys=['e2e_run_id','research_run_id','universe_run_id','valuation_run_id','local_market_run_id','portfolio_run_id','g4_run_id']
    assert all(gl.get(k)==rl.get(k) for k in keys),'Risk and G4 lineage mismatch';assert rl.get('decisional_risk_run_id'),'Missing decisional Risk run id';assert gm.get('ticker_count')==30 and int(gm.get('evaluated_count',0))+int(gm.get('blocked_count',0))==30,gm;assert gm.get('g4_accounting_complete') is True,gm;assert rr.get('risk_status')=='PASS',rr
    passes=int(gm.get('pass_count',0) or 0);fails=int(gm.get('fail_count',0) or 0);blocked=int(gm.get('blocked_count',0) or 0);evaluated=int(gm.get('evaluated_count',0) or 0)
    # A BLOCKED_BY_DATA ticker (a per-ticker data gap, e.g. a missing verified
    # ADR ratio or a currency-normalization bug -- see PROJECT_STATE.md) is
    # excluded from G4 evaluation, but was previously ALSO treated as a
    # whole-committee veto: any single blocked name in the Top-30 forced
    # HOLD_CASH_NO_ACTION even when other, cleanly-evaluated candidates
    # passed G4 and Risk. That double-counted an isolated data gap as risk
    # against unrelated tickers (2026-09-12, reviewed at the user's request).
    # A per-ticker gap doesn't cast doubt on tickers whose data IS fresh and
    # verified -- it only means that ONE ticker can't be traded this cycle,
    # which is already enforced by it never reaching G4_PASS. The only case
    # that legitimately warrants a systemic halt is evaluated==0 (nothing in
    # the Top-30 could be evaluated at all -- a pipeline-wide failure, not an
    # isolated gap), handled explicitly below.
    if rr.get('risk_veto')=='YES':decision='HOLD_CASH_NO_ACTION';rationale='RISK_VETO'
    elif evaluated==0:decision='HOLD_CASH_NO_ACTION';rationale='ALL_CANDIDATES_BLOCKED_BY_DATA'
    elif passes==0 and fails==evaluated:decision='HOLD_CASH_NO_ACTION';rationale='NO_CANDIDATE_BEATS_CASH_HURDLE'
    elif gm.get('deployment_decision')=='NO_NEW_DEPLOYMENT' and gm.get('cash_optimality_status')=='CASH_OPTIMAL_BY_MODEL':decision='HOLD_CASH_NO_ACTION';rationale='CASH_OPTIMAL_BY_MODEL'
    elif passes>0 and rr.get('deployment_decision')=='G4_CANDIDATES_MAY_PROCEED':decision='CANDIDATES_REQUIRE_EXECUTION_GATE';rationale='G4_PASS_RISK_PASS'
    else:decision='HOLD_CASH_NO_ACTION';rationale='NO_TRADE_READY_CANDIDATE'
    secondary=[]
    if blocked>0:secondary.append('SCENARIO_DATA_GAPS_FAIL_CLOSED')

    existing_holdings_stress_nav=0.0
    existing_holdings_stress_metrics: dict | None = None
    if a.positions and a.broad_valuation:
        existing_holdings_stress_nav,existing_holdings_stress_metrics=_compute_existing_holdings_stress(a.positions,a.broad_valuation,a.scenario_policy)

    new_trades: list[dict] = []
    allocation_metrics: dict | None = None
    if decision == 'CANDIDATES_REQUIRE_EXECUTION_GATE':
        new_trades, allocation_metrics = _build_new_trades(g4, a.allocation_policy, existing_holdings_stress_nav=existing_holdings_stress_nav)

    goal_tracking=_evaluate_goal_tracking(a.portfolio_state_manifest,a.financial_goal,new_trades,a.as_of_date)

    now=datetime.now(timezone.utc).isoformat();committee={'layer':'INVESTMENT_COMMITTEE','methodology_version':'COMMITTEE-1.3','created_at':now,'decision':decision,'rationale':rationale,'secondary_considerations':secondary,'risk_veto':rr.get('risk_veto'),'g4_cash_optimality_status':gm.get('cash_optimality_status'),'g4_pass_count':passes,'g4_fail_count':fails,'g4_blocked_count':blocked,'new_trades':new_trades,'allocation_metrics':allocation_metrics,'existing_holdings_stress_metrics':existing_holdings_stress_metrics,'goal_tracking':goal_tracking,'fabricated_trade_count':0,'decision_is_valid_no_action':decision=='HOLD_CASH_NO_ACTION'};shadow={'created_at':now,'e2e_run_id':gl['e2e_run_id'],'committee_run_id':a.committee_run_id,'decision':decision,'orders':new_trades,'order_count':len(new_trades),'status':'NO_ACTION_PERSISTED' if not committee['new_trades'] else 'PENDING_EXECUTION_GATE'}
    rl['committee_run_id']=a.committee_run_id;rl['committee_decision']=decision;rl['decision_persisted']=True;(out/'committee_decision.json').write_text(json.dumps(committee,indent=2,ensure_ascii=False));(out/'shadow_book.json').write_text(json.dumps(shadow,indent=2,ensure_ascii=False));(out/'e2e_lineage.json').write_text(json.dumps(rl,indent=2,ensure_ascii=False));print(json.dumps({'committee':committee,'shadow_book':shadow,'lineage':rl},indent=2,ensure_ascii=False))

if __name__=='__main__':main()
