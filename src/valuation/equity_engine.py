from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.finnhub import FinnhubAccessDenied, FinnhubConnector, FinnhubError
from src.valuation.common import age_days, as_float, latest_series_period, normalized_probabilities


def _recommendation_probabilities(
    recommendation: dict[str, Any] | None,
    prior: tuple[float, float, float],
    max_blend_weight: float,
) -> tuple[float, float, float]:
    if not recommendation:
        return prior
    strong_buy = as_float(recommendation.get("strongBuy")) or 0.0
    buy = as_float(recommendation.get("buy")) or 0.0
    hold = as_float(recommendation.get("hold")) or 0.0
    sell = as_float(recommendation.get("sell")) or 0.0
    strong_sell = as_float(recommendation.get("strongSell")) or 0.0
    total = strong_buy + buy + hold + sell + strong_sell
    if total <= 0:
        return prior
    observed = ((strong_buy + buy) / total, hold / total, (sell + strong_sell) / total)
    blend = min(total / 20.0, 1.0) * max_blend_weight
    mixed = tuple((1.0 - blend) * p + blend * o for p, o in zip(prior, observed))
    return normalized_probabilities(mixed)


def build_equity_scenario(
    symbol: str,
    current_price: float | None,
    connector: FinnhubConnector,
    policy: dict[str, Any],
    as_of: date | None = None,
) -> dict[str, Any]:
    ticker = symbol.upper()
    blockers: list[str] = []
    try:
        price_target = connector.price_target(ticker)
        recommendations = connector.recommendation_trends(ticker)
        financials = connector.basic_financials(ticker)
    except FinnhubAccessDenied as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "FINNHUB_ANALYST_CONSENSUS_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": [str(exc)],
            "source_ref": "Finnhub API",
            "retrieved_at": connector.retrieved_at(),
        }
    except FinnhubError as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "FINNHUB_ANALYST_CONSENSUS_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": ["FINNHUB_REQUEST_FAILED", str(exc)],
            "source_ref": "Finnhub API",
            "retrieved_at": connector.retrieved_at(),
        }

    high = as_float(price_target.get("targetHigh"))
    mean = as_float(price_target.get("targetMean"))
    median = as_float(price_target.get("targetMedian"))
    low = as_float(price_target.get("targetLow"))
    analyst_count = as_float(price_target.get("numberAnalysts"))
    last_updated = price_target.get("lastUpdated")
    pt_age = age_days(last_updated, as_of=as_of)

    freshness = policy.get("freshness", {})
    quality = policy.get("quality", {})
    confidence_policy = policy.get("confidence", {})
    probability_policy = policy.get("probabilities", {})

    max_pt_age = int(freshness.get("price_target_max_age_days", 45))
    min_analysts = int(quality.get("minimum_equity_analyst_count", 3))

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

    latest_rec = recommendations[0] if recommendations else None
    rec_age = age_days((latest_rec or {}).get("period"), as_of=as_of)
    max_rec_age = int(freshness.get("recommendation_max_age_days", 45))
    rec_fresh = rec_age is not None and 0 <= rec_age <= max_rec_age

    prior = (
        float(probability_policy.get("prior_bull", 0.25)),
        float(probability_policy.get("prior_base", 0.50)),
        float(probability_policy.get("prior_bear", 0.25)),
    )
    probs = _recommendation_probabilities(
        latest_rec if rec_fresh else None,
        prior,
        float(probability_policy.get("max_recommendation_blend_weight", 0.50)),
    )

    latest_financial_period = latest_series_period(financials)
    fundamentals_age = age_days(latest_financial_period, as_of=as_of) if latest_financial_period else None
    fundamentals_fresh = (
        fundamentals_age is not None
        and 0 <= fundamentals_age <= int(freshness.get("fundamentals_max_period_age_days", 400))
        and bool(financials.get("metric"))
    )

    confidence = float(confidence_policy.get("base", 0.35))
    if pt_age is not None and 0 <= pt_age <= max_pt_age:
        confidence += float(confidence_policy.get("fresh_price_target_bonus", 0.20))
    if analyst_count:
        confidence += min(analyst_count / 20.0, 1.0) * float(confidence_policy.get("analyst_count_bonus_max", 0.15))
    if rec_fresh:
        confidence += float(confidence_policy.get("fresh_recommendation_bonus", 0.10))
    if fundamentals_fresh:
        confidence += float(confidence_policy.get("fundamentals_bonus", 0.10))
    confidence = min(confidence, 1.0)

    base_target = median if median is not None and median > 0 else mean
    if base_target is not None and mean is not None:
        # Keep the base scenario anchored to mean consensus while allowing median as a robustness check.
        base_target = 0.70 * mean + 0.30 * base_target

    valuation_status = "VALUATION_READY" if not blockers else "BLOCKED_BY_DATA"
    return {
        "underlying_ticker": ticker,
        "valuation_method": "FINNHUB_ANALYST_CONSENSUS_V1",
        "valuation_status": valuation_status,
        "valuation_confidence": round(confidence, 4) if not blockers else None,
        "bull_target_price": high if not blockers else None,
        "base_target_price": base_target if not blockers else None,
        "bear_target_price": low if not blockers else None,
        "bull_probability": probs[0] if not blockers else None,
        "base_probability": probs[1] if not blockers else None,
        "bear_probability": probs[2] if not blockers else None,
        "current_price": current_price,
        "analyst_count": analyst_count,
        "price_target_last_updated": last_updated,
        "price_target_age_days": pt_age,
        "recommendation_period": (latest_rec or {}).get("period"),
        "recommendation_age_days": rec_age,
        "latest_fundamental_period": latest_financial_period.isoformat() if latest_financial_period else None,
        "fundamentals_age_days": fundamentals_age,
        "blockers": blockers,
        "source_date": last_updated,
        "source_ref": "Finnhub /stock/price-target + /stock/recommendation + /stock/metric",
        "retrieved_at": connector.retrieved_at(),
    }
