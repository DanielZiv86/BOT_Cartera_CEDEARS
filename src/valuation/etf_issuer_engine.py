from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.finnhub import FinnhubConnector
from src.connectors.issuer_holdings import IssuerHoldingsConnector, IssuerHoldingsError
from src.valuation.common import age_days, normalized_probabilities
from src.valuation.etf_engine import _holding_scenario_return


def build_issuer_etf_scenario(
    symbol: str,
    current_price: float | None,
    finnhub: FinnhubConnector,
    issuer_holdings: IssuerHoldingsConnector,
    policy: dict[str, Any],
    as_of: date | None = None,
) -> dict[str, Any]:
    ticker = symbol.upper()
    blockers: list[str] = []
    freshness = policy.get("freshness", {})
    quality = policy.get("quality", {})
    confidence_policy = policy.get("confidence", {})

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
        snapshot = issuer_holdings.fetch(ticker)
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
    max_holdings_age = int(freshness.get("etf_holdings_max_age_days", 35))
    if current_price is None or current_price <= 0:
        blockers.append("CURRENT_PRICE_MISSING")
    if holdings_age is None:
        blockers.append("ETF_HOLDINGS_FRESHNESS_UNKNOWN")
    elif holdings_age < 0 or holdings_age > max_holdings_age:
        blockers.append("ETF_HOLDINGS_STALE")

    max_holdings = int(quality.get("maximum_etf_holdings_to_analyze", 50))
    sorted_holdings = sorted(snapshot.holdings, key=lambda x: float(x.get("percent") or 0), reverse=True)[:max_holdings]

    covered_weight = 0.0
    valid_count = 0
    weighted_bull = 0.0
    weighted_base = 0.0
    weighted_bear = 0.0
    holding_errors: dict[str, int] = {}
    max_pt_age = int(freshness.get("price_target_max_age_days", 45))

    # Normalize percentage-point versus fractional weights defensively.
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
        weight = raw_weight / scale
        scenario, error = _holding_scenario_return(h_symbol, finnhub, max_pt_age, as_of)
        if scenario is None:
            holding_errors[error or "UNKNOWN"] = holding_errors.get(error or "UNKNOWN", 0) + 1
            continue
        covered_weight += weight
        valid_count += 1
        weighted_bull += weight * scenario["bull"]
        weighted_base += weight * scenario["base"]
        weighted_bear += weight * scenario["bear"]

    min_covered = float(quality.get("minimum_etf_covered_weight", 0.50))
    min_valid = int(quality.get("minimum_etf_valid_holdings", 5))
    if covered_weight < min_covered:
        blockers.append("ETF_LOOKTHROUGH_COVERAGE_INSUFFICIENT")
    if valid_count < min_valid:
        blockers.append("ETF_VALID_HOLDINGS_INSUFFICIENT")

    # Uncovered weight receives 0% price return. This is intentionally conservative.
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
        "etf_lookthrough_covered_weight": covered_weight,
        "etf_valid_holding_count": valid_count,
        "etf_analyzed_holding_count": len(sorted_holdings),
        "holding_error_counts": holding_errors,
        "holdings_source_tier": snapshot.source_tier,
        "holdings_provider": snapshot.provider,
        "blockers": blockers,
        "source_date": snapshot.as_of,
        "source_ref": snapshot.source_ref,
        "retrieved_at": issuer_holdings.retrieved_at(),
    }
