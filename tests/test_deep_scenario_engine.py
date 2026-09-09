import pandas as pd
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY={
 'methodology_version':'SCENARIO-TEST',
 'equity':{'consensus_base_blend':.20,'bear_eps_compression':.18,'bear_multiple_factor':.78,'base_pe_floor':6,'base_pe_cap':25,'bull_multiple_factor':1.12,'bull_pe_cap':30},
 'consensus':{'dispersion_review_threshold':.75,'high_distance_from_median_cap':.50},
 'plausibility':{'max_standard_bull_upside':.60},
 'probabilities':{'base_probability':.50,'bull_min':.15,'bull_max':.27,'dispersion_penalty_start':.50,'dispersion_bull_penalty_max':.07},
}

def _row(ticker,current,high,median,low,eps,pe,growth,confidence=.60,de=.8):
 return {'cedear_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_method':'FINNHUB_ANALYST_CONSENSUS_SCREENING_V3','valuation_status':'VALUATION_READY','current_price':current,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':eps,'fundamental_pe_normalized':pe,'fundamental_eps_growth_3y':growth,'fundamental_debt_to_equity':de,'valuation_confidence':confidence}

def test_rds_extreme_consensus_high_cannot_inflate_bull_to_105_percent():
 df=pd.DataFrame([_row('RDS',95.32,199.24,110.99,84.38,8.0,11.9,.08,.65,.55)])
 out,m=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert m['scenario_validated_count']==1
 assert r['scenario_validated']
 assert r['bull_target_price'] <= 95.32*1.60
 assert r['bull_target_price'] < 199.24
 assert 'CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY' in r['scenario_review_flags']
 assert r['bear_is_independent_of_analyst_low'] is True or bool(r['bear_is_independent_of_analyst_low'])

def test_pbi_bear_is_fundamental_not_analyst_low():
 df=pd.DataFrame([_row('PBI',16.99,23.10,19.63,17.47,1.625,10.45,.12,.595,1.2)])
 out,_=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert r['scenario_validated']
 assert r['bear_target_price'] != 17.47
 assert r['bear_target_price'] < r['base_target_price'] < r['bull_target_price']
 assert abs(r['bull_probability']+.5+r['bear_probability']-1)<1e-9

def test_missing_fundamentals_fail_closed_never_fabricate_scenario():
 df=pd.DataFrame([_row('PBI',16.99,23.10,19.63,17.47,None,10.45,.12)])
 out,m=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert r['scenario_review_status']=='SCENARIO_NOT_VALIDATED'
 assert 'FUNDAMENTAL_EPS_MISSING_OR_NONPOSITIVE' in r['scenario_review_blockers']
 assert m['scenario_blocked_count']==1

def test_probabilities_are_not_fixed_25_50_25_when_confidence_differs():
 a=_row('AAA',100,130,110,80,5,20,.10,.9)
 b=_row('BBB',100,130,110,80,5,20,.10,.3)
 out,_=validate_scenarios(pd.DataFrame([a,b]),POLICY)
 assert out.iloc[0]['bull_probability'] != out.iloc[1]['bull_probability']
 assert out.iloc[0]['bull_probability'] != .25 or out.iloc[0]['bear_probability'] != .25
