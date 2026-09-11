from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd


def _num(v: Any) -> float | None:
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if np.isfinite(x) else None

def _rate(v: Any) -> float | None:
    x=_num(v); return None if x is None else (x/100.0 if abs(x)>1.5 else x)

def _clip(x: float,lo: float,hi: float)->float: return max(lo,min(hi,x))
def _first_num(row:pd.Series,*names:str)->float|None:
    for n in names:
        x=_num(row.get(n))
        if x is not None:return x
    return None

def _dynamic_probabilities(confidence:float,dispersion:float,policy:dict)->tuple[float,float,float]:
    # bull and bear are already a zero-sum pair by construction (base is
    # fixed, so bear = 1 - base - bull): confidence already pulls weight
    # away from Bear and into Bull, symmetrically, with no separate lever
    # needed. What actually constrained this was too narrow a bull_min/
    # bull_max band -- a well-covered, high-confidence name could still only
    # reach 27% Bull (73% Base+Bear), leaving Bear structurally around 23%
    # even at maximum confidence. Widened via policy (bull_min/bull_max)
    # rather than the range itself; bull_floor/bull_ceiling remain as an
    # absolute safety rail, now policy-configurable instead of hardcoded, so
    # they can be set wide enough to not silently re-narrow what bull_min/
    # bull_max were just widened to allow.
    p=policy.get('probabilities',{}) or {}; base=float(p.get('base_probability',.50)); lo=float(p.get('bull_min',.12)); hi=float(p.get('bull_max',.32)); penalty=min(max(dispersion-float(p.get('dispersion_penalty_start',.50)),0.),1.)*float(p.get('dispersion_bull_penalty_max',.07)); bull=_clip(lo+(hi-lo)*confidence-penalty,float(p.get('bull_floor',.08)),float(p.get('bull_ceiling',.35))); return bull,base,1.-base-bull

def _classify_sector(row:pd.Series,policy:dict)->tuple[str|None,str]:
    ticker=str(row.get('underlying_ticker') or row.get('cedear_ticker') or '').upper(); overrides=policy.get('sector_overrides',{}) or {}
    if ticker in overrides:return str(overrides[ticker]).upper(),'POLICY_OVERRIDE'
    official=str(row.get('industry_sector_official') or '').upper(); provider=str(row.get('fundamental_sector') or row.get('sector') or row.get('finnhub_sector') or row.get('fundamental_industry') or row.get('industry') or '').upper(); text=f'{official} {provider}'.strip()
    if any(k in text for k in ('BANK','FINANC','INSURANCE','CAPITAL MARKET','ASSET MANAGEMENT')):return 'FINANCIALS','COMAFI_OR_PROVIDER_METADATA'
    if any(k in text for k in ('ENERGY','OIL','GAS','PETROLE','PETRÓLE','PETROLEUM')):return 'ENERGY','COMAFI_OR_PROVIDER_METADATA'
    corporate_keywords=tuple(str(x).upper() for x in (policy.get('sector_classification',{}) or {}).get('corporate_keywords',('TECHNOLOGY','SOFTWARE','SEMICONDUCTOR','HEALTH','PHARMA','CONSUMER','INDUSTRIAL','MATERIAL','COMMUNICATION','TELECOM','UTILITY','REAL ESTATE','AEROSPACE','TRANSPORT','RETAIL','FOOD','BEVERAGE')))
    if any(k in text for k in corporate_keywords):return 'CORPORATE','COMAFI_OR_PROVIDER_METADATA'
    return None,'UNVERIFIED'

def _security_keys(row:pd.Series)->list[str]:
    keys=[]
    for raw in (row.get('underlying_ticker'),row.get('cedear_ticker')):
        key=str(raw or '').strip().upper()
        if key and key not in keys:keys.append(key)
    return keys

def _verified_security_mapping(row:pd.Series,policy:dict)->tuple[float,bool,str|None,str|None]:
    direct=_num(row.get('adr_shares_per_depositary_receipt'))
    if direct is not None and direct>0 and bool(row.get('economic_unit_normalization_verified',False)):
        return direct,True,str(row.get('adr_ratio_source') or 'UPSTREAM_VERIFIED_METADATA'),str(row.get('foreign_security_type') or 'UPSTREAM_VERIFIED_SECURITY')
    cfg=policy.get('identity',{}) or {}; adrs=cfg.get('verified_adr_ratios',{}) or {}; listings=cfg.get('verified_direct_foreign_listings',{}) or {}
    for key in _security_keys(row):
        entry=adrs.get(key)
        if isinstance(entry,dict):
            ratio=_num(entry.get('ordinary_shares_per_ads'))
            if ratio is not None and ratio>0 and entry.get('source'):return ratio,True,str(entry['source']),'ADS_ADR'
    for key in _security_keys(row):
        entry=listings.get(key)
        if isinstance(entry,dict):
            ratio=_num(entry.get('ordinary_shares_per_us_traded_share'))
            if ratio is not None and ratio>0 and entry.get('source') and entry.get('security_type'):return ratio,True,str(entry['source']),str(entry['security_type'])
    return 1.0,False,None,None

def _identity_check(row:pd.Series,policy:dict)->tuple[bool,list[str],dict[str,Any]]:
    blockers=[]; flags=[]; cfg=policy.get('identity',{}) or {}; current=_num(row.get('current_price')); eps=_num(row.get('fundamental_eps_normalized')); pe=_num(row.get('fundamental_pe_normalized'))
    adr,adr_verified,adr_source,security_type=_verified_security_mapping(row,policy); fx=_num(row.get('fundamental_fx_to_market')); fx=1.0 if fx is None else fx
    implied_eps=eps*pe*adr*fx if eps is not None and pe is not None and eps>0 and pe>0 and adr>0 and fx>0 else None; ratio_eps=implied_eps/current if implied_eps is not None and current and current>0 else None
    bv=_first_num(row,'fundamental_book_value_per_share','book_value_per_share'); pb=_first_num(row,'fundamental_price_to_book','price_to_book'); implied_pb=bv*pb*adr*fx if bv is not None and pb is not None and bv>0 and pb>0 and adr>0 and fx>0 else None; ratio_pb=implied_pb/current if implied_pb is not None and current and current>0 else None
    lo=float(cfg.get('eps_pe_to_price_ratio_min',.55)); hi=float(cfg.get('eps_pe_to_price_ratio_max',1.80)); identity_method='EPS_PE' if ratio_eps is not None else ('PB' if ratio_pb is not None else 'UNVERIFIABLE'); ratio=ratio_eps if ratio_eps is not None else ratio_pb; implied=implied_eps if ratio_eps is not None else implied_pb
    if ratio is None:blockers.append('ECONOMIC_IDENTITY_UNVERIFIABLE')
    elif not lo<=ratio<=hi:blockers.append(f'ECONOMIC_IDENTITY_{identity_method}_UNIT_MISMATCH')
    if not str(row.get('underlying_ticker') or '').strip():blockers.append('ECONOMIC_IDENTITY_UNDERLYING_MISSING')
    target=str(row.get('target_price_unit') or 'UNDERLYING_SECURITY').upper(); eps_unit=str(row.get('eps_unit') or 'UNDERLYING_SECURITY').upper(); normalization_verified=bool(row.get('economic_unit_normalization_verified',False)) or adr_verified
    if target!=eps_unit and not normalization_verified:blockers.append('ECONOMIC_IDENTITY_TARGET_EPS_UNIT_MISMATCH')
    country=str(row.get('issuer_country_normalized') or row.get('country_of_origin') or '').upper(); market=str(row.get('underlying_market_official') or row.get('underlying_market') or '').upper(); non_us=country not in ('','US','USA','UNITED STATES','ESTADOS UNIDOS')
    us_traded=market in ('NEW YORK','NYSE','NASDAQ','NASDAQ GS','NASDAQ GM','NASDAQ CM')
    if non_us and us_traded and not normalization_verified:
        blockers.append('FOREIGN_TRADED_SECURITY_UNIT_NORMALIZATION_UNVERIFIED'); flags.append('ADR_OR_FOREIGN_SHARE_NORMALIZATION_REQUIRED')
    if adr_verified and security_type=='ADS_ADR' and adr!=1.0:flags.append('VERIFIED_ADR_RATIO_APPLIED')
    if adr_verified and security_type=='ADS_ADR' and adr==1.0 and non_us:flags.append('VERIFIED_FOREIGN_SECURITY_1_TO_1_MAPPING_APPLIED')
    if adr_verified and security_type not in (None,'ADS_ADR'):
        flags.append('VERIFIED_DIRECT_FOREIGN_LISTING_MAPPING_APPLIED')
        if adr==1.0:flags.append('VERIFIED_FOREIGN_SECURITY_1_TO_1_MAPPING_APPLIED')
    if identity_method=='PB':flags.append('ECONOMIC_IDENTITY_PB_FALLBACK_APPLIED')
    status='VERIFIED_NORMALIZED' if not blockers else 'BLOCKED'; return not blockers,blockers,{'economic_identity_status':status,'economic_identity_method':identity_method,'identity_implied_price':implied,'identity_implied_to_market_ratio':ratio,'identity_adr_ratio_applied':adr,'identity_adr_ratio_verified':adr_verified,'identity_adr_ratio_source':adr_source,'identity_security_type':security_type,'identity_fx_applied':fx,'identity_flags':flags,'identity_target_unit':target,'identity_eps_unit':eps_unit}

def _scenario_unit_row(row:pd.Series,meta:dict)->pd.Series:
    r=row.copy(); adr=_num(meta.get('identity_adr_ratio_applied')) or 1.0; fx=_num(meta.get('identity_fx_applied')) or 1.0; factor=adr*fx
    if factor<=0:raise ValueError('SCENARIO_ECONOMIC_UNIT_NORMALIZATION_INVALID')
    for c in ('fundamental_eps_normalized','fundamental_book_value_per_share','book_value_per_share'):
        v=_num(r.get(c))
        if v is not None:r[c]=v*factor
    r['scenario_economic_unit_factor']=factor
    return r

def _consensus(row,current,policy):
    high=_first_num(row,'consensus_target_high','bull_target_price'); med=_first_num(row,'consensus_target_median','base_target_price'); low=_first_num(row,'consensus_target_low','bear_target_price'); flags=[]
    if any(x is None or x<=0 for x in (high,med,low)):return high,med,low,0.,flags,None
    c=policy.get('consensus',{}) or {}; plaus=policy.get('plausibility',{}) or {}
    # High and low are winsorized symmetrically: a single most-bullish or
    # most-bearish analyst in the sample shouldn't be able to single-handedly
    # set the Bull/Bear anchor or, via dispersion below, the bull/bear
    # probability split. Both a distance-from-median floor/cap and an
    # absolute distance-from-current floor/cap apply, matching each other's
    # mechanics exactly.
    bull_cap_abs=current*(1.+float(plaus.get('max_standard_bull_upside',.60)))
    bull_cap_med=med+float(c.get('high_distance_from_median_cap',.50))*current
    wh=min(high,bull_cap_med,bull_cap_abs)
    if wh<high:flags.append('CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY')
    bear_floor_abs=current*(1.-float(plaus.get('max_standard_bear_downside',.40)))
    bear_floor_med=med-float(c.get('low_distance_from_median_floor',.50))*current
    wl=max(low,bear_floor_med,bear_floor_abs)
    if wl>low:flags.append('CONSENSUS_LOW_WINSORIZED_FOR_PLAUSIBILITY')
    dispersion=(wh-wl)/current
    if dispersion>float(c.get('dispersion_review_threshold',.75)):flags.append('CONSENSUS_HIGH_LOW_DISPERSION')
    return high,med,wl,dispersion,flags,wh

def _corporate_targets(row,current,median,low,bull_cap,policy):
    c=policy.get('corporate',policy.get('equity',{})) or {}; eps=_num(row.get('fundamental_eps_normalized')); pe=_num(row.get('fundamental_pe_normalized')); growth=_rate(row.get('fundamental_eps_growth_3y'))
    if eps is None or eps<=0 or pe is None or pe<=0 or growth is None:raise ValueError('CORPORATE_FUNDAMENTALS_INCOMPLETE')
    g=_clip(growth,float(c.get('base_growth_floor',-.10)),float(c.get('base_growth_cap',.20)))
    # A flat P/E cap treats a no-growth value name and a 20%+ grower
    # identically, which structurally understates fair value (and Bull
    # upside) for exactly the megacap/quality-growth names this pipeline is
    # now tilted toward. The cap instead scales with the same (already
    # conservatively clipped) growth rate used for the EPS build-up itself --
    # roughly PEG-anchored -- so a genuine grower earns a richer multiple
    # ceiling than a mature/no-growth name, instead of both being flattened
    # to the same number.
    pe_cap_base=float(c.get('pe_cap_base',15)); pe_cap_growth_sensitivity=float(c.get('pe_cap_growth_sensitivity',1.5)); pe_cap_ceiling=float(c.get('pe_cap_ceiling',55))
    dynamic_pe_cap=_clip(pe_cap_base+pe_cap_growth_sensitivity*max(g,0.0)*100.0,pe_cap_base,pe_cap_ceiling)
    pem=_clip(pe,float(c.get('base_pe_floor',6)),dynamic_pe_cap); basefund=eps*(1+g)*pem; blend=float(c.get('consensus_base_blend',.20)); base=(1-blend)*basefund+blend*median
    de=_num(row.get('fundamental_debt_to_equity')); extra=0 if de is None else _clip(max(de-float(c.get('debt_equity_stress_start',.75)),0)*float(c.get('debt_equity_stress_slope',.08)),0,float(c.get('max_leverage_extra_compression',.12))); comp=_clip(float(c.get('bear_eps_compression',.18))+extra,float(c.get('bear_eps_compression',.18)),float(c.get('bear_eps_compression_cap',.35)))
    # A pure EPS-x-PE compression bear case treats every CORPORATE name
    # identically regardless of how resilient the business actually is --
    # unlike base (already blended 80/20 toward consensus median), it never
    # heard what analysts' own bear case actually says. Blending it toward
    # the real consensus low target the same way base blends toward the
    # median corrects that: a mechanically severe compression only sticks
    # when analysts themselves see comparable downside, instead of always
    # manufacturing a worse bear case than the market's own low estimate.
    raw_bear=eps*(1-comp)*max(float(c.get('bear_pe_floor',5)),pem*float(c.get('bear_multiple_factor',.78))); bear_blend=float(c.get('consensus_bear_blend',.20)); bear=(1-bear_blend)*raw_bear+bear_blend*low
    bg=_clip(max(g,float(c.get('bull_growth_floor',.08)))+float(c.get('bull_growth_increment',.08)),float(c.get('bull_growth_floor',.08)),float(c.get('bull_growth_cap',.30)))
    # No separate bull_pe_cap: pem is already growth-adjusted above, and the
    # consensus-derived bull_cap (winsorized in _consensus) remains the final
    # plausibility ceiling on the resulting price, same as before.
    raw_bull=eps*(1+bg)*pem*float(c.get('bull_multiple_factor',1.12)); min_premium=float(c.get('minimum_bull_premium_to_base',.10)); bull=min(max(raw_bull,base*(1+min_premium)),bull_cap); flags=[]
    if dynamic_pe_cap>pe_cap_base:flags.append('CORPORATE_GROWTH_ADJUSTED_PE_CAP_APPLIED')
    if bear!=raw_bear:flags.append('CORPORATE_BEAR_CONSENSUS_BLEND_APPLIED')
    if bull>raw_bull:flags.append('CORPORATE_BULL_ORDERING_FLOOR_APPLIED')
    return bear,base,bull,flags

def _financial_targets(row,current,median,bull_cap,policy):
    c=policy.get('financials',{}) or {}; bv=_first_num(row,'fundamental_book_value_per_share','book_value_per_share'); roe=_rate(_first_num(row,'fundamental_roe','roe')); flags=['DEBT_EQUITY_NOT_USED_FOR_FINANCIALS']
    if bv is None or bv<=0 or roe is None:raise ValueError('FINANCIAL_FUNDAMENTALS_INCOMPLETE')
    observed_pb=current/bv; r=_clip(roe,float(c.get('roe_floor',.04)),float(c.get('roe_cap',.22))); fair_pb=_clip(float(c.get('base_pb_anchor',1))+float(c.get('roe_pb_sensitivity',3))*(r-float(c.get('cost_of_equity_anchor',.10))),float(c.get('base_pb_floor',.45)),float(c.get('base_pb_cap',4.0)))
    ow=float(c.get('observed_pb_weight',.65)); fw=float(c.get('fair_pb_weight',1-ow)); denom=ow+fw
    if denom<=0:raise ValueError('FINANCIAL_PB_WEIGHTS_INVALID')
    basepb=_clip((ow*observed_pb+fw*fair_pb)/denom,float(c.get('base_pb_floor',.45)),float(c.get('base_pb_cap',4.0))); flags.append('FINANCIAL_OBSERVED_PB_ANCHORED')
    fundamental_base=bv*basepb; blend=float(c.get('consensus_base_blend',.2)); base=(1-blend)*fundamental_base+blend*median; bear=bv*max(float(c.get('bear_pb_floor',.35)),basepb*float(c.get('bear_pb_factor',.72))); raw_bull=bv*min(float(c.get('bull_pb_cap',5.0)),basepb*float(c.get('bull_pb_factor',1.2))); min_premium=float(c.get('minimum_bull_premium_to_base',.10)); bull=min(max(raw_bull,base*(1+min_premium)),bull_cap)
    if bull>raw_bull:flags.append('FINANCIAL_BULL_ORDERING_FLOOR_APPLIED')
    return bear,base,bull,flags

def _energy_targets(row,current,median,bull_cap,policy):
    c=policy.get('energy',{}) or {}; eps=_num(row.get('fundamental_eps_normalized')); pe=_num(row.get('fundamental_pe_normalized')); fcf=_rate(_first_num(row,'fundamental_fcf_yield','fcf_yield')); div=_rate(_first_num(row,'fundamental_dividend_yield','dividend_yield')) or 0
    if eps is None or eps<=0 or pe is None or pe<=0:raise ValueError('ENERGY_FUNDAMENTALS_INCOMPLETE')
    peb=_clip(pe,float(c.get('base_pe_floor',5)),float(c.get('base_pe_cap',14))); earn=eps*peb; fcfb=current if fcf is None or fcf<=0 else current*_clip(fcf/float(c.get('normalized_fcf_yield',.08)),.70,1.30); bf=float(c.get('earnings_weight',.65))*earn+(1-float(c.get('earnings_weight',.65)))*fcfb; blend=float(c.get('consensus_base_blend',.15)); base=(1-blend)*bf+blend*median; bear=bf*float(c.get('bear_cycle_factor',.72))+current*div*float(c.get('dividend_credit',.5)); raw_bull=bf*float(c.get('bull_cycle_factor',1.28))+current*div; min_premium=float(c.get('minimum_bull_premium_to_base',.10)); bull=min(max(raw_bull,base*(1+min_premium)),bull_cap); flags=['ENERGY_CYCLE_NORMALIZATION_APPLIED']
    if bull>raw_bull:flags.append('ENERGY_BULL_ORDERING_FLOOR_APPLIED')
    return bear,base,bull,flags

def _equity_review(row,policy):
    out=row.to_dict(); blockers=[]; flags=[]; current=_num(row.get('current_price')); confidence=_num(row.get('valuation_confidence'))
    if current is None or current<=0:blockers.append('SCENARIO_CURRENT_PRICE_MISSING')
    if confidence is None or not 0<=confidence<=1:blockers.append('SCENARIO_CONFIDENCE_MISSING')
    if blockers:out.update(scenario_validated=False,scenario_review_status='SCENARIO_NOT_VALIDATED',scenario_review_blockers=blockers,scenario_review_flags=flags,scenario_method='SECTOR_AWARE_FUNDAMENTAL_SCENARIO_ENGINE_V2_2'); return out
    _,ib,meta=_identity_check(row,policy); blockers.extend(ib); high,median,low,disp,cf,bcap=_consensus(row,current,policy); flags.extend(cf)
    if any(x is None or x<=0 for x in (high,median,low)) or bcap is None:blockers.append('CONSENSUS_DISTRIBUTION_MISSING')
    sector,sector_source=_classify_sector(row,policy)
    if sector is None:blockers.append('SECTOR_CLASSIFICATION_UNVERIFIED')
    if blockers:out.update(**meta,scenario_sector_model=sector,scenario_sector_source=sector_source,scenario_validated=False,scenario_review_status='SCENARIO_NOT_VALIDATED',scenario_review_blockers=blockers,scenario_review_flags=flags+meta.get('identity_flags',[]),scenario_method='SECTOR_AWARE_FUNDAMENTAL_SCENARIO_ENGINE_V2_2'); return out
    try:
        scenario_row=_scenario_unit_row(row,meta); factor=_num(scenario_row.get('scenario_economic_unit_factor')) or 1.0
        if factor!=1.0:flags.append('SCENARIO_FUNDAMENTALS_NORMALIZED_TO_TRADED_SECURITY')
        if sector=='FINANCIALS':bear,base,bull,mf=_financial_targets(scenario_row,current,median,bcap,policy)
        elif sector=='ENERGY':bear,base,bull,mf=_energy_targets(scenario_row,current,median,bcap,policy)
        else:bear,base,bull,mf=_corporate_targets(scenario_row,current,median,low,bcap,policy)
        flags.extend(mf)
    except ValueError as exc:blockers.append(str(exc)); bear=base=bull=None
    if bear is not None and base is not None and bull is not None and not (bear>0 and bear<base<bull):blockers.append('FUNDAMENTAL_SCENARIO_ORDER_INVALID')
    bp,bap,brp=_dynamic_probabilities(confidence,disp,policy); out.update(**meta,pre_review_bull_target_price=_num(row.get('bull_target_price')),pre_review_base_target_price=_num(row.get('base_target_price')),pre_review_bear_target_price=_num(row.get('bear_target_price')),bull_target_price=bull,base_target_price=base,bear_target_price=bear,bull_probability=bp,base_probability=bap,bear_probability=brp,scenario_sector_model=sector,scenario_sector_source=sector_source,scenario_validated=not blockers,scenario_review_status='SCENARIO_VALIDATED' if not blockers else 'SCENARIO_NOT_VALIDATED',scenario_review_blockers=blockers,scenario_review_flags=flags+meta.get('identity_flags',[]),scenario_method='SECTOR_AWARE_FUNDAMENTAL_SCENARIO_ENGINE_V2_2'); return out

def _non_equity_review(row:pd.Series)->dict[str,Any]:
    out=row.to_dict(); blockers=[]; flags=['NON_EQUITY_TRACKER_REVIEWED_FAIL_CLOSED']; status=str(row.get('valuation_status') or '').upper()
    if status!='VALUATION_READY':blockers.append('UPSTREAM_VALUATION_NOT_READY')
    bull=_num(row.get('bull_target_price')); base=_num(row.get('base_target_price')); bear=_num(row.get('bear_target_price'))
    if any(x is None or x<=0 for x in (bull,base,bear)) or not (bear<base<bull):blockers.append('NON_EQUITY_SCENARIO_TARGETS_MISSING_OR_INVALID')
    probs=[_num(row.get(c)) for c in ('bull_probability','base_probability','bear_probability')]
    if any(x is None or x<0 or x>1 for x in probs) or (all(x is not None for x in probs) and abs(sum(probs)-1.0)>1e-6):blockers.append('NON_EQUITY_SCENARIO_PROBABILITIES_INVALID')
    out.update(scenario_sector_model=None,scenario_sector_source='N/A',economic_identity_status='N/A',economic_identity_method='N/A',identity_adr_ratio_applied=1.0,identity_adr_ratio_verified=False,identity_adr_ratio_source=None,identity_security_type='NON_EQUITY',identity_fx_applied=1.0,identity_implied_price=None,identity_implied_to_market_ratio=None,identity_target_unit='N/A',identity_eps_unit='N/A',identity_flags=[],scenario_validated=not blockers,scenario_review_status='SCENARIO_VALIDATED' if not blockers else 'SCENARIO_NOT_VALIDATED',scenario_review_blockers=blockers,scenario_review_flags=flags,scenario_method='NON_EQUITY_TRACKER_FAIL_CLOSED_V2_2'); return out

def review_scenarios(df:pd.DataFrame,policy:dict)->pd.DataFrame:
    rows=[]
    for _,row in df.iterrows():
        engine=str(row.get('valuation_engine_type') or '').upper()
        rows.append(_equity_review(row,policy) if engine=='EQUITY' else _non_equity_review(row))
    return pd.DataFrame(rows)


def validate_scenarios(df:pd.DataFrame,policy:dict)->tuple[pd.DataFrame,dict[str,Any]]:
    reviewed=review_scenarios(df,policy); validated=int(reviewed['scenario_validated'].fillna(False).astype(bool).sum()) if 'scenario_validated' in reviewed.columns else 0; total=int(len(reviewed))
    manifest={'methodology_version':str(policy.get('methodology_version') or 'SCENARIO-2.2'),'scenario_methodology_version':str(policy.get('methodology_version') or 'SCENARIO-2.2'),'scenario_review_count':total,'scenario_validated_count':validated,'scenario_blocked_count':total-validated}
    return reviewed,manifest
