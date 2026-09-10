from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class G4Policy:
    cash_return_assumption: float = 0.00
    minimum_excess_return_over_cash: float = 0.05
    capital_preservation_buffer: float = 0.03
    minimum_margin_over_hurdle: float = 0.02
    max_bear_downside: float = -0.15
    candidate_test_weight_nav: float = 0.05
    max_single_name_weight: float = 0.20
    soft_single_name_weight: float = 0.12
    warning_single_name_weight: float = 0.15
    correlation_warning: float = 0.75
    uncertainty_penalty_max: float = 0.10
    local_warning_penalty: float = 0.02
    correlation_penalty_max: float = 0.03
    concentration_penalty_max: float = 0.03

    @property
    def cash_hurdle(self) -> float:
        return self.cash_return_assumption + self.minimum_excess_return_over_cash + self.capital_preservation_buffer


def _num(value: Any) -> float | None:
    try: out=float(value)
    except (TypeError,ValueError): return None
    return out if np.isfinite(out) else None


def _scenario_return(target_underlying,ratio,market_ccl,entry_ars,brokerage_rate,exit_spread_assumption):
    future_local_gross=target_underlying/ratio*market_ccl
    future_local_net=future_local_gross*(1.0-brokerage_rate-exit_spread_assumption)
    return future_local_net/entry_ars-1.0


def _validate_probabilities(row):
    bull_p=_num(row.get('bull_probability')); base_p=_num(row.get('base_probability')); bear_p=_num(row.get('bear_probability'))
    if bull_p is None or base_p is None or bear_p is None:return False,bull_p,base_p,bear_p
    if min(bull_p,base_p,bear_p)<0:return False,bull_p,base_p,bear_p
    return abs((bull_p+base_p+bear_p)-1.0)<=1e-6,bull_p,base_p,bear_p


def calculate_g4_cash_hurdle(local_market,valuation_inputs,portfolio_fit,positions=None,policy=None,brokerage_rate=.006):
    """G4-2.1 economics with Scenario V2.3 semantics.

    Bull/Base/probabilistic-Bear are probability-weighted for expected return.
    Severe Stress has zero probability and is used only by the preservation gate.
    G4-2.1 thresholds, costs and penalties are unchanged.
    """
    policy=policy or G4Policy(); local=local_market.copy(); local['cedear_ticker']=local['cedear_ticker'].astype(str).str.upper()
    valuations=valuation_inputs.copy()
    if valuations.empty:valuations=pd.DataFrame(columns=['cedear_ticker'])
    if 'cedear_ticker' not in valuations:valuations['cedear_ticker']=pd.Series(dtype=str)
    valuations['cedear_ticker']=valuations['cedear_ticker'].astype(str).str.upper()
    fit=portfolio_fit.copy()
    if fit.empty:fit=pd.DataFrame(columns=['cedear_ticker'])
    if 'cedear_ticker' not in fit:fit['cedear_ticker']=pd.Series(dtype=str)
    fit['cedear_ticker']=fit['cedear_ticker'].astype(str).str.upper()
    merged=local.merge(valuations,on='cedear_ticker',how='left',suffixes=('','_valuation')).merge(fit,on='cedear_ticker',how='left',suffixes=('','_fit'))
    existing_weights={}
    if positions is not None and not positions.empty and {'cedear_ticker','weight'}.issubset(positions.columns):
        p=positions.copy();p['cedear_ticker']=p['cedear_ticker'].astype(str).str.upper();p['weight']=pd.to_numeric(p['weight'],errors='coerce').fillna(0);existing_weights=p.groupby('cedear_ticker')['weight'].sum().to_dict()
    rows=[]
    for _,row in merged.iterrows():
        ticker=row['cedear_ticker']; blockers=[]; local_gate=str(row.get('valuation_g4_local_gate') or 'BLOCKED')
        if local_gate=='BLOCKED':blockers.append('LOCAL_MARKET_GATE_BLOCKED')
        ratio=_num(row.get('ratio_used'));market_ccl=_num(row.get('market_ccl_reference'));local_ref=_num(row.get('analytical_local_ref_ars'))
        if ratio is None or ratio<=0:blockers.append('RATIO_MISSING_OR_INVALID')
        if market_ccl is None or market_ccl<=0:blockers.append('MARKET_CCL_MISSING')
        if local_ref is None or local_ref<=0:blockers.append('LOCAL_ENTRY_REFERENCE_MISSING')
        bull_target=_num(row.get('bull_target_price'));base_target=_num(row.get('base_target_price'));bear_target=_num(row.get('bear_target_price'));stress_target=_num(row.get('stress_target_price'))
        valuation_status=str(row.get('valuation_status') or 'BLOCKED_BY_VALUATION_DATA')
        if valuation_status not in {'VALUATION_READY','VALUATION_READY_WITH_WARNING'}:blockers.append('VALUATION_NOT_READY')
        if any(x is None or x<=0 for x in (bull_target,base_target,bear_target)):blockers.append('SCENARIO_TARGETS_MISSING_OR_INVALID')
        if stress_target is None or stress_target<=0:blockers.append('STRESS_TARGET_MISSING_OR_INVALID')
        elif bear_target is not None and not stress_target<=bear_target:blockers.append('STRESS_BEAR_ORDERING_INVALID')
        stress_probability=_num(row.get('stress_probability'))
        if stress_probability is None or abs(stress_probability)>1e-12:blockers.append('STRESS_PROBABILITY_MUST_BE_ZERO')
        probs_valid,bull_p,base_p,bear_p=_validate_probabilities(row)
        if not probs_valid:blockers.append('SCENARIO_PROBABILITIES_INVALID')
        fit_status=str(row.get('portfolio_fit_status') or 'BLOCKED_BY_CORRELATION_DATA');diversification_score=_num(row.get('diversification_score'));max_corr=_num(row.get('max_corr_to_portfolio'))
        if fit_status!='PORTFOLIO_FIT_QUANT_READY' or diversification_score is None:blockers.append('PORTFOLIO_FIT_NOT_READY')
        confidence=_num(row.get('valuation_confidence'))
        if confidence is None or not 0<=confidence<=1:blockers.append('VALUATION_CONFIDENCE_MISSING')
        execution_ready=str(row.get('execution_book_status') or 'NOT_EXECUTABLE')=='EXECUTABLE_BOOK_READY';existing_weight=float(existing_weights.get(ticker,0));projected_weight=existing_weight+policy.candidate_test_weight_nav;hard_concentration_fail=projected_weight>policy.max_single_name_weight+1e-12
        result={'cedear_ticker':ticker,'valuation_method':row.get('valuation_method'),'valuation_status':valuation_status,'valuation_confidence':confidence,'local_gate':local_gate,'execution_ready':execution_ready,'portfolio_fit_status':fit_status,'diversification_score':diversification_score,'max_corr_to_portfolio':max_corr,'existing_weight':existing_weight,'candidate_test_weight_nav':policy.candidate_test_weight_nav,'projected_weight':projected_weight,'cash_hurdle':policy.cash_hurdle,'minimum_margin_over_hurdle':policy.minimum_margin_over_hurdle,'max_bear_downside_allowed':policy.max_bear_downside,'preservation_gate_scenario':'STRESS','blockers':blockers.copy()}
        if blockers:
            result.update({'bull_return_net':None,'base_return_net':None,'bear_return_net':None,'stress_return_net':None,'expected_return_net':None,'uncertainty_penalty':None,'correlation_penalty':None,'concentration_penalty':None,'risk_adjusted_er':None,'net_benefit_vs_cash':None,'g4_status':'BLOCKED_BY_DATA','g4_reason':';'.join(blockers)});rows.append(result);continue
        spread_pct=_num(row.get('spread_pct'));exit_spread_assumption=min(max((spread_pct or 0)/2,0),.02);analytical_entry_ars=local_ref*(1+brokerage_rate+exit_spread_assumption)
        bull_return=_scenario_return(bull_target,ratio,market_ccl,analytical_entry_ars,brokerage_rate,exit_spread_assumption);base_return=_scenario_return(base_target,ratio,market_ccl,analytical_entry_ars,brokerage_rate,exit_spread_assumption);bear_return=_scenario_return(bear_target,ratio,market_ccl,analytical_entry_ars,brokerage_rate,exit_spread_assumption);stress_return=_scenario_return(stress_target,ratio,market_ccl,analytical_entry_ars,brokerage_rate,exit_spread_assumption)
        expected=bull_p*bull_return+base_p*base_return+bear_p*bear_return
        uncertainty_penalty=(1-confidence)*policy.uncertainty_penalty_max+(policy.local_warning_penalty if local_gate=='PASS_WITH_WARNING' else 0)
        correlation_penalty=0
        if max_corr is not None and max_corr>policy.correlation_warning:correlation_penalty=min((max_corr-policy.correlation_warning)/max(1-policy.correlation_warning,1e-9)*policy.correlation_penalty_max,policy.correlation_penalty_max)
        concentration_penalty=0
        if projected_weight>policy.soft_single_name_weight:concentration_penalty=min((projected_weight-policy.soft_single_name_weight)/max(policy.max_single_name_weight-policy.soft_single_name_weight,1e-9)*policy.concentration_penalty_max,policy.concentration_penalty_max)
        risk_adjusted_er=expected-uncertainty_penalty-correlation_penalty-concentration_penalty;net_benefit=risk_adjusted_er-policy.cash_hurdle;downside_ok=stress_return>=policy.max_bear_downside;return_ok=net_benefit>=policy.minimum_margin_over_hurdle
        if hard_concentration_fail:g4_status='G4_FAIL_CONCENTRATION';reason='PROJECTED_SINGLE_NAME_WEIGHT_ABOVE_HARD_LIMIT'
        elif not downside_ok:g4_status='G4_FAIL_DOWNSIDE';reason='STRESS_DOWNSIDE_EXCEEDS_POLICY'
        elif not return_ok:g4_status='G4_FAIL_RETURN';reason='INSUFFICIENT_RISK_ADJUSTED_MARGIN_VS_CASH'
        else:g4_status='G4_PASS';reason='POSITIVE_MARGIN_VS_CASH_AND_STRESS_DOWNSIDE_COMPATIBLE'
        result.update({'bull_return_net':bull_return,'base_return_net':base_return,'bear_return_net':bear_return,'stress_return_net':stress_return,'expected_return_net':expected,'uncertainty_penalty':uncertainty_penalty,'correlation_penalty':correlation_penalty,'concentration_penalty':concentration_penalty,'risk_adjusted_er':risk_adjusted_er,'net_benefit_vs_cash':net_benefit,'g4_status':g4_status,'g4_reason':reason,'analytical_entry_ars':analytical_entry_ars,'exit_spread_assumption':exit_spread_assumption,'bull_probability':bull_p,'base_probability':base_p,'bear_probability':bear_p,'stress_probability':stress_probability});rows.append(result)
    result_df=pd.DataFrame(rows)
    if not result_df.empty:result_df['g4_rank']=result_df['net_benefit_vs_cash'].rank(method='min',ascending=False,na_option='bottom');result_df=result_df.sort_values(['g4_rank','cedear_ticker'],na_position='last').reset_index(drop=True)
    total=len(result_df);pass_count=int((result_df['g4_status']=='G4_PASS').sum()) if total else 0;blocked_count=int((result_df['g4_status']=='BLOCKED_BY_DATA').sum()) if total else 0;evaluated_count=total-blocked_count
    cash_optimality='NOT_DEMONSTRATED' if total==0 or blocked_count else ('CASH_NOT_OPTIMAL_BY_MODEL' if pass_count else 'CASH_OPTIMAL_BY_MODEL')
    metrics={'methodology_version':'G4-1.0','ticker_count':total,'evaluated_count':evaluated_count,'blocked_count':blocked_count,'pass_count':pass_count,'fail_count':evaluated_count-pass_count,'cash_hurdle':policy.cash_hurdle,'cash_optimality_status':cash_optimality,'deployment_decision':'ALLOW_NEW_DEPLOYMENT' if pass_count else ('RESEARCH_BLOCKED' if blocked_count else 'NO_NEW_DEPLOYMENT'),'return_currency':'USD_ECONOMIC_RETURN','execution_separate_from_analytical_g4':True,'preservation_gate_scenario':'STRESS','probabilistic_bear_used_in_expected_return':True,'stress_probability_weighted':False,'note':'G4-2.1 thresholds unchanged. Expected return uses Bull/Base/probabilistic Bear; preservation gate uses zero-probability severe Stress.'}
    return result_df,metrics
