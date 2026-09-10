from __future__ import annotations

import argparse,json
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
import yaml

from src.valuation.g4 import G4Policy,calculate_g4_cash_hurdle
from src.valuation.g4_review import apply_extreme_target_review
from src.valuation.deep_scenario_engine import validate_scenarios


def _load_policy(path):
    raw=yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}; cash=raw.get('cash_hurdle',{}); risk=raw.get('risk',{}); pen=raw.get('penalties',{})
    return G4Policy(cash_return_assumption=float(cash.get('cash_return_assumption',0)),minimum_excess_return_over_cash=float(cash.get('minimum_excess_return_over_cash',.05)),capital_preservation_buffer=float(cash.get('capital_preservation_buffer',.03)),minimum_margin_over_hurdle=float(cash.get('minimum_margin_over_hurdle',.02)),max_bear_downside=float(risk.get('max_bear_downside',-.15)),candidate_test_weight_nav=float(risk.get('candidate_test_weight_nav',.05)),max_single_name_weight=float(risk.get('max_single_name_weight',.20)),soft_single_name_weight=float(risk.get('soft_single_name_weight',.12)),warning_single_name_weight=float(risk.get('warning_single_name_weight',.15)),correlation_warning=float(risk.get('correlation_warning',.75)),uncertainty_penalty_max=float(pen.get('uncertainty_penalty_max',.10)),local_warning_penalty=float(pen.get('local_warning_penalty',.02)),correlation_penalty_max=float(pen.get('correlation_penalty_max',.03)),concentration_penalty_max=float(pen.get('concentration_penalty_max',.03))),raw


def _load(path):
    p=Path(path)
    if p.suffix.lower()=='.parquet': return pd.read_parquet(p)
    if p.suffix.lower()=='.csv': return pd.read_csv(p)
    if p.suffix.lower()=='.json': return pd.read_json(p)
    raise ValueError(f'Unsupported input: {p}')


def _certified_review_metrics(reviewed, scenario_methodology_version='SCENARIO-2.2'):
    validated=reviewed.get('scenario_validated',pd.Series(False,index=reviewed.index)).fillna(False).astype(bool)
    blockers={}
    if 'scenario_review_blockers' in reviewed.columns:
        for raw in reviewed['scenario_review_blockers']:
            vals=raw if isinstance(raw,list) else ([] if raw is None or (isinstance(raw,float) and pd.isna(raw)) else [str(raw)])
            for b in vals:
                b=str(b).strip()
                if b: blockers[b]=blockers.get(b,0)+1
    return {'scenario_review_count':len(reviewed),'scenario_validated_count':int(validated.sum()),'scenario_blocked_count':int((~validated).sum()),'scenario_review_complete':bool(validated.all()),'scenario_methodology_version':scenario_methodology_version,'scenario_blocker_counts':dict(sorted(blockers.items()))}


def _govern(m):
    x=dict(m); blocked=int(x.get('blocked_count',0) or 0); evaluated=int(x.get('evaluated_count',0) or 0); passes=int(x.get('pass_count',0) or 0); clean=int(x.get('clean_g4_pass_count',passes) or 0); review=int(x.get('extreme_target_review_required_count',0) or 0); total=int(x.get('ticker_count',0) or 0)
    accounted=(total==30 and evaluated+blocked==30)
    if total==0 or not accounted: x.update(deployment_decision='RESEARCH_BLOCKED',ranking_status='PARTIAL_NOT_ACTIONABLE')
    elif blocked>0: x.update(deployment_decision='NO_NEW_DEPLOYMENT_DATA_GAPS',ranking_status='COMPLETE_WITH_DATA_GAPS')
    elif clean>0: x.update(deployment_decision='ALLOW_NEW_DEPLOYMENT',ranking_status='COMPLETE_WITH_REVIEW_FLAGS' if review else 'COMPLETE_ACTIONABLE')
    elif passes>0 and review>0: x.update(deployment_decision='NO_NEW_DEPLOYMENT_PENDING_TARGET_REVIEW',ranking_status='COMPLETE_REVIEW_REQUIRED')
    else: x.update(deployment_decision='NO_NEW_DEPLOYMENT',ranking_status='COMPLETE_ACTIONABLE')
    x['accounted_count']=evaluated+blocked; x['g4_accounting_complete']=accounted
    return x


def _apply_global_governance(metrics): return _govern(metrics)


def _dynamic_equity_margin(result,reviewed,raw_policy):
    if result.empty:return result
    cfg=raw_policy.get('dynamic_equity_margin',{}) or {}; base=float(cfg.get('base_equity_risk_buffer',.015)); unc_max=float(cfg.get('uncertainty_buffer_max',.02)); downside_max=float(cfg.get('downside_buffer_max',.015))
    meta=reviewed[[c for c in ['cedear_ticker','valuation_engine_type','scenario_validated'] if c in reviewed.columns]].drop_duplicates('cedear_ticker'); out=result.merge(meta,on='cedear_ticker',how='left'); req=[]
    for _,r in out.iterrows():
        margin=float(r.get('minimum_margin_over_hurdle') or 0); engine=str(r.get('valuation_engine_type') or '').upper(); conf=float(r.get('valuation_confidence') or 0); bear=float(r.get('bear_return_net') or 0)
        if engine=='EQUITY': margin+=base+(1-conf)*unc_max+min(max(-bear,0),.30)/.30*downside_max
        req.append(margin)
    out['required_margin_over_cash']=req; mask=(out['g4_status']=='G4_PASS')&(out['net_benefit_vs_cash']<out['required_margin_over_cash']); out.loc[mask,'g4_status']='G4_FAIL_RETURN'; out.loc[mask,'g4_reason']='INSUFFICIENT_DYNAMIC_EQUITY_MARGIN_VS_CASH'; return out


def _execution(result,local):
    if result.empty:return result
    cols=[c for c in ['cedear_ticker','execution_book_status','executable_buy_ars','ratio_status','ccl_status','market_session_status'] if c in local.columns]; lm=local[cols].drop_duplicates('cedear_ticker'); out=result.merge(lm,on='cedear_ticker',how='left',suffixes=('','_execution'))
    book=out.get('execution_book_status',pd.Series(index=out.index,dtype=object)).isin(['BOOK_EXECUTABLE_BY_SANITY','EXECUTABLE_BOOK_READY']); buy=pd.to_numeric(out.get('executable_buy_ars'),errors='coerce').gt(0); ratio=out.get('ratio_status',pd.Series(index=out.index,dtype=object)).isin(['RATIO_VALIDATED_COMAFI','RATIO_VALIDATED_CANONICAL_CCL']); ccl=out.get('ccl_status',pd.Series(index=out.index,dtype=object)).isin(['CCL_READY_VALIDATED','CCL_READY_VALIDATED_CANONICAL','CCL_WARNING_MARKET_DEVIATION'])
    out['analysis_ready']=out['g4_status'].ne('BLOCKED_BY_DATA'); out['execution_ready']=out['analysis_ready']&book&buy&ratio&ccl; out['execution_gate_status']='NOT_EXECUTION_READY'; out.loc[out['execution_ready'],'execution_gate_status']='EXECUTION_READY'; return out


def _add_execution_gate(result,local): return _execution(result,local)


def main():
    p=argparse.ArgumentParser();
    for a in ('local-market','valuation-inputs','portfolio-fit','positions','policy','output-dir'):p.add_argument(f'--{a}',required=True)
    p.add_argument('--scenario-policy',default='config/scenario_review_policy.yml');p.add_argument('--brokerage-rate',type=float,default=.006);p.add_argument('--certified-scenario-review',action='store_true');a=p.parse_args()
    local=_load(a.local_market); valuations=_load(a.valuation_inputs); fit=_load(a.portfolio_fit); positions=_load(a.positions); policy,raw=_load_policy(a.policy); scenario_policy=yaml.safe_load(Path(a.scenario_policy).read_text(encoding='utf-8')) or {}
    scenario_methodology_version=str(scenario_policy.get('methodology_version') or 'SCENARIO-UNKNOWN')
    if a.certified_scenario_review:
        required={'scenario_validated','scenario_review_status','scenario_review_blockers','economic_identity_status','scenario_method'}
        missing=required-set(valuations.columns); assert not missing, {'certified_review_missing_columns':sorted(missing)}
        reviewed=valuations.copy(); scenario_metrics=_certified_review_metrics(reviewed,scenario_methodology_version)
    else:
        reviewed,scenario_metrics=validate_scenarios(valuations,scenario_policy)
        scenario_metrics['scenario_methodology_version']=scenario_methodology_version
    invalid=~reviewed.get('scenario_validated',pd.Series(False,index=reviewed.index)).fillna(False); reviewed.loc[invalid,'valuation_status']='BLOCKED_BY_DATA'
    result,metrics=calculate_g4_cash_hurdle(local_market=local,valuation_inputs=reviewed,portfolio_fit=fit,positions=positions,policy=policy,brokerage_rate=a.brokerage_rate); result=_dynamic_equity_margin(result,reviewed,raw)
    metrics['pass_count']=int((result['g4_status']=='G4_PASS').sum()); metrics['blocked_count']=int((result['g4_status']=='BLOCKED_BY_DATA').sum()); metrics['evaluated_count']=len(result)-metrics['blocked_count']; metrics['fail_count']=metrics['evaluated_count']-metrics['pass_count']; metrics['cash_optimality_status']='NOT_DEMONSTRATED' if metrics['blocked_count'] else ('CASH_NOT_OPTIMAL_BY_MODEL' if metrics['pass_count'] else 'CASH_OPTIMAL_BY_MODEL')
    result,review_metrics=apply_extreme_target_review(result,reviewed,raw); result=_execution(result,local); metrics=_govern({**metrics,**scenario_metrics,**review_metrics}); metrics['analysis_ready_count']=int(result.get('analysis_ready',pd.Series(dtype=bool)).sum());metrics['execution_ready_count']=int(result.get('execution_ready',pd.Series(dtype=bool)).sum())
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True); reviewed_json=reviewed.copy()
    for c in ('blockers','scenario_review_blockers','scenario_review_flags'):
        if c in reviewed_json:reviewed_json[c]=reviewed_json[c].map(lambda x:x if isinstance(x,list) else [])
    reviewed_json.to_json(out/'scenario_review.json',orient='records',indent=2,force_ascii=False); json_df=result.copy()
    for c in ('blockers','target_review_flags'):
        if c in json_df:json_df[c]=json_df[c].map(lambda x:x if isinstance(x,list) else [])
    json_df.to_json(out/'g4_cash_hurdle.json',orient='records',indent=2,force_ascii=False); pq=result.copy()
    for c in ('blockers','target_review_flags'):
        if c in pq:pq[c]=pq[c].map(lambda x:json.dumps(x,ensure_ascii=False) if isinstance(x,list) else x)
    pq.to_parquet(out/'g4_cash_hurdle.parquet',index=False); result[result['g4_status']!='BLOCKED_BY_DATA'].sort_values('net_benefit_vs_cash',ascending=False).to_json(out/'g4_ranked_evaluated.json',orient='records',indent=2,force_ascii=False)
    actionable=result[(result['g4_status']=='G4_PASS')&(result['target_review_status']=='ACTIONABLE_IF_GLOBAL_GOVERNANCE_ALLOWS')&(result['execution_ready'])].sort_values('net_benefit_vs_cash',ascending=False); actionable.to_json(out/'g4_ranked_actionable.json',orient='records',indent=2,force_ascii=False)
    manifest={'layer':'Deep Scenario Review + G4 Cash Hurdle','created_at':datetime.now(timezone.utc).isoformat(),'policy_file':a.policy,'scenario_policy_file':a.scenario_policy,'policy':raw,'brokerage_rate_per_side':a.brokerage_rate,**metrics,'methodology_version':str(raw.get('methodology_version') or 'G4-UNKNOWN'),'certified_scenario_review_consumed':bool(a.certified_scenario_review)};(out/'g4_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(manifest,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
