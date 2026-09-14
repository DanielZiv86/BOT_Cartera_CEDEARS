import pandas as pd
import pytest
from src.valuation.deep_scenario_engine import validate_scenarios

POLICY={
 'methodology_version':'SCENARIO-2.2','identity':{'eps_pe_to_price_ratio_min':.55,'eps_pe_to_price_ratio_max':1.80,'verified_adr_ratios':{'BBV':{'ordinary_shares_per_ads':1,'source':'BBVA_OFFICIAL'},'HSBC':{'ordinary_shares_per_ads':5,'source':'HSBC_OFFICIAL'},'ING':{'ordinary_shares_per_ads':1,'source':'ING_OFFICIAL'},'SAN':{'ordinary_shares_per_ads':1,'source':'SAN_OFFICIAL'},'EQNR':{'ordinary_shares_per_ads':1,'source':'EQNR_OFFICIAL'},'RDS':{'ordinary_shares_per_ads':2,'source':'SHELL_OFFICIAL'},'TXR':{'ordinary_shares_per_ads':10,'source':'TERNIUM_OFFICIAL'},'VOD':{'ordinary_shares_per_ads':10,'source':'VODAFONE_OFFICIAL'},'TEN':{'ordinary_shares_per_ads':2,'source':'TENARIS_OFFICIAL'},'TS':{'ordinary_shares_per_ads':2,'source':'TENARIS_OFFICIAL'},'ARM':{'ordinary_shares_per_ads':1,'source':'ARM_OFFICIAL'}},'verified_direct_foreign_listings':{'AEG':{'ordinary_shares_per_us_traded_share':1,'security_type':'NEW_YORK_REGISTRY_SHARE','source':'AEGON_OFFICIAL'},'PAGS':{'ordinary_shares_per_us_traded_share':1,'security_type':'NYSE_LISTED_CLASS_A_COMMON_SHARE','source':'PAGSEGURO_OFFICIAL'}},'verified_domestic_dual_class_ratios':{'BRKB':{'reference_class_shares_per_traded_share':0.0006666667,'source':'BERKSHIRE_OFFICIAL'},'BRK/B':{'reference_class_shares_per_traded_share':0.0006666667,'source':'BERKSHIRE_OFFICIAL'}}},
 'sector_overrides':{'RDS':'ENERGY','SHEL':'ENERGY','V':'CORPORATE','MA':'CORPORATE','BRKB':'FINANCIALS','BRK/B':'FINANCIALS','SPGI':'FINANCIALS','ADP':'CORPORATE','RTX':'CORPORATE','GOOGL':'CORPORATE'},
 'sector_classification':{'corporate_keywords':['TECHNOLOGY','SOFTWARE','SEMICONDUCTOR','HEALTH','PHARMA','CONSUMER','INDUSTRIAL','MATERIAL','COMMUNICATION','TELECOM','UTILITY','REAL ESTATE','AEROSPACE','TRANSPORT','RETAIL','FOOD','BEVERAGE']},
 'corporate':{'consensus_base_blend':.20,'consensus_bear_blend':.20,'bear_eps_compression':.18,'bear_multiple_factor':.78,'base_pe_floor':6,'pe_cap_base':15,'pe_cap_growth_sensitivity':1.5,'pe_cap_ceiling':55,'bull_multiple_factor':1.12,'base_growth_floor':-.10,'base_growth_cap':.20,'bull_growth_floor':.08,'bull_growth_increment':.08,'bull_growth_cap':.30},
 'financials':{'roe_floor':.04,'roe_cap':.22,'cost_of_equity_anchor':.10,'base_pb_anchor':1,'roe_pb_sensitivity':3,'base_pb_floor':.45,'base_pb_cap':4.0,'observed_pb_weight':.65,'fair_pb_weight':.35,'consensus_base_blend':.2,'bear_pb_factor':.72,'bear_pb_floor':.35,'bull_pb_factor':1.2,'bull_pb_cap':5.0,'minimum_bull_premium_to_base':.10,'consensus_bear_blend':.20},
 'energy':{'base_pe_floor':5,'base_pe_cap':14,'earnings_weight':.65,'normalized_fcf_yield':.08,'consensus_base_blend':.15,'bear_cycle_factor':.72,'bull_cycle_factor':1.28,'dividend_credit':.5,'minimum_bull_premium_to_base':.10,'consensus_bear_blend':.20},
 'utilities':{'base_pe_floor':10,'base_pe_cap':20,'consensus_base_blend':.20,'bear_pe_floor':7,'bear_multiple_factor':.85,'dividend_credit':.75,'bull_multiple_factor':1.15,'minimum_bull_premium_to_base':.10,'consensus_bear_blend':.20},
 'materials':{'base_pe_floor':5,'base_pe_cap':14,'earnings_weight':.65,'normalized_fcf_yield':.08,'consensus_base_blend':.15,'bear_cycle_factor':.70,'bull_cycle_factor':1.30,'dividend_credit':.5,'minimum_bull_premium_to_base':.10,'consensus_bear_blend':.20},
 'consumer_non_cyclical':{'base_growth_floor':-.10,'base_growth_cap':.20,'base_pe_floor':8,'pe_cap_base':16,'pe_cap_growth_sensitivity':1.5,'pe_cap_ceiling':50,'consensus_base_blend':.20,'bear_eps_compression':.12,'bear_multiple_factor':.82,'bear_pe_floor':6,'dividend_credit':.40,'bull_growth_floor':.06,'bull_growth_increment':.06,'bull_growth_cap':.25,'bull_multiple_factor':1.10,'minimum_bull_premium_to_base':.10,'consensus_bear_blend':.20},
 'consumer_cyclical':{'base_growth_floor':-.10,'base_growth_cap':.20,'base_pe_floor':6,'pe_cap_base':14,'pe_cap_growth_sensitivity':1.5,'pe_cap_ceiling':50,'consensus_base_blend':.20,'bear_eps_compression':.24,'bear_eps_compression_cap':.40,'bear_multiple_factor':.72,'bear_pe_floor':4,'current_ratio_stress_start':1.20,'current_ratio_stress_slope':.10,'max_liquidity_extra_compression':.12,'bull_growth_floor':.08,'bull_growth_increment':.08,'bull_growth_cap':.30,'bull_multiple_factor':1.12,'minimum_bull_premium_to_base':.10,'consensus_bear_blend':.20},
 'consensus':{'dispersion_review_threshold':.75,'high_distance_from_median_cap':.50,'low_distance_from_median_floor':.50},'plausibility':{'max_standard_bull_upside':.60,'max_standard_bear_downside':.40},'probabilities':{'base_probability':.50,'bull_min':.12,'bull_max':.32,'bull_floor':.08,'bull_ceiling':.35,'dispersion_penalty_start':.50,'dispersion_bull_penalty_max':.07}}

def _row(ticker,current,high,median,low,eps,pe,growth,confidence=.60,de=.8,sector='Technology',**extra):
 r={'cedear_ticker':ticker,'underlying_ticker':ticker,'valuation_engine_type':'EQUITY','valuation_method':'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4','valuation_status':'VALUATION_READY','current_price':current,'bull_target_price':high,'base_target_price':median,'bear_target_price':low,'consensus_target_high':high,'consensus_target_median':median,'consensus_target_low':low,'fundamental_eps_normalized':eps,'fundamental_pe_normalized':pe,'fundamental_eps_growth_3y':growth,'fundamental_debt_to_equity':de,'valuation_confidence':confidence,'eps_unit':'UNDERLYING_SECURITY','target_price_unit':'UNDERLYING_SECURITY','industry_sector_official':sector,'issuer_country_normalized':'US','underlying_market_official':'NASDAQ GS'}; r.update(extra); return r

def test_pbi_positive_control_validates_corporate_identity():
 out,m=validate_scenarios(pd.DataFrame([_row('PBI',17.17,23.1,19.63,12,.8362,16.2674,.12,.60,.8,sector='Technology')]),POLICY); r=out.iloc[0]
 assert m['scenario_validated_count']==1 and r['scenario_validated']; assert r['scenario_sector_model']=='CORPORATE'; assert r['economic_identity_status']=='VERIFIED_NORMALIZED'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_jpm_routes_to_financials_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('JPM',354.71,450,378.42,250,16.95,20,.08,.7,4,sector='Financial Services',fundamental_book_value_per_share=134.4218,fundamental_price_to_book=2.4202,fundamental_roe=15.74)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='FINANCIALS'; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']; assert r['scenario_validated']; assert r['base_target_price']>250; assert 'FINANCIAL_OBSERVED_PB_ANCHORED' in r['scenario_review_flags']

def test_financials_bear_case_blends_toward_consensus_low_same_as_corporate():
 # Same reasoning validated for CORPORATE: a pure P/B mechanical compression
 # never hears what analysts' own bear case actually says.
 out,_=validate_scenarios(pd.DataFrame([_row('JPM',354.71,450,378.42,250,16.95,20,.08,.7,4,sector='Financial Services',fundamental_book_value_per_share=134.4218,fundamental_price_to_book=2.4202,fundamental_roe=15.74)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 # basepb = clip((.65*observed_pb + .35*fair_pb)/1.0, .45, 4.0) with
 # observed_pb=current/bv=2.6389, fair_pb=clip(1+3*(.1574-.10),.45,4.0)=1.1722
 raw_mechanical_bear=134.4218*max(.35,2.125479140184107*.72)
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*250,rel=1e-4)
 assert 'FINANCIAL_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

def test_visa_routes_to_corporate_not_bank_balance_sheet_model():
 out,_=validate_scenarios(pd.DataFrame([_row('V',367.39,500,428.4,300,10.2024,34.24,.1337,.7,1,sector='Financial Services',fundamental_book_value_per_share=19.7892,fundamental_price_to_book=17.2671,fundamental_roe=52.91)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='CORPORATE'; assert r['scenario_sector_source']=='POLICY_OVERRIDE'; assert r['scenario_validated']

def test_cvx_routes_to_energy_from_official_sector():
 out,_=validate_scenarios(pd.DataFrame([_row('CVX',160,200,180,120,12,13,.05,.7,.3,sector='Energy',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='ENERGY'; assert r['scenario_validated']; assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_energy_bear_case_blends_toward_consensus_low_same_as_corporate():
 # Same reasoning validated for CORPORATE/FINANCIALS: a pure cycle-multiple
 # compression never hears what analysts' own bear case actually says.
 out,_=validate_scenarios(pd.DataFrame([_row('CVX',160,200,180,120,12,13,.05,.7,.3,sector='Energy',fundamental_fcf_yield=.08,fundamental_dividend_yield=.04)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 peb=13; earn=12*peb; fcfb=160*1.0; bf=.65*earn+.35*fcfb
 raw_mechanical_bear=bf*.72+160*.04*.5
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*120,rel=1e-4)
 assert 'ENERGY_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

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

def test_sector_override_matches_on_underlying_ticker_not_just_cedear_ticker():
 # BRKB's real data has cedear_ticker='BRKB' but underlying_ticker='BRK/B'
 # (the class-share slash); _classify_sector prefers underlying_ticker, so a
 # sector_overrides entry keyed only on the cedear_ticker spelling would
 # silently miss and fall through to SECTOR_CLASSIFICATION_UNVERIFIED -- this
 # was found and fixed this session (both spellings are now in the override).
 out,_=validate_scenarios(pd.DataFrame([_row('BRKB',507,650,600,450,31,14.58,.08,.7,.3,sector='',underlying_ticker='BRK/B')]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='FINANCIALS'
 assert 'SECTOR_CLASSIFICATION_UNVERIFIED' not in r['scenario_review_blockers']

def test_brkb_domestic_dual_class_ratio_reconciles_real_class_a_scale_fundamentals():
 # Real BRKB data (found 2026-09-14, broad valuation output): Finnhub's
 # /stock/metric reports EPS/PE/book-value-per-share at Class A economic
 # scale (fundamental_eps_normalized=46570.2364, fundamental_pe_normalized=
 # 14.6701, fundamental_book_value_per_share=497171.8642) even when queried
 # for BRK.B, while current_price ($510.369995) is genuinely BRK.B market
 # price -- implied Class A fair value 46570.2364*14.6701≈$683,262, a ~1339x
 # mismatch against current_price. Without the verified 1500:1 conversion
 # ratio this fails ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH and BRKB can never
 # get a Bear/Base/Bull case, even though it's a real, fully-covered holding.
 row=_row('BRKB',510.369995,650,560,460,46570.2364,14.6701,.05,.7,.3,sector='',underlying_ticker='BRK/B',
          fundamental_book_value_per_share=497171.8642,fundamental_price_to_book=1.5134,fundamental_roe=9.33)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['identity_security_type']=='DOMESTIC_DUAL_CLASS'
 assert r['identity_adr_ratio_applied']==pytest.approx(0.0006666667)
 assert r['identity_adr_ratio_source']=='BERKSHIRE_OFFICIAL'
 assert r['identity_implied_to_market_ratio']==pytest.approx(0.8924114736463848,rel=1e-6)
 assert 'VERIFIED_DOMESTIC_DUAL_CLASS_RATIO_APPLIED' in r['identity_flags']
 assert 'VERIFIED_DIRECT_FOREIGN_LISTING_MAPPING_APPLIED' not in r['identity_flags']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_unverified_dual_class_ticker_still_fails_closed_on_unit_mismatch():
 # A different (hypothetical) dual-class-shaped mismatch with no config
 # entry must still fail closed -- the mechanism only reconciles tickers
 # with an explicit, sourced ratio, never a guessed one.
 row=_row('DUALX',500,650,560,460,45000,15,.05,sector='Technology')
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert 'ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH' in r['scenario_review_blockers']
 assert r['identity_security_type'] is None

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

def test_ten_verified_two_for_one_ads_reconciles_tenaris_identity():
 # Real Tenaris (TEN/TS) data found 2026-09-14: without an ADR ratio, the
 # implied identity ratio is 0.499 (eps*pe/price), just below the 0.55
 # floor. Tenaris's own investor relations page states 1 ADS = 2 ordinary
 # shares (unchanged since a 2006 board-approved change from the original
 # 10:1, documented in Tenaris's SEC Form 6-K FY2006) -- applying it brings
 # the ratio to 0.999, essentially a perfect match.
 out,_=validate_scenarios(pd.DataFrame([_row('TEN',57.39,85.314705,63.058644,51.141653,1.8304,15.6591,-.0541,.7925,.027,underlying_ticker='TS',issuer_country_normalized='LU',underlying_market_official='New York')]),POLICY); r=out.iloc[0]
 assert r['identity_adr_ratio_applied']==2 and r['scenario_validated'], r['scenario_review_blockers']
 assert r['identity_implied_to_market_ratio']==pytest.approx(0.9988645,rel=1e-5)

def test_arm_verified_one_to_one_ads_clears_foreign_traded_normalization_block():
 # Real ARM data found 2026-09-14: the sole BLOCKED_BY_DATA name in that
 # week's real Top-30. The numeric identity ratio (eps*pe/price) is already
 # in-band (1.044) with no adjustment, but ARM is UK-domiciled and
 # Nasdaq-traded, so FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED
 # still fires without a verified ratio on file. Arm Holdings plc's SEC Form
 # 424B4 IPO prospectus (2023): "Each ADS represents the right to receive
 # one ordinary share" -- applying it as 1:1 doesn't change the ratio
 # itself, just satisfies the verification requirement.
 row=_row('ARM',243.4685058594,472.5,277.44,126.25,.8464,300.2923,.1834,.8,.003,sector='Technology',issuer_country_normalized='GB',underlying_market_official='NASDAQ GS')
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['identity_adr_ratio_applied']==1 and r['identity_adr_ratio_verified']
 assert 'VERIFIED_FOREIGN_SECURITY_1_TO_1_MAPPING_APPLIED' in r['identity_flags']
 assert r['identity_implied_to_market_ratio']==pytest.approx(1.0439437,rel=1e-5)

def test_hon_eps_pe_miss_rescued_by_pb_corroboration():
 # Real Honeywell data found 2026-09-14: EPS/PE ratio is 0.493 (just below
 # the 0.55 floor -- EPS-normalization noise, likely from a recent
 # portfolio restructuring, not a real unit/scale mismatch), but the
 # independent book-value/price-to-book ratio is 0.964, cleanly inside the
 # band. HON is a purely domestic, single-class stock -- no ADR or
 # dual-class ratio applies -- so the fix is architectural: corroborate
 # with PB before blocking on a borderline EPS/PE miss.
 row=_row('HON',202.36,514.5,281.52,239.37,7.9947,12.4802,.0322,.8,2.2396,fundamental_book_value_per_share=24.3193,fundamental_price_to_book=8.022,fundamental_roe=33.28)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['economic_identity_method']=='PB'
 assert 'ECONOMIC_IDENTITY_PB_CORROBORATION_RESCUES_EPS_PE_MISS' in r['identity_flags']
 assert r['identity_implied_to_market_ratio']==pytest.approx(0.964071,rel=1e-5)

def test_eps_pe_miss_not_rescued_when_pb_also_fails():
 # Negative control: the PB-corroboration rescue must not fire when BOTH
 # ratios are out of band -- that's a real unit-scale mismatch (like TEN
 # without its ADR ratio, or ERIC's currency mismatch), not EPS-metric
 # noise, and must still fail closed.
 row=_row('BADID',100,140,120,90,45,15,.05,fundamental_book_value_per_share=500,fundamental_price_to_book=1.3)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert 'ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH' in r['scenario_review_blockers']
 assert 'ECONOMIC_IDENTITY_PB_CORROBORATION_RESCUES_EPS_PE_MISS' not in r['identity_flags']

def test_eric_verified_fx_correction_reconciles_currency_mismatch():
 # Real Ericsson data found 2026-09-14: both EPS/PE (9.41x) and PB (8.79x)
 # ratios come out consistently ~9-9.4x too high with no FX applied -- the
 # signature of a currency mismatch (Finnhub reports ERIC's fundamentals in
 # SEK while the ADR trades in USD), confirmed against the real USD/SEK
 # rate that day (~9.7675). fundamental_fx_to_market is populated upstream
 # by equity_engine.py's live FX lookup (never guessed) -- this test feeds
 # that already-resolved value straight to the identity check, same as an
 # ADR ratio would be.
 row=_row('ERIC',10.31,14.45367,10.45143,7.10838,8.5063,11.4051,.148,.8,.3676,underlying_ticker='ERIC',issuer_country_normalized='SE',underlying_market_official='NASDAQ GS',fundamental_fx_to_market=1.0/9.7675)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['identity_implied_to_market_ratio']==pytest.approx(0.9631,rel=1e-3)
 assert 'VERIFIED_FX_CORRECTION_APPLIED' in r['identity_flags']
 assert 'FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED' not in r['scenario_review_blockers']

def test_pags_verified_fx_correction_combines_with_existing_adr_normalization():
 # Real PagSeguro data found 2026-09-14: same currency-mismatch shape as
 # ERIC (BRL vs. USD), on a ticker that already had a verified 1:1 direct
 # foreign listing on file from a prior session -- confirms the FX
 # correction and the ADR/direct-listing mechanism compose correctly
 # rather than conflicting.
 row=_row('PAGS',10.12,14.70,12.24,7.777,7.1118,6.789,.1585,.7625,.1718,underlying_ticker='PAGS',issuer_country_normalized='BR',underlying_market_official='New York',fundamental_fx_to_market=1.0/5.1627)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['identity_implied_to_market_ratio']==pytest.approx(0.9241,rel=1e-3)
 assert 'VERIFIED_FX_CORRECTION_APPLIED' in r['identity_flags']

def test_fx_correction_present_does_not_bypass_a_genuinely_bad_ratio():
 # Negative control: fundamental_fx_to_market being populated must not
 # itself waive the numeric ratio check -- if the resulting ratio is still
 # out of band (e.g. a wrong or irrelevant FX value), it must still block.
 row=_row('BADFX',100,140,120,90,45,15,.05,underlying_ticker='BADFX',issuer_country_normalized='SE',underlying_market_official='NASDAQ GS',fundamental_fx_to_market=1.0)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert not r['scenario_validated']
 assert 'ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH' in r['scenario_review_blockers']

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

def test_utilities_routes_from_official_sector_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('UTILCO',60,75,65,50,3,15,.03,.65,sector='Utilities',fundamental_dividend_yield=.035)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='UTILITIES'; assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'UTILITIES_REGULATED_NARROW_PE_BAND_NO_LEVERAGE_STRESS' in r['scenario_review_flags']

def test_utilities_bear_case_blends_toward_consensus_low():
 # Same reasoning as CORPORATE/FINANCIALS/ENERGY: the mechanical bear case
 # blends toward the winsorized consensus low rather than standing alone.
 out,_=validate_scenarios(pd.DataFrame([_row('UTILCO',60,75,65,50,3,15,.03,.65,sector='Utilities',fundamental_dividend_yield=.035)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 pem=15; raw_mechanical_bear=3*max(7,pem*.85)+60*.035*.75
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*50,rel=1e-4)
 assert 'UTILITIES_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

def test_basic_materials_routes_from_official_sector_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('MATCO',50,65,55,40,4,10,.05,.65,sector='Basic Materials',fundamental_fcf_yield=.06,fundamental_dividend_yield=.02)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='BASIC_MATERIALS'; assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'MATERIALS_CYCLE_NORMALIZATION_APPLIED' in r['scenario_review_flags']

def test_basic_materials_bear_case_blends_toward_consensus_low():
 out,_=validate_scenarios(pd.DataFrame([_row('MATCO',50,65,55,40,4,10,.05,.65,sector='Basic Materials',fundamental_fcf_yield=.06,fundamental_dividend_yield=.02)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 peb=10; earn=4*peb; fcfb=50*max(min(.06/.08,1.3),.7); bf=.65*earn+.35*fcfb
 raw_mechanical_bear=bf*.70+50*.02*.5
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*40,rel=1e-4)
 assert 'MATERIALS_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

def test_consumer_non_cyclical_routes_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('STAPLECO',80,100,88,65,3,18,.05,.65,sector='Consumer, Non-cyclical',fundamental_dividend_yield=.025)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='CONSUMER_NON_CYCLICAL'; assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']

def test_consumer_non_cyclical_bear_case_blends_toward_consensus_low():
 # Smaller base compression (0.12) than CORPORATE (0.18) reflects the more
 # resilient earnings of a staples/health/pharma-style name in a downturn.
 out,_=validate_scenarios(pd.DataFrame([_row('STAPLECO',80,100,88,65,3,18,.05,.65,sector='Consumer, Non-cyclical',fundamental_dividend_yield=.025)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 pem=18; raw_mechanical_bear=3*(1-.12)*max(6,pem*.82)+80*.025*.4
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*65,rel=1e-4)
 assert 'CONSUMER_NON_CYCLICAL_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

def test_consumer_cyclical_routes_and_orders_scenarios():
 out,_=validate_scenarios(pd.DataFrame([_row('CYCCO',70,90,78,52,3,14,.05,.65,sector='Consumer, Cyclical',fundamental_current_ratio=1.5)]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='CONSUMER_CYCLICAL'; assert r['scenario_validated'], r['scenario_review_blockers']
 assert r['bear_target_price']<r['base_target_price']<r['bull_target_price']
 assert 'CONSUMER_CYCLICAL_LIQUIDITY_STRESS_APPLIED' not in r['scenario_review_flags']

def test_consumer_cyclical_bear_case_blends_toward_consensus_low():
 # Larger base compression (0.24) than CORPORATE (0.18) reflects real
 # recession-sensitive demand for discretionary/cyclical names.
 out,_=validate_scenarios(pd.DataFrame([_row('CYCCO',70,90,78,52,3,14,.05,.65,sector='Consumer, Cyclical',fundamental_current_ratio=1.5)]),POLICY); r=out.iloc[0]
 assert r['scenario_validated'], r['scenario_review_blockers']
 pem=14; raw_mechanical_bear=3*(1-.24)*max(4,pem*.72)
 assert r['bear_target_price']==pytest.approx(0.8*raw_mechanical_bear+0.2*52,rel=1e-4)
 assert 'CONSUMER_CYCLICAL_BEAR_CONSENSUS_BLEND_APPLIED' in r['scenario_review_flags']

def test_consumer_cyclical_liquidity_stress_widens_bear_case_below_current_ratio_threshold():
 # fundamental_current_ratio is otherwise unused by any archetype -- a
 # liquidity cushion below current_ratio_stress_start (1.20) adds extra bear
 # compression, mirroring how CORPORATE stresses on Debt/Equity, on a signal
 # that matters more for cyclical consumer names in a downturn.
 stressed,_=validate_scenarios(pd.DataFrame([_row('CYCCO2',70,90,78,52,3,14,.05,.65,sector='Consumer, Cyclical',fundamental_current_ratio=0.9)]),POLICY); rs=stressed.iloc[0]
 unstressed,_=validate_scenarios(pd.DataFrame([_row('CYCCO3',70,90,78,52,3,14,.05,.65,sector='Consumer, Cyclical',fundamental_current_ratio=1.5)]),POLICY); ru=unstressed.iloc[0]
 assert rs['scenario_validated'] and ru['scenario_validated']
 assert 'CONSUMER_CYCLICAL_LIQUIDITY_STRESS_APPLIED' in rs['scenario_review_flags']
 assert rs['bear_target_price']<ru['bear_target_price']

def test_spgi_style_override_wins_over_new_consumer_non_cyclical_auto_classification():
 # SPGI's real Comafi category is "Consumer, Non-cyclical" (it's a
 # ratings/data business), but the existing sector_overrides entry keeps it
 # FINANCIALS -- a deliberate per-ticker judgment call that predates and
 # must not be silently reshuffled by the expanded taxonomy.
 row=_row('SPGI',500,650,560,420,20,25,.10,.7,sector='Consumer, Non-cyclical',fundamental_book_value_per_share=8,fundamental_price_to_book=62.5,fundamental_roe=55)
 out,_=validate_scenarios(pd.DataFrame([row]),POLICY); r=out.iloc[0]
 assert r['scenario_sector_model']=='FINANCIALS'; assert r['scenario_sector_source']=='POLICY_OVERRIDE'
