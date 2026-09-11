import pandas as pd
import pytest
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY={
 'methodology_version':'SCENARIO-2.2','identity':{'eps_pe_to_price_ratio_min':.55,'eps_pe_to_price_ratio_max':1.80,'verified_adr_ratios':{'BBV':{'ordinary_shares_per_ads':1,'source':'BBVA_OFFICIAL'},'HSBC':{'ordinary_shares_per_ads':5,'source':'HSBC_OFFICIAL'},'ING':{'ordinary_shares_per_ads':1,'source':'ING_OFFICIAL'},'SAN':{'ordinary_shares_per_ads':1,'source':'SAN_OFFICIAL'},'EQNR':{'ordinary_shares_per_ads':1,'source':'EQNR_OFFICIAL'},'RDS':{'ordinary_shares_per_ads':2,'source':'SHELL_OFFICIAL'},'TXR':{'ordinary_shares_per_ads':10,'source':'TERNIUM_OFFICIAL'},'VOD':{'ordinary_shares_per_ads':10,'source':'VODAFONE_OFFICIAL'}},'verified_direct_foreign_listings':{'AEG':{'ordinary_shares_per_us_traded_share':1,'security_type':'NEW_YORK_REGISTRY_SHARE','source':'AEGON_OFFICIAL'}}},
 'sector_overrides':{'RDS':'ENERGY','SHEL':'ENERGY','V':'CORPORATE','MA':'CORPORATE'},
 'sector_classification':{'corporate_keywords':['TECHNOLOGY','SOFTWARE','SEMICONDUCTOR','HEALTH','PHARMA','CONSUMER','INDUSTRIAL','MATERIAL','COMMUNICATION','TELECOM','UTILITY','REAL ESTATE','AEROSPACE','TRANSPORT','RETAIL','FOOD','BEVERAGE']},
 'corporate':{'consensus_base_blend':.20,'consensus_bear_blend':.20,'bear_eps_compression':.18,'bear_multiple_factor':.78,'base_pe_floor':6,'pe_cap_base':15,'pe_cap_growth_sensitivity':1.5,'pe_cap_ceiling':55,'bull_multiple_factor':1.12,'base_growth_floor':-.10,'base_growth_cap':.20,'bull_growth_floor':.08,'bull_growth_increment':.08,'bull_growth_cap':.30},
 'financials':{'roe_floor':.04,'roe_cap':.22,'cost_of_equity_anchor':.10,'base_pb_anchor':1,'roe_pb_sensitivity':3,'base_pb_floor':.45,'base_pb_cap':4.0,'observed_pb_weight':.65,'fair_pb_weight':.35,'consensus_base_blend':.2,'bear_pb_factor':.72,'bear_pb_floor':.35,'bull_pb_factor':1.2,'bull_pb_cap':5.0,'minimum_bull_premium_to_base':.10},
 'energy':{'base_pe_floor':5,'base_pe_cap':14,'earnings_weight':.65,'normalized_fcf_yield':.08,'consensus_base_blend':.15,'bear_cycle_factor':.72,'bull_cycle_factor':1.28,'dividend_credit':.5,'minimum_bull_premium_to_base':.10},
 'consensus':{'dispersion_review_threshold':.75,'high_distance_from_median_cap':.50,'low_distance_from_median_floor':.50},'plausibility':{'max_standard_bull_upside':.60,'max_standard_bear_downside':.40},'probabilities':{'base_probability':.50,'bull_min':.12,'bull_max':.32,'bull_floor':.08,'bull_ceiling':.35,'dispersion_penalty_start':.50,'dispersion_bull_penalty_max':.07}}

def _row(ticker,current,high,median,low,eps,pe,growth,confidence=.60,de=.8,sector='Technology',**extra):
 r={'cedear_ticker':ticker,'underlying_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_method':'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4','valuation_status':'VALUATION_READY','current_price':current,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':eps,'fundamental_pe_normalized':pe,'fundamental_eps_growth_3y':growth,'fundamental_debt_to_equity':de,'valuation_confidence':confidence,'eps_unit':'UNDERLYING_SECURITY','target_price_unit':'UNDERLYING_SECURITY','industry_sector_official':sector,'issuer_country_normalized':'US','underlying_market_official':'NASDAQ GS'}; r.update(extra); return r

def test_pbi_positive_control_validates_corporate_identity():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',17.17,23.1,19.63,12,.8362,16.2674,.12,.60,.8,sector='Technology')]),POLICY); r=out.iloc[0]
 assert m['scenario_validated_count']==1 and r['scenario_validated']; assert r['scenario_sector_model']=='CORPORATE'; assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_jpm_routes_to_financials_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('JPM',354.71,450,378.42,250,16.95,20,.08,.7,4,sector='Financial Services',fundamental_book_value_per_share=134.4218,fundamental_price_to_book=2.4202,fundamental_roe=15.74)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='FINANCIALS'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']; assert r['scenario_validated']; assert r['base_target_price']>250; assert 'FINANCIAL_OBSERVED_PB_ANCHORED' in r['scenario_review_flags']

def test_visa_routes_to_corporate_not_bank_balance_sheet_model():
 out,_=validate_scenarios(pd.DataFrame([_row('V',367.39,500,428.4,300,10.2024,34.24,.1337,.7,1,sector='Financial Services',fundamental_book_value_per_share=19.7892,fundamental_price_to_book=17.2671,fundamental_roe=52.91)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='CORPORATE'; assert r['scenario_sector_source']=='POLICY_OVERRIDE'; assert r['scenario_validated']

def test_cvx_routes_to_energy_from_official_sector():
 out,_=validate_scenarios(pd.DataFrame([_row('CVX',160,200,180,120,12,13,.05,.7,.3,sector='Energy',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='ENERGY'; assert r['scenario_validated']; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_corporate_bear_case_blends_toward_consensus_low_instead_of_pure_mechanical_compression():
 # growth=.20 (the growth cap) gives a dynamic P/E cap of 15+1.5*20=45, well
 # above this name's actual P/E of 27, so pem is the real, unclipped 27 --
 # mechanical EPS-x-PE compression alone would put the bear case at ~-31%
 # (eps*0.82*21.06 = 69.08 vs current=100), still harsher than what analysts'
 # own low target implies (85, i.e. -15%). Blending toward that real low
 # pulls the bear case back from the mechanical extreme instead of ignoring
 # the market's own downside view entirely -- a quality name shouldn't be
 # penalized with a worse bear case than analysts themselves assign it.
 out,_=validate_scenarios(pd.DataFrame([_row('QUAL',100,180,125,85,4,27,.20,.7,.3,sector='Technology')]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 raw_mechanical_bear=4*(1-.18)*(27*.78)
 assert r['bear_target_price']>raw_mechanical_bear
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*85)
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'CORPORATE_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

def test_energy_bull_ordering_floor_applies_when_consensus_outruns_cycle_fundamentals():
 # eps/pe-cycle fundamentals alone put fair value far below a bullish
 # consensus median -- without a floor analogous to CORPORATE/FINANCIALS,
 # the bull scenario (fundamentals-anchored, cycle-multiple only) can land
 # below a base scenario pulled up by consensus blending, exactly the
 # ordering bug already fixed for the other two sector archetypes.
 out,_=validate_scenarios(pd.DataFrame([_row('XOM',45,200,150,100,5,8,.05,.7,.3,sector='Energy')]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'ENERGY_BULL_ORDERING_FLOOR_APPLIED' in r['scenario_review_flags']

def test_unknown_sector_fails_closed_never_defaults_corporate():
 out,m=validate_scenarios(pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,sector='')]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'SECTOR_CLASSIFICATION_UNVERIFIED' in r['scenario_review_blockers']; assert m['scenario_blocked_count']==1

def test_foreign_adr_unit_mismatch_fails_closed_without_verified_normalization():
 out,_=validate_scenarios(pd.DataFrame([_row('UNKNOWNADR',95.6,125,110,70,2.9985,15.2218,.08,.65,.4,sector='Energy',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_fcf_yield=.08)]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED' in r['scenario_review_blockers']

def test_verified_adr_ratio_normalization_can_reconcile_identity_and_financial_scenario_units():
 out,_=validate_scenarios(pd.DataFrame([_row('HSBC',105.11,140,107.69,75,4.17,5,.08,.65,.4,sector='Financial Services',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_book_value_per_share=11.5413,fundamental_price_to_book=1.3789,fundamental_roe=11.24)]),POLICY); r=out.iloc[0]
 assert r['identity_adr_ratio_applied']==5 and r['scenario_validated']

def test_txr_ten_for_one_ads_reconciles_identity_and_scenario_order():
 out,_=validate_scenarios(pd.DataFrame([_row('TXR',58.11,81.9,57.63,40.4,.2166,26.82,-.3781,.65,.4,sector='Basic Materials',issuer_country_normalized='LU',underlying_market_official='New York')]),POLICY); r=out.iloc[0]
 assert r['identity_adr_ratio_applied']==10 and r['scenario_validated']

def test_vod_negative_eps_uses_pb_identity_fallback():
 out,_=validate_scenarios(pd.DataFrame([_row('VOD',17.13,21.34,15.89,11.63,-.1,10,.08,.65,.4,sector='Telecom',issuer_country_normalized='GB',underlying_market_official='NASDAQ GS',fundamental_book_value_per_share=2.1931,fundamental_price_to_book=.6013)]),POLICY); r=out.iloc[0]
 assert r['economic_identity_method']=='PB'; assert r['identity_adr_ratio_applied']==10; assert not r['scenario_validated']; assert 'CORPORATE_FUNDAMENTALS_INCOMPLETE' in r['scenario_review_blockers']

def test_explicit_eps_target_unit_mismatch_fails_closed():
 out,_=validate_scenarios(pd.DataFrame([_row('AAA',100,130,110,80,5,20,.10,eps_unit='ORDINARY_SHARE',target_price_unit='ADR')]),POLICY); assert 'ECONOMIC_IDENTITY_TARGET_EPS_UNIT_MISMATCH' in out.iloc[0]['scenario_review_blockers']

def test_missing_identity_fundamentals_fail_closed_never_fabricate():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',16.99,23.1,19.63,17.47,None,None,.12,fundamental_book_value_per_share=None,fundamental_price_to_book=None)]),POLICY); assert not out.iloc[0]['scenario_validated'] and m['scenario_blocked_count']==1

def test_rds_verified_two_share_ads_and_extreme_consensus_cap():
 out,_=validate_scenarios(pd.DataFrame([_row('RDS',95.32,199.24,110.99,84.38,4,11.9,.08,.65,.55,sector='',issuer_country_normalized='GB',underlying_market_official='New York',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['identity_adr_ratio_applied']==2 and r['scenario_validated']; assert r['bull_target_price']<=95.32*1.60

def test_probabilities_are_dynamic():
 a=_row('AAA',100,130,110,80,5,20,.10,.9); b=_row('BBB',100,130,110,80,5,20,.10,.3); out,_=validate_scenarios(pd.DataFrame([a,b]),POLICY); assert out.iloc[0]['bull_probability']!=out.iloc[1]['bull_probability']

def test_widened_bull_range_lets_high_confidence_pull_more_weight_off_bear():
 # bull and bear are already a zero-sum pair (base_probability is fixed at
 # 50%), so confidence already moves weight between them symmetrically --
 # the fix here is a wider bull_min/bull_max band, not a new mechanism.
 # At near-max confidence a well-covered name should now reach close to the
 # widened bull_max (32%), pulling bear correspondingly lower than the old
 # 27%-cap regime allowed (bear floor around 18% instead of 23%).
 out,_=validate_scenarios(pd.DataFrame([_row('HICONF',100,140,120,85,5,18,.10,.97,.3,sector='Technology')]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bull_probability']>0.29
 assert r['bear_probability']<0.20
 assert abs((r['bull_probability']+r['base_probability']+r['bear_probability'])-1.0)<1e-9

def test_bbv_cedear_alias_resolves_verified_bbva_underlying_one_to_one():
 row=_row('BBV',18.5,23,20,14,1.2,15,.08,.7,.4,sector='Financial Services',issuer_country_normalized='ES',underlying_market_official='New York',underlying_ticker='BBVA',fundamental_book_value_per_share=12,fundamental_price_to_book=1.5,fundamental_roe=14)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['identity_adr_ratio_verified']; assert r['identity_adr_ratio_applied']==1; assert r['identity_adr_ratio_source']=='BBVA_OFFICIAL'; assert 'FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED' not in r['scenario_review_blockers']

def test_aeg_new_york_registry_share_is_verified_direct_listing_not_adr():
 row=_row('AEG',7.5,10,8.5,5.5,.5,15,.08,.7,.4,sector='Financial Services',issuer_country_normalized='NL',underlying_market_official='New York',fundamental_book_value_per_share=5,fundamental_price_to_book=1.5,fundamental_roe=12)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['identity_adr_ratio_verified']; assert r['identity_security_type']=='NEW_YORK_REGISTRY_SHARE'; assert 'VERIFIED_DIRECT_FOREIGN_LISTING_MAPPING_APPLIED' in r['identity_flags']; assert 'FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED' not in r['scenario_review_blockers']

def test_unknown_foreign_us_security_still_blocks_even_when_price_identity_looks_plausible():
 row=_row('XYZ',100,130,110,80,5,20,.10,.7,.4,sector='Technology',issuer_country_normalized='GB',underlying_market_official='New York')
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); assert 'FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED' in out.iloc[0]['scenario_review_blockers']

def test_blocked_etf_cannot_resurrect_as_g4_eligible():
 row={'cedear_ticker':'EEM','valuation_engine_type':'ETF','valuation_status':'BLOCKED_BY_DATA','bull_target_price':None,'base_target_price':None,'bear_target_price':None,'bull_probability':None,'base_probability':None,'bear_probability':None}
 out,m=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']; assert 'UPSTREAM_VALUATION_NOT_READY' in r['scenario_review_blockers']; assert 'NON_EQUITY_SCENARIO_TARGETS_MISSING_OR_INVALID' in r['scenario_review_blockers']; assert m['scenario_blocked_count']==1

def test_ready_etf_requires_complete_ordered_scenarios_and_probabilities():
 row={'cedear_ticker':'XLF','valuation_engine_type':'ETF','valuation_status':'VALUATION_READY','bull_target_price':120,'base_target_price':105,'bear_target_price':85,'bull_probability':.25,'base_probability':.5,'bear_probability':.25}
 out,m=validate_scenarios(pd.DataFrame([row]),POLICY); assert out.iloc[0]['scenario_validated']; assert m['scenario_validated_count']==1

def test_growth_adjusted_pe_cap_lets_richly_valued_growth_corporate_price_on_its_own_multiple():
 # Real NVDA-shaped inputs. growth=204% clips to the base_growth_cap (20%),
 # which now also drives the P/E cap to 15+1.5*20=45 -- comfortably above
 # NVDA's real ~43.8x multiple, so pem uses the real multiple instead of a
 # flat 25x cap. The old flat cap collapsed pem for Base and Bull alike, so
 # only the consensus-blended Base kept any real upside and Bull needed an
 # artificial floor to stay above it; with a growth-appropriate cap, Bull
 # exceeds Base on its own mechanical merits, without the floor firing.
 row=_row('NVDA',223.67,540.75,306.0,181.8,4.8979,43.8295,204.08,.7,.0538,sector='Technology')
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated']; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'CORPORATE_GROWTH_ADJUSTED_PE_CAP_APPLIED' in r['scenario_review_flags']
 assert 'CORPORATE_BULL_ORDERING_FLOOR_APPLIED' not in r['scenario_review_flags']
 # Bull upside vs current should now be a real, non-trivial number instead of
 # collapsing to (or below) current price the way the flat-cap model did.
 assert r['bull_target_price'] > r['current_price'] * 1.20

def test_bull_ordering_floor_still_fires_for_low_growth_name_with_rich_consensus_median():
 # A no-growth name gets the floor of the dynamic P/E cap (15x), well below
 # its real trading multiple of 15x here being the ceiling itself -- pem
 # stays clipped exactly like the old flat-cap model would, so the ordering
 # floor mechanism itself (not just the NVDA-shaped case it used to be
 # demonstrated with) still needs to exist and fire for names whose
 # consensus median runs ahead of what the mechanical model alone supports.
 row=_row('LOWG',100,155,155,80,4,15,.0,.7,.3,sector='Technology')
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'CORPORATE_BULL_ORDERING_FLOOR_APPLIED' in r['scenario_review_flags']
 assert abs(r['bull_target_price']-r['base_target_price']*1.10)<1e-6

def test_mastercard_routes_to_corporate_like_visa_not_bank_balance_sheet_model():
 # Real MA-shaped inputs. Mastercard's Comafi/provider sector metadata says
 # "Financial", but -- exactly like Visa -- it is a payment network, not a
 # bank: book value per share ($8.65) is tiny relative to price ($567.5,
 # ~66x P/B), so the Financials P/B anchor is meaningless for it and produces
 # a degenerate ~96%-collapse Bear case if the sector override is missing.
 row=_row('MA',567.5,777.0,678.3,552.7932,16.521,33.1055,17.34,.7,2.4557,sector='Financial',
          fundamental_book_value_per_share=8.6544,fundamental_price_to_book=66.2593,fundamental_roe=193.46)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='CORPORATE'; assert r['scenario_sector_source']=='POLICY_OVERRIDE'
 assert r['scenario_validated']; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 # A P/B-driven collapse would put Bear near current*0.04 (~$24); the
 # payment-network model should keep it in a materially saner range.
 assert r['bear_target_price']>567.5*0.30
