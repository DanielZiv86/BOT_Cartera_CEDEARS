from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _rate(v: Any) -> float | None:
    x = _num(v)
    if x is None:
        return None
    return x / 100.0 if abs(x) > 1.5 else x


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _first_num(row: pd.Series, *names: str) -> float | None:
    for name in names:
        value = _num(row.get(name))
        if value is not None:
            return value
    return None


def _dynamic_probabilities(confidence: float, dispersion: float, policy: dict) -> tuple[float, float, float]:
    p = policy.get('probabilities', {}) or {}
    base = float(p.get('base_probability', 0.50))
    bull_lo = float(p.get('bull_min', 0.15)); bull_hi = float(p.get('bull_max', 0.27))
    dispersion_penalty = min(max(dispersion - float(p.get('dispersion_penalty_start', 0.50)), 0.0), 1.0) * float(p.get('dispersion_bull_penalty_max', 0.07))
    bull = _clip(bull_lo + (bull_hi - bull_lo) * confidence - dispersion_penalty, 0.10, 0.30)
    bear = 1.0 - base - bull
    return bull, base, bear


def _classify_sector(row: pd.Series, policy: dict) -> str:
    explicit = str(row.get('fundamental_sector') or row.get('sector') or row.get('finnhub_sector') or '').upper()
    industry = str(row.get('fundamental_industry') or row.get('industry') or '').upper()
    text = f'{explicit} {industry}'
    ticker = str(row.get('underlying_ticker') or row.get('cedear_ticker') or '').upper()
    overrides = policy.get('sector_overrides', {}) or {}
    if ticker in overrides:
        return str(overrides[ticker]).upper()
    if any(k in text for k in ('BANK', 'FINANCIAL', 'INSURANCE', 'CAPITAL MARKETS', 'ASSET MANAGEMENT')):
        return 'FINANCIALS'
    if any(k in text for k in ('ENERGY', 'OIL', 'GAS', 'PETROLEUM')):
        return 'ENERGY'
    return 'CORPORATE'


def _identity_check(row: pd.Series, policy: dict) -> tuple[bool, list[str], dict[str, Any]]:
    blockers: list[str] = []
    flags: list[str] = []
    current = _num(row.get('current_price'))
    eps = _num(row.get('fundamental_eps_normalized'))
    pe = _num(row.get('fundamental_pe_normalized'))
    implied = eps * pe if eps is not None and pe is not None and eps > 0 and pe > 0 else None
    cfg = policy.get('identity', {}) or {}
    ratio_lo = float(cfg.get('eps_pe_to_price_ratio_min', 0.55))
    ratio_hi = float(cfg.get('eps_pe_to_price_ratio_max', 1.80))
    ratio = implied / current if implied is not None and current and current > 0 else None
    if ratio is None:
        blockers.append('ECONOMIC_IDENTITY_EPS_PE_UNVERIFIABLE')
    elif not ratio_lo <= ratio <= ratio_hi:
        blockers.append('ECONOMIC_IDENTITY_EPS_PE_UNIT_MISMATCH')
    underlying = str(row.get('underlying_ticker') or '').strip()
    if not underlying:
        blockers.append('ECONOMIC_IDENTITY_UNDERLYING_MISSING')
    target_unit = str(row.get('target_price_unit') or 'UNDERLYING_SECURITY').upper()
    eps_unit = str(row.get('eps_unit') or 'UNDERLYING_SECURITY').upper()
    if target_unit != eps_unit:
        blockers.append('ECONOMIC_IDENTITY_TARGET_EPS_UNIT_MISMATCH')
    return not blockers, blockers, {'identity_implied_price': implied, 'identity_implied_to_market_ratio': ratio, 'identity_flags': flags, 'identity_target_unit': target_unit, 'identity_eps_unit': eps_unit}


def _consensus(row: pd.Series, current: float, policy: dict) -> tuple[float | None, float | None, float | None, float, list[str], float | None]:
    high = _first_num(row, 'consensus_target_high', 'bull_target_price')
    median = _first_num(row, 'consensus_target_median', 'base_target_price')
    low = _first_num(row, 'consensus_target_low', 'bear_target_price')
    flags: list[str] = []
    if any(x is None or x <= 0 for x in (high, median, low)):
        return high, median, low, 0.0, flags, None
    dispersion = (high - low) / current
    ccfg = policy.get('consensus', {}) or {}
    if dispersion > float(ccfg.get('dispersion_review_threshold', 0.75)):
        flags.append('CONSENSUS_HIGH_LOW_DISPERSION')
    plausible_cap = current * (1.0 + float((policy.get('plausibility', {}) or {}).get('max_standard_bull_upside', 0.60)))
    winsor_high = min(high, median + float(ccfg.get('high_distance_from_median_cap', 0.50)) * current)
    if high > plausible_cap:
        flags.append('CONSENSUS_HIGH_WINSORIZED_FOR_PLAUSIBILITY')
    return high, median, low, dispersion, flags, min(winsor_high, plausible_cap)


def _corporate_targets(row: pd.Series, current: float, median: float, bull_cap: float, policy: dict) -> tuple[float, float, float, list[str]]:
    cfg = policy.get('corporate', policy.get('equity', {})) or {}
    eps = _num(row.get('fundamental_eps_normalized')); pe = _num(row.get('fundamental_pe_normalized')); growth = _rate(row.get('fundamental_eps_growth_3y'))
    if eps is None or eps <= 0 or pe is None or pe <= 0 or growth is None:
        raise ValueError('CORPORATE_FUNDAMENTALS_INCOMPLETE')
    g = _clip(growth, float(cfg.get('base_growth_floor', -0.10)), float(cfg.get('base_growth_cap', 0.20)))
    pe_base = _clip(pe, float(cfg.get('base_pe_floor', 6.0)), float(cfg.get('base_pe_cap', 25.0)))
    fundamental_base = eps * (1.0 + g) * pe_base
    base = (1.0 - float(cfg.get('consensus_base_blend', 0.20))) * fundamental_base + float(cfg.get('consensus_base_blend', 0.20)) * median
    debt_eq = _num(row.get('fundamental_debt_to_equity'))
    leverage_extra = 0.0 if debt_eq is None else _clip(max(debt_eq - float(cfg.get('debt_equity_stress_start', 0.75)), 0.0) * float(cfg.get('debt_equity_stress_slope', 0.08)), 0.0, float(cfg.get('max_leverage_extra_compression', 0.12)))
    compression = _clip(float(cfg.get('bear_eps_compression', 0.18)) + leverage_extra, float(cfg.get('bear_eps_compression', 0.18)), float(cfg.get('bear_eps_compression_cap', 0.35)))
    bear = eps * (1.0 - compression) * max(float(cfg.get('bear_pe_floor', 5.0)), pe_base * float(cfg.get('bear_multiple_factor', 0.78)))
    bull_growth = _clip(max(g, float(cfg.get('bull_growth_floor', 0.08))) + float(cfg.get('bull_growth_increment', 0.08)), float(cfg.get('bull_growth_floor', 0.08)), float(cfg.get('bull_growth_cap', 0.30)))
    bull = min(eps * (1.0 + bull_growth) * min(float(cfg.get('bull_pe_cap', 30.0)), pe_base * float(cfg.get('bull_multiple_factor', 1.12))), bull_cap)
    return bear, base, bull, []


def _financial_targets(row: pd.Series, current: float, median: float, bull_cap: float, policy: dict) -> tuple[float, float, float, list[str]]:
    cfg = policy.get('financials', {}) or {}
    bvps = _first_num(row, 'fundamental_book_value_per_share', 'book_value_per_share')
    pb = _first_num(row, 'fundamental_price_to_book', 'price_to_book')
    roe = _rate(_first_num(row, 'fundamental_roe', 'roe'))
    flags: list[str] = ['DEBT_EQUITY_NOT_USED_FOR_FINANCIALS']
    if bvps is None and pb is not None and pb > 0:
        bvps = current / pb
    if bvps is None or bvps <= 0 or roe is None:
        raise ValueError('FINANCIAL_FUNDAMENTALS_INCOMPLETE')
    sustainable_roe = _clip(roe, float(cfg.get('roe_floor', 0.04)), float(cfg.get('roe_cap', 0.22)))
    base_pb = _clip(float(cfg.get('base_pb_anchor', 1.0)) + float(cfg.get('roe_pb_sensitivity', 3.0)) * (sustainable_roe - float(cfg.get('cost_of_equity_anchor', 0.10))), float(cfg.get('base_pb_floor', 0.45)), float(cfg.get('base_pb_cap', 2.20)))
    fundamental_base = bvps * base_pb
    blend = float(cfg.get('consensus_base_blend', 0.20))
    base = (1.0 - blend) * fundamental_base + blend * median
    bear = bvps * max(float(cfg.get('bear_pb_floor', 0.35)), base_pb * float(cfg.get('bear_pb_factor', 0.72)))
    bull = min(bvps * min(float(cfg.get('bull_pb_cap', 2.75)), base_pb * float(cfg.get('bull_pb_factor', 1.20))), bull_cap)
    return bear, base, bull, flags


def _energy_targets(row: pd.Series, current: float, median: float, bull_cap: float, policy: dict) -> tuple[float, float, float, list[str]]:
    cfg = policy.get('energy', {}) or {}
    eps = _num(row.get('fundamental_eps_normalized')); pe = _num(row.get('fundamental_pe_normalized'))
    fcf_yield = _rate(_first_num(row, 'fundamental_fcf_yield', 'fcf_yield'))
    dividend_yield = _rate(_first_num(row, 'fundamental_dividend_yield', 'dividend_yield')) or 0.0
    if eps is None or eps <= 0 or pe is None or pe <= 0:
        raise ValueError('ENERGY_FUNDAMENTALS_INCOMPLETE')
    pe_base = _clip(pe, float(cfg.get('base_pe_floor', 5.0)), float(cfg.get('base_pe_cap', 14.0)))
    earnings_base = eps * pe_base
    fcf_base = current if fcf_yield is None or fcf_yield <= 0 else current * _clip(fcf_yield / float(cfg.get('normalized_fcf_yield', 0.08)), 0.70, 1.30)
    base_fundamental = float(cfg.get('earnings_weight', 0.65)) * earnings_base + (1.0 - float(cfg.get('earnings_weight', 0.65))) * fcf_base
    base = (1.0 - float(cfg.get('consensus_base_blend', 0.15))) * base_fundamental + float(cfg.get('consensus_base_blend', 0.15)) * median
    bear = base_fundamental * float(cfg.get('bear_cycle_factor', 0.72)) + current * dividend_yield * float(cfg.get('dividend_credit', 0.50))
    bull = min(base_fundamental * float(cfg.get('bull_cycle_factor', 1.28)) + current * dividend_yield, bull_cap)
    return bear, base, bull, ['ENERGY_CYCLE_NORMALIZATION_APPLIED']


def _equity_review(row: pd.Series, policy: dict) -> dict[str, Any]:
    out = row.to_dict(); blockers: list[str] = []; flags: list[str] = []
    current = _num(row.get('current_price')); confidence = _num(row.get('valuation_confidence'))
    if current is None or current <= 0: blockers.append('SCENARIO_CURRENT_PRICE_MISSING')
    if confidence is None or not 0 <= confidence <= 1: blockers.append('SCENARIO_CONFIDENCE_MISSING')
    if blockers:
        out.update(scenario_validated=False, scenario_review_status='SCENARIO_NOT_VALIDATED', scenario_review_blockers=blockers, scenario_review_flags=flags, scenario_method='SECTOR_AWARE_FUNDAMENTAL_SCENARIO_ENGINE_V2')
        return out
    identity_ok, identity_blockers, identity_meta = _identity_check(row, policy)
    blockers.extend(identity_blockers)
    high, median, low, dispersion, consensus_flags, bull_cap = _consensus(row, current, policy)
    flags.extend(consensus_flags)
    if any(x is None or x <= 0 for x in (high, median, low)) or bull_cap is None:
        blockers.append('CONSENSUS_DISTRIBUTION_MISSING')
    sector = _classify_sector(row, policy)
    if blockers:
        out.update(**identity_meta, scenario_sector_model=sector, scenario_validated=False, scenario_review_status='SCENARIO_NOT_VALIDATED', scenario_review_blockers=blockers, scenario_review_flags=flags, scenario_method='SECTOR_AWARE_FUNDAMENTAL_SCENARIO_ENGINE_V2')
        return out
    try:
        if sector == 'FINANCIALS':
            bear, base, bull, model_flags = _financial_targets(row, current, median, bull_cap, policy)
        elif sector == 'ENERGY':
            bear, base, bull, model_flags = _energy_targets(row, current, median, bull_cap, policy)
        else:
            bear, base, bull, model_flags = _corporate_targets(row, current, median, bull_cap, policy)
        flags.extend(model_flags)
    except ValueError as exc:
        blockers.append(str(exc))
        bear = base = bull = None
    if bear is not None and base is not None and bull is not None and not (bear > 0 and bear < base < bull):
        blockers.append('FUNDAMENTAL_SCENARIO_ORDER_INVALID')
    bp, bap, brp = _dynamic_probabilities(confidence, dispersion, policy)
    out.update(
        **identity_meta,
        pre_review_bull_target_price=_num(row.get('bull_target_price')), pre_review_base_target_price=_num(row.get('base_target_price')), pre_review_bear_target_price=_num(row.get('bear_target_price')),
        bull_target_price=bull, base_target_price=base, bear_target_price=bear,
        bull_probability=bp, base_probability=bap, bear_probability=brp,
        scenario_sector_model=sector, scenario_validated=not blockers,
        scenario_review_status='SCENARIO_VALIDATED' if not blockers else 'SCENARIO_NOT_VALIDATED', scenario_review_blockers=blockers, scenario_review_flags=flags,
        scenario_method='SECTOR_AWARE_FUNDAMENTAL_SCENARIO_ENGINE_V2', consensus_dispersion=dispersion,
        bear_is_independent_of_analyst_low=True, expected_return_must_be_recomputed_post_review=True,
    )
    return out


def validate_scenarios(frame: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for _, row in frame.iterrows():
        engine = str(row.get('valuation_engine_type') or '').upper(); method = str(row.get('valuation_method') or '')
        if engine == 'EQUITY' and method.startswith('FINNHUB_ANALYST_CONSENSUS'):
            rows.append(_equity_review(row, policy))
        else:
            out = row.to_dict(); ready = str(row.get('valuation_status')) in {'VALUATION_READY', 'VALUATION_READY_WITH_WARNING'}
            out.update(scenario_validated=ready, scenario_review_status='SCENARIO_VALIDATED_SPECIALIZED_ENGINE' if ready else 'SCENARIO_NOT_VALIDATED', scenario_review_blockers=[] if ready else ['UPSTREAM_SPECIALIZED_SCENARIO_NOT_READY'], scenario_review_flags=[], scenario_method=f'SPECIALIZED_UPSTREAM:{method}', expected_return_must_be_recomputed_post_review=True)
            rows.append(out)
    result = pd.DataFrame(rows); valid = int(result.get('scenario_validated', pd.Series(dtype=bool)).fillna(False).sum()); total = len(result)
    return result, {'scenario_review_count': total, 'scenario_validated_count': valid, 'scenario_blocked_count': total - valid, 'scenario_review_complete': bool(total and valid == total), 'scenario_methodology_version': policy.get('methodology_version', 'SCENARIO-2.0')}
