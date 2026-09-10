import pandas as pd
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY={
 'methodology_version':'SCENARIO-2.1','identity':{'eps_pe_to_price_ratio_min':.55,'eps_pe_to_price_ratio_max':1.80},
 'sector_overrides':{'RDS':'ENERGY','SHEL':'ENERGY'},
 'sector_classification':{'corporate_keywords':['TECHNOLOGY','SOFTWARE','HEALTH','CONSUMER','INDUSTRIAL','TRANSPORT']},
 'corporate':{'consensus_base_blend':.20,'bear_eps_compression':.18,'bear_multiple_factor':.78,'base_pe_floor':6,'base_pe_cap':25,'bull_multiple_factor':1.12,'bull_pe_cap':30},
 'financials':{'roe_floor':.04,'roe_cap':.22,'cost_of_equity_anchor':.10,'base_pb_anchor':1,'roe_pb_sensitivity':3,'base_pb_floor':.45,'base_pb_cap':2.2,'consensus_base_blend':.2,'bear_pb_factor':.72,'bear_pb_floor':.35,'bull_pb_factor':1.2,'bull_pb_cap':2.75},
 'energy':{'base_pe_floor':5,'base_pe_cap':14,'earnings_weight':.65,'normalized_fcf_yield':.08,'consensus_base_blend':.15,'bear_cycle_factor':.72,'bull_cycle_factor':1.28,'dividend_credit':.5},
 'consensus':{'dispersion_review_threshold':.75,'high_distance_from_median_cap':.50},'plausibility':{'max_standard_bull_upside':.60},'probabilities':{'base_probability':.50,'bull_min':.15,'bull_max':.27,'dispersion_penalty_start':.50,'dispersion_bull_penalty_max':.07}}

def _row(ticker,current,high,median,low,eps,pe,growth,confidence=.60,de=.8,sector='Technology',**extra):
 r={'cedear_ticker':ticker,'underlying_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_method':'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4','valuation_status':'VALUATION_READY','current_price':current,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':eps,'fundamental_pe_normalized':pe,'fundamental_eps_growth_3y':growth,'fundamental_debt_to_equity':de,'valuation_confidence':confidence,'eps_unit':'UNDERLYING_SECURITY','target_price_unit':'UNDERLYING_SECURITY','industry_sector_official':sector,'issuer_country_normalized':'US','underlying_market_official':'NASDAQ GS'}; r.update(extra); return r

def test_pbi_positive_control_validates_corporate_identity():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',17.17,23.1,19.63,12,.8362,16.2674,.12,.60,.8,sector='Technology')]),POLICY); r=out.iloc[0]
 assert m['scenario_validated_count']==1 and r['scenario_validated']; assert r['scenario_sector_model']=='CORPORATE'; assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_jpm_routes_to_financials_from_official_sector_not_override():
 out,_=validate_scenarios(pd.DataFrame([_row('JPM',200,240,220,160,10,20,.08,.7,4,sector='Financial Services',fundamental_book_value_per_share=110,fundamental_price_to_book=1.8,fundamental_roe=18)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='FINANCIALS'; assert r['scenario_sector_source']=='COMAFI_OR_PROVIDER_METADATA'; assert 'DEBT_EQUITY_NOT_USED_FOR_FINANCIALS' in r['scenario_review_flags']

def test_cvx_routes_to_energy_from_official_sector():
 out,_=validate_scenarios(pd.DataFrame([_row('CVX',160,200,180,120,12,13,.05,.7,.3,sector='Energy',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='ENERGY'; assert 'ENERGY_CYCLE_NORMALIZATION_APPLIED' in r['scenario_review_flags']

def test_unknown_sector_fails_closed_never_defaults_corporate():
 out,m=validate_scenarios(pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,sector='')]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert r['scenario_sector_model'] is None; assert 'SECTOR_CLASSIFICATION_UNVERIFIED' in r['scenario_review_blockers']; assert m['scenario_blocked_count']==1

def test_foreign_adr_unit_mismatch_fails_closed_without_verified_normalization():
 out,_=validate_scenarios(pd.DataFrame([_row('SHEL',95.6,125,110,70,2.9985,15.2218,.08,.65,.4,sector='Energy',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_fcf_yield=.08)]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH' in r['scenario_review_blockers']; assert 'ADR_OR_FOREIGN_SHARE_NORMALIZATION_REQUIRED' in r['scenario_review_flags']

def test_verified_adr_ratio_normalization_can_reconcile_identity():
 # Synthetic ADR: fundamentals are per ordinary share; one ADR represents two shares.
 out,_=validate_scenarios(pd.DataFrame([_row('ADR2',100,130,110,75,2.5,20,.08,.65,.4,sector='Energy',issuer_country_normalized='GB',underlying_market_official='New York',adr_shares_per_depositary_receipt=2,economic_unit_normalization_verified=True,fundamental_fcf_yield=.08)]),POLICY); r=out.iloc[0]
 assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['identity_adr_ratio_applied']==2; assert r['scenario_validated']

def test_explicit_eps_target_unit_mismatch_fails_closed():
 out,_=validate_scenarios(pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,eps_unit='ORDINARY_SHARE',target_price_unit='ADR')]),POLICY); assert 'ECONOMIC_IDENTITY_TARGET_EPS_UNIT_MISMATCH' in out.iloc[0]['scenario_review_blockers']

def test_missing_fundamentals_fail_closed_never_fabricate_scenario():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',16.99,23.1,19.63,17.47,None,10.45,.12)]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'ECONOMIC_IDENTITY_EPS_PE_UNVERIFIABLE' in r['scenario_review_blockers']; assert m['scenario_blocked_count']==1

def test_rds_extreme_consensus_high_cannot_inflate_bull():
 out,_=validate_scenarios(pd.DataFrame([_row('RDS',95.32,199.24,110.99,84.38,8,11.9,.08,.65,.55,sector='',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated']; assert r['scenario_sector_model']=='ENERGY'; assert r['bull_target_price']<=95.32*1.60; assert 'CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY' in r['scenario_review_flags']

def test_probabilities_are_dynamic():
 a=_row('AAA',100,130,110,80,5,20,.10,.9); b=_row('BBB',100,130,110,80,5,20,.10,.3); out,_=validate_scenarios(pd.DataFrame([a,b]),POLICY); assert out.iloc[0]['bull_probability']!=out.iloc[1]['bull_probability']; assert abs(out.iloc[0]['bull_probability']+.5+out.iloc[0]['bear_probability']-1)<1e-9
