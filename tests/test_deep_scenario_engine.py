import pandas as pd
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY = {
 'methodology_version':'SCENARIO-2.0',
 'identity':{'eps_pe_to_price_ratio_min':.55,'eps_pe_to_price_ratio_max':1.80},
 'sector_overrides':{'MFG':'FINANCIALS','MUFG':'FINANCIALS','NMR':'FINANCIALS','RDS':'ENERGY','SHEL':'ENERGY','PBR':'ENERGY'},
 'corporate':{'consensus_base_blend':.20,'bear_eps_compression':.18,'bear_multiple_factor':.78,'base_pe_floor':6,'base_pe_cap':25,'bull_multiple_factor':1.12,'bull_pe_cap':30},
 'financials':{'roe_floor':.04,'roe_cap':.22,'cost_of_equity_anchor':.10,'base_pb_anchor':1,'roe_pb_sensitivity':3,'base_pb_floor':.45,'base_pb_cap':2.2,'consensus_base_blend':.2,'bear_pb_factor':.72,'bear_pb_floor':.35,'bull_pb_factor':1.2,'bull_pb_cap':2.75},
 'energy':{'base_pe_floor':5,'base_pe_cap':14,'earnings_weight':.65,'normalized_fcf_yield':.08,'consensus_base_blend':.15,'bear_cycle_factor':.72,'bull_cycle_factor':1.28,'dividend_credit':.5},
 'consensus':{'dispersion_review_threshold':.75,'high_distance_from_median_cap':.50},
 'plausibility':{'max_standard_bull_upside':.60},
 'probabilities':{'base_probability':.50,'bull_min':.15,'bull_max':.27,'dispersion_penalty_start':.50,'dispersion_bull_penalty_max':.07},
}

def _row(ticker,current,high,median,low,eps,pe,growth,confidence=.60,de=.8,**extra):
 r={'cedear_ticker':ticker,'underlying_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_method':'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4','valuation_status':'VALUATION_READY','current_price':current,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':eps,'fundamental_pe_normalized':pe,'fundamental_eps_growth_3y':growth,'fundamental_debt_to_equity':de,'valuation_confidence':confidence,'eps_unit':'UNDERLYING_SECURITY','target_price_unit':'UNDERLYING_SECURITY'}
 r.update(extra); return r

def test_rds_extreme_consensus_high_cannot_inflate_bull():
 df=pd.DataFrame([_row('RDS',95.32,199.24,110.99,84.38,8.0,11.9,.08,.65,.55,fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)])
 out,m=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert m['scenario_validated_count']==1
 assert r['scenario_validated']
 assert r['scenario_sector_model']=='ENERGY'
 assert r['bull_target_price'] <= 95.32*1.60
 assert r['bull_target_price'] < 199.24
 assert 'CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY' in r['scenario_review_flags']

def test_pbi_bear_is_fundamental_not_analyst_low_and_not_destroyed_by_raw_debt_equity():
 df=pd.DataFrame([_row('PBI',16.99,23.10,19.63,17.47,1.625,10.45,.12,.595,37.0)])
 out,_=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert r['scenario_validated']
 assert r['scenario_sector_model']=='CORPORATE'
 assert r['bear_target_price'] != 17.47
 assert r['bear_target_price'] < r['base_target_price'] < r['bull_target_price']

def test_financial_uses_pb_roe_and_ignores_corporate_debt_equity_stress():
 df=pd.DataFrame([_row('MFG',14.0,18,16,10,.82,17.0,.10,.65,6.0,fundamental_book_value_per_share=13.0,fundamental_price_to_book=1.08,fundamental_roe=10.5)])
 out,_=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert r['scenario_validated']
 assert r['scenario_sector_model']=='FINANCIALS'
 assert 'DEBT_EQUITY_NOT_USED_FOR_FINANCIALS' in r['scenario_review_flags']
 assert r['bear_target_price'] < r['base_target_price'] < r['bull_target_price']

def test_identity_mismatch_fails_closed_before_scenario():
 df=pd.DataFrame([_row('RDS',95.32,199.24,110.99,84.38,2.9985,11.0382,.08,.65,.55,fundamental_fcf_yield=.08)])
 out,m=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert 'ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH' in r['scenario_review_blockers']
 assert m['scenario_blocked_count']==1

def test_explicit_eps_target_unit_mismatch_fails_closed():
 df=pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,eps_unit='ORDINARY_SHARE',target_price_unit='ADR')])
 out,_=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert 'ECONOMIC_IDENTITY_TARGET_EPS_UNIT_MISMATCH' in r['scenario_review_blockers']

def test_missing_fundamentals_fail_closed_never_fabricate_scenario():
 df=pd.DataFrame([_row('PBI',16.99,23.10,19.63,17.47,None,10.45,.12)])
 out,m=validate_scenarios(df,POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert 'ECONOMIC_IDENTITY_EPS_PE_UNVERIFIABLE' in r['scenario_review_blockers']
 assert m['scenario_blocked_count']==1

def test_probabilities_are_dynamic():
 a=_row('AAA',100,130,110,80,5,20,.10,.9); b=_row('BBB',100,130,110,80,5,20,.10,.3)
 out,_=validate_scenarios(pd.DataFrame([a,b]),POLICY)
 assert out.iloc[0]['bull_probability'] != out.iloc[1]['bull_probability']
 assert abs(out.iloc[0]['bull_probability']+.5+out.iloc[0]['bear_probability']-1)<1e-9
