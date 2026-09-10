from pathlib import Path
import pandas as pd
import yaml
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY=yaml.safe_load(Path('config/scenario_review_policy.yml').read_text())

def row(ticker='AAA',confidence=.7,high=140,median=115,low=85):
    return {'cedear_ticker':ticker,'underlying_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_status':'VALUATION_READY','current_price':100.,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':5.,'fundamental_pe_normalized':20.,'fundamental_eps_growth_3y':.10,'fundamental_debt_to_equity':.8,'valuation_confidence':confidence,'eps_unit':'UNDERLYING_SECURITY','target_price_unit':'UNDERLYING_SECURITY','industry_sector_official':'Technology','issuer_country_normalized':'US','underlying_market_official':'NASDAQ GS'}

def test_v23_separates_stress_from_probabilistic_bear():
    out,m=validate_scenarios(pd.DataFrame([row()]),POLICY); r=out.iloc[0]
    assert m['scenario_methodology_version']=='SCENARIO-2.3'
    assert m['stress_separated_from_probabilistic_distribution'] is True
    assert r['scenario_validated']
    assert 0 < r['stress_target_price'] < r['bear_target_price'] < r['base_target_price'] < r['bull_target_price']
    assert r['stress_probability']==0
    assert 'STRESS_SEPARATED_FROM_PROBABILISTIC_BEAR' in r['scenario_review_flags']

def test_v23_probabilities_sum_to_one_and_base_is_dynamic():
    out,_=validate_scenarios(pd.DataFrame([row('HIGH',.9),row('LOW',.3)]),POLICY)
    for _,r in out.iterrows():
        assert abs(r['bull_probability']+r['base_probability']+r['bear_probability']-1)<1e-12
        assert r['bear_probability']>=POLICY['probabilities']['bear_min']
    assert out.iloc[0]['base_probability'] > out.iloc[1]['base_probability']

def test_v23_low_confidence_moves_probabilistic_bear_toward_stress():
    out,_=validate_scenarios(pd.DataFrame([row('HIGH',.9),row('LOW',.2)]),POLICY)
    def normalized_distance(r): return (r['base_target_price']-r['bear_target_price'])/(r['base_target_price']-r['stress_target_price'])
    assert normalized_distance(out.iloc[1]) > normalized_distance(out.iloc[0])

def test_v23_extreme_analyst_low_cannot_turn_probabilistic_bear_into_stress():
    out,_=validate_scenarios(pd.DataFrame([row(low=1)]),POLICY); r=out.iloc[0]
    assert r['scenario_validated']; assert r['stress_target_price'] < r['bear_target_price'] < r['base_target_price']
    assert 'CONSENSUS_LOW_CLIPPED_TO_PROBABILISTIC_RANGE' in r['scenario_review_flags']

def test_v23_stress_formula_is_retained_not_deleted():
    r=validate_scenarios(pd.DataFrame([row()]),POLICY)[0].iloc[0]
    expected=5*(1-.18)*(20*.78)
    assert abs(r['stress_target_price']-expected)<1e-9
    assert r['bear_target_price']>r['stress_target_price']

def test_non_equity_remains_fail_closed_and_explicitly_marks_stress_proxy():
    x={'cedear_ticker':'EEM','valuation_engine_type':'ETF','valuation_status':'BLOCKED_BY_DATA','bull_target_price':None,'base_target_price':None,'bear_target_price':None,'bull_probability':None,'base_probability':None,'bear_probability':None}
    out,_=validate_scenarios(pd.DataFrame([x]),POLICY); r=out.iloc[0]
    assert not r['scenario_validated']; assert 'UPSTREAM_VALUATION_NOT_READY' in r['scenario_review_blockers']; assert r['scenario_method']=='NON_EQUITY_TRACKER_FAIL_CLOSED_V2_3'
