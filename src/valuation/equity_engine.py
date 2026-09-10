from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.finnhub import FinnhubAccessDenied, FinnhubConnector, FinnhubError
from src.valuation.common import age_days, as_float, normalized_probabilities
from src.valuation.index_etf_engine import build_index_etf_scenario


def _metric(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = as_float(metrics.get(name))
        if value is not None:
            return value
    return None


def build_equity_scenario(symbol: str, current_price: float | None, connector: FinnhubConnector, policy: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    ticker = symbol.upper(); blockers = []; freshness = policy.get('freshness', {}); quality = policy.get('quality', {}); confidence_policy = policy.get('confidence', {}); probability_policy = policy.get('probabilities', {})
    max_pt_age = int(freshness.get('price_target_max_age_days', 45)); min_analysts = int(quality.get('minimum_equity_analyst_count', 3))
    try:
        price_target = connector.price_target(ticker)
    except (FinnhubAccessDenied, FinnhubError) as exc:
        if ticker in (policy.get('index_etf_models', {}) or {}): return build_index_etf_scenario(ticker, current_price, policy)
        code = str(exc) if isinstance(exc, FinnhubAccessDenied) else 'FINNHUB_REQUEST_FAILED'
        return {'underlying_ticker': ticker, 'valuation_method': 'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4', 'valuation_status': 'BLOCKED_BY_DATA', 'valuation_confidence': None, 'blockers': [code], 'source_ref': 'Finnhub /stock/price-target', 'retrieved_at': connector.retrieved_at()}

    high = as_float(price_target.get('targetHigh')); mean = as_float(price_target.get('targetMean')); median = as_float(price_target.get('targetMedian')); low = as_float(price_target.get('targetLow')); analyst_count = as_float(price_target.get('numberAnalysts'))
    last_updated = price_target.get('lastUpdated'); pt_age = age_days(last_updated, as_of=as_of)
    if any(v is None or v <= 0 for v in (high, mean, low)): blockers.append('PRICE_TARGET_FIELDS_MISSING')
    if not blockers and not (low <= mean <= high): blockers.append('PRICE_TARGET_ORDER_INVALID')
    if pt_age is None: blockers.append('PRICE_TARGET_FRESHNESS_UNKNOWN')
    elif pt_age < 0 or pt_age > max_pt_age: blockers.append('PRICE_TARGET_STALE')
    if analyst_count is None or analyst_count < min_analysts: blockers.append('INSUFFICIENT_ANALYST_COVERAGE')
    if current_price is None or current_price <= 0: blockers.append('CURRENT_PRICE_MISSING')

    fundamental_error = None; metrics = {}
    try:
        raw = connector.basic_financials(ticker); metrics = raw.get('metric', {}) if isinstance(raw, dict) and isinstance(raw.get('metric'), dict) else {}
    except (FinnhubAccessDenied, FinnhubError) as exc:
        fundamental_error = str(exc) if isinstance(exc, FinnhubAccessDenied) else 'FINNHUB_FUNDAMENTALS_REQUEST_FAILED'

    eps = _metric(metrics, 'epsNormalizedAnnual', 'epsBasicExclExtraItemsAnnual', 'epsTTM')
    pe = _metric(metrics, 'peNormalizedAnnual', 'peBasicExclExtraTTM', 'peTTM')
    eps_growth = _metric(metrics, 'epsGrowth3Y', 'epsGrowth5Y', 'epsGrowthTTMYoy')
    debt_equity = _metric(metrics, 'totalDebt/totalEquityAnnual', 'totalDebt/totalEquityQuarterly')
    net_margin = _metric(metrics, 'netProfitMarginAnnual', 'netProfitMarginTTM')
    current_ratio = _metric(metrics, 'currentRatioAnnual', 'currentRatioQuarterly')
    pb = _metric(metrics, 'pbAnnual', 'pbQuarterly', 'priceToBookAnnual', 'priceToBookQuarterly')
    bvps = _metric(metrics, 'bookValuePerShareAnnual', 'bookValuePerShareQuarterly')
    roe = _metric(metrics, 'roeRfy', 'roeTTM', 'returnOnEquityAnnual', 'returnOnEquityTTM')
    dividend_yield = _metric(metrics, 'dividendYieldIndicatedAnnual', 'dividendYield5Y', 'currentDividendYieldTTM')
    fcf_per_share = _metric(metrics, 'freeCashFlowPerShareTTM', 'freeCashFlowPerShareAnnual')
    fcf_yield = (fcf_per_share / current_price) if fcf_per_share is not None and current_price and current_price > 0 else None
    common = {
        'underlying_ticker': ticker, 'valuation_method': 'FINNHUB_ANALYST_CONSENSUS_SCREENING_V4', 'current_price': current_price,
        'analyst_count': analyst_count, 'consensus_target_high': high, 'consensus_target_mean': mean, 'consensus_target_median': median, 'consensus_target_low': low,
        'price_target_last_updated': last_updated, 'price_target_age_days': pt_age,
        'fundamental_eps_normalized': eps, 'fundamental_pe_normalized': pe, 'fundamental_eps_growth_3y': eps_growth,
        'fundamental_debt_to_equity': debt_equity, 'fundamental_net_margin': net_margin, 'fundamental_current_ratio': current_ratio,
        'fundamental_price_to_book': pb, 'fundamental_book_value_per_share': bvps, 'fundamental_roe': roe,
        'fundamental_dividend_yield': dividend_yield, 'fundamental_fcf_yield': fcf_yield,
        'eps_unit': 'UNDERLYING_SECURITY', 'target_price_unit': 'UNDERLYING_SECURITY',
        'fundamental_source_error': fundamental_error, 'fundamental_source_ref': 'Finnhub /stock/metric?metric=all',
        'enrichment_status': 'SECTOR_AWARE_FUNDAMENTALS_ATTACHED', 'source_date': last_updated,
        'source_ref': 'Finnhub /stock/price-target + /stock/metric', 'retrieved_at': connector.retrieved_at(),
    }

    if blockers:
        if ticker in (policy.get('index_etf_models', {}) or {}):
            aggregate = build_index_etf_scenario(ticker, current_price, policy)
            if aggregate.get('valuation_status') == 'VALUATION_READY': aggregate['analyst_consensus_blockers'] = blockers; aggregate['enrichment_status'] = 'INDEX_AGGREGATE_FUNDAMENTALS_FALLBACK'; aggregate['retrieved_at'] = connector.retrieved_at(); return aggregate
        return {**common, 'valuation_status': 'BLOCKED_BY_DATA', 'valuation_confidence': None, 'bull_target_price': None, 'base_target_price': None, 'bear_target_price': None, 'bull_probability': None, 'base_probability': None, 'bear_probability': None, 'blockers': blockers}

    prior = normalized_probabilities((float(probability_policy.get('prior_bull', .25)), float(probability_policy.get('prior_base', .50)), float(probability_policy.get('prior_bear', .25))))
    confidence = float(confidence_policy.get('base', .35))
    if pt_age is not None and 0 <= pt_age <= max_pt_age: confidence += float(confidence_policy.get('fresh_price_target_bonus', .20))
    if analyst_count: confidence += min(analyst_count / 20.0, 1.0) * float(confidence_policy.get('analyst_count_bonus_max', .15))
    if eps is not None and pe is not None and eps_growth is not None: confidence += float(confidence_policy.get('fundamentals_bonus', .10))
    confidence = min(confidence, 1.0)
    base_target = median if median is not None and median > 0 else mean
    if base_target is not None and mean is not None: base_target = .70 * mean + .30 * base_target
    return {**common, 'valuation_status': 'VALUATION_READY', 'valuation_confidence': round(confidence, 4), 'bull_target_price': high, 'base_target_price': base_target, 'bear_target_price': low, 'bull_probability': prior[0], 'base_probability': prior[1], 'bear_probability': prior[2], 'blockers': []}
