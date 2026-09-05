from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.finnhub import FinnhubAccessDenied, FinnhubConnector, FinnhubError
from src.valuation.common import age_days, as_float, normalized_probabilities


ConstituentScenario = tuple[dict[str, float] | None, str | None]


def _holding_scenario_return(
    holding_symbol: str,
    connector: FinnhubConnector,
    max_price_target_age_days: int,
    as_of: date | None,
) -> ConstituentScenario:
    try:
        quote = connector.quote(holding_symbol)
        target = connector.price_target(holding_symbol)
    except FinnhubError as exc:
        return None, str(exc)
    current = as_float(quote.get("c")) or as_float(quote.get("pc"))
    high = as_float(target.get("targetHigh"))
    mean = as_float(target.get("targetMean"))
    median = as_float(target.get("targetMedian"))
    low = as_float(target.get("targetLow"))
    analyst_count = as_float(target.get("numberAnalysts")) or 0.0
    pt_age = age_days(target.get("lastUpdated"), as_of=as_of)
    if current is None or current <= 0 or any(v is None or v <= 0 for v in (high, mean, low)):
        return None, "HOLDING_TARGET_MISSING"
    if pt_age is None or pt_age < 0 or pt_age > max_price_target_age_days:
        return None, "HOLDING_TARGET_STALE"
    if analyst_count < 3:
        return None, "HOLDING_ANALYST_COVERAGE_LOW"
    base = 0.70 * mean + 0.30 * (median if median is not None and median > 0 else mean)
    return {
        "bull": high / current - 1.0,
        "base": base / current - 1.0,
        "bear": low / current - 1.0,
        "analyst_count": analyst_count,
        "age_days": float(pt_age),
    }, None


def _cached_holding_scenario_return(
    holding_symbol: str,
    connector: FinnhubConnector,
    max_price_target_age_days: int,
    as_of: date | None,
    constituent_cache: dict[str, ConstituentScenario] | None,
) -> tuple[ConstituentScenario, bool]:
    symbol = holding_symbol.strip().upper()
    if constituent_cache is not None and symbol in constituent_cache:
        return constituent_cache[symbol], True
    result = _holding_scenario_return(symbol, connector, max_price_target_age_days, as_of)
    if constituent_cache is not None:
        constituent_cache[symbol] = result
    return result, False


def build_etf_scenario(
    symbol: str,
    current_price: float | None,
    connector: FinnhubConnector,
    policy: dict[str, Any],
    as_of: date | None = None,
    constituent_cache: dict[str, ConstituentScenario] | None = None,
) -> dict[str, Any]:
    ticker = symbol.upper()
    blockers: list[str] = []
    freshness = policy.get("freshness", {})
    quality = policy.get("quality", {})
    confidence_policy = policy.get("confidence", {})

    try:
        profile_payload = connector.etf_profile(ticker)
        holdings_payload = connector.etf_holdings(ticker)
    except FinnhubAccessDenied as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "FINNHUB_ETF_LOOKTHROUGH_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": [str(exc), "ETF_PREMIUM_ACCESS_REQUIRED_OR_UNAVAILABLE"],
            "source_ref": "Finnhub ETF API",
            "retrieved_at": connector.retrieved_at(),
        }
    except FinnhubError as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "FINNHUB_ETF_LOOKTHROUGH_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": ["FINNHUB_ETF_REQUEST_FAILED", str(exc)],
            "source_ref": "Finnhub ETF API",
            "retrieved_at": connector.retrieved_at(),
        }

    profile = profile_payload.get("profile") if isinstance(profile_payload.get("profile"), dict) else profile_payload
    holdings = holdings_payload.get("holdings") if isinstance(holdings_payload, dict) else None
    holdings = holdings if isinstance(holdings, list) else []
    holdings_date = holdings_payload.get("atDate") if isinstance(holdings_payload, dict) else None
    holdings_age = age_days(holdings_date, as_of=as_of)
    max_holdings_age = int(freshness.get("etf_holdings_max_age_days", 35))

    if current_price is None or current_price <= 0:
        blockers.append("CURRENT_PRICE_MISSING")
    if not holdings:
        blockers.append("ETF_HOLDINGS_MISSING")
    if holdings_age is None:
        blockers.append("ETF_HOLDINGS_FRESHNESS_UNKNOWN")
    elif holdings_age < 0 or holdings_age > max_holdings_age:
        blockers.append("ETF_HOLDINGS_STALE")

    max_holdings = int(quality.get("maximum_etf_holdings_to_analyze", 50))
    sorted_holdings = sorted(holdings, key=lambda x: as_float(x.get("percent")) or 0.0, reverse=True)[:max_holdings]
    min_covered = float(quality.get("minimum_etf_covered_weight", 0.50))
    min_valid = int(quality.get("minimum_etf_valid_holdings", 5))

    covered_weight = 0.0
    valid_count = 0
    analyzed_count = 0
    weighted_bull = 0.0
    weighted_base = 0.0
    weighted_bear = 0.0
    weighted_analysts = 0.0
    holding_errors: dict[str, int] = {}
    max_pt_age = int(freshness.get("price_target_max_age_days", 45))
    shared_cache_hits = 0
    direct_constituent_lookups = 0

    for holding in sorted_holdings:
        h_symbol = str(holding.get("symbol") or "").strip().upper()
        weight_pct = as_float(holding.get("percent"))
        if not h_symbol or weight_pct is None or weight_pct <= 0:
            continue
        analyzed_count += 1
        weight = weight_pct / 100.0
        (scenario, error), from_cache = _cached_holding_scenario_return(
            h_symbol, connector, max_pt_age, as_of, constituent_cache
        )
        if from_cache:
            shared_cache_hits += 1
        else:
            direct_constituent_lookups += 1
        if scenario is None:
            holding_errors[error or "UNKNOWN"] = holding_errors.get(error or "UNKNOWN", 0) + 1
            continue
        covered_weight += weight
        valid_count += 1
        weighted_bull += weight * scenario["bull"]
        weighted_base += weight * scenario["base"]
        weighted_bear += weight * scenario["bear"]
        weighted_analysts += weight * scenario["analyst_count"]

        # Once the deterministic coverage hurdle is met, additional holdings do
        # not change eligibility and only consume provider quota.
        if covered_weight >= min_covered and valid_count >= min_valid:
            break

    if covered_weight < min_covered:
        blockers.append("ETF_LOOKTHROUGH_COVERAGE_INSUFFICIENT")
    if valid_count < min_valid:
        blockers.append("ETF_VALID_HOLDINGS_INSUFFICIENT")

    dividend_yield = as_float((profile or {}).get("dividendYield"))
    if dividend_yield is not None:
        if dividend_yield > 1.0:
            dividend_yield /= 100.0
        if dividend_yield < 0 or dividend_yield > 0.25:
            dividend_yield = None
    dividend_yield = dividend_yield or 0.0

    bull_return = weighted_bull + covered_weight * dividend_yield
    base_return = weighted_base + covered_weight * dividend_yield
    bear_return = weighted_bear + covered_weight * dividend_yield

    if not blockers and not (bear_return <= base_return <= bull_return):
        blockers.append("ETF_SCENARIO_ORDER_INVALID")

    confidence = float(confidence_policy.get("base", 0.35))
    confidence += min(covered_weight, 1.0) * float(confidence_policy.get("etf_holdings_coverage_bonus_max", 0.20))
    if holdings_age is not None and 0 <= holdings_age <= max_holdings_age:
        confidence += float(confidence_policy.get("etf_fresh_holdings_bonus", 0.10))
    if valid_count >= min_valid:
        confidence += min(valid_count / max(min_valid * 4, 1), 1.0) * float(confidence_policy.get("analyst_count_bonus_max", 0.15))
    confidence = min(confidence, 1.0)

    prior = (
        float(policy.get("probabilities", {}).get("prior_bull", 0.25)),
        float(policy.get("probabilities", {}).get("prior_base", 0.50)),
        float(policy.get("probabilities", {}).get("prior_bear", 0.25)),
    )
    probs = normalized_probabilities(prior)
    valuation_status = "VALUATION_READY" if not blockers else "BLOCKED_BY_DATA"
    return {
        "underlying_ticker": ticker,
        "valuation_method": "FINNHUB_ETF_LOOKTHROUGH_V1",
        "valuation_status": valuation_status,
        "valuation_confidence": round(confidence, 4) if not blockers else None,
        "bull_target_price": current_price * (1.0 + bull_return) if not blockers else None,
        "base_target_price": current_price * (1.0 + base_return) if not blockers else None,
        "bear_target_price": current_price * (1.0 + bear_return) if not blockers else None,
        "bull_probability": probs[0] if not blockers else None,
        "base_probability": probs[1] if not blockers else None,
        "bear_probability": probs[2] if not blockers else None,
        "current_price": current_price,
        "etf_holdings_date": holdings_date,
        "etf_holdings_age_days": holdings_age,
        "etf_lookthrough_covered_weight": covered_weight,
        "etf_valid_holding_count": valid_count,
        "etf_analyzed_holding_count": analyzed_count,
        "etf_shared_constituent_cache_hits": shared_cache_hits,
        "etf_direct_constituent_lookups": direct_constituent_lookups,
        "weighted_analyst_count_proxy": weighted_analysts,
        "etf_dividend_yield": dividend_yield,
        "holding_error_counts": holding_errors,
        "blockers": blockers,
        "source_date": holdings_date,
        "source_ref": "Finnhub /etf/profile + /etf/holdings + shared constituent cache",
        "retrieved_at": connector.retrieved_at(),
    }
