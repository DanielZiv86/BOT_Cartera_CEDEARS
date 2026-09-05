from __future__ import annotations

from datetime import date
from typing import Any

from src.connectors.non_equity_tracker import NonEquityTrackerConnector, TrackerDataError
from src.valuation.common import age_days, normalized_probabilities


def build_non_equity_tracker_scenario(
    symbol: str,
    current_price: float | None,
    connector: NonEquityTrackerConnector,
    tracker_policy: dict[str, Any],
    as_of: date | None = None,
) -> dict[str, Any]:
    ticker = symbol.upper()
    cfg = (tracker_policy.get("trackers") or {}).get(ticker)
    if not isinstance(cfg, dict):
        return {
            "underlying_ticker": ticker,
            "valuation_method": "NON_EQUITY_TRACKER_NAV_STRESS_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": ["TRACKER_POLICY_NOT_CONFIGURED"],
            "source_ref": "config/non_equity_tracker_policy.yml",
            "retrieved_at": connector.retrieved_at(),
        }

    blockers: list[str] = []
    try:
        snap = connector.fetch(ticker)
    except TrackerDataError as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "NON_EQUITY_TRACKER_NAV_STRESS_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": [str(exc)],
            "source_ref": str(cfg.get("issuer_url") or "config/non_equity_tracker_policy.yml"),
            "retrieved_at": connector.retrieved_at(),
        }
    except Exception as exc:
        return {
            "underlying_ticker": ticker,
            "valuation_method": "NON_EQUITY_TRACKER_NAV_STRESS_V1",
            "valuation_status": "BLOCKED_BY_DATA",
            "valuation_confidence": None,
            "blockers": [f"ISSUER_DATA_ERROR:{type(exc).__name__}"],
            "source_ref": str(cfg.get("issuer_url") or "config/non_equity_tracker_policy.yml"),
            "retrieved_at": connector.retrieved_at(),
        }

    max_age = int(tracker_policy.get("max_issuer_nav_age_days", 10))
    nav_age = age_days(snap.nav_date, as_of=as_of)
    if snap.nav is None or snap.nav <= 0:
        blockers.append("ISSUER_NAV_MISSING_OR_INVALID")
    if nav_age is None:
        blockers.append("ISSUER_NAV_FRESHNESS_UNKNOWN")
    elif nav_age < 0 or nav_age > max_age:
        blockers.append("ISSUER_NAV_STALE")
    if current_price is None or current_price <= 0:
        blockers.append("CURRENT_PRICE_MISSING")

    scenarios = cfg.get("scenarios") or {}
    try:
        bull_r = float(scenarios["bull_return"])
        base_r = float(scenarios["base_return"])
        bear_r = float(scenarios["bear_return"])
        bull_p = float(scenarios["bull_probability"])
        base_p = float(scenarios["base_probability"])
        bear_p = float(scenarios["bear_probability"])
        annual_fee = float(cfg.get("annual_fee", 0.0))
        confidence = float(cfg.get("confidence", 0.50))
    except (KeyError, TypeError, ValueError):
        blockers.append("TRACKER_SCENARIO_POLICY_INVALID")
        bull_r = base_r = bear_r = 0.0
        bull_p, base_p, bear_p = 0.25, 0.50, 0.25
        annual_fee = 0.0
        confidence = 0.0

    if not (bear_r <= base_r <= bull_r):
        blockers.append("TRACKER_SCENARIO_ORDER_INVALID")
    probs = normalized_probabilities((bull_p, base_p, bear_p))

    # Targets are anchored to fresh issuer NAV rather than exchange price so any
    # current premium/discount is not silently carried into the 12m scenario.
    nav = float(snap.nav or 0.0)
    fee_drag = max(0.0, annual_fee)
    bull_target = nav * (1.0 + bull_r) * (1.0 - fee_drag)
    base_target = nav * (1.0 + base_r) * (1.0 - fee_drag)
    bear_target = nav * (1.0 + bear_r) * (1.0 - fee_drag)

    valuation_status = "VALUATION_READY" if not blockers else "BLOCKED_BY_DATA"
    return {
        "underlying_ticker": ticker,
        "valuation_method": "NON_EQUITY_TRACKER_NAV_STRESS_V1",
        "valuation_status": valuation_status,
        "valuation_confidence": round(confidence, 4) if not blockers else None,
        "bull_target_price": bull_target if not blockers else None,
        "base_target_price": base_target if not blockers else None,
        "bear_target_price": bear_target if not blockers else None,
        "bull_probability": probs[0] if not blockers else None,
        "base_probability": probs[1] if not blockers else None,
        "bear_probability": probs[2] if not blockers else None,
        "current_price": current_price,
        "issuer_nav": snap.nav,
        "issuer_nav_date": snap.nav_date,
        "issuer_nav_age_days": nav_age,
        "issuer_market_price": snap.market_price,
        "issuer_market_price_date": snap.market_price_date,
        "issuer_premium_discount_pct": snap.premium_discount_pct,
        "tracked_asset": cfg.get("asset"),
        "annual_fee": annual_fee,
        "scenario_bull_return_asset": bull_r,
        "scenario_base_return_asset": base_r,
        "scenario_bear_return_asset": bear_r,
        "scenario_policy_version": tracker_policy.get("version"),
        "scenario_policy_effective_date": tracker_policy.get("effective_date"),
        "blockers": blockers,
        "source_date": snap.nav_date,
        "source_ref": snap.source_ref,
        "source_tier": snap.source_tier,
        "source_provider": snap.provider,
        "retrieved_at": connector.retrieved_at(),
    }
