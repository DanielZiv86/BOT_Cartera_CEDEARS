from __future__ import annotations
import pandas as pd
from src.orchestration.build_g4_cash_hurdle import _add_execution_gate,_apply_global_governance
from src.valuation.g4 import G4Policy,calculate_g4_cash_hurdle
from src.valuation.g4_review import apply_extreme_target_review

def _base_local():return pd.DataFrame([{'cedear_ticker':'TEST','valuation_g4_local_gate':'PASS','ratio_used':10.,'market_ccl_reference':1600.,'analytical_local_ref_ars':16000.,'spread_pct':.01,'execution_book_status':'EXECUTABLE_BOOK_READY'}])
def _fit():return pd.DataFrame([{'cedear_ticker':'TEST','portfolio_fit_status':'PORTFOLIO_FIT_QUANT_READY','diversification_score':80.,'max_corr_to_portfolio':.50}])
def _positions():return pd.DataFrame([{'cedear_ticker':'OTHER','weight':.30}])
def _valuation(**overrides):
    x={'cedear_ticker':'TEST','valuation_method':'TEST_MODEL','valuation_status':'VALUATION_READY','valuation_confidence':.90,'current_price':100.,'bull_target_price':140.,'base_target_price':125.,'bear_target_price':105.,'stress_target_price':95.,'stress_probability':0.,'bull_probability':.25,'base_probability':.55,'bear_probability':.20};x.update(overrides);return pd.DataFrame([x])

def test_g4_pass_when_margin_and_stress_downside_are_sufficient():
    result,metrics=calculate_g4_cash_hurdle(_base_local(),_valuation(),_fit(),_positions(),policy=G4Policy(),brokerage_rate=.006);r=result.iloc[0]
    assert r['g4_status']=='G4_PASS';assert r['risk_adjusted_er']>r['cash_hurdle'];assert r['stress_return_net']>=-.15;assert r['preservation_gate_scenario']=='STRESS';assert metrics['cash_optimality_status']=='CASH_NOT_OPTIMAL_BY_MODEL'

def test_missing_valuation_never_passes():
    result,metrics=calculate_g4_cash_hurdle(_base_local(),pd.DataFrame(columns=['cedear_ticker']),_fit(),_positions());assert result.iloc[0]['g4_status']=='BLOCKED_BY_DATA';assert metrics['cash_optimality_status']=='NOT_DEMONSTRATED'

def test_probabilistic_bear_can_be_acceptable_but_stress_still_fails_preservation():
    result,_=calculate_g4_cash_hurdle(_base_local(),_valuation(bull_target_price=180.,base_target_price=150.,bear_target_price=100.,stress_target_price=70.,bull_probability=.35,base_probability=.55,bear_probability=.10,valuation_confidence=.95),_fit(),_positions());r=result.iloc[0]
    assert r['bear_return_net']>r['stress_return_net'];assert r['g4_status']=='G4_FAIL_DOWNSIDE';assert r['g4_reason']=='STRESS_DOWNSIDE_EXCEEDS_POLICY'

def test_stress_is_not_probability_weighted_into_expected_return():
    result,_=calculate_g4_cash_hurdle(_base_local(),_valuation(stress_target_price=80.),_fit(),_positions());r=result.iloc[0];expected=r['bull_probability']*r['bull_return_net']+r['base_probability']*r['base_return_net']+r['bear_probability']*r['bear_return_net'];assert abs(r['expected_return_net']-expected)<1e-12

def test_nonzero_stress_probability_blocks_candidate():
    result,_=calculate_g4_cash_hurdle(_base_local(),_valuation(stress_probability=.01),_fit(),_positions());assert result.iloc[0]['g4_status']=='BLOCKED_BY_DATA';assert 'STRESS_PROBABILITY_MUST_BE_ZERO' in result.iloc[0]['g4_reason']

def test_invalid_probabilities_block_ticker():
    result,_=calculate_g4_cash_hurdle(_base_local(),_valuation(bull_probability=.5,base_probability=.5,bear_probability=.5),_fit(),_positions());assert result.iloc[0]['g4_status']=='BLOCKED_BY_DATA';assert 'SCENARIO_PROBABILITIES_INVALID' in result.iloc[0]['g4_reason']

def test_incomplete_universe_blocks_global_deployment_even_with_passes():
    g=_apply_global_governance({'ticker_count':305,'blocked_count':80,'pass_count':90,'clean_g4_pass_count':60,'extreme_target_review_required_count':30,'deployment_decision':'ALLOW_NEW_DEPLOYMENT'});assert g['deployment_decision']=='RESEARCH_BLOCKED'

def test_extreme_target_pass_is_flagged_and_not_clean_actionable():
    valuation=pd.DataFrame([{'cedear_ticker':'TEST','current_price':100.,'bull_target_price':240.,'base_target_price':180.,'bear_target_price':80.}]);economic=pd.DataFrame([{'cedear_ticker':'TEST','g4_status':'G4_PASS','net_benefit_vs_cash':.25}]);reviewed,metrics=apply_extreme_target_review(economic,valuation,{'target_review':{'base_upside_review_threshold':.75,'bull_upside_review_threshold':1.25,'high_low_dispersion_review_threshold':1.}});assert reviewed.iloc[0]['target_review_status']=='EXTREME_TARGET_REQUIRES_REVIEW';assert metrics['clean_g4_pass_count']==0

def test_execution_gate_accepts_current_canonical_local_market_statuses():
    economic=pd.DataFrame([{'cedear_ticker':'CIBR','g4_status':'G4_FAIL_DOWNSIDE'}]);local=pd.DataFrame([{'cedear_ticker':'CIBR','execution_book_status':'BOOK_EXECUTABLE_BY_SANITY','executable_buy_ars':12345.,'ratio_status':'RATIO_VALIDATED_CANONICAL_CCL','ccl_status':'CCL_READY_VALIDATED_CANONICAL','market_session_status':'OPEN'}]);out=_add_execution_gate(economic,local);assert bool(out.iloc[0]['analysis_ready']);assert bool(out.iloc[0]['execution_ready'])

def test_execution_gate_remains_fail_closed_without_executable_book():
    economic=pd.DataFrame([{'cedear_ticker':'TEST','g4_status':'G4_FAIL_RETURN'}]);local=pd.DataFrame([{'cedear_ticker':'TEST','execution_book_status':'BOOK_NOT_EXECUTABLE','executable_buy_ars':12345.,'ratio_status':'RATIO_VALIDATED_CANONICAL_CCL','ccl_status':'CCL_READY_VALIDATED_CANONICAL','market_session_status':'OPEN'}]);out=_add_execution_gate(economic,local);assert not bool(out.iloc[0]['execution_ready'])
