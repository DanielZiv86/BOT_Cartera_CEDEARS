import pandas as pd
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY={
 'methodology_version':'SCENARIO-2.1','identity':{'eps_pe_to_price_ratio_min':.55,'eps_pe_to_price_ratio_max':1.80,'verified_adr_ratios':{'HSBC':{'ordinary_shares_per_ads':5,'source':'HSBC_OFFICIAL'},'RDS':{'ordinary_shares_per_ads':2,'source':'SHELL_OFFICIAL'},'TXR':{'ordinary_shares_per_ads':10,'source':'TERNIUM_OFFICIAL'},'VOD':{'ordinary_shares_per_ads':10,'source':'VODAFONE_OFFICIAL'}}},
 'sector_overrides':{'RDS':'ENERGY','SHEL':'ENERGY'},
 'sector_classification':{'corporate_keywords':['TECHNOLOGY','SOFTWARE','HEALTH','CONSUMER','INDUSTRIAL','TRANSPORT','TELECOM']},
 'corporate':{'consensus_base_blend':.20,'bear_eps_compression':.18,'bear_multiple_factor':.78,'base_pe_floor':6,'base_pe_cap':25,'bull_multiple_factor':1.12,'bull_pe_cap':30},
 'financials':{'roe_floor':.04,'roe_cap':.22,'cost_of_equity_anchor':.10,'base_pb_anchor':1,'roe_pb_sensitivity':3,'base_pb_floor':.45,'base_pb_cap':2.2,'consensus_base_blend':.2,'bear_pb_factor':.72,'bear_pb_floor':.35,'bull_pb_factor':1.2,'bull_pb_cap':2.75,'minimum_bull_premium_to_base':.10},
 'energy':{'base_pe_floor':5,'base_pe_cap':14,'earnings_weight':.65,'normalized_fcf_yield':.08,'consensus_base_blend':.15,'bear_cycle_factor':.72,'bull_cycle_factor':1.28,'dividend_credit':.5},
 'consensus':{'dispersion_review_threshold':.75,'high_distance_from_median_cap':.50},'plausibility':{'max_standard_bull_upside':.60},'probabilities':{'base_probability':.50,'bull_min':.15,'bull_max':.27,'dispersion_penalty_start':.50,'dispersion_bull_penalty_max':.07}}

def _row(ticker,current,high,median,low,eps,pe,growth,confidence=.60,de=.8,sector='Technology',**extra):
 r={'cedear_ticker':ticker,'underlying_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_method':'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4','valuation_status':'VALUATION_READY','current_price':current,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':eps,'fundamental_pe_normalized':pe,'fundamental_eps_growth_3y':growth,'fundamental_debt_to_equity':de,'valuation_confidence':confidence,'eps_unit':'UNDERLYING_SECURITY','target_price_unit':'UNDERLYING_SECURITY','industry_sector_official':sector,'issuer_country_normalized':'US','underlying_market_official':'NASDAQ GS'}; r.update(extra); return r

def test_pbi_positive_control_validates_corporate_identity():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',17.17,23.1,19.63,12,.8362,16.2674,.12,.60,.8,sector='Technology')]),POLICY); r=out.iloc[0]
 assert m['scenario_validated_count']==1 and r['scenario_validated']; assert r['scenario_sector_model']=='CORPORATE'; assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_jpm_routes_to_financials_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('JPM',354.71,450,378.42,250,16.95,20,.08,.7,4,sector='Financial Services',fundamental_book_value_per_share=134.4218,fundamental_price_to_book=2.4202,fundamental_roe=15.74)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='FINANCIALS'; assert r['scenario_sector_source']=='COMAFI_OR_PROVIDER_METADATA'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']; assert r['scenario_validated']

def test_visa_financial_ordering_regression():
 out,_=validate_scenarios(pd.DataFrame([_row('V',367.39,500,428.4,300,18.47,18.91,.10,.7,1,sector='Financial Services',fundamental_book_value_per_share=19.7892,fundamental_price_to_book=17.2671,fundamental_roe=52.91)]),POLICY); r=out.iloc[0]
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']; assert 'FUNDAMENTAL_SCENARIO_ORDER_INVALID' not in r['scenario_review_blockers']

def test_cvx_routes_to_energy_from_official_sector():
 out,_=validate_scenarios(pd.DataFrame([_row('CVX',160,200,180,120,12,13,.05,.7,.3,sector='Energy',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='ENERGY'; assert 'ENERGY_CYCLE_NORMALIZATION_APPLIED' in r['scenario_review_flags']

def test_unknown_sector_fails_closed_never_defaults_corporate():
 out,m=validate_scenarios(pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,sector='')]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert r['scenario_sector_model'] is None; assert 'SECTOR_CLASSIFICATION_UNVERIFIED' in r['scenario_review_blockers']; assert m['scenario_blocked_count']==1

def test_foreign_adr_unit_mismatch_fails_closed_without_verified_normalization():
 out,_=validate_scenarios(pd.DataFrame([_row('UNKNOWNADR',95.6,125,110,70,2.9985,15.2218,.08,.65,.4,sector='Energy',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_fcf_yield=.08)]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH' in r['scenario_review_blockers']; assert 'ADR_OR_FOREIGN_SHARE_NORMALIZATION_REQUIRED' in r['scenario_review_flags']

def test_verified_adr_ratio_normalization_can_reconcile_identity():
 out,_=validate_scenarios(pd.DataFrame([_row('HSBC',105.11,140,107.69,75,4.17,5,.08,.65,.4,sector='Financial Services',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_book_value_per_share=11.5413,fundamental_price_to_book=1.3789,fundamental_roe=11.24)]),POLICY); r=out.iloc[0]
 assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['identity_adr_ratio_applied']==5; assert r['identity_adr_ratio_verified']; assert 'VERIFIED_ADR_RATIO_APPLIED' in r['scenario_review_flags']

def test_txr_ten_for_one_ads_reconciles_identity():
 out,_=validate_scenarios(pd.DataFrame([_row('TXR',58.11,81.9,57.63,40.4,.581,10,.08,.65,.4,sector='Industrial',issuer_country_normalized='LU',underlying_market_official='New York')]),POLICY); r=out.iloc[0]
 assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['identity_adr_ratio_applied']==10

def test_vod_negative_eps_uses_pb_identity_fallback():
 out,_=validate_scenarios(pd.DataFrame([_row('VOD',17.13,21.34,15.89,11.63,-.1,10,.08,.65,.4,sector='Telecom',issuer_country_normalized='GB',underlying_market_official='NASDAQ GS',fundamental_book_value_per_share=2.1931,fundamental_price_to_book=.6013)]),POLICY); r=out.iloc[0]
 assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['economic_identity_method']=='PB'; assert r['identity_adr_ratio_applied']==10; assert 'ECONOMIC_IDENTITY_PB_FALLBACK_APPLIED' in r['scenario_review_flags']

def test_explicit_eps_target_unit_mismatch_fails_closed():
 out,_=validate_scenarios(pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,eps_unit='ORDINARY_SHARE',target_price_unit='ADR')]),POLICY); assert 'ECONOMIC_IDENTITY_TARGET_EPS_UNIT_MISMATCH' in out.iloc[0]['scenario_review_blockers']

def test_missing_identity_fundamentals_fail_closed_never_fabricate():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',16.99,23.1,19.63,17.47,None,None,.12,fundamental_book_value_per_share=None,fundamental_price_to_book=None)]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'ECONOMIC_IDENTITY_UNVERIFIABLE' in r['scenario_review_blockers']; assert m['scenario_blocked_count']==1

def test_rds_verified_two_share_ads_and_extreme_consensus_cap():
 out,_=validate_scenarios(pd.DataFrame([_row('RDS',95.32,199.24,110.99,84.38,4,11.9,.08,.65,.55,sector='',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['identity_adr_ratio_applied']==2; assert r['scenario_validated']; assert r['bull_target_price']<=95.32*1.60; assert 'CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY' in r['scenario_review_flags']

def test_probabilities_are_dynamic():
 a=_row('AAA',100,130,110,80,5,20,.10,.9); b=_row('BBB',100,130,110,80,5,20,.10,.3); out,_=validate_scenarios(pd.DataFrame([a,b]),POLICY); assert out.iloc[0]['bull_probability']!=out.iloc[1]['bull_probability']; assert abs(out.iloc[0]['bull_probability']+.5+out.iloc[0]['bear_probability']-1)<1e-9
