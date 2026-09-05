from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.finnhub import FinnhubConnector
from src.connectors.issuer_holdings import HoldingsSnapshot, IssuerHoldingsConnector, IssuerHoldingsError
from src.valuation.common import age_days, normalized_probabilities
from src.valuation.etf_engine import ConstituentScenario, _cached_holding_scenario_return


def _cached_equity_return(row: dict[str, Any] | None) -> dict[str, float] | None:
    if not row or row.get("valuation_status") != "VALUATION_READY":
        return None
    current = row.get("current_price")
    bull = row.get("bull_target_price")
    base = row.get("base_target_price")
    bear = row.get("bear_target_price")
    try:
        current = float(current)
        bull = float(bull)
        base = float(base)
        bear = float(bear)
    except (TypeError, ValueError):
        return None
    if current <= 0 or min(bull, base, bear) <= 0:
        return None
    return {
        "bull": bull / current - 1.0,
        "base": base / current - 1.0,
        "bear": bear / current - 1.0,
    }


def build_issuer_etf_scenario(
    symbol: str,
    current_price: float | None,
    finnhub: FinnhubConnector,
    issuer_holdings: IssuerHoldingsConnector,
    policy: dict[str, Any],
    as_of: date | None = None,
    equity_scenarios: dict[str, dict[str, Any]] | None = None,
    constituent_cache: dict[str, ConstituentScenario] | None = None,
    direct_lookup_budget: dict[str, int] | None = None,
    holdings_snapshot: HoldingsSnapshot | None = None,
) -> dict[str, Any]:
    ticker = symbol.upper()
    blockers: list[str] = []
    freshness = policy.get("freshness", {})
    quality = policy.get("quality", {})
    confidence_policy = policy.get("confidence", {})
    equity_scenarios = equity_scenarios or {}

    special = {str(t).upper() for t in policy.get("instrument_overrides", {}).get("non_equity_trackers", [])}
    if ticker in special:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "NON_EQUITY_TRACKER_REQUIRES_DEDICATED_MODEL",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": ["NON_EQUITY_TRACKER_NOT_ELIGIBLE_FOR_EQUITY_LOOKTHROUGH"],
            "source_ref": "ETF issuer fallback policy",
            "retrieved_at": issuer_holdings.retrieved_at(),
        }

    try:
        snapshot = holdings_snapshot or issuer_holdings.fetch(ticker)
    except IssuerHoldingsError as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "ISSUER_HOLDINGS_LOOKTHROUGH_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": ["ISSUER_HOLDINGS_UNAVAILABLE", str(exc)],
            "source_ref": "Configured issuer holdings sources",
            "retrieved_at": issuer_holdings.retrieved_at(),
        }

    holdings_age = age_days(snapshot.as_of, as_of=as_of)
    default_holdings_age = int(freshness.get("etf_holdings_max_age_days", 35))
    max_holdings_age = snapshot.freshness_max_age_days or default_holdings_age
    if current_price is None or current_price <= 0:
        blockers.append("CURRENT_PRICE_MISSING")
    if holdings_age is None:
        blockers.append("ETF_HOLDINGS_FRESHNESS_UNKNOWN")
    elif holdings_age < 0 or holdings_age > max_holdings_age:
        blockers.append("ETF_HOLDINGS_STALE")

    default_max_holdings = int(quality.get("maximum_etf_holdings_to_analyze", 50))
    max_holdings = snapshot.max_holdings_to_analyze or default_max_holdings
    sorted_holdings = sorted(snapshot.holdings, key=lambda x: float(x.get("percent") or 0), reverse=True)[:max_holdings]
    min_covered = float(quality.get("minimum_etf_covered_weight", 0.50))
    min_valid = int(quality.get("minimum_etf_valid_holdings", 5))
    max_direct_per_etf = int(quality.get("maximum_direct_constituent_lookups_per_etf", 8))

    covered_weight = 0.0
    valid_count = 0
    weighted_bull = 0.0
    weighted_base = 0.0
    weighted_bear = 0.0
    holding_errors: dict[str, int] = {}
    max_pt_age = int(freshness.get("price_target_max_age_days", 45))
    cached_equity_count = 0
    shared_cache_hits = 0
    direct_finnhub_count = 0
    analyzed_count = 0

    total_raw = sum(float(h.get("percent") or 0) for h in sorted_holdings)
    scale = 1.0 if total_raw <= 1.5 else 100.0

    for holding in sorted_holdings:
        h_symbol = str(holding.get("symbol") or "").strip().upper()
        try:
            raw_weight = float(holding.get("percent") or 0)
        except (TypeError, ValueError):
            continue
        if not h_symbol or raw_weight <= 0:
            continue
        analyzed_count += 1
        weight = raw_weight / scale

        scenario = _cached_equity_return(equity_scenarios.get(h_symbol))
        error = None
        if scenario is not None:
            cached_equity_count += 1
        else:
            from_existing_shared_cache = constituent_cache is not None and h_symbol in constituent_cache
            if not from_existing_shared_cache:
                global_remaining = direct_lookup_budget.get("remaining", 0) if direct_lookup_budget is not None else None
                if direct_finnhub_count >= max_direct_per_etf:
                    scenario, error = None, "ETF_DIRECT_LOOKUP_BUDGET_PER_FUND_EXHAUSTED"
                elif global_remaining is not None and global_remaining <= 0:
                    scenario, error = None, "ETF_DIRECT_LOOKUP_BUDGET_GLOBAL_EXHAUSTED"
                else:
                    if direct_lookup_budget is not None:
                        direct_lookup_budget["remaining"] = global_remaining - 1
                    direct_finnhub_count += 1
                    (scenario, error), _ = _cached_holding_scenario_return(
                        h_symbol, finnhub, max_pt_age, as_of, constituent_cache
                    )
            else:
                (scenario, error), _ = _cached_holding_scenario_return(
                    h_symbol, finnhub, max_pt_age, as_of, constituent_cache
                )
                shared_cache_hits += 1

        if scenario is None:
            holding_errors[error or "NO_READY_EQUITY_VALUATION"] = holding_errors.get(error or "NO_READY_EQUITY_VALUATION", 0) + 1
            continue
        covered_weight += weight
        valid_count += 1
        weighted_bull += weight * scenario["bull"]
        weighted_base += weight * scenario["base"]
        weighted_bear += weight * scenario["bear"]

        if covered_weight >= min_covered and valid_count >= min_valid:
            break

    if covered_weight < min_covered:
        blockers.append("ETF_LOOKTHROUGH_COVERAGE_INSUFFICIENT")
    if valid_count < min_valid:
        blockers.append("ETF_VALID_HOLDINGS_INSUFFICIENT")

    bull_return = weighted_bull
    base_return = weighted_base
    bear_return = weighted_bear
    if not blockers and not (bear_return <= base_return <= bull_return):
        blockers.append("ETF_SCENARIO_ORDER_INVALID")

    confidence = float(confidence_policy.get("base", 0.35))
    source_bonus = 0.12 if snapshot.source_tier == "ISSUER_OFFICIAL" else 0.04
    confidence += source_bonus
    confidence += min(max(covered_weight, 0.0), 1.0) * float(confidence_policy.get("etf_holdings_coverage_bonus_max", 0.20))
    if holdings_age is not None and 0 <= holdings_age <= max_holdings_age:
        confidence += float(confidence_policy.get("etf_fresh_holdings_bonus", 0.10))
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
        "valuation_method": "ISSUER_HOLDINGS_LOOKTHROUGH_V1",
        "valuation_status": valuation_status,
        "valuation_confidence": round(confidence, 4) if not blockers else None,
        "bull_target_price": current_price * (1.0 + bull_return) if not blockers else None,
        "base_target_price": current_price * (1.0 + base_return) if not blockers else None,
        "bear_target_price": current_price * (1.0 + bear_return) if not blockers else None,
        "bull_probability": probs[0] if not blockers else None,
        "base_probability": probs[1] if not blockers else None,
        "bear_probability": probs[2] if not blockers else None,
        "current_price": current_price,
        "etf_holdings_date": snapshot.as_of,
        "etf_holdings_age_days": holdings_age,
        "etf_holdings_max_age_days_applied": max_holdings_age,
        "etf_lookthrough_covered_weight": covered_weight,
        "etf_valid_holding_count": valid_count,
        "etf_analyzed_holding_count": analyzed_count,
        "etf_cached_equity_count": cached_equity_count,
        "etf_shared_constituent_cache_hits": shared_cache_hits,
        "etf_direct_finnhub_count": direct_finnhub_count,
        "holding_error_counts": holding_errors,
        "holdings_source_tier": snapshot.source_tier,
        "holdings_provider": snapshot.provider,
        "blockers": blockers,
        "source_date": snapshot.as_of,
        "source_ref": snapshot.source_ref,
        "retrieved_at": issuer_holdings.retrieved_at(),
    }
