from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.finnhub import FinnhubAccessDenied, FinnhubConnector, FinnhubError
from src.valuation.common import age_days, as_float, normalized_probabilities


def build_equity_scenario(
    symbol: str,
    current_price: float | None,
    connector: FinnhubConnector,
    policy: dict[str, Any],
    as_of: date | None = None,
) -> dict[str, Any]:
    """Build the broad-universe equity valuation scenario.

    Universe mode intentionally uses only Finnhub /stock/price-target as the
    material external input. Recommendation trends and fundamental metrics are
    deferred to Deep Research for shortlisted candidates. This keeps the full
    305-name run bounded, deterministic and auditable without weakening the
    price-target freshness or analyst-coverage gates.
    """
    ticker = symbol.upper()
    blockers: list[str] = []
    freshness = policy.get("freshness", {})
    quality = policy.get("quality", {})
    confidence_policy = policy.get("confidence", {})
    probability_policy = policy.get("probabilities", {})
    max_pt_age = int(freshness.get("price_target_max_age_days", 45))
    min_analysts = int(quality.get("minimum_equity_analyst_count", 3))

    try:
        price_target = connector.price_target(ticker)
    except FinnhubAccessDenied as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "FINNHUB_ANALYST_CONSENSUS_SCREENING_V2",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": [str(exc)],
            "source_ref": "Finnhub /stock/price-target",
            "retrieved_at": connector.retrieved_at(),
        }
    except FinnhubError as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "FINNHUB_ANALYST_CONSENSUS_SCREENING_V2",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": ["FINNHUB_REQUEST_FAILED", str(exc)],
            "source_ref": "Finnhub /stock/price-target",
            "retrieved_at": connector.retrieved_at(),
        }

    high = as_float(price_target.get("targetHigh"))
    mean = as_float(price_target.get("targetMean"))
    median = as_float(price_target.get("targetMedian"))
    low = as_float(price_target.get("targetLow"))
    analyst_count = as_float(price_target.get("numberAnalysts"))
    last_updated = price_target.get("lastUpdated")
    pt_age = age_days(last_updated, as_of=as_of)

    if any(v is None or v <= 0 for v in (high, mean, low)):
        blockers.append("PRICE_TARGET_FIELDS_MISSING")
    if not blockers and not (low <= mean <= high):
        blockers.append("PRICE_TARGET_ORDER_INVALID")
    if pt_age is None:
        blockers.append("PRICE_TARGET_FRESHNESS_UNKNOWN")
    elif pt_age < 0 or pt_age > max_pt_age:
        blockers.append("PRICE_TARGET_STALE")
    if analyst_count is None or analyst_count < min_analysts:
        blockers.append("INSUFFICIENT_ANALYST_COVERAGE")
    if current_price is None or current_price <= 0:
        blockers.append("CURRENT_PRICE_MISSING")

    common = {
        "underlying_ticker": ticker,
        "valuation_method": "FINNHUB_ANALYST_CONSENSUS_SCREENING_V2",
        "current_price": current_price,
        "analyst_count": analyst_count,
        "price_target_last_updated": last_updated,
        "price_target_age_days": pt_age,
        "recommendation_period": None,
        "recommendation_age_days": None,
        "latest_fundamental_period": None,
        "fundamentals_age_days": None,
        "enrichment_status": "DEFERRED_TO_DEEP_RESEARCH",
        "source_date": last_updated,
        "source_ref": "Finnhub /stock/price-target",
        "retrieved_at": connector.retrieved_at(),
    }

    if blockers:
        return {
            **common,
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "bull_target_price": None,
            "base_target_price": None,
            "bear_target_price": None,
            "bull_probability": None,
            "base_probability": None,
            "bear_probability": None,
            "blockers": blockers,
        }

    prior = normalized_probabilities((
        float(probability_policy.get("prior_bull", 0.25)),
        float(probability_policy.get("prior_base", 0.50)),
        float(probability_policy.get("prior_bear", 0.25)),
    ))

    confidence = float(confidence_policy.get("base", 0.35))
    if pt_age is not None and 0 <= pt_age <= max_pt_age:
        confidence += float(confidence_policy.get("fresh_price_target_bonus", 0.20))
    if analyst_count:
        confidence += min(analyst_count / 20.0, 1.0) * float(confidence_policy.get("analyst_count_bonus_max", 0.15))
    confidence = min(confidence, 1.0)

    base_target = median if median is not None and median > 0 else mean
    if base_target is not None and mean is not None:
        base_target = 0.70 * mean + 0.30 * base_target

    return {
        **common,
        "valuation_status": "VALUATION_READY",
        "valuation_confidence": round(confidence, 4),
        "bull_target_price": high,
        "base_target_price": base_target,
        "bear_target_price": low,
        "bull_probability": prior[0],
        "base_probability": prior[1],
        "bear_probability": prior[2],
        "blockers": [],
    }
