from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _num(v: Any) -> float | None:
    try:
        x=float(v)
    except (TypeError,ValueError):
        return None
    return x if np.isfinite(x) else None


def _rate(v: Any) -> float | None:
    x=_num(v)
    if x is None: return None
    return x/100.0 if abs(x)>1.5 else x


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,x))


def _dynamic_probabilities(confidence: float, dispersion: float, policy: dict) -> tuple[float,float,float]:
    p=policy.get('probabilities',{}) or {}
    base=float(p.get('base_probability',0.50))
    bull_lo=float(p.get('bull_min',0.15)); bull_hi=float(p.get('bull_max',0.27))
    dispersion_penalty=min(max(dispersion-float(p.get('dispersion_penalty_start',0.50)),0.0),1.0)*float(p.get('dispersion_bull_penalty_max',0.07))
    bull=_clip(bull_lo+(bull_hi-bull_lo)*confidence-dispersion_penalty,0.10,0.30)
    bear=1.0-base-bull
    return bull,base,bear


def _equity_review(row: pd.Series, policy: dict) -> dict[str,Any]:
    out=row.to_dict(); blockers=[]; flags=[]
    current=_num(row.get('current_price'))
    eps=_num(row.get('fundamental_eps_normalized'))
    pe=_num(row.get('fundamental_pe_normalized'))
    growth=_rate(row.get('fundamental_eps_growth_3y'))
    debt_eq=_num(row.get('fundamental_debt_to_equity'))
    confidence=_num(row.get('valuation_confidence'))
    high=_num(row.get('consensus_target_high') or row.get('bull_target_price'))
    median=_num(row.get('consensus_target_median') or row.get('base_target_price'))
    low=_num(row.get('consensus_target_low') or row.get('bear_target_price'))
    if current is None or current<=0: blockers.append('SCENARIO_CURRENT_PRICE_MISSING')
    if eps is None or eps<=0: blockers.append('FUNDAMENTAL_EPS_MISSING_OR_NONPOSITIVE')
    if pe is None or pe<=0: blockers.append('FUNDAMENTAL_PE_MISSING_OR_NONPOSITIVE')
    if growth is None: blockers.append('FUNDAMENTAL_GROWTH_MISSING')
    if confidence is None or not 0<=confidence<=1: blockers.append('SCENARIO_CONFIDENCE_MISSING')
    if any(x is None or x<=0 for x in (high,median,low)): blockers.append('CONSENSUS_DISTRIBUTION_MISSING')
    if blockers:
        out.update(scenario_validated=False,scenario_review_status='SCENARIO_NOT_VALIDATED',scenario_review_blockers=blockers,scenario_review_flags=flags,scenario_method='FUNDAMENTAL_SCENARIO_ENGINE_V1')
        return out

    cfg=policy.get('equity',{}) or {}
    g=_clip(growth,float(cfg.get('base_growth_floor',-0.10)),float(cfg.get('base_growth_cap',0.20)))
    pe_base=_clip(pe,float(cfg.get('base_pe_floor',6.0)),float(cfg.get('base_pe_cap',25.0)))
    fundamental_base=eps*(1.0+g)*pe_base
    consensus_blend=float(cfg.get('consensus_base_blend',0.20))
    base=(1.0-consensus_blend)*fundamental_base+consensus_blend*median

    leverage_extra=0.0 if debt_eq is None else _clip(max(debt_eq-float(cfg.get('debt_equity_stress_start',0.75)),0.0)*float(cfg.get('debt_equity_stress_slope',0.08)),0.0,float(cfg.get('max_leverage_extra_compression',0.12)))
    compression=_clip(float(cfg.get('bear_eps_compression',0.18))+leverage_extra,float(cfg.get('bear_eps_compression',0.18)),float(cfg.get('bear_eps_compression_cap',0.35)))
    bear_pe=max(float(cfg.get('bear_pe_floor',5.0)),pe_base*float(cfg.get('bear_multiple_factor',0.78)))
    bear=eps*(1.0-compression)*bear_pe

    bull_growth=_clip(max(g,float(cfg.get('bull_growth_floor',0.08)))+float(cfg.get('bull_growth_increment',0.08)),float(cfg.get('bull_growth_floor',0.08)),float(cfg.get('bull_growth_cap',0.30)))
    bull_pe=min(float(cfg.get('bull_pe_cap',30.0)),pe_base*float(cfg.get('bull_multiple_factor',1.12)))
    fundamental_bull=eps*(1.0+bull_growth)*bull_pe

    dispersion=(high-low)/current
    review_threshold=float((policy.get('consensus',{}) or {}).get('dispersion_review_threshold',0.75))
    if dispersion>review_threshold: flags.append('CONSENSUS_HIGH_LOW_DISPERSION')
    max_bull_upside=float((policy.get('plausibility',{}) or {}).get('max_standard_bull_upside',0.60))
    plausible_cap=current*(1.0+max_bull_upside)
    # Consensus high is evidence, not authority. It can only reduce a fundamental bull after winsorisation.
    winsor_high=min(high,median+float((policy.get('consensus',{}) or {}).get('high_distance_from_median_cap',0.50))*current)
    bull=min(fundamental_bull,winsor_high,plausible_cap)
    if high>plausible_cap: flags.append('CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY')

    # Enforce economic ordering without ever using analyst low to manufacture the Bear case.
    bear=min(bear,base*0.90)
    bull=max(bull,base*1.05)
    bull=min(bull,plausible_cap)
    if not (bear>0 and bear<base<bull):
        blockers.append('FUNDAMENTAL_SCENARIO_ORDER_INVALID')

    bp,bap,brp=_dynamic_probabilities(confidence,dispersion,policy)
    out.update(
        pre_review_bull_target_price=_num(row.get('bull_target_price')),
        pre_review_base_target_price=_num(row.get('base_target_price')),
        pre_review_bear_target_price=_num(row.get('bear_target_price')),
        bull_target_price=bull,base_target_price=base,bear_target_price=bear,
        bull_probability=bp,base_probability=bap,bear_probability=brp,
        scenario_validated=not blockers,
        scenario_review_status='SCENARIO_VALIDATED' if not blockers else 'SCENARIO_NOT_VALIDATED',
        scenario_review_blockers=blockers,scenario_review_flags=flags,
        scenario_method='FUNDAMENTAL_SCENARIO_ENGINE_V1',
        consensus_dispersion=dispersion,
        fundamental_base_target=fundamental_base,
        fundamental_bull_target=fundamental_bull,
        fundamental_bear_target=bear,
        bear_is_independent_of_analyst_low=True,
        expected_return_must_be_recomputed_post_review=True,
    )
    return out


def validate_scenarios(frame: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame,dict[str,Any]]:
    rows=[]
    for _,row in frame.iterrows():
        engine=str(row.get('valuation_engine_type') or '').upper()
        method=str(row.get('valuation_method') or '')
        if engine=='EQUITY' and method.startswith('FINNHUB_ANALYST_CONSENSUS'):
            rows.append(_equity_review(row,policy))
        else:
            out=row.to_dict()
            ready=str(row.get('valuation_status')) in {'VALUATION_READY','VALUATION_READY_WITH_WARNING'}
            out.update(scenario_validated=ready,scenario_review_status='SCENARIO_VALIDATED_SPECIALIZED_ENGINE' if ready else 'SCENARIO_NOT_VALIDATED',scenario_review_blockers=[] if ready else ['UPSTREAM_SPECIALIZED_SCENARIO_NOT_READY'],scenario_review_flags=[],scenario_method=f'SPECIALIZED_UPSTREAM:{method}',expected_return_must_be_recomputed_post_review=True)
            rows.append(out)
    result=pd.DataFrame(rows)
    valid=int(result.get('scenario_validated',pd.Series(dtype=bool)).fillna(False).sum())
    total=len(result)
    return result,{'scenario_review_count':total,'scenario_validated_count':valid,'scenario_blocked_count':total-valid,'scenario_review_complete':bool(total and valid==total),'scenario_methodology_version':policy.get('methodology_version','SCENARIO-1.0')}
